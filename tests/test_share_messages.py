#!/usr/bin/env pypy
"""
Comprehensive test suite for p2pool/share_messages.py

Tests cover:
  1. Constants & configuration values
  2. Crypto helpers (_hash160, _derive_pubkey, _ecdsa_sign, _ecdsa_verify,
     _xor_bytes, _generate_stream, _derive_encryption_key)
  3. Encryption layer (encrypt_message_data, decrypt_message_data)
  4. DerivedSigningKey (derivation, announcements, pack/unpack roundtrip)
  5. SigningKeyRegistry (register, revoke, lookup, key rotation, JSON)
  6. ShareMessage (create, pack/unpack, sign/verify, to_dict, edge cases)
  7. pack_share_messages / unpack_share_messages (full encrypted roundtrip)
  8. ShareMessageStore (add, dedup, prune, query, process_share)
  9. Message builders (all build_* convenience functions)
 10. Edge cases & error handling (malformed data, oversized, expired, etc.)
 11. Message Weight Units (MWU) budget calculations

Run:  pypy test_share_messages.py
"""
from __future__ import print_function, division

import sys
import os
import struct
import time
import hashlib
import hmac
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from p2pool.share_messages import (
    # Constants
    MSG_NODE_STATUS, MSG_MINER_MESSAGE, MSG_POOL_ANNOUNCE,
    MSG_VERSION_SIGNAL, MSG_MERGED_STATUS, MSG_EMERGENCY, MSG_TRANSITION_SIGNAL,
    FLAG_HAS_SIGNATURE, FLAG_BROADCAST, FLAG_PERSISTENT, FLAG_PROTOCOL_AUTHORITY,
    MAX_MESSAGE_PAYLOAD, MAX_MESSAGES_PER_SHARE, MAX_TOTAL_MESSAGE_BYTES,
    MAX_MESSAGE_AGE, MAX_MESSAGE_HISTORY,
    MWU_HEADER, MWU_PER_PAYLOAD_BYTE, MWU_PER_SIGNATURE_BYTE,
    MWU_ANNOUNCEMENT, MAX_MWU_PER_SHARE, FREE_MWU_ALLOWANCE,
    SIGNING_KEY_DOMAIN, SIGNING_KEY_ANNOUNCEMENT_SIZE,
    MESSAGE_TYPE_NAMES,
    DONATION_PUBKEY_FORRESTV, DONATION_PUBKEY_MAINTAINER,
    DONATION_AUTHORITY_PUBKEYS,
    ENCRYPTED_ENVELOPE_VERSION, ENCRYPTION_NONCE_SIZE,
    ENCRYPTION_MAC_SIZE, ENCRYPTION_HEADER_SIZE,

    # Crypto helpers
    _derive_pubkey, _ecdsa_sign, _ecdsa_verify, _hash160,
    _derive_encryption_key, _generate_stream, _xor_bytes,

    # Encryption
    encrypt_message_data, decrypt_message_data,

    # Classes
    DerivedSigningKey, SigningKeyRegistry, ShareMessage, ShareMessageStore,
    BanList,

    # Pack/unpack
    pack_share_messages, unpack_share_messages,
    compute_message_data_hash,

    # Builders
    build_node_status, build_miner_message, build_pool_announcement,
    build_merged_status, build_version_signal, build_emergency_alert,
    build_transition_signal, is_authority_pubkey,
)

# ============================================================================
# Test harness
# ============================================================================

passed = 0
failed = 0
skipped = 0
section_passed = 0
section_failed = 0


def check(name, condition, detail=""):
    global passed, failed, section_passed, section_failed
    if condition:
        print("  PASS: %s" % name)
        passed += 1
        section_passed += 1
    else:
        print("  FAIL: %s %s" % (name, detail))
        failed += 1
        section_failed += 1


def check_raises(name, fn, exc_type=Exception):
    """Check that fn() raises exc_type."""
    global passed, failed, section_passed, section_failed
    try:
        fn()
        print("  FAIL: %s (no exception raised)" % name)
        failed += 1
        section_failed += 1
    except exc_type:
        print("  PASS: %s" % name)
        passed += 1
        section_passed += 1
    except Exception as e:
        print("  FAIL: %s (wrong exception: %s)" % (name, e))
        failed += 1
        section_failed += 1


def section(title):
    global section_passed, section_failed
    section_passed = 0
    section_failed = 0
    print("\n" + "=" * 70)
    print("[%s]" % title)
    print("=" * 70)


def section_end():
    print("  --- section: %d passed, %d failed ---" % (section_passed, section_failed))


# Deterministic test key (32 bytes)
TEST_MASTER_KEY = hashlib.sha256(b'test-master-key-for-p2pool-messaging').digest()
TEST_MASTER_KEY_2 = hashlib.sha256(b'second-test-key-for-p2pool-messaging').digest()


# ============================================================================
# 1. Constants
# ============================================================================

section("1. Constants & Configuration")

check("MSG_NODE_STATUS == 0x01", MSG_NODE_STATUS == 0x01)
check("MSG_MINER_MESSAGE == 0x02", MSG_MINER_MESSAGE == 0x02)
check("MSG_POOL_ANNOUNCE == 0x03", MSG_POOL_ANNOUNCE == 0x03)
check("MSG_VERSION_SIGNAL == 0x04", MSG_VERSION_SIGNAL == 0x04)
check("MSG_MERGED_STATUS == 0x05", MSG_MERGED_STATUS == 0x05)
check("MSG_EMERGENCY == 0x10", MSG_EMERGENCY == 0x10)
check("MSG_TRANSITION_SIGNAL == 0x20", MSG_TRANSITION_SIGNAL == 0x20)

check("FLAG_HAS_SIGNATURE == 0x01", FLAG_HAS_SIGNATURE == 0x01)
check("FLAG_BROADCAST == 0x02", FLAG_BROADCAST == 0x02)
check("FLAG_PERSISTENT == 0x04", FLAG_PERSISTENT == 0x04)
check("FLAG_PROTOCOL_AUTHORITY == 0x08", FLAG_PROTOCOL_AUTHORITY == 0x08)

check("MAX_MESSAGE_PAYLOAD == 220", MAX_MESSAGE_PAYLOAD == 220)
check("MAX_MESSAGES_PER_SHARE == 3", MAX_MESSAGES_PER_SHARE == 3)
check("MAX_TOTAL_MESSAGE_BYTES == 512", MAX_TOTAL_MESSAGE_BYTES == 512)
check("MAX_MESSAGE_AGE == 86400", MAX_MESSAGE_AGE == 86400)
check("MAX_MESSAGE_HISTORY == 1000", MAX_MESSAGE_HISTORY == 1000)

check("SIGNING_KEY_ANNOUNCEMENT_SIZE == 57", SIGNING_KEY_ANNOUNCEMENT_SIZE == 57)
check("ENCRYPTION_HEADER_SIZE == 49", ENCRYPTION_HEADER_SIZE == 49)

check("MESSAGE_TYPE_NAMES has 7 entries", len(MESSAGE_TYPE_NAMES) == 7)
check("DONATION_AUTHORITY_PUBKEYS has 2 keys", len(DONATION_AUTHORITY_PUBKEYS) == 2)
check("forrestv pubkey is 33 bytes", len(DONATION_PUBKEY_FORRESTV) == 33)
check("maintainer pubkey is 33 bytes", len(DONATION_PUBKEY_MAINTAINER) == 33)
check("forrestv pubkey starts 0x03", ord(DONATION_PUBKEY_FORRESTV[0]) == 0x03)
check("maintainer pubkey starts 0x02", ord(DONATION_PUBKEY_MAINTAINER[0]) == 0x02)

# MWU constants
check("MWU_HEADER == 8", MWU_HEADER == 8)
check("MWU_PER_PAYLOAD_BYTE == 1", MWU_PER_PAYLOAD_BYTE == 1)
check("MWU_PER_SIGNATURE_BYTE == 2", MWU_PER_SIGNATURE_BYTE == 2)
check("MWU_ANNOUNCEMENT == 171", MWU_ANNOUNCEMENT == 171)
check("MAX_MWU_PER_SHARE == 1024", MAX_MWU_PER_SHARE == 1024)
check("FREE_MWU_ALLOWANCE == 64", FREE_MWU_ALLOWANCE == 64)

section_end()


# ============================================================================
# 2. Crypto Helpers
# ============================================================================

section("2. Crypto Helpers")

# _hash160
known_data = b'test data for hash160'
h160 = _hash160(known_data)
check("_hash160 returns 20 bytes", len(h160) == 20)

# Same input -> same output
h160_again = _hash160(known_data)
check("_hash160 deterministic", h160 == h160_again)

# Different input -> different output
h160_other = _hash160(b'different data')
check("_hash160 different input -> different output", h160 != h160_other)

# _derive_pubkey
privkey = hashlib.sha256(b'test-privkey').digest()
uncompressed, compressed = _derive_pubkey(privkey)
check("_derive_pubkey uncompressed is 65 bytes", len(uncompressed) == 65)
check("_derive_pubkey compressed is 33 bytes", len(compressed) == 33)
check("uncompressed starts with 0x04", ord(uncompressed[0]) == 0x04)
check("compressed starts with 0x02 or 0x03",
      ord(compressed[0]) in (0x02, 0x03))

# Deterministic
uncompressed2, compressed2 = _derive_pubkey(privkey)
check("_derive_pubkey deterministic (compressed)", compressed == compressed2)
check("_derive_pubkey deterministic (uncompressed)", uncompressed == uncompressed2)

# Different key -> different pubkey
privkey2 = hashlib.sha256(b'test-privkey-2').digest()
_, compressed3 = _derive_pubkey(privkey2)
check("different privkey -> different pubkey", compressed != compressed3)

# _ecdsa_sign and _ecdsa_verify
msg_hash = hashlib.sha256(b'test message for signing').digest()
signature = _ecdsa_sign(privkey, msg_hash)
check("_ecdsa_sign returns non-empty bytes", len(signature) > 0)
check("_ecdsa_sign DER sig length 68-73", 30 <= len(signature) <= 73,
      "got %d" % len(signature))

# Verify with correct key
verified = _ecdsa_verify(compressed, msg_hash, signature)
check("_ecdsa_verify correct key+msg -> True", verified is True)

# Verify with wrong key
verified_wrong = _ecdsa_verify(compressed3, msg_hash, signature)
check("_ecdsa_verify wrong key -> False", verified_wrong is False)

# Verify with wrong message
wrong_hash = hashlib.sha256(b'wrong message').digest()
verified_wrong_msg = _ecdsa_verify(compressed, wrong_hash, signature)
check("_ecdsa_verify wrong message -> False", verified_wrong_msg is False)

# Verify with tampered signature
if len(signature) > 5:
    tampered = signature[:4] + chr(ord(signature[4]) ^ 0xFF) + signature[5:]
    verified_tampered = _ecdsa_verify(compressed, msg_hash, tampered)
    check("_ecdsa_verify tampered sig -> False", verified_tampered is False)

# _xor_bytes
a = b'\x00\xFF\xAA\x55'
b_data = b'\xFF\x00\x55\xAA'
xored = _xor_bytes(a, b_data)
check("_xor_bytes basic", xored == b'\xFF\xFF\xFF\xFF')

# XOR with self = zeros
zeros = _xor_bytes(a, a)
check("_xor_bytes self -> zeros", zeros == b'\x00\x00\x00\x00')

# XOR is reversible
original = _xor_bytes(xored, b_data)
check("_xor_bytes reversible", original == a)

# _generate_stream
enc_key = hashlib.sha256(b'test-enc-key').digest()
stream = _generate_stream(enc_key, 100)
check("_generate_stream returns correct length", len(stream) == 100)

# Deterministic
stream2 = _generate_stream(enc_key, 100)
check("_generate_stream deterministic", stream == stream2)

# Different key -> different stream
enc_key2 = hashlib.sha256(b'test-enc-key-2').digest()
stream3 = _generate_stream(enc_key2, 100)
check("_generate_stream different key -> different stream", stream != stream3)

# Different length
stream_short = _generate_stream(enc_key, 10)
check("_generate_stream prefix matches", stream[:10] == stream_short)

# _derive_encryption_key
nonce = b'\x01' * 16
ek = _derive_encryption_key(DONATION_PUBKEY_FORRESTV, nonce)
check("_derive_encryption_key returns 32 bytes", len(ek) == 32)

# Same inputs -> same output
ek2 = _derive_encryption_key(DONATION_PUBKEY_FORRESTV, nonce)
check("_derive_encryption_key deterministic", ek == ek2)

# Different nonce -> different key
nonce2 = b'\x02' * 16
ek3 = _derive_encryption_key(DONATION_PUBKEY_FORRESTV, nonce2)
check("_derive_encryption_key different nonce -> different key", ek != ek3)

# Different pubkey -> different key
ek4 = _derive_encryption_key(DONATION_PUBKEY_MAINTAINER, nonce)
check("_derive_encryption_key different pubkey -> different key", ek != ek4)

section_end()


# ============================================================================
# 3. Encryption Layer
# ============================================================================

section("3. Encryption Layer")

# encrypt_message_data + decrypt_message_data roundtrip
test_plaintext = b'Hello, p2pool messaging!'
encrypted = encrypt_message_data(test_plaintext, DONATION_PUBKEY_FORRESTV)
check("encrypt returns non-empty", len(encrypted) > 0)
check("encrypt adds overhead", len(encrypted) > len(test_plaintext))
check("encrypted starts with version byte",
      ord(encrypted[0]) == ENCRYPTED_ENVELOPE_VERSION)
check("encrypted has minimum header size",
      len(encrypted) >= ENCRYPTION_HEADER_SIZE + len(test_plaintext))

# Decrypt
decrypted, auth_pubkey = decrypt_message_data(encrypted)
check("decrypt recovers plaintext", decrypted == test_plaintext)
check("decrypt identifies authority key", auth_pubkey == DONATION_PUBKEY_FORRESTV)

# Encrypt with maintainer key
encrypted_m = encrypt_message_data(test_plaintext, DONATION_PUBKEY_MAINTAINER)
decrypted_m, auth_pubkey_m = decrypt_message_data(encrypted_m)
check("decrypt with maintainer key", decrypted_m == test_plaintext)
check("decrypt identifies maintainer key", auth_pubkey_m == DONATION_PUBKEY_MAINTAINER)

# Two encryptions of same data differ (random nonce)
encrypted2 = encrypt_message_data(test_plaintext, DONATION_PUBKEY_FORRESTV)
check("two encryptions differ (random nonce)", encrypted != encrypted2)

# Decrypt both produce same plaintext
dec2, _ = decrypt_message_data(encrypted2)
check("both decrypt to same plaintext", dec2 == test_plaintext)

# Empty data
empty_enc = encrypt_message_data(b'', DONATION_PUBKEY_FORRESTV)
check("encrypt empty data returns empty", empty_enc == b'')

# Decrypt empty data
dec_empty, key_empty = decrypt_message_data(b'')
check("decrypt empty -> None", dec_empty is None and key_empty is None)

# Decrypt too short
dec_short, key_short = decrypt_message_data(b'\x01' * 10)
check("decrypt too short -> None", dec_short is None and key_short is None)

# Decrypt wrong version
wrong_version = chr(0x99) + encrypted[1:]
dec_wv, key_wv = decrypt_message_data(wrong_version)
check("decrypt wrong version -> None", dec_wv is None and key_wv is None)

# Tamper with ciphertext -> MAC failure
if len(encrypted) > ENCRYPTION_HEADER_SIZE + 2:
    tampered_enc = (encrypted[:ENCRYPTION_HEADER_SIZE + 1] +
                    chr(ord(encrypted[ENCRYPTION_HEADER_SIZE + 1]) ^ 0xFF) +
                    encrypted[ENCRYPTION_HEADER_SIZE + 2:])
    dec_tampered, key_tampered = decrypt_message_data(tampered_enc)
    check("decrypt tampered ciphertext -> None (MAC fail)",
          dec_tampered is None and key_tampered is None)

# Tamper with MAC -> failure
if len(encrypted) > 20:
    tampered_mac = (encrypted[:18] +
                    chr(ord(encrypted[18]) ^ 0xFF) +
                    encrypted[19:])
    dec_tm, key_tm = decrypt_message_data(tampered_mac)
    check("decrypt tampered MAC -> None", dec_tm is None and key_tm is None)

# Non-authority pubkey -> ValueError
check_raises("encrypt with non-authority pubkey raises ValueError",
             lambda: encrypt_message_data(b'test', b'\x02' + b'\x00' * 32),
             ValueError)

section_end()


# ============================================================================
# 4. DerivedSigningKey
# ============================================================================

section("4. DerivedSigningKey")

# Basic creation
dsk = DerivedSigningKey(TEST_MASTER_KEY, key_index=0)
check("DerivedSigningKey created", dsk is not None)
check("signing_id is 20 bytes", len(dsk.signing_id) == 20)
check("key_index == 0", dsk.key_index == 0)

# Deterministic
dsk2 = DerivedSigningKey(TEST_MASTER_KEY, key_index=0)
check("DerivedSigningKey deterministic (signing_id)",
      dsk.signing_id == dsk2.signing_id)

# Different key_index -> different signing_id
dsk_rot = DerivedSigningKey(TEST_MASTER_KEY, key_index=1)
check("key_index=1 -> different signing_id",
      dsk.signing_id != dsk_rot.signing_id)

# Different master key -> different signing_id
dsk_diff = DerivedSigningKey(TEST_MASTER_KEY_2, key_index=0)
check("different master key -> different signing_id",
      dsk.signing_id != dsk_diff.signing_id)

# Invalid master key length
check_raises("short master key raises ValueError",
             lambda: DerivedSigningKey(b'short', key_index=0), ValueError)
check_raises("long master key raises ValueError",
             lambda: DerivedSigningKey(b'\x00' * 64, key_index=0), ValueError)

# Sign
test_hash = hashlib.sha256(b'test message').digest()
sig = dsk.sign(test_hash)
check("sign returns non-empty", len(sig) > 0)

# get_announcement
ann = dsk.get_announcement()
check("announcement has signing_id", ann['signing_id'] == dsk.signing_id)
check("announcement has key_index", ann['key_index'] == 0)
check("announcement has 33-byte signing_pubkey",
      len(ann['signing_pubkey']) == 33)

# pack_announcement
packed_ann = dsk.pack_announcement()
check("packed announcement is 57 bytes", len(packed_ann) == 57,
      "got %d" % len(packed_ann))

# unpack_announcement roundtrip
sid, kidx, spk, consumed = DerivedSigningKey.unpack_announcement(packed_ann)
check("unpack signing_id matches", sid == dsk.signing_id)
check("unpack key_index matches", kidx == 0)
check("unpack signing_pubkey matches", spk == ann['signing_pubkey'])
check("unpack consumed == 57", consumed == 57)

# unpack_announcement with offset
padded = b'\xFF' * 10 + packed_ann
sid2, kidx2, spk2, consumed2 = DerivedSigningKey.unpack_announcement(padded, offset=10)
check("unpack with offset works", sid2 == dsk.signing_id)

# unpack_announcement with insufficient data
sid3, kidx3, spk3, consumed3 = DerivedSigningKey.unpack_announcement(b'too short')
check("unpack too short -> None", sid3 is None and consumed3 == 0)

# unpack_announcement with tampered signing_id (mismatch with pubkey)
tampered_ann = b'\x00' * 20 + packed_ann[20:]  # replace signing_id with zeros
sid_t, kidx_t, spk_t, consumed_t = DerivedSigningKey.unpack_announcement(tampered_ann)
check("unpack tampered signing_id -> None",
      sid_t is None and consumed_t == SIGNING_KEY_ANNOUNCEMENT_SIZE)

# Verify the signing_id = HASH160(compressed_pubkey) relationship
expected_id = _hash160(ann['signing_pubkey'])
check("signing_id == HASH160(compressed_pubkey)", dsk.signing_id == expected_id)

section_end()


# ============================================================================
# 5. SigningKeyRegistry
# ============================================================================

section("5. SigningKeyRegistry")

reg = SigningKeyRegistry()

# Register first key
ann_data = dsk.get_announcement()
is_new = reg.register_key(
    miner_address='miner1_addr',
    signing_id=ann_data['signing_id'],
    key_index=ann_data['key_index'],
    signing_pubkey=ann_data['signing_pubkey'],
    share_hash=0xDEAD,
    timestamp=time.time(),
)
check("register_key returns True for new key", is_new is True)

# Key is valid
check("is_key_valid for registered key", reg.is_key_valid(ann_data['signing_id']))

# get_pubkey returns correct key
pubkey = reg.get_pubkey_for_id(ann_data['signing_id'])
check("get_pubkey_for_id returns correct pubkey", pubkey == ann_data['signing_pubkey'])

# get_miner_for_id
miner = reg.get_miner_for_id(ann_data['signing_id'])
check("get_miner_for_id returns correct miner", miner == 'miner1_addr')

# get_miner_current_key
current = reg.get_miner_current_key('miner1_addr')
check("get_miner_current_key returned dict", current is not None)
check("current key has key_index 0", current['key_index'] == 0)

# Re-register same key
is_new2 = reg.register_key(
    miner_address='miner1_addr',
    signing_id=ann_data['signing_id'],
    key_index=ann_data['key_index'],
    signing_pubkey=ann_data['signing_pubkey'],
)
check("re-register same key returns False", is_new2 is False)

# Key rotation: register key_index=1
ann_rot = dsk_rot.get_announcement()
is_new_rot = reg.register_key(
    miner_address='miner1_addr',
    signing_id=ann_rot['signing_id'],
    key_index=ann_rot['key_index'],
    signing_pubkey=ann_rot['signing_pubkey'],
)
check("rotated key register returns True", is_new_rot is True)

# Old key should be revoked
check("old key_index=0 revoked after rotation",
      not reg.is_key_valid(ann_data['signing_id']))

# New key should be valid
check("new key_index=1 valid", reg.is_key_valid(ann_rot['signing_id']))

# get_pubkey_for_id on revoked key returns None
revoked_pk = reg.get_pubkey_for_id(ann_data['signing_id'])
check("get_pubkey_for_id revoked key -> None", revoked_pk is None)

# get_miner_current_key after rotation
current2 = reg.get_miner_current_key('miner1_addr')
check("current key after rotation has key_index 1", current2['key_index'] == 1)

# Register second miner
ann_diff = dsk_diff.get_announcement()
reg.register_key(
    miner_address='miner2_addr',
    signing_id=ann_diff['signing_id'],
    key_index=0,
    signing_pubkey=ann_diff['signing_pubkey'],
)
check("second miner key valid", reg.is_key_valid(ann_diff['signing_id']))
check("second miner lookup correct",
      reg.get_miner_for_id(ann_diff['signing_id']) == 'miner2_addr')

# Unknown signing_id
unknown_id = b'\xFF' * 20
check("unknown signing_id invalid", not reg.is_key_valid(unknown_id))
check("unknown signing_id pubkey -> None", reg.get_pubkey_for_id(unknown_id) is None)
check("unknown signing_id miner -> None", reg.get_miner_for_id(unknown_id) is None)

# Unknown miner
check("unknown miner current key -> None",
      reg.get_miner_current_key('unknown_miner') is None)

# to_json
reg_json = reg.to_json()
check("to_json returns dict", isinstance(reg_json, dict))
check("to_json has miner1_addr", 'miner1_addr' in reg_json)
check("to_json has miner2_addr", 'miner2_addr' in reg_json)

section_end()


# ============================================================================
# 6. ShareMessage
# ============================================================================

section("6. ShareMessage — Create, Pack/Unpack, Properties")

# Basic creation
msg = ShareMessage(
    msg_type=MSG_MINER_MESSAGE,
    payload=b'Hello miners!',
    flags=FLAG_BROADCAST | FLAG_PERSISTENT,
    timestamp=1700000000,
)
check("msg created", msg is not None)
check("msg.msg_type correct", msg.msg_type == MSG_MINER_MESSAGE)
check("msg.payload correct", msg.payload == b'Hello miners!')
check("msg.timestamp correct", msg.timestamp == 1700000000)
check("msg.type_name == MINER_MESSAGE", msg.type_name == 'MINER_MESSAGE')
check("msg.has_signature is False (not signed yet)", not msg.has_signature)
check("msg.is_broadcast is True", msg.is_broadcast)
check("msg.is_persistent is True", msg.is_persistent)
check("msg.is_protocol_authority is False", not msg.is_protocol_authority)
check("msg.verified is False", msg.verified is False)
check("msg.share_hash is None", msg.share_hash is None)

# message_hash is deterministic
mh1 = msg.message_hash()
mh2 = msg.message_hash()
check("message_hash is 32 bytes", len(mh1) == 32)
check("message_hash deterministic", mh1 == mh2)

# Different payload -> different hash
msg2 = ShareMessage(MSG_MINER_MESSAGE, b'Different', timestamp=1700000000,
                    flags=FLAG_BROADCAST | FLAG_PERSISTENT)
check("different payload -> different message_hash",
      msg.message_hash() != msg2.message_hash())

# Auto-timestamp
msg_auto = ShareMessage(MSG_NODE_STATUS, b'test')
check("auto timestamp near now", abs(msg_auto.timestamp - int(time.time())) < 5)

# String payload auto-encode
msg_str = ShareMessage(MSG_MINER_MESSAGE, 'text payload')
check("string payload auto-encoded", isinstance(msg_str.payload, bytes))

# Pack
packed = msg.pack()
check("pack returns bytes", isinstance(packed, (bytes, str)))
check("pack minimum size", len(packed) >= 29)  # 8 header + 0 payload + 20 sid + 1 siglen

# Unpack roundtrip
msg_unpacked, new_offset = ShareMessage.unpack(packed)
check("unpack type matches", msg_unpacked.msg_type == msg.msg_type)
check("unpack flags match (minus authority)",
      msg_unpacked.flags == (msg.flags & ~FLAG_PROTOCOL_AUTHORITY))
check("unpack timestamp matches", msg_unpacked.timestamp == msg.timestamp)
check("unpack payload matches", msg_unpacked.payload == msg.payload)
check("unpack offset at end", new_offset == len(packed))

# Pack with signature
msg_signed = ShareMessage(
    MSG_MINER_MESSAGE, b'Signed message',
    flags=FLAG_HAS_SIGNATURE | FLAG_BROADCAST,
    timestamp=1700000000,
)
msg_signed.sign(dsk)
check("sign sets FLAG_HAS_SIGNATURE", msg_signed.has_signature)
check("sign sets signing_id", msg_signed.signing_id == dsk.signing_id)
check("sign sets non-empty signature", len(msg_signed.signature) > 0)

packed_signed = msg_signed.pack()
msg_us, off_us = ShareMessage.unpack(packed_signed)
check("unpack signed: type matches", msg_us.msg_type == MSG_MINER_MESSAGE)
check("unpack signed: payload matches", msg_us.payload == b'Signed message')
check("unpack signed: signing_id matches",
      msg_us.signing_id == msg_signed.signing_id)
check("unpack signed: signature matches",
      msg_us.signature == msg_signed.signature)

# Verify against registry (dsk key_index=0 was revoked)
# We need to register a fresh key that hasn't been rotated
reg_verify = SigningKeyRegistry()
ann_v = dsk.get_announcement()
reg_verify.register_key('miner_v', ann_v['signing_id'], ann_v['key_index'],
                        ann_v['signing_pubkey'])
result_verify = msg_signed.verify(reg_verify)
check("verify returns True with valid key", result_verify is True)
check("verified flag set", msg_signed.verified is True)
check("sender_address set", msg_signed.sender_address == 'miner_v')

# Verify with revoked key (from original reg where key was rotated)
msg_signed2 = ShareMessage(MSG_MINER_MESSAGE, b'test', timestamp=1700000001)
msg_signed2.sign(dsk)  # key_index=0, which was revoked in 'reg'
result_revoked = msg_signed2.verify(reg)  # reg has key_index=0 revoked
check("verify with revoked key -> False", result_revoked is False)

# Unsigned message verify -> False
msg_unsigned = ShareMessage(MSG_NODE_STATUS, b'status')
result_unsigned = msg_unsigned.verify(reg_verify)
check("verify unsigned message -> False", result_unsigned is False)

# to_dict
d = msg.to_dict()
check("to_dict has type", d['type'] == 'MINER_MESSAGE')
check("to_dict has type_id", d['type_id'] == MSG_MINER_MESSAGE)
check("to_dict has timestamp", d['timestamp'] == 1700000000)
check("to_dict has verified", d['verified'] is False)
check("to_dict flags dict", isinstance(d['flags'], dict))
check("to_dict text for MINER_MESSAGE", 'text' in d)
check("to_dict text content", d['text'] == 'Hello miners!')

# to_dict for NODE_STATUS (JSON payload)
status_payload = json.dumps({'v': '13.4', 'up': 3600})
msg_status = ShareMessage(MSG_NODE_STATUS, status_payload, timestamp=1700000000)
d_status = msg_status.to_dict()
check("to_dict NODE_STATUS has data field", 'data' in d_status)
check("to_dict NODE_STATUS data is dict", isinstance(d_status['data'], dict))

# to_dict for unknown binary payload
msg_bin = ShareMessage(0xFF, b'\xDE\xAD\xBE\xEF', timestamp=1700000000)
d_bin = msg_bin.to_dict()
check("to_dict unknown type has raw field", 'raw' in d_bin)

# __repr__
repr_str = repr(msg)
check("repr contains type name", 'MINER_MESSAGE' in repr_str)
check("repr contains ShareMessage", 'ShareMessage' in repr_str)

# Pack oversized payload -> ValueError
msg_big = ShareMessage(MSG_MINER_MESSAGE, b'X' * (MAX_MESSAGE_PAYLOAD + 1))
check_raises("pack oversized payload raises ValueError",
             lambda: msg_big.pack(), ValueError)

# Pack oversized signature -> ValueError
msg_bigsig = ShareMessage(MSG_MINER_MESSAGE, b'test')
msg_bigsig.signature = b'\x00' * 74  # max DER sig is 73
check_raises("pack oversized signature raises ValueError",
             lambda: msg_bigsig.pack(), ValueError)

# Unpack from too-short data
check_raises("unpack from 3 bytes raises ValueError",
             lambda: ShareMessage.unpack(b'\x00' * 3), ValueError)

# Unpack with declared payload larger than actual data
header = struct.pack('<BBIH', 0x02, 0x00, 1700000000, 200)  # says 200 bytes payload
check_raises("unpack truncated payload raises ValueError",
             lambda: ShareMessage.unpack(header + b'\x00' * 5), ValueError)

# Unpack with payload_len > MAX_MESSAGE_PAYLOAD
header_big = struct.pack('<BBIH', 0x02, 0x00, 1700000000, 500)
check_raises("unpack payload_len > MAX raises ValueError",
             lambda: ShareMessage.unpack(header_big + b'\x00' * 500), ValueError)

# Signing with None signing_id pack uses zero-fill
msg_nosid = ShareMessage(MSG_NODE_STATUS, b'test', timestamp=1700000000)
packed_nosid = msg_nosid.pack()
msg_nosid_up, _ = ShareMessage.unpack(packed_nosid)
check("unpack unsigned -> signing_id is None", msg_nosid_up.signing_id is None)

section_end()


# ============================================================================
# 7. Authority Direct Verification
# ============================================================================

section("7. Authority Direct Verification")

# verify_authority_direct requires an actual signature
# Since we don't have the real authority private keys, test with a mock scenario
# We test the rejection paths:

msg_auth = ShareMessage(MSG_TRANSITION_SIGNAL, b'{"from":36,"to":37}',
                        timestamp=1700000000)

# No signature -> False
result_nosig = msg_auth.verify_authority_direct(DONATION_PUBKEY_FORRESTV)
check("verify_authority_direct no sig -> False", result_nosig is False)

# Non-authority pubkey -> False
msg_auth.signature = b'\x30\x06\x02\x01\x01\x02\x01\x01'  # dummy DER
msg_auth.signing_id = b'\x00' * 20
result_nonauth = msg_auth.verify_authority_direct(b'\x02' + b'\x00' * 32)
check("verify_authority_direct non-authority pubkey -> False",
      result_nonauth is False)

# is_authority_pubkey
check("is_authority_pubkey forrestv", is_authority_pubkey(DONATION_PUBKEY_FORRESTV))
check("is_authority_pubkey maintainer", is_authority_pubkey(DONATION_PUBKEY_MAINTAINER))
check("is_authority_pubkey random -> False",
      not is_authority_pubkey(b'\x02' + b'\x00' * 32))

section_end()


# ============================================================================
# 8. Pack/Unpack Share Messages (Full Encrypted Roundtrip)
# ============================================================================

section("8. Pack/Unpack Share Messages (Encrypted Roundtrip)")

# pack_share_messages requires authority-signed messages, so we test that
# unsigned messages are rejected
msg_unsigned_pack = ShareMessage(MSG_MINER_MESSAGE, b'unsigned',
                                 timestamp=1700000000)
check_raises("pack unsigned message raises ValueError",
             lambda: pack_share_messages([msg_unsigned_pack]),
             ValueError)

# pack with non-authority signature also rejected
msg_noauth = ShareMessage(MSG_MINER_MESSAGE, b'wrong signer',
                          timestamp=1700000000)
msg_noauth.sign(dsk)  # valid signature, but NOT an authority key
check_raises("pack non-authority signature raises ValueError",
             lambda: pack_share_messages([msg_noauth]),
             ValueError)

# Empty pack
empty_result = pack_share_messages([], signing_key_announcement=None)
check("pack no messages -> empty bytes", empty_result == b'')

# Unpack empty
msgs_empty, info_empty = unpack_share_messages(b'')
check("unpack empty -> empty list", msgs_empty == [])
check("unpack empty -> None info", info_empty is None)

# Unpack too short
msgs_short, info_short = unpack_share_messages(b'\x01\x02\x03')
check("unpack too short -> empty list", msgs_short == [])

# compute_message_data_hash
hash_empty = compute_message_data_hash(b'')
check("message_data_hash empty -> zero hash", hash_empty == b'\x00' * 32)

hash_data = compute_message_data_hash(b'test data')
check("message_data_hash returns 32 bytes", len(hash_data) == 32)
check("message_data_hash non-zero", hash_data != b'\x00' * 32)

# Deterministic
hash_data2 = compute_message_data_hash(b'test data')
check("message_data_hash deterministic", hash_data == hash_data2)

# Different data -> different hash
hash_diff = compute_message_data_hash(b'different data')
check("message_data_hash different data", hash_data != hash_diff)

section_end()


# ============================================================================
# 9. ShareMessageStore
# ============================================================================

section("9. ShareMessageStore")

store = ShareMessageStore(max_messages=100, max_age=86400)
check("store created", store is not None)
check("store empty initially", len(store.messages) == 0)

# add_local_message
msg_local = ShareMessage(MSG_MINER_MESSAGE, b'Hello from local',
                         sender_address='local_miner')
added = store.add_local_message(msg_local)
check("add_local_message returns True", added is True)
check("store has 1 message", len(store.messages) == 1)

# Duplicate detection
added_dup = store.add_local_message(msg_local)
check("duplicate message rejected", added_dup is False)
check("store still 1 message", len(store.messages) == 1)

# Add different message
msg_local2 = ShareMessage(MSG_POOL_ANNOUNCE, b'Pool announcement',
                          sender_address='operator')
added2 = store.add_local_message(msg_local2)
check("second message added", added2 is True)
check("store has 2 messages", len(store.messages) == 2)

# get_messages
all_msgs = store.get_messages()
check("get_messages returns all", len(all_msgs) == 2)

# get_messages by type
miner_msgs = store.get_messages(msg_type=MSG_MINER_MESSAGE)
check("get_messages filter by type", len(miner_msgs) == 1)
check("filtered message correct", miner_msgs[0].payload == b'Hello from local')

announce_msgs = store.get_messages(msg_type=MSG_POOL_ANNOUNCE)
check("get pool announcements", len(announce_msgs) == 1)

# get_messages by sender
sender_msgs = store.get_messages(sender='local_miner')
check("get_messages by sender", len(sender_msgs) == 1)

# get_messages since timestamp
future = int(time.time()) + 3600
since_msgs = store.get_messages(since=future)
check("get_messages since future -> empty", len(since_msgs) == 0)

past = 0
since_past = store.get_messages(since=past)
check("get_messages since epoch -> all", len(since_past) == 2)

# get_messages verified_only (none verified)
verified_msgs = store.get_messages(verified_only=True)
check("get_messages verified_only (none) -> empty", len(verified_msgs) == 0)

# get_messages limit
limited = store.get_messages(limit=1)
check("get_messages with limit=1", len(limited) == 1)

# Convenience getters
check("get_recent returns messages", len(store.get_recent()) == 2)
check("get_chat returns miner messages", len(store.get_all_chat()) == 1)
check("get_chat verified only", len(store.get_chat()) == 0)  # none verified
check("get_announcements returns announcements", len(store.get_announcements()) == 1)
check("get_alerts returns empty (no alerts)", len(store.get_alerts()) == 0)
check("get_node_statuses returns empty", len(store.get_node_statuses()) == 0)

# Add a node status
msg_ns = ShareMessage(MSG_NODE_STATUS, b'{"v":"1.0"}')
store.add_local_message(msg_ns)
check("get_node_statuses after add", len(store.get_node_statuses()) == 1)

# Stats
stats = store.stats
check("stats total_messages", stats['total_messages'] == 3)
check("stats unique_senders", stats['unique_senders'] >= 1)
check("stats by_type has MINER_MESSAGE", 'MINER_MESSAGE' in stats['by_type'])
check("stats signed_count", isinstance(stats['signed_count'], int))
check("stats verified_count", isinstance(stats['verified_count'], int))
check("stats has key_registry", 'key_registry' in stats)

# to_json
json_msgs = store.to_json()
check("to_json returns list", isinstance(json_msgs, list))
check("to_json length matches", len(json_msgs) == 3)

# Pruning: expired messages
store_prune = ShareMessageStore(max_messages=100, max_age=10)
msg_old = ShareMessage(MSG_MINER_MESSAGE, b'old message',
                       timestamp=int(time.time()) - 20)
added_old = store_prune.add_local_message(msg_old)
check("expired message rejected on add", added_old is False)

# Pruning: max messages
store_small = ShareMessageStore(max_messages=3, max_age=86400)
for i in range(5):
    m = ShareMessage(MSG_MINER_MESSAGE, ('msg %d' % i).encode('utf-8'),
                     timestamp=int(time.time()) + i)
    store_small.add_local_message(m)
check("max_messages enforced", len(store_small.messages) <= 3)

# add_local_message with sender override
msg_override = ShareMessage(MSG_MINER_MESSAGE, b'override sender')
store.add_local_message(msg_override, sender_address='custom_sender')
check("sender override works",
      any(m.sender_address == 'custom_sender' for m in store.messages))

section_end()


# ============================================================================
# 10. Message Builders
# ============================================================================

section("10. Message Builders")

# build_node_status
ns = build_node_status('13.4', 3600, 1500000, 8640, 3,
                       merged_chains=['DOGE'], capabilities=['v36', 'mm'])
check("build_node_status type", ns.msg_type == MSG_NODE_STATUS)
check("build_node_status flags broadcast only",
      ns.flags == FLAG_BROADCAST)
payload_ns = json.loads(ns.payload)
check("node_status has version", payload_ns['v'] == '13.4')
check("node_status has uptime", payload_ns['up'] == 3600)
check("node_status has hashrate", payload_ns['hr'] == 1500000)
check("node_status has share_count", payload_ns['sc'] == 8640)
check("node_status has peers", payload_ns['p'] == 3)
check("node_status has merged_chains", payload_ns['mc'] == ['DOGE'])
check("node_status has capabilities", payload_ns['cap'] == ['v36', 'mm'])

# build_node_status without optional fields
ns_min = build_node_status('1.0', 0, 0, 0, 0)
payload_min = json.loads(ns_min.payload)
check("node_status minimal has no mc", 'mc' not in payload_min)
check("node_status minimal has no cap", 'cap' not in payload_min)

# build_miner_message
mm = build_miner_message('Hello world')
check("build_miner_message type", mm.msg_type == MSG_MINER_MESSAGE)
check("build_miner_message payload", mm.payload == b'Hello world')
check("build_miner_message flags",
      mm.flags == (FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT))

# build_miner_message truncation
long_text = 'A' * 300
mm_long = build_miner_message(long_text)
check("build_miner_message truncates to MAX",
      len(mm_long.payload) == MAX_MESSAGE_PAYLOAD)

# build_pool_announcement
pa = build_pool_announcement('Maintenance tonight')
check("build_pool_announcement type", pa.msg_type == MSG_POOL_ANNOUNCE)
check("build_pool_announcement payload", pa.payload == b'Maintenance tonight')
check("build_pool_announcement flags signed+broadcast+persistent",
      pa.flags == (FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT))

# build_merged_status
ms = build_merged_status('Dogecoin', 'DOGE', 5000000, 10000.0, blocks_found=3)
check("build_merged_status type", ms.msg_type == MSG_MERGED_STATUS)
payload_ms = json.loads(ms.payload)
check("merged_status chain", payload_ms['chain'] == 'Dogecoin')
check("merged_status sym", payload_ms['sym'] == 'DOGE')
check("merged_status height", payload_ms['h'] == 5000000)
check("merged_status block_value", payload_ms['bv'] == 10000.0)
check("merged_status blocks_found", payload_ms['bf'] == 3)

# build_version_signal
vs = build_version_signal(36, ['mm', 'segwit', 'mweb'], extra={'proto': 3600})
check("build_version_signal type", vs.msg_type == MSG_VERSION_SIGNAL)
payload_vs = json.loads(vs.payload)
check("version_signal ver", payload_vs['ver'] == 36)
check("version_signal feat", payload_vs['feat'] == ['mm', 'segwit', 'mweb'])
check("version_signal extra proto", payload_vs['proto'] == 3600)

# build_emergency_alert
ea = build_emergency_alert('CRITICAL: Upgrade NOW!')
check("build_emergency_alert type", ea.msg_type == MSG_EMERGENCY)
check("build_emergency_alert payload", ea.payload == b'CRITICAL: Upgrade NOW!')

# build_transition_signal
ts = build_transition_signal(
    current_version=36,
    target_version=37,
    message='Upgrade to v37 for MWEB support',
    urgency='recommended',
    upgrade_url='https://github.com/frstrtr/p2pool-merged-v36/releases',
    activation_threshold=95,
    extra={'deadline': 1700000000},
)
check("build_transition_signal type", ts.msg_type == MSG_TRANSITION_SIGNAL)
payload_ts = json.loads(ts.payload)
check("transition_signal from", payload_ts['from'] == 36)
check("transition_signal to", payload_ts['to'] == 37)
check("transition_signal msg", payload_ts['msg'] == 'Upgrade to v37 for MWEB support')
check("transition_signal urg", payload_ts['urg'] == 'recommended')
check("transition_signal url", 'url' in payload_ts)
check("transition_signal thr", payload_ts['thr'] == 95)
check("transition_signal extra deadline", payload_ts['deadline'] == 1700000000)
check("transition_signal has PROTOCOL_AUTHORITY flag",
      ts.flags & FLAG_PROTOCOL_AUTHORITY)

# build_transition_signal without optional fields
ts_min = build_transition_signal(36, 37, 'Upgrade', urgency='info')
payload_ts_min = json.loads(ts_min.payload)
check("transition_signal minimal no url", 'url' not in payload_ts_min)
check("transition_signal minimal no thr", 'thr' not in payload_ts_min)

# build_transition_signal invalid urgency
check_raises("transition_signal invalid urgency -> AssertionError",
             lambda: build_transition_signal(36, 37, 'test', urgency='wrong'),
             AssertionError)

# build_transition_signal oversized payload
check_raises("transition_signal oversized payload",
             lambda: build_transition_signal(36, 37, 'X' * 500, urgency='info'),
             ValueError)

section_end()


# ============================================================================
# 11. Message Weight Units (MWU) Budget
# ============================================================================

section("11. Message Weight Units Budget Calculations")

# Test MWU calculations as documented
# MWU of a message = MWU_HEADER + (payload_len * MWU_PER_PAYLOAD_BYTE) +
#                     (sig_len * MWU_PER_SIGNATURE_BYTE)

def calc_mwu(msg):
    """Calculate MWU for a message (as spec'd in constants)."""
    mwu = MWU_HEADER
    mwu += len(msg.payload) * MWU_PER_PAYLOAD_BYTE
    if msg.signature:
        mwu += len(msg.signature) * MWU_PER_SIGNATURE_BYTE
    return mwu

# Small status message within free allowance
small_msg = ShareMessage(MSG_NODE_STATUS, b'{"v":"1"}')
mwu_small = calc_mwu(small_msg)
check("small status MWU = header + payload",
      mwu_small == MWU_HEADER + len(small_msg.payload))
check("small status within free allowance",
      mwu_small <= FREE_MWU_ALLOWANCE)

# Signed message with typical 72-byte DER signature
typical_signed = ShareMessage(MSG_MINER_MESSAGE, b'Hello world')
typical_signed.signature = b'\x00' * 72
mwu_signed = calc_mwu(typical_signed)
expected_mwu = MWU_HEADER + 11 + (72 * MWU_PER_SIGNATURE_BYTE)
check("signed message MWU calculation",
      mwu_signed == expected_mwu,
      "got %d, expected %d" % (mwu_signed, expected_mwu))

# Max payload message
max_msg = ShareMessage(MSG_MINER_MESSAGE, b'X' * MAX_MESSAGE_PAYLOAD)
max_msg.signature = b'\x00' * 73
mwu_max = calc_mwu(max_msg)
check("max message MWU = %d" % mwu_max, mwu_max > 0)
check("max message MWU exceeds free allowance", mwu_max > FREE_MWU_ALLOWANCE)

# Announcement MWU (constant)
check("MWU_ANNOUNCEMENT == 57 * 3", MWU_ANNOUNCEMENT == 57 * 3)

# Multiple messages per share budget
three_small = [ShareMessage(MSG_NODE_STATUS, b'{"v":"1"}') for _ in range(3)]
total_mwu = sum(calc_mwu(m) for m in three_small)
check("3 small messages within per-share budget",
      total_mwu <= MAX_MWU_PER_SHARE)

section_end()


# ============================================================================
# 12. Wire Format Edge Cases
# ============================================================================

section("12. Wire Format Edge Cases")

# Empty payload message pack/unpack
msg_empty = ShareMessage(MSG_NODE_STATUS, b'', timestamp=1700000000)
packed_empty = msg_empty.pack()
msg_empty_up, off_empty = ShareMessage.unpack(packed_empty)
check("empty payload pack/unpack", msg_empty_up.payload == b'')
check("empty payload type preserved", msg_empty_up.msg_type == MSG_NODE_STATUS)

# Max payload pack/unpack
msg_max = ShareMessage(MSG_MINER_MESSAGE,
                       b'M' * MAX_MESSAGE_PAYLOAD, timestamp=1700000000)
packed_max = msg_max.pack()
msg_max_up, off_max = ShareMessage.unpack(packed_max)
check("max payload pack/unpack preserved",
      len(msg_max_up.payload) == MAX_MESSAGE_PAYLOAD)
check("max payload content preserved", msg_max_up.payload == b'M' * MAX_MESSAGE_PAYLOAD)

# All message types pack/unpack
for mt, mt_name in MESSAGE_TYPE_NAMES.items():
    m = ShareMessage(mt, b'test payload', timestamp=1700000000)
    p = m.pack()
    mu, _ = ShareMessage.unpack(p)
    check("type 0x%02x (%s) roundtrip" % (mt, mt_name), mu.msg_type == mt)

# Multiple messages concatenated
msg_a = ShareMessage(MSG_MINER_MESSAGE, b'first', timestamp=1700000000)
msg_b = ShareMessage(MSG_POOL_ANNOUNCE, b'second', timestamp=1700000001)
packed_concat = msg_a.pack() + msg_b.pack()
m_a, off_a = ShareMessage.unpack(packed_concat, 0)
m_b, off_b = ShareMessage.unpack(packed_concat, off_a)
check("concatenated unpack first msg", m_a.payload == b'first')
check("concatenated unpack second msg", m_b.payload == b'second')
check("concatenated offset at end", off_b == len(packed_concat))

# All flags combinations
for flags in [0, FLAG_HAS_SIGNATURE, FLAG_BROADCAST, FLAG_PERSISTENT,
              FLAG_BROADCAST | FLAG_PERSISTENT,
              FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT]:
    m = ShareMessage(MSG_MINER_MESSAGE, b'flags test', flags=flags,
                     timestamp=1700000000)
    p = m.pack()
    mu, _ = ShareMessage.unpack(p)
    expected_flags = flags & ~FLAG_PROTOCOL_AUTHORITY
    check("flags 0x%02x roundtrip" % flags, mu.flags == expected_flags)

# FLAG_PROTOCOL_AUTHORITY stripped on unpack
msg_pa = ShareMessage(MSG_MINER_MESSAGE, b'test',
                      flags=FLAG_PROTOCOL_AUTHORITY | FLAG_BROADCAST,
                      timestamp=1700000000)
packed_pa = msg_pa.pack()
msg_pa_up, _ = ShareMessage.unpack(packed_pa)
check("PROTOCOL_AUTHORITY stripped on unpack",
      not (msg_pa_up.flags & FLAG_PROTOCOL_AUTHORITY))

# Binary payload with all byte values
all_bytes = b''.join(chr(i) for i in range(220))
msg_bin = ShareMessage(MSG_MINER_MESSAGE, all_bytes, timestamp=1700000000)
packed_bin = msg_bin.pack()
msg_bin_up, _ = ShareMessage.unpack(packed_bin)
check("binary payload all 220 byte values preserved",
      msg_bin_up.payload == all_bytes)

section_end()


# ============================================================================
# 13. SigningKeyRegistry Advanced Scenarios
# ============================================================================

section("13. SigningKeyRegistry Advanced Scenarios")

reg_adv = SigningKeyRegistry()

# Register 3 different miners
keys = []
for i in range(3):
    master = hashlib.sha256(('miner-%d-master-key' % i).encode('utf-8')).digest()
    dk = DerivedSigningKey(master, key_index=0)
    ann = dk.get_announcement()
    reg_adv.register_key(
        miner_address='miner_%d' % i,
        signing_id=ann['signing_id'],
        key_index=0,
        signing_pubkey=ann['signing_pubkey'],
    )
    keys.append((master, dk, ann))

check("3 miners registered", len(reg_adv.keys) == 3)

# All keys valid
for i, (_, dk, ann) in enumerate(keys):
    check("miner_%d key valid" % i, reg_adv.is_key_valid(ann['signing_id']))

# Rotate miner_0 through multiple indexes
for idx in range(1, 5):
    dk_new = DerivedSigningKey(keys[0][0], key_index=idx)
    ann_new = dk_new.get_announcement()
    reg_adv.register_key(
        miner_address='miner_0',
        signing_id=ann_new['signing_id'],
        key_index=idx,
        signing_pubkey=ann_new['signing_pubkey'],
    )

# Only latest key should be valid
current_0 = reg_adv.get_miner_current_key('miner_0')
check("miner_0 current key_index == 4", current_0['key_index'] == 4)
check("miner_0 old key_index=0 revoked",
      not reg_adv.is_key_valid(keys[0][2]['signing_id']))

# Other miners unaffected
check("miner_1 still valid", reg_adv.is_key_valid(keys[1][2]['signing_id']))
check("miner_2 still valid", reg_adv.is_key_valid(keys[2][2]['signing_id']))

# JSON serialization has all data
j = reg_adv.to_json()
check("JSON has miner_0", 'miner_0' in j)
check("miner_0 current_key_index == 4", j['miner_0']['current_key_index'] == 4)
check("miner_0 has 5 keys total", len(j['miner_0']['keys']) == 5)

# Register a lower key_index after a higher one (does not un-revoke)
dk_old = DerivedSigningKey(keys[0][0], key_index=2)
ann_old = dk_old.get_announcement()
reg_adv.register_key(
    miner_address='miner_0',
    signing_id=ann_old['signing_id'],
    key_index=2,
    signing_pubkey=ann_old['signing_pubkey'],
)
check("re-registered old key_index=2 still revoked (lower than current 4)",
      not reg_adv.is_key_valid(ann_old['signing_id']))

section_end()


# ============================================================================
# 14. ShareMessageStore Advanced
# ============================================================================

section("14. ShareMessageStore Advanced")

# Ordering: newest first
store_order = ShareMessageStore(max_messages=100, max_age=86400)
now = int(time.time())
for i in range(5):
    m = ShareMessage(MSG_MINER_MESSAGE, ('order %d' % i).encode('utf-8'),
                     timestamp=now + i)
    store_order.add_local_message(m)

check("store ordered newest first",
      store_order.messages[0].timestamp >= store_order.messages[-1].timestamp)

# Verified-only filter
store_ver = ShareMessageStore()
msg_ver = ShareMessage(MSG_MINER_MESSAGE, b'verified msg', timestamp=now)
msg_ver.verified = True
msg_ver.sender_address = 'verified_miner'
store_ver._add_message(msg_ver)

msg_unver = ShareMessage(MSG_POOL_ANNOUNCE, b'unverified', timestamp=now + 1)
store_ver._add_message(msg_unver)

check("verified_only filter", len(store_ver.get_messages(verified_only=True)) == 1)
check("verified message is the right one",
      store_ver.get_messages(verified_only=True)[0].payload == b'verified msg')

# Combined filters: type + sender + verified
store_filter = ShareMessageStore()
for i in range(10):
    m = ShareMessage(
        MSG_MINER_MESSAGE if i % 2 == 0 else MSG_POOL_ANNOUNCE,
        ('filter %d' % i).encode('utf-8'),
        timestamp=now + i,
    )
    m.sender_address = 'alice' if i < 5 else 'bob'
    m.verified = (i % 3 == 0)
    store_filter._add_message(m)

alice_miner = store_filter.get_messages(msg_type=MSG_MINER_MESSAGE, sender='alice')
check("combined filter: alice miner messages",
      all(m.sender_address == 'alice' and m.msg_type == MSG_MINER_MESSAGE
          for m in alice_miner))

alice_verified = store_filter.get_messages(sender='alice', verified_only=True)
check("combined filter: alice verified",
      all(m.sender_address == 'alice' and m.verified for m in alice_verified))

# Key registry integration in store
store_kr = ShareMessageStore()
check("store has key_registry", isinstance(store_kr.key_registry, SigningKeyRegistry))

section_end()


# ============================================================================
# 15. DerivedSigningKey Signing Roundtrip with Registry
# ============================================================================

section("15. Full Sign+Verify Roundtrip via Registry")

# Create a key, sign a message, register the key, verify
master = hashlib.sha256(b'roundtrip-master-key').digest()
dk = DerivedSigningKey(master, key_index=0)

msg_rt = ShareMessage(MSG_MINER_MESSAGE, b'Roundtrip test message',
                      timestamp=1700000000)
msg_rt.sign(dk)

check("signed message has FLAG_HAS_SIGNATURE", msg_rt.has_signature)
check("signed message has signing_id", msg_rt.signing_id == dk.signing_id)
check("signed message has non-empty sig", len(msg_rt.signature) > 0)

# Pack and unpack (simulates network transfer)
packed_rt = msg_rt.pack()
msg_received, _ = ShareMessage.unpack(packed_rt)

# Register the signing key in a fresh registry
reg_rt = SigningKeyRegistry()
ann_rt = dk.get_announcement()
reg_rt.register_key('roundtrip_miner', ann_rt['signing_id'],
                    ann_rt['key_index'], ann_rt['signing_pubkey'])

# Verify the received message
result_rt = msg_received.verify(reg_rt)
check("received message verifies True", result_rt is True)
check("received message verified flag", msg_received.verified is True)
check("received message sender_address set",
      msg_received.sender_address == 'roundtrip_miner')

# Tamper with payload after signing -> verification fails
msg_tampered = ShareMessage(MSG_MINER_MESSAGE, b'TAMPERED message',
                            flags=msg_rt.flags, timestamp=msg_rt.timestamp)
msg_tampered.signing_id = msg_rt.signing_id
msg_tampered.signature = msg_rt.signature  # copy original sig
result_tampered = msg_tampered.verify(reg_rt)
check("tampered payload -> verify False", result_tampered is False)

# Tamper with timestamp -> different hash -> verify fails
msg_ts_tamper = ShareMessage(MSG_MINER_MESSAGE, b'Roundtrip test message',
                             flags=msg_rt.flags, timestamp=1700000001)
msg_ts_tamper.signing_id = msg_rt.signing_id
msg_ts_tamper.signature = msg_rt.signature
result_ts = msg_ts_tamper.verify(reg_rt)
check("tampered timestamp -> verify False", result_ts is False)

# Verify after key rotation -> should fail
dk_rotated = DerivedSigningKey(master, key_index=1)
ann_rot2 = dk_rotated.get_announcement()
reg_rt.register_key('roundtrip_miner', ann_rot2['signing_id'],
                    ann_rot2['key_index'], ann_rot2['signing_pubkey'])
msg_old_key = ShareMessage(MSG_MINER_MESSAGE, b'old key msg',
                           timestamp=1700000000)
msg_old_key.sign(dk)  # sign with old key (key_index=0)
result_old = msg_old_key.verify(reg_rt)
check("message signed with rotated-out key -> False", result_old is False)

# Sign with new key -> works
msg_new_key = ShareMessage(MSG_MINER_MESSAGE, b'new key msg',
                           timestamp=1700000000)
msg_new_key.sign(dk_rotated)
result_new = msg_new_key.verify(reg_rt)
check("message signed with current key -> True", result_new is True)

section_end()


# ============================================================================
# 16. Encryption/Decryption Edge Cases
# ============================================================================

section("16. Encryption/Decryption Edge Cases")

# Single byte plaintext
enc1 = encrypt_message_data(b'\x42', DONATION_PUBKEY_FORRESTV)
dec1, key1 = decrypt_message_data(enc1)
check("single byte encrypt/decrypt", dec1 == b'\x42')

# Large-ish plaintext (close to MAX_TOTAL_MESSAGE_BYTES)
large_plain = b'\xAB' * 500
enc_large = encrypt_message_data(large_plain, DONATION_PUBKEY_FORRESTV)
dec_large, key_large = decrypt_message_data(enc_large)
check("large plaintext encrypt/decrypt", dec_large == large_plain)

# All zero bytes
zero_plain = b'\x00' * 100
enc_zero = encrypt_message_data(zero_plain, DONATION_PUBKEY_FORRESTV)
dec_zero, _ = decrypt_message_data(enc_zero)
check("all-zero plaintext roundtrip", dec_zero == zero_plain)

# Verify each authority key independently
for pubkey in DONATION_AUTHORITY_PUBKEYS:
    enc = encrypt_message_data(b'authority test', pubkey)
    dec, auth = decrypt_message_data(enc)
    check("authority key %s... roundtrip" % pubkey[:4].encode('hex'),
          dec == b'authority test' and auth == pubkey)

# Ciphertext is actually encrypted (not plaintext)
enc_check = encrypt_message_data(b'VISIBLE PLAINTEXT', DONATION_PUBKEY_FORRESTV)
check("ciphertext does not contain plaintext",
      b'VISIBLE PLAINTEXT' not in enc_check)

section_end()


# ============================================================================
# 17. Announcement Pack/Unpack Edge Cases
# ============================================================================

section("17. Announcement Pack/Unpack Edge Cases")

# Pack and unpack multiple key indexes
for idx in range(5):
    dk_idx = DerivedSigningKey(TEST_MASTER_KEY, key_index=idx)
    packed = dk_idx.pack_announcement()
    sid, ki, spk, consumed = DerivedSigningKey.unpack_announcement(packed)
    check("key_index=%d pack/unpack" % idx,
          sid == dk_idx.signing_id and ki == idx)

# Large key_index (near uint32 max)
dk_large_idx = DerivedSigningKey(TEST_MASTER_KEY, key_index=0xFFFFFFFE)
packed_li = dk_large_idx.pack_announcement()
sid_li, ki_li, _, _ = DerivedSigningKey.unpack_announcement(packed_li)
check("large key_index pack/unpack", ki_li == 0xFFFFFFFE)

# Announcement with trailing data (should only consume 57 bytes)
trailing = dk_large_idx.pack_announcement() + b'\xFF' * 100
sid_t, ki_t, spk_t, cons_t = DerivedSigningKey.unpack_announcement(trailing)
check("trailing data ignored", cons_t == 57)
check("trailing: correct signing_id", sid_t == dk_large_idx.signing_id)

# Exact 57 bytes (no more, no less)
check("exactly 57 bytes works",
      DerivedSigningKey.unpack_announcement(dk_large_idx.pack_announcement())[0] is not None)

# 56 bytes -> failure
check("56 bytes -> None",
      DerivedSigningKey.unpack_announcement(b'\x00' * 56)[0] is None)

section_end()


# ============================================================================
# 18. BanList
# ============================================================================

section("18. BanList")

# Basic creation (no persistence)
bl = BanList()
check("BanList created", bl is not None)
check("empty lists", len(bl.banned_signing_ids) == 0
      and len(bl.banned_addresses) == 0
      and len(bl.banned_keywords) == 0
      and len(bl.banned_types) == 0)

# Ban signing_id
bl.ban_signing_id('abcdef0123456789')
check("ban signing_id added", 'abcdef0123456789' in bl.banned_signing_ids)

# Ban address
bl.ban_address('LSpammer123')
check("ban address added", 'LSpammer123' in bl.banned_addresses)

# Ban keyword
bl.ban_keyword('SCAM')
check("ban keyword added (lowercased)", 'scam' in bl.banned_keywords)

# Ban type
bl.ban_type(MSG_MINER_MESSAGE)
check("ban type added", MSG_MINER_MESSAGE in bl.banned_types)

# is_banned: check by type
msg_chat = ShareMessage(MSG_MINER_MESSAGE, b'hello', sender_address='good_miner')
check("msg banned by type", bl.is_banned(msg_chat))

# is_banned: check by address
msg_from_spammer = ShareMessage(MSG_POOL_ANNOUNCE, b'legit text',
                                sender_address='LSpammer123')
check("msg banned by address", bl.is_banned(msg_from_spammer))

# is_banned: check by keyword
msg_scam = ShareMessage(MSG_POOL_ANNOUNCE, b'This is a SCAM alert',
                        sender_address='good_miner')
check("msg banned by keyword (case-insensitive)", bl.is_banned(msg_scam))

# is_banned: signing_id match
msg_sid = ShareMessage(MSG_POOL_ANNOUNCE, b'message body',
                       sender_address='other_miner')
msg_sid.signing_id = 'abcdef0123456789'.decode('hex')
check("msg banned by signing_id", bl.is_banned(msg_sid))

# is_banned: authority messages NEVER banned
msg_authority = ShareMessage(MSG_EMERGENCY, b'SCAM word here',
                             flags=FLAG_PROTOCOL_AUTHORITY | FLAG_BROADCAST,
                             sender_address='LSpammer123')
check("authority msg NOT banned despite keyword+address",
      not bl.is_banned(msg_authority))

# is_banned: clean message not banned
msg_clean = ShareMessage(MSG_POOL_ANNOUNCE, b'nothing wrong here',
                         sender_address='clean_miner')
check("clean message not banned", not bl.is_banned(msg_clean))

# Unban
bl.unban_type(MSG_MINER_MESSAGE)
check("unban type", MSG_MINER_MESSAGE not in bl.banned_types)
check("chat msg no longer banned by type", not bl.is_banned(msg_chat))

bl.unban_address('LSpammer123')
check("unban address", 'LSpammer123' not in bl.banned_addresses)

bl.unban_keyword('SCAM')
check("unban keyword", 'scam' not in bl.banned_keywords)

bl.unban_signing_id('abcdef0123456789')
check("unban signing_id", 'abcdef0123456789' not in bl.banned_signing_ids)

# to_json
bl2 = BanList()
bl2.ban_address('addr1')
bl2.ban_keyword('spam')
bl2.ban_type(MSG_EMERGENCY)
j = bl2.to_json()
check("to_json has addresses", 'addr1' in j['addresses'])
check("to_json has keywords", 'spam' in j['keywords'])
check("to_json has types", MSG_EMERGENCY in j['types'])
check("to_json has type_names", 'EMERGENCY' in j['type_names'])

# Persistence roundtrip
import tempfile
tmp = tempfile.mktemp(suffix='.json')
try:
    bl_persist = BanList(persist_path=tmp)
    bl_persist.ban_address('persist_addr')
    bl_persist.ban_keyword('persist_word')
    bl_persist.ban_type(MSG_MINER_MESSAGE)
    bl_persist.ban_signing_id('deadbeef' * 4)

    # Load into fresh BanList
    bl_loaded = BanList(persist_path=tmp)
    check("persistence: address", 'persist_addr' in bl_loaded.banned_addresses)
    check("persistence: keyword", 'persist_word' in bl_loaded.banned_keywords)
    check("persistence: type", MSG_MINER_MESSAGE in bl_loaded.banned_types)
    check("persistence: signing_id", 'deadbeef' * 4 in bl_loaded.banned_signing_ids)
finally:
    try:
        os.remove(tmp)
    except OSError:
        pass

section_end()


# ============================================================================
# 19. ShareMessageStore with BanList Integration
# ============================================================================

section("19. ShareMessageStore + BanList")

bl_store = BanList()
bl_store.ban_keyword('blocked')
bl_store.ban_address('banned_miner')

store_bl = ShareMessageStore(ban_list=bl_store)

# Add messages
msg_ok = ShareMessage(MSG_MINER_MESSAGE, b'hello world', sender_address='good')
msg_blocked = ShareMessage(MSG_MINER_MESSAGE, b'this is blocked content',
                           sender_address='good', timestamp=int(time.time()) + 1)
msg_banned_addr = ShareMessage(MSG_POOL_ANNOUNCE, b'legit content',
                               sender_address='banned_miner',
                               timestamp=int(time.time()) + 2)
msg_auth = ShareMessage(MSG_EMERGENCY, b'blocked keyword authority',
                        flags=FLAG_PROTOCOL_AUTHORITY | FLAG_BROADCAST,
                        sender_address='banned_miner',
                        timestamp=int(time.time()) + 3)

for m in [msg_ok, msg_blocked, msg_banned_addr, msg_auth]:
    store_bl.add_local_message(m)

check("store has 4 messages total", len(store_bl.messages) == 4)

# get_messages with bans applied (default)
filtered = store_bl.get_messages()
check("filtered: 2 messages visible (ok + authority)", len(filtered) == 2)
check("filtered: clean msg present",
      any(m.payload == b'hello world' for m in filtered))
check("filtered: authority msg present despite ban match",
      any(m.payload == b'blocked keyword authority' for m in filtered))
check("filtered: blocked content hidden",
      not any(m.payload == b'this is blocked content' for m in filtered))
check("filtered: banned address hidden",
      not any(m.sender_address == 'banned_miner' and
              not (m.flags & FLAG_PROTOCOL_AUTHORITY) for m in filtered))

# get_messages with bans disabled
unfiltered = store_bl.get_messages(apply_bans=False)
check("unfiltered: all 4 visible", len(unfiltered) == 4)

section_end()


# ============================================================================
# 20. ShareMessageStore Sharechain-Aware Pruning
# ============================================================================

section("20. Sharechain-Aware Pruning")

store_chain = ShareMessageStore()
now = int(time.time())

# Add messages tied to specific share hashes
for i in range(5):
    m = ShareMessage(MSG_MINER_MESSAGE, ('share msg %d' % i).encode('utf-8'),
                     timestamp=now + i)
    m.share_hash = 0x1000 + i
    m.sender_address = 'miner_%d' % i
    store_chain._add_message(m)

check("5 messages in store", len(store_chain.messages) == 5)
check("5 share hashes tracked", len(store_chain._share_messages) == 5)

# Prune: keep only shares 0x1000, 0x1001, 0x1002 in active chain
active = set([0x1000, 0x1001, 0x1002])
store_chain.prune_by_sharechain(active)

check("3 messages remain after prune", len(store_chain.messages) == 3)
check("pruned shares removed from index",
      0x1003 not in store_chain._share_messages
      and 0x1004 not in store_chain._share_messages)
check("active shares kept",
      0x1000 in store_chain._share_messages
      and 0x1001 in store_chain._share_messages
      and 0x1002 in store_chain._share_messages)

# Authority messages survive sharechain pruning
store_auth = ShareMessageStore()
msg_auth_chain = ShareMessage(MSG_EMERGENCY, b'authority alert',
                              flags=FLAG_PROTOCOL_AUTHORITY | FLAG_BROADCAST,
                              timestamp=now)
msg_auth_chain.share_hash = 0x2000
msg_auth_chain.sender_address = 'authority'
store_auth._add_message(msg_auth_chain)

msg_regular = ShareMessage(MSG_MINER_MESSAGE, b'regular msg',
                           timestamp=now + 1)
msg_regular.share_hash = 0x2001
msg_regular.sender_address = 'miner'
store_auth._add_message(msg_regular)

check("2 msgs before authority prune", len(store_auth.messages) == 2)
check("authority msg in authority_messages list",
      len(store_auth.authority_messages) == 1)

# Prune both shares out of active chain
store_auth.prune_by_sharechain(set([0x9999]))  # neither share is active

check("authority msg survives sharechain prune",
      any(m.payload == b'authority alert' for m in store_auth.messages))
check("regular msg pruned",
      not any(m.payload == b'regular msg' for m in store_auth.messages))

section_end()


# ============================================================================
# 21. ShareMessageStore Stats with New Fields
# ============================================================================

section("21. ShareMessageStore Enhanced Stats")

bl_stats = BanList()
bl_stats.ban_keyword('test')
store_stats = ShareMessageStore(ban_list=bl_stats)

msg_s1 = ShareMessage(MSG_MINER_MESSAGE, b'stats msg 1', timestamp=now)
msg_s1.share_hash = 0x3000
store_stats._add_message(msg_s1)

msg_s2 = ShareMessage(MSG_EMERGENCY, b'authority stats',
                       flags=FLAG_PROTOCOL_AUTHORITY | FLAG_BROADCAST,
                       timestamp=now + 1)
msg_s2.share_hash = 0x3001
store_stats._add_message(msg_s2)

stats = store_stats.stats
check("stats has authority_messages", 'authority_messages' in stats)
check("stats authority_messages == 1", stats['authority_messages'] == 1)
check("stats has tracked_shares", 'tracked_shares' in stats)
check("stats tracked_shares == 2", stats['tracked_shares'] == 2)
check("stats has ban_list", 'ban_list' in stats)
check("stats ban_list has keywords",
      'test' in stats['ban_list']['keywords'])

section_end()


# ============================================================================
# 20. Default Display Policy (authority_only filter)
# ============================================================================

section("20. Default Display Policy (authority_only)")

store_policy = ShareMessageStore()
now = int(time.time())

# Add a regular (non-authority) miner message
msg_regular = ShareMessage(MSG_MINER_MESSAGE, b'hello from miner',
                           timestamp=now, sender_address='regular_miner')
store_policy.add_local_message(msg_regular)

# Add an authority message (simulate FLAG_PROTOCOL_AUTHORITY)
msg_authority = ShareMessage(MSG_EMERGENCY, b'URGENT: upgrade now',
                             flags=FLAG_BROADCAST | FLAG_PERSISTENT | FLAG_PROTOCOL_AUTHORITY,
                             timestamp=now + 1, sender_address='authority')
store_policy.add_local_message(msg_authority)

# Add a pool announcement (non-authority)
msg_announce = ShareMessage(MSG_POOL_ANNOUNCE, b'Pool maintenance',
                            timestamp=now + 2, sender_address='pool_op')
store_policy.add_local_message(msg_announce)

# Add a node status (non-authority)
msg_status = ShareMessage(MSG_NODE_STATUS, b'{"v":"1.0"}',
                          timestamp=now + 3, sender_address='node1')
store_policy.add_local_message(msg_status)

check("store has 4 messages total", len(store_policy.messages) == 4)

# authority_only=False returns all messages
all_msgs = store_policy.get_messages(authority_only=False)
check("authority_only=False returns all 4", len(all_msgs) == 4)

# authority_only=True returns only authority messages
auth_msgs = store_policy.get_messages(authority_only=True)
check("authority_only=True returns 1", len(auth_msgs) == 1)
check("authority message is the EMERGENCY",
      auth_msgs[0].msg_type == MSG_EMERGENCY)
check("authority message has correct payload",
      auth_msgs[0].payload == b'URGENT: upgrade now')

# authority_only + msg_type filter
auth_emerg = store_policy.get_messages(authority_only=True, msg_type=MSG_EMERGENCY)
check("authority_only + EMERGENCY filter", len(auth_emerg) == 1)

auth_miner = store_policy.get_messages(authority_only=True, msg_type=MSG_MINER_MESSAGE)
check("authority_only + MINER_MESSAGE filter -> empty", len(auth_miner) == 0)

# Default behavior: without authority_only, all messages returned
default_msgs = store_policy.get_messages()
check("default (no authority_only) returns all", len(default_msgs) == 4)

# Non-authority alerts should NOT appear with authority_only
msg_nonauth_alert = ShareMessage(MSG_EMERGENCY, b'fake alert',
                                 flags=FLAG_BROADCAST,
                                 timestamp=now + 4, sender_address='faker')
store_policy.add_local_message(msg_nonauth_alert)

auth_alerts = store_policy.get_messages(authority_only=True, msg_type=MSG_EMERGENCY)
check("non-authority EMERGENCY hidden with authority_only",
      len(auth_alerts) == 1)
check("only real authority alert shown",
      auth_alerts[0].payload == b'URGENT: upgrade now')

# All alerts without authority_only
all_alerts = store_policy.get_messages(authority_only=False, msg_type=MSG_EMERGENCY)
check("all EMERGENCY without authority_only returns 2", len(all_alerts) == 2)

section_end()


# ============================================================================
# Summary
# ============================================================================

print("\n" + "=" * 70)
print("SHARE MESSAGING TEST SUITE COMPLETE")
print("=" * 70)
print("  Total: %d passed, %d failed, %d skipped" % (passed, failed, skipped))

if failed > 0:
    print("\n  *** %d TEST(S) FAILED ***" % failed)
    sys.exit(1)
else:
    print("\n  All tests passed!")
    sys.exit(0)
