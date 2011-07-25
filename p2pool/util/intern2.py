import weakref

_weak_backing = weakref.WeakKeyDictionary()
_backing = {}

def intern2(obj):
    if isinstance(obj, str):
        return intern(obj)
    
    if obj in _backing:
        return _backing[obj]
    if obj in _weak_backing:
        return _weak_backing[obj]
    
    if hasattr(obj, '__dict__'):
        for key in obj.__dict__:
            obj.__dict__[key] = recursive_intern2(obj.__dict__[key])
    if isinstance(obj, tuple):
        obj = tuple(recursive_intern2(x) for x in obj)
    
    try:
        weakref.ref(obj)
    except TypeError:
        _backing[obj] = obj
    else:
        _weak_backing[obj] = obj
    return obj

if __name__ == '__main__':
    a = 2**256*100
    b = intern2(a)
    c = 2**256*100
    d = intern2(c)
    print id(a), id(b)
    print id(c), id(d)
