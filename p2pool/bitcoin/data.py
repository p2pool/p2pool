from __future__ import division

import struct
import StringIO
import hashlib

from . import base58
from p2pool.util import bases

class EarlyEnd(Exception):
    pass

class LateEnd(Exception):
    pass

class Type(object):
    # the same data can have only one unpacked representation, but multiple packed binary representations
    
    def _unpack(self, data):
        f = StringIO.StringIO(data)
        
        obj = self.read(f)
        
        if f.tell() != len(data):
            raise LateEnd('underread ' + repr((self, data)))
        
        return obj
    
    def unpack(self, data):
        obj = self._unpack(data)
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
    
    
    def pack_base58(self, obj):
        return base58.base58_encode(self.pack(obj))
    
    def unpack_base58(self, base58_data):
        return self.unpack(base58.base58_decode(base58_data))
        
    
    def hash160(self, obj):
        return ripemdsha(self.pack(obj))
    
    def hash256(self, obj):
        return doublesha(self.pack(obj))

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
        if item >= 2**256:
            raise ValueError("invalid hash value")
        file.write(('%064x' % (item,)).decode('hex')[::-1])

class ShortHashType(Type):
    def read(self, file):
        data = file.read(160//8)
        if len(data) != 160//8:
            raise EarlyEnd('incorrect length!')
        return int(data[::-1].encode('hex'), 16)
    
    def write(self, file, item):
        if item >= 2**160:
            raise ValueError("invalid hash value")
        file.write(('%040x' % (item,)).decode('hex')[::-1])

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

class ChecksummedType(Type):
    def __init__(self, inner):
        self.inner = inner
    
    def read(self, file):
        obj = self.inner.read(file)
        data = self.inner.pack(obj)
        
        if file.read(4) != hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]:
            raise ValueError("invalid checksum")
        
        return obj
    
    def write(self, file, item):
        data = self.inner.pack(item)
        file.write(data)
        file.write(hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4])

address_type = ComposedType([
    ('services', StructType('<Q')),
    ('address', IPV6AddressType()),
    ('port', StructType('>H')),
])

tx_type = ComposedType([
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

block_header_type = ComposedType([
    ('version', StructType('<I')),
    ('previous_block', HashType()),
    ('merkle_root', HashType()),
    ('timestamp', StructType('<I')),
    ('bits', FixedStrType(4)),
    ('nonce', StructType('<I')),
])

block_type = ComposedType([
    ('header', block_header_type),
    ('txs', ListType(tx_type)),
])

def doublesha(data):
    return HashType().unpack(hashlib.sha256(hashlib.sha256(data).digest()).digest())

def ripemdsha(data):
    return ShortHashType().unpack(hashlib.new('ripemd160', hashlib.sha256(data).digest()).digest())

merkle_record_type = ComposedType([
    ('left', HashType()),
    ('right', HashType()),
])

def merkle_hash(tx_list):
    hash_list = map(tx_hash, tx_list)
    while len(hash_list) > 1:
        hash_list = [doublesha(merkle_record_type.pack(dict(left=left, right=left if right is None else right)))
            for left, right in zip(hash_list[::2], hash_list[1::2] + [None])]
    return hash_list[0]

def tx_hash(tx):
    return doublesha(tx_type.pack(tx))

def block_hash(header):
    return doublesha(block_header_type.pack(header))

def shift_left(n, m):
    # python: :(
    if m < 0:
        return n >> -m
    return n << m

def bits_to_target(bits):
    bits = bits[::-1]
    length = ord(bits[0])
    return bases.string_to_natural((bits[1:] + "\0"*length)[:length])

def old_bits_to_target(bits):
    return shift_left(bits & 0x00ffffff, 8 * ((bits >> 24) - 3))

def about_equal(a, b):
    if a == b: return True
    return abs(a-b)/((abs(a)+abs(b))/2) < .01

def compress_target_to_bits(target): # loses precision
    print
    print "t", target
    n = bases.natural_to_string(target)
    print "n", n.encode('hex')
    bits = chr(len(n)) + n[:3].ljust(3, '\0')
    bits = bits[::-1]
    print "bits", bits.encode('hex')
    print "new", bits_to_target(bits)
    print "old", old_bits_to_target(struct.unpack("<I", bits)[0])
    assert about_equal(bits_to_target(bits), target), (bits_to_target(bits), target)
    assert about_equal(old_bits_to_target(struct.unpack("<I", bits)[0]), target), (old_bits_to_target(struct.unpack("<I", bits)[0]), target)
    return bits

def target_to_average_attempts(target):
    return 2**256//(target + 1)

human_address_type = ChecksummedType(ComposedType([
    ('version', StructType("<B")),
    ('pubkey_hash', ShortHashType()),
]))

pubkey_type = FixedStrType(65)

def pubkey_hash_to_address(pubkey_hash, net):
    return human_address_type.pack_base58(dict(version=net.BITCOIN_ADDRESS_VERSION, pubkey_hash=pubkey_hash))

def pubkey_to_address(pubkey, net):
    return pubkey_hash_to_address(pubkey_type.hash160(pubkey), net)

def address_to_pubkey_hash(address, net):
    x = human_address_type.unpack_base58(address)
    if x['version'] != net.BITCOIN_ADDRESS_VERSION:
        raise ValueError('address not for this net!')
    return x['pubkey_hash']

class Mainnet(object):
    BITCOIN_P2P_PREFIX = 'f9beb4d9'.decode('hex')
    BITCOIN_P2P_PORT = 8333
    BITCOIN_ADDRESS_VERSION = 0

class Testnet(object):
    BITCOIN_P2P_PREFIX = 'fabfb5da'.decode('hex')
    BITCOIN_P2P_PORT = 18333
    BITCOIN_ADDRESS_VERSION = 111

