import binascii
import struct

import p2pool
from p2pool.util import memoize

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
    
    def _unpack(self, data, ignore_trailing=False):
        obj, (data2, pos) = self.read((data, 0))
        
        assert data2 is data
        
        if pos != len(data) and not ignore_trailing:
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
    
    
    def unpack(self, data, ignore_trailing=False):
        obj = self._unpack(data, ignore_trailing)
        
        if p2pool.DEBUG:
            packed = self._pack(obj)
            good = data.startswith(packed) if ignore_trailing else data == packed
            if not good:
                raise AssertionError()
        
        return obj
    
    def pack(self, obj):
        data = self._pack(obj)
        
        if p2pool.DEBUG:
            if self._unpack(data) != obj:
                raise AssertionError((self._unpack(data), obj))
        
        return data
    
    def packed_size(self, obj):
        if hasattr(obj, '_packed_size') and obj._packed_size is not None:
            type_obj, packed_size = obj._packed_size
            if type_obj is self:
                return packed_size
        
        packed_size = len(self.pack(obj))
        
        if hasattr(obj, '_packed_size'):
            obj._packed_size = self, packed_size
        
        return packed_size

class VarIntType(Type):
    def read(self, file):
        data, file = read(file, 1)
        first = ord(data)
        if first < 0xfd:
            return first, file
        if first == 0xfd:
            desc, length, minimum = '<H', 2, 0xfd
        elif first == 0xfe:
            desc, length, minimum = '<I', 4, 2**16
        elif first == 0xff:
            desc, length, minimum = '<Q', 8, 2**32
        else:
            raise AssertionError()
        data2, file = read(file, length)
        res, = struct.unpack(desc, data2)
        if res < minimum:
            raise AssertionError('VarInt not canonically packed')
        return res, file
    
    def write(self, file, item):
        if item < 0xfd:
            return file, struct.pack('<B', item)
        elif item <= 0xffff:
            return file, struct.pack('<BH', 0xfd, item)
        elif item <= 0xffffffff:
            return file, struct.pack('<BI', 0xfe, item)
        elif item <= 0xffffffffffffffff:
            return file, struct.pack('<BQ', 0xff, item)
        else:
            raise ValueError('int too large for varint')

class VarStrType(Type):
    _inner_size = VarIntType()
    
    def read(self, file):
        length, file = self._inner_size.read(file)
        return read(file, length)
    
    def write(self, file, item):
        return self._inner_size.write(file, len(item)), item

class EnumType(Type):
    def __init__(self, inner, pack_to_unpack):
        self.inner = inner
        self.pack_to_unpack = pack_to_unpack
        
        self.unpack_to_pack = {}
        for k, v in pack_to_unpack.iteritems():
            if v in self.unpack_to_pack:
                raise ValueError('duplicate value in pack_to_unpack')
            self.unpack_to_pack[v] = k
    
    def read(self, file):
        data, file = self.inner.read(file)
        if data not in self.pack_to_unpack:
            raise ValueError('enum data (%r) not in pack_to_unpack (%r)' % (data, self.pack_to_unpack))
        return self.pack_to_unpack[data], file
    
    def write(self, file, item):
        if item not in self.unpack_to_pack:
            raise ValueError('enum item (%r) not in unpack_to_pack (%r)' % (item, self.unpack_to_pack))
        return self.inner.write(file, self.unpack_to_pack[item])

class ListType(Type):
    _inner_size = VarIntType()
    
    def __init__(self, type, mul=1):
        self.type = type
        self.mul = mul
    
    def read(self, file):
        length, file = self._inner_size.read(file)
        length *= self.mul
        res = [None]*length
        for i in xrange(length):
            res[i], file = self.type.read(file)
        return res, file
    
    def write(self, file, item):
        assert len(item) % self.mul == 0
        file = self._inner_size.write(file, len(item)//self.mul)
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

@memoize.fast_memoize_multiple_args
class IntType(Type):
    __slots__ = 'bytes step format_str max'.split(' ')
    
    def __new__(cls, bits, endianness='little'):
        assert bits % 8 == 0
        assert endianness in ['little', 'big']
        if bits in [8, 16, 32, 64]:
            return StructType(('<' if endianness == 'little' else '>') + {8: 'B', 16: 'H', 32: 'I', 64: 'Q'}[bits])
        else:
            return Type.__new__(cls, bits, endianness)
    
    def __init__(self, bits, endianness='little'):
        assert bits % 8 == 0
        assert endianness in ['little', 'big']
        self.bytes = bits//8
        self.step = -1 if endianness == 'little' else 1
        self.format_str = '%%0%ix' % (2*self.bytes)
        self.max = 2**bits
    
    def read(self, file, b2a_hex=binascii.b2a_hex):
        if self.bytes == 0:
            return 0, file
        data, file = read(file, self.bytes)
        return int(b2a_hex(data[::self.step]), 16), file
    
    def write(self, file, item, a2b_hex=binascii.a2b_hex):
        if self.bytes == 0:
            return file
        if not 0 <= item < self.max:
            raise ValueError('invalid int value - %r' % (item,))
        return file, a2b_hex(self.format_str % (item,))[::self.step]

class IPV6AddressType(Type):
    def read(self, file):
        data, file = read(file, 16)
        if data[:12] == '00000000000000000000ffff'.decode('hex'):
            return '.'.join(str(ord(x)) for x in data[12:]), file
        return ':'.join(data[i*2:(i+1)*2].encode('hex') for i in xrange(8)), file
    
    def write(self, file, item):
        if ':' in item:
            data = ''.join(item.replace(':', '')).decode('hex')
        else:
            bits = map(int, item.split('.'))
            if len(bits) != 4:
                raise ValueError('invalid address: %r' % (bits,))
            data = '00000000000000000000ffff'.decode('hex') + ''.join(chr(x) for x in bits)
        assert len(data) == 16, len(data)
        return file, data

_record_types = {}

def get_record(fields):
    fields = tuple(sorted(fields))
    if 'keys' in fields or '_packed_size' in fields:
        raise ValueError()
    if fields not in _record_types:
        class _Record(object):
            __slots__ = fields + ('_packed_size',)
            def __init__(self):
                self._packed_size = None
            def __repr__(self):
                return repr(dict(self))
            def __getitem__(self, key):
                return getattr(self, key)
            def __setitem__(self, key, value):
                setattr(self, key, value)
            #def __iter__(self):
            #    for field in fields:
            #        yield field, getattr(self, field)
            def keys(self):
                return fields
            def get(self, key, default=None):
                return getattr(self, key, default)
            def __eq__(self, other):
                if isinstance(other, dict):
                    return dict(self) == other
                elif isinstance(other, _Record):
                    for k in fields:
                        if getattr(self, k) != getattr(other, k):
                            return False
                    return True
                elif other is None:
                    return False
                raise TypeError()
            def __ne__(self, other):
                return not (self == other)
        _record_types[fields] = _Record
    return _record_types[fields]

class ComposedType(Type):
    def __init__(self, fields):
        self.fields = list(fields)
        self.field_names = set(k for k, v in fields)
        self.record_type = get_record(k for k, v in self.fields)
    
    def read(self, file):
        item = self.record_type()
        for key, type_ in self.fields:
            item[key], file = type_.read(file)
        return item, file
    
    def write(self, file, item):
        assert set(item.keys()) == self.field_names, (set(item.keys()) - self.field_names, self.field_names - set(item.keys()))
        for key, type_ in self.fields:
            file = type_.write(file, item[key])
        return file

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

class FixedStrType(Type):
    def __init__(self, length):
        self.length = length
    
    def read(self, file):
        return read(file, self.length)
    
    def write(self, file, item):
        if len(item) != self.length:
            raise ValueError('incorrect length item!')
        return file, item
