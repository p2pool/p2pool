'''
Implementation of Bitcoin's p2p protocol
'''

from __future__ import division

import hashlib
import random
import StringIO
import socket
import struct
import time
import traceback

from twisted.internet import defer, protocol, reactor

import expiring_dict
import util

class EarlyEnd(Exception):
    pass

class LateEnd(Exception):
    pass

class Type(object):
    def _unpack(self, data, ignore_extra=False):
        f = StringIO.StringIO(data)
        obj = self.read(f)
        
        if not ignore_extra:
            if f.tell() != len(data):
                raise LateEnd('underread ' + repr((self, data)))
        
        return obj
    
    def unpack(self, data, ignore_extra=False):
        obj = self._unpack(data, ignore_extra)
        assert self._unpack(self._pack(obj)) == obj
        return obj
    
    def _pack(self, obj):
        f = StringIO.StringIO()
        self.write(f, obj)
        
        data = f.getvalue()
        
        return data
    
    def pack(self, obj):
        data = self._pack(obj)
        assert self._unpack(data) == obj
        return data

class VarIntType(Type):
    def read(self, file):
        data = file.read(1)
        if len(data) != 1:
            raise EarlyEnd()
        first, = struct.unpack('<B', data)
        if first == 0xff: desc = '<Q'
        elif first == 0xfe: desc = '<I'
        elif first == 0xfd: desc = '<H'
        else: return first
        length = struct.calcsize(desc)
        data = file.read(length)
        if len(data) != length:
            raise EarlyEnd()
        return struct.unpack(desc, data)[0]
    
    def write(self, file, item):
        if item < 0xfd:
            file.write(struct.pack('<B', item))
        elif item <= 0xffff:
            file.write(struct.pack('<BH', 0xfd, item))
        elif item <= 0xffffffff:
            file.write(struct.pack('<BI', 0xfe, item))
        elif item <= 0xffffffffffffffff:
            file.write(struct.pack('<BQ', 0xff, item))
        else:
            raise ValueError('int too large for varint')

class VarStrType(Type):
    def read(self, file):
        length = VarIntType().read(file)
        res = file.read(length)
        if len(res) != length:
            raise EarlyEnd('var str not long enough %r' % ((length, len(res), res),))
        return res
    
    def write(self, file, item):
        VarIntType().write(file, len(item))
        file.write(item)

class FixedStrType(Type):
    def __init__(self, length):
        self.length = length
    
    def read(self, file):
        res = file.read(self.length)
        if len(res) != self.length:
            raise EarlyEnd('early EOF!')
        return res
    
    def write(self, file, item):
        if len(item) != self.length:
            raise ValueError('incorrect length!')
        file.write(item)

class EnumType(Type):
    def __init__(self, inner, values):
        self.inner = inner
        self.values = values
        
        self.keys = {}
        for k, v in values.iteritems():
            if v in self.keys:
                raise ValueError('duplicate value in values')
            self.keys[v] = k
    
    def read(self, file):
        return self.keys[self.inner.read(file)]
    
    def write(self, file, item):
        self.inner.write(file, self.values[item])

class HashType(Type):
    def read(self, file):
        data = file.read(256//8)
        if len(data) != 256//8:
            raise EarlyEnd('incorrect length!')
        return int(data[::-1].encode('hex'), 16)
    
    def write(self, file, item):
        file.write(('%064x' % (item,)).decode('hex')[::-1])

class ShortHashType(Type):
    def read(self, file):
        data = file.read(160//8)
        if len(data) != 160//8:
            raise EarlyEnd('incorrect length!')
        return int(data[::-1].encode('hex'), 16)
    
    def write(self, file, item):
        file.write(('%020x' % (item,)).decode('hex')[::-1])

class ListType(Type):
    def __init__(self, type):
        self.type = type
    
    def read(self, file):
        length = VarIntType().read(file)
        return [self.type.read(file) for i in xrange(length)]
    
    def write(self, file, item):
        VarIntType().write(file, len(item))
        for subitem in item:
            self.type.write(file, subitem)

class StructType(Type):
    def __init__(self, desc):
        self.desc = desc
        self.length = struct.calcsize(self.desc)
    
    def read(self, file):
        data = file.read(self.length)
        if len(data) != self.length:
            raise EarlyEnd()
        res, = struct.unpack(self.desc, data)
        return res
    
    def write(self, file, item):
        data = struct.pack(self.desc, item)
        if struct.unpack(self.desc, data)[0] != item:
            # special test because struct doesn't error on some overflows
            raise ValueError("item didn't survive pack cycle (%r)" % (item,))
        file.write(data)

class IPV6AddressType(Type):
    def read(self, file):
        data = file.read(16)
        if len(data) != 16:
            raise EarlyEnd()
        if data[:12] != '00000000000000000000ffff'.decode('hex'):
            raise ValueError("ipv6 addresses not supported yet")
        return '::ffff:' + '.'.join(str(ord(x)) for x in data[12:])
    
    def write(self, file, item):
        prefix = '::ffff:'
        if not item.startswith(prefix):
            raise ValueError("ipv6 addresses not supported yet")
        item = item[len(prefix):]
        bits = map(int, item.split('.'))
        if len(bits) != 4:
            raise ValueError("invalid address: %r" % (bits,))
        data = '00000000000000000000ffff'.decode('hex') + ''.join(chr(x) for x in bits)
        assert len(data) == 16, len(data)
        file.write(data)

class ComposedType(Type):
    def __init__(self, fields):
        self.fields = fields
    
    def read(self, file):
        item = {}
        for key, type_ in self.fields:
            item[key] = type_.read(file)
        return item
    
    def write(self, file, item):
        for key, type_ in self.fields:
            type_.write(file, item[key])

address = ComposedType([
    ('services', StructType('<Q')),
    ('address', IPV6AddressType()),
    ('port', StructType('>H')),
])

tx = ComposedType([
    ('version', StructType('<I')),
    ('tx_ins', ListType(ComposedType([
        ('previous_output', ComposedType([
            ('hash', HashType()),
            ('index', StructType('<I')),
        ])),
        ('script', VarStrType()),
        ('sequence', StructType('<I')),
    ]))),
    ('tx_outs', ListType(ComposedType([
        ('value', StructType('<Q')),
        ('script', VarStrType()),
    ]))),
    ('lock_time', StructType('<I')),
])

block_header = ComposedType([
    ('version', StructType('<I')),
    ('previous_block', HashType()),
    ('merkle_root', HashType()),
    ('timestamp', StructType('<I')),
    ('bits', StructType('<I')),
    ('nonce', StructType('<I')),
])

block = ComposedType([
    ('header', block_header),
    ('txns', ListType(tx)),
])

def doublesha(data):
    return HashType().unpack(hashlib.sha256(hashlib.sha256(data).digest()).digest())

def ripemdsha(data):
    return ShortHashType().unpack(hashlib.new('ripemd160', hashlib.sha256(data).digest()).digest())

merkle_record = ComposedType([
    ('left', HashType()),
    ('right', HashType()),
])

def merkle_hash(txn_list):
    hash_list = [doublesha(tx.pack(txn)) for txn in txn_list]
    while len(hash_list) > 1:
        hash_list = [doublesha(merkle_record.pack(dict(left=left, right=left if right is None else right)))
            for left, right in zip(hash_list[::2], hash_list[1::2] + [None])]
    return hash_list[0]

def block_hash(header):
    return doublesha(block_header.pack(header))

class BaseProtocol(protocol.Protocol):
    def connectionMade(self):
        self.dataReceived = util.DataChunker(self.dataReceiver())
    
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
            
            type_ = self.message_types.get(command, None)
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
        payload = self.message_types[command].pack(payload2)
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
    def __init__(self, testnet=False):
        if testnet:
            self._prefix = 'fabfb5da'.decode('hex')
        else:
            self._prefix = 'f9beb4d9'.decode('hex')
    
    version = 0
    
    @property
    def use_checksum(self):
        return self.version >= 209
    
    message_types = {
        'version': ComposedType([
            ('version', StructType('<I')),
            ('services', StructType('<Q')),
            ('time', StructType('<Q')),
            ('addr_to', address),
            ('addr_from', address),
            ('nonce', StructType('<Q')),
            ('sub_version_num', VarStrType()),
            ('start_height', StructType('<I')),
        ]),
        'verack': ComposedType([]),
        'addr': ComposedType([
            ('addrs', ListType(ComposedType([
                ('timestamp', StructType('<I')),
                ('address', address),
            ]))),
        ]),
        'inv': ComposedType([
            ('invs', ListType(ComposedType([
                ('type', EnumType(StructType('<I'), {'tx': 1, 'block': 2})),
                ('hash', HashType()),
            ]))),
        ]),
        'getdata': ComposedType([
            ('requests', ListType(ComposedType([
                ('type', EnumType(StructType('<I'), {'tx': 1, 'block': 2})),
                ('hash', HashType()),
            ]))),
        ]),
        'getblocks': ComposedType([
            ('version', StructType('<I')),
            ('have', ListType(HashType())),
            ('last', HashType()),
        ]),
        'getheaders': ComposedType([
            ('version', StructType('<I')),
            ('have', ListType(HashType())),
            ('last', HashType()),
        ]),
        'tx': ComposedType([
            ('tx', tx),
        ]),
        'block': ComposedType([
            ('block', block),
        ]),
        'headers': ComposedType([
            ('headers', ListType(block_header)),
        ]),
        'getaddr': ComposedType([]),
        'checkorder': ComposedType([
            ('id', HashType()),
            ('order', FixedStrType(60)), # XXX
        ]),
        'submitorder': ComposedType([
            ('id', HashType()),
            ('order', FixedStrType(60)), # XXX
        ]),
        'reply': ComposedType([
            ('hash', HashType()),
            ('reply',  EnumType(StructType('<I'), {'success': 0, 'failure': 1, 'denied': 2})),
            ('script', VarStrType()),
        ]),
        'ping': ComposedType([]),
        'alert': ComposedType([
            ('message', VarStrType()),
            ('signature', VarStrType()),
        ]),
    }
    
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
        self.check_order = util.GenericDeferrer(2**256, lambda id, order: self.send_checkorder(id=id, order=order))
        self.submit_order = util.GenericDeferrer(2**256, lambda id, order: self.send_submitorder(id=id, order=order))
        self.get_block = util.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='block', hash=hash)]))
        self.get_block_header = util.ReplyMatcher(lambda hash: self.send_getdata(requests=[dict(type='block', hash=hash)]))
        
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
        pass#print 'TX', hex(merkle_hash([tx])), tx
    
    def handle_block(self, block):
        self.get_block.got_response(block_hash(block['header']), block)
        self.factory.new_block.happened(block)
    
    def handle_ping(self):
        pass
    
    def connectionLost(self, reason):
        if hasattr(self.factory, 'gotConnection'):
            self.factory.gotConnection(None)

class ProtocolInv(Protocol):
    def __init__(self, *args, **kwargs):
        Protocol.__init__(self, *args, **kwargs)
        
        self.inv = expiring_dict.ExpiringDict(600)
    
    def handle_getdata(self, requests):
        for inv in requests:
            type_, hash_ = inv['type'], inv['hash']
            if (type_, hash_) in self.inv:
                print 'bitcoind requested %s %x, sent' % (type_, hash_)
                self.sendPacket(type_, {type_: self.inv[(type_, hash_)]})
            else:
                print 'bitcoind requested %s %x, but not found' % (type_, hash_)
    
    def addInv(self, type_, data):
        if type_ == 'block':
            hash_ = block_hash(data['header'])
        elif type_ == 'tx':
            hash_ = merkle_hash([data])
        else:
            raise ValueError('invalid type: %r' % (type_,))
        self.inv[(type_, hash_)] = data
        self.send_inv(invs=[dict(type=type_, hash=hash_)])

class ClientFactory(protocol.ReconnectingClientFactory):
    protocol = ProtocolInv
    
    maxDelay = 15
    
    conn = None
    waiters = None
    
    def __init__(self, testnet=False):
        #protocol.ReconnectingClientFactory.__init__(self)
        self.testnet = testnet
        self.new_block = util.Event()
    
    def buildProtocol(self, addr):
        p = self.protocol(self.testnet)
        p.factory = self
        return p
    
    def gotConnection(self, conn):
        self.conn = conn
        if conn is not None:
            if self.waiters is None:
                self.waiters = []
            
            waiters = self.waiters
            self.waiters = []
            
            for df in waiters:
                df.callback(conn)
    
    def getProtocol(self):
        df = defer.Deferred()
        
        if self.conn is not None:
            df.callback(self.conn)
        else:
            if self.waiters is None:
                self.waiters = []
            self.waiters.append(df)
        
        return df

if __name__ == '__main__':
    factory = ClientFactory()
    reactor.connectTCP('127.0.0.1', 8333, factory)
    
    reactor.run()
