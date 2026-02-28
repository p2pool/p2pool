from __future__ import division

import hashlib
import random
import warnings
import binascii

import p2pool
from p2pool.util import math, pack, segwit_addr, cash_addr
import struct

mask = (1<<64) - 1

def hash256(data):
    return pack.IntType(256).unpack(hashlib.sha256(hashlib.sha256(data).digest()).digest())

def pack256(data):
    if data is None:
        data = 0
    return struct.pack("<QQQQ", data & mask, data>>64 & mask, data>>128 & mask,
                        data>>192 & mask)

def unpack256(data):
    raw = struct.unpack("<QQQQ", data)
    return (raw[3]<<192) + (raw[2]<<128) + (raw[1]<<64) + raw[0]

def hex_to_hash(data):
    return unpack256(data.decode('hex')[::-1])

def hash256d(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()

def hash160(data):
    if data == '04ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664b'.decode('hex'):
        return 0x384f570ccc88ac2e7e00b026d1690a3fca63dd0 # forrestv uncompressed pubkey (LeD2fnnDJYZuyt8zgDsZ2oBGmuVcxGKCLd)
    if data == '03ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1'.decode('hex'):
        return 0x7dec8dc4d5c39f0acbf3d34120432cb1f667aa74 # forrestv compressed pubkey (LVrpnVLEf3vU5rZahS7QF5UW8u6G1VgLUR)
    if data == '02fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a'.decode('hex'):
        return 0x613cafd91ab596762c115c7e94d5e4b1225ccb20 # our compressed pubkey (LNDMW3bAQ8Sz3Tzm6y3chYeuJTb8VHSHGM)
    return pack.IntType(160).unpack(hashlib.new('ripemd160', hashlib.sha256(data).digest()).digest())

class ChecksummedType(pack.Type):
    def __init__(self, inner, checksum_func=lambda data: hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]):
        self.inner = inner
        self.checksum_func = checksum_func
    
    def read(self, file):
        start = file.tell()
        obj = self.inner.read(file)
        end = file.tell()
        file.seek(start)
        data = file.read(end - start)
        
        calculated_checksum = self.checksum_func(data)
        checksum = file.read(len(calculated_checksum))
        if checksum != calculated_checksum:
            raise ValueError('invalid checksum')
        
        return obj
    
    def write(self, file, item):
        data = self.inner.pack(item)
        file.write(data)
        file.write(self.checksum_func(data))
        #return (file, data), self.checksum_func(data)

class FloatingInteger(object):
    __slots__ = ['bits', '_target']
    
    @classmethod
    def from_target_upper_bound(cls, target):
        n = math.natural_to_string(target)
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
        bits = self._inner.read(file)
        return FloatingInteger(bits)
    
    def write(self, file, item):
        return self._inner.write(file, item.bits)

address_type = pack.ComposedType([
    ('services', pack.IntType(64)),
    ('address', pack.IPV6AddressType()),
    ('port', pack.IntType(16, 'big')),
])

def is_segwit_tx(tx):
    # GBT dict transactions: segwit if hash != txid
    if isinstance(tx, dict) and 'hash' in tx and 'txid' in tx and 'data' in tx:
        return tx['hash'] != tx['txid']
    return tx.get('marker', -1) == 0 and tx.get('flag', -1) >= 1

tx_in_type = pack.ComposedType([
    ('previous_output', pack.PossiblyNoneType(dict(hash=0, index=2**32 - 1), pack.ComposedType([
        ('hash', pack.IntType(256)),
        ('index', pack.IntType(32)),
    ]))),
    ('script', pack.VarStrType()),
    ('sequence', pack.PossiblyNoneType(2**32 - 1, pack.IntType(32))),
])

tx_out_type = pack.ComposedType([
    ('value', pack.IntType(64)),
    ('script', pack.VarStrType()),
])

tx_id_type = pack.ComposedType([
    ('version', pack.IntType(32)),
    ('tx_ins', pack.ListType(tx_in_type)),
    ('tx_outs', pack.ListType(tx_out_type)),
    ('lock_time', pack.IntType(32))
])

def get_stripped_size(tx):
    # GBT dict transactions: use weight field to derive stripped size
    # weight = real_size + 3 * stripped_size, so stripped_size = (4 * real_size - weight) / 3
    if isinstance(tx, dict) and 'data' in tx and 'weight' in tx:
        real_size = len(tx['data']) // 2
        return (4 * real_size - tx['weight']) // 3
    if not 'stripped_size' in tx:
        tx['stripped_size'] = tx_id_type.packed_size(tx)
    return tx['stripped_size']
def get_size(tx):
    # GBT dict transactions: size is len(hex_data) / 2
    if isinstance(tx, dict) and 'data' in tx:
        return len(tx['data']) // 2
    if not 'size' in tx:
        tx['size'] = tx_id_type.packed_size(tx)
    return tx['size']

class TransactionType(pack.Type):
    _int_type = pack.IntType(32)
    _varint_type = pack.VarIntType()
    _witness_type = pack.ListType(pack.VarStrType())
    _wtx_type = pack.ComposedType([
        ('flag', pack.IntType(8)),
        ('tx_ins', pack.ListType(tx_in_type)),
        ('tx_outs', pack.ListType(tx_out_type))
    ])
    _ntx_type = pack.ComposedType([
        ('tx_outs', pack.ListType(tx_out_type)),
        ('lock_time', _int_type)
    ])
    _write_type = pack.ComposedType([
        ('version', _int_type),
        ('marker', pack.IntType(8)),
        ('flag', pack.IntType(8)),
        ('tx_ins', pack.ListType(tx_in_type)),
        ('tx_outs', pack.ListType(tx_out_type))
    ])

    def read(self, file):
        version = self._int_type.read(file)
        marker = self._varint_type.read(file)
        if marker == 0:
            next = self._wtx_type.read(file)
            witness = [None]*len(next['tx_ins'])
            for i in xrange(len(next['tx_ins'])):
                witness[i] = self._witness_type.read(file)
            locktime = self._int_type.read(file)
            return dict(version=version, marker=marker, flag=next['flag'], tx_ins=next['tx_ins'], tx_outs=next['tx_outs'], witness=witness, lock_time=locktime)
        else:
            tx_ins = [None]*marker
            for i in xrange(marker):
                tx_ins[i] = tx_in_type.read(file)
            next = self._ntx_type.read(file)
            return dict(version=version, tx_ins=tx_ins, tx_outs=next['tx_outs'], lock_time=next['lock_time'])
    
    def write(self, file, item):
        # Raw hex string transactions (from GBT rawtx approach): decode and write directly
        # This enables P2P block broadcast with hex-encoded txs from getblocktemplate
        if isinstance(item, (str, unicode)):
            file.write(item.decode('hex'))
            return
        # GBT dict transactions: write raw hex data directly
        if isinstance(item, dict) and 'data' in item and 'txid' in item:
            file.write(item['data'].decode('hex'))
            return
        if is_segwit_tx(item):
            assert len(item['tx_ins']) == len(item['witness'])
            self._write_type.write(file, item)
            for w in item['witness']:
                self._witness_type.write(file, w)
            self._int_type.write(file, item['lock_time'])
            return
        return tx_id_type.write(file, item)

tx_type = TransactionType()

merkle_link_type = pack.ComposedType([
    ('branch', pack.ListType(pack.IntType(256))),
    ('index', pack.IntType(32)),
])

merkle_tx_type = pack.ComposedType([
    ('tx', tx_id_type), # used only in aux_pow_type
    ('block_hash', pack.IntType(256)),
    ('merkle_link', merkle_link_type),
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

stripped_block_type = pack.ComposedType([
    ('header', block_header_type),
    ('txs', pack.ListType(tx_id_type)),
])

# merged mining

aux_pow_type = pack.ComposedType([
    ('merkle_tx', merkle_tx_type),
    ('merkle_link', merkle_link_type),
    ('parent_block_header', block_header_type),
])

aux_pow_coinbase_type = pack.ComposedType([
    ('merkle_root', pack.IntType(256, 'big')),
    ('size', pack.IntType(32)),
    ('nonce', pack.IntType(32)),
])

def make_auxpow_tree(chain_ids):
    for size in (2**i for i in xrange(31)):
        if size < len(chain_ids):
            continue
        res = {}
        for chain_id in chain_ids:
            pos = (1103515245 * chain_id + 1103515245 * 12345 + 12345) % size
            if pos in res:
                break
            res[pos] = chain_id
        else:
            return res, size
    raise AssertionError()

# merkle trees

merkle_record_type = pack.ComposedType([
    ('left', pack.IntType(256)),
    ('right', pack.IntType(256)),
])

class MerkleNode(object):
    """Class for building a merkle tree."""

    __slots__ = ('hash', 'parent', 'left', 'right')

    def __init__(self, hash, left=None, right=None, parent=None):
        if hash is None:
            self.hash = '0'
        else:
            self.hash = hash
        self.left = left
        self.right = right
        self.parent = parent

    def get_sibling(self):
        """Get the hash's sibling.

        Args:
            None

        Returns:
            The sibling MerkleNode of hash.
        """
        if not self.parent:
            raise ValueError("There is no sibling of this node.")
        if self == self.parent.left:
            return self.parent.right
        return self.parent.left

    def __hash__(self):
        return self.hash

    def __str__(self, level=0):
        ret = "%s%s\n" % ('\t'*level, self.hash)
        if self.left:
            ret += self.left.__str__(level=level+1)
        if self.right:
            ret += self.right.__str__(level=level+1)
        return ret

def merkle_hash(hashes):
    if not hashes:
        return 0
    hash_list = list(hashes)
    while len(hash_list) > 1:
        hash_list = [hash256(merkle_record_type.pack(dict(left=left, right=right)))
            for left, right in zip(hash_list[::2], hash_list[1::2] + [hash_list[::2][-1]])]
    return hash_list[0]

def build_merkle_tree(nodes):
    """Build a merkle tree from a list of hashes

    Args:
        nodes: A list of merkle nodes already part of the tree.

    Returns:
        The root merkle node.
    """
    if len(nodes) < 1:
        raise ValueError("No nodes in list to build a merkle tree with.")
    if len(nodes) == 1:
        return nodes[0]
    new_nodes = []
    for i in range(0, len(nodes), 2):
        try:
            right = nodes[i+1]
        except IndexError:
            right = nodes[i]
        new_node = MerkleNode(hash=hash256d(nodes[i].hash + right.hash),
                              left=nodes[i], right=right)
        nodes[i].parent = new_node
        try:
            nodes[i+1].parent = new_node
        except IndexError:
            pass
        new_nodes.append(new_node)
    return build_merkle_tree(new_nodes)

def calculate_merkle_link(hashes, index):
    assert index < len(hashes)
    merkle_nodes = [MerkleNode(pack256(x)) for x in hashes]
    merkle_tree = build_merkle_tree(merkle_nodes)
    merkle_branch = []
    index_node = merkle_nodes[index]
    while index_node.parent:
        merkle_branch.append(unpack256(index_node.get_sibling().hash))
        index_node = index_node.parent
    return {'index': index, 'branch': merkle_branch}

def check_merkle_link(tip_hash, link):
    if link['index'] >= 2**len(link['branch']):
        raise ValueError('index too large')
    return reduce(lambda c, (i, h): hash256(merkle_record_type.pack(
        dict(left=h, right=c) if (link['index'] >> i) & 1 else
        dict(left=c, right=h)
    )), enumerate(link['branch']), tip_hash)

# targets

def target_to_average_attempts(target):
    assert 0 <= target and isinstance(target, (int, long)), target
    if target >= 2**256: warnings.warn('target >= 2**256!')
    return 2**256//(target + 1)

def average_attempts_to_target(average_attempts):
    assert average_attempts > 0
    return min(int(2**256/average_attempts - 1 + 0.5), 2**256-1)

def target_to_difficulty(target):
    assert 0 <= target and isinstance(target, (int, long)), target
    if target >= 2**256: warnings.warn('target >= 2**256!')
    return (0xffff0000 * 2**(256-64) + 1)/(target + 1)

def difficulty_to_target(difficulty):
    assert difficulty >= 0
    if difficulty == 0: return 2**256-1
    return min(int((0xffff0000 * 2**(256-64) + 1)/difficulty - 1 + 0.5), 2**256-1)

# human addresses

base58_alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def base58_encode(bindata):
    bindata2 = bindata.lstrip(chr(0))
    return base58_alphabet[0]*(len(bindata) - len(bindata2)) + math.natural_to_string(math.string_to_natural(bindata2), base58_alphabet)

def base58_decode(b58data):
    b58data2 = b58data.lstrip(base58_alphabet[0])
    return chr(0)*(len(b58data) - len(b58data2)) + math.natural_to_string(math.string_to_natural(b58data2, base58_alphabet))

human_address_type = ChecksummedType(pack.ComposedType([
    ('version', pack.IntType(8)),
    ('pubkey_hash', pack.IntType(160)),
]))

# --- Address conversion caches ---
# These are pure functions: same input always produces same output.
# Caching avoids repeated base58/bech32 encode/decode on every share/template.
_cache_addr_to_pubkey_hash = {}   # (address, net_id) -> (pubkey_hash, version, witver)
_cache_addr_to_script2 = {}       # (address, net_id) -> script2
_cache_pubkey_hash_to_addr = {}   # (pubkey_hash, addr_ver, bech32_ver, net_id) -> address
_cache_pubkey_hash_to_script = {} # (pubkey_hash, version, bech32_version, net_id) -> script2

def _net_id(net):
    """Stable identity for a network object (used as cache key component)."""
    return id(net)

def clear_address_caches():
    """Clear all address conversion caches (for testing)."""
    _cache_addr_to_pubkey_hash.clear()
    _cache_addr_to_script2.clear()
    _cache_pubkey_hash_to_addr.clear()
    _cache_pubkey_hash_to_script.clear()
    _cache_script2_to_addr.clear()

def pubkey_hash_to_address(pubkey_hash, addr_ver, bech32_ver, net):
    cache_key = (pubkey_hash, addr_ver, bech32_ver, _net_id(net))
    cached = _cache_pubkey_hash_to_addr.get(cache_key)
    if cached is not None:
        return cached
    result = _pubkey_hash_to_address_impl(pubkey_hash, addr_ver, bech32_ver, net)
    _cache_pubkey_hash_to_addr[cache_key] = result
    return result

def _pubkey_hash_to_address_impl(pubkey_hash, addr_ver, bech32_ver, net):
    if addr_ver == -1:
        if hasattr(net, 'padding_bugfix') and net.padding_bugfix:
            thash = '{:040x}'.format(pubkey_hash)
        else:
            thash = '{:x}'.format(pubkey_hash)
            if len(thash) % 2 == 1:
                thash = '0%s' % thash
        data = [int(x) for x in bytearray.fromhex(thash)]
        if net.SYMBOL.lower() in ['bch', 'tbch', 'bsv', 'tbsv']:
            return cash_addr.encode(net.HUMAN_READABLE_PART, bech32_ver, data)
        else:
            return segwit_addr.encode(net.HUMAN_READABLE_PART, bech32_ver, data)
    return base58_encode(human_address_type.pack(dict(version=addr_ver, pubkey_hash=pubkey_hash)))

def pubkey_to_address(pubkey, net):
    return pubkey_hash_to_address(hash160(pubkey), net.ADDRESS_VERSION, -1, net)

class AddrError(Exception):
    __slots__ = ()

def address_to_script2(address, net):
    cache_key = (address, _net_id(net))
    cached = _cache_addr_to_script2.get(cache_key)
    if cached is not None:
        return cached
    res = address_to_pubkey_hash(address, net)
    result = pubkey_hash_to_script2(res[0], res[1], res[2], net)
    _cache_addr_to_script2[cache_key] = result
    return result

def address_to_pubkey_hash(address, net):
    cache_key = (address, _net_id(net))
    cached = _cache_addr_to_pubkey_hash.get(cache_key)
    if cached is not None:
        return cached
    result = _address_to_pubkey_hash_impl(address, net)
    _cache_addr_to_pubkey_hash[cache_key] = result
    return result

def _address_to_pubkey_hash_impl(address, net):
    try:
        return get_legacy_pubkey_hash(address, net)
    except AddrError:
        pass

    if net.SYMBOL.lower() not in ['bch', 'tbch', 'bsv', 'tbsv']:
        try:
            return get_bech32_pubkey_hash(address, net)
        except AddrError:
            pass
    else:
        try:
            return get_cashaddr_pubkey_hash(address, net)
        except AddrError:
            pass
    raise ValueError('invalid addr')

def get_legacy_pubkey_hash(address, net):
    # P2PKH or P2SH address
    try:
        base_decode = base58_decode(address)
        x = human_address_type.unpack(base_decode)
    except Exception as e:
        raise AddrError
    else:
        if x['version'] != net.ADDRESS_VERSION and x['version'] != net.ADDRESS_P2SH_VERSION:
            raise ValueError('address not for this net!')
        return x['pubkey_hash'], x['version'], -1

def get_bech32_pubkey_hash(address, net):
    try:
        witver, witprog = segwit_addr.decode(net.HUMAN_READABLE_PART, address)
        if witver is None or witprog is None:
            raise ValueError
    except Exception as e:
        raise AddrError
    else:
        # Return the witness program as integer, version -1 (indicates bech32), 
        # witness version, and the original byte length for P2WPKH/P2WSH distinction
        pubkey_hash_int = int(''.join('{:02x}'.format(x) for x in witprog), 16)
        return pubkey_hash_int, -1, witver

def get_cashaddr_pubkey_hash(address, net):
    try:
        ver, data = cash_addr.decode(net.HUMAN_READABLE_PART, address)
        if ver is None or data is None:
            raise ValueError
    except Exception as e:
        raise AddrError
    else:
        return int(''.join('{:02x}'.format(x) for x in data), 16), -1, ver

# transactions

def get_witness_commitment_hash(witness_root_hash, witness_reserved_value):
    return hash256(merkle_record_type.pack(dict(left=witness_root_hash, right=witness_reserved_value)))

def get_wtxid(tx, txid=None, txhash=None):
    # GBT dict transactions: 'hash' field is the wtxid
    if isinstance(tx, dict) and 'hash' in tx and 'data' in tx:
        return hex_to_hash(tx['hash'])
    has_witness = False
    if is_segwit_tx(tx):
        assert len(tx['tx_ins']) == len(tx['witness'])
        has_witness = any(len(w) > 0 for w in tx['witness'])
    if has_witness:
        return hash256(tx_type.pack(tx)) if txhash is None else txhash
    else:
        return hash256(tx_id_type.pack(tx)) if txid is None else txid

def get_txid(tx):
    # GBT dict transactions: 'txid' field is the txid
    if isinstance(tx, dict) and 'txid' in tx and 'data' in tx:
        return hex_to_hash(tx['txid'])
    return hash256(tx_id_type.pack(tx))

def pubkey_to_script2(pubkey):
    assert len(pubkey) <= 75
    return (chr(len(pubkey)) + pubkey) + '\xac'

def pubkey_hash_to_script2(pubkey_hash, version, bech32_version, net):
    cache_key = (pubkey_hash, version, bech32_version, _net_id(net))
    cached = _cache_pubkey_hash_to_script.get(cache_key)
    if cached is not None:
        return cached
    result = _pubkey_hash_to_script2_impl(pubkey_hash, version, bech32_version, net)
    _cache_pubkey_hash_to_script[cache_key] = result
    return result

def _pubkey_hash_to_script2_impl(pubkey_hash, version, bech32_version, net):
    if version == -1 and bech32_version >= 0:
        if hasattr(net, 'padding_bugfix') and net.padding_bugfix:
            decoded = '{:040x}'.format(pubkey_hash)
        else:
            decoded = '{:x}'.format(pubkey_hash)
        ehash = binascii.unhexlify(decoded)
        size = '{:x}'.format(len(decoded) // 2)
        if len(size) % 2 == 1:
            size = '0%s' % size
        hsize = binascii.unhexlify(size)
        if net.SYMBOL.lower() in ['bch', 'tbch', 'bsv', 'tbsv']:
            # CashAddrs can be longer than 20 bytes
            # TODO: Check the version and restrict the bytes.
            if bech32_version == 0:
                # P2KH
                return '\x76\xa9%s%s\x88\xac' % (hsize, ehash)
            elif bech32_version == 1:
                # P2SH
                return '\xa9%s%s\x87' % (hsize, ehash)
            else:
                raise NotImplementedError("Invalid cashaddr type %d" % bech32_version)
        else:
            return '\x00%s%s' % (hsize, ehash)
    if version == net.ADDRESS_P2SH_VERSION:
        return ('\xa9\x14' + pack.IntType(160).pack(pubkey_hash)) + '\x87'
    return '\x76\xa9' + ('\x14' + pack.IntType(160).pack(pubkey_hash)) + '\x88\xac'

_cache_script2_to_addr = {}  # (script2, addr_ver, bech32_ver, net_id) -> address

def script2_to_address(script2, addr_ver, bech32_ver, net):
    cache_key = (script2, addr_ver, bech32_ver, _net_id(net))
    cached = _cache_script2_to_addr.get(cache_key)
    if cached is not None:
        return cached
    result = _script2_to_address_impl(script2, addr_ver, bech32_ver, net)
    _cache_script2_to_addr[cache_key] = result
    return result

def _script2_to_address_impl(script2, addr_ver, bech32_ver, net):
    try:
        return script2_to_pubkey_address(script2, net)
    except AddrError:
        pass
    for func in [script2_to_pubkey_hash_address, script2_to_bech32_address,
                 script2_to_p2sh_address, script2_to_cashaddress]:
        try:
            return func(script2, addr_ver, bech32_ver, net)
        except AddrError:
            pass
    raise ValueError("Invalid script2 hash %s" % binascii.hexlify(script2))

def script2_to_pubkey_address(script2, net):
    try:
        pubkey = script2[1:-1]
        res = pubkey_to_script2(pubkey)
        if res != script2:
            raise ValueError
    except:
        raise AddrError
    return pubkey_to_address(pubkey, net)
    
def script2_to_pubkey_hash_address(script2, addr_ver, bech32_ver, net):
    # TODO: Check for BCH and BSV length, could be longer than 20 bytes
    try:
        pubkey_hash = pack.IntType(160).unpack(script2[3:-2])
        res = pubkey_hash_to_script2(pubkey_hash, addr_ver, bech32_ver, net)
        if res != script2:
            raise ValueError
    except Exception as e:
        raise AddrError
    return pubkey_hash_to_address(pubkey_hash, addr_ver, bech32_ver, net)

def script2_to_cashaddress(script2, addr_ver, ca_ver, net):
    try:
        if ca_ver == 0:
            sub_hash = script2[3:-2]
        elif ca_ver == 1:
            sub_hash = script2[2:-1]
        else:
            raise ValueError
        pubkey_hash = int(sub_hash.encode('hex'), 16)
        res = pubkey_hash_to_script2(pubkey_hash, addr_ver, ca_ver, net)
        if res != script2:
            raise ValueError
    except Exception as e:
        raise AddrError
    return pubkey_hash_to_address(pubkey_hash, addr_ver, ca_ver, net)

def script2_to_bech32_address(script2, addr_ver, bech32_ver, net):
    try:
        pubkey_hash = int(script2[2:].encode('hex'), 16)
        res = pubkey_hash_to_script2(pubkey_hash, addr_ver, bech32_ver, net)
        if res != script2:
            raise ValueError
    except Exception as e:
        raise AddrError
    return pubkey_hash_to_address(pubkey_hash, addr_ver, bech32_ver, net)

def script2_to_p2sh_address(script2, addr_ver, bech32_ver, net):
    # TODO: Check for BCH and BSV length, could be longer than 20 bytes
    try:
        pubkey_hash = pack.IntType(160).unpack(script2[2:-1])
        res = pubkey_hash_to_script2(pubkey_hash, addr_ver, bech32_ver, net)
        if res != script2:
            raise ValueError
    except Exception as e:
        raise AddrError
    return pubkey_hash_to_address(pubkey_hash, addr_ver, bech32_ver, net)

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
    
    # Try P2MS (n-of-m multisig)
    p2ms_display = p2ms_script_to_addresses(script2, net)
    if p2ms_display is not None:
        return 'Multisig. %s' % (p2ms_display,)
    
    return 'Unknown. Script: %s'  % (script2.encode('hex'),)

def parse_p2ms_script(script):
    """
    Parse a P2MS (n-of-m multisig) script and extract all pubkeys.
    
    P2MS format: OP_n <pubkey1> <pubkey2> ... <pubkeym> OP_m OP_CHECKMULTISIG
    - OP_n = 0x51-0x60 (1-16 required signatures)
    - OP_m = 0x51-0x60 (1-16 total pubkeys)
    - OP_CHECKMULTISIG = 0xae
    
    Returns: (n, m, [pubkey1, pubkey2, ...]) or None if not a valid P2MS script
    """
    if len(script) < 4 or script[-1] != '\xae':
        return None
    
    n_op = ord(script[0])
    m_op = ord(script[-2])
    
    # Valid OP_n and OP_m are 0x51 (OP_1) through 0x60 (OP_16)
    if not (0x51 <= n_op <= 0x60 and 0x51 <= m_op <= 0x60):
        return None
    
    n = n_op - 0x50  # Number of required signatures
    m = m_op - 0x50  # Number of pubkeys
    
    if n > m:
        return None
    
    # Parse pubkeys
    pubkeys = []
    pos = 1  # Start after OP_n
    
    while pos < len(script) - 2:  # Stop before OP_m and OP_CHECKMULTISIG
        push_len = ord(script[pos])
        
        if push_len == 0x41:  # 65-byte uncompressed pubkey
            if pos + 66 > len(script) - 2:
                return None
            pubkeys.append(script[pos+1:pos+66])
            pos += 66
        elif push_len == 0x21:  # 33-byte compressed pubkey
            if pos + 34 > len(script) - 2:
                return None
            pubkeys.append(script[pos+1:pos+34])
            pos += 34
        else:
            # Invalid push length or we've hit OP_m
            break
    
    if len(pubkeys) != m:
        return None
    
    return (n, m, pubkeys)

def p2ms_script_to_addresses(script, net):
    """
    Convert a P2MS script to a display-friendly string showing all addresses.
    
    Returns: "n-of-m: addr1, addr2, ..." or None if not a valid P2MS script
    """
    parsed = parse_p2ms_script(script)
    if parsed is None:
        return None
    
    n, m, pubkeys = parsed
    addresses = [pubkey_to_address(pk, net) for pk in pubkeys]
    return "%d-of-%d: %s" % (n, m, ", ".join(addresses))

def p2ms_script_to_address_list(script, net):
    """
    Convert a P2MS script to a list of addresses with metadata.
    
    Returns: {'n': int, 'm': int, 'addresses': [addr1, addr2, ...]} or None
    """
    parsed = parse_p2ms_script(script)
    if parsed is None:
        return None
    
    n, m, pubkeys = parsed
    addresses = [pubkey_to_address(pk, net) for pk in pubkeys]
    return {'n': n, 'm': m, 'addresses': addresses}

def is_segwit_script(script):
    return script.startswith('\x00\x14') or script.startswith('\xa9\x14')
