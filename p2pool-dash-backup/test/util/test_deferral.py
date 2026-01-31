import random
import time

from twisted.internet import defer
from twisted.trial import unittest

from p2pool.util import deferral

class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_sleep(self):
        for i in xrange(10):
            length = random.expovariate(1/0.1)
            start = time.time()
            yield deferral.sleep(length)
            end = time.time()
            assert length <= end - start <= length + 0.1
