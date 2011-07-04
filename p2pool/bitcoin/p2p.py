'''
Implementation of Bitcoin's p2p protocol
'''

from __future__ import division

import hashlib
import random
import struct
import time
import traceback

from twisted.internet import protocol, reactor

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
                traceback.print_exc()
                continue
            
            handler = getattr(self, 'handle_' + command, None)
            if handler is None:
                print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                print 'NO HANDLER FOR', command
                continue
            
            #print 'RECV', command, payload2
            
            try:
                handler(**payload2)
            except:
                print 'RECV', command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                traceback.print_exc()
                continue
    
    def sendPacket(self, command, payload2={}):
        type_ = getattr(self, "message_" + command, None)
        if type_ is None:
            raise ValueError('invalid command')
        payload = type_.pack(payload2)
        if len(command) >= 12:
            raise ValueError('command too long')
        if self.use_checksum:
            checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        else:
            checksum = ''
        data = self._prefix + struct.pack('<12sI', command, len(payload)) + checksum + payload
        self.transport.write(data)
        #print 'SEND', command, payload2
    
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
    
    @property
    def use_checksum(self):
        return self.version >= 209
    
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
    message_verack = bitcoin_data.ComposedType([])
    message_addr = bitcoin_data.ComposedType([
        ('addrs', bitcoin_data.ListType(bitcoin_data.ComposedType([
            ('timestamp', bitcoin_data.StructType('<I')),
            ('address', bitcoin_data.address_type),
        ]))),
    ])
    message_inv = bitcoin_data.ComposedType([
        ('invs', bitcoin_data.ListType(bitcoin_data.ComposedType([
            ('type', bitcoin_data.EnumType(bitcoin_data.StructType('<I'), {'tx': 1, 'block': 2})),
            ('hash', bitcoin_data.HashType()),
        ]))),
    ])
    message_getdata = bitcoin_data.ComposedType([
        ('requests', bitcoin_data.ListType(bitcoin_data.ComposedType([
            ('type', bitcoin_data.EnumType(bitcoin_data.StructType('<I'), {'tx': 1, 'block': 2})),
            ('hash', bitcoin_data.HashType()),
        ]))),
    ])
    message_getblocks = bitcoin_data.ComposedType([
        ('version', bitcoin_data.StructType('<I')),
        ('have', bitcoin_data.ListType(bitcoin_data.HashType())),
        ('last', bitcoin_data.HashType()),
    ])
    message_getheaders = bitcoin_data.ComposedType([
        ('version', bitcoin_data.StructType('<I')),
        ('have', bitcoin_data.ListType(bitcoin_data.HashType())),
        ('last', bitcoin_data.HashType()),
    ])
    message_tx = bitcoin_data.ComposedType([
        ('tx', bitcoin_data.tx_type),
    ])
    message_block = bitcoin_data.ComposedType([
        ('block', bitcoin_data.block_type),
    ])
    message_headers = bitcoin_data.ComposedType([
        ('headers', bitcoin_data.ListType(bitcoin_data.block_header_type)),
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
    message_reply = bitcoin_data.ComposedType([
        ('hash', bitcoin_data.HashType()),
        ('reply',  bitcoin_data.EnumType(bitcoin_data.StructType('<I'), {'success': 0, 'failure': 1, 'denied': 2})),
        ('script', bitcoin_data.VarStrType()),
    ])
    message_ping = bitcoin_data.ComposedType([])
    message_alert = bitcoin_data.ComposedType([
        ('message', bitcoin_data.VarStrType()),
        ('signature', bitcoin_data.VarStrType()),
    ])
    
    null_order = '\0'*60
    
    def connectionMade(self):
        BaseProtocol.connectionMade(self)
        
        self.send_version(
            version=32200,
            services=1,
            time=int(time.time()),
            addr_to=dict(
                services=1,
                address='::ffff:' + self.transport.getPeer().host,
                port=self.transport.getPeer().port,
            ),
            addr_from=dict(
                services=1,
                address='::ffff:' + self.transport.getHost().host,
                port=self.transport.getHost().port,
            ),
            nonce=random.randrange(2**64),
            sub_version_num='',
            start_height=0,
        )
    
    def handle_version(self, version, services, time, addr_to, addr_from, nonce, sub_version_num, start_height):
        #print 'VERSION', locals()
        self.version_after = version
        self.send_verack()
    
    def handle_verack(self):
        self.version = self.version_after
        
        # connection ready
        self.check_order = deferral.GenericDeferrer(2**256, lambda id, order: self.send_checkorder(id=id, order=order))
        self.submit_order = deferral.GenericDeferrer(2**256, lambda id, order: self.send_submitorder(id=id, order=order))
        self.get_block = deferral.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='block', hash=hash)]))
        self.get_block_header = deferral.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='block', hash=hash)]))
        
        if hasattr(self.factory, 'resetDelay'):
            self.factory.resetDelay()
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(self)
    
    def handle_inv(self, invs):
        for inv in invs:
            #print 'INV', item['type'], hex(item['hash'])
            self.send_getdata(requests=[inv])
    
    def handle_addr(self, addrs):
        for addr in addrs:
            pass#print 'ADDR', addr
    
    def handle_reply(self, hash, reply, script):
        self.check_order.got_response(hash, dict(reply=reply, script=script))
        self.submit_order.got_response(hash, dict(reply=reply, script=script))
    
    def handle_tx(self, tx):
        #print 'TX', hex(merkle_hash([tx])), tx
        self.factory.new_tx.happened(tx)
    
    def handle_block(self, block):
        self.get_block.got_response(bitcoin_data.block_hash(block['header']), block)
        self.factory.new_block.happened(block)
    
    def handle_ping(self):
        pass
    
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
    
    def buildProtocol(self, addr):
        p = self.protocol(self.net)
        p.factory = self
        return p
    
    def gotConnection(self, conn):
        self.conn.set(conn)
    
    def getProtocol(self):
        return self.conn.get_not_none()

if __name__ == '__main__':
    factory = ClientFactory()
    reactor.connectTCP('127.0.0.1', 8333, factory)
    
    reactor.run()
