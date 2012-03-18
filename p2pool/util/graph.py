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

class DataView(object):
    def __init__(self, desc, ds_desc, last_bin_end, bins):
        assert len(bins) == desc.bin_count
        
        self.desc = desc
        self.ds_desc = ds_desc
        self.last_bin_end = last_bin_end
        self.bins = bins
    
    def _add_datum(self, t, value):
        shift = max(0, int(math.ceil((t - self.last_bin_end)/self.desc.bin_width)))
        self.bins = _shift(self.bins, shift, (0, 0))
        self.last_bin_end += shift*self.desc.bin_width
        
        bin = int(math.ceil((self.last_bin_end - self.desc.bin_width - t)/self.desc.bin_width))
        
        if bin >= self.desc.bin_count:
            return
        
        prev_total, prev_count = self.bins[bin]
        self.bins[bin] = prev_total + value, prev_count + 1
    
    def get_data(self, t):
        shift = max(0, int(math.ceil((t - self.last_bin_end)/self.desc.bin_width)))
        bins = _shift(self.bins, shift, (0, 0))
        last_bin_end = self.last_bin_end + shift*self.desc.bin_width
        
        assert last_bin_end - self.desc.bin_width <= t <= last_bin_end
        
        return [(
            (min(t, last_bin_end - self.desc.bin_width*i) + (last_bin_end - self.desc.bin_width*(i + 1)))/2, # center time
            (total/count if count else None) if self.ds_desc.source_is_cumulative
                else total/(min(t, last_bin_end - self.desc.bin_width*i) - (last_bin_end - self.desc.bin_width*(i + 1))), # value
            min(t, last_bin_end - self.desc.bin_width*i) - (last_bin_end - self.desc.bin_width*(i + 1)), # width
        ) for i, (total, count) in enumerate(bins)]


class DataStreamDescription(object):
    def __init__(self, source_is_cumulative, dataview_descriptions):
        self.source_is_cumulative = source_is_cumulative
        self.dataview_descriptions = dataview_descriptions

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
        def get_dataview(ds_name, ds_desc, dv_name, dv_desc):
            if ds_name in obj:
                ds_data = obj[ds_name]
                if dv_name in ds_data:
                    dv_data = ds_data[dv_name]
                    if dv_data['bin_width'] == dv_desc.bin_width and len(dv_data['bins']) == dv_desc.bin_count:
                        return DataView(dv_desc, ds_desc, dv_data['last_bin_end'], dv_data['bins'])
            return DataView(dv_desc, ds_desc, 0, dv_desc.bin_count*[(0, 0)])
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
