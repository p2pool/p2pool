from __future__ import division

import base64
import random
import tempfile

from twisted.internet import defer, reactor
from twisted.python import failure
from twisted.trial import unittest
from twisted.web import client, resource, server

from p2pool import data, node, work
from p2pool.bitcoin import data as bitcoin_data, networks, worker_interface
from p2pool.util import deferral, jsonrpc, math, variable

class bitcoind(object): # can be used as p2p factory, p2p protocol, or rpc jsonrpc proxy
    def __init__(self):
        self.blocks = [0x000000000000016c169477c25421250ec5d32cf9c6d38538b5de970a2355fd89]
        self.headers = {0x16c169477c25421250ec5d32cf9c6d38538b5de970a2355fd89: {
            'nonce': 1853158954,
            'timestamp': 1351658517,
            'merkle_root': 2282849479936278423916707524932131168473430114569971665822757638339486597658L,
            'version': 1,
            'previous_block': 1048610514577342396345362905164852351970507722694242579238530L,
            'bits': bitcoin_data.FloatingInteger(bits=0x1a0513c5, target=0x513c50000000000000000000000000000000000000000000000L),
        }}
        
        self.conn = variable.Variable(self)
        self.new_headers = variable.Event()
        self.new_block = variable.Event()
        self.new_tx = variable.Event()
    
    # p2p factory
    
    def getProtocol(self):
        return self
    
    # p2p protocol
    
    def send_block(self, block):
        pass
    
    def send_tx(self, tx):
        pass
    
    def get_block_header(self, block_hash):
        return self.headers[block_hash]
    
    # rpc jsonrpc proxy
    
    def rpc_help(self):
        return '\ngetblock '
    
    def rpc_getblock(self, block_hash_hex):
        block_hash = int(block_hash_hex, 16)
        return dict(height=self.blocks.index(block_hash))
    
    def __getattr__(self, name):
        if name.startswith('rpc_'):
            return lambda *args, **kwargs: failure.Failure(jsonrpc.Error_for_code(-32601)('Method not found'))
    
    def rpc_getblocktemplate(self, param):
        if param['mode'] == 'template':
            pass
        elif param['mode'] == 'submit':
            result = param['data']
            block = bitcoin_data.block_type.unpack(result.decode('hex'))
            if sum(tx_out['value'] for tx_out in block['txs'][0]['tx_outs']) != sum(tx['tx_outs'][0]['value'] for tx in block['txs'][1:]) + 5000000000:
                print 'invalid fee'
            if block['header']['previous_block'] != self.blocks[-1]:
                return False
            if bitcoin_data.hash256(result.decode('hex')) > block['header']['bits'].target:
                return False
            header_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(block['header']))
            self.blocks.append(header_hash)
            self.headers[header_hash] = block['header']
            reactor.callLater(0, self.new_block.happened)
            return True
        else:
            raise jsonrpc.Error_for_code(-1)('invalid request')
        
        txs = []
        for i in xrange(100):
            fee = i
            txs.append(dict(
                data=bitcoin_data.tx_type.pack(dict(version=1, tx_ins=[], tx_outs=[dict(value=fee, script='hello!'*100)], lock_time=0)).encode('hex'),
                fee=fee,
            ))
        return {
            "version" : 2,
            "previousblockhash" : '%064x' % (self.blocks[-1],),
            "transactions" : txs,
            "coinbaseaux" : {
                "flags" : "062f503253482f"
            },
            "coinbasevalue" : 5000000000 + sum(tx['fee'] for tx in txs),
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
            "height" : len(self.blocks),
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
    NAME='mynet',
    PARENT=networks.nets['litecoin_testnet'],
    SHARE_PERIOD=5, # seconds
    CHAIN_LENGTH=20*60//3, # shares
    REAL_CHAIN_LENGTH=20*60//3, # shares
    TARGET_LOOKBEHIND=200, # shares
    SPREAD=3, # blocks
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
        self.wb = wb
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
        bitd = bitcoind()
        
        mm_root = resource.Resource()
        mm_root.putChild('', jsonrpc.HTTPServer(mm_provider))
        mm_port = reactor.listenTCP(0, server.Site(mm_root))
        
        n = node.Node(bitd, bitd, [], [], mynet)
        yield n.start()
        
        wb = work.WorkerBridge(node=n, my_pubkey_hash=42, donation_percentage=2, merged_urls=[('http://127.0.0.1:%i' % (mm_port.getHost().port,), '')], worker_fee=3)
        web_root = resource.Resource()
        worker_interface.WorkerInterface(wb).attach_to(web_root)
        port = reactor.listenTCP(0, server.Site(web_root))
        
        proxy = jsonrpc.HTTPProxy('http://127.0.0.1:' + str(port.getHost().port),
            headers=dict(Authorization='Basic ' + base64.b64encode('user/0:password')))
        
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
        
        bitd = bitcoind()
        
        nodes = []
        for i in xrange(N):
            nodes.append((yield MiniNode.start(mynet, bitd, bitd, [mn.n.p2p_node.serverfactory.listen_port.getHost().port for mn in nodes], [])))
        
        yield deferral.sleep(3)
        
        for i in xrange(SHARES):
            proxy = jsonrpc.HTTPProxy('http://127.0.0.1:' + str(random.choice(nodes).web_port.getHost().port),
                headers=dict(Authorization='Basic ' + base64.b64encode('user/0:password')))
            blah = yield proxy.rpc_getwork()
            yield proxy.rpc_getwork(blah['data'])
            yield deferral.sleep(.05)
            print i
            print type(nodes[0].n.tracker.items[nodes[0].n.best_share_var.value])
        
        # crawl web pages
        from p2pool import web
        stop_event = variable.Event()
        web2_root = web.get_web_root(nodes[0].wb, tempfile.mkdtemp(), variable.Variable(None), stop_event)
        web2_port = reactor.listenTCP(0, server.Site(web2_root))
        for name in web2_root.listNames() + ['web/' + x for x in web2_root.getChildWithDefault('web', None).listNames()]:
            if name in ['web/graph_data', 'web/share', 'web/share_data']: continue
            print
            print name
            try:
                res = yield client.getPage('http://127.0.0.1:%i/%s' % (web2_port.getHost().port, name))
            except:
                import traceback
                traceback.print_exc()
            else:
                print repr(res)[:100]
            print
        yield web2_port.stopListening()
        stop_event.happened()
        del web2_root
        
        yield deferral.sleep(3)
        
        for i, n in enumerate(nodes):
            assert len(n.n.tracker.items) == SHARES, (i, len(n.n.tracker.items))
            assert n.n.tracker.verified.get_height(n.n.best_share_var.value) == SHARES, (i, n.n.tracker.verified.get_height(n.n.best_share_var.value))
            assert type(n.n.tracker.items[nodes[0].n.best_share_var.value]) is (data.Share.SUCCESSOR if data.Share.SUCCESSOR is not None else data.Share)
            assert type(n.n.tracker.items[n.n.tracker.get_nth_parent_hash(nodes[0].n.best_share_var.value, SHARES - 5)]) is data.Share
        
        for n in nodes:
            yield n.stop()
        
        del nodes, n
        import gc
        gc.collect()
        gc.collect()
        gc.collect()
        
        yield deferral.sleep(20) # waiting for work_poller to exit
    test_nodes.timeout = 300
