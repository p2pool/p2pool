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

from . import data as bitcoin_data
from p2pool.util import variable, datachunker, deferral

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
                    print 'invalid hash for', repr(command), checksum.encode('hex') if checksum is not None else None, repr(payload[:100].encode('hex')), len(payload)
                    continue
            
            type_ = getattr(self, 'message_' + command, None)
            if type_ is None:
                print 'no type for', repr(command)
                continue
            
            try:
                payload2 = type_.unpack(payload)
            except:
                print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                log.err(None, 'Error parsing message: (see RECV line)')
                continue
            
            handler = getattr(self, 'handle_' + command, None)
            if handler is None:
                print 'no handler for', repr(command)
                continue
            
            try:
                handler(**payload2)
            except:
                print 'RECV', command, repr(payload2)[:100]
                log.err(None, 'Error handling message: (see RECV line)')
                continue
    
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
        self._prefix = net.BITCOIN_P2P_PREFIX
    
    version = 0
    
    max_payload_length = 1000000
    
    @property
    def use_checksum(self):
        return self.version >= 209
    
    
    null_order = '\0'*60
    
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
    
    message_version = bitcoin_data.ComposedType([
        ('version', bitcoin_data.StructType('<I')),
        ('services', bitcoin_data.StructType('<Q')),
        ('time', bitcoin_data.StructType('<Q')),
        ('addr_to', bitcoin_data.address_type),
        ('addr_from', bitcoin_data.address_type),
        ('nonce', bitcoin_data.StructType('<Q')),
        ('sub_version_num', bitcoin_data.VarStrType()),
        ('start_height', bitcoin_data.StructType('<I')),
    ])
    def handle_version(self, version, services, time, addr_to, addr_from, nonce, sub_version_num, start_height):
        #print 'VERSION', locals()
        self.version_after = version
        self.send_verack()
    
    message_verack = bitcoin_data.ComposedType([])
    def handle_verack(self):
        self.version = self.version_after
        
        self.ready()
    
    def ready(self):
        self.check_order = deferral.GenericDeferrer(2**256, lambda id, order: self.send_checkorder(id=id, order=order))
        self.submit_order = deferral.GenericDeferrer(2**256, lambda id, order: self.send_submitorder(id=id, order=order))
        self.get_block = deferral.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='block', hash=hash)]))
        self.get_block_header = deferral.ReplyMatcher(lambda hash: self.send_getheaders(version=1, have=[], last=hash))
        self.get_tx = deferral.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='tx', hash=hash)]))
        
        if hasattr(self.factory, 'resetDelay'):
            self.factory.resetDelay()
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(self)
    
    message_inv = bitcoin_data.ComposedType([
        ('invs', bitcoin_data.ListType(bitcoin_data.ComposedType([
            ('type', bitcoin_data.EnumType(bitcoin_data.StructType('<I'), {'tx': 1, 'block': 2})),
            ('hash', bitcoin_data.HashType()),
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
    
    message_getdata = bitcoin_data.ComposedType([
        ('requests', bitcoin_data.ListType(bitcoin_data.ComposedType([
            ('type', bitcoin_data.EnumType(bitcoin_data.StructType('<I'), {'tx': 1, 'block': 2})),
            ('hash', bitcoin_data.HashType()),
        ]))),
    ])
    message_getblocks = bitcoin_data.ComposedType([
        ('version', bitcoin_data.StructType('<I')),
        ('have', bitcoin_data.ListType(bitcoin_data.HashType())),
        ('last', bitcoin_data.PossiblyNoneType(0, bitcoin_data.HashType())),
    ])
    message_getheaders = bitcoin_data.ComposedType([
        ('version', bitcoin_data.StructType('<I')),
        ('have', bitcoin_data.ListType(bitcoin_data.HashType())),
        ('last', bitcoin_data.PossiblyNoneType(0, bitcoin_data.HashType())),
    ])
    message_getaddr = bitcoin_data.ComposedType([])
    message_checkorder = bitcoin_data.ComposedType([
        ('id', bitcoin_data.HashType()),
        ('order', bitcoin_data.FixedStrType(60)), # XXX
    ])
    message_submitorder = bitcoin_data.ComposedType([
        ('id', bitcoin_data.HashType()),
        ('order', bitcoin_data.FixedStrType(60)), # XXX
    ])
    
    message_addr = bitcoin_data.ComposedType([
        ('addrs', bitcoin_data.ListType(bitcoin_data.ComposedType([
            ('timestamp', bitcoin_data.StructType('<I')),
            ('address', bitcoin_data.address_type),
        ]))),
    ])
    def handle_addr(self, addrs):
        for addr in addrs:
            pass
    
    message_tx = bitcoin_data.ComposedType([
        ('tx', bitcoin_data.tx_type),
    ])
    def handle_tx(self, tx):
        self.get_tx.got_response(bitcoin_data.tx_type.hash256(tx), tx)
    
    message_block = bitcoin_data.ComposedType([
        ('block', bitcoin_data.block_type),
    ])
    def handle_block(self, block):
        block_hash = bitcoin_data.block_header_type.hash256(block['header'])
        self.get_block.got_response(block_hash, block)
        self.get_block_header.got_response(block_hash, block['header'])
    
    message_headers = bitcoin_data.ComposedType([
        ('headers', bitcoin_data.ListType(bitcoin_data.block_type)),
    ])
    def handle_headers(self, headers):
        for header in headers:
            header = header['header']
            self.get_block_header.got_response(bitcoin_data.block_header_type.hash256(header), header)
        self.factory.new_headers.happened([header['header'] for header in headers])
    
    message_reply = bitcoin_data.ComposedType([
        ('hash', bitcoin_data.HashType()),
        ('reply',  bitcoin_data.EnumType(bitcoin_data.StructType('<I'), {'success': 0, 'failure': 1, 'denied': 2})),
        ('script', bitcoin_data.PossiblyNoneType('', bitcoin_data.VarStrType())),
    ])
    def handle_reply(self, hash, reply, script):
        self.check_order.got_response(hash, dict(reply=reply, script=script))
        self.submit_order.got_response(hash, dict(reply=reply, script=script))
    
    message_ping = bitcoin_data.ComposedType([])
    def handle_ping(self):
        pass
    
    message_alert = bitcoin_data.ComposedType([
        ('message', bitcoin_data.VarStrType()),
        ('signature', bitcoin_data.VarStrType()),
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
        return cls(bitcoin_data.block_header_type.hash256(header), header['previous_block'])
    
    def __init__(self, hash, previous_hash):
        self.hash, self.previous_hash = hash, previous_hash

class HeightTracker(object):
    '''Point this at a factory and let it take care of getting block heights'''
    
    def __init__(self, factory, backing):
        self.factory = factory
        self.tracker = bitcoin_data.Tracker()
        self.backing = backing
        self.most_recent = None
        
        self._watch1 = self.factory.new_headers.watch(self.heard_headers)
        self._watch2 = self.factory.new_block.watch(self.heard_block)
        
        self.requested = set()
        self._clear_task = task.LoopingCall(self.requested.clear)
        self._clear_task.start(60)
        
        self.last_notified_size = 0
        
        self.updated = variable.Event()
        
        self._load_backing()
        
        self.think()
    
    def _load_backing(self):
        open(self.backing, 'ab').close()
        with open(self.backing, 'rb') as f:
            count = 0
            for line in f:
                try:
                    hash, previous_hash, checksum = (int(x, 16) for x in line.strip().split(' '))
                except Exception:
                    print "skipping over bad data in headers.dat"
                else:
                    if (hash - previous_hash) % 2**256 != checksum:
                        print "checksum failed"
                        continue
                    if previous_hash == 0: previous_hash = None
                    count += 1
                    if count % 10000 == 0 and count: print count
                    if hash not in self.tracker.shares:
                        self.tracker.add(HeaderWrapper(hash, previous_hash))
    
    def think(self):
        highest_head = max(self.tracker.heads, key=lambda h: self.tracker.get_height_and_last(h)[0]) if self.tracker.heads else None
        height, last = self.tracker.get_height_and_last(highest_head)
        cur = highest_head
        cur_height = height
        have = []
        step = 1
        while cur is not None:
            have.append(cur)
            if step > cur_height:
                break
            cur = self.tracker.get_nth_parent_hash(cur, step)
            cur_height -= step
            if len(have) > 10:
                step *= 2
        if height:
            have.append(self.tracker.get_nth_parent_hash(highest_head, height - 1))
        if not have:
            have.append(0)
        self.request(have, None)
        
        for tail in self.tracker.tails:
            if tail is None:
                continue
            self.request([], tail)
        for head in self.tracker.heads:
            if head == highest_head:
                continue
            self.request([head], None)
    
    def heard_headers(self, headers):
        changed = False
        b = open(self.backing, 'ab')
        for header in headers:
            hw = HeaderWrapper.from_header(header)
            if hw.hash in self.tracker.shares:
                continue
            changed = True
            self.tracker.add(hw)
            hash, prev = hw.hash, 0 if hw.previous_hash is None else hw.previous_hash
            b.write('%x %x %x\n' % (hash, prev, (hash - prev) % 2**256))
        b.close()
        if changed:
            self.updated.happened()
        self.think()
        
        if len(self.tracker.shares) > self.last_notified_size + 10:
            print 'Have %i block headers' % len(self.tracker.shares)
            self.last_notified_size = len(self.tracker.shares)
    
    def heard_block(self, block_hash):
        self.request([], block_hash)
    
    @defer.inlineCallbacks
    def request(self, have, last):
        if (tuple(have), last) in self.requested:
            return
        self.requested.add((tuple(have), last))
        (yield self.factory.getProtocol()).send_getheaders(version=1, have=have, last=last)
    
    def getHeight(self, block_hash):
        height, last = self.tracker.get_height_and_last(block_hash)
        if last is not None:
            #self.request([], last)
            raise ValueError()
        return height
    
    def get_min_height(self, block_hash):
        height, last = self.tracker.get_height_and_last(block_hash)
        #if last is not None:
        #    self.request([], last)
        return height
    
    def get_highest_height(self):
        return self.tracker.get_highest_height()
    
    def stop(self):
        self.factory.new_headers.unwatch(self._watch1)
        self.factory.new_block.unwatch(self._watch2)
        self._clear_task.stop()

if __name__ == '__main__':
    factory = ClientFactory(bitcoin_data.Mainnet)
    reactor.connectTCP('127.0.0.1', 8333, factory)
    h = HeightTracker(factory)
    
    @repr
    @apply
    @defer.inlineCallbacks
    def think():
        while True:
            yield deferral.sleep(1)
            print h.get_min_height(0xa285c3cb2a90ac7194cca034512748289e2526d9d7ae6ee7523)
    
    reactor.run()
