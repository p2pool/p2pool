from __future__ import division

import math

class Vector(tuple):
    for name, operator in [("neg", "-%s"), ("pos", "+%s"), ("abs", "abs(%s)")]:
        exec("def __%s__(self): return Vector(%s for x in self)" % (name, operator % "x"))
    
    for name, operator in [
        ("add", "%s+%s"), ("sub", "%s-%s"), ("mul", "%s*%s"), ("truediv", "%s/%s"), ("floordiv", "%s//%s"),
        ("call", "%s(%s)"),
    ]:
        exec("""def __%s__(self, other):
        try:
            return %s(%s for x, y in zip(self, other))
        except:
            return Vector(%s for x in self)""" % (name, "sum" if name == "mul" else "Vector", operator % ("x", "y"), operator % ("x", "other")))
        exec("""def __r%s__(self, other):
        try:
            return %s(%s for x, y in zip(self, other))
        except:
            return Vector(%s for x in self)""" % (name, "sum" if name == "mul" else "Vector", operator % ("y", "x"), operator % ("other", "x")))
    
    def __mod__((x, y, z), (X, Y, Z)):
        return Vector([y*Z-z*Y, z*X-x*Z, x*Y-y*X])
    
    def __rmod__((X, Y, Z), (x, y, z)):
        return Vector([y*Z-z*Y, z*X-x*Z, x*Y-y*X])
    
    def __repr__(self):
        return 'v%s' % tuple.__repr__(self)
    
    def __getitem__(self, item):
        if isinstance(item, slice):
            return Vector(tuple.__getitem__(self, item))
        else:
            return tuple.__getitem__(self, item)
    
    def __getslice__(self, i, j):
        return self.__getitem__(slice(i, j))
    
    def mag(self):
        return math.sqrt(self*self)
    
    def unit(self):
        m = self.mag()
        if m == 0:
            return self
        return (1/m)*self
    
    @property
    def rounded(self):
        return Vector(int(x + .5) for x in self)
    
    @property
    def truncated(self):
        return Vector(int(x) for x in self)

def v(*args):
    return Vector(args)
