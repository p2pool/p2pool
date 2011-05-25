import random
import time
import traceback

from entangled.kademlia import node, datastore, encoding, protocol
from twisted.internet import defer

import util

class CustomBencode(encoding.Bencode):
    def __init__(self, prefix=""):
        self.prefix = prefix
    
    def encode(self, data):
        return self.prefix + encoding.Bencode.encode(data)
    
    def decode(self, data):
        if not data.startswith(self.prefix):
            raise ValueError("invalid prefix")
        return encoding.Bencode.decode(data[len(self.prefix):])

class Node(node.Node):
    @property
    def peers(self):
        for bucket in self._routingTable._buckets:
            for contact in bucket._contacts:
                yield contact
    
    def __init__(self, blockCallback, **kwargs):
        node.Node.__init__(self, networkProtocol=protocol.KademliaProtocol(self, msgEncoder=CustomBencode("p2pool")), **kwargs)
        self.blockCallback = blockCallback
        self.clock_offset = 0
    
    # time
    
    def joinNetwork(self, *args, **kwargs):
        node.Node.joinNetwork(self, *args, **kwargs)
        
        def go(res):
            self.joined()
            return res
        self._joinDeferred.addBoth(go)
    
    def joined(self):
        self.time_task()
    
    def get_my_time(self):
        return time.time() - self.clock_offset
    
    @node.rpcmethod
    def get_time(self):
        return time.time()
    
    @defer.inlineCallbacks
    def time_task(self):
        while True:
            t_send = time.time()
            clock_deltas = {None: (t_send, t_send)}
            for peer, request in [(peer, peer.get_time().addCallback(lambda res: (time.time(), res))) for peer in self.peers]:
                try:
                    t_recv, response = yield request
                    t = (t_send + t_recv)/2
                    clock_deltas[(peer.id, peer.address, peer.port)] = (t, float(response))
                except:
                    traceback.print_exc()
                    continue
            
            self.clock_offset = util.median(mine - theirs for mine, theirs in clock_deltas.itervalues())
            
            yield util.sleep(random.expovariate(1/500.))
    
    # disable data storage
    
    @node.rpcmethod
    def store(self, key, value, originalPublisherID=None, age=0, **kwargs):
        return
    
    @node.rpcmethod
    def findValue(self, key, value, originalPublisherID=None, age=0, **kwargs):
        return
    
    def _republishData(self, *args):
        return defer.succeed(None)
    
    # meat
    
    @node.rpcmethod
    def block(self, block_data):
        self.blockCallback(block_data)
