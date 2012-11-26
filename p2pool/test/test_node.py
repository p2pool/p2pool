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
    
    def send_tx(self, tx):
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
            "transactions" : ([
                {
                    "data" : "01000000014c6ade5af7e7803fdf2ecae88d939ec044fdb3de84bc70168723969666b30e38010000008b483045022100e1fce6361811e24d57b494c3d71a9e653e54b9489dd5a1889affdef8a1e912b002204079a4720f25b55a0f092bcd70a5824e38a85072bb8e58477df8eb6a66b967ae01410426952de5ee7e5fea3c2065ffceada913d7d643f5631f0d714d667a0b81b599aada24f6e0b46d4bd4051b8111be95cf460fbd1977eadb3f2adc68b4018f8b5ba6ffffffff020065cd1d000000001976a9144799fc9c1b2cfb2c0187551be50f6ea41ed37ed888ac80969800000000001976a914ac2092a73378e8b80a127748a10274c962579f5188ac00000000",
                    "hash" : "9665fece00aceffd175a28912707889c9b2039be004c77e1497b59d8f5132966",
                    "depends" : [
                    ],
                    "fee" : 0,
                    "sigops" : 2
                },
                {
                    "data" : "0100000003bbb3bda750ea9bc057906a7fb12b7a0bf81e4a2c5ffbf3117d0aff9f6e4a7d8c000000006b483045022100fbadaa914af56955dca66c1cca59f7ec9fadbfe01fdec7d72e6cde85abd67be302202713f52dacf7da9c678c33440caef5e2de65dc02994197b5b59d284214088fb1012102ace616bb7d1e5a58118c83466f410fd2c5423450da0dbeb5b1fca158873a92cbffffffffd5c3ec30d816ecc203c581cb7365c1c51c1917b59660ca16683c2f4e1e394337010000006a47304402207dc3644c8a14175e1cec939fcec4d60702f556ee153f602b764adcf32c5a1e6b02207aee1c6ed4d0e8004f1a4fe0a82401bf7e8f285ae1a506fe1be25670ebdb092d0121034d77fd7088a2ee52bc1a3f850772aa61a47d230b3093065a23fd909d95c38ffbfffffffffbf4692b046b684fc51bc7112da5bbd6094fb92eb87f25c6a0893fea15fac13b000000006c493046022100b8d79f514b2bd20f9f2aa5bb5031cf038a5b97fd2fe9ea182187bbeea454d5d202210085f55c96c1e2be5faf26f6122e2d105f9ffaa49b61890a1def9b30ff48be3362012102716ee02e7f5a9f2e5619b5ac7c092e5e5aab6fc45708504bb1f8aac4ea31a84cffffffff0262cc990a000000001976a9141f7dcec4f61c2a1488c7ccf03673120f230d1fd988ac005ed0b2000000001976a914f2b29da6ac6a2aac1f088ead181b553d60d35e9c88ac00000000",
                    "hash" : "27ac960a159b7f8a7d3cc3095d0248375ca65be2c98b16a5818814262eabe01c",
                    "depends" : [
                    ],
                    "fee" : 0,
                    "sigops" : 2
                },
                {
                    "data" : "01000000012d0b6b9d9f57de5c567ea43f26e488321bfcfd0226f3043f7151d504702cfacd010000008b483045022025830bac86c09f77fb132507952210fd0b2452d8d583c12be80e274d943c7127022100f1674c75ae0b38fcee9489daa4164d6f84a386534be0eb1cc063e853bc1d3258014104f993167e332d7fe550b5049d35a972463944beb9ae8e9abe888f832ba6847883a2fd3464765b6350b89a84c8fe7ecee0cca4352494413b4c15791c1cd0694022ffffffff02007ddaac000000001976a9140e0c40f1b244e2dd07c95f52978f50a6fe5ec85188ac66208687080000001976a9143e64cf12ce0369ce9fe78b37708ae6f8a565b2d288ac00000000",
                    "hash" : "00d1647f78e05715b171c9169d555141c9a6ec54d1ec177534aae4555d7bbc7a",
                    "depends" : [
                    ],
                    "fee" : 0,
                    "sigops" : 2
                }
            ] if random.randrange(2) else []),
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

@apply
class mm_provider(object):
    def __getattr__(self, name):
        print '>>>>>>>', name
    def rpc_getauxblock(self, request, result1=None, result2=None):
        if result1 is not None:
            print result1, result2
            return True
        return {
            "target" : "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", # 2**256*2/3
            "hash" : "2756ea0315d46dc3d8d974f34380873fc88863845ac01a658ef11bc3b368af52",
            "chainid" : 1
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
    def start(cls, net, factory, bitcoind, peer_ports, merged_urls):
        self = cls()
        
        self.n = node.Node(factory, bitcoind, [], [], net)
        yield self.n.start()
        
        self.n.p2p_node = node.P2PNode(self.n, port=0, max_incoming_conns=1000000, addr_store={}, connect_addrs=[('127.0.0.1', peer_port) for peer_port in peer_ports])
        self.n.p2p_node.start()
        
        wb = work.WorkerBridge(node=self.n, my_pubkey_hash=random.randrange(2**160), donation_percentage=random.uniform(0, 10), merged_urls=merged_urls, worker_fee=3)
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
        mm_root = resource.Resource()
        mm_root.putChild('', jsonrpc.Server(mm_provider))
        mm_port = reactor.listenTCP(0, server.Site(mm_root))
        
        n = node.Node(factory, bitcoind, [], [], mynet)
        yield n.start()
        
        wb = work.WorkerBridge(node=n, my_pubkey_hash=42, donation_percentage=2, merged_urls=[('http://127.0.0.1:%i' % (mm_port.getHost().port,), '')], worker_fee=3)
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
        
        wb.stop()
        n.stop()
        
        yield port.stopListening()
        del n, wb, web_root, port, proxy
        import gc
        gc.collect()
        gc.collect()
        gc.collect()
        
        yield deferral.sleep(20) # waiting for work_poller to exit
        yield mm_port.stopListening()
    #test_node.timeout = 15
    
    @defer.inlineCallbacks
    def test_nodes(self):
        N = 3
        SHARES = 600
        
        nodes = []
        for i in xrange(N):
            nodes.append((yield MiniNode.start(mynet, factory, bitcoind, [mn.n.p2p_node.serverfactory.listen_port.getHost().port for mn in nodes], [])))
        
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
            assert type(n.n.tracker.items[nodes[0].n.best_share_var.value]) is data.Share
            assert type(n.n.tracker.items[n.n.tracker.get_nth_parent_hash(nodes[0].n.best_share_var.value, SHARES - 5)]) is data.Share
        
        for n in nodes:
            yield n.stop()
        
        del nodes, n
        import gc
        gc.collect()
        gc.collect()
        gc.collect()
        
        yield deferral.sleep(20) # waiting for work_poller to exit
