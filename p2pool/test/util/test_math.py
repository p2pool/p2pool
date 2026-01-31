from __future__ import division

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
                n = random.choice([
                    random.randrange(3),
                    random.randrange(300),
                    random.randrange(100000000000000000000000000000),
                ])
                s = math.natural_to_string(n, alphabet)
                n2 = math.string_to_natural(s, alphabet)
                #print n, s.encode('hex'), n2
                self.assertEquals(n, n2)
    
    def test_binom(self):
        for n in xrange(1, 100):
            for x in xrange(n + 1):
                left, right = math.binomial_conf_interval(x, n)
                assert 0 <= left <= x/n <= right <= 1, (left, right, x, n)

    def test_convertbits(self):
        self.assertListEqual([0], math.convertbits([0], 8, 16, True))
        self.assertEqual(None, math.convertbits([0], 8, 16, False))
        self.assertListEqual([0], math.convertbits([0, 0], 8, 16, False))
        self.assertListEqual([0, 0], math.convertbits([0], 16, 8, False))
        self.assertListEqual([255], math.convertbits([0, 255], 8, 16, False))
        self.assertListEqual([65280], math.convertbits([255], 8, 16, True))
        self.assertListEqual([65535], math.convertbits([255, 255], 8, 16, True))
        self.assertListEqual([0, 255], math.convertbits([255], 16, 8, False))
        self.assertListEqual([255, 0], math.convertbits([65280], 16, 8, False))
        self.assertListEqual([255, 255], math.convertbits([65535], 16, 8, False))
        self.assertListEqual([4, 11, 13, 2, 16], math.convertbits([34, 218, 40], 8, 5, True))
        self.assertListEqual([34, 218, 40, 0], math.convertbits([4, 11, 13, 2, 16], 5, 8, True))
        self.assertListEqual([34, 218, 40], math.convertbits([4, 11, 13, 2, 16], 5, 8, False))
        self.assertListEqual([3, 82, 34, 218, 40], math.convertbits([0, 13, 9, 2, 5, 22, 17, 8], 5, 8, True))
        self.assertListEqual([3, 82, 34, 218, 40], math.convertbits([0, 13, 9, 2, 5, 22, 17, 8], 5, 8, False))
        self.assertListEqual([0, 13, 9, 2, 5, 22, 17, 8], math.convertbits([3, 82, 34, 218, 40], 8, 5, True))
        self.assertListEqual([0, 13, 9, 2, 5, 22, 17, 8], math.convertbits([3, 82, 34, 218, 40], 8, 5, False))
