import struct
import socket
import random
import StringIO
import hashlib
import time

from twisted.internet import protocol, reactor
from twisted.python import failure

def hex(n):
    return '0x%x' % n

class VarIntType(object):
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
    def pack(self, item):
        if item < 0xfd:
            return struct.pack("<B", item)
        elif item <= 0xffff:
            return struct.pack("<BH", 0xfd, item)
        elif item <= 0xffffffff:
            return struct.pack("<BI", 0xfe, item)
        elif item <= 0xffffffffffffffff:
            return struct.pack("<BQ", 0xff, item)
        else:
            raise ValueError("int too large for varint")

class VarStrType(object):
    def read(self, file):
        length = VarIntType().read(file)
        res = file.read(length)
        if len(res) != length:
            raise ValueError()
        return res
    def pack(self, item):
        return VarIntType().pack(len(item)) + item

class FixedStrType(object):
    def __init__(self, length):
        self.length = length
    def read(self, file):
        return file.read(self.length)
    def pack(self, item):
        if len(item) != self.length:
            raise ValueError("incorrect length!")
        return item

class EnumType(object):
    def __init__(self, inner, map):
        self.inner = inner
        self.map = map
        self.revmap = dict((v, k) for k, v in map.iteritems())
    def read(self, file):
        inner = self.inner.read(file)
        return self.map[inner]
    def pack(self, item):
        return self.inner.pack(self.revmap[item])

class Hash(object):
    def read(self, file):
        data = file.read(256//8)
        if len(data) != 256//8:
            raise ValueError("incorrect length!")
        return int(data[::-1].encode('hex'), 16)
    def pack(self, item):
        return ('%064x' % (item,)).decode('hex')[::-1]

class ListType(object):
    def __init__(self, type):
        self.type = type
    def read(self, file):
        length = VarIntType().read(file)
        return [self.type.read(file) for i in xrange(length)]
    def pack(self, item):
        return VarIntType().pack(len(item)) + ''.join(map(self.type.pack, item))

class StructType(object):
    def __init__(self, desc):
        self.desc = desc
    def read(self, file):
        data = file.read(struct.calcsize(self.desc))
        res, = struct.unpack(self.desc, data)
        return res
    def pack(self, item):
        return struct.pack(self.desc, item)

class IPV6AddressType(object):
    def read(self, file):
        return socket.inet_ntop(socket.AF_INET6, file.read(16))
    def pack(self, item):
        return socket.inet_pton(socket.AF_INET6, item)

class ComposedType(object):
    def __init__(self, fields):
        self.fields = fields
    def read(self, file):
        result = {}
        for key, type in self.fields:
            result[key] = type.read(file)
        return result
    def pack(self, item):
        return ''.join(type.pack(item[key]) for key, type in self.fields)

address = ComposedType([
    ('services', StructType('<Q')),
    ('address', IPV6AddressType()),
    ('port', StructType('>H')),
])

merkle_record = ComposedType([
    ('left', Hash()),
    ('right', Hash()),
])

inv_vector = ComposedType([
    ('type', EnumType(StructType('<I'), {1: "tx", 2: "block"})),
    ('hash', Hash()),
])

outpoint = ComposedType([
    ('hash', Hash()),
    ('index', StructType('<I')),
])

tx_in = ComposedType([
    ('previous_output', outpoint),
    ('script', VarStrType()),
    ('sequence', StructType('<I')),
])

tx_out = ComposedType([
    ('value', StructType('<Q')),
    ('script', VarStrType()),
])

tx = ComposedType([
    ('version', StructType('<I')),
    ('tx_ins', ListType(tx_in)),
    ('tx_outs', ListType(tx_out)),
    ('lock_time', StructType('<I')),
])

block_headers = ComposedType([
    ('version', StructType('<I')),
    ('previous_block', Hash()),
    ('merkle_root', Hash()),
    ('timestamp', StructType('<I')),
    ('bits', StructType('<I')),
    ('nonce', StructType('<I')),
])

message_types = {
    'version': ComposedType([
        ('version', StructType('<I')),
        ('services', StructType('<Q')),
        ('timestamp', StructType('<Q')),
        ('addr_me', address),
        ('addr_you', address),
        ('nonce', StructType('<Q')),
        ('sub_version_num', VarStrType()),
        ('start_height', StructType('<I')),
    ]),
    'verack': ComposedType([]),
    'addr': ListType(ComposedType([
        ('timestamp', StructType('<I')),
        ('address', address),
    ])),
    'inv': ListType(inv_vector),
    'getdata': ListType(inv_vector),
    'getblocks': ComposedType([
        # XXX has version here?
        ('have', ListType(Hash())),
        ('last', Hash()),
    ]),
    'getheaders': ComposedType([
        # XXX has version here?
        ('have', ListType(Hash())),
        ('last', Hash()),
    ]),
    'tx': tx,
    'block': ComposedType([
        ('headers', block_headers),
        ('txns', ListType(tx)),
    ]),
    'headers': ListType(block_headers),
    'getaddr': ComposedType([]),
    'checkorder': ComposedType([
        ('hash', Hash()),
        ('order', FixedStrType(60)),
    ]),
    'submitorder': ComposedType([
        ('hash', Hash()),
        ('order', FixedStrType(60)),
    ]),
    'reply': ComposedType([
        ('hash', Hash()),
        ('reply',  EnumType(StructType('<I'), {0: 'success', 1: 'failure', 2: 'denied'})),
        ('script', VarStrType()),
    ]),
    'ping': ComposedType([]),
    'alert': ComposedType([
        ('message', VarStrType()),
        ('signature', VarStrType()),
    ]),
}

def doublesha(data):
    return int(hashlib.sha256(hashlib.sha256(data).digest()).digest()[::-1].encode('hex'), 16)

def merkle_hash(txn_list):
    hash_list = [doublesha(tx.pack(txn)) for txn in txn_list]
    while len(hash_list) > 1:
        hash_list = [doublesha(merkle_record.pack(dict(left=left, right=left if right is None else right)))
            for left, right in zip(hash_list[::2], hash_list[1::2] + [None])]
    return hash_list[0]

class Protocol(protocol.Protocol):
    _prefix = '\xf9\xbe\xb4\xd9'
    version = 0
    buf = ""
    
    def connectionMade(self):
        self.checkorder = GenericDeferrer(5, lambda id, (order,): self.sendPacket("checkorder", dict(hash=id, order=order))
        self.receiver = self.dataReceiver()
        self.receiver_wants = self.receiver.next()
        self.receiver_buf = ""
        
        self.sendPacket("version", dict(
            version=32200,
            services=1,
            timestamp=int(time.time()),
            addr_me=dict(
                services=1,
                address="::ffff:127.0.0.1",
                port=self.transport.getHost().port,
            ),
            addr_you=dict(
                services=1,
                address="::ffff:127.0.0.1",
                port=self.transport.getPeer().port,
            ),
            nonce=random.randrange(2**64),
            sub_version_num="",
            start_height=0,
        ))
        reactor.callLater(1, self.sendPacket, "checkorder", dict(hash=42, order='\0'*60))
    
    def dataReceived(self, data):
        pos = 0
        receiver_wants = self.receiver_wants
        buf = self.receiver_buf + data
        
        while True:
            if pos + receiver_wants > len(buf):
                break
            new_receiver_wants = self.receiver.send(buf[pos:pos + receiver_wants])
            pos += receiver_wants
            receiver_wants = new_receiver_wants
        
        self.receiver_buf = buf[pos:]
        self.receiver_wants = receiver_wants
    
    def dataReceiver(self):
        while True:
            start = yield 4
            junk = ""
            while start != self._prefix:
                start = start + (yield 1)
                junk += start[:-4]
                start = start[-4:]
            if junk:
                print "JUNK", repr(junk)
            
            command = (yield 12).rstrip('\0')
            length, = struct.unpack("<I", (yield 4))
            
            if self.version >= 209:
                checksum = yield 4
            else:
                checksum = None
            
            payload = yield length
            
            if checksum is not None:
                if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
                    print "RECV", command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                    print "INVALID HASH"
                    continue
            
            type = message_types.get(command, None)
            if type is None:
                print "ERROR: NO TYPE FOR", repr(command)
                continue
            f = StringIO.StringIO(payload)
            try:
                payload2 = type.read(f)
            except:
                import traceback
                traceback.print_exc()
                continue
            if f.tell() != len(payload):
                print "ERROR: UNDERREAD", repr(command), f.tell(), len(payload)
                continue
            
            handler = getattr(self, "handle_" + command, None)
            if handler is None:
                print "RECV", command, checksum.encode('hex') if checksum is not None else None, repr(payload.encode('hex')), len(payload)
                print self, "has no handler for", command
            else:
                handler(payload2)
    
    def handle_version(self, payload):
        #print "VERSION", payload
        self.version_after = payload['version']
        self.sendPacket("verack")
    
    def handle_verack(self, payload):
        self.version = self.version_after
    
    def handle_inv(self, payload):
        for item in payload:
            print "INV", item['type'], hex(item['hash'])
            self.sendPacket("getdata", [item])
    
    def handle_addr(self, payload):
        for addr in payload:
            pass#print "ADDR", addr
    
    def handle_reply(self, payload):
        print "REPLY", payload
    
    def handle_tx(self, payload):
        pass#print "TX", hex(doublesha(tx.pack(payload))), payload
    
    def handle_block(self, payload):
        #print "BLOCK", hex(doublesha(block_headers.pack(payload['headers'])))
        #print payload
        #print merkle_hash(payload['txns'])
        #print
        pass
    
    def handle_ping(self, payload):
        pass
    
    def sendPacket(self, command, payload2={}):
        payload = message_types[command].pack(payload2)
        if len(command) >= 12:
            raise ValueError("command too long")
        if self.version >= 209:
            checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        else:
            checksum = ""
        data = self._prefix + struct.pack("<12sI", command, len(payload)) + checksum + payload
        self.transport.write(data)
        #print "SEND", command, repr(payload.encode('hex'))

class GenericDeferrer(object):
    def __init__(self, timeout, func, max_id):
        self.timeout = timeout
        self.func = func
        self.max_id = max_id
        self.map = {}
    def __call__(self, *ask):
        while True:
            id = random.randrange(self.max_id)
            if id not in self.map:
                break
        df = defer.Deferred()
        def timeout():
            df.errback(fail.Failure(defer.TimeoutError()))
        timer = reactor.callLater(self.timeout, timeout)
        self.func(id, ask)
        self.map[id] = df, timer
        return df
    def gotResponse(self, id, resp):
        if id not in self.map:
            return # XXX
        df = self.map[id]
        df.callback(resp)

if __name__ == "__main__":
    factory = protocol.ClientFactory()
    factory.protocol = Protocol
    reactor.connectTCP("127.0.0.1", 8333, factory)
    
    reactor.run()
