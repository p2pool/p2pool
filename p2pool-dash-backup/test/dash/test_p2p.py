from twisted.internet import defer, reactor
from twisted.trial import unittest

from p2pool.dash import data, networks, p2p
from p2pool.util import deferral


class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_get_block(self):
        factory = p2p.ClientFactory(networks.nets['dash'])
        c = reactor.connectTCP('127.0.0.1', 9999, factory)
        try:
            h = 0x00000000000132b9afeca5e9a2fdf4477338df6dcff1342300240bc70397c4bb
            block = yield deferral.retry()(defer.inlineCallbacks(lambda: defer.returnValue((yield (yield factory.getProtocol()).get_block(h)))))()
            assert data.merkle_hash(map(data.hash256, map(data.tx_type.pack, block['txs']))) == block['header']['merkle_root']
            assert data.hash256(data.block_header_type.pack(block['header'])) == h
        finally:
            factory.stopTrying()
            c.disconnect()
