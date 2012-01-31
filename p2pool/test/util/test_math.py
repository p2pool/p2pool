import random
import unittest

from p2pool.util import math

def generate_alphabet():
    if random.randrange(2):
        return None
    else:
        a = map(chr, xrange(256))
        random.shuffle(a)
        return a[:random.randrange(2, len(a))]

class Test(unittest.TestCase):
    def test_add_tuples(self):
        assert math.add_tuples((1, 2, 3), (4, 5, 6)) == (5, 7, 9)
    
    def test_bases(self):
        for i in xrange(10):
            alphabet = generate_alphabet()
            for i in xrange(100):
                n = random.randrange(100000000000000000000000000000)
                s = math.natural_to_string(n, alphabet)
                n2 = math.string_to_natural(s, alphabet)
                #print n, s.encode('hex'), n2
                self.assertEquals(n, n2)
