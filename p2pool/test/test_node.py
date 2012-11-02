from __future__ import division

import random

from twisted.internet import defer, reactor
from twisted.trial import unittest
from twisted.web import resource, server

from p2pool import data, node, work
from p2pool.bitcoin import data as bitcoin_data, networks, worker_interface
from p2pool.util import deferral, jsonrpc, math, variable

@apply
class bitcoinp2p(object):
    def send_block(self, block):
        pass
    
    def get_block_header(self, hash):
        if hash == 0x16c169477c25421250ec5d32cf9c6d38538b5de970a2355fd89:
            return defer.succeed({
                'nonce': 1853158954,
                'timestamp': 1351658517,
                'merkle_root': 2282849479936278423916707524932131168473430114569971665822757638339486597658L,
                'version': 1,
                'previous_block': 1048610514577342396345362905164852351970507722694242579238530L,
                'bits': bitcoin_data.FloatingInteger(bits=0x1a0513c5, target=0x513c50000000000000000000000000000000000000000000000L),
            })
        print hex(hash)
        return defer.fail('blah')

class factory(object):
    new_headers = variable.Event()
    new_block = variable.Event()
    new_tx = variable.Event()
    conn = variable.Variable(bitcoinp2p)
    @classmethod
    def getProtocol(self):
        return bitcoinp2p

class bitcoind(object):
    @classmethod
    def rpc_help(self):
        return '\ngetblock '
    
    @classmethod
    def rpc_getblock(self, block_hash_hex):
        return dict(height=42)
    
    @classmethod
    def rpc_getmemorypool(self, result=None):
        if result is not None:
            return True
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
            "bits" : "21008000",
            "height" : 205801
        }

mynet = math.Object(
    PARENT=networks.nets['litecoin_testnet'],
    SHARE_PERIOD=3, # seconds
    CHAIN_LENGTH=20*60//3, # shares
    REAL_CHAIN_LENGTH=20*60//3, # shares
    TARGET_LOOKBEHIND=200, # shares
    SPREAD=12, # blocks
    IDENTIFIER='cca5e24ec6408b1e'.decode('hex'),
    PREFIX='ad9614f6466a39cf'.decode('hex'),
    P2P_PORT=19338,
    MIN_TARGET=2**256 - 1,
    MAX_TARGET=2**256 - 1,
    PERSIST=False,
    WORKER_PORT=19327,
    BOOTSTRAP_ADDRS='72.14.191.28'.split(' '),
    ANNOUNCE_CHANNEL='#p2pool-alt',
    VERSION_CHECK=lambda v: True,
)

class MiniNode(object):
    @classmethod
    @defer.inlineCallbacks
    def start(cls, net, factory, bitcoind, peer_ports):
        self = cls()
        
        self.n = node.Node(factory, bitcoind, [], [], net)
        yield self.n.start()
        
        self.n.p2p_node = node.P2PNode(self.n, 0, 1000000, {}, [('127.0.0.1', peer_port) for peer_port in peer_ports])
        self.n.p2p_node.start()
        
        wb = work.WorkerBridge(node=self.n, my_pubkey_hash=random.randrange(2**160), donation_percentage=random.uniform(0, 10), merged_urls=[], worker_fee=3)
        web_root = resource.Resource()
        worker_interface.WorkerInterface(wb).attach_to(web_root)
        self.web_port = reactor.listenTCP(0, server.Site(web_root))
        
        defer.returnValue(self)
    
    @defer.inlineCallbacks
    def stop(self):
        yield self.web_port.stopListening()
        yield self.n.p2p_node.stop()
        yield self.n.stop()
        del self.web_port, self.n

class Test(unittest.TestCase):
    @defer.inlineCallbacks
    def test_node(self):
        n = node.Node(factory, bitcoind, [], [], mynet)
        yield n.start()
        
        wb = work.WorkerBridge(node=n, my_pubkey_hash=42, donation_percentage=2, merged_urls=[], worker_fee=3)
        web_root = resource.Resource()
        worker_interface.WorkerInterface(wb).attach_to(web_root)
        port = reactor.listenTCP(0, server.Site(web_root))
        
        proxy = jsonrpc.Proxy('http://127.0.0.1:' + str(port.getHost().port))
        
        yield deferral.sleep(3)
        
        for i in xrange(100):
            blah = yield proxy.rpc_getwork()
            yield proxy.rpc_getwork(blah['data'])
        
        yield deferral.sleep(3)
        
        assert len(n.tracker.items) == 100
        assert n.tracker.verified.get_height(n.best_share_var.value) == 100
        
        n.stop()
        
        yield port.stopListening()
        del n, wb, web_root, port, proxy
        import gc
        gc.collect()
        gc.collect()
        gc.collect()
        
        yield deferral.sleep(20) # waiting for work_poller to exit
    #test_node.timeout = 15
    
    @defer.inlineCallbacks
    def test_nodes(self):
      try:
        old_successor = data.Share.SUCCESSOR
        data.Share.SUCCESSOR = data.NewShare
        
        N = 3
        SHARES = 600
        
        nodes = []
        for i in xrange(N):
            nodes.append((yield MiniNode.start(mynet, factory, bitcoind, [mn.n.p2p_node.serverfactory.listen_port.getHost().port for mn in nodes])))
        
        yield deferral.sleep(3)
        
        for i in xrange(SHARES):
            proxy = jsonrpc.Proxy('http://127.0.0.1:' + str(random.choice(nodes).web_port.getHost().port))
            blah = yield proxy.rpc_getwork()
            yield proxy.rpc_getwork(blah['data'])
            yield deferral.sleep(random.expovariate(1/.1))
            print i
            print type(nodes[0].n.tracker.items[nodes[0].n.best_share_var.value])
    
        yield deferral.sleep(3)
        
        for i, n in enumerate(nodes):
            assert len(n.n.tracker.items) == SHARES, (i, len(n.n.tracker.items))
            assert n.n.tracker.verified.get_height(n.n.best_share_var.value) == SHARES, (i, n.n.tracker.verified.get_height(n.n.best_share_var.value))
            assert type(n.n.tracker.items[nodes[0].n.best_share_var.value]) is data.NewShare
            assert type(n.n.tracker.items[n.n.tracker.get_nth_parent_hash(nodes[0].n.best_share_var.value, SHARES - 5)]) is data.Share
        
        for n in nodes:
            yield n.stop()
        
        del nodes, n
        import gc
        gc.collect()
        gc.collect()
        gc.collect()
        
        yield deferral.sleep(20) # waiting for work_poller to exit
      finally:
        data.Share.SUCCESSOR = old_successor
