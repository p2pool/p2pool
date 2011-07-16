from __future__ import division

import struct
import hashlib
import warnings

from . import base58
from p2pool.util import bases, math

class EarlyEnd(Exception):
    pass

class LateEnd(Exception):
    pass

def read((data, pos), length):
    data2 = data[pos:pos + length]
    if len(data2) != length:
        raise EarlyEnd()
    return data2, (data, pos + length)

class Type(object):
    # the same data can have only one unpacked representation, but multiple packed binary representations
    
    #def __hash__(self):
    #    return hash(tuple(self.__dict__.items()))
    
    #def __eq__(self, other):
    #    if not isinstance(other, Type):
    #        raise NotImplementedError()
    #    return self.__dict__ == other.__dict__
    
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
        
        if __debug__:
            data2 = self._pack(obj)
            if data2 != data:
                assert self._unpack(data2) == obj
        
        return obj
    
    def pack(self, obj):
        data = self._pack(obj)
        
        assert self._unpack(data) == obj
        
        return data
    
    
    def pack_base58(self, obj):
        return base58.base58_encode(self.pack(obj))
    
    def unpack_base58(self, base58_data):
        return self.unpack(base58.base58_decode(base58_data))
    
    
    def hash160(self, obj):
        return ShortHashType().unpack(hashlib.new('ripemd160', hashlib.sha256(self.pack(obj)).digest()).digest())
    
    def hash256(self, obj):
        return HashType().unpack(hashlib.sha256(hashlib.sha256(self.pack(obj)).digest()).digest())

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
        self.values = values
        
        self.keys = {}
        for k, v in values.iteritems():
            if v in self.keys:
                raise ValueError('duplicate value in values')
            self.keys[v] = k
    
    def read(self, file):
        data, file = self.inner.read(file)
        return self.keys[data], file
    
    def write(self, file, item):
        return self.inner.write(file, self.values[item])

class HashType(Type):
    def read(self, file):
        data, file = read(file, 256//8)
        return int(data[::-1].encode('hex'), 16), file
    
    def write(self, file, item):
        if not 0 <= item < 2**256:
            raise ValueError('invalid hash value - %r' % (item,))
        if item != 0 and item < 2**160:
            warnings.warn('very low hash value - maybe you meant to use ShortHashType? %x' % (item,))
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

class ComposedType(Type):
    def __init__(self, fields):
        self.fields = fields
    
    def read(self, file):
        item = {}
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

class FloatingIntegerType(Type):
    # redundancy doesn't matter here because bitcoin checks binary bits against its own computed bits
    # so it will always be encoded 'normally' in blocks (they way bitcoin does it)
    _inner = StructType('<I')
    
    def read(self, file):
        bits, file = self._inner.read(file)
        target = self._bits_to_target(bits)
        if __debug__:
            if self._target_to_bits(target) != bits:
                raise ValueError('bits in non-canonical form')
        return target, file
    
    def write(self, file, item):
        return self._inner.write(file, self._target_to_bits(item))
    
    def truncate_to(self, x):
        return self._bits_to_target(self._target_to_bits(x, _check=False))
    
    def _bits_to_target(self, bits2):
        target = math.shift_left(bits2 & 0x00ffffff, 8 * ((bits2 >> 24) - 3))
        assert target == self._bits_to_target1(struct.pack('<I', bits2))
        assert self._target_to_bits(target, _check=False) == bits2
        return target
    
    def _bits_to_target1(self, bits):
        bits = bits[::-1]
        length = ord(bits[0])
        return bases.string_to_natural((bits[1:] + '\0'*length)[:length])
    
    def _target_to_bits(self, target, _check=True):
        n = bases.natural_to_string(target)
        if n and ord(n[0]) >= 128:
            n = '\x00' + n
        bits2 = (chr(len(n)) + (n + 3*chr(0))[:3])[::-1]
        bits = struct.unpack('<I', bits2)[0]
        if _check:
            if self._bits_to_target(bits) != target:
                raise ValueError(repr((target, self._bits_to_target(bits, _check=False))))
        return bits

class PossiblyNone(Type):
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
        ('previous_output', PossiblyNone(dict(hash=0, index=2**32 - 1), ComposedType([
            ('hash', HashType()),
            ('index', StructType('<I')),
        ]))),
        ('script', VarStrType()),
        ('sequence', PossiblyNone(2**32 - 1, StructType('<I'))),
    ]))),
    ('tx_outs', ListType(ComposedType([
        ('value', StructType('<Q')),
        ('script', VarStrType()),
    ]))),
    ('lock_time', StructType('<I')),
])

block_header_type = ComposedType([
    ('version', StructType('<I')),
    ('previous_block', PossiblyNone(0, HashType())),
    ('merkle_root', HashType()),
    ('timestamp', StructType('<I')),
    ('target', FloatingIntegerType()),
    ('nonce', StructType('<I')),
])

block_type = ComposedType([
    ('header', block_header_type),
    ('txs', ListType(tx_type)),
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

def target_to_average_attempts(target):
    return 2**256//(target + 1)

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

# linked list tracker

class Tracker(object):
    def __init__(self):
        self.shares = {} # hash -> share
        self.reverse_shares = {} # previous_hash -> set of share_hashes
        
        self.heads = {} # head hash -> tail_hash
        self.tails = {} # tail hash -> set of head hashes
        self.heights = {} # share_hash -> height_to, other_share_hash
        self.skips = {} # share_hash -> skip list
        
        self.id_generator = itertools.count()
        self.tails_by_id = {}
    
    def add(self, share):
        assert not isinstance(share, (int, long, type(None)))
        if share.hash in self.shares:
            return # XXX raise exception?
        
        self.shares[share.hash] = share
        self.reverse_shares.setdefault(share.previous_hash, set()).add(share.hash)
        
        if share.hash in self.tails:
            heads = self.tails.pop(share.hash)
        else:
            heads = set([share.hash])
        
        if share.previous_hash in self.heads:
            tail = self.heads.pop(share.previous_hash)
        else:
            #dist, tail = self.get_height_and_last(share.previous_hash) # XXX this should be moved out of the critical area even though it shouldn't matter
            tail = share.previous_hash
            while tail in self.shares:
                tail = self.shares[tail].previous_hash
        
        self.tails.setdefault(tail, set()).update(heads)
        if share.previous_hash in self.tails[tail]:
            self.tails[tail].remove(share.previous_hash)
        
        for head in heads:
            self.heads[head] = tail
    
    def test(self):
        t = Tracker()
        for s in self.shares.itervalues():
            t.add(s)
        
        assert self.shares == t.shares, (self.shares, t.shares)
        assert self.reverse_shares == t.reverse_shares, (self.reverse_shares, t.reverse_shares)
        assert self.heads == t.heads, (self.heads, t.heads)
        assert self.tails == t.tails, (self.tails, t.tails)
    
    def remove(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        if share_hash not in self.shares:
            raise KeyError()
        share = self.shares[share_hash]
        del share_hash
        
        if share.hash in self.heads and share.previous_hash in self.tails:
            tail = self.heads.pop(share.hash)
            self.tails[tail].remove(share.hash)
            if not self.tails[share.previous_hash]:
                self.tails.pop(share.previous_hash)
        elif share.hash in self.heads:
            tail = self.heads.pop(share.hash)
            self.tails[tail].remove(share.hash)
            if self.reverse_shares[share.previous_hash] != set([share.hash]):
                pass # has sibling
            else:
                self.tails[tail].add(share.previous_hash)
                self.heads[share.previous_hash] = tail
        elif share.previous_hash in self.tails:
            raise NotImplementedError() # will break other things..
            heads = self.tails[share.previous_hash]
            if len(self.reverse_shares[share.previous_hash]) > 1:
                raise NotImplementedError()
            else:
                del self.tails[share.previous_hash]
                for head in heads:
                    self.heads[head] = share.hash
                self.tails[share.hash] = set(heads)
        else:
            raise NotImplementedError()
        
        '''
        height, tail = self.get_height_and_last(share.hash)
        
        if share.hash in self.heads:
            my_heads = set([share.hash])
        elif share.previous_hash in self.tails:
            my_heads = self.tails[share.previous_hash]
        else:
            some_heads = self.tails[tail]
            some_heads_heights = dict((that_head, self.get_height_and_last(that_head)[0]) for that_head in some_heads)
            my_heads = set(that_head for that_head in some_heads
                if some_heads_heights[that_head] > height and
                self.get_nth_parent_hash(that_head, some_heads_heights[that_head] - height) == share.hash)
        
        if share.previous_hash != tail:
            self.heads[share.previous_hash] = tail
        
        for head in my_heads:
            if head != share.hash:
                self.heads[head] = share.hash
            else:
                self.heads.pop(head)
        
        if share.hash in self.heads:
            self.heads.pop(share.hash)
        
        
        self.tails[tail].difference_update(my_heads)
        if share.previous_hash != tail:
            self.tails[tail].add(share.previous_hash)
        if not self.tails[tail]:
            self.tails.pop(tail)
        if my_heads != set([share.hash]):
            self.tails[share.hash] = set(my_heads) - set([share.hash])
        '''
        
        self.shares.pop(share.hash)
        self.reverse_shares[share.previous_hash].remove(share.hash)
        if not self.reverse_shares[share.previous_hash]:
            self.reverse_shares.pop(share.previous_hash)
        
        assert self.test() is None
    
    def get_height_and_last(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        orig = share_hash
        height = 0
        updates = []
        while True:
            if share_hash is None or share_hash not in self.shares:
                break
            updates.append((share_hash, height))
            if share_hash in self.heights:
                height_inc, share_hash = self.heights[share_hash]
            else:
                height_inc, share_hash = 1, self.shares[share_hash].previous_hash
            height += height_inc
        for update_hash, height_then in updates:
            self.heights[update_hash] = height - height_then, share_hash
        assert (height, share_hash) == self.get_height_and_last2(orig), ((height, share_hash), self.get_height_and_last2(orig))
        return height, share_hash
    
    def get_height_and_last2(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        height = 0
        while True:
            if share_hash not in self.shares:
                break
            share_hash = self.shares[share_hash].previous_hash
            height += 1
        return height, share_hash
    
    def get_chain_known(self, start_hash):
        assert isinstance(start_hash, (int, long, type(None)))
        '''
        Chain starting with item of hash I{start_hash} of items that this Tracker contains
        '''
        item_hash_to_get = start_hash
        while True:
            if item_hash_to_get not in self.shares:
                break
            share = self.shares[item_hash_to_get]
            assert not isinstance(share, long)
            yield share
            item_hash_to_get = share.previous_hash
    
    def get_chain_to_root(self, start_hash, root=None):
        assert isinstance(start_hash, (int, long, type(None)))
        assert isinstance(root, (int, long, type(None)))
        '''
        Chain of hashes starting with share_hash of shares to the root (doesn't include root)
        Raises an error if one is missing
        '''
        share_hash_to_get = start_hash
        while share_hash_to_get != root:
            share = self.shares[share_hash_to_get]
            yield share
            share_hash_to_get = share.previous_hash
    
    def get_best_hash(self):
        '''
        Returns hash of item with the most items in its chain
        '''
        if not self.heads:
            return None
        return max(self.heads, key=self.get_height_and_last)
    
    def get_highest_height(self):
        return max(self.get_height_and_last(head)[0] for head in self.heads) if self.heads else 0
    
    def get_nth_parent_hash(self, item_hash, n):
        if n < 0:
            raise ValueError('n must be >= 0')
        
        updates = {}
        while n:
            if item_hash not in self.skips:
                self.skips[item_hash] = math.geometric(.5), [(1, self.shares[item_hash].previous_hash)]
            skip_length, skip = self.skips[item_hash]
            
            for i in xrange(skip_length):
                if i in updates:
                    n_then, that_hash = updates.pop(i)
                    x, y = self.skips[that_hash]
                    assert len(y) == i
                    y.append((n_then - n, item_hash))
            
            for i in xrange(len(skip), skip_length):
                updates[i] = n, item_hash
            
            for i, (dist, then_hash) in enumerate(reversed(skip)):
                if dist <= n:
                    break
            else:
                raise AssertionError()
            
            n -= dist
            item_hash = then_hash
        
        return item_hash
    
    def get_nth_parent2(self, item_hash, n):
        x = item_hash
        for i in xrange(n):
            x = self.shares[item_hash].previous_hash
        return x

if __name__ == '__main__':
    class FakeShare(object):
        def __init__(self, hash, previous_hash):
            self.hash = hash
            self.previous_hash = previous_hash
    
    t = Tracker()
    
    for i in xrange(100):
        t.add(FakeShare(i, i - 1 if i > 0 else None))
    
    t.remove(99)
    
    print "HEADS", t.heads
    print "TAILS", t.tails
    
    import random
    
    while True:
        print
        print '-'*30
        print
        t = Tracker()
        for i in xrange(random.randrange(100)):
            x = random.choice(list(t.shares) + [None])
            print i, '->', x
            t.add(FakeShare(i, x))
        while t.shares:
            x = random.choice(list(t.shares))
            print "DEL", x, t.__dict__
            try:
                t.remove(x)
            except NotImplementedError:
                print "aborted; not implemented"
        import time
        time.sleep(.1)
        print "HEADS", t.heads
        print "TAILS", t.tails
    
    #for share_hash, share in sorted(t.shares.iteritems()):
    #    print share_hash, share.previous_hash, t.heads.get(share_hash), t.tails.get(share_hash)
    
    import sys;sys.exit()
    
    print t.get_nth_parent_hash(9000, 5000)
    print t.get_nth_parent_hash(9001, 412)
    #print t.get_nth_parent_hash(90, 51)
    
    for share_hash in sorted(t.shares):
        print str(share_hash).rjust(4),
        x = t.skips.get(share_hash, None)
        if x is not None:
            print str(x[0]).rjust(4),
            for a in x[1]:
                print str(a).rjust(10),
        print

# network definitions

class Mainnet(object):
    BITCOIN_P2P_PREFIX = 'f9beb4d9'.decode('hex')
    BITCOIN_P2P_PORT = 8333
    BITCOIN_ADDRESS_VERSION = 0

class Testnet(object):
    BITCOIN_P2P_PREFIX = 'fabfb5da'.decode('hex')
    BITCOIN_P2P_PORT = 18333
    BITCOIN_ADDRESS_VERSION = 111
