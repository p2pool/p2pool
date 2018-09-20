import unittest

from p2pool.util import pack

class Test(unittest.TestCase):
    def test_VarInt(self):
        t = pack.VarIntType()
        for i in range(2**20):
            assert t.unpack(t.pack(i)) == i
        for i in range(2**36, 2**36+25):
            assert t.unpack(t.pack(i)) == i
