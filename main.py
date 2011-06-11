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

class Node(object):
    def __init__(self, block, shares):
        self.block = block
        self.coinbase = coinbase_type.read(self.block['txns'][0]['tx_ins'][0]['script'], ignore_extra=True)
        self.shares = shares
    
    #@classmethod
    #def accept(
    
    def hash(self):
        return bitcoin_p2p.block_hash(self.block['headers'])
    
    def previous_hash(self):
        hash_ = self.coinbase['previous_block2']
        if hash_ == 2**256 - 1:
            return None
        return hash_
    
    def check(self, chain, height2, previous_node):
        if self.block['headers']['version'] != chain.version: return False
        if self.block['headers']['previous_block'] != chain.previous_block: return False
        if self.block['headers']['merkle_root'] != bitcoin_p2p.merkle_hash(self.block['txns']): return False
        if self.block['headers']['bits'] != chain.bits: return False
        
        if not self.block['txns']: return False
        if len(self.block['txns'][0]['tx_ins']) != 1: return False
        
        okay, self.shares = check_transaction(self.block['txns'][0], {} if previous_node is None else previous_node.shares)
        
        return okay
    
    def share(self):
        if self.shared:
            return
        self.shared = True
        a

class Chain(object):
    def __init__(self, version, previous_block, bits, height):
        self.version, self.previous_block1, self.bits, self.height1 = version, previous_block, bits, height
        
        self.nodes = {} # hash -> (height, node)
        self.highest = util.Variable(None) # (height, node)
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

def check_transaction(t, shares):
    coinbase = coinbase_type.read(t['tx_ins'][0]['script'], ignore_extra=True)
    t2, new_shares = generate_transaction(shares, t['tx_outs'][coinbase['last_share_index']]['script'], coinbase['subsidy'], coinbase['previous_block2'])
    return t2 == t, shares

def generate_transaction(shares, add_pubkey, subsidy, previous_block2):
    shares = shares[1:-1] + [add_pubkey, add_pubkey]
    total_shares = len(shares)
    
    grouped_shares = {}
    for script in shares:
        grouped_shares[script]
    amounts = dict((pubkey, subsidy*shares//total_shares) for (pubkey, shares) in shares.iteritems())
    amounts = incr_dict(amounts, "XXX", subsidy - sum(amounts.itervalues()))
    dests = sorted(amounts.iterkeys())
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=dict(index=4294967295, hash=0),
            sequence=4294967295,
            script=coinbase_type.pack(dict(
                version=1,
                subsidy=subsidy,
                previous_block2=previous_block2,
                last_share_index=dests.index(add_pubkey),
                nonce=random.randrange(2**256) if nonce is None else nonce,
            )),
        )],
        tx_outs=[dict(value=amount, script=pubkey) for (pubkey, amount) in dests],
        lock_time=0,
    ), shares

class DeferredCacher(object):
    # XXX should combine requests
    def __init__(self, func, backing=None):
        if backing is None:
            backing = {}
        
        self.func = func
        self.backing = backing
    
    @defer.inlineCallbacks
    def __call__(self, key):
        if key in self.backing:
            defer.returnValue(self.backing[key])
        value = yield self.func(key)
        self.backing[key] = value
        defer.returnValue(value)

@defer.inlineCallbacks
def get_last_p2pool_block(current_block_hash, get_block):
    block_hash = current_block_hash
    while True:
        print hex(block_hash)
        if block_hash == 0x2c0117ac4e1f784761bc010f5d69c2b107c659a672d0107df64:
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

coinbase_type = bitcoin_p2p.ComposedType([
    ('subsidy', bitcoin_p2p.StructType('<Q')),
    ('previous_block2', bitcoin_p2p.HashType()),
    ('last_share_index', bitcoin_p2p.StructType('<I')),
    ('nonce', bitcoin_p2p.HashType()),
])

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
        
        print "    ...success!"
        print "    Current block hash: %x height: %i" % (current_work.value['previous_block'], current_work.value['height'])
        print
        
        # connect to bitcoind over bitcoin-p2p and do checkorder to get pubkey to send payouts to
        print "Testing bitcoind P2P connection..."
        factory = bitcoin_p2p.ClientFactory()
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        
        while True:
            try:
                res = yield (yield factory.getProtocol()).check_order(order='\0'*60)
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
        
        get_block = DeferredCacher(defer.inlineCallbacks(lambda block_hash: defer.returnValue((yield (yield factory.getProtocol()).get_block(block_hash)))), expiring_dict.ExpiringDict(3600))
        print (yield get_last_p2pool_block(conv.BlockAttempt.from_getwork((yield bitcoind.rpc_getwork())).previous_block, get_block))
        
        # setup worker logic
        
        merkle_root_to_transactions = expiring_dict.ExpiringDict(100)
        
        def compute(state, state2):
            transactions = [generate_transaction(
                shares=state['highest'].shares if state['highest'] is not None else {},
                add_pubkey=my_pubkey,
                subsidy=50*100000000 >> height//210000,
                previous_block2=state['highest'].hash() if state['highest'] is not None else {},
            )]
            merkle_root = bitcoin_p2p.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = transactions
            ba = conv.BlockAttempt(version, previous_block, merkle_root, timestamp, bits)
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
