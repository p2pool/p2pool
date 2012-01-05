from __future__ import absolute_import, division

import __builtin__
import math
import random

def median(x, use_float=True):
    # there exist better algorithms...
    y = sorted(x)
    if not y:
        raise ValueError('empty sequence!')
    left = (len(y) - 1)//2
    right = len(y)//2
    sum = y[left] + y[right]
    if use_float:
        return sum/2
    else:
        return sum//2

def mean(x):
    total = 0
    count = 0
    for y in x:
        total += y
        count += 1
    return total/count

def shuffled(x):
    x = list(x)
    random.shuffle(x)
    return x

def shift_left(n, m):
    # python: :(
    if m >= 0:
        return n << m
    return n >> -m

def clip(x, (low, high)):
    if x < low:
        return low
    elif x > high:
        return high
    else:
        return x

def nth(i, n=0):
    i = iter(i)
    for _ in xrange(n):
        i.next()
    return i.next()

def geometric(p):
    if p <= 0 or p > 1:
        raise ValueError('p must be in the interval (0.0, 1.0]')
    if p == 1:
        return 1
    return int(math.log1p(-random.random()) / math.log1p(-p)) + 1

def add_dicts(*dicts):
    res = {}
    for d in dicts:
        for k, v in d.iteritems():
            res[k] = res.get(k, 0) + v
    return dict((k, v) for k, v in res.iteritems() if v)

def format(x):
    prefixes = 'kMGTPEZY'
    count = 0
    while x >= 100000 and count < len(prefixes) - 2:
        x = x//1000
        count += 1
    s = '' if count == 0 else prefixes[count - 1]
    return '%i' % (x,) + s

def perfect_round(x):
    a, b = divmod(x, 1)
    a2 = int(a)
    if random.random() >= b:
        return a2
    else:
        return a2 + 1

def erf(x):
    # save the sign of x
    sign = 1
    if x < 0:
        sign = -1
    x = abs(x)
    
    # constants
    a1 =  0.254829592
    a2 = -0.284496736
    a3 =  1.421413741
    a4 = -1.453152027
    a5 =  1.061405429
    p  =  0.3275911
    
    # A&S formula 7.1.26
    t = 1.0/(1.0 + p*x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t*math.exp(-x*x)
    return sign*y # erf(-x) = -erf(x)

def ierf(z, steps=10):
    guess = 0
    for i in xrange(steps):
        d = 2*math.e**(-guess**2)/math.sqrt(math.pi)
        guess = guess - (erf(guess) - z)/d
    return guess

def binomial_conf_interval(x, n, conf=0.95):
    # approximate - Wilson score interval
    z = math.sqrt(2)*ierf(conf)
    p = x/n
    topa = p + z**2/2/n
    topb = z * math.sqrt(p*(1-p)/n + z**2/4/n**2)
    bottom = 1 + z**2/n
    return (topa - topb)/bottom, (topa + topb)/bottom

def interval_to_center_radius((low, high)):
    return (high+low)/2, (high-low)/2

def reversed(x):
    try:
        return __builtin__.reversed(x)
    except TypeError:
        return reversed(list(x))

class Object(object):
    def __init__(self, **kwargs):
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

def add_tuples(res, *tuples):
    for t in tuples:
        if len(t) != len(res):
            raise ValueError('tuples must all be the same length')
        res = tuple(a + b for a, b in zip(res, t))
    return res

def flatten_linked_list(x):
    while x is not None:
        x, cur = x
        yield cur

if __name__ == '__main__':
    import random
    a = 1
    while True:
        print a, format(a) + 'H/s'
        a = a * random.randrange(2, 5)
