import random

from twisted.internet import defer, endpoints, protocol, reactor
from twisted.trial import unittest

from p2pool import networks, p2p
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral


class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_sharereq(self):
        class MyNode(p2p.Node):
            def __init__(self, df):
                p2p.Node.__init__(self, lambda: None, 29333, networks.nets['bitcoin'], {}, set([('127.0.0.1', 9333)]), 0, 0, 0, 0)
                
                self.df = df
            
            def handle_share_hashes(self, hashes, peer):
                peer.get_shares(
                    hashes=[hashes[0]],
                    parents=5,
                    stops=[],
                ).chainDeferred(self.df)
        
        df = defer.Deferred()
        n = MyNode(df)
        n.start()
        try:
            yield df
        finally:
            yield n.stop()
    
    @defer.inlineCallbacks
    def test_tx_limit(self):
        class MyNode(p2p.Node):
            def __init__(self, df):
                p2p.Node.__init__(self, lambda: None, 29333, networks.nets['bitcoin'], {}, set([('127.0.0.1', 9333)]), 0, 0, 0, 0)
                
                self.df = df
                self.sent_time = 0
            
            @defer.inlineCallbacks
            def got_conn(self, conn):
                p2p.Node.got_conn(self, conn)
                
                yield deferral.sleep(.5)
                
                new_mining_txs = dict(self.mining_txs_var.value)
                for i in xrange(3):
                    huge_tx = dict(
                        version=0,
                        tx_ins=[],
                        tx_outs=[dict(
                            value=0,
                            script='x'*900000,
                        )],
                        lock_time=i,
                    )
                    new_mining_txs[bitcoin_data.hash256(bitcoin_data.tx_type.pack(huge_tx))] = huge_tx
                self.mining_txs_var.set(new_mining_txs)
                
                self.sent_time = reactor.seconds()
            
            def lost_conn(self, conn, reason):
                self.df.callback(None)
        try:
            p2p.Protocol.max_remembered_txs_size *= 10
            
            df = defer.Deferred()
            n = MyNode(df)
            n.start()
            yield df
            if not (n.sent_time <= reactor.seconds() <= n.sent_time + 1):
                raise ValueError('node did not disconnect within 1 seconds of receiving too much tx data')
            yield n.stop()
        finally:
            p2p.Protocol.max_remembered_txs_size //= 10
