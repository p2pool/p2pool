from __future__ import division

import hashlib

from p2pool.util import bases, math, pack

def hash256(data):
    return pack.IntType(256).unpack(hashlib.sha256(hashlib.sha256(data).digest()).digest())

def hash160(data):
    return pack.IntType(160).unpack(hashlib.new('ripemd160', hashlib.sha256(data).digest()).digest())

class ChecksummedType(pack.Type):
    def __init__(self, inner):
        self.inner = inner
    
    def read(self, file):
        obj, file = self.inner.read(file)
        data = self.inner.pack(obj)
        
        checksum, file = pack.read(file, 4)
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
        bits = pack.IntType(32).unpack(bits2)
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

class FloatingIntegerType(pack.Type):
    _inner = pack.IntType(32)
    
    def read(self, file):
        bits, file = self._inner.read(file)
        return FloatingInteger(bits), file
    
    def write(self, file, item):
        return self._inner.write(file, item.bits)

address_type = pack.ComposedType([
    ('services', pack.IntType(64)),
    ('address', pack.IPV6AddressType()),
    ('port', pack.IntType(16, 'big')),
])

tx_type = pack.ComposedType([
    ('version', pack.IntType(32)),
    ('tx_ins', pack.ListType(pack.ComposedType([
        ('previous_output', pack.PossiblyNoneType(dict(hash=0, index=2**32 - 1), pack.ComposedType([
            ('hash', pack.IntType(256)),
            ('index', pack.IntType(32)),
        ]))),
        ('script', pack.VarStrType()),
        ('sequence', pack.PossiblyNoneType(2**32 - 1, pack.IntType(32))),
    ]))),
    ('tx_outs', pack.ListType(pack.ComposedType([
        ('value', pack.IntType(64)),
        ('script', pack.VarStrType()),
    ]))),
    ('lock_time', pack.IntType(32)),
])

merkle_branch_type = pack.ListType(pack.IntType(256))

merkle_tx_type = pack.ComposedType([
    ('tx', tx_type),
    ('block_hash', pack.IntType(256)),
    ('merkle_branch', merkle_branch_type),
    ('index', pack.IntType(32)),
])

block_header_type = pack.ComposedType([
    ('version', pack.IntType(32)),
    ('previous_block', pack.PossiblyNoneType(0, pack.IntType(256))),
    ('merkle_root', pack.IntType(256)),
    ('timestamp', pack.IntType(32)),
    ('bits', FloatingIntegerType()),
    ('nonce', pack.IntType(32)),
])

block_type = pack.ComposedType([
    ('header', block_header_type),
    ('txs', pack.ListType(tx_type)),
])

aux_pow_type = pack.ComposedType([
    ('merkle_tx', merkle_tx_type),
    ('merkle_branch', merkle_branch_type),
    ('index', pack.IntType(32)),
    ('parent_block_header', block_header_type),
])


merkle_record_type = pack.ComposedType([
    ('left', pack.IntType(256)),
    ('right', pack.IntType(256)),
])

def merkle_hash(hashes):
    if not hashes:
        return 0
    hash_list = list(hashes)
    while len(hash_list) > 1:
        hash_list = [hash256(merkle_record_type.pack(dict(left=left, right=left if right is None else right)))
            for left, right in zip(hash_list[::2], hash_list[1::2] + [None])]
    return hash_list[0]

def calculate_merkle_branch(hashes, index):
    # XXX optimize this
    
    hash_list = [(h, i == index, []) for i, h in enumerate(hashes)]
    
    while len(hash_list) > 1:
        hash_list = [
            (
                hash256(merkle_record_type.pack(dict(left=left, right=right))),
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
    return reduce(lambda c, (i, h): hash256(merkle_record_type.pack(
        dict(left=h, right=c) if 2**i & index else
        dict(left=c, right=h)
    )), enumerate(merkle_branch), tip_hash)

def target_to_average_attempts(target):
    return 2**256//(target + 1)

def target_to_difficulty(target):
    return (0xffff0000 * 2**(256-64) + 1)/(target + 1)

# tx

def tx_get_sigop_count(tx):
    return sum(script.get_sigop_count(txin['script']) for txin in tx['tx_ins']) + sum(script.get_sigop_count(txout['script']) for txout in tx['tx_outs'])

# human addresses

base58_alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def base58_encode(bindata):
    bindata2 = bindata.lstrip(chr(0))
    return base58_alphabet[0]*(len(bindata) - len(bindata2)) + bases.natural_to_string(bases.string_to_natural(bindata2), base58_alphabet)

def base58_decode(b58data):
    b58data2 = b58data.lstrip(base58_alphabet[0])
    return chr(0)*(len(b58data) - len(b58data2)) + bases.natural_to_string(bases.string_to_natural(b58data2, base58_alphabet))

human_address_type = ChecksummedType(pack.ComposedType([
    ('version', pack.IntType(8)),
    ('pubkey_hash', pack.IntType(160)),
]))

def pubkey_hash_to_address(pubkey_hash, net):
    return base58_encode(human_address_type.pack(dict(version=net.ADDRESS_VERSION, pubkey_hash=pubkey_hash)))

def pubkey_to_address(pubkey, net):
    return pubkey_hash_to_address(hash160(pubkey), net)

def address_to_pubkey_hash(address, net):
    x = human_address_type.unpack(base58_decode(address))
    if x['version'] != net.ADDRESS_VERSION:
        raise ValueError('address not for this net!')
    return x['pubkey_hash']

# transactions

def pubkey_to_script2(pubkey):
    return ('\x41' + pubkey) + '\xac'

def pubkey_hash_to_script2(pubkey_hash):
    return '\x76\xa9' + ('\x14' + pack.IntType(160).pack(pubkey_hash)) + '\x88\xac'

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
        pubkey_hash = pack.IntType(160).unpack(script2[3:-2])
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
        pubkey_hash = pack.IntType(160).unpack(script2[3:-2])
        script2_test2 = pubkey_hash_to_script2(pubkey_hash)
    except:
        pass
    else:
        if script2_test2 == script2:
            return 'Address. Address: %s' % (pubkey_hash_to_address(pubkey_hash, net),)
    
    return 'Unknown. Script: %s'  % (script2.encode('hex'),)
