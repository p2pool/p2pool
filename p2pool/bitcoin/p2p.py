'''
Implementation of Bitcoin's p2p protocol
'''

from __future__ import division

import hashlib
import random
import struct
import time
import zlib

from twisted.internet import defer, protocol, reactor
from twisted.python import log

from . import data as bitcoin_data
from p2pool.util import variable, datachunker, deferral

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
            
            if self.use_checksum:
                checksum = yield 4
            else:
                checksum = None
            
            payload = yield length
            
            if self.compress:
                try:
                    payload = zlib.decompress(payload)
                except:
                    print 'FAILURE DECOMPRESSING'
                    continue
            
            if checksum is not None:
                if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
                    print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                    print 'INVALID HASH'
                    continue
            
            type_ = getattr(self, "message_" + command, None)
            if type_ is None:
                print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                print 'NO TYPE FOR', repr(command)
                continue
            
            try:
                payload2 = type_.unpack(payload)
            except:
                print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                log.err()
                continue
            
            handler = getattr(self, 'handle_' + command, None)
            if handler is None:
                print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                print 'NO HANDLER FOR', command
                continue
            
            #print 'RECV', command, repr(payload2)[:500]
            
            try:
                handler(**payload2)
            except:
                print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                log.err()
                continue
    
    def sendPacket(self, command, payload2):
        if len(command) >= 12:
            raise ValueError('command too long')
        type_ = getattr(self, "message_" + command, None)
        if type_ is None:
            raise ValueError('invalid command')
        #print 'SEND', command, repr(payload2)[:500]
        payload = type_.pack(payload2)
        if self.use_checksum:
            checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        else:
            checksum = ''
        if self.compress:
            payload = zlib.compress(payload)
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
    
    compress = False
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
                print "Unknown inv type", item
    
    message_getdata = bitcoin_data.ComposedType([
        ('requests', bitcoin_data.ListType(bitcoin_data.ComposedType([
            ('type', bitcoin_data.EnumType(bitcoin_data.StructType('<I'), {'tx': 1, 'block': 2})),
            ('hash', bitcoin_data.HashType()),
        ]))),
    ])
    message_getblocks = bitcoin_data.ComposedType([
        ('version', bitcoin_data.StructType('<I')),
        ('have', bitcoin_data.ListType(bitcoin_data.HashType())),
        ('last', bitcoin_data.PossiblyNone(0, bitcoin_data.HashType())),
    ])
    message_getheaders = bitcoin_data.ComposedType([
        ('version', bitcoin_data.StructType('<I')),
        ('have', bitcoin_data.ListType(bitcoin_data.HashType())),
        ('last', bitcoin_data.PossiblyNone(0, bitcoin_data.HashType())),
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
        ('script', bitcoin_data.PossiblyNone("", bitcoin_data.VarStrType())),
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
        print "ALERT:", (message, signature)
    
    def connectionLost(self, reason):
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(None)

class ClientFactory(protocol.ReconnectingClientFactory):
    protocol = Protocol
    
    maxDelay = 15
    
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
    def __init__(self, header):
        self.hash = bitcoin_data.block_header_type.hash256(header)
        self.previous_hash = header['previous_block']

class HeightTracker(object):
    '''Point this at a factory and let it take care of getting block heights'''
    # XXX think keeps object alive
    
    def __init__(self, factory):
        self.factory = factory
        self.tracker = bitcoin_data.Tracker()
        self.most_recent = None
        
        self.factory.new_headers.watch(self.heard_headers)
        
        self.think()
    
    @defer.inlineCallbacks
    def think(self):
        last = None
        yield self.factory.getProtocol()
        while True:
            highest_head = max(self.tracker.heads, key=lambda h: self.tracker.get_height_and_last(h)[0]) if self.tracker.heads else None
            it = self.tracker.get_chain_known(highest_head)
            have = []
            step = 1
            try:
                cur = it.next()
            except StopIteration:
                cur = None
            while True:
                if cur is None:
                    break
                have.append(cur.hash)
                for i in xrange(step): # XXX inefficient
                    try:
                        cur = it.next()
                    except StopIteration:
                        break
                else:
                    if len(have) > 10:
                        step *= 2
                    continue
                break
            chain = list(self.tracker.get_chain_known(highest_head))
            if chain:
                have.append(chain[-1].hash)
            if not have:
                have.append(0)
            if have == last:
                yield deferral.sleep(1)
                last = None
                continue
            
            last = have
            good_tails = [x for x in self.tracker.tails if x is not None]
            self.request(have, random.choice(good_tails) if good_tails else None)
            for tail in self.tracker.tails:
                if tail is None:
                    continue
                self.request([], tail)
            try:
                yield self.factory.new_headers.get_deferred(timeout=5)
            except defer.TimeoutError:
                pass
    
    def heard_headers(self, headers):
        header2s = map(HeaderWrapper, headers)
        for header2 in header2s:
            self.tracker.add(header2)
        if header2s:
            if self.tracker.get_height_and_last(header2s[-1].hash)[1] is None:
                self.most_recent = header2s[-1].hash
                if random.random() < .6:
                    self.request([header2s[-1].hash], None)
        print len(self.tracker.shares)
    
    def request(self, have, last):
        #print "REQ", ('[' + ', '.join(map(hex, have)) + ']', hex(last) if last is not None else None)
        if self.factory.conn.value is not None:
            self.factory.conn.value.send_getheaders(version=1, have=have, last=last)
    
    #@defer.inlineCallbacks
    #XXX should defer
    def getHeight(self, block_hash):
        height, last = self.tracker.get_height_and_last(block_hash)
        if last is not None:
            self.request([], last)
            raise ValueError()
        return height
    
    def get_min_height(self, block_hash):
        height, last = self.tracker.get_height_and_last(block_hash)
        if last is not None:
            self.request([], last)
        return height
    
    def get_highest_height(self):
        return self.tracker.get_highest_height()

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
            try:
                print h.getHeight(0xa285c3cb2a90ac7194cca034512748289e2526d9d7ae6ee7523)
            except Exception, e:
                log.err()
    
    reactor.run()
