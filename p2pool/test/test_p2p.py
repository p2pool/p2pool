import random

from twisted.internet import defer, reactor
from twisted.trial import unittest

from p2pool import data, networks, p2p
from p2pool.util import deferral

class MyNode(p2p.Node):
    def handle_share_hashes(self, hashes, peer):
        peer.send_sharereq(id=random.randrange(2**256), hashes=[hashes[0]], parents=5, stops=[])
        print 'handle_share_hashes', (hashes, peer)
    
    def handle_share_reply(self, id, result, shares, peer):
        print (id, result, shares)

class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_sharereq(self):
        n = MyNode(lambda: None, 29333, networks.nets['bitcoin'], {}, set([('127.0.0.1', 9333)]), 0, 0, 0, 0)
        n.start()
        try:
            yield deferral.sleep(10)
        finally:
            n.stop()
