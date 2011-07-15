_nothing = object()

def memoize_with_backing(backing, inverse_of=None):
    def a(f):
        def b(*args):
            res = backing.get((f, args), _nothing)
            if res is not _nothing:
                return res
            
            res = f(*args)
            
            backing[(f, args)] = res
            if inverse_of is not None:
                if len(args) != 1:
                    raise ValueError('inverse_of can only be used for functions taking one argument')
                backing[(inverse_of, (res,))] = args[0]
            
            return res
        return b
    return a
