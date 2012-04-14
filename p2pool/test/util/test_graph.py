import unittest

from p2pool.util import graph

class Test(unittest.TestCase):
    def test_combine_and_keep_largest(self):
        f = graph.combine_and_keep_largest(3, 'squashed')
        a, b = dict(a=1, b=2, c=3, d=4, e=5), dict(a=1, b=3, c=5, d=7, e=9)
        res = f(a, b)
        assert res == {'squashed': 15, 'e': 14, 'd': 11}
        assert f(res, dict(squashed=100)) == {'squashed': 115, 'e': 14, 'd': 11}
