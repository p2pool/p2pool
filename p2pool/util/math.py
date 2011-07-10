from __future__ import division

def median(x, use_float=True):
    # there exist better algorithms...
    y = sorted(x)
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
    if m < 0:
        return n >> -m
    return n << m

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
