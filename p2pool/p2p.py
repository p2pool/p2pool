from __future__ import division

import random
import time

from twisted.internet import defer, protocol, reactor
from twisted.python import log

import p2pool
from p2pool import data as p2pool_data
from p2pool.bitcoin import p2p as bitcoin_p2p
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral, variable, dicts

# mode
#     0: send hash first (high latency, low bandwidth)
#     1: send entire share (low latency, high bandwidth)

class Protocol(bitcoin_p2p.BaseProtocol):
    version = 1
    sub_version = p2pool.__version__
    
    def __init__(self, node):
        self.node = node
        
        self._prefix = self.node.net.PREFIX
    
    max_payload_length = 1000000
    max_net_payload_length = 2000000
    use_checksum = True
    compress = False
    
    other_version = None
    node_var_watch = None
    connected2 = False
    
    @property
    def mode(self):
        return min(self.node.mode_var.value, self.other_mode_var.value)
    
    def connectionMade(self):
        bitcoin_p2p.BaseProtocol.connectionMade(self)
        
        self.addr = self.transport.getPeer().host, self.transport.getPeer().port
        
        self.send_version(
            version=self.version,
            services=0,
            addr_to=dict(
                services=0,
                address=self.transport.getPeer().host,
                port=self.transport.getPeer().port,
            ),
            addr_from=dict(
                services=0,
                address=self.transport.getHost().host,
                port=self.transport.getHost().port,
            ),
            nonce=self.node.nonce,
            sub_version=self.sub_version,
            mode=self.node.mode_var.value,
            best_share_hash=self.node.current_work.value['best_share_hash'],
        )
        
        self.node_var_watch = self.node.mode_var.changed.watch(lambda new_mode: self.send_setmode(mode=new_mode))
        
        reactor.callLater(10, self._connect_timeout)
    
    def _connect_timeout(self):
        if not self.connected2 and self.transport.connected:
            print 'Handshake timed out, disconnecting from %s:%i' % self.addr
            self.transport.loseConnection()
    
    @defer.inlineCallbacks
    def _think(self):
        while self.connected2:
            self.send_ping()
            yield deferral.sleep(random.expovariate(1/100))
    
    @defer.inlineCallbacks
    def _think2(self):
        while self.connected2:
            self.send_addrme(port=self.node.port)
            #print 'sending addrme'
            yield deferral.sleep(random.expovariate(1/(100*len(self.node.peers) + 1)))
    
    message_version = bitcoin_data.ComposedType([
        ('version', bitcoin_data.StructType('<I')),
        ('services', bitcoin_data.StructType('<Q')),
        ('addr_to', bitcoin_data.address_type),
        ('addr_from', bitcoin_data.address_type),
        ('nonce', bitcoin_data.StructType('<Q')),
        ('sub_version', bitcoin_data.VarStrType()),
        ('mode', bitcoin_data.StructType('<I')),
        ('best_share_hash', bitcoin_data.PossiblyNoneType(0, bitcoin_data.HashType())),
    ])
    def handle_version(self, version, services, addr_to, addr_from, nonce, sub_version, mode, best_share_hash):
        self.other_version = version
        self.other_sub_version = sub_version[:512]
        self.other_services = services
        self.other_mode_var = variable.Variable(mode)
        
        if nonce == self.node.nonce:
            #print 'Detected connection to self, disconnecting from %s:%i' % self.addr
            self.transport.loseConnection()
            return
        if nonce in self.node.peers:
            #print 'Detected duplicate connection, disconnecting from %s:%i' % self.addr
            self.transport.loseConnection()
            return
        
        self.nonce = nonce
        self.connected2 = True
        self.node.got_conn(self)
        
        self._think()
        self._think2()
        
        if best_share_hash is not None:
            self.handle_share0s(hashes=[best_share_hash])
    
    
    message_setmode = bitcoin_data.ComposedType([
        ('mode', bitcoin_data.StructType('<I')),
    ])
    def handle_setmode(self, mode):
        self.other_mode_var.set(mode)
    
    message_ping = bitcoin_data.ComposedType([])
    def handle_ping(self):
        pass
    
    message_addrme = bitcoin_data.ComposedType([
        ('port', bitcoin_data.StructType('<H')),
    ])
    def handle_addrme(self, port):
        host = self.transport.getPeer().host
        #print 'addrme from', host, port
        if host == '127.0.0.1':
            if random.random() < .8 and self.node.peers:
                random.choice(self.node.peers.values()).send_addrme(port=port) # services...
        else:
            self.node.got_addr((self.transport.getPeer().host, port), self.other_services, int(time.time()))
            if random.random() < .8 and self.node.peers:
                random.choice(self.node.peers.values()).send_addrs(addrs=[
                    dict(
                        address=dict(
                            services=self.other_services,
                            address=host,
                            port=port,
                        ),
                        timestamp=int(time.time()),
                    ),
                ])
    
    message_addrs = bitcoin_data.ComposedType([
        ('addrs', bitcoin_data.ListType(bitcoin_data.ComposedType([
            ('timestamp', bitcoin_data.StructType('<Q')),
            ('address', bitcoin_data.address_type),
        ]))),
    ])
    def handle_addrs(self, addrs):
        for addr_record in addrs:
            self.node.got_addr((addr_record['address']['address'], addr_record['address']['port']), addr_record['address']['services'], min(int(time.time()), addr_record['timestamp']))
            if random.random() < .8 and self.node.peers:
                random.choice(self.node.peers.values()).send_addrs(addrs=[addr_record])
    
    message_getaddrs = bitcoin_data.ComposedType([
        ('count', bitcoin_data.StructType('<I')),
    ])
    def handle_getaddrs(self, count):
        if count > 100:
            count = 100
        self.send_addrs(addrs=[
            dict(
                timestamp=self.node.addr_store[host, port][2],
                address=dict(
                    services=self.node.addr_store[host, port][0],
                    address=host,
                    port=port,
                ),
            ) for host, port in
            random.sample(self.node.addr_store.keys(), min(count, len(self.node.addr_store)))
        ])
    
    message_getshares = bitcoin_data.ComposedType([
        ('hashes', bitcoin_data.ListType(bitcoin_data.HashType())),
        ('parents', bitcoin_data.VarIntType()),
        ('stops', bitcoin_data.ListType(bitcoin_data.HashType())),
    ])
    def handle_getshares(self, hashes, parents, stops):
        self.node.handle_get_shares(hashes, parents, stops, self)
    
    message_share0s = bitcoin_data.ComposedType([
        ('hashes', bitcoin_data.ListType(bitcoin_data.HashType())),
    ])
    def handle_share0s(self, hashes):
        self.node.handle_share_hashes(hashes, self)
    
    message_share1as = bitcoin_data.ComposedType([
        ('share1as', bitcoin_data.ListType(p2pool_data.share1a_type)),
    ])
    def handle_share1as(self, share1as):
        shares = []
        for share1a in share1as:
            hash_ = bitcoin_data.block_header_type.hash256(share1a['header'])
            if hash_ <= share1a['header']['target']:
                print 'Dropping peer %s:%i due to invalid share' % self.addr
                self.transport.loseConnection()
                return
            share = p2pool_data.Share.from_share1a(share1a)
            share.peer = self # XXX
            shares.append(share)
        self.node.handle_shares(shares, self)
    
    message_share1bs = bitcoin_data.ComposedType([
        ('share1bs', bitcoin_data.ListType(p2pool_data.share1b_type)),
    ])
    def handle_share1bs(self, share1bs):
        shares = []
        for share1b in share1bs:
            hash_ = bitcoin_data.block_header_type.hash256(share1b['header'])
            if not hash_ <= share1b['header']['target']:
                print 'Dropping peer %s:%i due to invalid share' % self.addr
                self.transport.loseConnection()
                return
            share = p2pool_data.Share.from_share1b(share1b)
            share.peer = self # XXX
            shares.append(share)
        self.node.handle_shares(shares, self)
    
    def send_shares(self, shares, full=False):
        share1bs = []
        share0s = []
        share1as = []
        # XXX doesn't need to send full block when it's not urgent
        # eg. when getting history
        for share in shares:
            if share.bitcoin_hash <= share.header['target']:
                share1bs.append(share.as_share1b())
            else:
                if self.mode == 0 and not full:
                    share0s.append(share.hash)
                elif self.mode == 1 or full:
                    share1as.append(share.as_share1a())
                else:
                    raise ValueError(self.mode)
        def att(f, **kwargs):
            try:
                f(**kwargs)
            except bitcoin_p2p.TooLong:
                att(f, **dict((k, v[:len(v)//2]) for k, v in kwargs.iteritems()))
                att(f, **dict((k, v[len(v)//2:]) for k, v in kwargs.iteritems()))
        if share1bs: att(self.send_share1bs, share1bs=share1bs)
        if share0s: att(self.send_share0s, hashes=share0s)
        if share1as: att(self.send_share1as, share1as=share1as)
    
    def connectionLost(self, reason):
        if self.node_var_watch is not None:
            self.node.mode_var.changed.unwatch(self.node_var_watch)
        
        if self.connected2:
            self.node.lost_conn(self)

class ServerFactory(protocol.ServerFactory):
    def __init__(self, node):
        self.node = node
    
    def buildProtocol(self, addr):
        p = Protocol(self.node)
        p.factory = self
        return p

class ClientFactory(protocol.ClientFactory):
    def __init__(self, node):
        self.node = node
    
    def buildProtocol(self, addr):
        p = Protocol(self.node)
        p.factory = self
        return p
    
    def startedConnecting(self, connector):
        self.node.attempt_started(connector)
    
    def clientConnectionFailed(self, connector, reason):
        self.node.attempt_failed(connector)
    
    def clientConnectionLost(self, connector, reason):
        self.node.attempt_ended(connector)

addrdb_key = bitcoin_data.ComposedType([
    ('address', bitcoin_data.IPV6AddressType()),
    ('port', bitcoin_data.StructType('>H')),
])
addrdb_value = bitcoin_data.ComposedType([
    ('services', bitcoin_data.StructType('<Q')),
    ('first_seen', bitcoin_data.StructType('<Q')),
    ('last_seen', bitcoin_data.StructType('<Q')),
])

class AddrStore(dicts.DictWrapper):
    def encode_key(self, (address, port)):
        return addrdb_key.pack(dict(address=address, port=port))
    def decode_key(self, encoded_key):
        k = addrdb_key.unpack(encoded_key)
        return k['address'], k['port']
    
    def encode_value(self, (services, first_seen, last_seen)):
        return addrdb_value.pack(dict(services=services, first_seen=first_seen, last_seen=last_seen))
    def decode_value(self, encoded_value):
        v = addrdb_value.unpack(encoded_value)
        return v['services'], v['first_seen'], v['last_seen']

class Node(object):
    def __init__(self, current_work, port, net, addr_store=None, preferred_addrs=set(), mode=0, desired_peers=10, max_attempts=100, preferred_storage=1000):
        if addr_store is None:
            addr_store = {}
        
        self.port = port
        self.net = net
        self.addr_store = AddrStore(addr_store)
        self.preferred_addrs = preferred_addrs
        self.mode_var = variable.Variable(mode)
        self.desired_peers = desired_peers
        self.max_attempts = max_attempts
        self.current_work = current_work
        self.preferred_storage = preferred_storage
        
        self.nonce = random.randrange(2**64)
        self.attempts = {}
        self.peers = {}
        self.running = False
    
    def start(self):
        if self.running:
            raise ValueError('already running')
        
        self.running = True
        
        self.listen_port = reactor.listenTCP(self.port, ServerFactory(self))
        
        self._think()
        self._think2()
    
    @defer.inlineCallbacks
    def _think(self):
        while self.running:
            try:
                if len(self.peers) < self.desired_peers and len(self.attempts) < self.max_attempts and (len(self.preferred_addrs) or len(self.addr_store)):
                    if (random.randrange(2) and len(self.preferred_addrs)) or not len(self.addr_store):
                        host, port = random.choice(list(self.preferred_addrs))
                    else:
                        host, port = random.choice(self.addr_store.keys())
                    
                    if (host, port) not in self.attempts:
                        #print 'Trying to connect to', host, port
                        reactor.connectTCP(host, port, ClientFactory(self), timeout=10)
            except:
                log.err()
            
            yield deferral.sleep(random.expovariate(1/5))
    
    @defer.inlineCallbacks
    def _think2(self):
        while self.running:
            try:
                if len(self.addr_store) < self.preferred_storage and self.peers:
                    random.choice(self.peers.values()).send_getaddrs(count=8)
            except:
                log.err()
            
            yield deferral.sleep(random.expovariate(1/20))
    
    def stop(self):
        if not self.running:
            raise ValueError('already stopped')
        
        self.running = False
        
        self.listen_port.stopListening()
    
    
    def attempt_started(self, connector):
        host, port = connector.getDestination().host, connector.getDestination().port
        if (host, port) in self.attempts:
            raise ValueError('already have attempt')
        self.attempts[host, port] = connector
    
    def attempt_failed(self, connector):
        self.attempt_ended(connector)
    
    def attempt_ended(self, connector):
        host, port = connector.getDestination().host, connector.getDestination().port
        if (host, port) not in self.attempts:
            raise ValueError('''don't have attempt''')
        if connector is not self.attempts[host, port]:
            raise ValueError('wrong connector')
        del self.attempts[host, port]
    
    
    def got_conn(self, conn):
        if conn.nonce in self.peers:
            raise ValueError('already have peer')
        self.peers[conn.nonce] = conn
        
        print 'Connected to peer %s:%i %r' % (conn.addr[0], conn.addr[1], conn.other_sub_version)
    
    def lost_conn(self, conn):
        if conn.nonce not in self.peers:
            raise ValueError('''don't have peer''')
        if conn is not self.peers[conn.nonce]:
            raise ValueError('wrong conn')
        del self.peers[conn.nonce]
        
        print 'Lost peer %s:%i' % (conn.addr[0], conn.addr[1])
    
    
    def got_addr(self, (host, port), services, timestamp):
        if (host, port) in self.addr_store:
            old_services, old_first_seen, old_last_seen = self.addr_store[host, port]
            self.addr_store[host, port] = services, old_first_seen, max(old_last_seen, timestamp)
        else:
            self.addr_store[host, port] = services, timestamp, timestamp
    
    def handle_shares(self, shares, peer):
        print 'handle_shares', (shares, peer)
    
    def handle_share_hashes(self, hashes, peer):
        print 'handle_share_hashes', (hashes, peer)
    
    def handle_get_shares(self, hashes, parents, stops, peer):
        print 'handle_get_shares', (hashes, parents, stops, peer)

if __name__ == '__main__':
    p = random.randrange(2**15, 2**16)
    for i in xrange(5):
        p2 = random.randrange(2**15, 2**16)
        print p, p2
        n = Node(p2, True, {addrdb_key.pack(dict(address='127.0.0.1', port=p)): addrdb_value.pack(dict(services=0, first_seen=int(time.time())-10, last_seen=int(time.time())))})
        n.start()
        p = p2
    
    reactor.run()
