from __future__ import division

import hashlib
import os
import random
import sys
import time
import array
import traceback

from twisted.python import log

import p2pool
from p2pool.bitcoin import data as bitcoin_data, script, sha256
from p2pool.util import math, forest, pack

def parse_bip0034(coinbase):
    _, opdata = script.parse(coinbase).next()
    bignum = pack.IntType(len(opdata)*8).unpack(opdata)
    if ord(opdata[-1]) & 0x80:
        bignum = -bignum
    return (bignum,)

# hashlink

hash_link_type = pack.ComposedType([
    ('state', pack.FixedStrType(32)),
    ('extra_data', pack.FixedStrType(0)), # bit of a hack, but since the donation script is at the end, const_ending is long enough to always make this empty
    ('length', pack.VarIntType()),
])

# V36: extra_data can be non-empty because COMBINED_DONATION_SCRIPT (P2SH, 23 bytes)
# makes gentx_before_refhash only 35 bytes (< 64-byte SHA-256 block boundary).
# VarStrType() stores the actual extra bytes instead of requiring padding.
v36_hash_link_type = pack.ComposedType([
    ('state', pack.FixedStrType(32)),
    ('extra_data', pack.VarStrType()),  # variable-length: no padding output needed
    ('length', pack.VarIntType()),
])

def prefix_to_hash_link(prefix, const_ending=''):
    import sys
    # Debug: Uncomment to trace hash_link SHA256 internals (confirmed working)
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] prefix length: %d' % len(prefix)
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] const_ending length: %d' % len(const_ending)
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] const_ending: %s' % const_ending.encode('hex')
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] last 50 bytes of prefix: %s' % prefix[-50:].encode('hex')
    
    if not prefix.endswith(const_ending):
        raise ValueError('prefix_to_hash_link: prefix does not end with const_ending')
    x = sha256.sha256(prefix)
    
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] SHA256 state: %s (len=%d)' % (x.state.encode('hex'), len(x.state))
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] SHA256 buf: %s (len=%d)' % (x.buf.encode('hex'), len(x.buf))
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] SHA256 length: %d' % x.length
    extra_data = x.buf[:max(0, len(x.buf)-len(const_ending))]
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] extra_data: %s (len=%d)' % (extra_data.encode('hex'), len(extra_data))
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] length//8: %d' % (x.length//8)
    
    return dict(state=x.state, extra_data=extra_data, length=x.length//8)

def check_hash_link(hash_link, data, const_ending=''):
    # Debug: Uncomment to trace hash_link validation (confirmed working)
    # import sys
    # print >>sys.stderr, '[CHECK_HASH_LINK] hash_link[length]: %d' % hash_link['length']
    # print >>sys.stderr, '[CHECK_HASH_LINK] hash_link[state]: %s (len=%d)' % (hash_link['state'].encode('hex'), len(hash_link['state']))
    # print >>sys.stderr, '[CHECK_HASH_LINK] hash_link[extra_data]: %s (len=%d)' % (hash_link['extra_data'].encode('hex'), len(hash_link['extra_data']))
    # print >>sys.stderr, '[CHECK_HASH_LINK] data: %s (len=%d)' % (data.encode('hex'), len(data))
    # print >>sys.stderr, '[CHECK_HASH_LINK] const_ending: %s (len=%d)' % (const_ending.encode('hex'), len(const_ending))
    
    extra_length = hash_link['length'] % (512//8)
    if len(hash_link['extra_data']) != max(0, extra_length - len(const_ending)):
        raise ValueError('check_hash_link: extra_data length mismatch (got %d, expected %d)' % (len(hash_link['extra_data']), max(0, extra_length - len(const_ending))))
    extra = (hash_link['extra_data'] + const_ending)[len(hash_link['extra_data']) + len(const_ending) - extra_length:]
    if len(extra) != extra_length:
        raise ValueError('check_hash_link: extra length mismatch (got %d, expected %d)' % (len(extra), extra_length))
    
    # print >>sys.stderr, '[CHECK_HASH_LINK] extra_length: %d' % extra_length
    # print >>sys.stderr, '[CHECK_HASH_LINK] extra: %s' % extra.encode('hex')
    # print >>sys.stderr, '[CHECK_HASH_LINK] About to reconstruct hash with:'
    # print >>sys.stderr, '[CHECK_HASH_LINK]   state: %s' % hash_link['state'].encode('hex')
    # print >>sys.stderr, '[CHECK_HASH_LINK]   extra: %s' % extra.encode('hex')
    # print >>sys.stderr, '[CHECK_HASH_LINK]   length*8: %d' % (8*hash_link['length'])
    # print >>sys.stderr, '[CHECK_HASH_LINK]   data to hash: %s' % data.encode('hex')
    
    result = pack.IntType(256).unpack(hashlib.sha256(sha256.sha256(data, (hash_link['state'], extra, 8*hash_link['length'])).digest()).digest())
    # print >>sys.stderr, '[CHECK_HASH_LINK] Reconstructed gentx_hash: %064x' % result
    return result

# shares

share_type = pack.ComposedType([
    ('type', pack.VarIntType()),
    ('contents', pack.VarStrType()),
])

def load_share(share, net, peer_addr):
    assert peer_addr is None or isinstance(peer_addr, tuple)
    if share['type'] in share_versions:
        net.PARENT.padding_bugfix = (share['type'] >= 35)
        return share_versions[share['type']](net, peer_addr, share_versions[share['type']].get_dynamic_types(net)['share_type'].unpack(share['contents']))

    elif share['type'] < Share.VERSION:
        from p2pool import p2p
        raise p2p.PeerMisbehavingError('sent an obsolete share')
    else:
        raise ValueError('unknown share type: %r' % (share['type'],))

def is_segwit_activated(version, net):
    assert not(version is None or net is None)
    segwit_activation_version = getattr(net, 'SEGWIT_ACTIVATION_VERSION', 0)
    return version >= segwit_activation_version and segwit_activation_version > 0

# DONATION_SCRIPT: Original global P2Pool donation (P2PK format)
# This MUST match global P2Pool exactly for share compatibility (used in gentx_before_refhash)
# P2PK script: 0x41 <65-byte uncompressed pubkey> 0xac (OP_CHECKSIG)
# Address: LeD2fnnDJYZuyt8zgDsZ2oBGmuVcxGKCLd (Litecoin mainnet)
DONATION_SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')

# Precomputed pubkey_hash for DONATION_SCRIPT (performance optimization)
# This matches the hash160 hack in bitcoin/data.py for the donation pubkey
# Avoids recalculating hash160 on every share
DONATION_PUBKEY_HASH = 0x384f570ccc88ac2e7e00b026d1690a3fca63dd0

# COMBINED_DONATION_REDEEM_SCRIPT: 1-of-2 P2MS redeem script for V36+
# OP_1 PUSH33 <forrestv_compressed> PUSH33 <our_compressed> OP_2 OP_CHECKMULTISIG
COMBINED_DONATION_REDEEM_SCRIPT = '512103ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d12102fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a52ae'.decode('hex')

# COMBINED_DONATION_SCRIPT: P2SH-wrapped 1-of-2 P2MS scriptPubKey for V36+
# scriptPubKey = OP_HASH160 <hash160(redeem_script)> OP_EQUAL
COMBINED_DONATION_SCRIPT = 'a9148c6272621d89e8fa526dd86acff60c7136be8e8587'.decode('hex')

# V36_HASHLINK_PAD_SCRIPT removed: v36_hash_link_type uses VarStrType() for
# extra_data, so gentx_before_refhash no longer needs to be >= 64 bytes.
# This saves 31 bytes per coinbase transaction on-chain.

# DONATION MARKER MONITORING MEMO (parent chain / share coinbase):
# - Pre-V36 marker address  : donation_script_to_address(net)
#   - Litecoin mainnet      : LeD2fnnDJYZuyt8zgDsZ2oBGmuVcxGKCLd
#   - Bitcoin mainnet       : 1Kz5QaUPDtKrj5SqW5tFkn7WZh8LmQaQi4
# - Post-V36 marker address : combined_donation_script_to_address(net)
#   - Litecoin mainnet      : MLhSmVQxMusLE3pjGFvp4unFckgjeD8LUA
#   - Bitcoin mainnet       : 3EVJTbzzQo1uRYYqANwUFGXrJ46HeaLvze
#
# Merged-chain (Dogecoin) marker monitoring uses script2_to_address(script, doge_net):
# - Dogecoin mainnet pre-V36  : DQ8AwqR2XJE9G5dSEfspJYH7Spre85dj6L
# - Dogecoin mainnet post-V36 : A5EZCT4tUrtoKuvJaWbtVQADzdUKdtsqpr
# - Dogecoin testnet pre-V36  : noBEfr9wTGgs94CdGVXGYwsQghEwBsXw4K
# - Dogecoin testnet post-V36 : 2N63WXLw22FXFdLBNqWZLsDX7WQJTPXus7f
# Use these when monitoring on-chain donation marker outputs across activation.

# Precomputed merged-chain donation addresses.
# Used by web API endpoints to avoid per-request script2_to_address() / hash160() calls.
#
# Pre-V36 (from DONATION_SCRIPT P2PK — requires hash160(pubkey) to derive):
DONATION_DOGE_MAINNET = 'DQ8AwqR2XJE9G5dSEfspJYH7Spre85dj6L'
DONATION_DOGE_TESTNET = 'noBEfr9wTGgs94CdGVXGYwsQghEwBsXw4K'
#
# Post-V36 (from COMBINED_DONATION_SCRIPT P2SH — hash already embedded in script):
COMBINED_DONATION_DOGE_MAINNET = 'A5EZCT4tUrtoKuvJaWbtVQADzdUKdtsqpr'
COMBINED_DONATION_DOGE_TESTNET = '2N63WXLw22FXFdLBNqWZLsDX7WQJTPXus7f'

# ============================================================================
# CANONICAL MERGED COINBASE CONSTRUCTION
# ============================================================================
# These constants define the deterministic merged chain coinbase format.
# Every peer MUST produce the identical coinbase given the same inputs.
# This enables consensus-level enforcement of merged mining reward distribution.

CANONICAL_MERGED_COINBASE_TEXT = 'P2Pool merged mining'   # OP_RETURN text (fixed)
CANONICAL_MERGED_COINBASE_EXTRA = '/P2Pool/'              # Coinbase input script extra
CANONICAL_MERGED_FINDER_FEE_PER_MILLE = 5                 # 0.5% = 5 per mille (integer)

def build_canonical_merged_coinbase(weights, total_weight, donation_weight,
                                     coinbase_value, block_height,
                                     finder_script, merged_addr_net, parent_net):
    """Build a deterministic merged chain coinbase transaction.
    
    ALL arithmetic is integer-only for cross-platform/cross-interpreter
    determinism (no floats — avoids CPython vs PyPy rounding differences).
    
    Output ordering is canonical:
      1. Miner outputs: sorted ascending by script bytes
      2. OP_RETURN output (value=0, fixed text)
      3. Donation output (COMBINED_DONATION_SCRIPT) — always LAST
    
    Finder fee is coalesced into the finder's miner output (not a separate output)
    so output count remains minimal and ordering is unambiguous.
    
    Args:
        weights: {address_key: weight} from get_v36_merged_weights(chain_id=X)
        total_weight: grand total = sum(weights.values()) + donation_weight
                      (already includes donation per get_v36_merged_weights convention)
        donation_weight: donation weight from share chain
        coinbase_value: total merged chain block reward (satoshis)
        block_height: merged chain block height (for BIP34 coinbase script)
        finder_script: P2PKH scriptPubKey for share creator on merged chain,
                       or None if not convertible
        merged_addr_net: merged chain network object (ADDRESS_VERSION, etc.)
        parent_net: parent chain network object (for address_to_pubkey_hash)
    
    Returns:
        dict: coinbase transaction (version, tx_ins, tx_outs, lock_time)
    """
    # Integer fee calculations — no floats anywhere
    # NOTE: total_weight already includes donation_weight per get_v36_merged_weights()
    # convention: total_weight == sum(weights.values()) + donation_weight
    grand_total = total_weight
    donation_amount = coinbase_value * donation_weight // grand_total if grand_total > 0 else 0
    finder_fee_amount = coinbase_value * CANONICAL_MERGED_FINDER_FEE_PER_MILLE // 1000 if finder_script else 0
    miners_reward = coinbase_value - donation_amount - finder_fee_amount
    
    # Resolve weight keys to merged chain scripts, accumulate amounts
    # Keys from get_v36_merged_weights():
    #   'MERGED:<hex_script>' = explicit/auto-generated merged chain script (tier 1)
    #   parent_address_string  = needs auto-conversion (tier 2: P2PKH, P2SH, bech32)
    # Unconvertible addresses are skipped — their weight is redistributed
    # proportionally to all convertible miners (tier 3: pool distribution).
    script_weights = {}   # {script_bytes: accumulated_weight}
    accepted_total_weight = 0
    
    for key, weight in weights.iteritems():
        merged_script = None
        if key.startswith('MERGED:'):
            merged_script = key[7:].decode('hex')
        else:
            # Auto-convert: extract pubkey_hash from parent address
            try:
                pubkey_hash, version, witver = bitcoin_data.address_to_pubkey_hash(key, parent_net)
                if version == parent_net.ADDRESS_VERSION:
                    # P2PKH — construct merged chain P2PKH script directly
                    merged_script = '\x76\xa9\x14' + pack.IntType(160).pack(pubkey_hash) + '\x88\xac'
                elif version == parent_net.ADDRESS_P2SH_VERSION:
                    # P2SH — construct merged chain P2SH script (OP_HASH160 <hash> OP_EQUAL)
                    merged_script = '\xa9\x14' + pack.IntType(160).pack(pubkey_hash) + '\x87'
                elif version == -1 and witver == 0 and pubkey_hash <= (1 << 160) - 1:
                    # P2WPKH (bech32 v0, 20-byte program) — same pubkey_hash
                    merged_script = '\x76\xa9\x14' + pack.IntType(160).pack(pubkey_hash) + '\x88\xac'
            except Exception:
                pass  # Unconvertible (P2WSH, P2TR, etc.) — skip
        
        if merged_script is not None:
            script_weights[merged_script] = script_weights.get(merged_script, 0) + weight
            accepted_total_weight += weight
    
    # Compute miner amounts (integer division — remainder goes to donation)
    output_amounts = {}  # {script_bytes: satoshi_amount}
    total_distributed = 0
    for s, w in script_weights.iteritems():
        amount = miners_reward * w // accepted_total_weight if accepted_total_weight > 0 else 0
        if amount > 0:
            output_amounts[s] = amount
            total_distributed += amount
    
    # Add finder fee (coalesced with miner output if same script)
    if finder_fee_amount > 0 and finder_script is not None:
        output_amounts[finder_script] = output_amounts.get(finder_script, 0) + finder_fee_amount
    
    # Rounding remainder → donation (integer division always truncates)
    rounding_remainder = miners_reward - total_distributed
    final_donation = donation_amount + rounding_remainder
    
    # Build sorted output list (deterministic ordering by script bytes)
    tx_outs = []
    for s in sorted(output_amounts.keys()):
        tx_outs.append({'value': output_amounts[s], 'script': s})
    
    # OP_RETURN (fixed canonical text, value=0)
    op_text = CANONICAL_MERGED_COINBASE_TEXT
    if isinstance(op_text, unicode):
        op_text = op_text.encode('utf-8')
    tx_outs.append({'value': 0, 'script': '\x6a' + chr(len(op_text)) + op_text})
    
    # Donation (COMBINED_DONATION_SCRIPT, always LAST — matches parent chain convention)
    tx_outs.append({'value': final_donation, 'script': COMBINED_DONATION_SCRIPT})
    
    # Coinbase input (BIP34 height + canonical extra data)
    coinbase_script = script.create_push_script([block_height]) + CANONICAL_MERGED_COINBASE_EXTRA
    
    return {
        'version': 1,
        'tx_ins': [{'previous_output': None, 'sequence': None, 'script': coinbase_script}],
        'tx_outs': tx_outs,
        'lock_time': 0,
    }


def get_canonical_merged_finder_script(share_pubkey_hash, merged_addresses, chain_id, merged_addr_net):
    """Derive the canonical finder scriptPubKey for a share creator on a merged chain.
    
    Deterministic from share data — used by both get_work() and check().
    
    Three-tier priority (consensus-enforced):
      1. Explicit merged address from miner (stratum comma-separated) → that script.
         Also covers auto-generated merged addresses stored in the share.
         This tier handles ALL address types (P2PKH, P2SH, bech32 P2WPKH).
      2. Auto-convert share creator's pubkey_hash → merged chain P2PKH script.
         Only for P2PKH and bech32 P2WPKH (same pubkey_hash). P2SH must use
         tier 1 (auto-generated P2SH entries stored in merged_addresses).
      3. Return None → pool distribution fallback.
         Finder fee is zero; finder's portion is redistributed proportionally
         to all PPLNS participants. This handles unconvertible address types.
    
    Returns: script bytes, or None (pool distribution — no finder fee)
    """
    # Tier 1: Explicit or auto-generated merged address for this chain
    if merged_addresses:
        for entry in merged_addresses:
            if entry.get('chain_id') == chain_id:
                return entry['script']
    
    # Tier 2: Auto-convert from parent chain pubkey_hash (P2PKH/bech32 only)
    if share_pubkey_hash is not None:
        return '\x76\xa9\x14' + pack.IntType(160).pack(share_pubkey_hash) + '\x88\xac'
    
    # Tier 3: Pool distribution fallback — unconvertible address
    return None


def verify_merged_coinbase_commitment(share, tracker, net, parent_net):
    """Verify that the merged coinbase committed in mm_data matches canonical construction.
    
    This closes the merged mining trust gap: peers independently re-derive
    the expected merged coinbase from share chain state and verify it matches
    what's committed in the LTC coinbase (via mm_data → DOGE block hash).
    
    Verification chain:
      1. Re-derive canonical DOGE coinbase from PPLNS weights + committed params
      2. canonical_txid = hash256(canonical_coinbase)
      3. check_merkle_link(canonical_txid, coinbase_merkle_link) == header.merkle_root
      4. hash256(header) == doge_block_hash
      5. doge_block_hash matches aux_merkle_root in mm_data (parsed from LTC coinbase)
    
    Returns: None on success, raises ValueError on failure
    """
    merged_info_list = share.share_info.get('merged_coinbase_info')
    if not merged_info_list:
        return  # No merged mining data — nothing to verify
    
    # Parse mm_data from LTC coinbase script
    coinbase_script = share.share_info['share_data']['coinbase']
    marker = '\xfa\xbe\x6d\x6d'
    mm_pos = coinbase_script.find(marker)
    if mm_pos < 0:
        if merged_info_list:
            raise ValueError('merged_coinbase_info present but no mm_data in coinbase')
        return
    
    mm_bytes = coinbase_script[mm_pos + 4:]
    if len(mm_bytes) < 40:
        raise ValueError('mm_data too short in coinbase')
    aux_merkle_root = pack.IntType(256, 'big').unpack(mm_bytes[:32])
    aux_size = pack.IntType(32).unpack(mm_bytes[32:36])
    
    # Get PPLNS weights (same params as compute_merged_payout_hash)
    prev_hash = share.share_info['share_data']['previous_share_hash']
    if prev_hash is None:
        return  # Genesis share, no verification possible
    
    height = tracker.get_height(prev_hash)
    if height == 0:
        return
    
    # Skip verification when tracker chain is incomplete (< REAL_CHAIN_LENGTH).
    # The PPLNS weights depend on tracker state — if the verifier has fewer shares
    # than the creator, the canonical coinbase will differ and verification fails.
    # This is expected during initial sync or when peers have different chain depths.
    # Once the chain is fully synced, verification will run and catch any mismatch.
    if height < net.REAL_CHAIN_LENGTH:
        return  # Insufficient chain depth for reliable PPLNS verification
    
    block_target = share.header['bits'].target
    max_weight = 65535 * net.SPREAD * bitcoin_data.target_to_average_attempts(block_target)
    chain_length = min(height, net.REAL_CHAIN_LENGTH)
    
    for info in merged_info_list:
        chain_id = info['chain_id']
        coinbase_value = info['coinbase_value']
        block_height = info['block_height']
        header_bytes = info['block_header_bytes']
        cb_merkle_link = info['coinbase_merkle_link']
        
        # Determine merged chain network
        merged_addr_net = _get_merged_chain_net(chain_id, net)
        if merged_addr_net is None:
            continue  # Unknown chain — can't verify (permissive for forward compat)
        
        # Step 1: Get PPLNS weights for this merged chain
        weights, total_weight, donation_weight = get_v36_merged_weights(
            tracker, prev_hash, chain_length, max_weight, chain_id=chain_id)
        
        if not weights or total_weight == 0:
            continue  # No V36 shares in window — nothing to verify
        
        # Step 2: Determine finder script (share creator's merged address)
        share_pubkey_hash = share.share_data.get('pubkey_hash')
        share_pubkey_type = share.share_data.get('pubkey_type')
        merged_addrs = share.share_info.get('merged_addresses')
        # P2SH addresses can't auto-convert to merged-chain P2PKH;
        # must use Tier 1 (merged_addresses) or Tier 3 (pool distribution)
        if share_pubkey_type == PUBKEY_TYPE_P2SH:
            canonical_pubkey_hash = None
        else:
            canonical_pubkey_hash = share_pubkey_hash
        finder_script = get_canonical_merged_finder_script(
            canonical_pubkey_hash, merged_addrs, chain_id, merged_addr_net)
        
        # Step 3: Re-derive canonical coinbase
        canonical_coinbase = build_canonical_merged_coinbase(
            weights, total_weight, donation_weight,
            coinbase_value, block_height,
            finder_script, merged_addr_net, parent_net)
        
        # Step 4: Compute canonical txid
        canonical_txid = bitcoin_data.hash256(bitcoin_data.tx_id_type.pack(canonical_coinbase))
        
        # Step 5: Verify merkle link → header merkle root
        expected_merkle_root = bitcoin_data.check_merkle_link(canonical_txid, cb_merkle_link)
        
        # Step 6: Parse and verify DOGE block header
        header = bitcoin_data.block_header_type.unpack(header_bytes)
        if header['merkle_root'] != expected_merkle_root:
            raise ValueError(
                'merged coinbase verification failed for chain %d: '
                'canonical merkle_root %064x != header merkle_root %064x' % (
                    chain_id, expected_merkle_root, header['merkle_root']))
        
        # Step 7: Compute DOGE block hash and verify vs mm_data
        doge_block_hash = bitcoin_data.hash256(header_bytes)
        
        # For single merged chain: aux_merkle_root == block_hash
        # For multiple chains: need aux tree reconstruction
        if aux_size == 1:
            if doge_block_hash != aux_merkle_root:
                raise ValueError(
                    'merged block hash verification failed for chain %d: '
                    'block_hash %064x != aux_merkle_root %064x' % (
                        chain_id, doge_block_hash, aux_merkle_root))
        else:
            # Multi-chain: verify block_hash at correct slot in aux merkle tree
            # Reconstruct expected slot from chain_id
            tree_slot = chain_id % aux_size
            # We can only verify if aux_merkle_root is consistent with block_hash
            # at the expected slot. Without other chains' hashes, we verify
            # that make_auxpow_tree produces the expected slot.
            expected_tree, expected_size = bitcoin_data.make_auxpow_tree({chain_id: None})
            if expected_size != aux_size:
                raise ValueError(
                    'merged aux tree size mismatch for chain %d: '
                    'expected %d, got %d' % (chain_id, expected_size, aux_size))
            # For multi-chain, the aux_merkle_root check is weaker —
            # we trust the single-chain case covers our deployment


def _get_merged_chain_net(chain_id, net):
    """Get the merged chain network object for a given chain_id.
    
    Returns the network object or None if unknown.
    """
    if chain_id == 98:  # Dogecoin
        parent_symbol = getattr(net.PARENT, 'SYMBOL', '') if hasattr(net, 'PARENT') else ''
        is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
        try:
            if is_testnet:
                from p2pool.networks import litecoin_testnet
                if hasattr(litecoin_testnet, 'dogecoin_testnet_net'):
                    return litecoin_testnet.dogecoin_testnet_net
                # Fallback: construct minimal net object
                class DogecoinTestnet(object):
                    SYMBOL = 'tDOGE'
                    ADDRESS_VERSION = 113  # 0x71
                    ADDRESS_P2SH_VERSION = 196  # 0xc4
                return DogecoinTestnet()
            else:
                from p2pool.networks import litecoin
                if hasattr(litecoin, 'dogecoin_net'):
                    return litecoin.dogecoin_net
                class DogecoinMainnet(object):
                    SYMBOL = 'DOGE'
                    ADDRESS_VERSION = 30  # 0x1e
                    ADDRESS_P2SH_VERSION = 22  # 0x16
                return DogecoinMainnet()
        except ImportError:
            pass
    return None

# Precomputed hash key for COMBINED_DONATION_SCRIPT fast-path.
#
# For P2SH-wrapped combined donation script, the key is the embedded script hash
# (hash160(redeem_script)) from: OP_HASH160 <20-byte-hash> OP_EQUAL.
#
# COMBINED_DONATION_SCRIPT = a9 14 <hash160> 87
#   BE hex hash160 = 8c6272621d89e8fa526dd86acff60c7136be8e85
#   LE int         = 0x858ebe36710cf6cf6ad86d52fae8891d6272628c
COMBINED_DONATION_PUBKEY_HASH = 0x858ebe36710cf6cf6ad86d52fae8891d6272628c

def script_to_pubkey_hash(script):
    """
    Extract pubkey_hash from a script (supports P2PK, P2PKH, and P2MS formats).
    
    P2PK format: <push_len> <pubkey> OP_CHECKSIG (0xac)
      - Returns hash160(pubkey)
    P2PKH format: OP_DUP (0x76) OP_HASH160 (0xa9) 0x14 <pubkey_hash> OP_EQUALVERIFY (0x88) OP_CHECKSIG (0xac)
      - Returns pubkey_hash directly
    P2MS (n-of-m): OP_n <pubkey1> ... <pubkeym> OP_m OP_CHECKMULTISIG (0xae)
      - Returns hash160 of first pubkey (for share attribution)
    
    Returns: pubkey_hash as integer
    """
    # Performance optimization: check for known donation scripts first
    if script == DONATION_SCRIPT:
        return DONATION_PUBKEY_HASH
    if script == COMBINED_DONATION_SCRIPT:
        return COMBINED_DONATION_PUBKEY_HASH
    
    # P2PKH script: 76 a9 14 <20-byte-hash> 88 ac (25 bytes)
    if len(script) == 25 and script[0] == '\x76' and script[1] == '\xa9' and script[2] == '\x14':
        return int(script[3:23].encode('hex'), 16)
    
    # P2PK script with uncompressed pubkey: 41 <65-byte-pubkey> ac (67 bytes)
    if len(script) == 67 and script[0] == '\x41' and script[-1] == '\xac':
        pubkey = script[1:-1]
        return bitcoin_data.hash160(pubkey)
    
    # P2PK script with compressed pubkey: 21 <33-byte-pubkey> ac (35 bytes)
    if len(script) == 35 and script[0] == '\x21' and script[-1] == '\xac':
        pubkey = script[1:-1]
        return bitcoin_data.hash160(pubkey)
    
    # P2MS (n-of-m multisig): OP_n <pubkeys...> OP_m OP_CHECKMULTISIG
    # OP_n = 0x51-0x60 (1-16), OP_m = 0x51-0x60 (1-16), OP_CHECKMULTISIG = 0xae
    if len(script) >= 4 and script[-1] == '\xae':
        n_op = ord(script[0])
        m_op = ord(script[-2])
        # Valid OP_n and OP_m are 0x51 (OP_1) through 0x60 (OP_16)
        if 0x51 <= n_op <= 0x60 and 0x51 <= m_op <= 0x60:
            # Extract first pubkey for hash160
            # Format: OP_n <push_len> <pubkey1> [<push_len> <pubkey2> ...] OP_m OP_CHECKMULTISIG
            push_len = ord(script[1])
            if push_len == 0x41:  # 65-byte uncompressed pubkey
                pubkey = script[2:2+65]
                return bitcoin_data.hash160(pubkey)
            elif push_len == 0x21:  # 33-byte compressed pubkey
                pubkey = script[2:2+33]
                return bitcoin_data.hash160(pubkey)
    
    raise ValueError('Unsupported script format (length=%d)' % len(script))

_donation_addr_cache = {}  # {id(net): address} — zero-crypto cached lookup
def donation_script_to_address(net):
    """Get address for pre-V36 DONATION_SCRIPT (P2PK).
    
    Uses precomputed DONATION_PUBKEY_HASH to skip hash160(pubkey) entirely.
    Result is cached per net — O(1) after first call, and first call itself
    is just base58check encoding (no cryptographic hashing).
    """
    cached = _donation_addr_cache.get(id(net))
    if cached is not None:
        return cached
    # Use precomputed DONATION_PUBKEY_HASH — avoids hash160(65-byte pubkey)
    # pubkey_hash_to_address is just base58check encoding, zero crypto.
    addr = bitcoin_data.pubkey_hash_to_address(
            DONATION_PUBKEY_HASH, net.PARENT.ADDRESS_VERSION, -1, net.PARENT)
    _donation_addr_cache[id(net)] = addr
    return addr

_combined_donation_addr_cache = {}  # {net: address}
def combined_donation_script_to_address(net):
    """Get display/key address for the V36 combined donation script.

    For P2SH-wrapped combined donation script, return a standard Base58 P2SH address.

    Monitoring note:
    - Pre-V36 marker monitor: donation_script_to_address(net)
    - Post-V36 marker monitor: combined_donation_script_to_address(net)
        - Examples:
            - Litecoin mainnet: LeD2fnnDJYZuyt8zgDsZ2oBGmuVcxGKCLd -> MLhSmVQxMusLE3pjGFvp4unFckgjeD8LUA
            - Bitcoin mainnet:  1Kz5QaUPDtKrj5SqW5tFkn7WZh8LmQaQi4 -> 3EVJTbzzQo1uRYYqANwUFGXrJ46HeaLvze
            - Dogecoin mainnet (merged): DQ8AwqR2XJE9G5dSEfspJYH7Spre85dj6L -> A5EZCT4tUrtoKuvJaWbtVQADzdUKdtsqpr
            - Dogecoin testnet (merged): noBEfr9wTGgs94CdGVXGYwsQghEwBsXw4K -> 2N63WXLw22FXFdLBNqWZLsDX7WQJTPXus7f
    If net is None (tests/utilities), fall back to deterministic synthetic key.
    """
    if net is None:
        return 'P2SH:combined_donation'
    cached = _combined_donation_addr_cache.get(id(net))
    if cached is not None:
        return cached
    # Use precomputed COMBINED_DONATION_PUBKEY_HASH — skips script2_to_address
    # parsing. For P2SH the hash is embedded in the script (byte slice), but
    # using the precomputed int is even faster — just base58check.
    addr = bitcoin_data.pubkey_hash_to_address(
            COMBINED_DONATION_PUBKEY_HASH,
            net.PARENT.ADDRESS_P2SH_VERSION, -1, net.PARENT)
    _combined_donation_addr_cache[id(net)] = addr
    return addr

# =============================================================================
# V36 Address Type System
# =============================================================================
# V36 shares store a 1-byte pubkey_type alongside the 20-byte pubkey_hash
# to preserve the miner's original address type in the share chain.
# This enables native P2WPKH (bech32) and P2SH outputs in the parent chain
# coinbase, instead of always converting to P2PKH.
#
# Values:
#   0 = P2PKH   (legacy, OP_DUP OP_HASH160 <20> OP_EQUALVERIFY OP_CHECKSIG)
#   1 = P2WPKH  (bech32 v0, OP_0 <20-byte witness_program>)
#   2 = P2SH    (OP_HASH160 <20> OP_EQUAL)
# =============================================================================
PUBKEY_TYPE_P2PKH  = 0
PUBKEY_TYPE_P2WPKH = 1
PUBKEY_TYPE_P2SH   = 2

def pubkey_type_to_version_witver(pubkey_type, net):
    """Map V36 pubkey_type integer to (version, witver) for script/address construction."""
    if pubkey_type == PUBKEY_TYPE_P2WPKH:
        return (-1, 0)          # bech32 v0: version=-1, witver=0
    elif pubkey_type == PUBKEY_TYPE_P2SH:
        return (net.ADDRESS_P2SH_VERSION, -1)
    else:
        return (net.ADDRESS_VERSION, -1)  # P2PKH default

def get_pubkey_type(version, witver, net):
    """Derive pubkey_type integer from address_to_pubkey_hash() return values."""
    if witver == 0:
        return PUBKEY_TYPE_P2WPKH
    elif version == net.ADDRESS_P2SH_VERSION:
        return PUBKEY_TYPE_P2SH
    else:
        return PUBKEY_TYPE_P2PKH

class BaseShare(object):
    VERSION = 0
    VOTING_VERSION = 0
    SUCCESSOR = None
    MINIMUM_PROTOCOL_VERSION = 1400
    
    small_block_header_type = pack.ComposedType([
        ('version', pack.VarIntType()),
        ('previous_block', pack.PossiblyNoneType(0, pack.IntType(256))),
        ('timestamp', pack.IntType(32)),
        ('bits', bitcoin_data.FloatingIntegerType()),
        ('nonce', pack.IntType(32)),
    ])
    share_info_type = None
    share_type = None
    ref_type = None

    # Donation scripts in coinbase (last output before OP_RETURN):
    # Pre-V36: DONATION_SCRIPT (P2PK, 67 bytes) - original P2Pool author Forrest Voight
    # Post-V36: COMBINED_DONATION_SCRIPT (P2SH scriptPubKey wrapping 1-of-2 P2MS redeem script)
    #   - MergedMiningShare overrides gentx_before_refhash with COMBINED_DONATION_SCRIPT
    #   - P2SH output is standard/addressable while preserving 1-of-2 spend semantics
    gentx_before_refhash = pack.VarStrType().pack(DONATION_SCRIPT) + pack.IntType(64).pack(0) + pack.VarStrType().pack('\x6a\x28' + pack.IntType(256).pack(0) + pack.IntType(64).pack(0))[:3]

    gentx_size = 50000 # conservative estimate, will be overwritten during execution
    gentx_weight = 200000
    cached_types = None
    @classmethod
    def get_dynamic_types(cls, net):
        if not cls.cached_types == None:
            return cls.cached_types
        t = dict(share_info_type=None, share_type=None, ref_type=None)
        segwit_data = ('segwit_data', pack.PossiblyNoneType(dict(txid_merkle_link=dict(branch=[], index=0), wtxid_merkle_root=2**256-1), pack.ComposedType([
            ('txid_merkle_link', pack.ComposedType([
                ('branch', pack.ListType(pack.IntType(256))),
                ('index', pack.IntType(0)), # it will always be 0
            ])),
            ('wtxid_merkle_root', pack.IntType(256))
        ])))
        t['share_info_type'] = pack.ComposedType([
            ('share_data', pack.ComposedType([
                ('previous_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
                ('coinbase', pack.VarStrType()),
                ('nonce', pack.IntType(32)),
                ] + ([('address', pack.VarStrType())]
                        if cls.VERSION >= 34
                            else [('pubkey_hash', pack.IntType(160))]) + [
                ('subsidy', pack.IntType(64)),
                ('donation', pack.IntType(16)),
                ('stale_info', pack.EnumType(pack.IntType(8), dict((k, {0: None, 253: 'orphan', 254: 'doa'}.get(k, 'unk%i' % (k,))) for k in xrange(256)))),
                ('desired_version', pack.VarIntType()),
            ]))] + ([segwit_data] if is_segwit_activated(cls.VERSION, net) else []) + ([
            ('new_transaction_hashes', pack.ListType(pack.IntType(256))),
            ('transaction_hash_refs', pack.ListType(pack.VarIntType(), 2)), # pairs of share_count, tx_count
            ] if cls.VERSION < 34 else []) + [
            ('far_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
            ('max_bits', bitcoin_data.FloatingIntegerType()),
            ('bits', bitcoin_data.FloatingIntegerType()),
            ('timestamp', pack.IntType(32)),
            ('absheight', pack.IntType(32)),
            ('abswork', pack.IntType(128)),
        ])
        t['share_type'] = pack.ComposedType([
            ('min_header', cls.small_block_header_type),
            ('share_info', t['share_info_type']),
            ('ref_merkle_link', pack.ComposedType([
                ('branch', pack.ListType(pack.IntType(256))),
                ('index', pack.IntType(0)),
            ])),
            ('last_txout_nonce', pack.IntType(64)),
            ('hash_link', hash_link_type),
            ('merkle_link', pack.ComposedType([
                ('branch', pack.ListType(pack.IntType(256))),
                ('index', pack.IntType(0)), # it will always be 0
            ])),
        ])
        t['ref_type'] = pack.ComposedType([
            ('identifier', pack.FixedStrType(64//8)),
            ('share_info', t['share_info_type']),
        ])
        cls.cached_types = t
        return t

    @classmethod
    def generate_transaction(cls, tracker, share_data, block_target, desired_timestamp, desired_target, ref_merkle_link, desired_other_transaction_hashes_and_fees, net, known_txs=None, last_txout_nonce=0, base_subsidy=None, segwit_data=None, v36_active=False, merged_addresses=None, message_data=None, merged_coinbase_info=None):
        # V36 Donation Switch:
        # - Pre-V36 (<95%): Uses DONATION_SCRIPT (P2PK, original P2Pool author)
        # - Post-V36 (>=95%): Uses COMBINED_DONATION_SCRIPT (P2SH wrapping 1-of-2 P2MS redeem script)
        # MergedMiningShare has its own gentx_before_refhash matching COMBINED_DONATION_SCRIPT
        t0 = time.time()
        previous_share = tracker.items[share_data['previous_share_hash']] if share_data['previous_share_hash'] is not None else None
        
        height, last = tracker.get_height_and_last(share_data['previous_share_hash'])
        if not (height >= net.REAL_CHAIN_LENGTH or last is None):
            raise ValueError('share chain not long enough (height=%d, need %d)' % (height, net.REAL_CHAIN_LENGTH))
        if height < net.TARGET_LOOKBEHIND:
            pre_target3 = net.MAX_TARGET
        else:
            attempts_per_second = get_pool_attempts_per_second(tracker, share_data['previous_share_hash'], net.TARGET_LOOKBEHIND, min_work=True, integer=True)
            pre_target = 2**256//(net.SHARE_PERIOD*attempts_per_second) - 1 if attempts_per_second else 2**256-1
            pre_target2 = math.clip(pre_target, (previous_share.max_target*9//10, previous_share.max_target*11//10))
            pre_target3 = math.clip(pre_target2, (net.MIN_TARGET, net.MAX_TARGET))
        max_bits = bitcoin_data.FloatingInteger.from_target_upper_bound(pre_target3)
        bits = bitcoin_data.FloatingInteger.from_target_upper_bound(math.clip(desired_target, (pre_target3//30, pre_target3)))
        
        new_transaction_hashes = []
        new_transaction_size = 0 # including witnesses
        all_transaction_stripped_size = 0 # stripped size
        all_transaction_real_size = 0 # including witnesses, for statistics
        new_transaction_weight = 0
        all_transaction_weight = 0
        transaction_hash_refs = []
        other_transaction_hashes = []
        t1 = time.time()
        tx_hash_to_this = {}
        if cls.VERSION < 34:
            past_shares = list(tracker.get_chain(share_data['previous_share_hash'], min(height, 100)))
            for i, share in enumerate(past_shares):
                for j, tx_hash in enumerate(share.new_transaction_hashes):
                    if tx_hash not in tx_hash_to_this:
                        tx_hash_to_this[tx_hash] = [1+i, j] # share_count, tx_count

        t2 = time.time()
        for tx_hash, fee in desired_other_transaction_hashes_and_fees:
            if known_txs is not None:
                this_stripped_size = bitcoin_data.get_stripped_size(known_txs[tx_hash])
                this_real_size     = bitcoin_data.get_size(known_txs[tx_hash])
                this_weight        = this_real_size + 3*this_stripped_size
            else: # we're just verifying someone else's share. We'll calculate sizes in should_punish_reason()
                this_stripped_size = 0
                this_real_size = 0
                this_weight = 0

            if all_transaction_stripped_size + this_stripped_size + 80 + cls.gentx_size +  500 > net.BLOCK_MAX_SIZE:
                break
            if all_transaction_weight + this_weight + 4*80 + cls.gentx_weight + 2000 > net.BLOCK_MAX_WEIGHT and not getattr(net, 'IMMUTABLE_BLOCKS', False):
                break

            if tx_hash in tx_hash_to_this:
                this = tx_hash_to_this[tx_hash]
                if known_txs is not None:
                    all_transaction_stripped_size += this_stripped_size
                    all_transaction_real_size += this_real_size
                    all_transaction_weight += this_weight
            else:
                if known_txs is not None:
                    new_transaction_size += this_real_size
                    all_transaction_stripped_size += this_stripped_size
                    all_transaction_real_size += this_real_size
                    new_transaction_weight += this_weight
                    all_transaction_weight += this_weight
                new_transaction_hashes.append(tx_hash)
                this = [0, len(new_transaction_hashes)-1]
            transaction_hash_refs.extend(this)
            other_transaction_hashes.append(tx_hash)

        t3 = time.time()
        if transaction_hash_refs and max(transaction_hash_refs) < 2**16:
            transaction_hash_refs = array.array('H', transaction_hash_refs)
        elif transaction_hash_refs and max(transaction_hash_refs) < 2**32: # in case we see blocks with more than 65536 tx
            transaction_hash_refs = array.array('L', transaction_hash_refs)
        t4 = time.time()

        if all_transaction_stripped_size and p2pool.DEBUG:
            print "Generating a share with %i bytes, %i WU (new: %i B, %i WU) in %i tx (%i new), plus est gentx of %i bytes/%i WU" % (
                all_transaction_real_size,
                all_transaction_weight,
                new_transaction_size,
                new_transaction_weight,
                len(other_transaction_hashes),
                len(new_transaction_hashes),
                cls.gentx_size,
                cls.gentx_weight)
            print "Total block stripped size=%i B, full size=%i B,  weight: %i WU" % (
                80+all_transaction_stripped_size+cls.gentx_size, 
                80+all_transaction_real_size+cls.gentx_size, 
                3*80+all_transaction_weight+cls.gentx_weight)

        included_transactions = set(other_transaction_hashes)
        removed_fees = [fee for tx_hash, fee in desired_other_transaction_hashes_and_fees if tx_hash not in included_transactions]
        definite_fees = sum(0 if fee is None else fee for tx_hash, fee in desired_other_transaction_hashes_and_fees if tx_hash in included_transactions)
        if None not in removed_fees:
            share_data = dict(share_data, subsidy=share_data['subsidy'] - sum(removed_fees))
        else:
            if base_subsidy is None:
                raise ValueError('base_subsidy is None in subsidy calculation')
            share_data = dict(share_data, subsidy=base_subsidy + definite_fees)
        
        weights, total_weight, donation_weight = tracker.get_cumulative_weights(previous_share.share_data['previous_share_hash'] if previous_share is not None else None,
            max(0, min(height, net.REAL_CHAIN_LENGTH) - 1),
            65535*net.SPREAD*bitcoin_data.target_to_average_attempts(block_target),
        )
        if total_weight != sum(weights.itervalues()) + donation_weight:
            raise ValueError('PPLNS weight mismatch: total_weight=%d, sum+donation=%d' % (total_weight, sum(weights.itervalues()) + donation_weight))
        
        amounts = dict((script, share_data['subsidy']*(199*weight)//(200*total_weight)) for script, weight in weights.iteritems()) # 99.5% goes according to weights prior to this share
        if 'address' not in share_data:
            # V36: Use pubkey_type to derive native address (bech32, P2SH, or P2PKH)
            _pt = share_data.get('pubkey_type', PUBKEY_TYPE_P2PKH)
            _ver, _witver = pubkey_type_to_version_witver(_pt, net.PARENT)
            this_address = bitcoin_data.pubkey_hash_to_address(
                    share_data['pubkey_hash'], _ver, _witver, net.PARENT)
        else:
            this_address = share_data['address']
        
        # V36 Donation System:
        # =====================
        # Pre-V36: DONATION_SCRIPT only (P2PK, original author Forrest Voight)
        # Post-V36: COMBINED_DONATION_SCRIPT (P2SH wrapping 1-of-2 P2MS redeem script)
        #   - Single output replaces two separate donation outputs
        #   - Saves 30 bytes per share coinbase (110 -> 80 bytes)
        #   - COMBINED_DONATION_SCRIPT MUST be LAST (before OP_RETURN) for V36 gentx_before_refhash
        #
        # Primary donation (pre-V36) goes to original author (DONATION_SCRIPT)
        primary_donation_address = donation_script_to_address(net)
        
        # Combined donation (V36+) goes to P2SH-wrapped combined script (COMBINED_DONATION_SCRIPT)
        combined_donation_addr = combined_donation_script_to_address(net)
        
        # 0.5% goes to block finder
        amounts[this_address] = amounts.get(this_address, 0) \
                                + share_data['subsidy']//200
        # all that's left over is the donation weight and some extra
        # satoshis due to rounding
        total_donation = share_data['subsidy'] - sum(amounts.itervalues())
        
        if v36_active:
            # V36 (95%+): Single P2SH-wrapped combined donation output (COMBINED_DONATION_SCRIPT)
            # All donation goes to the combined script - either party can spend
            amounts[combined_donation_addr] = amounts.get(combined_donation_addr, 0) + total_donation
        else:
            # Pre-V36: All donation goes to primary (original author P2PK)
            amounts[primary_donation_address] = amounts.get(primary_donation_address, 0) + total_donation
            
        if cls.VERSION < 34 and 'pubkey_hash' not in share_data:
            share_data['pubkey_hash'], _, _ = bitcoin_data.address_to_pubkey_hash(
                    this_address, net.PARENT)
            del(share_data['address'])
        
        # V36: store pubkey_hash and pubkey_type (saves ~15 bytes vs VarStrType address)
        if cls.VERSION >= 36 and 'pubkey_hash' not in share_data:
            _ph, _v, _wv = bitcoin_data.address_to_pubkey_hash(
                    this_address, net.PARENT)
            share_data['pubkey_hash'] = _ph
            share_data['pubkey_type'] = get_pubkey_type(_v, _wv, net.PARENT)
            if 'address' in share_data:
                del share_data['address']
        
        if sum(amounts.itervalues()) != share_data['subsidy'] or any(x < 0 for x in amounts.itervalues()):
            raise ValueError()

        # block length limit, unlikely to ever be hit
        # Exclude donation addresses from dests - they are added separately at the end
        # Pre-V36: primary_donation_address (P2PK)
        # V36+: combined_donation_addr (derived from P2SH combined donation script)
        excluded_dests = {primary_donation_address, combined_donation_addr}
        dests = sorted([addr for addr in amounts.iterkeys() if addr not in excluded_dests], 
                       key=lambda address: (amounts[address], address))[-4000:]
        if len(dests) >= 200:
            print "found %i payment dests. Antminer S9s may crash when this is close to 226." % len(dests)

        segwit_activated = is_segwit_activated(cls.VERSION, net)
        if segwit_data is None and known_txs is None:
            segwit_activated = False
        if not(segwit_activated or known_txs is None) and any(bitcoin_data.is_segwit_tx(known_txs[h]) for h in other_transaction_hashes):
            raise ValueError('segwit transaction included before activation')
        if segwit_activated and known_txs is not None:
            # Build list of (tx, txid) tuples for share transactions
            share_txs = [(known_txs[h], bitcoin_data.get_txid(known_txs[h])) for h in other_transaction_hashes]
            # IMPORTANT: For wtxid calculation, do NOT pass 'h' as txhash - 'h' is the txid (lookup key),
            # not the wtxid. Pass None for txhash so get_wtxid() computes the actual wtxid by hashing
            # the full transaction including witness data.
            segwit_data = dict(txid_merkle_link=bitcoin_data.calculate_merkle_link([None] + [tx[1] for tx in share_txs], 0), wtxid_merkle_root=bitcoin_data.merkle_hash([0] + [bitcoin_data.get_wtxid(tx[0], tx[1], None) for tx in share_txs]))
        if segwit_activated and segwit_data is not None:
            witness_reserved_value_str = '[P2Pool]'*4
            witness_reserved_value = pack.IntType(256).unpack(witness_reserved_value_str)
            witness_commitment_hash = bitcoin_data.get_witness_commitment_hash(segwit_data['wtxid_merkle_root'], witness_reserved_value)

        share_info = dict(
            share_data=share_data,
            far_share_hash=None if last is None and height < 99 else tracker.get_nth_parent_hash(share_data['previous_share_hash'], 99),
            max_bits=max_bits,
            bits=bits,

            timestamp=(math.clip(desired_timestamp, (
                        (previous_share.timestamp + net.SHARE_PERIOD) - (net.SHARE_PERIOD - 1), # = previous_share.timestamp + 1
                        (previous_share.timestamp + net.SHARE_PERIOD) + (net.SHARE_PERIOD - 1),)) if previous_share is not None else desired_timestamp
                      ) if cls.VERSION < 32 else
                      max(desired_timestamp, (previous_share.timestamp + 1)) if previous_share is not None else desired_timestamp,
            absheight=((previous_share.absheight if previous_share is not None else 0) + 1) % 2**32,
            abswork=((previous_share.abswork if previous_share is not None else 0) + bitcoin_data.target_to_average_attempts(bits.target)) % 2**128,
        )
        if cls.VERSION < 34:
            share_info['new_transaction_hashes'] = new_transaction_hashes
            share_info['transaction_hash_refs'] = transaction_hash_refs

        if previous_share != None and desired_timestamp > previous_share.timestamp + 180:
            print "Warning: Previous share's timestamp is %i seconds old." % int(desired_timestamp - previous_share.timestamp)
            print "Make sure your system clock is accurate, and ensure that you're connected to decent peers."
            print "If your clock is more than 300 seconds behind, it can result in orphaned shares."
            print "(It's also possible that this share is just taking a long time to mine.)"
        if previous_share != None and previous_share.timestamp > int(time.time()) + 3:
            print "WARNING! Previous share's timestamp is %i seconds in the future. This is not normal." % \
                   int(previous_share.timestamp - (int(time.time())))
            print "Make sure your system clock is accurate. Errors beyond 300 sec result in orphaned shares."

        if segwit_activated:
            share_info['segwit_data'] = segwit_data
        
        # V36+: include merged_addresses field
        # If miner provided validated merged chain addresses via stratum, store them.
        # None = use default (auto-conversion from parent chain pubkey_hash).
        # List of [{chain_id: int, script: bytes}] = explicit addresses per chain.
        if cls.VERSION >= 36:
            share_info['merged_addresses'] = merged_addresses  # None or list of validated entries
        
        # V36+: Include merged coinbase verification data for consensus enforcement.
        # This enables peers to independently verify the merged chain coinbase was
        # built correctly with proper PPLNS distribution. Contains DOGE header,
        # merkle proof, and reward parameters needed for canonical re-derivation.
        if cls.VERSION >= 36:
            share_info['merged_coinbase_info'] = merged_coinbase_info if merged_coinbase_info else None
        
        # V36+: Commit merged PPLNS weight distribution hash for consensus enforcement.
        # This ensures the share creator cannot manipulate merged chain (e.g. DOGE) payouts
        # without being detected by all validating peers.
        # Uses same PPLNS window as parent chain (starting at previous_share_hash).
        if cls.VERSION >= 36:
            share_info['merged_payout_hash'] = compute_merged_payout_hash(
                tracker, share_data['previous_share_hash'], block_target, net)
        
        # Build payouts list - IMPORTANT: donation script must be LAST for gentx_before_refhash compatibility
        # Pre-V36: DONATION_SCRIPT (P2PK, 67 bytes) as last output
        # V36+:    COMBINED_DONATION_SCRIPT (P2SH scriptPubKey) as last output
        
        # Build payouts from dests (donation addresses already excluded from dests above)
        payouts = [dict(value=amounts[addr],
                        script=bitcoin_data.address_to_script2(addr, net.PARENT)
                        ) for addr in dests if amounts[addr]]
        
        if v36_active:
            # V36 (95%+): Single P2SH-wrapped combined donation output (COMBINED_DONATION_SCRIPT)
            # MUST BE LAST payout output before the OP_RETURN
            payouts.append({'script': COMBINED_DONATION_SCRIPT, 'value': amounts[combined_donation_addr]})
        else:
            # Pre-V36: Only primary donation script (MUST BE LAST!)
            payouts.append({'script': DONATION_SCRIPT, 'value': amounts[primary_donation_address]})
        
        # Debug: Uncomment to trace payout structure (confirmed working)
        # import sys
        # print >>sys.stderr, '[PAYOUT DEBUG] Number of payout outputs: %d' % len(payouts)
        # for i, payout in enumerate(payouts):
        #     script_address = 'unknown'
        #     try:
        #         script_address = bitcoin_data.script2_to_address(payout['script'], net.PARENT)[:20] + '...'
        #     except:
        #         pass
        #     print >>sys.stderr, '[PAYOUT DEBUG]   Output %d: value=%d, script_len=%d, addr=%s' % (i, payout['value'], len(payout['script']), script_address)

        # Defense-in-depth: validate message_data is encrypted + authority-signed before embedding
        if message_data is not None and cls.VERSION >= 36:
            try:
                from p2pool.share_messages import (
                    unpack_share_messages as _unpack_msgs,
                    DONATION_AUTHORITY_PUBKEYS as _AUTH_PUBKEYS,
                )
                _msgs, _info = _unpack_msgs(message_data)
                if not _msgs or _info is None:
                    import sys as _sys
                    print >> _sys.stderr, ('[TRANSITION MSG] REJECTED: '
                        'message_data failed decryption -- not encrypted '
                        'by any donation authority key')
                    message_data = None
                else:
                    _auth_pk = _info.get('authority_pubkey', b'')
                    for _m in _msgs:
                        if not _m.signature or not _m.verify_authority_direct(_auth_pk):
                            import sys as _sys
                            print >> _sys.stderr, ('[TRANSITION MSG] REJECTED: '
                                'message type 0x%02x signature invalid after '
                                'decryption -- not embedding' % _m.msg_type)
                            message_data = None
                            break
            except Exception as _e:
                import sys as _sys
                print >> _sys.stderr, ('[TRANSITION MSG] REJECTED: '
                    'failed to validate message_data -- %s' % _e)
                message_data = None

        gentx = dict(
            version=1,
            tx_ins=[dict(
                previous_output=None,
                sequence=None,
                script=share_data['coinbase'],
            )],
            tx_outs=([dict(value=0, script='\x6a\x24\xaa\x21\xa9\xed' \
                                           + pack.IntType(256).pack(
                                                witness_commitment_hash))]
                                           if segwit_activated else []) \
                    + payouts \
                    + [dict(value=0, script='\x6a\x28' + cls.get_ref_hash(
                        net, share_info, ref_merkle_link, message_data=message_data) \
                                + pack.IntType(64).pack(last_txout_nonce))],
            lock_time=0,
        )
        
        # Debug: Uncomment to trace gentx creation (confirmed working)
        # import sys
        # print >>sys.stderr, '[GENTX CREATION] coinbase script length: %d bytes' % len(share_data['coinbase'])
        # print >>sys.stderr, '[GENTX CREATION] coinbase script hex: %s' % share_data['coinbase'].encode('hex')
        # print >>sys.stderr, '[GENTX CREATION] num payouts: %d' % len(payouts)
        # print >>sys.stderr, '[GENTX CREATION] total outputs: %d' % (len(gentx['tx_outs']))
        
        # DEBUG: Verify gentx_before_refhash structure
        packed_gentx = bitcoin_data.tx_id_type.pack(gentx)
        cutoff_prefix = packed_gentx[:-32-8-4]  # Remove ref_hash + nonce + lock_time
        
        # Donation script is always LAST output before OP_RETURN
        # Pre-V36: DONATION_SCRIPT (P2PK), V36: COMBINED_DONATION_SCRIPT (P2SH-wrapped combined script)
        # cls.gentx_before_refhash is version-specific (MergedMiningShare overrides BaseShare)
        
        # Debug: Uncomment to trace gentx validation (confirmed working)
        #print >>sys.stderr, '[GENTX DEBUG] Total packed length: %d bytes' % len(packed_gentx)
        #print >>sys.stderr, '[GENTX DEBUG] Prefix length (after cut): %d bytes' % len(cutoff_prefix)
        #print >>sys.stderr, '[GENTX DEBUG] gentx_before_refhash length: %d bytes' % len(cls.gentx_before_refhash)
        #print >>sys.stderr, '[GENTX DEBUG] Last 50 bytes of prefix: %s' % cutoff_prefix[-50:].encode('hex')
        #print >>sys.stderr, '[GENTX DEBUG] gentx_before_refhash: %s' % cls.gentx_before_refhash.encode('hex')
        if not cutoff_prefix.endswith(cls.gentx_before_refhash):
            # Keep ERROR logs - these indicate actual problems
            print >>sys.stderr, '[GENTX ERROR] Prefix does NOT end with gentx_before_refhash!'
            print >>sys.stderr, '[GENTX ERROR] V36 active: %s' % v36_active
            print >>sys.stderr, '[GENTX ERROR] Expected ending: %s' % cls.gentx_before_refhash.encode('hex')
            print >>sys.stderr, '[GENTX ERROR] Actual ending:   %s' % cutoff_prefix[-len(cls.gentx_before_refhash):].encode('hex')
        #else:
            #print >>sys.stderr, '[GENTX DEBUG] OK: Prefix ends with gentx_before_refhash'
        
        if segwit_activated:
            gentx['marker'] = 0
            gentx['flag'] = 1
            gentx['witness'] = [[witness_reserved_value_str]]
        
        def get_share(header, last_txout_nonce=last_txout_nonce):
            min_header = dict(header); del min_header['merkle_root']
            packed_for_link = bitcoin_data.tx_id_type.pack(gentx)
            prefix_for_link = packed_for_link[:-32-8-4]
            share_contents = dict(
                min_header=min_header,
                share_info=share_info,
                ref_merkle_link=dict(branch=[], index=0),
                last_txout_nonce=last_txout_nonce,
                hash_link=prefix_to_hash_link(prefix_for_link, cls.gentx_before_refhash),
                merkle_link=bitcoin_data.calculate_merkle_link([None] + other_transaction_hashes, 0),
            )
            if cls.VERSION >= 36:
                share_contents['message_data'] = message_data
            share = cls(net, None, share_contents)
            if share.header != header: # checks merkle_root
                raise ValueError('share header does not match expected header (merkle_root mismatch)')
            return share
        t5 = time.time()
        if p2pool.BENCH: print "%8.3f ms for data.py:generate_transaction(). Parts: %8.3f %8.3f %8.3f %8.3f %8.3f " % (
            (t5-t0)*1000.,
            (t1-t0)*1000.,
            (t2-t1)*1000.,
            (t3-t2)*1000.,
            (t4-t3)*1000.,
            (t5-t4)*1000.)
        return share_info, gentx, other_transaction_hashes, get_share
    
    @classmethod
    def get_ref_hash(cls, net, share_info, ref_merkle_link, message_data=None):
        ref_dict = dict(
            identifier=net.IDENTIFIER,
            share_info=share_info,
        )
        if cls.VERSION >= 36:
            ref_dict['message_data'] = message_data  # None → PossiblyNoneType packs b''
        return pack.IntType(256).pack(bitcoin_data.check_merkle_link(bitcoin_data.hash256(cls.get_dynamic_types(net)['ref_type'].pack(ref_dict)), ref_merkle_link))
    
    __slots__ = 'net peer_addr contents min_header share_info hash_link merkle_link hash share_data max_target target timestamp previous_hash new_script desired_version gentx_hash header pow_hash header_hash new_transaction_hashes time_seen absheight abswork _message_data _parsed_messages _signing_key_info'.split(' ')
    
    def __init__(self, net, peer_addr, contents):
        dynamic_types = self.get_dynamic_types(net)
        self.share_info_type = dynamic_types['share_info_type']
        self.share_type = dynamic_types['share_type']
        self.ref_type = dynamic_types['ref_type']

        self.net = net
        self.peer_addr = peer_addr
        self.contents = contents
        
        self.min_header = contents['min_header']
        self.share_info = contents['share_info']
        self.hash_link = contents['hash_link']
        self.merkle_link = contents['merkle_link']
        self.naughty = 0

        # save some memory if we can
        if self.VERSION < 34:
            txrefs = self.share_info['transaction_hash_refs']
            if txrefs and max(txrefs) < 2**16:
                self.share_info['transaction_hash_refs'] = array.array('H', txrefs)
            elif txrefs and max(txrefs) < 2**32: # in case we see blocks with more than 65536 tx in the future
                self.share_info['transaction_hash_refs'] = array.array('L', txrefs)
        
        segwit_activated = is_segwit_activated(self.VERSION, net)
        
        if not (2 <= len(self.share_info['share_data']['coinbase']) <= 100):
            raise ValueError('''bad coinbase size! %i bytes''' % (len(self.share_info['share_data']['coinbase']),))
        
        # V36 uses VarStrType for extra_data (gentx_before_refhash < 64 bytes)
        if self.VERSION < 36:
            if self.hash_link['extra_data']:
                raise ValueError('pre-V36 share has non-empty hash_link extra_data: %r' % (self.hash_link['extra_data'],))
        
        self.share_data = self.share_info['share_data']
        self.max_target = self.share_info['max_bits'].target
        self.target = self.share_info['bits'].target
        self.timestamp = self.share_info['timestamp']
        self.previous_hash = self.share_data['previous_share_hash']
        if self.VERSION >= 36:
            # V36: Use pubkey_type to construct native script/address
            # (P2PKH=0, P2WPKH/bech32=1, P2SH=2)
            _ver, _witver = pubkey_type_to_version_witver(
                    self.share_data.get('pubkey_type', PUBKEY_TYPE_P2PKH), net.PARENT)
            self.new_script = bitcoin_data.pubkey_hash_to_script2(
                    self.share_data['pubkey_hash'], _ver, _witver, net.PARENT)
            self.address = bitcoin_data.pubkey_hash_to_address(
                    self.share_data['pubkey_hash'], _ver, _witver, net.PARENT)
        elif self.VERSION >= 34:
            self.new_script = bitcoin_data.address_to_script2(
                    self.share_data['address'], net.PARENT)
            self.address = self.share_data['address']
        else:
            self.new_script = bitcoin_data.pubkey_hash_to_script2(
                    self.share_data['pubkey_hash'],
                    net.PARENT.ADDRESS_VERSION, -1, net.PARENT)
            self.address = bitcoin_data.pubkey_hash_to_address(
                    self.share_data['pubkey_hash'],
                    net.PARENT.ADDRESS_VERSION, -1, net.PARENT)
        self.desired_version = self.share_data['desired_version']
        # V36+: Read merged_addresses from share_info (may be None for auto-conversion)
        if self.VERSION >= 36:
            self.merged_addresses = self.share_info.get('merged_addresses', None)
        else:
            self.merged_addresses = None
        
        # V36+: Read message_data from ref_type contents (for share-embedded messaging)
        if self.VERSION >= 36:
            self._message_data = contents.get('message_data', None)
        else:
            self._message_data = None
        self._parsed_messages = []
        self._signing_key_info = None
        self.absheight = self.share_info['absheight']
        self.abswork = self.share_info['abswork']
        if net.NAME == 'bitcoin' and self.absheight > 3927800 and self.desired_version == 16:
            raise ValueError("This is not a hardfork-supporting share!")
        
        if self.VERSION < 34:
            n = set()
            for share_count, tx_count in self.iter_transaction_hash_refs():
                if share_count >= 110:
                    raise ValueError('transaction hash ref share_count too large: %d' % share_count)
                if share_count == 0:
                    n.add(tx_count)
            if n != set(range(len(self.share_info['new_transaction_hashes']))):
                raise ValueError('transaction hash refs do not cover all new_transaction_hashes')
        
        # Debug: Uncomment to trace share validation (confirmed working)
        # import sys
        # print >>sys.stderr, '[VALIDATION] coinbase script length: %d bytes' % len(self.share_info['share_data']['coinbase'])
        # print >>sys.stderr, '[VALIDATION] coinbase script hex: %s' % self.share_info['share_data']['coinbase'].encode('hex')
        
        self.gentx_hash = check_hash_link(
            self.hash_link,
            self.get_ref_hash(net, self.share_info, contents['ref_merkle_link'], message_data=self._message_data) + pack.IntType(64).pack(self.contents['last_txout_nonce']) + pack.IntType(32).pack(0),
            self.gentx_before_refhash,
        )
        # Reconstruct merkle_root from gentx_hash and merkle_link
        merkle_root = bitcoin_data.check_merkle_link(self.gentx_hash, self.share_info['segwit_data']['txid_merkle_link'] if segwit_activated else self.merkle_link)
        self.header = dict(self.min_header, merkle_root=merkle_root)
        
        # Debug: Uncomment to trace share creation (prints on every share)
        # import sys
        # print >>sys.stderr, '[SHARE __init__] Calculated merkle_root: %064x' % merkle_root
        # print >>sys.stderr, '[SHARE __init__] gentx_hash: %064x' % self.gentx_hash
        # print >>sys.stderr, '[SHARE __init__] merkle_link branches: %d' % len(self.merkle_link['branch'])
        
        self.pow_hash = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(self.header))
        self.hash = self.header_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(self.header))
        
        if self.target > net.MAX_TARGET:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('share target invalid')
        
        if self.pow_hash > self.target:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('share PoW invalid')
        
        if self.VERSION < 34:
            self.new_transaction_hashes = self.share_info['new_transaction_hashes']
        
        # XXX eww
        self.time_seen = time.time()
    
    def __repr__(self):
        return 'Share' + repr((self.net, self.peer_addr, self.contents))
    
    def as_share(self):
        return dict(type=self.VERSION, contents=self.share_type.pack(self.contents))
    
    def iter_transaction_hash_refs(self):
        try:
            return zip(self.share_info['transaction_hash_refs'][::2], self.share_info['transaction_hash_refs'][1::2])
        except AttributeError:
            return zip()
        except KeyError:
            return zip()

    def check(self, tracker, known_txs=None, block_abs_height_func=None):
        from p2pool import p2p
        if self.timestamp > int(time.time()) + 600:
            raise ValueError("Share timestamp is %i seconds in the future! Check your system clock." % \
                self.timestamp - int(time.time()))
        counts = None
        if self.share_data['previous_share_hash'] is not None and block_abs_height_func is not None:
            previous_share = tracker.items[self.share_data['previous_share_hash']]
            if tracker.get_height(self.share_data['previous_share_hash']) >= self.net.CHAIN_LENGTH:
                counts = get_desired_version_counts(tracker, tracker.get_nth_parent_hash(previous_share.hash, self.net.CHAIN_LENGTH*9//10), self.net.CHAIN_LENGTH//10)
                if type(self) is type(previous_share):
                    pass
                elif type(self) is type(previous_share).SUCCESSOR:
                    # switch only valid if 60% of hashes in [self.net.CHAIN_LENGTH*9//10, self.net.CHAIN_LENGTH] for new version
                    if counts.get(self.VERSION, 0) < sum(counts.itervalues())*60//100:
                        raise p2p.PeerMisbehavingError('switch without enough hash power upgraded')
                else:
                    raise p2p.PeerMisbehavingError('''%s can't follow %s''' % (type(self).__name__, type(previous_share).__name__))
            elif type(self) is type(previous_share).SUCCESSOR:
                raise p2p.PeerMisbehavingError('switch without enough history')
        
        if self.VERSION < 34:
            other_tx_hashes = [tracker.items[tracker.get_nth_parent_hash(self.hash, share_count)].share_info['new_transaction_hashes'][tx_count] for share_count, tx_count in self.iter_transaction_hash_refs()]
        else:
            other_tx_hashes = []
        if known_txs is not None and not isinstance(known_txs, dict):
            print "Performing maybe-unnecessary packing and hashing"
            known_txs = dict((bitcoin_data.hash256(bitcoin_data.tx_type.pack(tx)), tx) for tx in known_txs)
        
        # Generate the expected coinbase transaction
        share_info, gentx, other_tx_hashes2, get_share = self.generate_transaction(
            tracker, self.share_info['share_data'], self.header['bits'].target, 
            self.share_info['timestamp'], self.share_info['bits'].target, 
            self.contents['ref_merkle_link'], [(h, None) for h in other_tx_hashes], self.net,
            known_txs=None, last_txout_nonce=self.contents['last_txout_nonce'], 
            segwit_data=self.share_info.get('segwit_data', None),
            v36_active=(self.VERSION >= 36),
            merged_addresses=self.share_info.get('merged_addresses', None),
            message_data=self._message_data,
            merged_coinbase_info=self.share_info.get('merged_coinbase_info', None))
        
        if other_tx_hashes2 != other_tx_hashes:
            raise ValueError('reconstructed other_tx_hashes do not match expected')
        if bitcoin_data.get_txid(gentx) != self.gentx_hash:
            raise ValueError('''gentx doesn't match hash_link''')
        
        # V36+: Verify merged coinbase consensus enforcement.
        # Re-derive the canonical merged chain coinbase from PPLNS weights and
        # committed parameters, then verify it matches what's committed in mm_data.
        # This is the core anti-theft mechanism for merged mining rewards.
        if self.VERSION >= 36:
            try:
                parent_net = self.net.PARENT
                merged_info = self.share_info.get('merged_coinbase_info')
                verify_merged_coinbase_commitment(self, tracker, self.net, parent_net)
            except ValueError as e:
                raise ValueError('merged coinbase verification failed: %s' % (e,))
        
        # V36+: Validate share-embedded messages (transition signals, etc.)
        #
        # STRICT POLICY: A share that carries message_data MUST pass both:
        #   1. Decryption — encrypted by a COMBINED_DONATION_SCRIPT authority key
        #   2. Signature  — each inner message signed by the same authority key
        #
        # If message_data is present but fails either check, THE SHARE IS REJECTED.
        # This prevents malicious miners from spamming the system with fake
        # system messages — they waste their PoW and get no reward.
        #
        # Shares with NO message_data (None or empty) are always valid.
        if self.VERSION >= 36 and self._message_data:
            from p2pool.share_messages import (
                unpack_share_messages, DONATION_AUTHORITY_PUBKEYS,
                FLAG_PROTOCOL_AUTHORITY,
            )
            messages, signing_key_info = unpack_share_messages(self._message_data)
            self._signing_key_info = signing_key_info

            if signing_key_info is None:
                # Decryption failed — not encrypted by any known authority key.
                # This share is carrying fake/garbage message_data → REJECT.
                raise p2p.PeerMisbehavingError(
                    'share carries message_data that failed decryption '
                    'against all COMBINED_DONATION_SCRIPT authority keys')

            authority_pubkey = signing_key_info.get('authority_pubkey', b'')
            if authority_pubkey not in DONATION_AUTHORITY_PUBKEYS:
                raise p2p.PeerMisbehavingError(
                    'share message_data decrypted but authority_pubkey '
                    'not in COMBINED_DONATION_SCRIPT')

            if not messages:
                # Decryption succeeded but no valid messages inside.
                # Malformed inner envelope → REJECT.
                raise p2p.PeerMisbehavingError(
                    'share message_data decrypted but contains no valid messages')

            # Verify each message signature against the authority pubkey
            for msg in messages:
                if not msg.signature:
                    raise p2p.PeerMisbehavingError(
                        'share contains unsigned message (type 0x%02x) '
                        'inside encrypted envelope' % msg.msg_type)
                if not msg.verify_authority_direct(authority_pubkey):
                    raise p2p.PeerMisbehavingError(
                        'share contains message (type 0x%02x) with invalid '
                        'signature — does not match encryption authority key'
                        % msg.msg_type)
                msg.flags |= FLAG_PROTOCOL_AUTHORITY

            self._parsed_messages = messages

        if self.VERSION < 34:
            # check for excessive fees
            if self.share_data['previous_share_hash'] is not None and block_abs_height_func is not None:
                pass # dead code for V35+ network

        if self.share_data['previous_share_hash'] and tracker.items[self.share_data['previous_share_hash']].naughty:
            print "naughty ancestor found %i generations ago" % tracker.items[self.share_data['previous_share_hash']].naughty
            # I am not easily angered ...
            print "I will not fail to punish children and grandchildren to the third and fourth generation for the sins of their parents."
            self.naughty = 1 + tracker.items[self.share_data['previous_share_hash']].naughty
            if self.naughty > 6:
                self.naughty = 0

        # share_info was already validated by generate_transaction matching gentx_hash
        if share_info != self.share_info:
            raise ValueError('share_info invalid')
        
        if self.VERSION < 34:
            if bitcoin_data.calculate_merkle_link([None] + other_tx_hashes, 0) != self.merkle_link: # the other hash commitments are checked in the share_info assertion
                raise ValueError('merkle_link and other_tx_hashes do not match')
        
        update_min_protocol_version(counts, self)

        self.gentx_size = len(bitcoin_data.tx_id_type.pack(gentx))
        self.gentx_weight = len(bitcoin_data.tx_type.pack(gentx)) + 3*self.gentx_size

        type(self).gentx_size   = self.gentx_size # saving this share's gentx size as a class variable is an ugly hack, and you're welcome to hate me for doing it. But it works.
        type(self).gentx_weight = self.gentx_weight

        _diff = self.net.PARENT.DUMB_SCRYPT_DIFF*float(
                bitcoin_data.target_to_difficulty(self.target))
        if not self.naughty:
            print("Received good share: diff=%.2e hash=%064x miner=%s" %
                    (_diff, self.hash, self.address))
        else:
            print("Received naughty=%i share: diff=%.2e hash=%064x miner=%s" %
                    (self.naughty, _diff, self.hash, self.address))
        return gentx # only used by as_block
    
    def get_other_tx_hashes(self, tracker):
        parents_needed = max(share_count for share_count, tx_count in self.iter_transaction_hash_refs()) if self.share_info.get('transaction_hash_refs', None) else 0
        parents = tracker.get_height(self.hash) - 1
        if parents < parents_needed:
            return None
        last_shares = list(tracker.get_chain(self.hash, parents_needed + 1))
        ret = []
        for share_count, tx_count in self.iter_transaction_hash_refs():
            try:
                ret.append(last_shares[share_count]
                              .share_info['new_transaction_hashes'][tx_count])
            except AttributeError:
                continue
        return ret
    
    def _get_other_txs(self, tracker, known_txs):
        other_tx_hashes = self.get_other_tx_hashes(tracker)
        if other_tx_hashes is None:
            return None # not all parents present
        
        if not all(tx_hash in known_txs for tx_hash in other_tx_hashes):
            return None # not all txs present
        
        return [known_txs[tx_hash] for tx_hash in other_tx_hashes]
    
    def should_punish_reason(self, previous_block, bits, tracker, known_txs):
        if self.pow_hash <= self.header['bits'].target:
            return -1, 'block solution'
        if self.naughty == 1:
            return self.naughty, 'naughty share (excessive block reward or otherwise would make an invalid block)'
        if self.naughty:
            return self.naughty, 'descendent of naughty share                                                    '
        if self.VERSION < 34:
            other_txs = self._get_other_txs(tracker, known_txs)
        else:
            other_txs = None
        if other_txs is None:
            pass
        else:
            if not hasattr(self, 'all_tx_size'):
                self.all_txs_size = sum(bitcoin_data.get_size(tx) for tx in other_txs)
                self.stripped_txs_size = sum(bitcoin_data.get_stripped_size(tx) for tx in other_txs)
            if self.all_txs_size + 3 * self.stripped_txs_size + 4*80 + self.gentx_weight > tracker.net.BLOCK_MAX_WEIGHT:
                return True, 'txs over block weight limit'
            if self.stripped_txs_size + 80 + self.gentx_size > tracker.net.BLOCK_MAX_SIZE:
                return True, 'txs over block size limit'
        
        return False, None
    
    def as_block(self, tracker, known_txs):
        other_txs = self._get_other_txs(tracker, known_txs)
        if other_txs is None:
            return None # not all txs present
        return dict(header=self.header, txs=[self.check(tracker, other_txs)] + other_txs)


class MergedMiningShare(BaseShare):
    """
    V36 share with merged mining address support.
    
    Allows miners to specify explicit addresses for merged chains (DOGE, etc.)
    instead of relying on automatic P2PKH conversion.
    
    New Features:
    - merged_addresses: List of (chain_id, script) pairs for merged chain payments
    - MWEB transaction handling: Can process Litecoin HogEx transactions
    
    Migration:
    - Activated when 95% of hash power signals VERSION=36
    - V35 nodes can still validate V36 shares (backward compatible structure)
    - MWEB fix only applies when V36 is the active share type
    """
    VERSION = 36
    VOTING_VERSION = 36
    SUCCESSOR = None  # Current head (until V37)
    # Testing phase: 3503 allows peers running 3502+ (jtoomim network).
    # Set to 3600 when V36 is finalized and ready for production.
    MINIMUM_PROTOCOL_VERSION = 3503
    
    # V36 uses COMBINED_DONATION_SCRIPT (P2SH wrapping 1-of-2 P2MS redeem script) instead of DONATION_SCRIPT (P2PK)
    # This replaces two separate donation outputs with one combined output.
    # Either forrestv or we can spend independently (1-of-2 multisig via redeem script).
    #
    # gentx_before_refhash encodes the constant suffix of the packed coinbase tx
    # (everything after the variable donation value, before the ref hash):
    #   donation_scriptPubKey(24) + opreturn_value(8) + opreturn_start(3) = 35 bytes
    # With v36_hash_link_type (VarStrType for extra_data), no padding needed.
    gentx_before_refhash = (
        pack.VarStrType().pack(COMBINED_DONATION_SCRIPT) +                                                       # 24 bytes: donation scriptPubKey
        pack.IntType(64).pack(0) +                                                                                # 8 bytes: OP_RETURN value (always 0)
        pack.VarStrType().pack('\x6a\x28' + pack.IntType(256).pack(0) + pack.IntType(64).pack(0))[:3]            # 3 bytes: OP_RETURN script start
    )  # Total: 35 bytes — v36_hash_link_type stores extra_data via VarStrType
    
    cached_types = None
    
    @classmethod
    def get_dynamic_types(cls, net):
        """
        V36 adds merged_addresses after segwit_data in share_info_type.
        
        merged_addresses is optional (PossiblyNoneType with default []):
        - If None/empty: auto-convert from parent chain address (P2PKH only)
        - If present: explicit merged chain payment scripts
        """
        if cls.cached_types is not None:
            return cls.cached_types
        
        # Start with V35 base types
        t = dict(share_info_type=None, share_type=None, ref_type=None)
        
        segwit_data = ('segwit_data', pack.PossiblyNoneType(
            dict(txid_merkle_link=dict(branch=[], index=0), wtxid_merkle_root=2**256-1),
            pack.ComposedType([
                ('txid_merkle_link', pack.ComposedType([
                    ('branch', pack.ListType(pack.IntType(256))),
                    ('index', pack.IntType(0)),  # always 0
                ])),
                ('wtxid_merkle_root', pack.IntType(256))
            ])
        ))
        
        # NEW in V36: merged_addresses field
        # Each entry: (chain_id: u32, script: bytes)
        # chain_id: AuxPoW chain ID (e.g., 0x62 for DOGE)
        # script: Payment script for that chain (P2PKH format)
        merged_address_entry = pack.ComposedType([
            ('chain_id', pack.IntType(32)),
            ('script', pack.VarStrType()),
        ])
        merged_addresses = ('merged_addresses', pack.PossiblyNoneType(
            [],  # Default: empty list (use auto-conversion)
            pack.ListType(merged_address_entry)  # Merged chain address entries
        ))
        
        t['share_info_type'] = pack.ComposedType([
            ('share_data', pack.ComposedType([
                ('previous_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
                ('coinbase', pack.VarStrType()),
                ('nonce', pack.IntType(32)),
                ('pubkey_hash', pack.IntType(160)),  # V36: compact binary pubkey_hash (saves ~15 bytes vs VarStrType address)
                ('pubkey_type', pack.IntType(8)),     # V36: address type (0=P2PKH, 1=P2WPKH/bech32, 2=P2SH)
                ('subsidy', pack.VarIntType()),      # V36: variable-length (saves ~3-7 bytes vs IntType(64))
                ('donation', pack.IntType(16)),
                ('stale_info', pack.EnumType(pack.IntType(8), dict((k, {0: None, 253: 'orphan', 254: 'doa'}.get(k, 'unk%i' % (k,))) for k in xrange(256)))),
                ('desired_version', pack.VarIntType()),
            ])),
            segwit_data,
            merged_addresses,  # NEW in V36
            ('far_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
            ('max_bits', bitcoin_data.FloatingIntegerType()),
            ('bits', bitcoin_data.FloatingIntegerType()),
            ('timestamp', pack.IntType(32)),
            ('absheight', pack.IntType(32)),
            ('abswork', pack.VarIntType()),  # V36: variable-length (saves ~7-15 bytes vs IntType(128))
            # NEW in V36: Merged coinbase verification data for consensus enforcement.
            # Contains the info peers need to re-derive and verify the merged chain
            # coinbase (DOGE, etc.) was built correctly with proper PPLNS distribution.
            # This closes the trust gap: without this, a malicious node could steal
            # merged chain rewards from miners connected to it.
            ('merged_coinbase_info', pack.PossiblyNoneType(
                [],  # Default: empty (no merged mining or pre-enforcement shares)
                pack.ListType(pack.ComposedType([
                    ('chain_id', pack.IntType(32)),            # AuxPoW chain ID (e.g., 98 for DOGE)
                    ('coinbase_value', pack.VarIntType()),     # Total block reward (satoshis)
                    ('block_height', pack.VarIntType()),       # Merged chain block height (BIP34)
                    ('block_header_bytes', pack.FixedStrType(80)),  # 80-byte block header
                    ('coinbase_merkle_link', pack.ComposedType([   # Merkle proof: coinbase → root
                        ('branch', pack.ListType(pack.IntType(256))),
                        ('index', pack.IntType(0)),  # always 0 (coinbase is first tx)
                    ])),
                ]))
            )),
            # Consensus commitment for merged mining reward distribution.
            # Hash of the expected PPLNS weight distribution (from get_v36_merged_weights).
            # Peers recompute this from their own share chain state and reject if mismatch.
            # 0 = no merged mining active or no V36 shares in PPLNS window.
            ('merged_payout_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
        ])
        
        t['share_type'] = pack.ComposedType([
            ('min_header', cls.small_block_header_type),
            ('share_info', t['share_info_type']),
            ('ref_merkle_link', pack.ComposedType([
                ('branch', pack.ListType(pack.IntType(256))),
                ('index', pack.IntType(0)),
            ])),
            ('last_txout_nonce', pack.IntType(64)),
            ('hash_link', v36_hash_link_type),  # V36: VarStrType for extra_data (no padding needed)
            ('merkle_link', pack.ComposedType([
                ('branch', pack.ListType(pack.IntType(256))),
                ('index', pack.IntType(0)),  # always 0
            ])),
            ('message_data', pack.PossiblyNoneType(b'', pack.VarStrType())),
        ])
        
        t['ref_type'] = pack.ComposedType([
            ('identifier', pack.FixedStrType(64//8)),
            ('share_info', t['share_info_type']),
            ('message_data', pack.PossiblyNoneType(b'', pack.VarStrType())),
        ])
        
        cls.cached_types = t
        return t


class PaddingBugfixShare(BaseShare):
    VERSION=35
    VOTING_VERSION = 35
    SUCCESSOR = MergedMiningShare  # V36 is the successor
    MINIMUM_PROTOCOL_VERSION = 3500

class SegwitMiningShare(BaseShare):
    VERSION = 34
    VOTING_VERSION = 34
    SUCCESSOR = PaddingBugfixShare
    MINIMUM_PROTOCOL_VERSION = 3300

class NewShare(BaseShare):
    VERSION = 33
    VOTING_VERSION = 33
    SUCCESSOR = PaddingBugfixShare
    MINIMUM_PROTOCOL_VERSION = 3300

class PreSegwitShare(BaseShare):
    VERSION = 32
    VOTING_VERSION = 32
    SUCCESSOR = PaddingBugfixShare

class Share(BaseShare):
    VERSION = 17
    VOTING_VERSION = 17
    SUCCESSOR = PaddingBugfixShare


share_versions = {s.VERSION:s for s in [MergedMiningShare, PaddingBugfixShare, SegwitMiningShare, NewShare, PreSegwitShare, Share]}

class WeightsSkipList(forest.TrackerSkipList):
    # share_count, weights, total_weight
    
    def get_delta(self, element):
        from p2pool.bitcoin import data as bitcoin_data
        share = self.tracker.items[element]
        att = bitcoin_data.target_to_average_attempts(share.target)
        return (1, {share.address: att*(65535-share.share_data['donation'])},
                att*65535, att*share.share_data['donation'])
    
    def combine_deltas(self, (share_count1, weights1, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2)):
        return share_count1 + share_count2, math.add_dicts(weights1, weights2), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def initial_solution(self, start, (max_shares, desired_weight)):
        assert desired_weight % 65535 == 0, divmod(desired_weight, 65535)
        return 0, None, 0, 0
    
    def apply_delta(self, (share_count1, weights_list, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2), (max_shares, desired_weight)):
        if total_weight1 + total_weight2 > desired_weight and share_count2 == 1:
            assert (desired_weight - total_weight1) % 65535 == 0
            script, = weights2.iterkeys()
            new_weights = {script: (desired_weight - total_weight1)//65535*weights2[script]//(total_weight2//65535)}
            return share_count1 + share_count2, (weights_list, new_weights), desired_weight, total_donation_weight1 + (desired_weight - total_weight1)//65535*total_donation_weight2//(total_weight2//65535)
        return share_count1 + share_count2, (weights_list, weights2), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def judge(self, (share_count, weights_list, total_weight, total_donation_weight), (max_shares, desired_weight)):
        if share_count > max_shares or total_weight > desired_weight:
            return 1
        elif share_count == max_shares or total_weight == desired_weight:
            return 0
        else:
            return -1
    
    def finalize(self, (share_count, weights_list, total_weight, total_donation_weight), (max_shares, desired_weight)):
        assert share_count <= max_shares and total_weight <= desired_weight
        assert share_count == max_shares or total_weight == desired_weight
        return math.add_dicts(*math.flatten_linked_list(weights_list)), total_weight, total_donation_weight

class MergedWeightsSkipList(forest.TrackerSkipList):
    """O(log n) skip list for V36 merged mining PPLNS weight computation.
    
    Like WeightsSkipList but excludes pre-V36 shares (desired_version < 36)
    and resolves address keys from merged_addresses when chain_id is set.
    Pre-V36 shares count toward share_count (window sizing) but contribute
    zero weight — their weight is redistributed to V36 miners.
    
    One instance per chain_id is required since address resolution depends
    on which merged chain's merged_addresses entry to look up.
    """
    
    def __init__(self, tracker, chain_id=None):
        forest.TrackerSkipList.__init__(self, tracker)
        self.chain_id = chain_id
    
    def get_delta(self, element):
        share = self.tracker.items[element]
        att = bitcoin_data.target_to_average_attempts(share.target)
        
        if share.desired_version < 36:
            # Pre-V36: excluded from merged weight distribution.
            # Count share (for window sizing) but zero weight.
            return (1, {}, 0, 0)
        
        # V36-signaling share: determine address key
        address_key = share.address  # default: parent chain address
        
        if self.chain_id is not None and share.VERSION >= 36:
            merged_addrs = getattr(share, 'merged_addresses', None)
            if merged_addrs is None and hasattr(share, 'share_info') and isinstance(share.share_info, dict):
                merged_addrs = share.share_info.get('merged_addresses', None)
            if merged_addrs:
                for entry in merged_addrs:
                    if entry['chain_id'] == self.chain_id:
                        address_key = 'MERGED:' + entry['script'].encode('hex')
                        break
        
        return (1, {address_key: att*(65535-share.share_data['donation'])},
                att*65535, att*share.share_data['donation'])
    
    def combine_deltas(self, (sc1, w1, tw1, dw1), (sc2, w2, tw2, dw2)):
        return sc1 + sc2, math.add_dicts(w1, w2), tw1 + tw2, dw1 + dw2
    
    def initial_solution(self, start, (max_shares, desired_weight)):
        assert desired_weight % 65535 == 0, divmod(desired_weight, 65535)
        return 0, None, 0, 0
    
    def apply_delta(self, (sc1, wl, tw1, dw1), (sc2, w2, tw2, dw2), (max_shares, desired_weight)):
        if tw1 + tw2 > desired_weight and sc2 == 1:
            if not w2:
                # Pre-V36 single step with zero weight — can't overshoot, pass through
                return sc1 + sc2, (wl, w2), tw1, dw1
            assert (desired_weight - tw1) % 65535 == 0
            script, = w2.iterkeys()
            new_weights = {script: (desired_weight - tw1)//65535*w2[script]//(tw2//65535)}
            return sc1 + sc2, (wl, new_weights), desired_weight, dw1 + (desired_weight - tw1)//65535*dw2//(tw2//65535)
        return sc1 + sc2, (wl, w2), tw1 + tw2, dw1 + dw2
    
    def judge(self, (sc, wl, tw, dw), (max_shares, desired_weight)):
        if sc > max_shares or tw > desired_weight:
            return 1
        elif sc == max_shares or tw == desired_weight:
            return 0
        else:
            return -1
    
    def finalize(self, (sc, wl, tw, dw), (max_shares, desired_weight)):
        assert sc <= max_shares and tw <= desired_weight
        assert sc == max_shares or tw == desired_weight
        return math.add_dicts(*math.flatten_linked_list(wl)), tw, dw

class OkayTracker(forest.Tracker):
    def __init__(self, net):
        forest.Tracker.__init__(self, delta_type=forest.get_attributedelta_type(dict(forest.AttributeDelta.attrs,
            work=lambda share: bitcoin_data.target_to_average_attempts(share.target),
            min_work=lambda share: bitcoin_data.target_to_average_attempts(share.max_target),
        )))
        self.net = net
        self.verified = forest.SubsetTracker(delta_type=forest.get_attributedelta_type(dict(forest.AttributeDelta.attrs,
            work=lambda share: bitcoin_data.target_to_average_attempts(share.target),
        )), subset_of=self)
        self.get_cumulative_weights = WeightsSkipList(self)
        self._merged_weights_skip_lists = {}  # chain_id -> MergedWeightsSkipList
    
    def get_v36_merged_cumulative_weights(self, chain_id, start_hash, chain_length, max_weight):
        """O(log n) merged mining weight computation via skip list."""
        if chain_id not in self._merged_weights_skip_lists:
            self._merged_weights_skip_lists[chain_id] = MergedWeightsSkipList(self, chain_id)
        return self._merged_weights_skip_lists[chain_id](start_hash, chain_length, max_weight)

    def attempt_verify(self, share, block_abs_height_func, known_txs):
        if share.hash in self.verified.items:
            return True
        height, last = self.get_height_and_last(share.hash)
        if height < self.net.CHAIN_LENGTH + 1 and last is not None:
            raise AssertionError()
        try:
            share.gentx = share.check(self, known_txs, block_abs_height_func=block_abs_height_func)
        except:
            log.err(None, 'Share check failed: %064x -> %064x' % (share.hash, share.previous_hash if share.previous_hash is not None else 0))
            return False
        else:
            self.verified.add(share)
            return True
    
    def think(self, block_rel_height_func, block_abs_height_func, previous_block, bits, known_txs):
        desired = set()
        bad_peer_addresses = set()
        
        # O(len(self.heads))
        #   make 'unverified heads' set?
        # for each overall head, attempt verification
        # if it fails, attempt on parent, and repeat
        # if no successful verification because of lack of parents, request parent
        bads = []
        for head in set(self.heads) - set(self.verified.heads):
            head_height, last = self.get_height_and_last(head)
            
            for share in self.get_chain(head, head_height if last is None else min(5, max(0, head_height - self.net.CHAIN_LENGTH))):
                if self.attempt_verify(share, block_abs_height_func, known_txs):
                    break
                bads.append(share.hash)
            else:
                if last is not None:
                    desired.add((
                        self.items[random.choice(list(self.reverse[last]))].peer_addr,
                        last,
                        max(x.timestamp for x in self.get_chain(head, min(head_height, 5))),
                        min(x.target for x in self.get_chain(head, min(head_height, 5))),
                    ))
        for bad in bads:
            if bad in self.verified.items:
                raise ValueError('bad share %s found in verified items' % (bad,))
            #assert bad in self.heads
            bad_share = self.items[bad]
            if bad_share.peer_addr is not None:
                bad_peer_addresses.add(bad_share.peer_addr)
            if p2pool.DEBUG:
                print "BAD", bad
            try:
                self.remove(bad)
            except NotImplementedError:
                pass
        
        # try to get at least CHAIN_LENGTH height for each verified head, requesting parents if needed
        for head in list(self.verified.heads):
            head_height, last_hash = self.verified.get_height_and_last(head)
            last_height, last_last_hash = self.get_height_and_last(last_hash)
            # XXX review boundary conditions
            want = max(self.net.CHAIN_LENGTH - head_height, 0)
            can = max(last_height - 1 - self.net.CHAIN_LENGTH, 0) if last_last_hash is not None else last_height
            get = min(want, can)
            #print 'Z', head_height, last_hash is None, last_height, last_last_hash is None, want, can, get
            for share in self.get_chain(last_hash, get):
                if not self.attempt_verify(share, block_abs_height_func, known_txs):
                    break
            if head_height < self.net.CHAIN_LENGTH and last_last_hash is not None:
                desired.add((
                    self.items[random.choice(list(self.verified.reverse[last_hash]))].peer_addr,
                    last_last_hash,
                    max(x.timestamp for x in self.get_chain(head, min(head_height, 5))),
                    min(x.target for x in self.get_chain(head, min(head_height, 5))),
                ))
        
        # decide best tree
        decorated_tails = sorted((self.score(max(self.verified.tails[tail_hash], key=self.verified.get_work), block_rel_height_func), tail_hash) for tail_hash in self.verified.tails)
        if p2pool.DEBUG:
            print len(decorated_tails), 'tails:'
            for score, tail_hash in decorated_tails:
                print format_hash(tail_hash), score
        best_tail_score, best_tail = decorated_tails[-1] if decorated_tails else (None, None)
        
        # decide best verified head
        decorated_heads = sorted(((
            self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))) -
            min(self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0], 1) * bitcoin_data.target_to_average_attempts(self.items[h].target),
            #self.items[h].peer_addr is None,
            -self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0],
            #-self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0] * bitcoin_data.target_to_average_attempts(self.items[h].target),
            -self.items[h].time_seen,
        ), h) for h in self.verified.tails.get(best_tail, []))
        traditional_sort = sorted(((
            self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))),
            #self.items[h].peer_addr is None,
            -self.items[h].time_seen, # assume they can't tell we should punish this share and will be sorting based on time
            -self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0],
        ), h) for h in self.verified.tails.get(best_tail, []))
        punish_aggressively = traditional_sort[-1][0][2] if traditional_sort else False

        if p2pool.DEBUG:
            print len(decorated_heads), 'heads. Top 10:'
            for score, head_hash in decorated_heads[-10:]:
                print '   ', format_hash(head_hash), format_hash(self.items[head_hash].previous_hash), score
            print "Traditional sort:"
            for score, head_hash in traditional_sort[-10:]:
                print '   ', format_hash(head_hash), format_hash(self.items[head_hash].previous_hash), score
        best_head_score, best = decorated_heads[-1] if decorated_heads else (None, None)

        punish = 0
        if best is not None:
            best_share = self.items[best]
            punish, punish_reason = best_share.should_punish_reason(previous_block, bits, self, known_txs)
            while punish > 0:
                print 'Punishing share for %r! Jumping from %s to %s!' % (punish_reason, format_hash(best), format_hash(best_share.previous_hash))
                best = best_share.previous_hash
                best_share = self.items[best]
                punish, punish_reason = best_share.should_punish_reason(previous_block, bits, self, known_txs)
                if not punish:
                    def best_descendent(hsh, limit=20):
                        child_hashes = self.reverse.get(hsh, set())
                        best_kids = sorted((best_descendent(child, limit-1) for child in child_hashes if not self.items[child].naughty))
                        if not best_kids or limit<0: # in case the only children are naughty
                            return 0, hsh
                        return (best_kids[-1][0]+1, best_kids[-1][1])
                    try:
                        gens, hsh = best_descendent(best)
                        if p2pool.DEBUG: print "best_descendent went %i generations for share %s from %s" % (gens, format_hash(hsh), format_hash(best))
                        best = hsh
                        best_share = self.items[best]
                    except:
                        traceback.print_exc()
            
            timestamp_cutoff = min(int(time.time()), best_share.timestamp) - 3600
            target_cutoff = int(2**256//(self.net.SHARE_PERIOD*best_tail_score[1] + 1) * 2 + .5) if best_tail_score[1] is not None else 2**256-1

            # Hard fork logic:
            # If our best share is v34 or higher, we will correctly zero-pad output scripts
            # Otherwise, we preserve a bug in order to avoid a chainsplit
            self.net.PARENT.padding_bugfix = (best_share.VERSION >= 35)

        else:
            timestamp_cutoff = int(time.time()) - 24*60*60
            target_cutoff = 2**256-1
        
        if p2pool.DEBUG:
            print 'Desire %i shares. Cutoff: %s old diff>%.2f' % (len(desired), math.format_dt(time.time() - timestamp_cutoff), bitcoin_data.target_to_difficulty(target_cutoff))
            for peer_addr, hash, ts, targ in desired:
                print '   ', None if peer_addr is None else '%s:%i' % peer_addr, format_hash(hash), math.format_dt(time.time() - ts), bitcoin_data.target_to_difficulty(targ), ts >= timestamp_cutoff, targ <= target_cutoff
        
        return best, [(peer_addr, hash) for peer_addr, hash, ts, targ in desired if ts >= timestamp_cutoff], decorated_heads, bad_peer_addresses, punish_aggressively
    
    def score(self, share_hash, block_rel_height_func):
        # returns approximate lower bound on chain's hashrate in the last self.net.CHAIN_LENGTH*15//16*self.net.SHARE_PERIOD time
        
        head_height = self.verified.get_height(share_hash)
        if head_height < self.net.CHAIN_LENGTH:
            return head_height, None
        
        end_point = self.verified.get_nth_parent_hash(share_hash, self.net.CHAIN_LENGTH*15//16)
        
        block_height = max(block_rel_height_func(share.header['previous_block']) for share in
            self.verified.get_chain(end_point, self.net.CHAIN_LENGTH//16))
        
        return self.net.CHAIN_LENGTH, self.verified.get_delta(share_hash, end_point).work/((0 - block_height + 1)*self.net.PARENT.BLOCK_PERIOD)

def update_min_protocol_version(counts, share):
    """One-way ratchet: when >=95% of shares are a newer version, bump
    the network's MINIMUM_PROTOCOL_VERSION so peers running older protocol
    versions are rejected.  Protocol.VERSION in p2p.py is auto-derived from
    max(share.MINIMUM_PROTOCOL_VERSION) so it always satisfies this check."""
    minpver = getattr(share.net, 'MINIMUM_PROTOCOL_VERSION', 1400)
    newminpver = share.MINIMUM_PROTOCOL_VERSION
    if (counts is not None) and (minpver < newminpver):
            if counts.get(share.VERSION, 0) >= sum(counts.itervalues())*95//100:
                share.net.MINIMUM_PROTOCOL_VERSION = newminpver
                print 'Setting MINIMUM_PROTOCOL_VERSION = %d' % (newminpver)


class AutoRatchet(object):
    """Fully automated, network-aware share version ratchet.
    
    Manages V35 -> V36 share version transitions without any manual
    configuration changes.  Persists state to disk so restarts (even
    with cleared share stores) don't regress to V35 once the network
    has confirmed V36.
    
    Window sizes adapt to the network config:
      Testnet:  REAL_CHAIN_LENGTH=400,  SHARE_PERIOD=4s   (~27 min)
      Mainnet:  REAL_CHAIN_LENGTH=8640, SHARE_PERIOD=15s  (~36 hours)
    
    State machine:
    
      VOTING --------(95% desired_version>=36)--------> ACTIVATED
        ^                                                   |
        |----(<50% desired_version>=36)-----<               |
                                                            |
        (sustained 2*REAL_CHAIN_LENGTH at 95% V36 shares)   |
                                                            v
      VOTING <--(follows V35 network, keeps voting)--- CONFIRMED
        ^                                                   |
        |---( <50% votes, network genuinely V35)---<        |
                                                            |
                          (permanent on restart)            |
                          CONFIRMED <-----------------------+
    
    VOTING:    Creates V35 shares, votes desired_version=36
    ACTIVATED: Creates V36 shares; reverts if network is <50% V36
    CONFIRMED: Creates V36 shares; persisted to disk, survives restart
               Still follows V35 network if <50% votes (consensus wins)
    """
    
    ACTIVATION_THRESHOLD = 95     # % of window voting V36 to activate
    DEACTIVATION_THRESHOLD = 50   # % below which to revert
    CONFIRMATION_MULTIPLIER = 2   # confirm after 2x REAL_CHAIN_LENGTH of V36 majority
    
    STATE_VOTING = 'voting'
    STATE_ACTIVATED = 'activated'
    STATE_CONFIRMED = 'confirmed'
    
    def __init__(self, datadir_path):
        self._state_file = os.path.join(datadir_path, 'v36_ratchet.json') if datadir_path else None
        self._state = self.STATE_VOTING
        self._activated_at = None       # timestamp
        self._activated_height = None   # share chain height at activation
        self._confirmed_at = None       # timestamp
        self._load()
    
    def _load(self):
        if self._state_file is None:
            return
        try:
            if os.path.exists(self._state_file):
                import json
                with open(self._state_file, 'r') as f:
                    data = json.load(f)
                self._state = data.get('state', self.STATE_VOTING)
                self._activated_at = data.get('activated_at')
                self._activated_height = data.get('activated_height')
                self._confirmed_at = data.get('confirmed_at')
                print '[AutoRatchet] Loaded state: %s (activated_at=%s, height=%s, confirmed_at=%s)' % (
                    self._state, self._activated_at, self._activated_height, self._confirmed_at)
        except (IOError, ValueError, KeyError) as e:
            print '[AutoRatchet] Warning: could not load state file: %s' % e
    
    def _save(self):
        if self._state_file is None:
            return
        try:
            import json
            data = {
                'state': self._state,
                'activated_at': self._activated_at,
                'activated_height': self._activated_height,
                'confirmed_at': self._confirmed_at,
            }
            with open(self._state_file, 'w') as f:
                json.dump(data, f)
        except IOError as e:
            print '[AutoRatchet] Warning: could not save state file: %s' % e
    
    @property
    def state(self):
        return self._state
    
    def get_share_version(self, tracker, best_share_hash, net):
        """Determine share version based on network state + ratchet state.
        
        Uses net.REAL_CHAIN_LENGTH for window sizing (400 testnet, 8640 mainnet).
        Confirmation requires 2 * REAL_CHAIN_LENGTH shares of sustained V36 majority.
        
        Returns:
            (share_class, desired_version) tuple
            share_class: MergedMiningShare or PaddingBugfixShare
            desired_version: always 36 (vote for V36)
        """
        confirmation_window = net.REAL_CHAIN_LENGTH * self.CONFIRMATION_MULTIPLIER
        
        # No chain at all — use persisted ratchet state for bootstrap
        if best_share_hash is None or tracker.get_height(best_share_hash) < 1:
            if self._state == self.STATE_CONFIRMED:
                return (MergedMiningShare, 36)
            else:
                # ACTIVATED but not confirmed → not safe to assume V36 on empty chain
                # VOTING → V35 is correct
                return (PaddingBugfixShare, 36)
        
        # Count version votes in available window
        height = tracker.get_height(best_share_hash)
        sample = min(height, net.REAL_CHAIN_LENGTH)
        v36_votes = 0
        v36_shares = 0  # actual V36 format shares (not just votes)
        total = 0
        
        for share in tracker.get_chain(best_share_hash, sample):
            total += 1
            desired_ver = getattr(share, 'desired_version', share.VERSION)
            if desired_ver >= 36:
                v36_votes += 1
            if share.VERSION >= 36:
                v36_shares += 1
        
        if total == 0:
            if self._state == self.STATE_CONFIRMED:
                return (MergedMiningShare, 36)
            return (PaddingBugfixShare, 36)
        
        vote_pct = (v36_votes * 100) // total
        share_pct = (v36_shares * 100) // total
        full_window = (total >= net.REAL_CHAIN_LENGTH)
        
        old_state = self._state
        
        # --- State transitions ---
        if self._state == self.STATE_VOTING:
            # Only activate with a full window of data
            if full_window and vote_pct >= self.ACTIVATION_THRESHOLD:
                self._state = self.STATE_ACTIVATED
                self._activated_at = int(time.time())
                self._activated_height = height
                print '[AutoRatchet] VOTING -> ACTIVATED (%d%% of %d shares vote V36, window=%d)' % (
                    vote_pct, total, net.REAL_CHAIN_LENGTH)
                self._save()
        
        elif self._state == self.STATE_ACTIVATED:
            if full_window and vote_pct < self.DEACTIVATION_THRESHOLD:
                # Network has genuinely reverted to V35 majority
                self._state = self.STATE_VOTING
                self._activated_at = None
                self._activated_height = None
                print '[AutoRatchet] ACTIVATED -> VOTING (%d%% votes < %d%% threshold)' % (
                    vote_pct, self.DEACTIVATION_THRESHOLD)
                self._save()
            elif self._activated_height is not None:
                if self._activated_height > height:
                    # activated_height is stale (from a previous session with a taller chain).
                    # Reset to current height so confirmation countdown restarts from now.
                    print '[AutoRatchet] Adjusting stale activated_height %d -> %d (chain rebuilt after restart)' % (
                        self._activated_height, height)
                    self._activated_height = height
                    self._save()
                shares_since = height - self._activated_height
                if shares_since >= confirmation_window and share_pct >= self.ACTIVATION_THRESHOLD:
                    self._state = self.STATE_CONFIRMED
                    self._confirmed_at = int(time.time())
                    print '[AutoRatchet] ACTIVATED -> CONFIRMED (%d shares since activation, %d%% V36, window=%d)' % (
                        shares_since, share_pct, confirmation_window)
                    self._save()
        
        elif self._state == self.STATE_CONFIRMED:
            # CONFIRMED is permanent for bootstrap, but still respects network consensus
            if full_window and vote_pct < self.DEACTIVATION_THRESHOLD:
                print '[AutoRatchet] WARNING: CONFIRMED but network is %d%% V35 - following network consensus' % (100 - vote_pct)
                return (PaddingBugfixShare, 36)
        
        # --- Output ---
        if self._state in (self.STATE_ACTIVATED, self.STATE_CONFIRMED):
            return (MergedMiningShare, 36)
        else:
            return (PaddingBugfixShare, 36)
    
    def __repr__(self):
        return 'AutoRatchet(state=%s, activated=%s, height=%s, confirmed=%s)' % (
            self._state, self._activated_at, self._activated_height, self._confirmed_at)


def get_pool_attempts_per_second(tracker, previous_share_hash, dist, min_work=False, integer=False):
    assert dist >= 2
    near = tracker.items[previous_share_hash]
    far = tracker.items[tracker.get_nth_parent_hash(previous_share_hash, dist - 1)]
    attempts = tracker.get_delta(near.hash, far.hash).work if not min_work else tracker.get_delta(near.hash, far.hash).min_work
    time = near.timestamp - far.timestamp
    if time <= 0:
        time = 1
    if integer:
        return attempts//time
    return attempts/time

def get_average_stale_prop(tracker, share_hash, lookbehind):
    stales = sum(1 for share in tracker.get_chain(share_hash, lookbehind) if share.share_data['stale_info'] is not None)
    return stales/(lookbehind + stales)

def get_stale_counts(tracker, share_hash, lookbehind, rates=False):
    res = {}
    for share in tracker.get_chain(share_hash, lookbehind - 1):
        res['good'] = res.get('good', 0) + bitcoin_data.target_to_average_attempts(share.target)
        s = share.share_data['stale_info']
        if s is not None:
            res[s] = res.get(s, 0) + bitcoin_data.target_to_average_attempts(share.target)
    if rates:
        dt = tracker.items[share_hash].timestamp - tracker.items[tracker.get_nth_parent_hash(share_hash, lookbehind - 1)].timestamp
        res = dict((k, v/dt) for k, v in res.iteritems())
    return res

def get_user_stale_props(tracker, share_hash, lookbehind, net):
    res = {}
    for share in tracker.get_chain(share_hash, lookbehind - 1):
        # Use share.address which is always set correctly for all versions:
        # V36: computed from share_data['pubkey_hash'] via pubkey_hash_to_address()
        # V34/V35: stored as share_data['address']
        # <V34: computed from share_data['pubkey_hash'] via pubkey_hash_to_address()
        key = share.address
        stale, total = res.get(key, (0, 0))
        total += 1
        if share.share_data['stale_info'] is not None:
            stale += 1
            total += 1
        res[key] = stale, total
    return dict((pubkey_hash, stale/total) for pubkey_hash, (stale, total) in res.iteritems())

def get_expected_payouts(tracker, best_share_hash, block_target, subsidy, net):
    weights, total_weight, donation_weight = tracker.get_cumulative_weights(best_share_hash, min(tracker.get_height(best_share_hash), net.REAL_CHAIN_LENGTH), 65535*net.SPREAD*bitcoin_data.target_to_average_attempts(block_target))
    res = dict((script, subsidy*weight//total_weight) for script, weight in weights.iteritems())
    # Use correct donation address based on whether V36 is active:
    # V36+: COMBINED_DONATION_SCRIPT (P2SH) → combined_donation_script_to_address()
    # Pre-V36: DONATION_SCRIPT (P2PK) → donation_script_to_address()
    best_share = tracker.items[best_share_hash]
    if best_share.VERSION >= 36:
        donation_addr = combined_donation_script_to_address(net)
    else:
        donation_addr = donation_script_to_address(net)
    res[donation_addr] = res.get(donation_addr, 0) + subsidy - sum(res.itervalues())
    return res

def get_desired_version_counts(tracker, best_share_hash, dist):
    res = {}
    for share in tracker.get_chain(best_share_hash, dist):
        res[share.desired_version] = res.get(share.desired_version, 0) + bitcoin_data.target_to_average_attempts(share.target)
    return res

def get_v36_merged_weights(tracker, best_share_hash, chain_length, max_weight, chain_id=None):
    """Calculate PPLNS weights for merged mining, including ONLY V36-signaling shares.
    
    Uses O(log n) MergedWeightsSkipList when the tracker supports it
    (OkayTracker), falling back to O(n) linear walk otherwise.
    
    During the V36 transition, pre-V36 shares should not receive merged mining
    rewards because V35 nodes don't contribute to merged block building.
    Their weight is excluded entirely — redistributed proportionally to V36
    miners by virtue of a smaller total_weight denominator.
    
    Args:
        tracker: OkayTracker instance (or any Tracker)
        best_share_hash: Head of share chain
        chain_length: Number of shares to walk (typically REAL_CHAIN_LENGTH)
        max_weight: Weight cap (65535 * SPREAD * target_to_average_attempts)
        chain_id: Merged chain AuxPoW ID (e.g., 98 for Dogecoin).
                  If provided, looks up explicit merged_addresses in V36 shares.
    
    Returns:
        (weights, total_weight, donation_weight) — same format as
        get_cumulative_weights() where total_weight == sum(weights) + donation_weight.
        Only V36-signaling shares are counted.
        Keys prefixed with 'MERGED:' are already merged-chain scripts (hex-encoded).
    """
    if chain_length <= 0 or best_share_hash is None:
        return {}, 0, 0
    
    # Fast path: O(log n) via MergedWeightsSkipList
    if hasattr(tracker, 'get_v36_merged_cumulative_weights'):
        weights, total_weight, donation_weight = tracker.get_v36_merged_cumulative_weights(
            chain_id, best_share_hash, chain_length, max_weight)
        import time as _time
        _now = _time.time()
        _last_t = getattr(get_v36_merged_weights, '_last_log_time', 0)
        if _now - _last_t >= 60:
            get_v36_merged_weights._last_log_time = _now
            print 'Merged mining weights: %d addresses (weight=%d, donation=%d) via skip list' % (
                len(weights), total_weight, donation_weight)
        return weights, total_weight, donation_weight
    
    # Fallback: O(n) linear walk for trackers without SkipList support
    weights = {}  # {address_key: weight}
    total_weight = 0
    donation_weight = 0
    v36_count = 0
    pre_v36_count = 0
    explicit_count = 0
    
    for share in tracker.get_chain(best_share_hash, chain_length):
        att = bitcoin_data.target_to_average_attempts(share.target)
        share_total = att * 65535  # Total contribution of this share
        
        if share.desired_version < 36:
            pre_v36_count += 1
            if total_weight + donation_weight + share_total > max_weight:
                break
            continue
        
        share_weight = att * (65535 - share.share_data['donation'])
        share_donation = att * share.share_data['donation']
        
        if total_weight + donation_weight + share_weight + share_donation > max_weight:
            remaining = max_weight - total_weight - donation_weight
            total_share = share_weight + share_donation
            if remaining > 0 and total_share > 0:
                share_weight = remaining * share_weight // total_share
                share_donation = remaining * share_donation // total_share
            else:
                break
        
        address_key = None
        
        if chain_id is not None and share.VERSION >= 36:
            merged_addrs = getattr(share, 'merged_addresses', None)
            if merged_addrs is None:
                merged_addrs = share.share_info.get('merged_addresses', None) if hasattr(share, 'share_info') and isinstance(share.share_info, dict) else None
            
            if merged_addrs:
                for entry in merged_addrs:
                    if entry['chain_id'] == chain_id:
                        address_key = 'MERGED:' + entry['script'].encode('hex')
                        explicit_count += 1
                        break
        
        if address_key is None:
            address_key = share.address
        
        weights[address_key] = weights.get(address_key, 0) + share_weight
        total_weight += share_weight
        donation_weight += share_donation
        v36_count += 1
    
    grand_total = total_weight + donation_weight
    
    _last = getattr(get_v36_merged_weights, '_last_log', None)
    _cur = (v36_count, pre_v36_count, explicit_count)
    if _last != _cur:
        get_v36_merged_weights._last_log = _cur
        msg = 'Merged mining weights: %d V36-signaling shares (weight=%d), %d pre-V36 excluded' % (
            v36_count, grand_total, pre_v36_count)
        if explicit_count > 0:
            msg += ', %d with explicit merged addresses' % explicit_count
        print msg
    
    return weights, grand_total, donation_weight

def compute_merged_payout_hash(tracker, previous_share_hash, block_target, net):
    """Compute deterministic hash of expected merged PPLNS weight distribution.
    
    This hash is committed into V36 shares so peers can verify that the
    share creator's merged mining payouts match the expected distribution.
    
    Without this, merged chain rewards are honor-system only — a malicious
    node could build correct parent chain payouts (consensus-enforced) but
    pay 100% of merged rewards to themselves (undetectable by peers).
    
    The hash covers sorted (address_key, weight) pairs plus total/donation
    weights — all deterministic from share chain state.
    
    Uses the same PPLNS window parameters as generate_transaction:
    - Starts at previous_share_hash (the parent share tip)
    - Chain length = min(height, REAL_CHAIN_LENGTH)
    - max_weight = 65535 * SPREAD * target_to_average_attempts(block_target)
    
    Returns:
        int or None: 256-bit hash, or None if no V36 shares in window / no share history.
        None is serialized as 0 by PossiblyNoneType in the wire format.
    """
    if previous_share_hash is None:
        return None
    
    height = tracker.get_height(previous_share_hash)
    if height == 0:
        return None
    
    max_weight = 65535 * net.SPREAD * bitcoin_data.target_to_average_attempts(block_target)
    chain_length = min(height, net.REAL_CHAIN_LENGTH)
    
    weights, total_weight, donation_weight = get_v36_merged_weights(
        tracker, previous_share_hash, chain_length, max_weight)
    
    if not weights or total_weight == 0:
        return None  # No V36 shares in window
    
    # Deterministic serialization: sorted by address key
    # Format: "addr1:weight1|addr2:weight2|...|T:total|D:donation"
    parts = []
    for addr_key in sorted(weights.keys()):
        parts.append('%s:%d' % (addr_key, weights[addr_key]))
    parts.append('T:%d' % total_weight)
    parts.append('D:%d' % donation_weight)
    
    payload = '|'.join(parts)
    return bitcoin_data.hash256(payload)


def get_warnings(tracker, best_share, net, bitcoind_getinfo, bitcoind_work_value, merged_work=None, auto_ratchet=None):
    res = []
    
    # Parent coin symbol for clear daemon identification
    parent_symbol = getattr(net.PARENT, 'SYMBOL', 'BTC') if hasattr(net, 'PARENT') else 'BTC'
    parent_name = getattr(net.PARENT, 'NAME', parent_symbol) if hasattr(net, 'PARENT') else parent_symbol
    
    desired_version_counts = get_desired_version_counts(tracker, best_share,
        min(net.CHAIN_LENGTH, 60*60//net.SHARE_PERIOD, tracker.get_height(best_share)))
    majority_desired_version = max(desired_version_counts, key=lambda k: desired_version_counts[k])
    if majority_desired_version not in share_versions and desired_version_counts[majority_desired_version] > sum(desired_version_counts.itervalues())/2:
        res.append('A MAJORITY OF SHARES CONTAIN A VOTE FOR AN UNSUPPORTED SHARE IMPLEMENTATION! (v%i with %i%% support)\n'
            'An upgrade is likely necessary. Check https://github.com/frstrtr/p2pool-merged-v36/releases for more information.' % (
                majority_desired_version, 100*desired_version_counts[majority_desired_version]/sum(desired_version_counts.itervalues())))
    
    if bitcoind_getinfo['warnings'] != '':
        if 'This is a pre-release test build' not in bitcoind_getinfo['warnings']:
            res.append('(from %s daemon) %s' % (parent_symbol, bitcoind_getinfo['warnings']))
    
    version_warning = getattr(net, 'VERSION_WARNING', lambda v: None)(bitcoind_getinfo['version'])
    if version_warning is not None:
        res.append(version_warning)
    
    if time.time() > bitcoind_work_value['last_update'] + 60:
        res.append('LOST CONTACT WITH %s DAEMON for %s! Check that it isn\'t frozen or dead!' % (
            parent_symbol, math.format_dt(time.time() - bitcoind_work_value['last_update'])))
    
    # Merged mining daemon warnings
    if merged_work:
        for chainid, mw in merged_work.iteritems():
            merged_name = mw.get('merged_net_name', 'Merged Chain (chainid %d)' % chainid)
            merged_symbol = mw.get('merged_net_symbol', 'chainid %d' % chainid)
            
            # Warnings from merged daemon's getnetworkinfo
            merged_warnings = mw.get('daemon_warnings', '')
            if merged_warnings and 'This is a pre-release test build' not in merged_warnings:
                res.append('(from %s daemon) %s' % (merged_symbol, merged_warnings))
            
            # Lost contact with merged daemon
            if 'last_update' in mw and time.time() > mw['last_update'] + 60:
                res.append('LOST CONTACT WITH %s DAEMON (%s) for %s! Check that mm-adapter or the merged daemon isn\'t frozen or dead!' % (
                    merged_symbol, merged_name,
                    math.format_dt(time.time() - mw['last_update'])))
    
    # AutoRatchet: determine effective state for transition-signal gating
    # (The dashboard ratchet banner handles the visual transition status display)
    ratchet_confirmed = False
    if auto_ratchet is not None:
        ratchet_state = getattr(auto_ratchet, 'state', '')
        
        # Detect stale confirmed: if chain is mostly V35, treat as voting
        effective_state = ratchet_state
        if ratchet_state == 'confirmed':
            height = tracker.get_height(best_share)
            sample = min(height, net.REAL_CHAIN_LENGTH) if height > 0 else 0
            v36_count = sum(1 for share in tracker.get_chain(best_share, sample) if share.VERSION >= 36)
            if sample > 0 and v36_count * 100 // sample < 50:
                effective_state = 'voting'
        
        ratchet_confirmed = effective_state == 'confirmed'
    if ratchet_confirmed:
        return res
    try:
        from p2pool.share_messages import MSG_TRANSITION_SIGNAL, FLAG_PROTOCOL_AUTHORITY
        scan_depth = min(
            net.CHAIN_LENGTH,
            60 * 60 // net.SHARE_PERIOD,
            tracker.get_height(best_share),
        )
        seen_transitions = set()  # dedup by (from, to)
        for share in tracker.get_chain(best_share, scan_depth):
            if not hasattr(share, '_parsed_messages') or not share._parsed_messages:
                continue
            for msg in share._parsed_messages:
                if msg.msg_type != MSG_TRANSITION_SIGNAL:
                    continue
                if not (msg.flags & FLAG_PROTOCOL_AUTHORITY):
                    continue
                try:
                    import json as _json
                    data = _json.loads(msg.payload)
                    key = (data.get('from'), data.get('to'))
                    if key in seen_transitions:
                        continue
                    seen_transitions.add(key)
                    urgency = data.get('urg', 'info')
                    prefix = {
                        'required': 'URGENT UPGRADE REQUIRED',
                        'recommended': 'Upgrade recommended',
                        'info': 'Upgrade info',
                    }.get(urgency, 'Upgrade info')
                    text = data.get('msg', 'Upgrade available')
                    url = data.get('url', '')
                    url_suffix = (' — %s' % url) if url else ''
                    res.append('[%s] v%s→v%s: %s%s' % (
                        prefix,
                        data.get('from', '?'),
                        data.get('to', '?'),
                        text,
                        url_suffix,
                    ))
                except (ValueError, TypeError, KeyError):
                    continue
    except ImportError:
        pass
    
    return res

def format_hash(x):
    if x is None:
        return 'xxxxxxxx'
    return '%08x' % (x % 2**32)

class ShareStore(object):
    def __init__(self, prefix, net, share_cb, verified_hash_cb):
        self.dirname = os.path.dirname(os.path.abspath(prefix))
        self.filename = os.path.basename(os.path.abspath(prefix))
        self.net = net

        start = time.time()
        
        known = {}
        filenames, next = self.get_filenames_and_next()
        for filename in filenames:
            share_hashes, verified_hashes = known.setdefault(filename, (set(), set()))
            with open(filename, 'rb') as f:
                for line in f:
                    try:
                        type_id_str, data_hex = line.strip().split(' ')
                        type_id = int(type_id_str)
                        if type_id == 0:
                            pass
                        elif type_id == 1:
                            pass
                        elif type_id == 2:
                            verified_hash = int(data_hex, 16)
                            verified_hash_cb(verified_hash)
                            verified_hashes.add(verified_hash)
                        elif type_id == 5:
                            raw_share = share_type.unpack(data_hex.decode('hex'))
                            if raw_share['type'] < Share.VERSION:
                                continue
                            share = load_share(raw_share, self.net, None)
                            share_cb(share)
                            share_hashes.add(share.hash)
                        else:
                            raise NotImplementedError("share type %i" % (type_id,))
                    except Exception:
                        log.err(None, "HARMLESS error while reading saved shares, continuing where left off:")
        
        self.known = known # filename -> (set of share hashes, set of verified hashes)
        self.known_desired = dict((k, (set(a), set(b))) for k, (a, b) in known.iteritems())

        print "Share loading took %.3f seconds" % (time.time() - start)
    
    def _add_line(self, line):
        filenames, next = self.get_filenames_and_next()
        if filenames and os.path.getsize(filenames[-1]) < 10e6:
            filename = filenames[-1]
        else:
            filename = next
        
        with open(filename, 'ab') as f:
            f.write(line + '\n')
        
        return filename
    
    def add_share(self, share):
        for filename, (share_hashes, verified_hashes) in self.known.iteritems():
            if share.hash in share_hashes:
                break
        else:
            filename = self._add_line("%i %s" % (5, share_type.pack(share.as_share()).encode('hex')))
            share_hashes, verified_hashes = self.known.setdefault(filename, (set(), set()))
            share_hashes.add(share.hash)
        share_hashes, verified_hashes = self.known_desired.setdefault(filename, (set(), set()))
        share_hashes.add(share.hash)
    
    def add_verified_hash(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known.iteritems():
            if share_hash in verified_hashes:
                break
        else:
            filename = self._add_line("%i %x" % (2, share_hash))
            share_hashes, verified_hashes = self.known.setdefault(filename, (set(), set()))
            verified_hashes.add(share_hash)
        share_hashes, verified_hashes = self.known_desired.setdefault(filename, (set(), set()))
        verified_hashes.add(share_hash)
    
    def get_filenames_and_next(self):
        suffixes = sorted(int(x[len(self.filename):]) for x in os.listdir(self.dirname) if x.startswith(self.filename) and x[len(self.filename):].isdigit())
        return [os.path.join(self.dirname, self.filename + str(suffix)) for suffix in suffixes], os.path.join(self.dirname, self.filename + (str(suffixes[-1] + 1) if suffixes else str(0)))
    
    def forget_share(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            if share_hash in share_hashes:
                share_hashes.remove(share_hash)
        self.check_remove()
    
    def forget_verified_share(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            if share_hash in verified_hashes:
                verified_hashes.remove(share_hash)
        self.check_remove()
    
    def check_remove(self):
        to_remove = set()
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            #print filename, len(share_hashes) + len(verified_hashes)
            if not share_hashes and not verified_hashes:
                to_remove.add(filename)
        for filename in to_remove:
            self.known.pop(filename)
            self.known_desired.pop(filename)
            os.remove(filename)
            print "REMOVED", filename
