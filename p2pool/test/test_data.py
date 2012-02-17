import random
import unittest

from p2pool import data
from p2pool.bitcoin import data as bitcoin_data

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
