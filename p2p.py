from __future__ import division

import random
import time
import traceback

from twisted.internet import defer, reactor, protocol, task

import bitcoin_p2p
import conv
import util

# mode
#     0: send hash first (high latency, low bandwidth)
#     1: send entire share (low latency, high bandwidth)

if 0:
    import pygame
    d = pygame.display.set_mode((512, 512))
    task.LoopingCall(pygame.display.update).start(.1)
    def draw_circle(id, color=(255,0,0)):
        id = repr(id)
        pygame.draw.circle(d, (255, 0, 0), (hash(id)%512, hash(id)//512%512), 4)
    def draw_line(id, id2, color):
        id = repr(id)
        pygame.draw.line(d, color, (hash(id)%512, hash(id)//512%512), (hash(id2)%512, hash(id2)//512%512))
else:
    draw_circle = draw_line = lambda *args, **kwargs: None

class Protocol(bitcoin_p2p.BaseProtocol):
    version = 0
    sub_version = ""
    
    def __init__(self, node):
        self.node = node
    
    @property
    def _prefix(self):
        if self.node.testnet:
            return 'f77cea5d16a2183f'.decode('hex')
        else:
            return '95ec1eda53c5e716'.decode('hex')
    
    use_checksum = True
    
    message_types = {
        'version': bitcoin_p2p.ComposedType([
            ('version', bitcoin_p2p.StructType('<I')),
            ('services', bitcoin_p2p.StructType('<Q')),
            ('addr_to', bitcoin_p2p.address),
            ('addr_from', bitcoin_p2p.address),
            ('nonce', bitcoin_p2p.StructType('<Q')),
            ('sub_version', bitcoin_p2p.VarStrType()),
            ('mode', bitcoin_p2p.StructType('<I')),
            ('state', bitcoin_p2p.ComposedType([
                ('chain_id', bitcoin_p2p.ComposedType([
                    ('previous_p2pool_block', bitcoin_p2p.HashType()),
                    ('bits', bitcoin_p2p.StructType('<I')),
                ])),
                ('highest', bitcoin_p2p.ComposedType([
                    ('hash', bitcoin_p2p.HashType()),
                    ('height', bitcoin_p2p.StructType('<Q')),
                ])),
            ])),
        ]),
        
        'update_mode': bitcoin_p2p.ComposedType([
            ('mode', bitcoin_p2p.StructType('<I')),
        ]),
        
        'ping': bitcoin_p2p.ComposedType([]),
        
        'addrme': bitcoin_p2p.ComposedType([
            ('port', bitcoin_p2p.StructType('<H')),
        ]),
        'addrs': bitcoin_p2p.ComposedType([
            ('addrs', bitcoin_p2p.ListType(bitcoin_p2p.ComposedType([
                ('timestamp', bitcoin_p2p.StructType('<Q')),
                ('address', bitcoin_p2p.address),
            ]))),
        ]),
        'getaddrs': bitcoin_p2p.ComposedType([
            ('count', bitcoin_p2p.StructType('<I')),
        ]),
        
        'getsharesbychain': bitcoin_p2p.ComposedType([
            ('chain_id', bitcoin_p2p.ComposedType([
                ('previous_p2pool_block', bitcoin_p2p.HashType()),
                ('bits', bitcoin_p2p.StructType('<I')),
            ])),
            ('have', bitcoin_p2p.ListType(bitcoin_p2p.HashType())),
        ]),
        'getshares': bitcoin_p2p.ComposedType([
            ('hashes', bitcoin_p2p.ListType(bitcoin_p2p.HashType())),
        ]),
        
        'share0s': bitcoin_p2p.ComposedType([
            ('share0s', bitcoin_p2p.ListType(bitcoin_p2p.ComposedType([
                ('chain_id', bitcoin_p2p.ComposedType([
                    ('previous_p2pool_block', bitcoin_p2p.HashType()),
                    ('bits', bitcoin_p2p.StructType('<I')),
                ])),
                ('hashes', bitcoin_p2p.ListType(bitcoin_p2p.HashType())),
            ]))),
        ]), 
        'share1s': bitcoin_p2p.ComposedType([
            ('share1s', bitcoin_p2p.ListType(bitcoin_p2p.ComposedType([
                ('header', bitcoin_p2p.block_header),
                ('gentx', bitcoin_p2p.ComposedType([
                    ('tx', bitcoin_p2p.tx),
                    ('merkle_branch', bitcoin_p2p.merkle_branch),
                ])),
            ]))),
        ]),
        'share2s': bitcoin_p2p.ComposedType([
            ('share1s', bitcoin_p2p.ListType(bitcoin_p2p.block)),
        ]),
    }
    
    other_version = None
    node_var_watch = None
    
    @property
    def mode(self):
        return min(self.node.mode.value, self.other_mode.value)
    
    def connectionMade(self):
        bitcoin_p2p.BaseProtocol.connectionMade(self)
        if isinstance(self.factory, ClientFactory):
            draw_line(self.node.port, self.transport.getPeer().port, (128, 128, 128))
        
        chain = self.node.current_work['current_chain']
        self.send_version(
            version=self.version,
            services=0,
            addr_to=dict(
                services=0,
                address='::ffff:' + self.transport.getPeer().host,
                port=self.transport.getPeer().port,
            ),
            addr_from=dict(
                services=0,
                address='::ffff:' + self.transport.getHost().host,
                port=self.transport.getHost().port,
            ),
            nonce=self.node.nonce,
            sub_version=self.sub_version,
            mode=self.node.mode_var.value,
            state=dict(
                chain_id=dict(
                    previous_p2pool_block=0,
                    bits=0,
                ),
                highest=dict(
                    hash=0,
                    height=0,
                ),
            ),
        )
        
        self.node_var_watch = self.node.mode_var.changed.watch(self.send_set_mode)
        
        self.connected = False
        
        self._think()
        self._think2()
        
        reactor.callLater(10, self._connect_timeout)
    
    def _connect_timeout(self):
        if not self.connected and self.transport.connected:
            print "Handshake timed out, disconnecting"
            self.transport.loseConnection()
    
    @defer.inlineCallbacks
    def _think(self):
        while self.transport.connected:
            self.send_ping()
            yield util.sleep(random.expovariate(1/100))
    
    @defer.inlineCallbacks
    def _think2(self):
        while self.transport.connected:
            self.send_addrme(port=self.node.port)
            yield util.sleep(random.expovariate(1/100))
    
    def handle_version(self, version, services, addr_to, addr_from, nonce, sub_version, mode, state):
        self.other_version = version
        self.other_services = services
        self.other_mode_var = util.Variable(mode)
        
        if nonce == self.node.nonce:
            #print "Detected connection to self, disconnecting"
            self.transport.loseConnection()
            return
        
        self.connected = True
        self.node.got_conn(self, services)
        if isinstance(self.factory, ClientFactory):
            draw_line(self.node.port, self.transport.getPeer().port, (0, 255, 0))
    
    def handle_set_mode(self, mode):
        self.other_mode_var.set(mode)
    
    def handle_ping(self):
        pass
    
    def handle_addrme(self, port):
        self.node.got_addr(('::ffff:' + self.transport.getPeer().host, port), self.other_services, int(time.time()))
        if random.random() < .7 and self.node.peers:
            random.choice(self.node.peers.values()).send_addrs(addrs=[dict(address=dict(services=self.other_services, address='::ffff:' + self.transport.getPeer().host, port=port), timestamp=int(time.time()))])
    def handle_addrs(self, addrs):
        for addr_record in addrs:
            self.node.got_addr((addr_record['address']['address'], addr_record['address']['port']), addr_record['address']['services'], min(int(time.time()), addr_record['timestamp']))
            if random.random() < .7 and self.node.peers:
                random.choice(self.node.peers.values()).send_addrs(addrs=[addr_record])
    def handle_getaddrs(self, count):
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
    
    def handle_share0s(self, share0s):
        for share0 in share0s:
            print share0
            self.node.handle_share_hash
    def handle_share1s(self, share1s):
        for share1 in share1s:
            hash_ = bitcoin_p2p.block_hash(share1['header'])
            if hash_ <= conv.bits_to_target(share1['header']['bits']):
                print "Dropping peer %s:%i due to invalid share" % (self.transport.getPeer().host, self.transport.getPeer().port)
                self.transport.loseConnection()
                return
            share1()
    def handle_share2s(self, share2s):
        for share2 in share2s:
            hash_ = bitcoin_p2p.block_hash(share2['header'])
            if not hash_ <= conv.bits_to_target(share1['header']['bits']):
                print "Dropping peer %s:%i due to invalid share" % (self.transport.getPeer().host, self.transport.getPeer().port)
                self.transport.loseConnection()
                return
            share1()
    
    def send_share(self, share):
        hash_ = bitcoin_p2p.block_hash(share['header'])
        if hash_ <= conv.bits_to_target(share['header']['bits']):
            if 'txns' not in share:
                raise ValueError("partial block matching bits passed to send_share")
            self.send_share2s([share])
        else:
            if self.mode == 0:
                self.send_share0s([hash_])
            elif self.mode == 1:
                self.send_share1s([dict(
                    header=share['header'],
                    gentx=dict(
                        tx=share['txns'][0],
                        merkle_branch=bitcoin_p2p.calculate_merkle_branch(share['txns'], 0),
                    ),
                )])
            else:
                raise ValueError(self.mode)
    
    def connectionLost(self, reason):
        if self.node_var_watch is not None:
            self.node.mode_var.changed.unwatch(self.node_var_watch)
        
        if self.connected:
            self.node.lost_conn(self)
        
        if isinstance(self.factory, ClientFactory):
            draw_line(self.node.port, self.transport.getPeer().port, (255, 0, 0))

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

addrdb_key = bitcoin_p2p.ComposedType([
    ('address', bitcoin_p2p.IPV6AddressType()),
    ('port', bitcoin_p2p.StructType('>H')),
])
addrdb_value = bitcoin_p2p.ComposedType([
    ('services', bitcoin_p2p.StructType('<Q')),
    ('first_seen', bitcoin_p2p.StructType('<Q')),
    ('last_seen', bitcoin_p2p.StructType('<Q')),
])

class AddrStore(util.DictWrapper):
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
    def __init__(self, port, testnet, addr_store=None, preferred_addrs=[], mode=0, desired_peers=10, max_attempts=100):
        if addr_store is None:
            addr_store = {}
        
        self.port = port
        self.testnet = testnet
        self.addr_store = AddrStore(addr_store)
        self.preferred_addrs = preferred_addrs
        self.mode_var = util.Variable(mode)
        self.desired_peers = desired_peers
        self.max_attempts = max_attempts
        
        self.current_work = dict(current_chain=None)
        
        self.nonce = random.randrange(2**64)
        self.attempts = {}
        self.peers = {}
        self.running = False
        
        draw_circle(self.port)
    
    def start(self):
        if self.running:
            raise ValueError("already running")
        
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
                        host, port = random.choice(self.preferred_addrs)
                    else:
                        host2, port = random.choice(self.addr_store.keys())
                        prefix = '::ffff:'
                        if not host2.startswith(prefix):
                            raise ValueError("invalid address")
                        host = host2[len(prefix):]
                    
                    if (host, port) not in self.attempts and (host, port) not in self.peers:
                        reactor.connectTCP(host, port, ClientFactory(self), timeout=10)
            except:
                traceback.print_exc()
            
            yield util.sleep(random.expovariate(1/5))
    
    @defer.inlineCallbacks
    def _think2(self):
        while self.running:
            try:
                if len(self.addr_store) < self.preferred_addrs and self.peers:
                    random.choice(self.peers.values()).send_getaddrs(count=8)
            except:
                traceback.print_exc()
            
            yield util.sleep(random.expovariate(1/20))
    
    def stop(self):
        if not self.running:
            raise ValueError("already stopped")
        
        self.running = False
        
        self.listen_port.stopListening()
    
    
    def attempt_started(self, connector):
        host, port = connector.getDestination().host, connector.getDestination().port
        if (host, port) in self.attempts:
            raise ValueError("already have attempt")
        self.attempts[host, port] = connector
    
    def attempt_failed(self, connector):
        self.attempt_ended(connector)
    
    def attempt_ended(self, connector):
        host, port = connector.getDestination().host, connector.getDestination().port
        if (host, port) not in self.attempts:
            raise ValueError("don't have attempt")
        if connector is not self.attempts[host, port]:
            raise ValueError("wrong connector")
        del self.attempts[host, port]
    
    
    def got_conn(self, conn, services):
        host, port = conn.transport.getPeer().host, conn.transport.getPeer().port
        if (host, port) in self.peers:
            raise ValueError("already have peer")
        self.peers[host, port] = conn
        
        print "Connected to peer %s:%i" % (host, port)
    
    def lost_conn(self, conn):
        host, port = conn.transport.getPeer().host, conn.transport.getPeer().port
        if (host, port) not in self.peers:
            raise ValueError("don't have peer")
        if conn is not self.peers[host, port]:
            raise ValueError("wrong conn")
        del self.peers[host, port]
        
        print "Lost peer %s:%i" % (host, port)
    
    
    def got_addr(self, (host, port), services, timestamp):
        if (host, port) in self.addr_store:
            old_services, old_first_seen, old_last_seen = self.addr_store[host, port]
            self.addr_store[host, port] = services, old_first_seen, max(old_last_seen, timestamp)
        else:
            self.addr_store[host, port] = services, timestamp, timestamp

if __name__ == '__main__':
    p = random.randrange(2**15, 2**16)
    for i in xrange(5):
        p2 = random.randrange(2**15, 2**16)
        print p, p2
        n = Node(p2, True, {addrdb_key.pack(dict(address='::ffff:' + '127.0.0.1', port=p)): addrdb_value.pack(dict(services=0, first_seen=int(time.time())-10, last_seen=int(time.time())))})
        n.start()
        p = p2
    
    reactor.run()
