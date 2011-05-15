from __future__ import division

import argparse
import subprocess
import os
import sys
import traceback

from twisted.internet import reactor, defer
from twisted.web import server, resource, client

import jsonrpc
import conv
import worker_interface
import util

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

args = parser.parse_args()

print name

bitcoind = jsonrpc.Proxy('http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port), (args.bitcoind_rpc_username, args.bitcoind_rpc_password))
bitcoin_p2p = (args.bitcoind_address, args.bitcoind_p2p_port)

p2pool_protocol = (args.p2pool_port, args.p2pool_nodes)

current_work = util.Variable(None)

@repr
@apply
@defer.inlineCallbacks
def _():
    while True:
        try:
            work = conv.BlockAttempt.from_getwork((yield bitcoind.rpc_getwork()))
        except:
            traceback.print_exc()
            yield util.sleep(1)
        else:
            work2 = work.getwork(100)
            current_work.set(work2)
            yield util.sleep(.1)

def got_response(data):
    print data
    return True

reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, got_response)))

reactor.run()
