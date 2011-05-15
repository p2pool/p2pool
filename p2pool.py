from __future__ import division

import argparse
import subprocess
import os
import sys

from twisted.internet import reactor, defer
from twisted.web import server, resource, client

import jsonrpc
import conv
import util
import struct
import sha256

try:
    __version__ = subprocess.Popen(["svnversion", os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
except IOError:
    __version__ = "unknown"

name = "p2pool (version %s)" % (__version__,)

parser = argparse.ArgumentParser(description=name)
parser.add_argument('--version', action='version', version=__version__)

parser.add_argument("-p", "--p", metavar="PORT",
    help="use UDP port PORT to connect to other p2pool nodes and listen for connections (default: last used or random if never used)",
    type=int, action="store", default=None, dest="port")
parser.add_argument("-n", "--node", metavar="ADDR:PORT",
    help="connect to existing p2pool node at ADDR listening on UDP port PORT",
    action="append", default=[], dest="nodes")

parser.add_argument(metavar="ADDRESS",
    help="connect to a bitcoind at this address over the p2p interface - used to submit blocks and get the pubkey to generate to via an IP transaction (default: 127.0.0.1)",
    type=str, action="store", default="127.0.0.1", dest="authoritative_dns_ports")
parser.add_argument("-r", "--rpc", metavar="RPC",
    help="connect to a bitcoind at this url over the rpc interface - used to get the current highest block via getwork",
    type=int, action="append", default=[], dest="recursive_dns_ports")


args = parser.parse_args()
print args

bitcoind = jsonrpc.Proxy('http://127.0.0.1:8332/', ('user', 'tx2Ate1u'))

class LongPollingWorkerInterface(util.DeferredResource):
    def render_POST(self, request):
        raise ValueError()
    render_GET = render_POST

def decode(x):
    return int(x.decode('hex')[::-1].encode('hex'), 16)

def encode(x, w):
    x = ('%x' % x).zfill(w)
    return x.decode('hex')[::-1].encode('hex')

def bits_to_target(bits):
    return (bits & 0x00ffffff) * 2 ** (8 * ((bits >> 24) - 3))

def reverse_chunks(s, l):
    return ''.join(reversed([s[x:x+l] for x in xrange(0, len(s), l)]))

class BlockAttempt(object):
    def __init__(self, version, prev_block, merkle_root, timestamp, bits):
        self.version, self.prev_block, self.merkle_root, self.timestamp, self.bits = version, prev_block, merkle_root, timestamp, bits
    
    def getwork(self, target_multiplier=1):
        target = bits_to_target(self.bits) * target_multiplier
        
        prev_block2 = reverse_chunks('%064x' % self.prev_block, 8).decode('hex')
        merkle_root2 = reverse_chunks('%064x' % self.merkle_root, 8).decode('hex')
        data = struct.pack(">I32s32sIII", self.version, prev_block2, merkle_root2, self.timestamp, self.bits, 0).encode('hex') + "000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000"
        
        prev_block3 = ('%064x' % self.prev_block).decode('hex')[::-1]
        merkle_root3 = ('%064x' % self.merkle_root).decode('hex')[::-1]
        data2 = struct.pack("<I32s32s", self.version, prev_block3, merkle_root3)
        
        return {
            "data": data,
            "hash1": "00000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000010000",
            "target": ('%064x' % (target,)).decode('hex')[::-1].encode('hex'),
            "midstate": reverse_chunks(sha256.process(data2[:64])[::-1], 4).encode('hex'),
        }
    
    @classmethod
    def from_getwork(cls, getwork):
        version, prev_block, merkle_root, timestamp, bits, nonce = struct.unpack(">I32s32sIII", getwork['data'][:160].decode('hex'))
        prev_block = int(reverse_chunks(prev_block.encode('hex'), 8), 16)
        merkle_root = int(reverse_chunks(merkle_root.encode('hex'), 8), 16)
        
        ba = cls(version, prev_block, merkle_root, timestamp, bits)
        
        getwork2 = ba.getwork()
        if getwork2 != getwork:
            print ba.__dict__
            for k in getwork:
                print k
                print getwork[k]
                print getwork2[k]
                print getwork[k] == getwork2[k]
                print
            raise ValueError("nonsensical getwork request response")
        
        return ba

@repr
@apply
@defer.inlineCallbacks
def _():
    x = yield bitcoind.rpc_getwork()
    print BlockAttempt.from_getwork(x).getwork(1000000)

class WorkerInterface(jsonrpc.Server):
    extra_headers = {
    #    'X-Long-Polling': '/long-polling',
    }
    
    @defer.inlineCallbacks
    def rpc_getwork(self, *args):
        if args:
            print
            print args
            print
            defer.returnValue(True)
        resp = yield bitcoind.rpc_getwork(*args)
        ba = BlockAttempt.from_getwork(resp)
        
        defer.returnValue(ba.getwork(100))

root = resource.Resource()
root.putChild("", WorkerInterface())
root.putChild("long-polling", LongPollingWorkerInterface())

reactor.listenTCP(8338, server.Site(root), interface='127.0.0.1')

reactor.run()
