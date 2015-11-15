from twisted.internet import defer, reactor
from twisted.trial import unittest

from p2pool.bitcoin import data, networks, p2p
from p2pool.util import deferral


class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_get_block(self):
        factory = p2p.ClientFactory(networks.nets['bitcoin_regtest'])
        c = reactor.connectTCP('127.0.0.1', 18444, factory)
        try:
            h = 0x0f9188f13cb7b2c71f2a335e3a4fc328bf5beb436012afca590b1a11466e2206
            block = yield deferral.retry()(defer.inlineCallbacks(lambda: defer.returnValue((yield (yield factory.getProtocol()).get_block(h)))))()
            assert data.merkle_hash(map(data.hash256, map(data.tx_type.pack, block['txs']))) == block['header']['merkle_root']
            assert data.hash256(data.block_header_type.pack(block['header'])) == h
        finally:
            factory.stopTrying()
            c.disconnect()
