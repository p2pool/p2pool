#!/usr/bin/env python
"""
Test script to verify the donation transition system works correctly.
Tests both pre-V36 (DONATION_SCRIPT) and V36 (COMBINED_DONATION_SCRIPT) paths.

Verifies:
1. Script constants are well-formed
2. gentx_before_refhash matches for both BaseShare and MergedMiningShare
3. Pubkey hash endianness is correct (little-endian int)
4. hash160 hacks in bitcoin/data.py return correct values
5. P2MS script structure is valid
6. Script-to-address functions work
"""
from __future__ import print_function
import sys, os, hashlib, struct

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from p2pool import data as p2pool_data
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import pack

PASS = '\033[92mPASS\033[0m'
FAIL = '\033[91mFAIL\033[0m'
errors = []

def check(name, condition, detail=''):
    if condition:
        print('  [%s] %s' % (PASS, name))
    else:
        print('  [%s] %s %s' % (FAIL, name, ('- ' + detail) if detail else ''))
        errors.append(name)

print('=' * 70)
print('DONATION TRANSITION SYSTEM VALIDATION')
print('=' * 70)

# ============================================================
# 1. Script Constants
# ============================================================
print('\n--- 1. Script Constants ---')

# DONATION_SCRIPT: P2PK uncompressed (67 bytes)
check('DONATION_SCRIPT length = 67 bytes (P2PK uncompressed)',
      len(p2pool_data.DONATION_SCRIPT) == 67)
check('DONATION_SCRIPT starts with 0x41 (push 65 bytes)',
      p2pool_data.DONATION_SCRIPT[0] == '\x41')
check('DONATION_SCRIPT ends with 0xac (OP_CHECKSIG)',
      p2pool_data.DONATION_SCRIPT[-1] == '\xac')

# COMBINED_DONATION_REDEEM_SCRIPT: 1-of-2 P2MS (71 bytes)
check('COMBINED_DONATION_REDEEM_SCRIPT length = 71 bytes (1-of-2 P2MS)',
      len(p2pool_data.COMBINED_DONATION_REDEEM_SCRIPT) == 71)
check('COMBINED_DONATION_REDEEM_SCRIPT starts with 0x51 (OP_1)',
      p2pool_data.COMBINED_DONATION_REDEEM_SCRIPT[0] == '\x51')
check('COMBINED_DONATION_REDEEM_SCRIPT byte[1] = 0x21 (push 33 bytes, compressed pubkey 1)',
      p2pool_data.COMBINED_DONATION_REDEEM_SCRIPT[1] == '\x21')
check('COMBINED_DONATION_REDEEM_SCRIPT byte[35] = 0x21 (push 33 bytes, compressed pubkey 2)',
      p2pool_data.COMBINED_DONATION_REDEEM_SCRIPT[35] == '\x21')
check('COMBINED_DONATION_REDEEM_SCRIPT ends with 52ae (OP_2 OP_CHECKMULTISIG)',
      p2pool_data.COMBINED_DONATION_REDEEM_SCRIPT[-2:] == '\x52\xae')

# COMBINED_DONATION_SCRIPT: P2SH scriptPubKey (23 bytes)
check('COMBINED_DONATION_SCRIPT length = 23 bytes (P2SH scriptPubKey)',
      len(p2pool_data.COMBINED_DONATION_SCRIPT) == 23)
check('COMBINED_DONATION_SCRIPT starts with a9 14 (OP_HASH160 PUSH20)',
      p2pool_data.COMBINED_DONATION_SCRIPT[:2] == '\xa9\x14')
check('COMBINED_DONATION_SCRIPT ends with 87 (OP_EQUAL)',
      p2pool_data.COMBINED_DONATION_SCRIPT[-1] == '\x87')

# Verify pubkeys in redeem script match expected
forrestv_compressed = p2pool_data.COMBINED_DONATION_REDEEM_SCRIPT[2:2+33]
our_compressed = p2pool_data.COMBINED_DONATION_REDEEM_SCRIPT[36:36+33]
check('P2MS pubkey1 starts with 03 (compressed, odd y)',
      forrestv_compressed[0] == '\x03')
check('P2MS pubkey2 starts with 02 (compressed, even y)',
      our_compressed[0] == '\x02')

# Verify forrestv compressed matches forrestv uncompressed (same x-coordinate)
forrestv_uncompressed = p2pool_data.DONATION_SCRIPT[1:-1]  # Strip 0x41 push and 0xac OP_CHECKSIG
check('Forrestv uncompressed key is 65 bytes',
      len(forrestv_uncompressed) == 65)
check('Forrestv compressed x-coord matches uncompressed x-coord',
      forrestv_compressed[1:] == forrestv_uncompressed[1:33],
      'compressed[1:33]=%s... vs uncompressed[1:33]=%s...' % (
          forrestv_compressed[1:5].encode('hex'),
          forrestv_uncompressed[1:5].encode('hex')))

# ============================================================
# 2. Pubkey Hash Endianness (must be little-endian int)
# ============================================================
print('\n--- 2. Pubkey Hash Endianness ---')

# Compute actual hash160 values and compare
def compute_hash160_le(data):
    """Compute hash160 and return as little-endian int (matching pack.IntType(160).unpack)"""
    sha256 = hashlib.sha256(data).digest()
    ripemd160 = hashlib.new('ripemd160', sha256).digest()
    return pack.IntType(160).unpack(ripemd160)

# Forrestv uncompressed key hash160
actual_forrestv_uncompressed_hash = compute_hash160_le(forrestv_uncompressed)
check('DONATION_PUBKEY_HASH matches hash160(forrestv_uncompressed) [LE int]',
      p2pool_data.DONATION_PUBKEY_HASH == actual_forrestv_uncompressed_hash,
      'expected=0x%x got=0x%x' % (actual_forrestv_uncompressed_hash, p2pool_data.DONATION_PUBKEY_HASH))

# Combined donation script hash160 (embedded in P2SH scriptPubKey)
actual_combined_script_hash = pack.IntType(160).unpack(p2pool_data.COMBINED_DONATION_SCRIPT[2:22])
check('COMBINED_DONATION_PUBKEY_HASH matches embedded P2SH hash160 [LE int]',
      p2pool_data.COMBINED_DONATION_PUBKEY_HASH == actual_combined_script_hash,
      'expected=0x%x got=0x%x' % (actual_combined_script_hash, p2pool_data.COMBINED_DONATION_PUBKEY_HASH))

# Forrestv compressed key hash160 (still used for bitcoin/data.py hash160() fast-path)
actual_forrestv_compressed_hash = compute_hash160_le(forrestv_compressed)

# Our compressed key hash160 (kept for reference — used in COMBINED_DONATION_REDEEM_SCRIPT)
actual_our_hash = compute_hash160_le(our_compressed)

# ============================================================
# 3. hash160 Performance Hacks in bitcoin/data.py
# ============================================================
print('\n--- 3. hash160 Performance Hacks ---')

# bitcoin/data.py hash160() should return precomputed values for known pubkeys
hack_forrestv_uncompressed = bitcoin_data.hash160(forrestv_uncompressed)
check('hash160 hack: forrestv uncompressed returns correct LE int',
      hack_forrestv_uncompressed == p2pool_data.DONATION_PUBKEY_HASH,
      'hack=0x%x expected=0x%x' % (hack_forrestv_uncompressed, p2pool_data.DONATION_PUBKEY_HASH))

hack_forrestv_compressed = bitcoin_data.hash160(forrestv_compressed)
check('hash160 hack: forrestv compressed pubkey still returns expected LE int',
      hack_forrestv_compressed == actual_forrestv_compressed_hash,
      'hack=0x%x expected=0x%x' % (hack_forrestv_compressed, actual_forrestv_compressed_hash))

hack_our_compressed = bitcoin_data.hash160(our_compressed)
check('hash160 hack: our compressed returns correct LE int',
      hack_our_compressed == actual_our_hash,
      'hack=0x%x expected=0x%x' % (hack_our_compressed, actual_our_hash))

# ============================================================
# 4. gentx_before_refhash Consistency
# ============================================================
print('\n--- 4. gentx_before_refhash Consistency ---')

# Build expected gentx_before_refhash for BaseShare (DONATION_SCRIPT)
expected_base = pack.VarStrType().pack(p2pool_data.DONATION_SCRIPT) + \
                pack.IntType(64).pack(0) + \
                pack.VarStrType().pack('\x6a\x28' + pack.IntType(256).pack(0) + pack.IntType(64).pack(0))[:3]

check('BaseShare.gentx_before_refhash matches expected (DONATION_SCRIPT)',
      p2pool_data.BaseShare.gentx_before_refhash == expected_base)
check('BaseShare.gentx_before_refhash length = %d bytes' % len(expected_base),
      len(p2pool_data.BaseShare.gentx_before_refhash) == len(expected_base))

# Build expected gentx_before_refhash for MergedMiningShare (COMBINED_DONATION_SCRIPT)
expected_v36 = pack.VarStrType().pack(p2pool_data.COMBINED_DONATION_SCRIPT) + \
               pack.IntType(64).pack(0) + \
               pack.VarStrType().pack('\x6a\x28' + pack.IntType(256).pack(0) + pack.IntType(64).pack(0))[:3]

check('MergedMiningShare.gentx_before_refhash matches expected (COMBINED_DONATION_SCRIPT)',
      p2pool_data.MergedMiningShare.gentx_before_refhash == expected_v36)
check('MergedMiningShare.gentx_before_refhash length = %d bytes' % len(expected_v36),
      len(p2pool_data.MergedMiningShare.gentx_before_refhash) == len(expected_v36))

# Size difference tracks donation script size difference.
# With P2SH-wrapped combined script: 23 bytes vs 67-byte legacy P2PK script.
size_diff = len(p2pool_data.MergedMiningShare.gentx_before_refhash) - len(p2pool_data.BaseShare.gentx_before_refhash)
expected_size_diff = len(p2pool_data.COMBINED_DONATION_SCRIPT) - len(p2pool_data.DONATION_SCRIPT)
check('V36 gentx_before_refhash size delta matches donation script size delta',
      size_diff == expected_size_diff,
      'diff=%d expected=%d' % (size_diff, expected_size_diff))

# They must NOT be equal (different donation scripts)
check('BaseShare and MergedMiningShare gentx_before_refhash are DIFFERENT',
      p2pool_data.BaseShare.gentx_before_refhash != p2pool_data.MergedMiningShare.gentx_before_refhash)

# Verify structure: <varint><script><8-byte-value=0><varint 0x6a 0x28>
# The last 3 bytes should be the start of the OP_RETURN output
base_tail3 = p2pool_data.BaseShare.gentx_before_refhash[-3:]
v36_tail3 = p2pool_data.MergedMiningShare.gentx_before_refhash[-3:]
check('BaseShare gentx tail starts OP_RETURN (0x6a 0x28 prefix after varint)',
      base_tail3[1:] == '\x6a\x28')
check('V36 gentx tail starts OP_RETURN (0x6a 0x28 prefix after varint)',
      v36_tail3[1:] == '\x6a\x28')

# ============================================================
# 5. script_to_pubkey_hash() fast-paths
# ============================================================
print('\n--- 5. script_to_pubkey_hash() Fast-paths ---')

h1 = p2pool_data.script_to_pubkey_hash(p2pool_data.DONATION_SCRIPT)
check('script_to_pubkey_hash(DONATION_SCRIPT) returns DONATION_PUBKEY_HASH',
      h1 == p2pool_data.DONATION_PUBKEY_HASH)

h3 = p2pool_data.script_to_pubkey_hash(p2pool_data.COMBINED_DONATION_SCRIPT)
check('script_to_pubkey_hash(COMBINED_DONATION_SCRIPT) returns COMBINED_DONATION_PUBKEY_HASH',
      h3 == p2pool_data.COMBINED_DONATION_PUBKEY_HASH)

# ============================================================
# 6. Combined Donation Address Display
# ============================================================
print('\n--- 6. Combined Donation Address Display ---')

# Test that redeem script parses as 1-of-2 P2MS
parsed = bitcoin_data.parse_p2ms_script(p2pool_data.COMBINED_DONATION_REDEEM_SCRIPT)
check('parse_p2ms_script() succeeds on COMBINED_DONATION_REDEEM_SCRIPT',
      parsed is not None)
if parsed:
    n, m, pubkeys = parsed
    check('P2MS n=1 (1-of-2)',
          n == 1, 'got n=%d' % n)
    check('P2MS m=2 (1-of-2)',
          m == 2, 'got m=%d' % m)
    check('P2MS has 2 pubkeys',
          len(pubkeys) == 2, 'got %d' % len(pubkeys))
    check('P2MS pubkey1 = forrestv compressed',
          pubkeys[0] == forrestv_compressed)
    check('P2MS pubkey2 = our compressed',
          pubkeys[1] == our_compressed)

# Test combined_donation_script_to_address returns synthetic key when net is None
synthetic_addr = p2pool_data.combined_donation_script_to_address(None)
check('combined_donation_script_to_address returns synthetic key',
      synthetic_addr == 'P2SH:combined_donation',
      'got: %s' % synthetic_addr)

# ============================================================
# 7. Cross-check: V36 share type chain
# ============================================================
print('\n--- 7. Share Type Chain ---')

check('BaseShare.VERSION = 0',
      p2pool_data.BaseShare.VERSION == 0)
check('MergedMiningShare.VERSION = 36',
      p2pool_data.MergedMiningShare.VERSION == 36)
check('MergedMiningShare.VOTING_VERSION = 36',
      p2pool_data.MergedMiningShare.VOTING_VERSION == 36)

# Find the V35 share that has SUCCESSOR = MergedMiningShare
v35 = p2pool_data.PaddingBugfixShare
check('PaddingBugfixShare.VERSION = 35',
      v35.VERSION == 35)
check('PaddingBugfixShare.SUCCESSOR = MergedMiningShare',
      v35.SUCCESSOR == p2pool_data.MergedMiningShare,
      'got: %s' % (v35.SUCCESSOR,))
check('MergedMiningShare.SUCCESSOR = None (head of chain)',
      p2pool_data.MergedMiningShare.SUCCESSOR is None)

# V35 uses BaseShare gentx_before_refhash (DONATION_SCRIPT)
check('PaddingBugfixShare uses DONATION_SCRIPT in gentx_before_refhash',
      v35.gentx_before_refhash == p2pool_data.BaseShare.gentx_before_refhash,
      'V35 should inherit BaseShare gentx_before_refhash')

# ============================================================
# 8. Donation output structure in generate_transaction
# ============================================================
print('\n--- 8. Donation Amounts Logic ---')

# Verify that the excluded_dests logic works correctly
# Both primary_donation_address and combined_donation_addr should be excluded from sorted dests
# but added as the last output before OP_RETURN

# Test that donation addresses can be computed
try:
    from p2pool import networks as p2pool_networks
    net = p2pool_networks.nets['litecoin']
    primary_addr = p2pool_data.donation_script_to_address(net)
    check('donation_script_to_address(litecoin) returns valid address',
          primary_addr is not None and len(primary_addr) > 20,
          'got: %s' % primary_addr)
    print('       -> Primary donation address: %s' % primary_addr)

    combined_addr = p2pool_data.combined_donation_script_to_address(net)
    check('combined_donation_script_to_address returns standard address',
          combined_addr is not None and len(combined_addr) > 20,
          'got: %s' % combined_addr)
    print('       -> Combined donation address: %s' % combined_addr)
except ImportError:
    print('  [SKIP] Could not import litecoin network - skipping address tests')

# ============================================================
# SUMMARY
# ============================================================
print('\n' + '=' * 70)
if errors:
    print('\033[91mFAILED: %d test(s) failed:\033[0m' % len(errors))
    for e in errors:
        print('  - %s' % e)
    sys.exit(1)
else:
    print('\033[92mALL TESTS PASSED\033[0m')
    sys.exit(0)
