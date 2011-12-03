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

class Protocol(bitcoin_p2p.BaseProtocol):
    version = 1
    sub_version = p2pool.__version__
    
    def __init__(self, node):
        self.node = node
        
        self._prefix = self.node.net.PREFIX
    
    max_payload_length = 1000000
    use_checksum = True
    
    other_version = None
    connected2 = False
    
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
            mode=1,
            best_share_hash=self.node.current_work.value['best_share_hash'],
        )
        
        reactor.callLater(10, self._connect_timeout)
        self.timeout_delayed = reactor.callLater(100, self._timeout)
    
    def _connect_timeout(self):
        if not self.connected2 and self.transport.connected:
            print 'Handshake timed out, disconnecting from %s:%i' % self.addr
            self.transport.loseConnection()
    
    def gotPacket(self):
        if not self.timeout_delayed.called:
            self.timeout_delayed.cancel()
            self.timeout_delayed = reactor.callLater(100, self._timeout)
    
    def _timeout(self):
        if self.transport.connected:
            print 'Connection timed out, disconnecting from %s:%i' % self.addr
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
        ('mode', bitcoin_data.StructType('<I')), # always 1 for legacy compatibility
        ('best_share_hash', bitcoin_data.PossiblyNoneType(0, bitcoin_data.HashType())),
    ])
    def handle_version(self, version, services, addr_to, addr_from, nonce, sub_version, mode, best_share_hash):
        self.other_version = version
        self.other_sub_version = sub_version[:512]
        self.other_services = services
        
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
            self.node.handle_share_hashes([best_share_hash], self)
    
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
    
    message_shares = bitcoin_data.ComposedType([
        ('shares', bitcoin_data.ListType(p2pool_data.new_share_type)),
    ])
    def handle_shares(self, shares):
        res = []
        for share in shares:
            share_obj = p2pool_data.NewShare.from_share(share, self.node.net)
            share_obj.peer = self
            res.append(share_obj)
        self.node.handle_shares(res)
    
    def sendShares(self, shares, full=False):
        new_shares = []
        # XXX doesn't need to send full block when it's not urgent
        # eg. when getting history
        for share in shares:
            new_shares.append(share.as_share())
        def att(f, **kwargs):
            try:
                f(**kwargs)
            except bitcoin_p2p.TooLong:
                att(f, **dict((k, v[:len(v)//2]) for k, v in kwargs.iteritems()))
                att(f, **dict((k, v[len(v)//2:]) for k, v in kwargs.iteritems()))
        if new_shares: att(self.send_shares, shares=new_shares)
    
    def connectionLost(self, reason):
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
    def __init__(self, current_work, port, net, addr_store=None, preferred_addrs=set(), desired_peers=10, max_attempts=100, preferred_storage=1000):
        if addr_store is None:
            addr_store = {}
        
        self.port = port
        self.net = net
        self.addr_store = AddrStore(addr_store)
        self.preferred_addrs = preferred_addrs
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
        
        print 'Connected to peer %s:%i. p2pool version: %r' % (conn.addr[0], conn.addr[1], conn.other_sub_version)
    
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
