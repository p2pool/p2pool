'''
Implementation of Bitcoin's p2p protocol
'''

from __future__ import division

import hashlib
import random
import struct
import time

from twisted.internet import defer, protocol, reactor, task
from twisted.python import log

import p2pool
from . import data as bitcoin_data, getwork
from p2pool.util import variable, datachunker, deferral, forest, pack

class TooLong(Exception):
    pass

class BaseProtocol(protocol.Protocol):
    def connectionMade(self):
        self.dataReceived = datachunker.DataChunker(self.dataReceiver())
    
    def dataReceiver(self):
        while True:
            start = ''
            while start != self._prefix:
                start = (start + (yield 1))[-len(self._prefix):]
            
            command = (yield 12).rstrip('\0')
            length, = struct.unpack('<I', (yield 4))
            
            if length > self.max_payload_length:
                print 'length too large'
                continue
            
            if self.use_checksum:
                checksum = yield 4
            else:
                checksum = None
            
            payload = yield length
            
            if checksum is not None:
                if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
                    print 'invalid hash for', self.transport.getPeer().host, repr(command), length, checksum.encode('hex'), hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4].encode('hex'), payload.encode('hex')
                    continue
            
            type_ = getattr(self, 'message_' + command, None)
            if type_ is None:
                if p2pool.DEBUG:
                    print 'no type for', repr(command)
                continue
            
            try:
                payload2 = type_.unpack(payload)
            except:
                print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                log.err(None, 'Error parsing message: (see RECV line)')
                continue
            
            self.packetReceived(command, payload2)
    
    def packetReceived(self, command, payload2):
        handler = getattr(self, 'handle_' + command, None)
        if handler is None:
            if p2pool.DEBUG:
                print 'no handler for', repr(command)
            return
        
        try:
            handler(**payload2)
        except:
            print 'RECV', command, repr(payload2)[:100]
            log.err(None, 'Error handling message: (see RECV line)')
    
    def sendPacket(self, command, payload2):
        if len(command) >= 12:
            raise ValueError('command too long')
        type_ = getattr(self, 'message_' + command, None)
        if type_ is None:
            raise ValueError('invalid command')
        #print 'SEND', command, repr(payload2)[:500]
        payload = type_.pack(payload2)
        if len(payload) > self.max_payload_length:
            raise TooLong('payload too long')
        if self.use_checksum:
            checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        else:
            checksum = ''
        data = self._prefix + struct.pack('<12sI', command, len(payload)) + checksum + payload
        self.transport.write(data)
    
    def __getattr__(self, attr):
        prefix = 'send_'
        if attr.startswith(prefix):
            command = attr[len(prefix):]
            return lambda **payload2: self.sendPacket(command, payload2)
        #return protocol.Protocol.__getattr__(self, attr)
        raise AttributeError(attr)

class Protocol(BaseProtocol):
    def __init__(self, net):
        self._prefix = net.P2P_PREFIX
    
    version = 0
    
    max_payload_length = 1000000
    
    @property
    def use_checksum(self):
        return self.version >= 209
    
    def connectionMade(self):
        BaseProtocol.connectionMade(self)
        
        self.send_version(
            version=32200,
            services=1,
            time=int(time.time()),
            addr_to=dict(
                services=1,
                address=self.transport.getPeer().host,
                port=self.transport.getPeer().port,
            ),
            addr_from=dict(
                services=1,
                address=self.transport.getHost().host,
                port=self.transport.getHost().port,
            ),
            nonce=random.randrange(2**64),
            sub_version_num='',
            start_height=0,
        )
    
    message_version = pack.ComposedType([
        ('version', pack.IntType(32)),
        ('services', pack.IntType(64)),
        ('time', pack.IntType(64)),
        ('addr_to', bitcoin_data.address_type),
        ('addr_from', bitcoin_data.address_type),
        ('nonce', pack.IntType(64)),
        ('sub_version_num', pack.VarStrType()),
        ('start_height', pack.IntType(32)),
    ])
    def handle_version(self, version, services, time, addr_to, addr_from, nonce, sub_version_num, start_height):
        #print 'VERSION', locals()
        self.version_after = version
        self.send_verack()
    
    message_verack = pack.ComposedType([])
    def handle_verack(self):
        self.version = self.version_after
        
        self.ready()
    
    def ready(self):
        self.get_block = deferral.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='block', hash=hash)]))
        self.get_block_header = deferral.ReplyMatcher(lambda hash: self.send_getheaders(version=1, have=[], last=hash))
        self.get_tx = deferral.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='tx', hash=hash)]))
        
        if hasattr(self.factory, 'resetDelay'):
            self.factory.resetDelay()
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(self)
    
    message_inv = pack.ComposedType([
        ('invs', pack.ListType(pack.ComposedType([
            ('type', pack.EnumType(pack.IntType(32), {'tx': 1, 'block': 2})),
            ('hash', pack.IntType(256)),
        ]))),
    ])
    def handle_inv(self, invs):
        for inv in invs:
            if inv['type'] == 'tx':
                self.factory.new_tx.happened(inv['hash'])
            elif inv['type'] == 'block':
                self.factory.new_block.happened(inv['hash'])
            else:
                print 'Unknown inv type', item
    
    message_getdata = pack.ComposedType([
        ('requests', pack.ListType(pack.ComposedType([
            ('type', pack.EnumType(pack.IntType(32), {'tx': 1, 'block': 2})),
            ('hash', pack.IntType(256)),
        ]))),
    ])
    message_getblocks = pack.ComposedType([
        ('version', pack.IntType(32)),
        ('have', pack.ListType(pack.IntType(256))),
        ('last', pack.PossiblyNoneType(0, pack.IntType(256))),
    ])
    message_getheaders = pack.ComposedType([
        ('version', pack.IntType(32)),
        ('have', pack.ListType(pack.IntType(256))),
        ('last', pack.PossiblyNoneType(0, pack.IntType(256))),
    ])
    message_getaddr = pack.ComposedType([])
    
    message_addr = pack.ComposedType([
        ('addrs', pack.ListType(pack.ComposedType([
            ('timestamp', pack.IntType(32)),
            ('address', bitcoin_data.address_type),
        ]))),
    ])
    def handle_addr(self, addrs):
        for addr in addrs:
            pass
    
    message_tx = pack.ComposedType([
        ('tx', bitcoin_data.tx_type),
    ])
    def handle_tx(self, tx):
        self.get_tx.got_response(bitcoin_data.hash256(bitcoin_data.tx_type.pack(tx)), tx)
    
    message_block = pack.ComposedType([
        ('block', bitcoin_data.block_type),
    ])
    def handle_block(self, block):
        block_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(block['header']))
        self.get_block.got_response(block_hash, block)
        self.get_block_header.got_response(block_hash, block['header'])
    
    message_headers = pack.ComposedType([
        ('headers', pack.ListType(bitcoin_data.block_type)),
    ])
    def handle_headers(self, headers):
        for header in headers:
            header = header['header']
            self.get_block_header.got_response(bitcoin_data.hash256(bitcoin_data.block_header_type.pack(header)), header)
        self.factory.new_headers.happened([header['header'] for header in headers])
    
    message_ping = pack.ComposedType([])
    def handle_ping(self):
        pass
    
    message_alert = pack.ComposedType([
        ('message', pack.VarStrType()),
        ('signature', pack.VarStrType()),
    ])
    def handle_alert(self, message, signature):
        print 'ALERT:', (message, signature)
    
    def connectionLost(self, reason):
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(None)

class ClientFactory(protocol.ReconnectingClientFactory):
    protocol = Protocol
    
    maxDelay = 1
    
    def __init__(self, net):
        self.net = net
        self.conn = variable.Variable(None)
        
        self.new_block = variable.Event()
        self.new_tx = variable.Event()
        self.new_headers = variable.Event()
    
    def buildProtocol(self, addr):
        p = self.protocol(self.net)
        p.factory = self
        return p
    
    def gotConnection(self, conn):
        self.conn.set(conn)
    
    def getProtocol(self):
        return self.conn.get_not_none()

class HeaderWrapper(object):
    target = 2**256 - 1
    __slots__ = 'hash previous_hash'.split(' ')
    
    @classmethod
    def from_header(cls, header):
        return cls(bitcoin_data.hash256(bitcoin_data.block_header_type.pack(header)), header['previous_block'])
    
    def __init__(self, hash, previous_hash):
        self.hash, self.previous_hash = hash, previous_hash

class HeightTracker(object):
    '''Point this at a factory and let it take care of getting block heights'''
    
    def __init__(self, rpc_proxy, factory, backlog_needed=1000):
        self._rpc_proxy = rpc_proxy
        self._factory = factory
        self._backlog_needed = backlog_needed
        
        self._tracker = forest.Tracker()
        
        self._watch1 = self._factory.new_headers.watch(self._heard_headers)
        self._watch2 = self._factory.new_block.watch(self._heard_block)
        
        self._requested = set()
        self._clear_task = task.LoopingCall(self._requested.clear)
        self._clear_task.start(60)
        
        self._last_notified_size = 0
        
        self.updated = variable.Event()
        
        self._think_task = task.LoopingCall(self._think)
        self._think_task.start(15)
        self._think2_task = task.LoopingCall(self._think2)
        self._think2_task.start(15)
    
    def _think(self):
        try:
            highest_head = max(self._tracker.heads, key=lambda h: self._tracker.get_height_and_last(h)[0]) if self._tracker.heads else None
            if highest_head is None:
                return # wait for think2
            height, last = self._tracker.get_height_and_last(highest_head)
            if height < self._backlog_needed:
                self._request(last)
        except:
            log.err(None, 'Error in HeightTracker._think:')
    
    @defer.inlineCallbacks
    def _think2(self):
        try:
            ba = getwork.BlockAttempt.from_getwork((yield self._rpc_proxy.rpc_getwork()))
            self._request(ba.previous_block)
        except:
            log.err(None, 'Error in HeightTracker._think2:')
    
    def _heard_headers(self, headers):
        changed = False
        for header in headers:
            hw = HeaderWrapper.from_header(header)
            if hw.hash in self._tracker.shares:
                continue
            changed = True
            self._tracker.add(hw)
        if changed:
            self.updated.happened()
        self._think()
        
        if len(self._tracker.shares) >= self._last_notified_size + 100:
            print 'Have %i/%i block headers' % (len(self._tracker.shares), self._backlog_needed)
            self._last_notified_size = len(self._tracker.shares)
    
    def _heard_block(self, block_hash):
        self._request(block_hash)
    
    @defer.inlineCallbacks
    def _request(self, last):
        if last in self._tracker.shares:
            return
        if last in self._requested:
            return
        self._requested.add(last)
        (yield self._factory.getProtocol()).send_getheaders(version=1, have=[], last=last)
    
    def get_height_rel_highest(self, block_hash):
        # callers: highest height can change during yields!
        height, last = self._tracker.get_height_and_last(block_hash)
        if last not in self._tracker.tails:
            return -1000000000 # XXX hack
        return height - max(self._tracker.get_height(head_hash) for head_hash in self._tracker.tails[last])
    
    def stop(self):
        self._factory.new_headers.unwatch(self._watch1)
        self._factory.new_block.unwatch(self._watch2)
        self._clear_task.stop()
        self._think_task.stop()
        self._think2_task.stop()

if __name__ == '__main__':
    from . import networks
    factory = ClientFactory(networks.BitcoinMainnet)
    reactor.connectTCP('127.0.0.1', 8333, factory)
    
    @repr
    @apply
    @defer.inlineCallbacks
    def think():
        try:
            print (yield (yield factory.getProtocol()).get_block(0x000000000000003aaaf7638f9f9c0d0c60e8b0eb817dcdb55fd2b1964efc5175))
        except defer.TimeoutError:
            print "timeout"
        reactor.stop()
    
    reactor.run()
