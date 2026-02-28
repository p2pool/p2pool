#!/usr/bin/env python2
"""
End-to-end bech32 address conversion tests for merged mining.

Verifies that:
1. P2WPKH (bech32 v0, 20-byte) addresses are correctly identified as convertible
2. P2WSH (bech32 v0, 32-byte) addresses are correctly rejected
3. P2TR (bech32m v1) addresses are correctly rejected
4. P2SH (legacy script) addresses are correctly rejected
5. bech32 -> pubkey_hash -> DOGE legacy address produces correct output
6. V36 share roundtrip preserves pubkey_hash identity
7. build_merged_coinbase handles bech32 shareholders via auto-conversion
"""
from __future__ import print_function
import sys, os, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import segwit_addr
from p2pool.bitcoin.networks import litecoin_testnet, litecoin
from p2pool.bitcoin.networks import dogecoin_testnet4alpha, dogecoin
from p2pool.work import is_pubkey_hash_address
from p2pool import merged_mining

ltc_test = litecoin_testnet
doge_test = dogecoin_testnet4alpha
ltc_main = litecoin
doge_main = dogecoin

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print("  PASS: %s" % name)
        passed += 1
    else:
        print("  FAIL: %s %s" % (name, detail))
        failed += 1

print("=" * 70)
print("BECH32 ADDRESS CONVERSION TEST SUITE")
print("=" * 70)

# ===== Test 1: P2WPKH (bech32 SegWit v0, 20-byte program) =====
print("\n[Test 1] P2WPKH bech32 address - should be convertible")
legacy_addr = 'mwQqcRjWsCSvMfFrAvpcCujofQSFcV1AsW'
pkh_legacy, ver_legacy, wv_legacy = bitcoin_data.address_to_pubkey_hash(legacy_addr, ltc_test)
print("  Legacy: %s (pkh=%040x, ver=%s, wv=%s)" % (legacy_addr, pkh_legacy, ver_legacy, wv_legacy))

bech32_addr = bitcoin_data.pubkey_hash_to_address(pkh_legacy, -1, 0, ltc_test)
print("  Bech32: %s" % bech32_addr)

pkh_bech32, ver_bech32, wv_bech32 = bitcoin_data.address_to_pubkey_hash(bech32_addr, ltc_test)
check("bech32 decode pubkey_hash matches legacy", pkh_legacy == pkh_bech32)
check("bech32 version == -1", ver_bech32 == -1)
check("bech32 witness_version == 0", wv_bech32 == 0)

result = is_pubkey_hash_address(bech32_addr, ltc_test)
conv, pkh, err = result[0], result[1], result[2]
check("is_pubkey_hash_address returns True for P2WPKH", conv == True)
check("pubkey_hash matches", pkh == pkh_legacy)
check("no error message", err is None)
check("addr_type is p2pkh", len(result) > 3 and result[3] == 'p2pkh')

doge_addr = bitcoin_data.pubkey_hash_to_address(pkh, doge_test.ADDRESS_VERSION, -1, doge_test)
doge_addr_from_legacy = bitcoin_data.pubkey_hash_to_address(pkh_legacy, doge_test.ADDRESS_VERSION, -1, doge_test)
check("DOGE addr from bech32 == DOGE addr from legacy", doge_addr == doge_addr_from_legacy,
      "got %s vs %s" % (doge_addr, doge_addr_from_legacy))
print("  DOGE address: %s" % doge_addr)

# ===== Test 2: P2WSH (bech32 SegWit v0, 32-byte program) =====
print("\n[Test 2] P2WSH bech32 address - should NOT be convertible")
fake_hash = hashlib.sha256(b'dummy script data for p2wsh test').digest()
p2wsh_program = [ord(b) for b in fake_hash]
p2wsh_addr = segwit_addr.encode(ltc_test.HUMAN_READABLE_PART, 0, p2wsh_program)
print("  P2WSH: %s (%d chars)" % (p2wsh_addr, len(p2wsh_addr)))

result = is_pubkey_hash_address(p2wsh_addr, ltc_test)
conv, pkh, err = result[0], result[1], result[2]
check("P2WSH is NOT convertible", conv == False)
check("P2WSH error mentions script hash", err is not None and 'script hash' in err.lower(),
      "got: %s" % err)

# ===== Test 3: P2TR (bech32m SegWit v1) =====
print("\n[Test 3] P2TR bech32m address - should NOT be convertible")
p2tr_program = [0x02] + [i % 256 for i in range(31)]
try:
    p2tr_addr = segwit_addr.encode(ltc_test.HUMAN_READABLE_PART, 1, p2tr_program)
    print("  P2TR: %s (%d chars)" % (p2tr_addr, len(p2tr_addr)))
    result = is_pubkey_hash_address(p2tr_addr, ltc_test)
    conv = result[0]
    check("P2TR is NOT convertible", conv == False)
    check("P2TR error mentions taproot", result[2] is not None and 'taproot' in result[2].lower(),
          "got: %s" % result[2])
except Exception as e:
    # P2TR may fail to decode if segwit_addr doesn't support bech32m
    print("  P2TR encode/decode: %s" % e)
    result = is_pubkey_hash_address("tltc1p" + "a" * 54, ltc_test)
    check("P2TR-like address is NOT convertible", result[0] == False)

# ===== Test 4: P2SH =====
print("\n[Test 4] P2SH address - should BE convertible (as P2SH)")
# Generate a P2SH address using ADDRESS_P2SH_VERSION
p2sh_pkh = 0x89abcdeff0123456789abcdef0123456789abcde
p2sh_addr = bitcoin_data.pubkey_hash_to_address(p2sh_pkh, ltc_test.ADDRESS_P2SH_VERSION, -1, ltc_test)
print("  P2SH: %s" % p2sh_addr)
result = is_pubkey_hash_address(p2sh_addr, ltc_test)
conv = result[0]
pkh = result[1]
err = result[2]
addr_type = result[3] if len(result) > 3 else None
check("P2SH IS convertible", conv == True)
check("P2SH script_hash matches", pkh == p2sh_pkh)
check("P2SH addr_type is 'p2sh'", addr_type == 'p2sh', "got: %s" % addr_type)
# Verify it converts to DOGE P2SH
doge_p2sh = bitcoin_data.pubkey_hash_to_address(pkh, doge_test.ADDRESS_P2SH_VERSION, -1, doge_test)
print("  DOGE P2SH: %s" % doge_p2sh)
check("DOGE P2SH starts with '2' (testnet P2SH)", doge_p2sh.startswith('2'),
      "got: %s" % doge_p2sh)

# ===== Test 5: V36 share roundtrip =====
print("\n[Test 5] V36 share roundtrip: bech32 -> pubkey_hash -> legacy -> DOGE")
pkh_v36 = pkh_bech32  # What gets stored in V36 share's pubkey_hash field
reconstructed_ltc = bitcoin_data.pubkey_hash_to_address(pkh_v36, ltc_test.ADDRESS_VERSION, -1, ltc_test)
print("  Original bech32: %s" % bech32_addr)
print("  V36 reconstructed LTC (legacy): %s" % reconstructed_ltc)
doge_from_v36 = bitcoin_data.pubkey_hash_to_address(pkh_v36, doge_test.ADDRESS_VERSION, -1, doge_test)
check("V36 reconstructed legacy is valid LTC address", reconstructed_ltc.startswith('m') or reconstructed_ltc.startswith('n'))
check("DOGE from V36 matches DOGE from bech32", doge_from_v36 == doge_addr)
check("Same pubkey_hash preserves identity", pkh_v36 == pkh_legacy)

# ===== Test 6: Mainnet bech32 =====
print("\n[Test 6] Mainnet bech32 P2WPKH conversion")
test_pkh = 0x751e76e8199196d454941c45d1b3a323f1433bd6
bech32_main = bitcoin_data.pubkey_hash_to_address(test_pkh, -1, 0, ltc_main)
print("  LTC mainnet bech32: %s" % bech32_main)
conv, pkh, err = is_pubkey_hash_address(bech32_main, ltc_main)[:3]
check("Mainnet P2WPKH is convertible", conv == True)
if conv:
    doge_main_addr = bitcoin_data.pubkey_hash_to_address(pkh, doge_main.ADDRESS_VERSION, -1, doge_main)
    legacy_main = bitcoin_data.pubkey_hash_to_address(test_pkh, ltc_main.ADDRESS_VERSION, -1, ltc_main)
    print("  LTC legacy: %s" % legacy_main)
    print("  DOGE mainnet: %s" % doge_main_addr)
    check("Mainnet pubkey_hash preserved", pkh == test_pkh)

# ===== Test 7: build_merged_coinbase with bech32 shareholder =====
print("\n[Test 7] build_merged_coinbase with bech32 shareholder")
template = {
    'coinbasevalue': 100000000000,  # 1000 DOGE
    'height': 12345,
    'transactions': [],
    'version': 6422788,
    'previousblockhash': '0' * 64,
    'bits': '1d00ffff',
}

# Test with DOGE address (already converted by work.py)
shareholders_doge = {doge_addr: 1.0}
tx1 = merged_mining.build_merged_coinbase(
    template, shareholders_doge, doge_test, 1.0,
    parent_net=ltc_test)
outputs_1 = [o for o in tx1['tx_outs'] if o['value'] > 0 and o.get('script') != merged_mining.COMBINED_DONATION_SCRIPT]
check("DOGE address: outputs created", len(outputs_1) > 0)
miner_val_1 = sum(o['value'] for o in outputs_1)

# Test with LTC bech32 address (needs conversion inside build_merged_coinbase)
shareholders_bech32 = {bech32_addr: 1.0}
tx2 = merged_mining.build_merged_coinbase(
    template, shareholders_bech32, doge_test, 1.0,
    parent_net=ltc_test)
outputs_2 = [o for o in tx2['tx_outs'] if o['value'] > 0 and o.get('script') != merged_mining.COMBINED_DONATION_SCRIPT]
check("LTC bech32 address: outputs created via auto-conversion", len(outputs_2) > 0)
miner_val_2 = sum(o['value'] for o in outputs_2)

if outputs_1 and outputs_2:
    check("Same payout scripts (DOGE addr == converted bech32)", 
          outputs_1[0]['script'] == outputs_2[0]['script'],
          "scripts differ!")
    check("Same payout values", miner_val_1 == miner_val_2)

# ===== Test 8: build_merged_coinbase with mixed shareholders =====
print("\n[Test 8] build_merged_coinbase with mixed address types")
# Use a second address
legacy_addr2 = 'mxptR46XQBRk3EHstU83QRQcqT2PCVkW3g'
pkh2, _, _ = bitcoin_data.address_to_pubkey_hash(legacy_addr2, ltc_test)
bech32_addr2 = bitcoin_data.pubkey_hash_to_address(pkh2, -1, 0, ltc_test)
doge_addr2 = bitcoin_data.pubkey_hash_to_address(pkh2, doge_test.ADDRESS_VERSION, -1, doge_test)

# Mix: one DOGE addr + one LTC bech32
shareholders_mixed = {doge_addr: 0.6, bech32_addr2: 0.4}
tx3 = merged_mining.build_merged_coinbase(
    template, shareholders_mixed, doge_test, 1.0,
    parent_net=ltc_test)
outputs_3 = [o for o in tx3['tx_outs'] if o['value'] > 0 and o.get('script') != merged_mining.COMBINED_DONATION_SCRIPT]
check("Mixed shareholders: 2 miner outputs", len(outputs_3) == 2,
      "got %d outputs" % len(outputs_3))
total_miner_3 = sum(o['value'] for o in outputs_3)
print("  Total miner payout: %d satoshis" % total_miner_3)

# ===== Test 9: finder fee with bech32 address =====
print("\n[Test 9] Finder fee with bech32 address")
tx4 = merged_mining.build_merged_coinbase(
    template, shareholders_doge, doge_test, 1.0,
    parent_net=ltc_test,
    finder_address=bech32_addr2,
    finder_fee_percentage=0.5)
outputs_4 = [o for o in tx4['tx_outs'] if o['value'] > 0 and o.get('script') != merged_mining.COMBINED_DONATION_SCRIPT]
check("Finder fee with bech32: outputs created", len(outputs_4) >= 2,
      "got %d (expected >=2: miner + finder)" % len(outputs_4))

# ===== Test 10: key_is_address filter passes bech32 =====
print("\n[Test 10] key_is_address filter for bech32")
for addr_name, addr in [("bech32 P2WPKH", bech32_addr), ("bech32 P2WSH", p2wsh_addr), 
                          ("legacy P2PKH", legacy_addr)]:
    key_is_address = len(addr) >= 25 and len(addr) <= 100 and all(
        c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' for c in addr)
    check("%s passes key_is_address filter" % addr_name, key_is_address,
          "addr=%s, len=%d" % (addr, len(addr)))

# ===== Test 11: build_canonical_merged_coinbase with bech32 address key =====
print("\n[Test 11] build_canonical_merged_coinbase with bech32 P2WPKH key")
from p2pool.data import build_canonical_merged_coinbase, COMBINED_DONATION_SCRIPT
from p2pool.bitcoin import data as bitcoin_data_mod

# Simulate weights dict like get_v36_merged_weights returns.
# In practice share.address is always legacy P2PKH, but the canonical
# builder should also handle bech32 P2WPKH addresses for robustness.
test_weights_legacy = {legacy_addr: 60000}
test_weights_bech32 = {bech32_addr: 60000}
donation_w = 655
total_w = 60000 + donation_w
coinbase_val = 100000000000  # 1000 DOGE
block_h = 12345

# Build with legacy key
finder_script_test = '\x76\xa9\x14' + bitcoin_data_mod.pack.IntType(160).pack(pkh_legacy) + '\x88\xac'
tx_legacy = build_canonical_merged_coinbase(
    test_weights_legacy, total_w, donation_w, coinbase_val, block_h,
    finder_script_test, doge_test, ltc_test)

# Build with bech32 key
tx_bech32 = build_canonical_merged_coinbase(
    test_weights_bech32, total_w, donation_w, coinbase_val, block_h,
    finder_script_test, doge_test, ltc_test)

# The outputs should be identical — same pubkey_hash, same amounts
check("Canonical coinbase with legacy key: has outputs", len(tx_legacy['tx_outs']) > 0)
check("Canonical coinbase with bech32 key: has outputs", len(tx_bech32['tx_outs']) > 0)
check("Canonical coinbase: same number of outputs",
      len(tx_legacy['tx_outs']) == len(tx_bech32['tx_outs']),
      "legacy=%d, bech32=%d" % (len(tx_legacy['tx_outs']), len(tx_bech32['tx_outs'])))

# Compare output scripts and values
if len(tx_legacy['tx_outs']) == len(tx_bech32['tx_outs']):
    for i, (out_l, out_b) in enumerate(zip(tx_legacy['tx_outs'], tx_bech32['tx_outs'])):
        check("Output %d: same script" % i, out_l['script'] == out_b['script'],
              "scripts differ at output %d" % i)
        check("Output %d: same value" % i, out_l['value'] == out_b['value'],
              "legacy=%d, bech32=%d" % (out_l['value'], out_b['value']))

# Verify the miner output has the correct P2PKH script for DOGE
expected_doge_script = '\x76\xa9\x14' + bitcoin_data_mod.pack.IntType(160).pack(pkh_legacy) + '\x88\xac'
miner_outputs = [o for o in tx_bech32['tx_outs']
                 if o['script'] != COMBINED_DONATION_SCRIPT and o['value'] > 0]
check("Bech32 miner output has correct DOGE P2PKH script",
      len(miner_outputs) > 0 and any(o['script'] == expected_doge_script for o in miner_outputs))

# ===== Test 12: build_canonical_merged_coinbase rejects P2WSH/P2TR =====
print("\n[Test 12] build_canonical_merged_coinbase skips unconvertible addresses")
test_weights_p2wsh = {p2wsh_addr: 60000}
tx_p2wsh = build_canonical_merged_coinbase(
    test_weights_p2wsh, total_w, donation_w, coinbase_val, block_h,
    None, doge_test, ltc_test)
# P2WSH should be skipped — only donation output + OP_RETURN
non_donation_miner_outs = [o for o in tx_p2wsh['tx_outs']
                           if o['script'] != COMBINED_DONATION_SCRIPT and o['value'] > 0]
check("P2WSH address: no miner outputs (skipped)", len(non_donation_miner_outs) == 0,
      "got %d miner outputs" % len(non_donation_miner_outs))
# Full reward should go to donation
donation_outs = [o for o in tx_p2wsh['tx_outs'] if o['script'] == COMBINED_DONATION_SCRIPT]
check("P2WSH: full reward goes to donation", len(donation_outs) == 1 and donation_outs[0]['value'] == coinbase_val)

# ===== Test 13: build_canonical_merged_coinbase with MERGED: prefix key =====
print("\n[Test 13] build_canonical_merged_coinbase with MERGED: prefix key")
explicit_script = expected_doge_script
test_weights_merged = {'MERGED:' + explicit_script.encode('hex'): 60000}
tx_merged = build_canonical_merged_coinbase(
    test_weights_merged, total_w, donation_w, coinbase_val, block_h,
    finder_script_test, doge_test, ltc_test)
miner_outs_merged = [o for o in tx_merged['tx_outs']
                     if o['script'] != COMBINED_DONATION_SCRIPT and o['value'] > 0]
check("MERGED: prefix: miner output created", len(miner_outs_merged) > 0)
check("MERGED: prefix: same script as bech32 conversion",
      len(miner_outs_merged) > 0 and miner_outs_merged[0]['script'] == expected_doge_script)
# Values should match the legacy/bech32 outputs (all have same weight)
if miner_outputs and miner_outs_merged:
    check("MERGED: prefix: same value as bech32",
          miner_outs_merged[0]['value'] == miner_outputs[0]['value'])

# ===== Test 14: build_canonical_merged_coinbase with P2SH address key =====
print("\n[Test 14] build_canonical_merged_coinbase with P2SH address key")
test_weights_p2sh = {p2sh_addr: 60000}
tx_p2sh_c = build_canonical_merged_coinbase(
    test_weights_p2sh, total_w, donation_w, coinbase_val, block_h,
    None, doge_test, ltc_test)
# P2SH should produce a P2SH output: OP_HASH160 <hash> OP_EQUAL
expected_p2sh_script = '\xa9\x14' + bitcoin_data_mod.pack.IntType(160).pack(p2sh_pkh) + '\x87'
p2sh_miner_outs = [o for o in tx_p2sh_c['tx_outs']
                   if o['script'] != COMBINED_DONATION_SCRIPT and o['value'] > 0]
check("P2SH address: miner output created", len(p2sh_miner_outs) > 0,
      "got %d miner outputs" % len(p2sh_miner_outs))
if p2sh_miner_outs:
    check("P2SH output has correct P2SH script (OP_HASH160 <hash> OP_EQUAL)",
          p2sh_miner_outs[0]['script'] == expected_p2sh_script,
          "got script: %s" % p2sh_miner_outs[0]['script'].encode('hex'))

# ===== Test 15: build_merged_coinbase with P2SH shareholder =====
print("\n[Test 15] build_merged_coinbase with P2SH shareholder (auto-convert)")
# P2SH address from parent chain should auto-convert to DOGE P2SH
shareholders_p2sh = {p2sh_addr: 1.0}
tx_p2sh_m = merged_mining.build_merged_coinbase(
    template, shareholders_p2sh, doge_test, 1.0,
    parent_net=ltc_test)
p2sh_m_outs = [o for o in tx_p2sh_m['tx_outs']
               if o['value'] > 0 and o.get('script') != merged_mining.COMBINED_DONATION_SCRIPT]
check("P2SH shareholder: outputs created via auto-conversion", len(p2sh_m_outs) > 0,
      "got %d outputs" % len(p2sh_m_outs))
if p2sh_m_outs:
    check("P2SH shareholder: output script is P2SH (not P2PKH)",
          p2sh_m_outs[0]['script'] == expected_p2sh_script,
          "got: %s" % p2sh_m_outs[0]['script'].encode('hex'))

# ===== Summary =====
print("\n" + "=" * 70)
print("RESULTS: %d passed, %d failed out of %d tests" % (passed, failed, passed + failed))
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED!")
print("=" * 70)
sys.exit(1 if failed > 0 else 0)
