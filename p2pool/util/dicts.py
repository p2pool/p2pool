class DictWrapper(object):
    def encode_key(self, key):
        return key
    def decode_key(self, encoded_key):
        return encoded_key
    def encode_value(self, value):
        return value
    def decode_value(self, encoded_value):
        return encoded_value
    
    def __init__(self, inner):
        self.inner = inner
    
    def __len__(self):
        return len(self.inner)
    
    def __contains__(self, key):
        return self.encode_key(key) in self.inner
    
    def __getitem__(self, key):
        return self.decode_value(self.inner[self.encode_key(key)])
    def __setitem__(self, key, value):
        self.inner[self.encode_key(key)] = self.encode_value(value)
    def __delitem__(self, key):
        del self.inner[self.encode_key(key)]
    
    def __iter__(self):
        for encoded_key in self.inner:
            yield self.decode_key(encoded_key)
    def iterkeys(self):
        return iter(self)
    def keys(self):
        return list(self.iterkeys())
    
    def itervalue(self):
        for encoded_value in self.inner.itervalues():
            yield self.decode_value(encoded_value)
    def values(self):
        return list(self.itervalue())
    
    def iteritems(self):
        for key, value in self.inner.iteritems():
            yield self.decode_key(key), self.decode_value(value)
    def items(self):
        return list(self.iteritems())

def update_dict(d, **replace):
    d = d.copy()
    for k, v in replace.iteritems():
        if v is None:
            del d[k]
        else:
            d[k] = v
    return d
