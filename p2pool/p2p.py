from __future__ import division

import random
import time

from twisted.internet import defer, protocol, reactor
from twisted.python import log

import p2pool
from p2pool import data as p2pool_data
from p2pool.bitcoin import p2p as bitcoin_p2p
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import deferral, pack

class Protocol(bitcoin_p2p.BaseProtocol):
    def __init__(self, node, incoming):
        bitcoin_p2p.BaseProtocol.__init__(self, node.net.PREFIX, 1000000)
        self.node = node
        self.incoming = incoming
        
        self.other_version = None
        self.connected2 = False
    
    def connectionMade(self):
        self.factory.proto_made_connection(self)
        
        self.addr = self.transport.getPeer().host, self.transport.getPeer().port
        
        self.send_version(
            version=3,
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
            sub_version=p2pool.__version__,
            mode=1,
            best_share_hash=self.node.best_share_hash_func(),
        )
        
        reactor.callLater(10, self._connect_timeout)
        self.timeout_delayed = reactor.callLater(100, self._timeout)
        
        old_dataReceived = self.dataReceived
        def new_dataReceived(data):
            if not self.timeout_delayed.called:
                self.timeout_delayed.reset(100)
            old_dataReceived(data)
        self.dataReceived = new_dataReceived
    
    def _connect_timeout(self):
        if not self.connected2 and self.transport.connected:
            print 'Handshake timed out, disconnecting from %s:%i' % self.addr
            self.transport.loseConnection()
    
    def packetReceived(self, command, payload2):
        if command != 'version' and not self.connected2:
            self.transport.loseConnection()
            return
        
        bitcoin_p2p.BaseProtocol.packetReceived(self, command, payload2)
    
    def badPeerHappened(self):
        self.transport.loseConnection()
        self.node.bans[self.transport.getPeer().host] = time.time() + 60*60
    
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
    
    message_version = pack.ComposedType([
        ('version', pack.IntType(32)),
        ('services', pack.IntType(64)),
        ('addr_to', bitcoin_data.address_type),
        ('addr_from', bitcoin_data.address_type),
        ('nonce', pack.IntType(64)),
        ('sub_version', pack.VarStrType()),
        ('mode', pack.IntType(32)), # always 1 for legacy compatibility
        ('best_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
    ])
    def handle_version(self, version, services, addr_to, addr_from, nonce, sub_version, mode, best_share_hash):
        if self.other_version is not None or version < 2:
            self.transport.loseConnection()
            return
        
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
        self.factory.proto_connected(self)
        
        self._think()
        self._think2()
        
        if best_share_hash is not None:
            self.node.handle_share_hashes([best_share_hash], self)
    
    message_ping = pack.ComposedType([])
    def handle_ping(self):
        pass
    
    message_addrme = pack.ComposedType([
        ('port', pack.IntType(16)),
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
    
    message_addrs = pack.ComposedType([
        ('addrs', pack.ListType(pack.ComposedType([
            ('timestamp', pack.IntType(64)),
            ('address', bitcoin_data.address_type),
        ]))),
    ])
    def handle_addrs(self, addrs):
        for addr_record in addrs:
            self.node.got_addr((addr_record['address']['address'], addr_record['address']['port']), addr_record['address']['services'], min(int(time.time()), addr_record['timestamp']))
            if random.random() < .8 and self.node.peers:
                random.choice(self.node.peers.values()).send_addrs(addrs=[addr_record])
    
    message_getaddrs = pack.ComposedType([
        ('count', pack.IntType(32)),
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
            self.node.get_good_peers(count)
        ])
    
    message_getshares = pack.ComposedType([
        ('hashes', pack.ListType(pack.IntType(256))),
        ('parents', pack.VarIntType()),
        ('stops', pack.ListType(pack.IntType(256))),
    ])
    def handle_getshares(self, hashes, parents, stops):
        self.node.handle_get_shares(hashes, parents, stops, self)
    
    message_shares = pack.ComposedType([
        ('shares', pack.ListType(p2pool_data.share_type)),
    ])
    def handle_shares(self, shares):
        self.node.handle_shares([p2pool_data.Share.from_share(share, self.node.net, self) for share in shares], self)
    
    def sendShares(self, shares):
        def att(f, **kwargs):
            try:
                f(**kwargs)
            except bitcoin_p2p.TooLong:
                att(f, **dict((k, v[:len(v)//2]) for k, v in kwargs.iteritems()))
                att(f, **dict((k, v[len(v)//2:]) for k, v in kwargs.iteritems()))
        if shares:
            att(self.send_shares, shares=[share.as_share() for share in shares])
    
    def connectionLost(self, reason):
        if self.connected2:
            self.factory.proto_disconnected(self, reason)
            self.connected2 = False
        self.factory.proto_lost_connection(self, reason)

class ServerFactory(protocol.ServerFactory):
    def __init__(self, node, max_conns):
        self.node = node
        self.max_conns = max_conns
        
        self.conns = {}
        self.running = False
    
    def buildProtocol(self, addr):
        if sum(self.conns.itervalues()) >= self.max_conns or self.conns.get(self._host_to_ident(addr.host), 0) >= 3:
            return None
        if addr.host in self.node.bans and self.node.bans[addr.host] > time.time():
            return None
        p = Protocol(self.node, True)
        p.factory = self
        return p
    
    def _host_to_ident(self, host):
        a, b, c, d = host.split('.')
        return a, b
    
    def proto_made_connection(self, proto):
        ident = self._host_to_ident(proto.transport.getPeer().host)
        self.conns[ident] = self.conns.get(ident, 0) + 1
    def proto_lost_connection(self, proto, reason):
        ident = self._host_to_ident(proto.transport.getPeer().host)
        self.conns[ident] -= 1
        if not self.conns[ident]:
            del self.conns[ident]
    
    def proto_connected(self, proto):
        self.node.got_conn(proto)
    def proto_disconnected(self, proto, reason):
        self.node.lost_conn(proto, reason)
    
    def start(self):
        assert not self.running
        self.running = True
        
        def attempt_listen():
            if self.running:
                self.listen_port = reactor.listenTCP(self.node.port, self)
        deferral.retry('Error binding to P2P port:', traceback=False)(attempt_listen)()
    
    def stop(self):
        assert self.running
        self.running = False
        
        self.listen_port.stopListening()

class ClientFactory(protocol.ClientFactory):
    def __init__(self, node, desired_conns, max_attempts):
        self.node = node
        self.desired_conns = desired_conns
        self.max_attempts = max_attempts
        
        self.attempts = set()
        self.conns = set()
        self.running = False
    
    def _host_to_ident(self, host):
        a, b, c, d = host.split('.')
        return a, b
    
    def buildProtocol(self, addr):
        p = Protocol(self.node, False)
        p.factory = self
        return p
    
    def startedConnecting(self, connector):
        ident = self._host_to_ident(connector.getDestination().host)
        if ident in self.attempts:
            raise AssertionError('already have attempt')
        self.attempts.add(ident)
    
    def clientConnectionFailed(self, connector, reason):
        self.attempts.remove(self._host_to_ident(connector.getDestination().host))
    
    def clientConnectionLost(self, connector, reason):
        self.attempts.remove(self._host_to_ident(connector.getDestination().host))
    
    def proto_made_connection(self, proto):
        pass
    def proto_lost_connection(self, proto, reason):
        pass
    
    def proto_connected(self, proto):
        self.conns.add(proto)
        self.node.got_conn(proto)
    def proto_disconnected(self, proto, reason):
        self.conns.remove(proto)
        self.node.lost_conn(proto, reason)
    
    def start(self):
        assert not self.running
        self.running = True
        self._think()
    def stop(self):
        assert self.running
        self.running = False
    
    @defer.inlineCallbacks
    def _think(self):
        while self.running:
            try:
                if len(self.conns) < self.desired_conns and len(self.attempts) < self.max_attempts and self.node.addr_store:
                    (host, port), = self.node.get_good_peers(1)
                    
                    if self._host_to_ident(host) in self.attempts:
                        pass
                    elif host in self.node.bans and self.node.bans[host] > time.time():
                        pass
                    else:
                        #print 'Trying to connect to', host, port
                        reactor.connectTCP(host, port, self, timeout=5)
            except:
                log.err()
            
            yield deferral.sleep(random.expovariate(1/1))

class SingleClientFactory(protocol.ReconnectingClientFactory):
    def __init__(self, node):
        self.node = node
    
    def buildProtocol(self, addr):
        p = Protocol(self.node, incoming=False)
        p.factory = self
        return p
    
    def proto_made_connection(self, proto):
        pass
    def proto_lost_connection(self, proto, reason):
        pass
    
    def proto_connected(self, proto):
        self.resetDelay()
        self.node.got_conn(proto)
    def proto_disconnected(self, proto, reason):
        self.node.lost_conn(proto, reason)

class Node(object):
    def __init__(self, best_share_hash_func, port, net, addr_store={}, connect_addrs=set(), desired_outgoing_conns=10, max_outgoing_attempts=30, max_incoming_conns=50, preferred_storage=1000):
        self.best_share_hash_func = best_share_hash_func
        self.port = port
        self.net = net
        self.addr_store = dict(addr_store)
        self.connect_addrs = connect_addrs
        self.preferred_storage = preferred_storage
        
        self.nonce = random.randrange(2**64)
        self.peers = {}
        self.bans = {} # address -> end_time
        self.clientfactory = ClientFactory(self, desired_outgoing_conns, max_outgoing_attempts)
        self.serverfactory = ServerFactory(self, max_incoming_conns)
        self.running = False
    
    def start(self):
        if self.running:
            raise ValueError('already running')
        
        self.clientfactory.start()
        self.serverfactory.start()
        self.singleclientconnectors = [reactor.connectTCP(addr, port, SingleClientFactory(self)) for addr, port in self.connect_addrs]
        
        self.running = True
        
        self._think2()
    
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
        
        self.clientfactory.stop()
        self.serverfactory.stop()
        for singleclientconnector in self.singleclientconnectors:
            singleclientconnector.factory.stopTrying() # XXX will this disconnect a current connection?
        del self.singleclientconnectors
    
    def got_conn(self, conn):
        if conn.nonce in self.peers:
            raise ValueError('already have peer')
        self.peers[conn.nonce] = conn
        
        print '%s connection to peer %s:%i established. p2pool version: %i %r' % ('Incoming' if conn.incoming else 'Outgoing', conn.addr[0], conn.addr[1], conn.other_version, conn.other_sub_version)
    
    def lost_conn(self, conn, reason):
        if conn.nonce not in self.peers:
            raise ValueError('''don't have peer''')
        if conn is not self.peers[conn.nonce]:
            raise ValueError('wrong conn')
        del self.peers[conn.nonce]
        
        print 'Lost peer %s:%i - %s' % (conn.addr[0], conn.addr[1], reason.getErrorMessage())
    
    
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
    
    def get_good_peers(self, max_count):
        t = time.time()
        return [x[0] for x in sorted(self.addr_store.iteritems(), key=lambda (k, (services, first_seen, last_seen)): -max(3600, last_seen - first_seen)/max(3600, t - last_seen)*random.expovariate(1))][:max_count]

if __name__ == '__main__':
    p = random.randrange(2**15, 2**16)
    for i in xrange(5):
        p2 = random.randrange(2**15, 2**16)
        print p, p2
        n = Node(p2, True, {addrdb_key.pack(dict(address='127.0.0.1', port=p)): addrdb_value.pack(dict(services=0, first_seen=int(time.time())-10, last_seen=int(time.time())))})
        n.start()
        p = p2
    
    reactor.run()
