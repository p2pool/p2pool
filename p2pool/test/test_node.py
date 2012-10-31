from twisted.internet import defer
from twisted.trial import unittest

from p2pool import networks, node, work
from p2pool.util import deferral, variable

class factory(object):
    new_headers = variable.Event()
    new_block = variable.Event()
    new_tx = variable.Event()
    conn = variable.Variable(None)
    @classmethod
    def getProtocol(self):
        return defer.Deferred()

class bitcoind(object):
    @classmethod
    def rpc_help(self):
        return '\ngetblock '
    
    @classmethod
    def rpc_getblock(self, block_hash_hex):
        return dict(height=42)
    
    @classmethod
    def rpc_getmemorypool(self):
        return {
            "version" : 2,
            "previousblockhash" : "000000000000016c169477c25421250ec5d32cf9c6d38538b5de970a2355fd89",
            "transactions" : [
            ],
            "coinbaseaux" : {
                "flags" : "062f503253482f"
            },
            "coinbasevalue" : 5044450000,
            "target" : "0000000000000513c50000000000000000000000000000000000000000000000",
            "mintime" : 1351655621,
            "mutable" : [
                "time",
                "transactions",
                "prevblock"
            ],
            "noncerange" : "00000000ffffffff",
            "sigoplimit" : 20000,
            "sizelimit" : 1000000,
            "curtime" : 1351659940,
            "bits" : "1a0513c5",
            "height" : 205801
        }

class FakeRequest(object):
    def getUser(self):
        return 'fakeuser'
    def getClientIP(self):
        return 'fakeclientip'

class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_node(self):
        net = networks.nets['litecoin_testnet']
        n = node.Node(factory, bitcoind, [], [], net)
        yield n.start()
        
        wb = work.WorkerBridge(node=n, my_pubkey_hash=42, donation_percentage=2, merged_urls=[], worker_fee=3)
        
        yield deferral.sleep(3)
        
        for i in xrange(100):
            ba, got_resp = wb.get_work(pubkey_hash=4242, desired_share_target=2**256-1, desired_pseudoshare_target=2**256-1)
            got_resp(dict(version=ba.version, previous_block=ba.previous_block, merkle_root=ba.merkle_root, timestamp=ba.timestamp, bits=ba.bits, nonce=42), FakeRequest())
            yield deferral.sleep(.01)
        
        yield deferral.sleep(3)
        
        assert len(n.tracker.items) == 100
        assert n.tracker.verified.get_height(n.best_share_var.value) == 100
        
        n.stop()
        
        yield deferral.sleep(20) # waiting for work_poller to exit
