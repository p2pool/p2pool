from __future__ import division

import argparse
import subprocess
import os
import sys
import time
import traceback
import random
import StringIO

from twisted.internet import reactor, defer, task
from twisted.web import server, resource, client
from twisted.python import failure

import jsonrpc
import conv
import worker_interface
import util
import bitcoin_p2p
import p2p

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

TARGET_MULTIPLIER = 1000000000

class Node(object)):
    def __init__(self, block):
        self.block = block
    def hash(self):
        return bitcoin_p2p.block_hash(self.block)
    def previous_hash(self):
        hash_ = bitcoin_p2p.Hash().read(StringIO.StringIO(self.block['transactions'][0]['tx_ins']['script']))
        if hash_ == 2**256 - 1:
            return None
        return hash_

class Chain(object):
    def __init__(self):
        self.nodes = {} # hash -> (height, node)
        self.highest = util.Variable(None)
        self.highest_height = -1
        
    def accept(self, node):
        hash_ = node.hash()
        previous_hash = node.previous_hash()
        
        if previous_hash is None:
            self.nodes[hash_] = 
        
        if previous_hash not in self.nodes:
            return False
        
        previous_height, previous_node = self.nodes[previous_hash]
        
        self.nodes[node] = (height, item)

@defer.inlineCallbacks
def main(args):
    try:
        print name
        
        bitcoind = jsonrpc.Proxy('http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port), (args.bitcoind_rpc_username, args.bitcoind_rpc_password))
        
        @defer.inlineCallbacks
        def getwork():
            while True:
                try:
                    getwork_df, height_df = bitcoind.rpc_getwork(), bitcoind.rpc_getblocknumber()
                    getwork, height = conv.BlockAttempt.from_getwork((yield getwork_df)), (yield height_df)
                except:
                    traceback.print_exc()
                    yield util.sleep(1)
                    continue
                defer.returnValue((
                    ((getwork[0].version, getwork[0].previous_block, getwork[0].bits), height, chains.get(getwork[0].previous_block, Chain()).highest),
                    (getwork[0].timestamp,),
                ))
        initial = yield getwork()
        
        factory = bitcoin_p2p.ClientFactory()
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        
        while True:
            try:
                res = yield (yield factory.getProtocol()).checkorder(order='\0'*60)
                if res['reply'] != 'success':
                    print "error in checkorder reply:", res
                    continue
            except:
                traceback.print_exc()
            else:
                my_pubkey = res['script']
                break
            yield util.sleep(1)
        
        current_work = util.Variable(((initial[0].version, initial[0].previous_block, initial[0].bits), {}))
        current_work2 = (initial_getwork.timestamp,)
        
        def incr_dict(d, key, step=1):
            d = dict(d)
            if key not in d:
                d[key] = 0
            d[key] += 1
            return d
        
        merkle_root_to_transactions = util.ExpiringDict()
        
        def transactions_from_shares(shares):
            nHeight = 0 # XXX
            subsidy = (50*100000000) >> (nHeight / 210000)
            total_shares = sum(shares.itervalues())
            amounts = dict((pubkey, subsidy*shares//total_shares) for (pubkey, shares) in shares.iteritems())
            total_amount = sum(amounts.itervalues())
            amount_left = subsidy - total_amount
            incr_dict(amounts, "XXX", amount_left)
            
            transactions = [{
                'version': 1,
                'tx_ins': [{'previous_output': {'index': 4294967295, 'hash': 0}, 'sequence': 4294967295, 'script': bitcoin_p2p.Hash().pack(random.randrange(2**256))}],
                'tx_outs': [dict(value=amount, script=pubkey) for (pubkey, amount) in sorted(amounts.iteritems())],
                'lock_time': 0,
            }]
            return transactions
        
        def compute(((version, previous_block, timestamp, bits), log)):
            log2 = incr_dict(log, my_pubkey)
            transactions = transactions_from_shares(log2)
            merkle_root = bitcoin_p2p.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = transactions
            ba = conv.BlockAttempt(version, previous_block, merkle_root, timestamp, bits)
            return ba.getwork(TARGET_MULTIPLIER)
        
        def got_response(data):
            # match up with transactions
            headers = conv.decode_data(data)
            transactions = merkle_root_to_transactions[headers['merkle_root']]
            block = {'header': headers, 'txns': transactions}
            return p2pCallback(bitcoin_p2p.block.pack(block))

        
        chains = util.ExpiringDict()
        
        def p2pCallback(block_data):
            block = bitcoin_p2p.block.read(StringIO.StringIO(block_data))
            hash_ = bitcoin_p2p.block_hash(block['headers'])
            
            if block['headers']['version'] != 1:
                return False
            
            chains.setdefault(block['headers']['previous_block'], Chain()).accept(Node(block))
            
            if hash_ <= conv.bits_to_target(initial_getwork.bits):
                # broadcast to bitcoin
                if factory.conn is not None:
                    factory.conn.addInv("block", block)
            
            if hash_ <= TARGET_MULTIPLIER*conv.bits_to_target(initial_getwork.bits):
                # broadcast to p2p
                for peer in node.peers:
                    peer.block(bitcoin_p2p.block.pack(block))
                return True
            return False
        
        node = p2p.Node(p2pCallback, udpPort=random.randrange(49152, 65536) if args.p2pool_port is None else args.p2pool_port)
        node.joinNetwork(args.p2pool_nodes)
        
        def do_getwork():
            a
        
        def new_block(block):
            p2pCallback(bitcoin_p2p.block.pack(block))
        
        factory.new_block.watch(new_block)
        
        (yield factory.getProtocol()).sendPacket("getdata", [dict(type="block", hash=initial_getwork.previous_block)])
        
        yield node._joinDeferred
        
        reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response)))
        
        print "Started successfully!"
    except:
        traceback.print_exc()
        reactor.stop()

reactor.callWhenRunning(main, parser.parse_args())
reactor.run()
