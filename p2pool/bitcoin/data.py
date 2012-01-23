from __future__ import division

import binascii
import hashlib
import struct

from . import base58
from p2pool.util import bases, math
import p2pool

class EarlyEnd(Exception):
    pass

class LateEnd(Exception):
    pass

def read((data, pos), length):
    data2 = data[pos:pos + length]
    if len(data2) != length:
        raise EarlyEnd()
    return data2, (data, pos + length)

def size((data, pos)):
    return len(data) - pos

class Type(object):
    __slots__ = []
    
    # the same data can have only one unpacked representation, but multiple packed binary representations
    
    def __hash__(self):
        rval = getattr(self, '_hash', None)
        if rval is None:
            try:
                rval = self._hash = hash((type(self), frozenset(self.__dict__.items())))
            except:
                print self.__dict__
                raise
        return rval
    
    def __eq__(self, other):
        return type(other) is type(self) and other.__dict__ == self.__dict__
    
    def __ne__(self, other):
        return not (self == other)
    
    def _unpack(self, data):
        obj, (data2, pos) = self.read((data, 0))
        
        assert data2 is data
        
        if pos != len(data):
            raise LateEnd()
        
        return obj
    
    def _pack(self, obj):
        f = self.write(None, obj)
        
        res = []
        while f is not None:
            res.append(f[1])
            f = f[0]
        res.reverse()
        return ''.join(res)
    
    
    def unpack(self, data):
        obj = self._unpack(data)
        
        if p2pool.DEBUG:
            data2 = self._pack(obj)
            if data2 != data:
                if self._unpack(data2) != obj:
                    raise AssertionError()
        
        return obj
    
    def pack(self, obj):
        data = self._pack(obj)
        
        if p2pool.DEBUG:
            if self._unpack(data) != obj:
                raise AssertionError((self._unpack(data), obj))
        
        return data
    
    
    def pack_base58(self, obj):
        return base58.encode(self.pack(obj))
    
    def unpack_base58(self, base58_data):
        return self.unpack(base58.decode(base58_data))
    
    
    def hash160(self, obj):
        return IntType(160).unpack(hashlib.new('ripemd160', hashlib.sha256(self.pack(obj)).digest()).digest())
    
    def hash256(self, obj):
        return IntType(256).unpack(hashlib.sha256(hashlib.sha256(self.pack(obj)).digest()).digest())
    
    def scrypt(self, obj):
        import ltc_scrypt
        return IntType(256).unpack(ltc_scrypt.getPoWHash(self.pack(obj)))

class VarIntType(Type):
    # redundancy doesn't matter here because bitcoin and p2pool both reencode before hashing
    def read(self, file):
        data, file = read(file, 1)
        first = ord(data)
        if first < 0xfd:
            return first, file
        elif first == 0xfd:
            desc, length = '<H', 2
        elif first == 0xfe:
            desc, length = '<I', 4
        elif first == 0xff:
            desc, length = '<Q', 8
        else:
            raise AssertionError()
        data, file = read(file, length)
        return struct.unpack(desc, data)[0], file
    
    def write(self, file, item):
        if item < 0xfd:
            file = file, struct.pack('<B', item)
        elif item <= 0xffff:
            file = file, struct.pack('<BH', 0xfd, item)
        elif item <= 0xffffffff:
            file = file, struct.pack('<BI', 0xfe, item)
        elif item <= 0xffffffffffffffff:
            file = file, struct.pack('<BQ', 0xff, item)
        else:
            raise ValueError('int too large for varint')
        return file

class VarStrType(Type):
    _inner_size = VarIntType()
    
    def read(self, file):
        length, file = self._inner_size.read(file)
        return read(file, length)
    
    def write(self, file, item):
        return self._inner_size.write(file, len(item)), item

class PassthruType(Type):
    def read(self, file):
        return read(file, size(file))
    
    def write(self, file, item):
        return file, item

class EnumType(Type):
    def __init__(self, inner, values):
        self.inner = inner
        self.values = values
        
        keys = {}
        for k, v in values.iteritems():
            if v in keys:
                raise ValueError('duplicate value in values')
            keys[v] = k
        self.keys = keys
    
    def read(self, file):
        data, file = self.inner.read(file)
        if data not in self.keys:
            raise ValueError('enum data (%r) not in values (%r)' % (data, self.values))
        return self.keys[data], file
    
    def write(self, file, item):
        if item not in self.values:
            raise ValueError('enum item (%r) not in values (%r)' % (item, self.values))
        return self.inner.write(file, self.values[item])

class ListType(Type):
    _inner_size = VarIntType()
    
    def __init__(self, type):
        self.type = type
    
    def read(self, file):
        length, file = self._inner_size.read(file)
        res = []
        for i in xrange(length):
            item, file = self.type.read(file)
            res.append(item)
        return res, file
    
    def write(self, file, item):
        file = self._inner_size.write(file, len(item))
        for subitem in item:
            file = self.type.write(file, subitem)
        return file

class StructType(Type):
    __slots__ = 'desc length'.split(' ')
    
    def __init__(self, desc):
        self.desc = desc
        self.length = struct.calcsize(self.desc)
    
    def read(self, file):
        data, file = read(file, self.length)
        return struct.unpack(self.desc, data)[0], file
    
    def write(self, file, item):
        return file, struct.pack(self.desc, item)

class IntType(Type):
    __slots__ = 'bytes step format_str max'.split(' ')
    
    def __new__(cls, bits, endianness='little'):
        assert bits % 8 == 0
        assert endianness in ['little', 'big']
        if bits in [8, 16, 32, 64]:
            return StructType(('<' if endianness == 'little' else '>') + {8: 'B', 16: 'H', 32: 'I', 64: 'Q'}[bits])
        else:
            return object.__new__(cls, bits, endianness)
    
    def __init__(self, bits, endianness='little'):
        assert bits % 8 == 0
        assert endianness in ['little', 'big']
        self.bytes = bits//8
        self.step = -1 if endianness == 'little' else 1
        self.format_str = '%%0%ix' % (2*self.bytes)
        self.max = 2**bits
    
    def read(self, file, b2a_hex=binascii.b2a_hex):
        data, file = read(file, self.bytes)
        return int(b2a_hex(data[::self.step]), 16), file
    
    def write(self, file, item, a2b_hex=binascii.a2b_hex):
        if not 0 <= item < self.max:
            raise ValueError('invalid int value - %r' % (item,))
        return file, a2b_hex(self.format_str % (item,))[::self.step]

class IPV6AddressType(Type):
    def read(self, file):
        data, file = read(file, 16)
        if data[:12] != '00000000000000000000ffff'.decode('hex'):
            raise ValueError('ipv6 addresses not supported yet')
        return '.'.join(str(ord(x)) for x in data[12:]), file
    
    def write(self, file, item):
        bits = map(int, item.split('.'))
        if len(bits) != 4:
            raise ValueError('invalid address: %r' % (bits,))
        data = '00000000000000000000ffff'.decode('hex') + ''.join(chr(x) for x in bits)
        assert len(data) == 16, len(data)
        return file, data

_record_types = {}

def get_record(fields):
    fields = tuple(sorted(fields))
    if 'keys' in fields:
        raise ValueError()
    if fields not in _record_types:
        class _Record(object):
            __slots__ = fields
            def __repr__(self):
                return repr(dict(self))
            def __getitem__(self, key):
                return getattr(self, key)
            def __setitem__(self, key, value):
                setattr(self, key, value)
            #def __iter__(self):
            #    for field in self.__slots__:
            #        yield field, getattr(self, field)
            def keys(self):
                return self.__slots__
            def __eq__(self, other):
                if isinstance(other, dict):
                    return dict(self) == other
                elif isinstance(other, _Record):
                    return all(self[k] == other[k] for k in self.keys())
                raise TypeError()
            def __ne__(self, other):
                return not (self == other)
        _record_types[fields] = _Record
    return _record_types[fields]()

class ComposedType(Type):
    def __init__(self, fields):
        self.fields = tuple(fields)
    
    def read(self, file):
        item = get_record(k for k, v in self.fields)
        for key, type_ in self.fields:
            item[key], file = type_.read(file)
        return item, file
    
    def write(self, file, item):
        for key, type_ in self.fields:
            file = type_.write(file, item[key])
        return file

class ChecksummedType(Type):
    def __init__(self, inner):
        self.inner = inner
    
    def read(self, file):
        obj, file = self.inner.read(file)
        data = self.inner.pack(obj)
        
        checksum, file = read(file, 4)
        if checksum != hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]:
            raise ValueError('invalid checksum')
        
        return obj, file
    
    def write(self, file, item):
        data = self.inner.pack(item)
        return (file, data), hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]

class FloatingInteger(object):
    __slots__ = ['bits', '_target']
    
    @classmethod
    def from_target_upper_bound(cls, target):
        n = bases.natural_to_string(target)
        if n and ord(n[0]) >= 128:
            n = '\x00' + n
        bits2 = (chr(len(n)) + (n + 3*chr(0))[:3])[::-1]
        bits = struct.unpack('<I', bits2)[0]
        return cls(bits)
    
    def __init__(self, bits, target=None):
        self.bits = bits
        self._target = None
        if target is not None and self.target != target:
            raise ValueError('target does not match')
    
    @property
    def target(self):
        res = self._target
        if res is None:
            res = self._target = math.shift_left(self.bits & 0x00ffffff, 8 * ((self.bits >> 24) - 3))
        return res
    
    def __hash__(self):
        return hash(self.bits)
    
    def __eq__(self, other):
        return self.bits == other.bits
    
    def __ne__(self, other):
        return not (self == other)
    
    def __cmp__(self, other):
        assert False
    
    def __repr__(self):
        return 'FloatingInteger(bits=%s, target=%s)' % (hex(self.bits), hex(self.target))

class FloatingIntegerType(Type):
    _inner = IntType(32)
    
    def read(self, file):
        bits, file = self._inner.read(file)
        return FloatingInteger(bits), file
    
    def write(self, file, item):
        return self._inner.write(file, item.bits)

class PossiblyNoneType(Type):
    def __init__(self, none_value, inner):
        self.none_value = none_value
        self.inner = inner
    
    def read(self, file):
        value, file = self.inner.read(file)
        return None if value == self.none_value else value, file
    
    def write(self, file, item):
        if item == self.none_value:
            raise ValueError('none_value used')
        return self.inner.write(file, self.none_value if item is None else item)

address_type = ComposedType([
    ('services', IntType(64)),
    ('address', IPV6AddressType()),
    ('port', IntType(16, 'big')),
])

tx_type = ComposedType([
    ('version', IntType(32)),
    ('tx_ins', ListType(ComposedType([
        ('previous_output', PossiblyNoneType(dict(hash=0, index=2**32 - 1), ComposedType([
            ('hash', IntType(256)),
            ('index', IntType(32)),
        ]))),
        ('script', VarStrType()),
        ('sequence', PossiblyNoneType(2**32 - 1, IntType(32))),
    ]))),
    ('tx_outs', ListType(ComposedType([
        ('value', IntType(64)),
        ('script', VarStrType()),
    ]))),
    ('lock_time', IntType(32)),
])

merkle_branch_type = ListType(IntType(256))

merkle_tx_type = ComposedType([
    ('tx', tx_type),
    ('block_hash', IntType(256)),
    ('merkle_branch', merkle_branch_type),
    ('index', IntType(32)),
])

block_header_type = ComposedType([
    ('version', IntType(32)),
    ('previous_block', PossiblyNoneType(0, IntType(256))),
    ('merkle_root', IntType(256)),
    ('timestamp', IntType(32)),
    ('bits', FloatingIntegerType()),
    ('nonce', IntType(32)),
])

block_type = ComposedType([
    ('header', block_header_type),
    ('txs', ListType(tx_type)),
])

aux_pow_type = ComposedType([
    ('merkle_tx', merkle_tx_type),
    ('merkle_branch', merkle_branch_type),
    ('index', IntType(32)),
    ('parent_block_header', block_header_type),
])


merkle_record_type = ComposedType([
    ('left', IntType(256)),
    ('right', IntType(256)),
])

def merkle_hash(hashes):
    if not hashes:
        return 0
    hash_list = list(hashes)
    while len(hash_list) > 1:
        hash_list = [merkle_record_type.hash256(dict(left=left, right=left if right is None else right))
            for left, right in zip(hash_list[::2], hash_list[1::2] + [None])]
    return hash_list[0]

def calculate_merkle_branch(hashes, index):
    # XXX optimize this
    
    hash_list = [(h, i == index, []) for i, h in enumerate(hashes)]
    
    while len(hash_list) > 1:
        hash_list = [
            (
                merkle_record_type.hash256(dict(left=left, right=right)),
                left_f or right_f,
                (left_l if left_f else right_l) + [dict(side=1, hash=right) if left_f else dict(side=0, hash=left)],
            )
            for (left, left_f, left_l), (right, right_f, right_l) in
                zip(hash_list[::2], hash_list[1::2] + [hash_list[::2][-1]])
        ]
    
    res = [x['hash'] for x in hash_list[0][2]]
    
    assert hash_list[0][1]
    assert check_merkle_branch(hashes[index], index, res) == hash_list[0][0]
    assert index == sum(k*2**i for i, k in enumerate([1-x['side'] for x in hash_list[0][2]]))
    
    return res

def check_merkle_branch(tip_hash, index, merkle_branch):
    return reduce(lambda c, (i, h): merkle_record_type.hash256(
        dict(left=h, right=c) if 2**i & index else
        dict(left=c, right=h)
    ), enumerate(merkle_branch), tip_hash)

def target_to_average_attempts(target):
    return 2**256//(target + 1)

def target_to_difficulty(target):
    return (0xffff0000 * 2**(256-64) + 1)/(target + 1)

# tx

def tx_get_sigop_count(tx):
    return sum(script.get_sigop_count(txin['script']) for txin in tx['tx_ins']) + sum(script.get_sigop_count(txout['script']) for txout in tx['tx_outs'])

# human addresses

human_address_type = ChecksummedType(ComposedType([
    ('version', IntType(8)),
    ('pubkey_hash', IntType(160)),
]))

pubkey_type = PassthruType()

def pubkey_hash_to_address(pubkey_hash, net):
    return human_address_type.pack_base58(dict(version=net.ADDRESS_VERSION, pubkey_hash=pubkey_hash))

def pubkey_to_address(pubkey, net):
    return pubkey_hash_to_address(pubkey_type.hash160(pubkey), net)

def address_to_pubkey_hash(address, net):
    x = human_address_type.unpack_base58(address)
    if x['version'] != net.ADDRESS_VERSION:
        raise ValueError('address not for this net!')
    return x['pubkey_hash']

# transactions

def pubkey_to_script2(pubkey):
    return ('\x41' + pubkey_type.pack(pubkey)) + '\xac'

def pubkey_hash_to_script2(pubkey_hash):
    return '\x76\xa9' + ('\x14' + IntType(160).pack(pubkey_hash)) + '\x88\xac'

def script2_to_address(script2, net):
    try:
        pubkey = script2[1:-1]
        script2_test = pubkey_to_script2(pubkey)
    except:
        pass
    else:
        if script2_test == script2:
            return pubkey_to_address(pubkey, net)
    
    try:
        pubkey_hash = IntType(160).unpack(script2[3:-2])
        script2_test2 = pubkey_hash_to_script2(pubkey_hash)
    except:
        pass
    else:
        if script2_test2 == script2:
            return pubkey_hash_to_address(pubkey_hash, net)

def script2_to_human(script2, net):
    try:
        pubkey = script2[1:-1]
        script2_test = pubkey_to_script2(pubkey)
    except:
        pass
    else:
        if script2_test == script2:
            return 'Pubkey. Address: %s' % (pubkey_to_address(pubkey, net),)
    
    try:
        pubkey_hash = IntType(160).unpack(script2[3:-2])
        script2_test2 = pubkey_hash_to_script2(pubkey_hash)
    except:
        pass
    else:
        if script2_test2 == script2:
            return 'Address. Address: %s' % (pubkey_hash_to_address(pubkey_hash, net),)
    
    return 'Unknown. Script: %s'  % (script2.encode('hex'),)
