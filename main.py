from __future__ import division

import argparse
import subprocess
import os
import sys
import traceback
import random

from twisted.internet import reactor, defer
from twisted.web import server

import jsonrpc
import conv
import worker_interface
import util
import bitcoin_p2p
import p2p
import expiring_dict

try:
    __version__ = subprocess.Popen(["svnversion", os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
except IOError:
    __version__ = "unknown"

name = "p2pool (version %s)" % (__version__,)

parser = argparse.ArgumentParser(description=name)
parser.add_argument('--version', action='version', version=__version__)

p2pool_group = parser.add_argument_group("p2pool interface")
p2pool_group.add_argument("-p", "--p2pool-port", metavar="PORT",
    help="use UDP port PORT to connect to other p2pool nodes and listen for connections (default: random)",
    type=int, action="store", default=None, dest="p2pool_port")
p2pool_group.add_argument("-n", "--p2pool-node", metavar="ADDR:PORT",
    help="connect to existing p2pool node at ADDR listening on UDP port PORT, in addition to builtin addresses",
    type=str, action="append", default=[], dest="p2pool_nodes")

worker_group = parser.add_argument_group("worker interface")
worker_group.add_argument("-w", "--worker-port", metavar="PORT",
    help="listen on PORT for RPC connections from miners asking for work and providing responses (default: 8338)",
    type=int, action="store", default=8338, dest="worker_port")

bitcoind_group = parser.add_argument_group("bitcoind interface")
bitcoind_group.add_argument("--bitcoind-address", metavar="BITCOIND_ADDRESS",
    help="connect to a bitcoind at this address (default: 127.0.0.1)",
    type=str, action="store", default="127.0.0.1", dest="bitcoind_address")
bitcoind_group.add_argument("--bitcoind-rpc-port", metavar="BITCOIND_RPC_PORT",
    help="connect to a bitcoind at this port over the RPC interface - used to get the current highest block via getwork (default: 8332)",
    type=int, action="store", default=8332, dest="bitcoind_rpc_port")
bitcoind_group.add_argument("--bitcoind-p2p-port", metavar="BITCOIND_P2P_PORT",
    help="connect to a bitcoind at this port over the p2p interface - used to submit blocks and get the pubkey to generate to via an IP transaction (default: 8333)",
    type=int, action="store", default=8333, dest="bitcoind_p2p_port")

bitcoind_group.add_argument(metavar="BITCOIND_RPC_USERNAME",
    help="bitcoind RPC interface username",
    type=str, action="store", dest="bitcoind_rpc_username")
bitcoind_group.add_argument(metavar="BITCOIND_RPC_PASSWORD",
    help="bitcoind RPC interface password",
    type=str, action="store", dest="bitcoind_rpc_password")

TARGET_MULTIPLIER = 1000000000 # 100
SCRIPT = "410441ccbae5ca6ecfaa014028b0c49df2cd5588cb6058ac260d650bc13c9ec466f95c7a6d80a3ea7f7b8e2e87e49b96081e9b20415b06433d7a5b6a156b58690d96ac".decode('hex')

coinbase_type = bitcoin_p2p.ComposedType([
    ('previous_p2pool_block', bitcoin_p2p.HashType()),
    ('previous_p2pool_share', bitcoin_p2p.HashType()),
    ('subsidy', bitcoin_p2p.StructType('<Q')),
    ('last_share_index', bitcoin_p2p.StructType('<I')),
    ('nonce', bitcoin_p2p.HashType()),
])

class Node(object):
    def __init__(self, block):
        self.block = block
        self.coinbase = coinbase_type.unpack(self.block['txns'][0]['tx_ins'][0]['script'], ignore_extra=True)
    
    def hash(self):
        return bitcoin_p2p.block_hash(self.block['headers'])
    
    def previous_hash(self):
        hash_ = self.coinbase['previous_share']
        if hash_ == 2**256 - 1:
            return None
        return hash_
    
    def check(self, chain, height2, previous_node):
        # check bits and target
        
        t = self.block['txns'][0]
        t2, shares = generate_transaction(
            shares=previous_node.shares if previous_node is not None else [SCRIPT]*100,
            add_pubkey=t['tx_outs'][self.coinbase['last_share_index']]['script'],
            subsidy=coinbase['subsidy'],
            previous_block2=coinbase['previous_block2']
        )
        if t2 != t:
            raise ValueError("invalid generate txn")
        return shares

class Chain(object):
    def __init__(self, previous_p2pool_block):
        self.previous_p2pool_block = previous_p2pool_block
        
        self.nodes = {} # hash -> (height, node)
        self.highest = util.Variable(None) # (height, node) could be hash
        self.shared = set()
    
    def accept(self, node, is_current):
        hash_ = node.hash()
        
        if hash_ in self.nodes:
            return
        
        previous_hash = node.previous_hash()
        
        if previous_hash is None:
            previous_height, previous_node = -1, None
        elif previous_hash not in self.nodes:
            raise ValueError("missing referenced previous_node")
        else:
            previous_height, previous_node = self.nodes[previous_hash]
        
        height = previous_height + 1
        
        if not node.check(self, height, previous_node):
            return
        
        self.nodes[hash_] = (height, node)
        
        if height > self.highest.value[0]:
            self.highest.set((height, node))
        
        if is_current:
            node.share()

def generate_transaction(previous_shares, add_share, subsidy, previous_block2):
    shares = previous_shares[1:] + [add_share]
    
    dest_weights = {}
    for script, difficulty in shares:
        dest_weights[script] = dest_weights.get(script, 0) + difficulty
    total_weight = sum(dest_weights.itervalues())
    
    amounts = dict((script, subsidy*weight*63//(64*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[SCRIPT] = amounts.get(SCRIPT, 0) + subsidy//64 # prevent fake previous p2pool blocks
    amounts[SCRIPT] = amounts.get(SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    
    dests = sorted(amounts.iterkeys())
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=dict(index=4294967295, hash=0),
            sequence=4294967295,
            script=coinbase_type.pack(dict(
                previous_p2pool_block=previous_p2pool_block,
                previous_p2pool_share=previous_p2pool_share,
                subsidy=subsidy,
                last_share_index=dests.index(add_pubkey),
                nonce=random.randrange(2**256) if nonce is None else nonce,
            )),
        )],
        tx_outs=[dict(value=amounts[pubkey], script=pubkey) for pubkey in dests if amounts[pubkey]],
        lock_time=0,
    ), shares

@defer.inlineCallbacks
def get_last_p2pool_block(current_block_hash, get_block):
    block_hash = current_block_hash
    while True:
        if block_hash == 0x174784b4188975e572237bbedc98e9eed1a0d5670a37ba163ea1:
            defer.returnValue(block_hash)
        block = yield get_block(block_hash)
        if block == 5:
            defer.returnValue(block_hash)
        block_hash = block['headers']['previous_block']

@defer.inlineCallbacks
def getwork(bitcoind, chains):
    while True:
        try:
            getwork_df, height_df = bitcoind.rpc_getwork(), bitcoind.rpc_getblocknumber()
            getwork, height = conv.BlockAttempt.from_getwork((yield getwork_df)), (yield height_df)
        except:
            traceback.print_exc()
            yield util.sleep(1)
            continue
        defer.returnValue((getwork, height))
        defer.returnValue((
            ((getwork.version, getwork.previous_block, getwork.bits), height, chains.get(getwork.previous_block, Chain()).highest.value),
            (getwork.timestamp,),
        ))

@defer.inlineCallbacks
def main(args):
    try:
        print name
        print
        
        chains = expiring_dict.ExpiringDict()
        current_work = util.Variable(None)
        current_work2 = None
        
        # connect to bitcoind over JSON-RPC and do initial getwork
        print "Testing bitcoind RPC connection..."
        bitcoind = jsonrpc.Proxy('http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port), (args.bitcoind_rpc_username, args.bitcoind_rpc_password))
        
        work, height = yield getwork(bitcoind, chains)
        
        print "    ...success!"
        print "    Current block hash: %x height: %i" % (work.previous_block, height)
        print
        
        # connect to bitcoind over bitcoin-p2p and do checkorder to get pubkey to send payouts to
        print "Testing bitcoind P2P connection..."
        factory = bitcoin_p2p.ClientFactory()
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        
        while True:
            try:
                res = yield (yield factory.getProtocol()).check_order(order=bitcoin_p2p.Protocol.null_order)
                if res['reply'] != 'success':
                    print "error in checkorder reply:", res
                    continue
                my_pubkey = res['script']
            except:
                traceback.print_exc()
            else:
                break
            yield util.sleep(1)
        
        print "    ...success!"
        print "    Payout script:", my_pubkey.encode('hex')
        print
        
        @defer.inlineCallbacks
        def real_get_block(block_hash):
            block = yield (yield factory.getProtocol()).get_block(block_hash)
            print "    Got block %x" % (block_hash,)
            defer.returnValue(block)
        get_block = util.DeferredCacher(real_get_block, expiring_dict.ExpiringDict(3600))
        
        chains = util.ExpiringDict(100)
        
        print "Searching for last p2pool-generated block..."
        work, height = yield getwork(bitcoind, chains)
        p2pool_block_hash = (yield get_last_p2pool_block(work.previous_block, get_block))
        current_work.set(dict(
            version=work.version,
            previous_block=work.previous_block,
            bits=work.bits,
            height=height+1,
            current_chain=chains.setdefault(p2pool_block_hash, Chain(p2pool_block_hash)),
            highest_secondary_block=None,
        ))
        current_work2 = dict(
            timestamp=work.timestamp,
        )
        print "    ...success!"
        print "    Matched block %x" % (p2pool_block_hash,)
        print
        
        # setup worker logic
        
        merkle_root_to_transactions = expiring_dict.ExpiringDict(100)
        
        def compute(state, state2):
            transactions = [generate_transaction(
                shares=state['highest_secondary_block'].shares if state['highest'] is not None else {},
                add_pubkey=my_pubkey,
                subsidy=50*100000000 >> state['height']//210000,
                previous_block2=state['highest'].hash() if state['highest'] is not None else {},
            )]
            merkle_root = bitcoin_p2p.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = transactions # will stay for 100 seconds
            ba = conv.BlockAttempt(state['version'], state['previous_block'], merkle_root, state2['timestamp'], state['bits'])
            return ba.getwork(TARGET_MULTIPLIER)
        
        def got_response(data):
            # match up with transactions
            headers = conv.decode_data(data)
            transactions = merkle_root_to_transactions[headers['merkle_root']]
            block = dict(headers=headers, txns=transactions)
            return p2pCallback(bitcoin_p2p.block.pack(block))
        
        # setup p2p logic and join p2pool network
        
        seen = set() # grows indefinitely!
        
        def p2pCallback(block_data):
            block = bitcoin_p2p.block.unpack(block_data)
            hash_ = bitcoin_p2p.block_hash(block['headers'])
            
            # early out for worthless
            if hash_ < 2**256//2**32:
                return
            
            if hash_ in seen:
                return
            seen.add(hash_)
            
            if block['headers']['version'] != 1:
                return False
            
            node = Node(block)
            chains.setdefault(block['headers']['previous_block'], Chain()).accept(node)
            if block['headers']['previous_block'] in chains:
                node.share(p2p_node)
            
            if hash_ <= conv.bits_to_target(initial_getwork.bits):
                # send to bitcoind
                if factory.conn is not None:
                    factory.conn.addInv("block", block)
            
            if hash_ <= TARGET_MULTIPLIER*conv.bits_to_target(initial_getwork.bits):
                # broadcast to p2p
                for peer in node.peers:
                    peer.block(bitcoin_p2p.block.pack(block))
                return True
            return False
        
        print "Joining p2pool network..."
        
        p2p_node = p2p.Node(p2pCallback, udpPort=random.randrange(49152, 65536) if args.p2pool_port is None else args.p2pool_port)
        def parse(x):
            ip, port = x.split(':')
            return ip, int(port)
        
        nodes = [('72.14.191.28', 21519)]*0
        p2p_node.joinNetwork(map(parse, args.p2pool_nodes) + nodes)
        yield p2p_node._joinDeferred
        
        print "    ...success!"
        print
        
        # start listening for workers with a JSON-RPC server
        
        print "Listening for workers on port %i..." % (args.worker_port,)
        
        reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response)))
        
        print "    ...success!"
        print
        
        # done!
        
        print "Started successfully!"
        print
        
        while True:
            work, height = yield getwork(bitcoind, chains)
            current_work.set(dict(
                version=work.version,
                previous_block=work.previous_block,
                bits=work.bits,
                height=height,
                highest_block2=None,
            ))
            current_work2 = dict(
                timestamp=work.timestamp,
            )
            yield util.sleep(1)
    except:
        traceback.print_exc()
        reactor.stop()

reactor.callWhenRunning(main, parser.parse_args())
reactor.run()
