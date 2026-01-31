from twisted.internet import defer
from twisted.trial import unittest

from p2pool.util import deferral, expiring_dict

class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_expiring_dict1(self):
        e = expiring_dict.ExpiringDict(3, get_touches=True)
        e[1] = 2
        yield deferral.sleep(1.5)
        assert 1 in e
        yield deferral.sleep(3)
        assert 1 not in e
    
    @defer.inlineCallbacks
    def test_expiring_dict2(self):
        e = expiring_dict.ExpiringDict(3, get_touches=True)
        e[1] = 2
        yield deferral.sleep(2.25)
        e[1]
        yield deferral.sleep(2.25)
        assert 1 in e
    
    @defer.inlineCallbacks
    def test_expiring_dict3(self):
        e = expiring_dict.ExpiringDict(3, get_touches=False)
        e[1] = 2
        yield deferral.sleep(2.25)
        e[1]
        yield deferral.sleep(2.25)
        assert 1 not in e
