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

def hash256d(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()

def hash160(data):
    if data == '04ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664b'.decode('hex'):
        return 0x384f570ccc88ac2e7e00b026d1690a3fca63dd0 # hack for people who don't have openssl - this is the only value that p2pool ever hashes
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
    if not 'stripped_size' in tx:
        tx['stripped_size'] = tx_id_type.packed_size(tx)
    return tx['stripped_size']
def get_size(tx):
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

def pubkey_hash_to_address(pubkey_hash, addr_ver, bech32_ver, net):
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
    res = address_to_pubkey_hash(address, net)
    return pubkey_hash_to_script2(res[0], res[1], res[2], net)

def address_to_pubkey_hash(address, net):
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
        return int(''.join('{:02x}'.format(x) for x in witprog), 16), -1, witver

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
    has_witness = False
    if is_segwit_tx(tx):
        assert len(tx['tx_ins']) == len(tx['witness'])
        has_witness = any(len(w) > 0 for w in tx['witness'])
    if has_witness:
        return hash256(tx_type.pack(tx)) if txhash is None else txhash
    else:
        return hash256(tx_id_type.pack(tx)) if txid is None else txid

def get_txid(tx):
    return hash256(tx_id_type.pack(tx))

def pubkey_to_script2(pubkey):
    assert len(pubkey) <= 75
    return (chr(len(pubkey)) + pubkey) + '\xac'

def pubkey_hash_to_script2(pubkey_hash, version, bech32_version, net):
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

def script2_to_address(script2, addr_ver, bech32_ver, net):
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
    
    return 'Unknown. Script: %s'  % (script2.encode('hex'),)

def is_segwit_script(script):
    return script.startswith('\x00\x14') or script.startswith('\xa9\x14')
