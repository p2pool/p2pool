import random
import unittest

from p2pool.util import bases

def generate_alphabet():
    if random.randrange(2):
        return None
    else:
        a = map(chr, xrange(256))
        random.shuffle(a)
        return a[:random.randrange(2, len(a))]

class Test(unittest.TestCase):
    def test_all(self):
        for i in xrange(10):
            alphabet = generate_alphabet()
            for i in xrange(100):
                n = random.randrange(100000000000000000000000000000)
                s = bases.natural_to_string(n, alphabet)
                n2 = bases.string_to_natural(s, alphabet)
                #print n, s.encode('hex'), n2
                assert n == n2
