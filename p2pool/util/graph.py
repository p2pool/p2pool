from __future__ import absolute_import
from __future__ import division

import math

from p2pool.util import math as math2


class DataViewDescription(object):
    def __init__(self, bin_count, total_width):
        self.bin_count = bin_count
        self.bin_width = total_width/bin_count

def _shift(x, shift, pad_item):
    left_pad = math2.clip(shift, (0, len(x)))
    right_pad = math2.clip(-shift, (0, len(x)))
    return [pad_item]*left_pad + x[right_pad:-left_pad if left_pad else None] + [pad_item]*right_pad

combine_bins = math2.add_dicts_ext(lambda (a1, b1), (a2, b2): (a1+a2, b1+b2), (0, 0))

nothing = object()
def keep_largest(n, squash_key=nothing, key=lambda x: x, add_func=lambda a, b: a+b):
    def _(d):
        items = sorted(d.iteritems(), key=lambda (k, v): (k != squash_key, key(v)), reverse=True)
        while len(items) > n:
            k, v = items.pop()
            if squash_key is not nothing:
                items[-1] = squash_key, add_func(items[-1][1], v)
        return dict(items)
    return _

def _shift_bins_so_t_is_not_past_end(bins, last_bin_end, bin_width, t):
    # returns new_bins, new_last_bin_end
    shift = max(0, int(math.ceil((t - last_bin_end)/bin_width)))
    return _shift(bins, shift, {}), last_bin_end + shift*bin_width

class DataView(object):
    def __init__(self, desc, ds_desc, last_bin_end, bins):
        assert len(bins) == desc.bin_count
        
        self.desc = desc
        self.ds_desc = ds_desc
        self.last_bin_end = last_bin_end
        self.bins = bins
    
    def _add_datum(self, t, value):
        if not self.ds_desc.multivalues:
            value = {'null': value}
        elif self.ds_desc.multivalue_undefined_means_0 and 'null' not in value:
            value = dict(value, null=0) # use null to hold sample counter
        self.bins, self.last_bin_end = _shift_bins_so_t_is_not_past_end(self.bins, self.last_bin_end, self.desc.bin_width, t)
        
        bin = int(math.floor((self.last_bin_end - t)/self.desc.bin_width))
        assert bin >= 0
        if bin < self.desc.bin_count:
            self.bins[bin] = self.ds_desc.keep_largest_func(combine_bins(self.bins[bin], dict((k, (v, 1)) for k, v in value.iteritems())))
    
    def get_data(self, t):
        bins, last_bin_end = _shift_bins_so_t_is_not_past_end(self.bins, self.last_bin_end, self.desc.bin_width, t)
        assert last_bin_end - self.desc.bin_width <= t <= last_bin_end
        
        def _((i, bin)):
            left, right = last_bin_end - self.desc.bin_width*(i + 1), min(t, last_bin_end - self.desc.bin_width*i)
            center, width = (left+right)/2, right-left
            if self.ds_desc.is_gauge and self.ds_desc.multivalue_undefined_means_0:
                real_count = max([0] + [count for total, count in bin.itervalues()])
                if real_count == 0:
                    val = None
                else:
                    val = dict((k, total/real_count) for k, (total, count) in bin.iteritems())
                default = 0
            elif self.ds_desc.is_gauge and not self.ds_desc.multivalue_undefined_means_0:
                val = dict((k, total/count) for k, (total, count) in bin.iteritems())
                default = None
            else:
                val = dict((k, total/width) for k, (total, count) in bin.iteritems())
                default = 0
            if not self.ds_desc.multivalues:
                val = None if val is None else val.get('null', default)
            return center, val, width, default
        return map(_, enumerate(bins))


class DataStreamDescription(object):
    def __init__(self, dataview_descriptions, is_gauge=True, multivalues=False, multivalues_keep=20, multivalues_squash_key=None, multivalue_undefined_means_0=False, default_func=None):
        self.dataview_descriptions = dataview_descriptions
        self.is_gauge = is_gauge
        self.multivalues = multivalues
        self.keep_largest_func = keep_largest(multivalues_keep, multivalues_squash_key, key=lambda (t, c): t/c if self.is_gauge else t, add_func=lambda (a1, b1), (a2, b2): (a1+a2, b1+b2))
        self.multivalue_undefined_means_0 = multivalue_undefined_means_0
        self.default_func = default_func

class DataStream(object):
    def __init__(self, desc, dataviews):
        self.desc = desc
        self.dataviews = dataviews
    
    def add_datum(self, t, value=1):
        for dv_name, dv in self.dataviews.iteritems():
            dv._add_datum(t, value)


class HistoryDatabase(object):
    @classmethod
    def from_obj(cls, datastream_descriptions, obj={}):
        def convert_bin(bin):
            if isinstance(bin, dict):
                return bin
            total, count = bin
            if not isinstance(total, dict):
                total = {'null': total}
            return dict((k, (v, count)) for k, v in total.iteritems()) if count else {}
        def get_dataview(ds_name, ds_desc, dv_name, dv_desc):
            if ds_name in obj:
                ds_data = obj[ds_name]
                if dv_name in ds_data:
                    dv_data = ds_data[dv_name]
                    if dv_data['bin_width'] == dv_desc.bin_width and len(dv_data['bins']) == dv_desc.bin_count:
                        return DataView(dv_desc, ds_desc, dv_data['last_bin_end'], map(convert_bin, dv_data['bins']))
            elif ds_desc.default_func is None:
                return DataView(dv_desc, ds_desc, 0, dv_desc.bin_count*[{}])
            else:
                return ds_desc.default_func(ds_name, ds_desc, dv_name, dv_desc, obj)
        return cls(dict(
            (ds_name, DataStream(ds_desc, dict(
                (dv_name, get_dataview(ds_name, ds_desc, dv_name, dv_desc))
                for dv_name, dv_desc in ds_desc.dataview_descriptions.iteritems()
            )))
            for ds_name, ds_desc in datastream_descriptions.iteritems()
        ))
    
    def __init__(self, datastreams):
        self.datastreams = datastreams
    
    def to_obj(self):
        return dict((ds_name, dict((dv_name, dict(last_bin_end=dv.last_bin_end, bin_width=dv.desc.bin_width, bins=dv.bins))
            for dv_name, dv in ds.dataviews.iteritems())) for ds_name, ds in self.datastreams.iteritems())


def make_multivalue_migrator(multivalue_keys, post_func=lambda bins: bins):
    def _(ds_name, ds_desc, dv_name, dv_desc, obj):
        if not obj:
            last_bin_end = 0
            bins = dv_desc.bin_count*[{}]
        else:
            inputs = dict((k, obj.get(v, {dv_name: dict(bins=[{}]*dv_desc.bin_count, last_bin_end=0)})[dv_name]) for k, v in multivalue_keys.iteritems())
            last_bin_end = max(inp['last_bin_end'] for inp in inputs.itervalues()) if inputs else 0
            assert all(len(inp['bins']) == dv_desc.bin_count for inp in inputs.itervalues())
            inputs = dict((k, dict(zip(['bins', 'last_bin_end'], _shift_bins_so_t_is_not_past_end(v['bins'], v['last_bin_end'], dv_desc.bin_width, last_bin_end)))) for k, v in inputs.iteritems())
            assert len(set(inp['last_bin_end'] for inp in inputs.itervalues())) <= 1
            bins = post_func([dict((k, v['bins'][i]['null']) for k, v in inputs.iteritems() if 'null' in v['bins'][i]) for i in xrange(dv_desc.bin_count)])
        return DataView(dv_desc, ds_desc, last_bin_end, bins)
    return _
