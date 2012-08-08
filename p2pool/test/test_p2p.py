import random

from twisted.internet import defer
from twisted.trial import unittest

from p2pool import networks, p2p

class MyNode(p2p.Node):
    def __init__(self, df):
        p2p.Node.__init__(self, lambda: None, 29333, networks.nets['bitcoin'], {}, set([('127.0.0.1', 9333)]), 0, 0, 0, 0)
        
        self.id_to_use = random.randrange(2**256)
        self.df = df
    
    def handle_share_hashes(self, hashes, peer):
        peer.get_shares(
            hashes=[hashes[0]],
            parents=5,
            stops=[],
        ).chainDeferred(self.df)

class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_sharereq(self):
        df = defer.Deferred()
        n = MyNode(df)
        n.start()
        try:
            yield df
        finally:
            yield n.stop()
