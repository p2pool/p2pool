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

perfect_round = lambda x: int(x + random.random())

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

def find_root(y_over_dy, start, steps=10, bounds=(None, None)):
    guess = start
    for i in xrange(steps):
        guess = guess - y_over_dy(guess)
        if bounds[0] is not None and guess < bounds[0]: guess = bounds[0]
        if bounds[1] is not None and guess > bounds[1]: guess = bounds[1]
    return guess

def ierf(z):
    return find_root(lambda x: (erf(x) - z)/(2*math.e**(-x**2)/math.sqrt(math.pi)), 0)

try:
    from scipy import special
except ImportError:
    print 'Install SciPy for more accurate confidence intervals!'
    def binomial_conf_interval(x, n, conf=0.95):
        if n == 0:
            return (1-conf)/2, 1-(1-conf)/2
        # approximate - Wilson score interval
        z = math.sqrt(2)*ierf(conf)
        p = x/n
        topa = p + z**2/2/n
        topb = z * math.sqrt(p*(1-p)/n + z**2/4/n**2)
        bottom = 1 + z**2/n
        return (topa - topb)/bottom, (topa + topb)/bottom
else:
    def binomial_conf_interval(x, n, conf=0.95):
        if n == 0:
            left = random.random()*(1 - conf)
            return left, left + conf
        dkpdf = lambda p: ((x*p**(x-1) * (1-p)**(n-x) - p**x * (n-x)*(1-p)**(n-x-1)) \
            if p != 0 else {0: -n, 1: 1}.get(x, 0)*special.beta(x+1, n-x+1)) \
            if p != 1 else {n-1: -1, n: n}.get(x, 0)*special.beta(x+1, n-x+1)
        def f(left):
            right = special.betaincinv(x+1, n-x+1, special.betainc(x+1, n-x+1, left) + conf)
            l_pdf, r_pdf = left**x*(1-left)**(n-x), right**x*(1-right)**(n-x)
            return (r_pdf - l_pdf)*r_pdf/(dkpdf(right)*l_pdf - dkpdf(left)*r_pdf)
        left_max = special.betaincinv(x+1, n-x+1, 1 - conf)
        left = find_root(f, left_max/2, 8, (0, left_max))
        return left, special.betaincinv(x+1, n-x+1, special.betainc(x+1, n-x+1, left) + conf)

def binomial_conf_center_radius(x, n, conf=0.95):
    left, right = binomial_conf_interval(x, n, conf)
    if n == 0:
        return (left+right)/2, (right-left)/2
    p = x/n
    return p, max(p - left, right - p)

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

def weighted_choice(choices):
    choices = list((item, weight) for item, weight in choices)
    target = random.randrange(sum(weight for item, weight in choices))
    for item, weight in choices:
        if weight > target:
            return item
        target -= weight
    raise AssertionError()

if __name__ == '__main__':
    import random
    a = 1
    while True:
        print a, format(a) + 'H/s'
        a = a * random.randrange(2, 5)
