"""
Implementation of Bitcoin's p2p protocol
"""

import struct
import socket
import random
import cStringIO as StringIO
import hashlib
import time
import traceback

from twisted.internet import protocol, reactor, defer

import util

class Type(object):
    def _unpack(self, data, ignore_extra=False):
        f = StringIO.StringIO(data)
        obj = self.read(f)
        
        if not ignore_extra:
            if f.tell() != len(data):
                raise ValueError("underread " + repr((self, data)))
        
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
        first, = struct.unpack("<B", file.read(1))
        if first == 0xff:
            return struct.unpack("<Q", file.read(8))[0]
        elif first == 0xfe:
            return struct.unpack("<I", file.read(4))[0]
        elif first == 0xfd:
            return struct.unpack("<H", file.read(2))[0]
        else:
            return first
    
    def write(self, file, item):
        if item < 0xfd:
            file.write(struct.pack("<B", item))
        elif item <= 0xffff:
            file.write(struct.pack("<BH", 0xfd, item))
        elif item <= 0xffffffff:
            file.write(struct.pack("<BI", 0xfe, item))
        elif item <= 0xffffffffffffffff:
            file.write(struct.pack("<BQ", 0xff, item))
        else:
            raise ValueError("int too large for varint")

class VarStrType(Type):
    def read(self, file):
        length = VarIntType().read(file)
        res = file.read(length)
        if len(res) != length:
            raise ValueError("var str not long enough %r" % ((length, len(res), res),))
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
            raise ValueError("early EOF!")
        return res
    
    def write(self, file, item):
        if len(item) != self.length:
            raise ValueError("incorrect length!")
        file.write(item)

class EnumType(Type):
    def __init__(self, inner, values):
        self.inner = inner
        self.values = values
        
        self.keys = {}
        for k, v in values.iteritems():
            if v in self.keys:
                raise ValueError("duplicate value in values")
            self.keys[v] = k
    
    def read(self, file):
        return self.keys[self.inner.read(file)]
    
    def write(self, file, item):
        self.inner.write(file, self.values[item])

class HashType(Type):
    def read(self, file):
        data = file.read(256//8)
        if len(data) != 256//8:
            raise ValueError("incorrect length!")
        return int(data[::-1].encode('hex'), 16)
    
    def write(self, file, item):
        file.write(('%064x' % (item,)).decode('hex')[::-1])

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
    
    def read(self, file):
        data = file.read(struct.calcsize(self.desc))
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
        return socket.inet_ntop(socket.AF_INET6, file.read(16))
    
    def write(self, file, item):
        file.write(socket.inet_pton(socket.AF_INET6, item))

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

block_headers = ComposedType([
    ('version', StructType('<I')),
    ('previous_block', HashType()),
    ('merkle_root', HashType()),
    ('timestamp', StructType('<I')),
    ('bits', StructType('<I')),
    ('nonce', StructType('<I')),
])

block = ComposedType([
    ('headers', block_headers),
    ('txns', ListType(tx)),
])

def doublesha(data):
    return HashType().unpack(hashlib.sha256(hashlib.sha256(data).digest()).digest())

def merkle_hash(txn_list):
    merkle_record = ComposedType([
        ('left', HashType()),
        ('right', HashType()),
    ])
    
    hash_list = [doublesha(tx.pack(txn)) for txn in txn_list]
    while len(hash_list) > 1:
        hash_list = [doublesha(merkle_record.pack(dict(left=left, right=left if right is None else right)))
            for left, right in zip(hash_list[::2], hash_list[1::2] + [None])]
    return hash_list[0]

def block_hash(headers):
    return doublesha(block_headers.pack(headers))

class BaseProtocol(protocol.Protocol):
    def connectionMade(self):
        self.dataReceived = util.DataChunker(self.dataReceiver())
    
    def dataReceiver(self):
        while True:
            start = ""
            while start != self._prefix:
                start = (start + (yield 1))[-4:]
            
            command = (yield 12).rstrip('\0')
            length, = struct.unpack("<I", (yield 4))
            
            if self.use_checksum:
                checksum = yield 4
            else:
                checksum = None
            
            payload = yield length
            
            if checksum is not None:
                if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
                    print "RECV", command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                    print "INVALID HASH"
                    continue
            
            type_ = self.message_types.get(command, None)
            if type_ is None:
                print "RECV", command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                print "NO TYPE FOR", repr(command)
                continue
            
            try:
                payload2 = type_.unpack(payload)
            except:
                print "RECV", command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                traceback.print_exc()
                continue
            
            handler = getattr(self, "handle_" + command, None)
            if handler is None:
                print "RECV", command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                print "NO HANDLER FOR", command
                continue
            
            
            #print "RECV", command, payload2
            
            try:
                handler(payload2)
            except:
                print "RECV", command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                traceback.print_exc()
                continue
    
    def sendPacket(self, command, payload2={}):
        payload = self.message_types[command].pack(payload2)
        if len(command) >= 12:
            raise ValueError("command too long")
        if self.use_checksum:
            checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        else:
            checksum = ""
        data = self._prefix + struct.pack("<12sI", command, len(payload)) + checksum + payload
        self.transport.write(data)
        #print "SEND", command, payload2

class Protocol(BaseProtocol):
    _prefix = '\xf9\xbe\xb4\xd9'
    
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
        'addr': ListType(ComposedType([
            ('timestamp', StructType('<I')),
            ('address', address),
        ])),
        'inv': ListType(ComposedType([
            ('type', EnumType(StructType('<I'), {"tx": 1, "block": 2})),
            ('hash', HashType()),
        ])),
        'getdata': ListType(ComposedType([
            ('type', EnumType(StructType('<I'), {"tx": 1, "block": 2})),
            ('hash', HashType()),
        ])),
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
        'tx': tx,
        'block': block,
        'headers': ListType(block_headers),
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
    
    def connectionMade(self):
        BaseProtocol.connectionMade(self)
        
        self.sendPacket("version", dict(
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
            sub_version_num="",
            start_height=0,
        ))
    
    def handle_version(self, payload):
        #print "VERSION", payload
        self.version_after = payload['version']
        self.sendPacket("verack")
    
    def handle_verack(self, payload):
        self.version = self.version_after
        
        # connection ready
        self.check_order = util.GenericDeferrer(2**256, lambda id, order: self.sendPacket("checkorder", dict(id=id, order=order)))
        self.submit_order = util.GenericDeferrer(2**256, lambda id, order: self.sendPacket("submitorder", dict(id=id, order=order)))
        self.get_block = util.ReplyMatcher(lambda hash: self.sendPacket("getdata", [dict(type="block", hash=hash)]))
        self.get_block_headers = util.ReplyMatcher(lambda hash: self.sendPacket("getdata", [dict(type="block", hash=hash)]))
        
        if hasattr(self.factory, "resetDelay"):
            self.factory.resetDelay()
        if hasattr(self.factory, "gotConnection"):
            self.factory.gotConnection(self)
    
    def handle_inv(self, payload):
        for item in payload:
            #print "INV", item['type'], hex(item['hash'])
            self.sendPacket("getdata", [item])
    
    def handle_addr(self, payload):
        for addr in payload:
            pass#print "ADDR", addr
    
    def handle_reply(self, payload):
        hash_ = payload.pop('hash')
        self.check_order.got_response(hash_, payload)
        self.submit_order.got_response(hash_, payload)
    
    def handle_tx(self, payload):
        pass#print "TX", hex(merkle_hash([payload])), payload
    
    def handle_block(self, payload):
        self.get_block.got_response(block_hash(payload['headers']), payload)
        #print "BLOCK", hex(block_hash(payload['headers']))
        #print payload
        #print merkle_hash(payload['txns'])
        #print
        self.factory.new_block.happened(payload)
    
    def handle_ping(self, payload):
        pass
    
    def connectionLost(self, reason):
        if hasattr(self.factory, "gotConnection"):
            self.factory.gotConnection(None)

class ProtocolInv(Protocol):
    inv = None
    
    def handle_getdata(invs):
        if self.inv is None: self.inv = {}
        for inv in invs:
            type_, hash_ = inv['type'], inv['hash']
            if (type_, hash_) in self.inv:
                self.sendPacket(type_, self.inv[(type_, hash_)])
    
    def addInv(self, type_, data):
        if self.inv is None: self.inv = {}
        if type_ == "block":
            hash_ = block_hash(data['headers'])
        elif type_ == "tx":
            hash_ = merkle_hash([data])
        else:
            raise ValueError("invalid type: %r" % (type_,))
        self.inv[(type_, hash_)] = data
        self.sendPacket("inv", [dict(type=type_, hash=hash_)])

class ClientFactory(protocol.ReconnectingClientFactory):
    protocol = ProtocolInv
    
    maxDelay = 15
    
    conn = None
    waiters = None
    
    def __init__(self):
        #protocol.ReconnectingClientFactory.__init__(self)
        self.new_block = util.Event()
    
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

if __name__ == "__main__":
    factory = ClientFactory()
    reactor.connectTCP("127.0.0.1", 8333, factory)
    
    reactor.run()
