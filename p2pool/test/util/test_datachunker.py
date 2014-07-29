import random
import unittest

from p2pool.util import datachunker

def random_bytes(length):
    return ''.join(chr(random.randrange(2**8)) for i in xrange(length))

class Test(unittest.TestCase):
    def test_stringbuffer(self):
        for i in xrange(100):
            sb = datachunker.StringBuffer()
            
            r = random_bytes(random.randrange(1000))
            
            amount_inserted = 0
            while amount_inserted < len(r):
                x = random.randrange(10)
                sb.add(r[amount_inserted:amount_inserted+x])
                amount_inserted += x
            
            amount_removed = 0
            while amount_removed < len(r):
                x = random.randrange(min(10, len(r) - amount_removed) + 1)
                this = sb.get(x)
                assert r[amount_removed:amount_removed+x] == this
                amount_removed += x
