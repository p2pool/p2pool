import unittest

from p2pool.util import graph

class Test(unittest.TestCase):
    def test_keep_largest(self):
        b = dict(a=1, b=3, c=5, d=7, e=9)
        assert graph.keep_largest(3, 'squashed')(b) == {'squashed': 9, 'd': 7, 'e': 9}
        assert graph.keep_largest(3)(b) == {'c': 5, 'd': 7, 'e': 9}
