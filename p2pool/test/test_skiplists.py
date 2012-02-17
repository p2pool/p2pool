import random
import unittest

from p2pool import skiplists
from p2pool.util import forest
from p2pool.test.util import test_forest

class Test(unittest.TestCase):
    def test_all(self):
        t = forest.Tracker()
        d = skiplists.WeightsSkipList(t)
        for i in xrange(200):
            t.add(test_forest.FakeShare(hash=i, previous_hash=i - 1 if i > 0 else None, new_script=i, share_data=dict(donation=1234), target=2**249))
        for i in xrange(200):
            a = random.randrange(200)
            d(a, random.randrange(a + 1), 1000000*65535)[1]
