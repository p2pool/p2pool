# VERSION 100 Implementation Plan

## Overview

Share VERSION 100 introduces a **merkle tree of trees** structure for multiple merged mining chains with per-miner multiaddress support. This is a major protocol upgrade.

## Current State (v1.4.0)

```
Share VERSION 17  → SUCCESSOR = PaddingBugfixShare (v35)
PreSegwitShare 32 → SUCCESSOR = PaddingBugfixShare (v35)
NewShare 33       → SUCCESSOR = PaddingBugfixShare (v35)
SegwitMiningShare 34 → SUCCESSOR = PaddingBugfixShare (v35)
PaddingBugfixShare 35 → SUCCESSOR = None  (current head)

MINIMUM_PROTOCOL_VERSION = 3500 (for v35 shares)
```

## Proposed Changes

### 1. New Share Class: MultiMergedShare (VERSION 100)

```python
class MultiMergedShare(BaseShare):
    VERSION = 100
    VOTING_VERSION = 100
    SUCCESSOR = None
    MINIMUM_PROTOCOL_VERSION = 3600  # Bump by 100, not 10000
```

### 2. Update Successor Chain

```python
PaddingBugfixShare.SUCCESSOR = MultiMergedShare
```

### 3. New share_info_type Structure

```python
# Current (VERSION 35):
share_data = {
    'previous_share_hash': ...,
    'coinbase': ...,
    'nonce': ...,
    'address': ...,        # Single parent chain address (string)
    'subsidy': ...,
    'donation': ...,
    'stale_info': ...,
    'desired_version': ...,
}

# Proposed (VERSION 100):
share_data = {
    'previous_share_hash': ...,
    'coinbase': ...,
    'nonce': ...,
    'address': ...,                    # Parent chain address (unchanged)
    'merged_addresses': {              # NEW: Per-chain addresses
        'dogecoin': 'D...',            # Dogecoin payout address
        'bellscoin': 'B...',           # Bellscoin payout address
        # ... more merged chains
    },
    'subsidy': ...,
    'donation': ...,
    'stale_info': ...,
    'desired_version': ...,
}
```

### 4. Merkle Tree of Trees Structure

For merged mining with multiple chains, we need a deterministic way to commit to all chains:

```
Parent Block Header
       |
       v
   merkle_root
       |
       +---- coinbase tx
       |         |
       |         +---- OP_RETURN with merged mining commitment
       |                    |
       |                    v
       |              MM Merkle Root (tree of chain hashes)
       |                    |
       |         +----------+----------+
       |         |          |          |
       |       Chain 1    Chain 2    Chain 3
       |       (DOGE)     (BELLS)    (etc.)
       |
       +---- tx1, tx2, ...
```

Each chain's hash in the MM merkle tree is computed from:
- Chain ID (determines position in tree)
- Block header hash for that chain
- Miner's address for that chain (from share_data['merged_addresses'])

### 5. Pack Types for merged_addresses

```python
# New pack type for merged addresses
merged_addresses_type = pack.ComposedType([
    ('chain_count', pack.VarIntType()),
    ('chains', pack.ListType(pack.ComposedType([
        ('chain_id', pack.VarIntType()),      # e.g., 98 for Dogecoin
        ('address', pack.VarStrType()),        # e.g., "D..." address
    ]))),
])
```

### 6. Version Comparison Safety

All existing VERSION checks use `>=` or `<` comparisons:

| Check | VERSION 35 | VERSION 100 | Result |
|-------|------------|-------------|--------|
| `VERSION >= 34` | ✓ | ✓ | Correct |
| `VERSION < 34` | ✗ | ✗ | Correct |
| `VERSION >= 35` | ✓ | ✓ | Correct |
| `VERSION < 32` | ✗ | ✗ | Correct |

**No changes needed to existing version checks.**

### 7. Protocol Version Bump

```python
# In data.py
class MultiMergedShare(BaseShare):
    MINIMUM_PROTOCOL_VERSION = 3600  # +100 from v35's 3500

# In networks/*.py (update when deploying)
MINIMUM_PROTOCOL_VERSION = 3600
```

### 8. Backward Compatibility

- Old nodes (< v3600 protocol) will reject v100 shares as "unknown type"
- v100 nodes will accept v35 shares during transition
- 95%/60% voting thresholds ensure smooth rollout
- Merged mining addresses are optional (fallback to auto-conversion)

## Implementation Steps

### Phase 1: Share Format
1. [ ] Define `merged_addresses_type` pack structure
2. [ ] Create `MultiMergedShare` class with VERSION 100
3. [ ] Add `merged_addresses` to share_info_type for VERSION >= 100
4. [ ] Update `share_versions` dict
5. [ ] Set `PaddingBugfixShare.SUCCESSOR = MultiMergedShare`

### Phase 2: Address Handling
6. [ ] Store miner's merged addresses in share_data
7. [ ] Update `get_cumulative_weights()` to track per-chain addresses
8. [ ] Modify PPLNS to use stored addresses for merged payouts

### Phase 3: Merkle Tree of Trees
9. [ ] Implement multi-chain merkle tree construction
10. [ ] Update `make_auxpow_tree()` for multiple chains
11. [ ] Support chain-specific addresses in MM commitment

### Phase 4: Testing
12. [ ] Unit tests for new pack types
13. [ ] Integration tests with multiple merged chains
14. [ ] Testnet deployment (tLTC + tDOGE + tBELLS)

### Phase 5: Deployment
15. [ ] Update network configs with new MINIMUM_PROTOCOL_VERSION
16. [ ] Deploy to testnet nodes
17. [ ] Monitor version voting progress
18. [ ] Mainnet rollout after 95% adoption

## Files to Modify

| File | Changes |
|------|---------|
| `p2pool/data.py` | New share class, pack types, VERSION checks |
| `p2pool/work.py` | Store merged addresses in share_data |
| `p2pool/merged_mining.py` | Multi-chain merkle tree |
| `p2pool/bitcoin/data.py` | New address handling utilities |
| `p2pool/networks/*.py` | MINIMUM_PROTOCOL_VERSION bump |

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Chain split | 95%/60% voting thresholds |
| Old nodes rejected | Protocol version enforcement |
| Address validation | Per-chain validation in merged_mining.py |
| Merkle tree bugs | Extensive testing before mainnet |

## Timeline

- **v1.4.0** (current): Merged mining with auto-conversion
- **v1.5.0** (planned): VERSION 100 with multiaddress support
- **v2.0.0** (future): Multiple concurrent merged chains

---

*Created: 2025-12-25*
*Base version: v1.4.0 (Share VERSION 35, Protocol 3500)*
