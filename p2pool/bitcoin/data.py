from __future__ import division

import hashlib
import struct

from . import base58
from p2pool.util import bases, math, expiring_dict, memoize, dicts
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
    
    def pack2(self, obj):
        data = self._pack(obj)
        
        if p2pool.DEBUG:
            if self._unpack(data) != obj:
                raise AssertionError((self._unpack(data), obj))
        
        return data
    
    _backing = expiring_dict.ExpiringDict(100)
    pack2 = memoize.memoize_with_backing(_backing, [unpack])(pack2)
    unpack = memoize.memoize_with_backing(_backing)(unpack) # doesn't have an inverse
    
    def pack(self, obj):
        return self.pack2(dicts.immutify(obj))
    
    
    def pack_base58(self, obj):
        return base58.base58_encode(self.pack(obj))
    
    def unpack_base58(self, base58_data):
        return self.unpack(base58.base58_decode(base58_data))
    
    
    def hash160(self, obj):
        return ShortHashType().unpack(hashlib.new('ripemd160', hashlib.sha256(self.pack(obj)).digest()).digest())
    
    def hash256(self, obj):
        return HashType().unpack(hashlib.sha256(hashlib.sha256(self.pack(obj)).digest()).digest())
    
    def scrypt(self, obj):
        import ltc_scrypt
        return HashType().unpack(ltc_scrypt.getPoWHash(self.pack(obj)))

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

class FixedStrType(Type):
    def __init__(self, length):
        self.length = length
    
    def read(self, file):
        return read(file, self.length)
    
    def write(self, file, item):
        if len(item) != self.length:
            raise ValueError('incorrect length item!')
        return file, item

class EnumType(Type):
    def __init__(self, inner, values):
        self.inner = inner
        self.values = dicts.frozendict(values)
        
        keys = {}
        for k, v in values.iteritems():
            if v in keys:
                raise ValueError('duplicate value in values')
            keys[v] = k
        self.keys = dicts.frozendict(keys)
    
    def read(self, file):
        data, file = self.inner.read(file)
        if data not in self.keys:
            raise ValueError('enum data (%r) not in values (%r)' % (data, self.values))
        return self.keys[data], file
    
    def write(self, file, item):
        if item not in self.values:
            raise ValueError('enum item (%r) not in values (%r)' % (item, self.values))
        return self.inner.write(file, self.values[item])

class HashType(Type):
    def read(self, file):
        data, file = read(file, 256//8)
        return int(data[::-1].encode('hex'), 16), file
    
    def write(self, file, item):
        if not 0 <= item < 2**256:
            raise ValueError('invalid hash value - %r' % (item,))
        if item != 0 and item < 2**160:
            print 'Very low hash value - maybe you meant to use ShortHashType? %x' % (item,)
        return file, ('%064x' % (item,)).decode('hex')[::-1]

class ShortHashType(Type):
    def read(self, file):
        data, file = read(file, 160//8)
        return int(data[::-1].encode('hex'), 16), file
    
    def write(self, file, item):
        if not 0 <= item < 2**160:
            raise ValueError('invalid hash value - %r' % (item,))
        return file, ('%040x' % (item,)).decode('hex')[::-1]

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
    def __init__(self, desc):
        self.desc = desc
        self.length = struct.calcsize(self.desc)
    
    def read(self, file):
        data, file = read(file, self.length)
        res, = struct.unpack(self.desc, data)
        return res, file
    
    def write(self, file, item):
        data = struct.pack(self.desc, item)
        if struct.unpack(self.desc, data)[0] != item:
            # special test because struct doesn't error on some overflows
            raise ValueError('''item didn't survive pack cycle (%r)''' % (item,))
        return file, data

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
    __slots__ = ['_bits']
    
    @classmethod
    def from_target_upper_bound(cls, target):
        n = bases.natural_to_string(target)
        if n and ord(n[0]) >= 128:
            n = '\x00' + n
        bits2 = (chr(len(n)) + (n + 3*chr(0))[:3])[::-1]
        bits = struct.unpack('<I', bits2)[0]
        return cls(bits)
    
    def __init__(self, bits):
        self._bits = bits
    
    @property
    def _value(self):
        return math.shift_left(self._bits & 0x00ffffff, 8 * ((self._bits >> 24) - 3))
    
    def __hash__(self):
        return hash(self._value)
    
    def __cmp__(self, other):
        if isinstance(other, FloatingInteger):
            return cmp(self._value, other._value)
        elif isinstance(other, (int, long)):
            return cmp(self._value, other)
        else:
            raise NotImplementedError(other)
    
    def __int__(self):
        return self._value
    
    def __repr__(self):
        return 'FloatingInteger(bits=%s (%x))' % (hex(self._bits), self)
    
    def __add__(self, other):
        if isinstance(other, (int, long)):
            return self._value + other
        raise NotImplementedError()
    __radd__ = __add__
    def __mul__(self, other):
        if isinstance(other, (int, long)):
            return self._value * other
        raise NotImplementedError()
    __rmul__ = __mul__
    def __truediv__(self, other):
        if isinstance(other, (int, long)):
            return self._value / other
        raise NotImplementedError()
    def __floordiv__(self, other):
        if isinstance(other, (int, long)):
            return self._value // other
        raise NotImplementedError()
    __div__ = __truediv__
    def __rtruediv__(self, other):
        if isinstance(other, (int, long)):
            return other / self._value
        raise NotImplementedError()
    def __rfloordiv__(self, other):
        if isinstance(other, (int, long)):
            return other // self._value
        raise NotImplementedError()
    __rdiv__ = __rtruediv__

class FloatingIntegerType(Type):
    _inner = StructType('<I')
    
    def read(self, file):
        bits, file = self._inner.read(file)
        return FloatingInteger(bits), file
    
    def write(self, file, item):
        return self._inner.write(file, item._bits)

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
    ('services', StructType('<Q')),
    ('address', IPV6AddressType()),
    ('port', StructType('>H')),
])

tx_type = ComposedType([
    ('version', StructType('<I')),
    ('tx_ins', ListType(ComposedType([
        ('previous_output', PossiblyNoneType(dicts.frozendict(hash=0, index=2**32 - 1), ComposedType([
            ('hash', HashType()),
            ('index', StructType('<I')),
        ]))),
        ('script', VarStrType()),
        ('sequence', PossiblyNoneType(2**32 - 1, StructType('<I'))),
    ]))),
    ('tx_outs', ListType(ComposedType([
        ('value', StructType('<Q')),
        ('script', VarStrType()),
    ]))),
    ('lock_time', StructType('<I')),
])

merkle_branch_type = ListType(HashType())

merkle_tx_type = ComposedType([
    ('tx', tx_type),
    ('block_hash', HashType()),
    ('merkle_branch', merkle_branch_type),
    ('index', StructType('<i')),
])

block_header_type = ComposedType([
    ('version', StructType('<I')),
    ('previous_block', PossiblyNoneType(0, HashType())),
    ('merkle_root', HashType()),
    ('timestamp', StructType('<I')),
    ('target', FloatingIntegerType()),
    ('nonce', StructType('<I')),
])

block_type = ComposedType([
    ('header', block_header_type),
    ('txs', ListType(tx_type)),
])

aux_pow_type = ComposedType([
    ('merkle_tx', merkle_tx_type),
    ('merkle_branch', merkle_branch_type),
    ('index', StructType('<i')),
    ('parent_block_header', block_header_type),
])


merkle_record_type = ComposedType([
    ('left', HashType()),
    ('right', HashType()),
])

def merkle_hash(tx_list):
    if not tx_list:
        return 0
    hash_list = map(tx_type.hash256, tx_list)
    while len(hash_list) > 1:
        hash_list = [merkle_record_type.hash256(dict(left=left, right=left if right is None else right))
            for left, right in zip(hash_list[::2], hash_list[1::2] + [None])]
    return hash_list[0]

def calculate_merkle_branch(txs, index):
    # XXX optimize this
    
    hash_list = [(tx_type.hash256(tx), i == index, []) for i, tx in enumerate(txs)]
    
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
    assert check_merkle_branch(txs[index], index, res) == hash_list[0][0]
    assert index == sum(k*2**i for i, k in enumerate([1-x['side'] for x in hash_list[0][2]]))
    
    return res

def check_merkle_branch(tx, index, merkle_branch):
    return reduce(lambda c, (i, h): merkle_record_type.hash256(
        dict(left=h, right=c) if 2**i & index else
        dict(left=c, right=h)
    ), enumerate(merkle_branch), tx_type.hash256(tx))

def target_to_average_attempts(target):
    return 2**256//(target + 1)

def target_to_difficulty(target):
    return (0xffff0000 * 2**(256-64) + 1)/(target + 1)

# tx

def tx_get_sigop_count(tx):
    return sum(script.get_sigop_count(txin['script']) for txin in tx['tx_ins']) + sum(script.get_sigop_count(txout['script']) for txout in tx['tx_outs'])

# human addresses

human_address_type = ChecksummedType(ComposedType([
    ('version', StructType('<B')),
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

# transactions

def pubkey_to_script2(pubkey):
    return ('\x41' + pubkey_type.pack(pubkey)) + '\xac'

def pubkey_hash_to_script2(pubkey_hash):
    return '\x76\xa9' + ('\x14' + ShortHashType().pack(pubkey_hash)) + '\x88\xac'

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
        pubkey_hash = ShortHashType().unpack(script2[3:-2])
        script2_test2 = pubkey_hash_to_script2(pubkey_hash)
    except:
        pass
    else:
        if script2_test2 == script2:
            return 'Address. Address: %s' % (pubkey_hash_to_address(pubkey_hash, net),)
    
    return 'Unknown. Script: %s'  % (script2.encode('hex'),)
