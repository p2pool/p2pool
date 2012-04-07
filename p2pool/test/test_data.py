import random
import unittest

from p2pool import data
from p2pool.bitcoin import data as bitcoin_data
from p2pool.test.util import test_forest
from p2pool.util import forest

def random_bytes(length):
    return ''.join(chr(random.randrange(2**8)) for i in xrange(length))

class Test(unittest.TestCase):
    def test_hashlink1(self):
        for i in xrange(100):
            d = random_bytes(random.randrange(2048))
            x = data.prefix_to_hash_link(d)
            assert data.check_hash_link(x, '') == bitcoin_data.hash256(d)
    
    def test_hashlink2(self):
        for i in xrange(100):
            d = random_bytes(random.randrange(2048))
            d2 = random_bytes(random.randrange(2048))
            x = data.prefix_to_hash_link(d)
            assert data.check_hash_link(x, d2) == bitcoin_data.hash256(d + d2)
    
    def test_hashlink3(self):
        for i in xrange(100):
            d = random_bytes(random.randrange(2048))
            d2 = random_bytes(random.randrange(200))
            d3 = random_bytes(random.randrange(2048))
            x = data.prefix_to_hash_link(d + d2, d2)
            assert data.check_hash_link(x, d3, d2) == bitcoin_data.hash256(d + d2 + d3)
    
    def test_skiplist(self):
        t = forest.Tracker()
        d = data.WeightsSkipList(t)
        for i in xrange(200):
            t.add(test_forest.FakeShare(hash=i, previous_hash=i - 1 if i > 0 else None, new_script=i, share_data=dict(donation=1234), target=2**249))
        for i in xrange(200):
            a = random.randrange(200)
            d(a, random.randrange(a + 1), 1000000*65535)[1]
