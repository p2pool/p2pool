# P2Pool v36 Share Format: Merged Mining Extension Proposal

## Overview

This document proposes an extension to the P2Pool share format (v36) to enable **fair, decentralized merged mining** for auxiliary chains (specifically Litecoin + Dogecoin). The design leverages P2Pool's existing version signaling mechanism to ensure backwards compatibility and smooth network migration.

## Problem Statement

### Current Merged Mining Limitations

Traditional merged mining implementations have several issues:

1. **Centralized Coinbase Control**: Only the pool operator creates the merged coinbase, deciding payout distribution
2. **Address Incompatibility**: Non-P2PKH addresses (P2SH, Bech32) cannot be auto-converted between chains
3. **No Fair Distribution**: Legacy P2Pool nodes cannot participate in merged rewards
4. **No Upgrade Path**: No mechanism to signal merged mining capability to the network

### Goals

- Enable fair merged mining rewards for **all** P2Pool participants
- Support **any** address type (P2PKH, P2SH, Bech32) for merged rewards
- Use P2Pool's existing upgrade signaling mechanism
- Maintain backwards compatibility with legacy nodes
- Create economic incentives for network migration

---

## v36 Share Format Extension

### Share Version History

| Version | Name | Features |
|---------|------|----------|
| v17 | Share | Original format |
| v32 | PreSegwitShare | Pre-SegWit preparation |
| v33 | NewShare | Updated share format |
| v34 | SegwitMiningShare | SegWit transaction support |
| v35 | PaddingBugfixShare | Script padding fix |
| **v36** | **MergedMiningShare** | **Merged mining + address mapping** |

### New Fields in v36

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  v36 MERGED MINING SHARE STRUCTURE                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Inherited from v35:                                                        │
│  ├─ min_header                                                              │
│  ├─ share_info                                                              │
│  │   ├─ share_data                                                          │
│  │   │   ├─ previous_share_hash                                             │
│  │   │   ├─ coinbase                                                        │
│  │   │   ├─ nonce                                                           │
│  │   │   ├─ new_script           ← Primary chain address (LTC)              │
│  │   │   ├─ subsidy                                                         │
│  │   │   ├─ donation                                                        │
│  │   │   ├─ stale_info                                                      │
│  │   │   └─ desired_version = 36 ← Signals merged mining support            │
│  │   ├─ segwit_data                                                         │
│  │   └─ new_transaction_hashes                                              │
│  │                                                                          │
│  NEW in v36:                                                                │
│  └─ merged_addresses[]           ← Optional list of merged chain addresses  │
│      ├─ [0] chain_id: uint32     ← AuxPoW chain identifier (e.g., DOGE)     │
│      │       script: varstr      ← Payment script for that chain            │
│      ├─ [1] chain_id: uint32     ← Future merged chain                      │
│      │       script: varstr                                                 │
│      └─ ... (max 8 entries)                                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Type Definitions

```python
# Merged address entry type
merged_address_type = pack.ComposedType([
    ('chain_id', pack.IntType(32)),    # AuxPoW chain ID (DOGE = 0x00000003)
    ('script', pack.VarStrType()),     # Payment script for that chain
])

# v36 share includes merged_addresses list
share_info_type = pack.ComposedType([
    # ... existing v35 fields ...
    ('merged_addresses', pack.ListType(merged_address_type, 8)),  # Max 8 chains
])
```

---

## Address Handling

### The Address Compatibility Problem

Different cryptocurrencies use different address formats:

| Format | Litecoin | Dogecoin | Convertible? |
|--------|----------|----------|--------------|
| P2PKH | `L...` (version 0x30) | `D...` (version 0x1e) | ✅ Yes (same pubkey hash) |
| P2SH | `M...` (version 0x32) | `9...`/`A...` (version 0x16) | ❌ No (different redeem scripts) |
| Bech32 | `ltc1...` | N/A | ❌ No (DOGE doesn't support) |

### Address Resolution Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MERGED ADDRESS RESOLUTION (Priority Order)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. EXPLICIT MAPPING (v36 merged_addresses field)                           │
│     └─ If share contains explicit mapping for chain_id → USE IT             │
│     └─ Allows any address type, miner's explicit choice                     │
│                                                                             │
│  2. AUTO-CONVERT P2PKH                                                      │
│     └─ If new_script is P2PKH format → CONVERT pubkey_hash                  │
│     └─ L... → D... (same underlying pubkey_hash)                            │
│                                                                             │
│  3. NO MAPPING AVAILABLE                                                    │
│     └─ Non-convertible address with no explicit mapping                     │
│     └─ Miner cannot receive merged rewards for this share                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation

```python
def get_merged_address_for_share(share, chain_id):
    """
    Get merged mining address for a share.
    Returns payment script for chain_id or None.
    """
    # Priority 1: Explicit merged_addresses in v36+ share
    if hasattr(share, 'merged_addresses') and share.merged_addresses:
        for entry in share.merged_addresses:
            if entry['chain_id'] == chain_id:
                return entry['script']  # Explicitly specified!
    
    # Priority 2: Auto-convert P2PKH
    merged_script = convert_p2pkh_script(share.new_script, chain_id)
    if merged_script:
        return merged_script
    
    # Priority 3: No mapping available
    return None

def convert_p2pkh_script(script, chain_id):
    """
    Convert P2PKH script to target chain.
    Returns converted script or None if not P2PKH.
    """
    # P2PKH format: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
    if len(script) == 25 and script[0:3] == '\x76\xa9\x14' and script[23:25] == '\x88\xac':
        pubkey_hash = script[3:23]  # Extract 20-byte hash
        # Reconstruct with same pubkey_hash (works across chains!)
        return '\x76\xa9\x14' + pubkey_hash + '\x88\xac'
    return None
```

---

## Tiered Reward Distribution

### Incentive-Driven Migration

To encourage network migration while being fair to all participants:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TIERED MERGED REWARD DISTRIBUTION                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  TIER 1: FULL REWARDS (90-95% of merged coinbase)                           │
│  ├─ Miners on v36 merged nodes                                              │
│  ├─ Share signals desired_version >= 36                                     │
│  └─ Full proportional reward based on share weight                          │
│                                                                             │
│  TIER 2: INCENTIVE REWARDS (5-10% of merged coinbase)                       │
│  ├─ Miners on legacy nodes (v35 and below)                                  │
│  ├─ Address MUST be convertible (P2PKH only)                                │
│  └─ Small reward to encourage migration                                     │
│     "You're earning some DOGE! Upgrade to earn more!"                       │
│                                                                             │
│  TIER 3: NO REWARDS                                                         │
│  ├─ Legacy nodes with non-convertible addresses                             │
│  └─ Must upgrade or switch to P2PKH to participate                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Distribution Algorithm

```python
def calculate_merged_payouts(tracker, best_share, chain_id, total_reward, net):
    """
    Calculate fair merged mining payouts using share chain weights.
    """
    MERGED_VERSION = 36
    INCENTIVE_PERCENT = 5  # 5% for legacy convertible miners
    
    merged_weights = {}      # Full reward pool (v36 miners)
    incentive_weights = {}   # Incentive pool (legacy convertible)
    
    # Walk the share chain
    for share in tracker.get_chain(best_share, net.REAL_CHAIN_LENGTH):
        weight = target_to_average_attempts(share.target)
        merged_script = get_merged_address_for_share(share, chain_id)
        
        if merged_script is None:
            continue  # No valid merged address
        
        if share.desired_version >= MERGED_VERSION:
            # v36+ miner: FULL rewards
            merged_weights[merged_script] = merged_weights.get(merged_script, 0) + weight
        else:
            # Legacy miner with convertible address: INCENTIVE only
            incentive_weights[merged_script] = incentive_weights.get(merged_script, 0) + weight
    
    # Allocate reward pools
    merged_pool = total_reward * (100 - INCENTIVE_PERCENT) // 100
    incentive_pool = total_reward * INCENTIVE_PERCENT // 100
    
    payouts = {}
    
    # Full rewards for v36 miners
    total_merged_weight = sum(merged_weights.values())
    if total_merged_weight > 0:
        for script, weight in merged_weights.items():
            payouts[script] = merged_pool * weight // total_merged_weight
    else:
        # No v36 miners yet - incentive pool gets everything
        incentive_pool = total_reward
    
    # Incentive rewards for legacy convertible miners
    total_incentive_weight = sum(incentive_weights.values())
    if total_incentive_weight > 0:
        for script, weight in incentive_weights.items():
            amount = incentive_pool * weight // total_incentive_weight
            payouts[script] = payouts.get(script, 0) + amount
    
    return payouts
```

---

## Version Signaling & Activation

### Using P2Pool's Built-in Mechanism

P2Pool already has a version signaling mechanism via `desired_version`:

```python
# Each share contains:
share_data = {
    # ...
    'desired_version': 36,  # Miner signals support for v36
}

# Network monitors version distribution:
def get_desired_version_counts(tracker, best_share_hash, dist):
    res = {}
    for share in tracker.get_chain(best_share_hash, dist):
        res[share.desired_version] = res.get(share.desired_version, 0) + \
            target_to_average_attempts(share.target)
    return res
```

### Activation Thresholds

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MIGRATION PHASES                                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PHASE 1: DEPLOYMENT (0-10% v36)                                            │
│  ├─ Merged nodes deployed, signaling v36                                    │
│  ├─ Legacy nodes see "upgrade available" warning                            │
│  └─ Merged rewards distributed only among v36 miners                        │
│                                                                             │
│  PHASE 2: EARLY ADOPTION (10-50% v36)                                       │
│  ├─ Incentive rewards start flowing to legacy P2PKH miners                  │
│  ├─ Miners notice "free DOGE" appearing                                     │
│  └─ Economic pressure to investigate/upgrade                                │
│                                                                             │
│  PHASE 3: MAJORITY (50-90% v36)                                             │
│  ├─ Most hashrate on merged nodes                                           │
│  ├─ Incentive pool shrinks as legacy miners upgrade                         │
│  └─ Full rewards for participating miners                                   │
│                                                                             │
│  PHASE 4: MATURITY (90%+ v36)                                               │
│  ├─ Nearly all miners on merged nodes                                       │
│  ├─ Minimal incentive pool                                                  │
│  └─ Merged mining fully operational                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Miner Configuration

### Command Line Options

```bash
# Basic merged mining (P2PKH address auto-converts)
run_p2pool.py \
    --net litecoin \
    --address Lxyz...              # LTC rewards (P2PKH)
    --merged-url http://dogecoin:22555 \
    --merged-userpass user:pass

# Advanced: Explicit DOGE address (for non-P2PKH LTC addresses)
run_p2pool.py \
    --net litecoin \
    --address ltc1qxyz...          # LTC rewards (Bech32)
    --merged-url http://dogecoin:22555 \
    --merged-userpass user:pass \
    --merged-address-doge D9abc... # Explicit DOGE address

# Advanced: Multiple merged chains
run_p2pool.py \
    --net litecoin \
    --address Lxyz... \
    --merged-url-doge http://dogecoin:22555 \
    --merged-url-bells http://bells:19918 \
    --merged-address-bells Bxyz... # Explicit Bells address
```

### Address Scenarios

| LTC Address | DOGE Config | Result |
|-------------|-------------|--------|
| `Lxyz...` (P2PKH) | None | Auto-converts to `Dxyz...` ✅ |
| `Lxyz...` (P2PKH) | `--merged-address-doge D9abc...` | Uses explicit `D9abc...` ✅ |
| `Mxyz...` (P2SH) | None | ❌ Cannot participate |
| `Mxyz...` (P2SH) | `--merged-address-doge D9abc...` | Uses explicit `D9abc...` ✅ |
| `ltc1q...` (Bech32) | None | ❌ Cannot participate |
| `ltc1q...` (Bech32) | `--merged-address-doge D9abc...` | Uses explicit `D9abc...` ✅ |

---

## Security Considerations

### Proof-of-Work Protection

The v36 share format is protected by P2Pool's existing security model:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SECURITY PROPERTIES                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. POW-PROTECTED MAPPINGS                                                  │
│     └─ merged_addresses embedded in shares                                  │
│     └─ Each mapping costs a share's worth of POW                            │
│     └─ Cannot spam fake mappings without mining                             │
│                                                                             │
│  2. CONSENSUS-VALIDATED                                                     │
│     └─ All nodes validate share format                                      │
│     └─ Invalid merged_addresses = invalid share                             │
│     └─ No way to inject fake mappings                                       │
│                                                                             │
│  3. SELF-PRUNING                                                            │
│     └─ Shares expire after CHAIN_LENGTH (~24 hours)                         │
│     └─ Old mappings naturally expire                                        │
│     └─ Miner updates mapping by submitting new share                        │
│                                                                             │
│  4. BACKWARDS COMPATIBLE                                                    │
│     └─ Legacy nodes ignore merged_addresses field                           │
│     └─ Legacy nodes still validate share POW                                │
│     └─ No network split risk                                                │
│                                                                             │
│  5. NO RACE CONDITIONS                                                      │
│     └─ Merged coinbase created at share time                                │
│     └─ Uses snapshot of share chain at that moment                          │
│     └─ Winner doesn't control distribution                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Bad Actor Scenarios

| Attack | Mitigation |
|--------|------------|
| Fake address mappings | POW-protected: costs real hashrate |
| Redirect others' rewards | Only your own share's mapping affects your payout |
| Spam the network | Standard P2Pool share validation applies |
| Replay old mappings | Shares expire after CHAIN_LENGTH |
| Front-run winning share | Coinbase locked at share creation time |

---

## Implementation Roadmap

### Phase 1: Core Implementation

- [ ] Define `MergedMiningShare` (v36) class in `data.py`
- [ ] Add `merged_addresses` field to share type
- [ ] Implement address resolution logic
- [ ] Add `--merged-address-{chain}` CLI options

### Phase 2: Reward Distribution

- [ ] Implement tiered payout calculation
- [ ] Walk share chain for all miners (not just local)
- [ ] Support multiple merged chains
- [ ] Add donation distribution for merged rewards

### Phase 3: Network Integration

- [ ] Test interoperability with legacy nodes
- [ ] Verify version signaling works correctly
- [ ] Deploy to testnet
- [ ] Monitor migration metrics

### Phase 4: Documentation & Tooling

- [ ] Update web dashboard for merged stats
- [ ] Add merged address validation
- [ ] Create migration guide for miners
- [ ] Monitor and adjust incentive percentages

---

## Summary

The v36 share format extension provides:

1. **Fair Distribution**: All P2Pool miners can receive merged rewards proportionally
2. **Flexible Addresses**: Support for any address type via explicit mapping
3. **Economic Incentives**: Tiered rewards encourage migration without forcing it
4. **Backwards Compatibility**: Legacy nodes continue to function
5. **Security**: POW-protected mappings, consensus-validated
6. **Simplicity**: No separate gossip protocol, uses existing share propagation

This design maintains P2Pool's decentralized nature while enabling the economic benefits of merged mining for all participants.

---

## References

- P2Pool Share Format: `p2pool/data.py`
- Version Signaling: `get_desired_version_counts()`
- AuxPoW Specification: BIP-0301, Namecoin merged mining
- Litecoin Address Formats: BIP-173 (Bech32), Base58Check
- Dogecoin Chain ID: `0x00000003` (62 reversed)
