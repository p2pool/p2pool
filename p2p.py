import util

from entangled.kademlia import node, datastore

class OldDictDataStore(datastore.DictDataStore):
    def __init__(self, inner):
        self._dict = inner

class UnDNSNode(node.Node):
    @property
    def peers(self):
        for bucket in self._routingTable._buckets:
            for contact in bucket._contacts:
                yield contact
    
    def __init__(self, udpPort=None):
        if udpPort is None:
            udpPort = random.randrange(49152, 65536)
        
        self.clock_offset = 0
        node.Node.__init__(self, udpPort=udpPort, dataStore=OldDictDataStore(db.PickleValueWrapper(db.SQLiteDict(config_db, 'node'))))
    
    def joinNetwork(self, *args, **kwargs):
        node.Node.joinNetwork(self, *args, **kwargs)
        self._joinDeferred.addBoth(lambda _: (self.joined(), _)[1])
    
    def joined(self):
        self.time_task()
    
    def get_my_time(self):
        return time.time() - self.clock_offset
    
    @defer.inlineCallbacks
    def time_task(self):
        while True:
            t_send = time.time()
            clock_deltas = {None: (t_send, t_send)}
            for peer, request in [(peer, peer.get_time().addCallback(lambda res: (time.time(), res))) for peer in self.peers]:
                try:
                    t_recv, response = yield request
                    t = .5 * (t_send + t_recv)
                    clock_deltas[(peer.id, peer.address, peer.port)] = (t, float(response))
                except:
                    traceback.print_exc()
                    continue
            
            self.clock_offset = util.median(mine - theirs for mine, theirs in clock_deltas.itervalues())
            
            yield util.sleep(random.expovariate(1/100))
    
    @node.rpcmethod
    def store(self, key, value, originalPublisherID=None, age=0, **kwargs):
        return
    
    @node.rpcmethod
    def get_time(self):
        return time.time()
    
    def _republishData(self, *args):
        return defer.succeed(None)
