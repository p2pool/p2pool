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

@defer.inlineCallbacks
def main(args):
    try:
        print name
        
        bitcoind = jsonrpc.Proxy('http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port), (args.bitcoind_rpc_username, args.bitcoind_rpc_password))
        
        while True:
            try:
                initial_getwork = conv.BlockAttempt.from_getwork((yield bitcoind.rpc_getwork()))
            except:
                traceback.print_exc()
            else:
                break
            time.sleep(1)
        
        #print "GETWORK", initial_getwork
        #print conv.bits_to_target(initial_getwork.bits)/2**256.
        
        current_work = util.Variable(((initial_getwork.version, initial_getwork.previous_block, initial_getwork.timestamp, initial_getwork.bits), {}))
        
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
            time.sleep(1)
        
        #print "PUBKEY", my_pubkey.encode('hex')
        
        def incr_dict(d, key, step=1):
            d = dict(d)
            if key not in d:
                d[key] = 0
            d[key] += 1
            return d
        
        merkle_root_to_transactions = {} # merkle_root -> (timestamp, transactions)
        
        def compute(((version, previous_block, timestamp, bits), log)):
            nHeight = 0 # XXX
            subsidy = (50*100000000) >> (nHeight / 210000)
            log2 = incr_dict(log, my_pubkey)
            total_shares = sum(log2.itervalues())
            amounts = dict((pubkey, subsidy*shares//total_shares) for (pubkey, shares) in log2.iteritems())
            total_amount = sum(amounts.itervalues())
            amount_left = subsidy - total_amount
            incr_dict(amounts, "XXX", amount_left)
            
            transactions = [{
                'version': 1,
                'tx_ins': [{'previous_output': {'index': 4294967295, 'hash': 0}, 'sequence': 4294967295, 'script': bitcoin_p2p.Hash().pack(random.randrange(2**256))}],
                'tx_outs': [dict(value=amount, script=pubkey) for (pubkey, amount) in sorted(amounts.iteritems())],
                'lock_time': 0,
            }]
            merkle_root = bitcoin_p2p.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = (time.time(), transactions)
            ba = conv.BlockAttempt(version, previous_block, merkle_root, timestamp, bits)
            return ba.getwork(TARGET_MULTIPLIER)
        
        def got_response(data):
            headers = conv.decode_data(data)
            hash_ = bitcoin_p2p.block_hash(headers)
            
            encoded = bitcoin_p2p.block_headers.pack(headers)
            _, transactions = merkle_root_to_transactions[headers['merkle_root']]
            
            block = {'header': headers, 'txns': transactions}
            
            if hash_ <= conv.bits_to_target(initial_getwork.bits):
                # broadcast to bitcoin
                if factory.conn is not None:
                    factory.conn.addInv("block", block)
            
            if hash_ <= TARGET_MULTIPLIER*conv.bits_to_target(initial_getwork.bits):
                # broadcast to p2p
                for peer in node.peers:
                    peer.new_block(bitcoin_p2p.block.pack(block))
                return True
            return False

        reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response)))
        
        def p2pCallback(block_data):
            block = bitcoin_p2p.block.read(StringIO.StringIO(block_data))
        
        node = p2p.Node(p2pCallback, udpPort=random.randrange(49152, 65536) if args.p2pool_port is None else args.p2pool_port)
        node.joinNetwork(args.p2pool_nodes)
        yield node._joinDeferred
        
        print "Started successfully!"
        
        while True:
            yield util.sleep(60)
            for k in list(merkle_root_to_transactions):
                if merkle_root_to_transactions[k][0] < time.time() - 3600:
                    merkle_root_to_transactions.pop(k)
    except:
        traceback.print_exc()
        reactor.stop()

reactor.callWhenRunning(main, parser.parse_args())
reactor.run()
