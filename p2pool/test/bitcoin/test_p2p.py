from twisted.internet import defer, reactor
from twisted.trial import unittest

from p2pool.bitcoin import data, networks, p2p
from p2pool.util import deferral


class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_get_block(self):
        factory = p2p.ClientFactory(networks.nets['bitcoin'])
        c = reactor.connectTCP('127.0.0.1', 8333, factory)
        try:
            h = 0x000000000000046acff93b0e76cd10490551bf871ce9ac9fad62e67a07ff1d1e
            block = yield deferral.retry()(defer.inlineCallbacks(lambda: defer.returnValue((yield (yield factory.getProtocol()).get_block(h)))))()
            assert data.merkle_hash(map(data.get_txid, block['txs'])) == block['header']['merkle_root']
            assert data.hash256(data.block_header_type.pack(block['header'])) == h
        finally:
            factory.stopTrying()
            c.disconnect()
