import itertools

class LRUDict(object):
    def __init__(self, n):
        self.n = n
        self.inner = {}
        self.counter = itertools.count()
    def get(self, key, default=None):
        if key in self.inner:
            x, value = self.inner[key]
            self.inner[key] = self.counter.next(), value
            return value
        return default
    def __setitem__(self, key, value):
        self.inner[key] = self.counter.next(), value
        while len(self.inner) > self.n:
            self.inner.pop(min(self.inner, key=lambda k: self.inner[k][0]))

_nothing = object()

def memoize_with_backing(backing, has_inverses=set()):
    def a(f):
        def b(*args):
            res = backing.get((f, args), _nothing)
            if res is not _nothing:
                return res
            
            res = f(*args)
            
            backing[(f, args)] = res
            for inverse in has_inverses:
                backing[(inverse, args[:-1] + (res,))] = args[-1]
            
            return res
        return b
    return a

def memoize(f):
    return memoize_with_backing({})(f)


class cdict(dict):
    def __init__(self, func):
        dict.__init__(self)
        self._func = func
    
    def __missing__(self, key):
        value = self._func(key)
        self[key] = value
        return value

def fast_memoize_single_arg(func):
    return cdict(func).__getitem__

class cdict2(dict):
    def __init__(self, func):
        dict.__init__(self)
        self._func = func
    
    def __missing__(self, key):
        value = self._func(*key)
        self[key] = value
        return value

def fast_memoize_multiple_args(func):
    f = cdict2(func).__getitem__
    return lambda *args: f(args)
