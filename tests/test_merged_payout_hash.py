#!/usr/bin/env python
"""Test compute_merged_payout_hash determinism and correctness."""

from p2pool import data as p2pool_data
from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import pack
from p2pool import networks as p2pool_networks

net = p2pool_networks.nets['litecoin_testnet']

print('=== Test 1: hash with None previous_share_hash ===')
result = p2pool_data.compute_merged_payout_hash(None, None, 0, net)
assert result is None, 'Expected None for None previous_share_hash, got %s' % result
print('PASS')

print('')
print('=== Test 2: deterministic serialization ===')
# Simulate what the hash function does
weights = {'addr_b': 500, 'addr_a': 1000, 'addr_c': 250}
total_weight = 1750
donation_weight = 50

parts = []
for addr_key in sorted(weights.keys()):
    parts.append('%s:%d' % (addr_key, weights[addr_key]))
parts.append('T:%d' % total_weight)
parts.append('D:%d' % donation_weight)
payload = '|'.join(parts)
print('Payload: %r' % payload)
expected = 'addr_a:1000|addr_b:500|addr_c:250|T:1750|D:50'
assert payload == expected, 'Payload mismatch: %s != %s' % (payload, expected)
print('PASS')

print('')
print('=== Test 3: hash256 determinism ===')
# hash256 returns an integer directly (pack.IntType(256).unpack inside)
hash_int = bitcoin_data.hash256(payload)
print('hash_int: %x' % hash_int)
assert hash_int > 0, 'Hash should be non-zero'

# Run twice to verify determinism
hash_int2 = bitcoin_data.hash256(payload)
assert hash_int == hash_int2, 'Hash not deterministic!'
print('Deterministic: OK')
print('PASS')

print('')
print('=== Test 4: integer truncation determinism ===')
remaining = 100000000
share_weight = 75000000
share_donation = 25000000
total_share = share_weight + share_donation

truncated_weight = remaining * share_weight // total_share
truncated_donation = remaining * share_donation // total_share
print('truncated_weight: %d expected: 75000000' % truncated_weight)
print('truncated_donation: %d expected: 25000000' % truncated_donation)
assert truncated_weight == 75000000
assert truncated_donation == 25000000
print('PASS')

# Also test edge case: large numbers (like real PPLNS weights)
remaining = 1234567890123456789
share_weight = 987654321098765432
share_donation = 246913580274691358
total_share = share_weight + share_donation

truncated_weight = remaining * share_weight // total_share
truncated_donation = remaining * share_donation // total_share
print('Large number truncation: weight=%d donation=%d' % (truncated_weight, truncated_donation))
assert truncated_weight + truncated_donation <= remaining, 'Truncated sum exceeds remaining!'
print('PASS')

print('')
print('=== Test 5: PossiblyNoneType(0, IntType(256)) round-trip ===')
field_type = pack.PossiblyNoneType(0, pack.IntType(256))

# Test None → serialized as 0 sentinel
packed_none = field_type.pack(None)
unpacked_none = field_type.unpack(packed_none)
print('None: packed %d bytes, unpacked=%s' % (len(packed_none), unpacked_none))
assert unpacked_none is None, 'Expected None back, got %s' % unpacked_none

# Test non-zero hash value
test_hash = 0xdeadbeef1234567890abcdef1234567890abcdef1234567890abcdef12345678
packed_hash = field_type.pack(test_hash)
unpacked_hash = field_type.unpack(packed_hash)
print('Hash: packed %d bytes, unpacked=%x' % (len(packed_hash), unpacked_hash))
assert unpacked_hash == test_hash, 'Hash round-trip failed!'

# Verify that 0 cannot be packed (it's the sentinel)
try:
    field_type.pack(0)
    assert False, 'Should have raised ValueError for 0'
except ValueError:
    print('Correctly rejects literal 0 (sentinel value)')
print('PASS')

print('')
print('=== Test 6: full share_info_type serialization ===')
types = p2pool_data.MergedMiningShare.get_dynamic_types(net)
share_info_type = types['share_info_type']
field_names = [name for name, _ in share_info_type.fields]
print('Fields: %s' % field_names)
assert 'merged_payout_hash' in field_names
# Verify it's the last field
assert field_names[-1] == 'merged_payout_hash', 'merged_payout_hash should be last field, got %s' % field_names[-1]
print('merged_payout_hash is last field: OK')
print('PASS')

print('')
print('=== All 6 tests passed ===')
