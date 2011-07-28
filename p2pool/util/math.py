from __future__ import absolute_import, division

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

def add_dicts(dicts):
    res = {}
    for d in dicts:
        for k, v in d.iteritems():
            res[k] = res.get(k, 0) + v
    return dict((k, v) for k, v in res.iteritems() if v)

def format(x):
    prefixes = 'kMGTPEZY'
    count = 0
    while x >= 10000 and count < len(prefixes) - 2:
        x = x//1000
        count += 1
    s = '' if count == 0 else prefixes[count - 1]
    return '%i' % (x,) + s

if __name__ == '__main__':
    import random
    a = 1
    while True:
        print a, format(a) + 'H/s'
        a = a * random.randrange(2, 5)
