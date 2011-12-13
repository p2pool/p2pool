class frozendict(dict):
    __slots__ = ['_hash']
    
    def __hash__(self):
        rval = getattr(self, '_hash', None)
        if rval is None:
            rval = self._hash = hash(frozenset(self.iteritems()))
        return rval

class frozenlist(list):
    __slots__ = ['_hash']
    
    def __hash__(self):
        rval = getattr(self, '_hash', None)
        if rval is None:
            rval = self._hash = hash(tuple(self))
        return rval

def immutify(x):
    if isinstance(x, list):
        return frozenlist(immutify(y) for y in x)
    elif isinstance(x, dict):
        return frozendict((immutify(k), immutify(v)) for k, v in x.iteritems())
    else:
        hash(x) # will throw error if not immutable
        return x
