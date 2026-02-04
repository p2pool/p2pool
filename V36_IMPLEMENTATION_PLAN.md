# V36 Merged Mining Share Implementation Plan

## Executive Summary

This document outlines the comprehensive implementation plan for P2Pool V36 shares with merged mining support. V36 introduces **per-miner merged chain addresses** directly in the share structure, enabling fair, decentralized merged mining rewards with proper incentive-driven migration.

**Key Goals:**
1. Allow miners to specify explicit merged chain addresses (DOGE, etc.)
2. Support automatic P2PKH conversion for compatible addresses
3. Implement fair reward redistribution for pre-V36 nodes with unconvertible addresses
4. Create economic incentives for network migration to V36
5. **Migrate donation from lost-key address to controlled address** (Part 9)

**Critical Design Note - Different Migration Mechanics:**

| Feature | Migration Type | Reason |
|---------|---------------|--------|
| **Merged Mining Rewards** | Gradual proportional | NEW feature - V35 doesn't verify |
| **Donation** | Flag day (95%+ V36) | EXISTING feature - ALL nodes must agree on coinbase |

- **Merged rewards**: CAN be split proportionally because V35 doesn't verify merged outputs
- **Donation**: CANNOT change until V35 deprecated - `get_expected_payouts()` must produce IDENTICAL coinbase on ALL nodes
- **Result**: Continue SECONDARY_DONATION_ENABLED hack (50/50 split) until flag day

**Critical Donation Constraint:**
The original P2Pool donation address has a **LOST PRIVATE KEY** - all funds sent there are permanently burned. However, donation CANNOT be migrated gradually because **ALL P2Pool nodes (V35 and V36) must compute identical coinbase structure**. V35 nodes use `DONATION_SCRIPT` in `get_expected_payouts()` - if V36 used different script, V35 nodes would reject V36 blocks! Migration requires V35 deprecation first.

---

## Part 1: Current State Analysis

### 1.1 Existing Share Structure (V35 - PaddingBugfixShare)

```python
# Current share_data fields (V35):
share_data = {
    'previous_share_hash': IntType(256),
    'coinbase': VarStrType(),
    'nonce': IntType(32),
    'address': VarStrType(),         # Parent chain address (string)
    'subsidy': IntType(64),
    'donation': IntType(16),
    'stale_info': EnumType(),
    'desired_version': VarIntType(), # Currently signals up to 35
}
```

### 1.2 Current Address Handling Problem

| Address Type | Example | Convertible to DOGE? | Current Behavior |
|--------------|---------|---------------------|------------------|
| P2PKH | `Lxyz...` | ✅ Yes (pubkey_hash) | Works |
| P2WPKH | `ltc1q...` (43 chars) | ✅ Yes (pubkey_hash) | Works |
| P2SH | `Mxyz...` | ❌ No (script hash) | **Lost rewards** |
| P2WSH | `ltc1q...` (62 chars) | ❌ No (script hash) | **Lost rewards** |
| P2TR | `ltc1p...` | ❌ No (tweaked key) | **Lost rewards** |

### 1.3 Current Redistribution (Temporary Solution)

We currently redistribute unconvertible address rewards among convertible addresses on the merged mining node. This is:
- ✅ Fair for miners on OUR node
- ❌ Only benefits miners connected to the merged-mining-capable node
- ❌ Pre-V36 nodes can't participate at all

---

## Part 2: V36 Share Format Specification

### 2.1 New Share Class: MergedMiningShare

```python
class MergedMiningShare(BaseShare):
    VERSION = 36
    VOTING_VERSION = 36
    SUCCESSOR = None  # Current head (until V37)
    MINIMUM_PROTOCOL_VERSION = 3600  # +100 from V35's 3500
```

### 2.2 Extended share_info_type

```python
# V36 adds merged_addresses after existing fields
share_info_type = pack.ComposedType([
    ('share_data', pack.ComposedType([
        ('previous_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
        ('coinbase', pack.VarStrType()),
        ('nonce', pack.IntType(32)),
        ('address', pack.VarStrType()),    # Parent chain address (unchanged)
        ('subsidy', pack.IntType(64)),
        ('donation', pack.IntType(16)),
        ('stale_info', pack.EnumType(...)),
        ('desired_version', pack.VarIntType()),  # Signals 36 for merged support
    ])),
    ('segwit_data', ...),  # Existing field
    # NEW in V36:
    ('merged_addresses', pack.PossiblyNoneType([], pack.ListType(
        pack.ComposedType([
            ('chain_id', pack.IntType(32)),      # AuxPoW chain ID (DOGE=0x62)
            ('script', pack.VarStrType()),       # Payment script for that chain
        ]), max_count=8))),  # Max 8 merged chains
    # Existing fields continue...
    ('far_share_hash', ...),
    ('max_bits', ...),
    ('bits', ...),
    ('timestamp', ...),
    ('absheight', ...),
    ('abswork', ...),
])
```

### 2.3 Type Definitions

```python
# New pack type for merged addresses
merged_address_entry_type = pack.ComposedType([
    ('chain_id', pack.IntType(32)),    # AuxPoW chain ID
    ('script', pack.VarStrType()),     # Payment script (P2PKH format)
])

# List of merged addresses (max 8 chains)
merged_addresses_type = pack.PossiblyNoneType(
    [],  # Default: empty list (auto-convert or no merged support)
    pack.ListType(merged_address_entry_type, max_count=8)
)
```

### 2.4 Chain IDs

| Chain | Chain ID | Notes |
|-------|----------|-------|
| Dogecoin | 0x00000062 (98) | From auxpow commitment |
| Bellscoin | TBD | Future support |
| Reserved | 0-7 | Reserved for special purposes |

---

## Part 3: Merged Reward Redistribution Principle

### 3.1 The Redistribution Problem

When a merged block is found, we must distribute rewards among ALL miners in the share chain (PPLNS). However:

1. **V36 Miners** - Have explicit merged addresses OR convertible P2PKH → Full eligibility
2. **Pre-V36 Miners with P2PKH** - Can auto-convert → Partial eligibility (incentive)
3. **Pre-V36 Miners with P2SH/Bech32** - Cannot convert → No eligibility (redistribute)

### 3.2 Three-Pool Distribution Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MERGED BLOCK REWARD DISTRIBUTION                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Total Merged Block Reward (e.g., 10,000 DOGE)                              │
│                     │                                                       │
│          ┌─────────┴─────────┐                                              │
│          ▼                   ▼                                              │
│    ┌───────────┐      ┌───────────────────┐                                 │
│    │ PRIMARY   │      │ INCENTIVE POOL    │                                 │
│    │ POOL (90%)│      │ (10% max)         │                                 │
│    └─────┬─────┘      └─────────┬─────────┘                                 │
│          │                      │                                           │
│          ▼                      ▼                                           │
│   V36 Miners Only       Pre-V36 Convertible                                 │
│   (full rewards)        (upgrade incentive)                                 │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ PRE-V36 UNCONVERTIBLE SHARES → Redistributed to PRIMARY POOL        │   │
│   │ (P2SH, P2WSH, P2TR addresses get 0 merged rewards)                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Mathematical Model

#### Variables:

```
R_total     = Total merged block reward (satoshis)
W_v36       = Sum of share weights from V36 miners
W_pre_conv  = Sum of share weights from pre-V36 miners with convertible addresses
W_pre_unconv= Sum of share weights from pre-V36 miners with unconvertible addresses
W_total     = W_v36 + W_pre_conv + W_pre_unconv

INCENTIVE_RATE = 0.10  (10% - adjustable based on migration progress)
```

#### Pool Allocation:

```python
# Dynamic incentive rate based on V36 adoption
def calculate_incentive_rate(v36_adoption_percent):
    """
    Incentive rate decreases as V36 adoption increases.
    - 0% V36 adoption: 10% incentive (max encouragement)
    - 50% V36 adoption: 5% incentive
    - 90% V36 adoption: 1% incentive (minimal)
    - 100% V36 adoption: 0% incentive (everyone upgraded)
    """
    return max(0.01, 0.10 * (1.0 - v36_adoption_percent))

# Pool sizes
incentive_pool = R_total * INCENTIVE_RATE
primary_pool = R_total - incentive_pool

# If no V36 miners, primary pool goes to incentive pool
if W_v36 == 0:
    incentive_pool = R_total
    primary_pool = 0
```

#### Per-Miner Rewards:

```python
def calculate_miner_reward(miner_weight, miner_version, has_merged_address, R_total, pools, weights):
    """
    Calculate merged mining reward for a single miner.
    
    Args:
        miner_weight: This miner's share weight (target_to_average_attempts)
        miner_version: Share's desired_version field
        has_merged_address: True if explicit merged_addresses OR convertible P2PKH
        R_total: Total merged block reward
        pools: (primary_pool, incentive_pool)
        weights: (W_v36, W_pre_conv, W_pre_unconv)
    
    Returns:
        Reward in satoshis, or 0 if not eligible
    """
    primary_pool, incentive_pool = pools
    W_v36, W_pre_conv, W_pre_unconv = weights
    
    if not has_merged_address:
        # Unconvertible pre-V36: No reward (their share redistributed)
        return 0
    
    if miner_version >= 36:
        # V36 miner: Full primary pool share + redistribution bonus
        if W_v36 > 0:
            base_share = primary_pool * miner_weight / W_v36
            # Redistribution: unconvertible weight's portion goes to V36 miners
            redistribution_share = (R_total * W_pre_unconv / (W_total)) * (miner_weight / W_v36)
            return base_share + redistribution_share
        else:
            return 0
    else:
        # Pre-V36 with convertible address: Incentive pool only
        if W_pre_conv > 0:
            return incentive_pool * miner_weight / W_pre_conv
        else:
            return 0
```

### 3.4 Reward Flow Diagram

```
                    ┌──────────────────────────────────────┐
                    │   MERGED BLOCK FOUND (10,000 DOGE)   │
                    └──────────────────┬───────────────────┘
                                       │
                    ┌──────────────────┴───────────────────┐
                    │      Walk PPLNS Share Chain          │
                    │      (e.g., 8640 shares = 24 hours)  │
                    └──────────────────┬───────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
        ▼                              ▼                              ▼
┌───────────────┐           ┌───────────────────┐          ┌──────────────────┐
│  V36 MINERS   │           │ PRE-V36 CONVERT.  │          │ PRE-V36 UNCONV.  │
│  version >= 36│           │ version < 36      │          │ version < 36     │
│  + any address│           │ P2PKH address     │          │ P2SH/Bech32      │
├───────────────┤           ├───────────────────┤          ├──────────────────┤
│  W_v36 = 4000 │           │ W_pre_conv = 3500 │          │ W_pre_unconv=500 │
│  (50% weight) │           │ (43.75% weight)   │          │ (6.25% weight)   │
└───────┬───────┘           └─────────┬─────────┘          └────────┬─────────┘
        │                             │                             │
        │                             │                             │
        ▼                             ▼                             ▼
┌───────────────┐           ┌───────────────────┐          ┌──────────────────┐
│PRIMARY POOL   │           │ INCENTIVE POOL    │          │ REDISTRIBUTED    │
│= 9000 DOGE    │           │ = 1000 DOGE       │          │ to Primary Pool  │
│(90% of total) │           │ (10% of total)    │          │ = 625 DOGE       │
└───────┬───────┘           └─────────┬─────────┘          └────────┬─────────┘
        │                             │                             │
        │         ┌───────────────────┘                             │
        │         │                                                 │
        ▼         ▼                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FINAL DISTRIBUTION                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  V36 Miners (4000 weight):                                                  │
│    Base: 9000 * (4000/4000) = 9000 DOGE                                     │
│    Redistribution: 625 DOGE (from unconvertible)                            │
│    TOTAL: 9625 DOGE (96.25% of block!)                                      │
│                                                                             │
│  Pre-V36 Convertible (3500 weight):                                         │
│    Incentive: 1000 * (3500/3500) = 1000 DOGE                                │
│    TOTAL: 1000 DOGE (10% of block)                                          │
│    → Message: "Upgrade to V36 to earn 3.5x more!"                           │
│                                                                             │
│  Pre-V36 Unconvertible (500 weight):                                        │
│    TOTAL: 0 DOGE (cannot receive - no valid address)                        │
│    → Message: "Your address is not compatible with DOGE. Use P2PKH          │
│               or upgrade to V36 and specify a DOGE address."                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.5 Special Cases

#### Case 1: No V36 Miners Yet (Early Deployment)

```python
if W_v36 == 0:
    # All rewards go to incentive pool for convertible pre-V36 miners
    # This bootstraps the system - early upgraders see immediate benefit
    for miner in convertible_pre_v36_miners:
        payout[miner] = R_total * miner.weight / W_pre_conv
```

#### Case 2: All Miners are V36 (Full Migration)

```python
if W_pre_conv == 0 and W_pre_unconv == 0:
    # Standard proportional distribution, no incentive pool needed
    for miner in v36_miners:
        payout[miner] = R_total * miner.weight / W_v36
```

#### Case 3: Only Unconvertible Pre-V36 Miners

```python
if W_v36 == 0 and W_pre_conv == 0:
    # CRITICAL: No one can receive rewards!
    # This scenario shouldn't happen if merged mining nodes exist
    # The merged mining node operator should always be V36
    # Their reward acts as a "floor" for the system
    log.warning("No eligible merged mining recipients!")
```

---

## Part 4: Incentivization Strategy

### 4.1 Economic Incentives

| Miner Situation | Reward Multiplier | Message |
|-----------------|-------------------|---------|
| V36 + explicit DOGE addr | 100% of fair share | "Full merged mining rewards!" |
| V36 + P2PKH (auto-convert) | 100% of fair share | "Full merged mining rewards!" |
| Pre-V36 + P2PKH | ~10% of fair share | "Upgrade to earn 10x more!" |
| Pre-V36 + P2SH/Bech32 | 0% | "Address not compatible" |

### 4.2 Dashboard Notifications

```javascript
// Display in web dashboard for pre-V36 miners
function getMergedMiningStatus(minerShare) {
    if (minerShare.desired_version >= 36) {
        return {
            status: 'FULL_REWARDS',
            message: 'Full merged mining rewards active',
            color: 'green'
        };
    }
    
    if (isConvertibleAddress(minerShare.address)) {
        const potential = calculatePotentialReward(minerShare);
        const current = calculateCurrentIncentive(minerShare);
        return {
            status: 'INCENTIVE_ONLY',
            message: `Earning ${current} DOGE. Upgrade to V36 for ${potential} DOGE!`,
            color: 'yellow',
            upgradeUrl: '/upgrade-guide'
        };
    }
    
    return {
        status: 'NOT_ELIGIBLE',
        message: 'Your address cannot receive DOGE. Use P2PKH or specify DOGE address.',
        color: 'red',
        helpUrl: '/merged-mining-addresses'
    };
}
```

### 4.3 Migration Tracking

```python
def get_migration_stats(tracker, best_share_hash, chain_length):
    """
    Calculate V36 adoption statistics for the share chain.
    """
    stats = {
        'v36_shares': 0,
        'v36_weight': 0,
        'pre_v36_convertible_shares': 0,
        'pre_v36_convertible_weight': 0,
        'pre_v36_unconvertible_shares': 0,
        'pre_v36_unconvertible_weight': 0,
        'total_weight': 0,
    }
    
    for share in tracker.get_chain(best_share_hash, chain_length):
        weight = bitcoin_data.target_to_average_attempts(share.target)
        stats['total_weight'] += weight
        
        if share.desired_version >= 36:
            stats['v36_shares'] += 1
            stats['v36_weight'] += weight
        else:
            has_merged, _, _ = is_pubkey_hash_address(share.address, net.PARENT)
            if has_merged:
                stats['pre_v36_convertible_shares'] += 1
                stats['pre_v36_convertible_weight'] += weight
            else:
                stats['pre_v36_unconvertible_shares'] += 1
                stats['pre_v36_unconvertible_weight'] += weight
    
    # Calculate percentages
    if stats['total_weight'] > 0:
        stats['v36_percent'] = stats['v36_weight'] / stats['total_weight']
        stats['convertible_percent'] = stats['pre_v36_convertible_weight'] / stats['total_weight']
        stats['unconvertible_percent'] = stats['pre_v36_unconvertible_weight'] / stats['total_weight']
    
    return stats
```

---

## Part 5: Implementation Plan

### Phase 1: Share Format + Donation Migration (Week 1-2)

#### 1.1 Define MergedMiningShare Class

```python
# In p2pool/data.py

class MergedMiningShare(BaseShare):
    """
    V36 share with merged mining address support.
    Allows miners to specify explicit addresses for merged chains.
    ALSO: Migrates donation to controlled address (lost key fix!)
    """
    VERSION = 36
    VOTING_VERSION = 36
    SUCCESSOR = None
    MINIMUM_PROTOCOL_VERSION = 3600
    
    # CRITICAL: New gentx_before_refhash using SECONDARY_DONATION_SCRIPT
    # This is the donation migration point - no more burning to lost key!
    gentx_before_refhash = (
        pack.VarStrType().pack(SECONDARY_DONATION_SCRIPT) +  # NEW controlled address!
        pack.IntType(64).pack(0) + 
        pack.VarStrType().pack('\x6a\x28' + pack.IntType(256).pack(0) + pack.IntType(64).pack(0))[:3]
    )
    
    @classmethod
    def get_dynamic_types(cls, net):
        # Get V35 types first
        t = super(MergedMiningShare, cls).get_dynamic_types(net)
        
        # Add merged_addresses field to share_info_type
        # Insert after segwit_data but before far_share_hash
        merged_addresses_type = pack.PossiblyNoneType(
            [],
            pack.ListType(pack.ComposedType([
                ('chain_id', pack.IntType(32)),
                ('script', pack.VarStrType()),
            ]), max_count=8)
        )
        
        # Rebuild share_info_type with new field
        # ... implementation details ...
        
        return t
```

#### 1.2 Update Successor Chain

```python
# Update existing class
PaddingBugfixShare.SUCCESSOR = MergedMiningShare

# Update share_versions dict
share_versions = {
    s.VERSION: s for s in [
        MergedMiningShare,      # v36 - NEW
        PaddingBugfixShare,     # v35
        SegwitMiningShare,      # v34
        NewShare,               # v33
        PreSegwitShare,         # v32
        Share,                  # v17
    ]
}
```

### Phase 2: Address Resolution (Week 2-3)

#### 2.1 Implement Address Resolution

```python
# In p2pool/work.py or new p2pool/merged_addresses.py

def get_merged_address_for_share(share, chain_id, parent_net, merged_net):
    """
    Resolve merged chain address for a share.
    
    Priority:
    1. Explicit merged_addresses field (V36+)
    2. Auto-convert P2PKH/P2WPKH address
    3. Return None if not convertible
    
    Returns:
        Payment script for chain_id or None
    """
    # Priority 1: Check V36 explicit merged_addresses
    if share.VERSION >= 36:
        merged_addresses = share.share_info.get('merged_addresses', [])
        for entry in merged_addresses:
            if entry['chain_id'] == chain_id:
                return entry['script']
    
    # Priority 2: Try auto-conversion
    is_convertible, pubkey_hash, error = is_pubkey_hash_address(
        share.share_info['share_data']['address'], parent_net
    )
    
    if is_convertible and pubkey_hash is not None:
        # Convert pubkey_hash to merged chain P2PKH script
        return bitcoin_data.pubkey_hash_to_script2(
            pubkey_hash, merged_net.ADDRESS_VERSION, -1, merged_net
        )
    
    # Priority 3: Not convertible
    return None
```

### Phase 3: Reward Calculation (Week 3-4)

#### 3.1 Implement Distribution Algorithm

```python
# In p2pool/merged_mining.py or p2pool/work.py

def calculate_merged_payouts(tracker, best_share_hash, chain_id, total_reward, 
                              parent_net, merged_net, chain_length):
    """
    Calculate fair merged mining payouts using share chain weights.
    
    Implements three-pool distribution model:
    - Primary Pool (90%): V36 miners with full proportional rewards
    - Incentive Pool (10%): Pre-V36 miners with convertible addresses
    - Redistribution: Unconvertible shares' portion goes to Primary Pool
    
    Returns:
        dict: {merged_script: satoshi_amount}
    """
    MERGED_VERSION = 36
    BASE_INCENTIVE_RATE = 0.10  # 10% base
    
    # Accumulators
    v36_weights = {}           # {script: total_weight}
    pre_v36_conv_weights = {}  # {script: total_weight}
    total_v36_weight = 0
    total_pre_v36_conv_weight = 0
    total_pre_v36_unconv_weight = 0
    
    # Walk the share chain
    for share in tracker.get_chain(best_share_hash, chain_length):
        weight = bitcoin_data.target_to_average_attempts(share.target)
        merged_script = get_merged_address_for_share(
            share, chain_id, parent_net, merged_net
        )
        
        if merged_script is None:
            # Unconvertible - weight will be redistributed
            total_pre_v36_unconv_weight += weight
            continue
        
        if share.share_info['share_data']['desired_version'] >= MERGED_VERSION:
            # V36+ miner: Full primary pool
            v36_weights[merged_script] = v36_weights.get(merged_script, 0) + weight
            total_v36_weight += weight
        else:
            # Pre-V36 with convertible address: Incentive pool
            pre_v36_conv_weights[merged_script] = pre_v36_conv_weights.get(merged_script, 0) + weight
            total_pre_v36_conv_weight += weight
    
    # Calculate dynamic incentive rate based on V36 adoption
    total_weight = total_v36_weight + total_pre_v36_conv_weight + total_pre_v36_unconv_weight
    v36_adoption = total_v36_weight / total_weight if total_weight > 0 else 0
    incentive_rate = max(0.01, BASE_INCENTIVE_RATE * (1.0 - v36_adoption))
    
    # Special case: No V36 miners yet
    if total_v36_weight == 0:
        incentive_pool = total_reward
        primary_pool = 0
    else:
        incentive_pool = int(total_reward * incentive_rate)
        primary_pool = total_reward - incentive_pool
        
        # Add unconvertible redistribution to primary pool
        # (they can't receive, so their share goes to V36 miners)
        if total_weight > 0:
            unconv_portion = total_reward * total_pre_v36_unconv_weight // total_weight
            primary_pool += unconv_portion
    
    # Calculate payouts
    payouts = {}
    
    # Primary pool for V36 miners
    if total_v36_weight > 0 and primary_pool > 0:
        for script, weight in v36_weights.items():
            amount = primary_pool * weight // total_v36_weight
            payouts[script] = payouts.get(script, 0) + amount
    
    # Incentive pool for pre-V36 convertible miners
    if total_pre_v36_conv_weight > 0 and incentive_pool > 0:
        for script, weight in pre_v36_conv_weights.items():
            amount = incentive_pool * weight // total_pre_v36_conv_weight
            payouts[script] = payouts.get(script, 0) + amount
    
    return payouts
```

### Phase 4: CLI and Configuration (Week 4-5)

#### 4.1 New Command Line Options

```python
# In p2pool/main.py

parser.add_argument('--merged-address-doge',
    help='Explicit Dogecoin address for merged mining rewards',
    type=str, action='store', default=None, dest='merged_address_doge')

parser.add_argument('--merged-address-bells',
    help='Explicit Bellscoin address for merged mining rewards',
    type=str, action='store', default=None, dest='merged_address_bells')

# Generic format for future chains
parser.add_argument('--merged-address',
    help='Merged chain address in format CHAIN:ADDRESS (e.g., doge:D9xyz...)',
    type=str, action='append', default=[], dest='merged_addresses')
```

#### 4.2 Share Generation with Merged Addresses

```python
# In p2pool/work.py WorkerBridge.get_work()

def build_merged_addresses(self):
    """
    Build merged_addresses list from CLI options and miner requests.
    """
    merged_addresses = []
    
    # From CLI options
    if self.args.merged_address_doge:
        doge_script = bitcoin_data.address_to_script2(
            self.args.merged_address_doge, dogecoin_net)
        merged_addresses.append({
            'chain_id': 0x62,  # Dogecoin
            'script': doge_script
        })
    
    if self.args.merged_address_bells:
        bells_script = bitcoin_data.address_to_script2(
            self.args.merged_address_bells, bellscoin_net)
        merged_addresses.append({
            'chain_id': 0x...,  # Bellscoin chain ID
            'script': bells_script
        })
    
    # From --merged-address format
    for entry in self.args.merged_addresses:
        chain, address = entry.split(':', 1)
        chain_id, net = get_chain_info(chain)
        script = bitcoin_data.address_to_script2(address, net)
        merged_addresses.append({
            'chain_id': chain_id,
            'script': script
        })
    
    return merged_addresses if merged_addresses else None
```

### Phase 5: Network Protocol (Week 5-6)

#### 5.1 Protocol Version Bump

```python
# In p2pool/p2p.py
class Protocol(p2protocol.Protocol):
    VERSION = 3600  # Bump from 3502 to support V36 shares
```

#### 5.2 Share Serialization

The V36 shares need to serialize/deserialize the new `merged_addresses` field correctly. This is handled by the pack types, but we need to ensure backward compatibility:

```python
# V36 shares received by V35 nodes will be rejected as "unknown type"
# V35 shares received by V36 nodes will be accepted (SUCCESSOR chain)
```

### Phase 6: Testing (Week 6-7)

#### 6.1 Unit Tests

```python
# test_v36_shares.py

def test_v36_share_serialization():
    """Test V36 share round-trip serialization."""
    share = create_test_v36_share(merged_addresses=[
        {'chain_id': 0x62, 'script': b'\x76\xa9\x14' + b'\x00'*20 + b'\x88\xac'}
    ])
    packed = pack_share(share)
    unpacked = unpack_share(packed)
    assert unpacked.merged_addresses == share.merged_addresses

def test_merged_address_resolution():
    """Test address resolution priority."""
    # V36 with explicit address
    share_v36 = create_share(version=36, merged_addresses=[
        {'chain_id': 0x62, 'script': DOGE_SCRIPT_A}
    ])
    assert get_merged_address_for_share(share_v36, 0x62) == DOGE_SCRIPT_A
    
    # Pre-V36 with P2PKH (should auto-convert)
    share_v35_p2pkh = create_share(version=35, address='Lxyz...')
    assert get_merged_address_for_share(share_v35_p2pkh, 0x62) is not None
    
    # Pre-V36 with P2SH (should return None)
    share_v35_p2sh = create_share(version=35, address='Mxyz...')
    assert get_merged_address_for_share(share_v35_p2sh, 0x62) is None

def test_reward_distribution():
    """Test three-pool reward distribution."""
    # Create share chain with mixed versions
    shares = [
        create_share(version=36, weight=1000),  # V36
        create_share(version=35, address='Lxyz...', weight=500),  # Pre-V36 convertible
        create_share(version=35, address='Mxyz...', weight=300),  # Pre-V36 unconvertible
    ]
    
    payouts = calculate_merged_payouts(shares, total_reward=10000)
    
    # V36 should get primary pool + redistribution
    # Pre-V36 convertible should get incentive pool
    # Pre-V36 unconvertible should get nothing
    assert payouts[v36_script] > payouts[pre_v36_conv_script]
    assert pre_v36_unconv_script not in payouts
```

### Phase 7: Deployment (Week 7-8)

#### 7.1 Testnet Deployment

1. Deploy V36-capable nodes on Litecoin testnet
2. Connect to existing tLTC P2Pool network
3. Verify V35 shares still accepted
4. Verify V36 shares propagate correctly
5. Test merged mining with tDOGE

#### 7.2 Mainnet Rollout

1. Deploy V36 nodes alongside existing V35 nodes
2. Monitor `desired_version` signaling
3. Wait for 50% adoption before enabling full merged mining
4. Gradually reduce incentive pool as adoption increases

---

## Part 6: Files to Modify

| File | Changes |
|------|---------|
| `p2pool/data.py` | MergedMiningShare class, merged_addresses type, share_versions, **NEW gentx_before_refhash** |
| `p2pool/work.py` | get_merged_address_for_share(), build_merged_addresses(), share generation |
| `p2pool/web.py` | calculate_merged_payouts(), migration stats endpoint, **donation_stats endpoint** |
| `p2pool/main.py` | --merged-address-* CLI options |
| `p2pool/p2p.py` | Protocol VERSION bump to 3600 |
| `p2pool/bitcoin/data.py` | merged_address_entry_type pack definition |
| `p2pool/networks/*.py` | MINIMUM_PROTOCOL_VERSION update |
| `web-static/dashboard.html` | Migration status display, upgrade prompts, **donation transparency** |

---

## Part 7: Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Chain split between V35/V36 | High | SUCCESSOR chain ensures V36 nodes accept V35 shares |
| Address validation bugs | Medium | Extensive testing, fail-safe to auto-convert |
| Incentive gaming | Low | POW-protected, each share costs real work |
| Migration stalls | Medium | Adjust incentive rates dynamically |
| Merged chain issues | Low | Graceful degradation if merged chain unavailable |
| **Donation migration confusion** | Medium | **Clear documentation, transparency dashboard** |

---

## Part 8: Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| V36 adoption rate | >50% in 4 weeks | `get_desired_version_counts()` |
| Unconvertible share rate | <10% | Migration stats endpoint |
| Merged block success rate | >95% | Block submission logs |
| Miner upgrade complaints | Minimal | Community feedback |

---

## Part 10: Share Difficulty Stagnation Problem (Discovered Feb 2026)

### 10.1 Problem Discovery

During isolated testnet testing of V35/V36 compatibility, we discovered a **critical protocol flaw** in P2Pool's difficulty adjustment mechanism. When the network hashrate drops suddenly, share difficulty can become stuck at impossibly high levels.

**Test Environment:**
- 3 isolated P2Pool nodes (.29, .30, .31 on 192.168.86.x)
- 3 weak miners (AntRouter R1, ~1.3 MH/s each, ~4 MH/s total)
- Nodes isolated from global P2Pool network via iptables

**Observed Behavior:**
```
Stale share found, LOST, share hash > target!
Previous share's timestamp is 1548 seconds old
Best share difficulty: 104.8 (requires ~37B attempts)
With 4 MH/s total: Would take ~2.5 hours PER SHARE
```

### 10.2 Root Cause Analysis

P2Pool's difficulty adjustment is **share-count based, not time-based**:

```python
# From p2pool/data.py lines 220-250
if height < net.TARGET_LOOKBEHIND:
    pre_target3 = net.MAX_TARGET  # Start at MIN difficulty
else:
    # Uses get_pool_attempts_per_second() which looks at:
    # - Last TARGET_LOOKBEHIND shares (e.g., 720)
    # - Calculates hashrate from share timestamps
    attempts_per_second = get_pool_attempts_per_second(
        tracker, share_data['previous_share_hash'], 
        net.TARGET_LOOKBEHIND, min_work=True, integer=True
    )
    pre_target = 2**256 // (net.SHARE_PERIOD * attempts_per_second) - 1
```

**The Feedback Loop Problem:**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DIFFICULTY STAGNATION DEATH SPIRAL                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Big miner leaves network (or network splits)                            │
│     └─ Previous shares have HIGH difficulty (from high hashrate era)        │
│                                                                             │
│  2. Remaining small miners try to find shares                               │
│     └─ Difficulty too high for their hashrate                               │
│     └─ Takes hours/days to find even ONE share                              │
│                                                                             │
│  3. Difficulty adjustment cannot kick in                                    │
│     └─ Needs new shares to see hashrate dropped                             │
│     └─ But shares can't be found at current difficulty!                     │
│                                                                             │
│  4. Result: STUCK - Difficulty frozen at impossible level                   │
│     └─ Small miners effectively locked out                                  │
│     └─ Only solution: Delete share chain and restart                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.3 Real-World Impact: Pool Hopping Problem

This isn't just a test issue - it affects production P2Pool networks:

**Scenario: "Pool Hopper" Behavior**
1. Large miner (e.g., 100 GH/s) joins P2Pool as backup pool
2. Difficulty adjusts upward to accommodate high hashrate
3. Large miner's primary pool recovers → leaves P2Pool
4. Remaining miners (e.g., 1 GH/s total) stuck at 100x difficulty
5. Takes DAYS to find enough shares to reset difficulty
6. Meanwhile, miners have zero accounting and no payouts

**Impact on Fair Mining:**
- Large transient miners "burn" difficulty for everyone
- Small consistent miners punished for others' behavior
- Discourages small miners from using P2Pool

### 10.4 Why Bitcoin Cash Had Similar Problem

Bitcoin Cash faced this with their Emergency Difficulty Adjustment (EDA). When hashrate suddenly dropped, blocks became too slow to find. They implemented multiple fixes:

- **BCH EDA**: If 6+ blocks took >12h, reduce difficulty by 20%
- **BCH DAA**: Rolling 144-block window with time-weighted adjustment

P2Pool's share chain is analogous to Bitcoin's blockchain here.

### 10.5 Proposed Solution: Time-Based Difficulty Floor

Add a time-based decay mechanism when shares are stale:

```python
# PROPOSED: Add to p2pool/data.py difficulty calculation

def calculate_difficulty_with_time_decay(tracker, previous_share_hash, net):
    """
    Calculate share difficulty with time-based emergency adjustment.
    
    If last share is older than EMERGENCY_THRESHOLD, use time-based
    estimation instead of share-based hashrate calculation.
    """
    EMERGENCY_THRESHOLD = net.SHARE_PERIOD * 20  # e.g., 200 seconds for 10s shares
    DECAY_RATE = 0.5  # Halve estimated hashrate per threshold period
    
    if previous_share_hash is None:
        return net.MAX_TARGET  # Genesis: minimum difficulty
    
    last_share = tracker.items[previous_share_hash]
    time_since_share = time.time() - last_share.timestamp
    
    # Standard calculation for recent shares
    if time_since_share < EMERGENCY_THRESHOLD:
        return standard_difficulty_calculation(tracker, previous_share_hash, net)
    
    # EMERGENCY: Time-based difficulty decay
    # Estimate current hashrate assuming it dropped
    decay_periods = time_since_share / EMERGENCY_THRESHOLD
    decay_factor = DECAY_RATE ** decay_periods
    
    # Get last known hashrate
    last_known_hashrate = get_pool_attempts_per_second(
        tracker, previous_share_hash, 
        min(net.TARGET_LOOKBEHIND, tracker.get_height(previous_share_hash)),
        min_work=True, integer=True
    )
    
    # Apply decay - assume hashrate has dropped
    estimated_hashrate = max(1, int(last_known_hashrate * decay_factor))
    
    # Calculate target for estimated hashrate
    emergency_target = 2**256 // (net.SHARE_PERIOD * estimated_hashrate) - 1
    
    # Clamp to MAX_TARGET (minimum difficulty)
    return min(emergency_target, net.MAX_TARGET)
```

### 10.6 Alternative Solutions Considered

| Solution | Pros | Cons |
|----------|------|------|
| **Time decay (proposed)** | Simple, predictable, automatic | May briefly overshoot on recovery |
| **Share weight vesting (alternative)** | Prevents problem entirely, fair | More complex, changes payout accounting |
| **Manual reset (current)** | Works | Requires operator intervention, loses history |
| **Hybrid lookback** | More accurate | Complex implementation |
| **Minimum hashrate floor** | Prevents stagnation | May be too generous |

### 10.6.1 Alternative: Share Weight Vesting (Prevention vs Cure)

Instead of fixing stagnation AFTER it happens, **prevent it by dampening high-diff shares**:

**Core Insight:**
The problem isn't that difficulty goes up - it's that a TRANSIENT big miner can poison the difficulty for PERSISTENT small miners. If a big miner joins briefly, their high-diff shares dominate the window, then they leave and small miners are stuck.

**Vesting Concept:**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SHARE WEIGHT VESTING: HIGH-DIFF SHARES EARN WEIGHT OVER TIME               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  STANDARD (Current):                                                        │
│  └─ Share found at diff 100 → immediately counts as 100 weight              │
│  └─ Big miner joins, finds 10 shares at diff 100 → 1000 weight instantly    │
│  └─ Big miner leaves → difficulty stuck at 100, small miners stranded       │
│                                                                             │
│  WITH VESTING:                                                              │
│  └─ Share found at diff 100 → counts as (100 * vesting_factor)              │
│  └─ vesting_factor = min(1.0, shares_behind_this / VESTING_WINDOW)          │
│  └─ New share: vesting_factor = 0.0 (just born)                             │
│  └─ After VESTING_WINDOW shares: vesting_factor = 1.0 (fully vested)        │
│                                                                             │
│  RESULT:                                                                    │
│  └─ Big miner's shares start with LOW effective weight                      │
│  └─ Only count fully after VESTING_WINDOW more shares found                 │
│  └─ If big miner leaves quickly → their shares never fully vest             │
│  └─ Difficulty never spikes as high → small miners not stranded!            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Mathematical Model:**
```python
# PROPOSED: Share weight vesting for difficulty calculation

VESTING_WINDOW = 100  # Shares needed to fully vest (e.g., ~16 minutes at 10s/share)

def get_vested_weight(share, tracker, current_height):
    """
    Calculate vested weight of a share for difficulty calculation.
    
    New shares start with 0 weight and gradually vest to full weight
    as more shares are added on top of them.
    """
    share_height = tracker.get_height(share.hash)
    shares_on_top = current_height - share_height
    
    # Vesting factor: 0.0 at birth → 1.0 after VESTING_WINDOW shares
    vesting_factor = min(1.0, shares_on_top / VESTING_WINDOW)
    
    # Raw weight from target (current behavior)
    raw_weight = bitcoin_data.target_to_average_attempts(share.target)
    
    return raw_weight * vesting_factor

def calculate_pool_hashrate_with_vesting(tracker, tip_hash, lookback):
    """
    Calculate pool hashrate using vested share weights.
    
    High-diff shares from transient miners count less until they've
    been in the chain long enough to "prove" the hashrate is sustained.
    """
    current_height = tracker.get_height(tip_hash)
    total_vested_work = 0
    time_span = 0
    
    for share in tracker.get_chain(tip_hash, lookback):
        vested_weight = get_vested_weight(share, tracker, current_height)
        total_vested_work += vested_weight
        # Time span calculation as usual...
    
    return total_vested_work / time_span if time_span > 0 else 0
```

**Scenario Comparison:**
```
SCENARIO: Big miner (100 GH/s) joins for 5 minutes, then leaves
          Small miners (1 GH/s total) remain

CURRENT BEHAVIOR:
  - Big miner finds 30 shares at diff 100
  - Difficulty immediately at 100
  - Big miner leaves
  - Small miners need ~2.7 hours PER SHARE at diff 100
  - Takes DAYS to find 720 shares to reset difficulty

WITH VESTING (VESTING_WINDOW=100):
  - Big miner finds 30 shares at diff 100
  - Those shares start at 0% vested weight
  - After big miner leaves, only ~30% would be vested (30/100)
  - Effective difficulty: ~30 (not 100)
  - Small miners can find shares at reasonable difficulty
  - As they find shares, big miner's shares continue vesting
  - But NEW shares from small miners also count toward hashrate
  - Difficulty naturally balances to sustainable level
```

**Trade-offs:**

| Aspect | Time Decay | Share Vesting |
|--------|------------|---------------|
| **When it acts** | AFTER stagnation (reactive) | PREVENTS stagnation (proactive) |
| **Complexity** | Simple time check | Changes weight calculation |
| **Payout impact** | None | Potentially affects PPLNS weight? |
| **Gaming resistance** | Moderate | High (can't "spike and leave") |
| **Big miner fairness** | Full weight immediately | Earns weight over time |

**Critical Question: Does Vesting Affect Payouts?**

Two options:
1. **Vesting for DIFFICULTY ONLY** - Shares still pay full weight in PPLNS
   - Only dampens difficulty calculation
   - Big miner still gets fair payout for work done
   - Simpler, less controversial

2. **Vesting for DIFFICULTY AND PAYOUTS** - Shares earn payout weight gradually
   - "Pool hopper" gets reduced rewards (their shares aren't vested when block found)
   - Strongly discourages transient mining
   - More controversial but more effective

**Recommendation:** Start with Option 1 (difficulty only). This solves the stagnation problem without changing payout economics. Option 2 could be considered for V37 if pool hopping remains a problem.

### 10.6.2 Refined Alternative: Per-Miner Tenure Vesting

Instead of vesting shares based on their position in the chain, vest based on **how long the MINER has been consistently participating**:

**Core Insight:**
The problem is TRANSIENT miners, not new shares. A miner who stays and keeps contributing should have full weight. A miner who "spikes and leaves" should have dampened weight.

**Per-Miner Vesting Concept:**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PER-MINER TENURE VESTING: WEIGHT BASED ON MINER'S CONSISTENCY              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SHARE-BASED VESTING (10.6.1):                                              │
│  └─ Share vests as more shares added ON TOP of it                           │
│  └─ All miners' shares vest equally based on chain position                 │
│  └─ Simple but doesn't distinguish persistent vs transient miners           │
│                                                                             │
│  PER-MINER TENURE VESTING (This approach):                                  │
│  └─ Track how many shares each MINER has in the lookback window             │
│  └─ Miner's vesting_factor = min(1.0, miner_share_count / VESTING_WINDOW)   │
│  └─ ALL of that miner's shares use the SAME vesting factor                  │
│                                                                             │
│  EXAMPLE (VESTING_WINDOW = 100 shares):                                     │
│                                                                             │
│  Miner A (consistent small miner):                                          │
│    - Has 150 shares in lookback window                                      │
│    - vesting_factor = min(1.0, 150/100) = 1.0 (fully vested!)               │
│    - All 150 shares count at 100% weight                                    │
│                                                                             │
│  Miner B (pool hopper, just arrived):                                       │
│    - Has 10 shares in lookback window (high diff, just joined)              │
│    - vesting_factor = min(1.0, 10/100) = 0.1 (10% vested)                   │
│    - All 10 shares count at only 10% weight!                                │
│    - Even if each share is 100x difficulty, effective = 10x                 │
│                                                                             │
│  RESULT:                                                                    │
│  └─ Consistent miners: Full weight from day one (if they have tenure)       │
│  └─ Pool hoppers: Dampened weight until they prove consistency              │
│  └─ Difficulty reflects SUSTAINED hashrate, not spikes                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Mathematical Model:**
```python
# PROPOSED: Per-miner tenure vesting for difficulty calculation

VESTING_WINDOW = 100  # Shares needed to fully vest

def calculate_miner_vesting_factors(tracker, tip_hash, lookback):
    """
    Calculate vesting factor for each miner based on their tenure.
    
    Returns dict: {miner_address: vesting_factor}
    """
    miner_share_counts = {}  # {address: share_count}
    
    # Count shares per miner in lookback window
    for share in tracker.get_chain(tip_hash, lookback):
        address = share.share_info['share_data']['address']
        miner_share_counts[address] = miner_share_counts.get(address, 0) + 1
    
    # Calculate vesting factor for each miner
    vesting_factors = {}
    for address, count in miner_share_counts.items():
        vesting_factors[address] = min(1.0, count / VESTING_WINDOW)
    
    return vesting_factors

def calculate_pool_hashrate_with_tenure_vesting(tracker, tip_hash, lookback):
    """
    Calculate pool hashrate using per-miner tenure vesting.
    
    Miners with long tenure have full weight.
    New miners (potential pool hoppers) have dampened weight.
    """
    # First pass: calculate vesting factors
    vesting_factors = calculate_miner_vesting_factors(tracker, tip_hash, lookback)
    
    # Second pass: calculate vested work
    total_vested_work = 0
    timestamps = []
    
    for share in tracker.get_chain(tip_hash, lookback):
        address = share.share_info['share_data']['address']
        vesting = vesting_factors.get(address, 0.0)
        
        raw_weight = bitcoin_data.target_to_average_attempts(share.target)
        vested_weight = raw_weight * vesting
        
        total_vested_work += vested_weight
        timestamps.append(share.timestamp)
    
    # Calculate hashrate from vested work
    if len(timestamps) >= 2:
        time_span = max(timestamps) - min(timestamps)
        if time_span > 0:
            return total_vested_work / time_span
    
    return 0
```

**Scenario Comparison:**
```
SCENARIO: Big miner (100 GH/s) joins for 5 minutes, then leaves
          Small miner (1 GH/s) has been mining consistently

LOOKBACK_WINDOW = 720 shares, VESTING_WINDOW = 100 shares

CURRENT BEHAVIOR:
  - Big miner finds 30 shares at diff 100 in 5 minutes
  - Small miner has 200 shares at diff 1
  - Difficulty immediately spikes based on (30*100 + 200*1) = 3200 work
  - Big miner leaves → small miner stuck at high difficulty

WITH PER-MINER TENURE VESTING:
  - Small miner: 200 shares → vesting = min(1.0, 200/100) = 1.0 (100%)
  - Big miner: 30 shares → vesting = min(1.0, 30/100) = 0.3 (30%)
  
  - Small miner effective work: 200 * 1 * 1.0 = 200
  - Big miner effective work: 30 * 100 * 0.3 = 900
  - Total effective work: 1100 (not 3200!)
  
  - Difficulty based on 1100 work, not 3200
  - When big miner leaves, difficulty is already reasonable
  - Small miner can continue finding shares!
```

**Why Per-Miner is Better Than Per-Share:**

| Aspect | Per-Share Vesting | Per-Miner Tenure Vesting |
|--------|-------------------|--------------------------|
| **What it measures** | How old is this share | How consistent is this miner |
| **New consistent miner** | Starts at 0%, slow ramp | Reaches 100% after VESTING_WINDOW shares |
| **Pool hopper pattern** | Each share vests independently | ALL shares dampened by low tenure |
| **Existing miners** | Affected by new high-diff shares | Protected - their tenure is already 100% |
| **Fairness** | All shares treated equally | Rewards consistency over time |
| **Gaming resistance** | Medium | High - can't fake tenure |

**Edge Case: What About Brand New Pool?**
```
If pool is brand new (few total shares):
  - All miners have low share counts
  - All vesting factors are low
  - But difficulty calculation still works because:
    - Everyone is equally dampened
    - Ratio between miners preserved
    - Base difficulty still adjusts to find shares
  
Special handling for bootstrap:
  if total_shares < VESTING_WINDOW:
      # Everyone is "equally new" - use standard calculation
      return standard_difficulty_calculation()
```

**Implementation Note:**
This requires tracking shares per address, which is already done for PPLNS payouts. The calculation can reuse that infrastructure.

### 10.6.3 Attack Vectors and Mitigations

The per-miner tenure system can be gamed. Here are identified attacks and countermeasures:

**Attack 1: "Tenure Farming" - Keep Weak Miner After Leaving**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ATTACK: TENURE FARMING                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  EXPLOIT SEQUENCE:                                                          │
│  1. Hopper joins with 100 GH/s miner                                        │
│  2. Finds 100 shares at diff 100 → now "fully vested" (100%)                │
│  3. Switches main miner away, leaves 1 MH/s "placeholder"                   │
│  4. Placeholder finds 1 share/day, maintains share count > 100              │
│  5. Old high-diff shares STILL count at 100% weight!                        │
│  6. Difficulty stays poisoned even though real hashrate is gone             │
│                                                                             │
│  WHY IT WORKS:                                                              │
│  └─ Tenure based on SHARE COUNT, not sustained HASHRATE                     │
│  └─ 100 old high-diff shares + 1 new low-diff share = still 101 shares      │
│  └─ Vesting factor still 100%                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Attack 2: Address Reuse Across Sessions**
```
Same hopper returns periodically:
  - Week 1: Joins with high hashrate, builds tenure, leaves
  - Week 2: Returns briefly, tenure still valid, spikes difficulty again
  - Pattern: Periodic difficulty poisoning with minimal cost
```

**Attack 3: Cooperative Address Sharing**
```
Multiple hoppers share address:
  - Hopper A builds tenure
  - Hopper A leaves, Hopper B takes over same address
  - Address always has tenure, hoppers rotate freely
```

---

**MITIGATION: Weight-Based Tenure (Not Count-Based)**

Instead of counting shares, count WORK (difficulty-weighted):

```python
# IMPROVED: Weight-based tenure vesting

def calculate_miner_vesting_factors_weighted(tracker, tip_hash, lookback):
    """
    Calculate vesting factor based on WORK contribution, not share count.
    
    Key insight: If a miner's hashrate drops, their RECENT work drops,
    which should reduce vesting of their HISTORICAL shares.
    """
    VESTING_WORK_THRESHOLD = net.SHARE_PERIOD * lookback  # Expected work for full tenure
    RECENCY_WINDOW = lookback // 4  # Recent = last 25% of window
    
    miner_total_work = {}   # {address: total_work_in_window}
    miner_recent_work = {}  # {address: work_in_recent_window}
    
    share_index = 0
    for share in tracker.get_chain(tip_hash, lookback):
        address = share.share_info['share_data']['address']
        work = bitcoin_data.target_to_average_attempts(share.target)
        
        miner_total_work[address] = miner_total_work.get(address, 0) + work
        
        # Track recent work separately
        if share_index < RECENCY_WINDOW:
            miner_recent_work[address] = miner_recent_work.get(address, 0) + work
        
        share_index += 1
    
    # Calculate vesting with consistency check
    vesting_factors = {}
    for address in miner_total_work:
        total_work = miner_total_work[address]
        recent_work = miner_recent_work.get(address, 0)
        
        # Base vesting from total work
        base_vesting = min(1.0, total_work / VESTING_WORK_THRESHOLD)
        
        # Consistency factor: recent work should be proportional to total
        # If miner did 1000 work total but only 10 recently, they've "left"
        expected_recent = total_work * RECENCY_WINDOW / lookback
        if expected_recent > 0:
            consistency = min(1.0, recent_work / expected_recent)
        else:
            consistency = 1.0
        
        # Final vesting = base * consistency
        # Miner who left has low consistency → their old shares dampened
        vesting_factors[address] = base_vesting * consistency
    
    return vesting_factors
```

**How This Defeats Attack 1:**
```
SCENARIO: Hopper with 100 GH/s finds 100 shares, then leaves placeholder

With COUNT-BASED tenure (vulnerable):
  - Total shares: 101 (100 old + 1 new)
  - Vesting: min(1.0, 101/100) = 100%
  - ATTACK SUCCEEDS

With WORK-BASED tenure + consistency check:
  - Total work: 100 * high_diff + 1 * low_diff ≈ 10,000 + 0.01 = 10,000.01
  - Recent work (last 25%): 1 * low_diff = 0.01
  - Expected recent: 10,000.01 * 0.25 = 2,500
  - Consistency: 0.01 / 2,500 = 0.000004 (essentially 0!)
  - Final vesting: base * 0.000004 ≈ 0%
  - ATTACK DEFEATED - old shares don't count!
```

---

**Additional Attack Vectors Identified:**

| Attack | Description | Mitigation |
|--------|-------------|------------|
| **Tenure farming** | Keep weak miner to maintain share count | Work-based + consistency check |
| **Address reuse** | Same hopper returns with historical tenure | Time-decay on old shares |
| **Address sharing** | Multiple hoppers share address | Consistency check detects hashrate changes |
| **Slow ramp down** | Gradually reduce hashrate to avoid detection | Exponential recency weighting |
| **Split addresses** | Use multiple addresses to limit exposure | Per-pool minimum difficulty floor |

---

**REFINED SOLUTION: Multi-Factor Vesting**

Combine multiple signals for robust anti-gaming:

```python
def calculate_robust_vesting(tracker, tip_hash, lookback, address):
    """
    Multi-factor vesting calculation resistant to gaming.
    
    Factors:
    1. Work contribution (not just share count)
    2. Consistency (recent vs historical hashrate)
    3. Recency (exponential decay on old shares)
    """
    RECENCY_HALF_LIFE = lookback // 4  # Shares lose half weight every quarter window
    
    total_decayed_work = 0
    recent_work = 0
    share_index = 0
    
    for share in tracker.get_chain(tip_hash, lookback):
        if share.share_info['share_data']['address'] != address:
            continue
            
        work = bitcoin_data.target_to_average_attempts(share.target)
        
        # Exponential decay based on age
        age_factor = 0.5 ** (share_index / RECENCY_HALF_LIFE)
        decayed_work = work * age_factor
        
        total_decayed_work += decayed_work
        
        if share_index < RECENCY_HALF_LIFE:
            recent_work += work
        
        share_index += 1
    
    # Vesting based on decayed work
    # This naturally handles:
    # - Old shares matter less (decay)
    # - Consistent miners still have high total (continuous contribution)
    # - Hoppers have low total (their old shares decayed)
    
    WORK_THRESHOLD = net.SHARE_PERIOD * lookback * 0.5  # Adjusted for decay
    vesting = min(1.0, total_decayed_work / WORK_THRESHOLD)
    
    return vesting
```

**Why Exponential Decay Works:**
```
HONEST MINER (consistent 1 GH/s):
  - Finds ~1 share per period continuously
  - Each old share decays, but NEW shares added
  - Steady state: constant decayed_work sum
  - Vesting: 100% (stable)

HOPPER (100 GH/s spike, then leaves):
  - Day 1: Finds 100 shares at high diff, decayed_work = HIGH
  - Day 2: No new shares, old shares decay by 50%
  - Day 3: No new shares, old shares decay to 25%
  - Day 7: Old shares decayed to ~1.5%
  - Vesting drops rapidly even without consistency check!
```

---

**Summary of Gaming Resistance:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ANTI-GAMING MEASURES                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  COUNT-BASED TENURE (vulnerable):                                           │
│  └─ Gaming: Keep 1 weak miner to maintain share count                       │
│  └─ Result: Old high-diff shares still count at 100%                        │
│                                                                             │
│  WORK-BASED TENURE (better):                                                │
│  └─ Gaming: Keep weak miner... but work contribution is tiny                │
│  └─ Result: Need consistency check to catch hashrate drop                   │
│                                                                             │
│  WORK + CONSISTENCY CHECK (good):                                           │
│  └─ Gaming: Gradually ramp down to avoid detection                          │
│  └─ Result: Harder but possible with careful timing                         │
│                                                                             │
│  EXPONENTIAL DECAY + WORK (★ RECOMMENDED):                                  │
│  └─ Gaming: Very difficult - old shares ALWAYS decay                        │
│  └─ Leaving = vesting drops exponentially, no way to prevent                │
│  └─ Must continuously contribute to maintain vesting                        │
│  └─ Natural solution: rewards SUSTAINED contribution                        │
│                                                                             │
│  COMBINED APPROACH:                                                         │
│  └─ Primary: Exponential decay on share weight                              │
│  └─ Secondary: Consistency check (recent vs total)                          │
│  └─ Failsafe: Time-based emergency difficulty adjustment                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.7 Implementation Considerations

**Backward Compatibility:**
- This is a LOCAL calculation, not part of share structure
- Each node can implement independently
- V35 and V36 can coexist with different difficulty algorithms
- Share chain remains valid, only work generation changes

**Testing Required:**
- Verify difficulty doesn't oscillate wildly on hashrate changes
- Test recovery when hashrate returns
- Ensure no gaming by strategic disconnection

### 10.8 Integration with V36

This fix could be:
1. **V35.1 hotfix** - Deploy independently of V36
2. **V36 feature** - Bundle with merged mining upgrade
3. **Both** - Fix V35 immediately, inherit in V36

**Recommendation:** Fix as V35.1 hotfix since:
- Benefits all miners immediately
- Not dependent on V36 adoption
- Critical for network stability

### 10.9 Metrics and Monitoring

Add monitoring for difficulty health:

```python
# Web dashboard endpoint: /difficulty_health
def get_difficulty_health(tracker, best_share_hash, net):
    """
    Return difficulty health metrics for monitoring.
    """
    last_share = tracker.items[best_share_hash]
    time_since_share = time.time() - last_share.timestamp
    expected_time = net.SHARE_PERIOD
    
    return {
        'time_since_last_share': time_since_share,
        'expected_share_time': expected_time,
        'share_delay_ratio': time_since_share / expected_time,
        'current_difficulty': bitcoin_data.target_to_difficulty(last_share.target),
        'is_stale': time_since_share > expected_time * 10,
        'emergency_mode': time_since_share > expected_time * 20,
        'estimated_time_to_share': calculate_estimated_time(tracker, net),
    }
```

### 10.10 Summary: Difficulty Stagnation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  KEY FINDINGS                                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PROBLEM:                                                                   │
│  └─ Difficulty adjustment requires NEW shares                               │
│  └─ High difficulty prevents new shares from being found                    │
│  └─ Death spiral when hashrate drops suddenly                               │
│                                                                             │
│  IMPACT:                                                                    │
│  └─ Pool hopping damages remaining miners                                   │
│  └─ Network splits leave miners stranded                                    │
│  └─ Small miners punished for large miners' behavior                        │
│                                                                             │
│  SOLUTION EVOLUTION:                                                        │
│                                                                             │
│  A) TIME DECAY (Reactive failsafe):                                         │
│     └─ If no share in 20x expected time, decay difficulty                   │
│     └─ Simple emergency brake for extreme cases                             │
│                                                                             │
│  B) SHARE COUNT VESTING (Vulnerable to gaming):                             │
│     └─ Vesting based on miner's share count                                 │
│     └─ FLAW: Keep weak miner to farm tenure                                 │
│                                                                             │
│  C) WORK-BASED VESTING (Better but gameable):                               │
│     └─ Vesting based on work contribution, not count                        │
│     └─ Add consistency check (recent vs historical)                         │
│     └─ FLAW: Can slowly ramp down to avoid detection                        │
│                                                                             │
│  D) EXPONENTIAL DECAY ON SHARES (★ RECOMMENDED):                            │
│     └─ All shares lose weight over time (half-life decay)                   │
│     └─ Recent shares count more than old shares                             │
│     └─ Hopper leaves → their shares decay rapidly                           │
│     └─ Consistent miner → new shares replace decayed ones                   │
│     └─ NATURAL: Rewards sustained contribution, no gaming possible          │
│                                                                             │
│  COMBINED DEFENSE:                                                          │
│  └─ PRIMARY: Exponential decay on share weight for difficulty calc          │
│  └─ SECONDARY: Consistency check (detect sudden hashrate drops)             │
│  └─ FAILSAFE: Time-based emergency adjustment (network split, etc.)         │
│                                                                             │
│  IMPLEMENTATION:                                                            │
│  └─ Local calculation change (no protocol change needed)                    │
│  └─ Only affects difficulty calculation, NOT payouts                        │
│  └─ Can be V35.1 hotfix independent of V36                                  │
│  └─ Backward compatible with existing share chain                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 11: MWEB Compatibility Issue (Discovered Feb 2026)

### 11.1 Problem Discovery

During isolated testnet compatibility testing, we discovered that **unpatched jtoomim/p2pool nodes suffer significant hashrate loss** due to MWEB (MimbleWimble Extension Block) transaction parsing failures on Litecoin mainnet.

**Test Environment:**
- Node .30: Original jtoomim/p2pool (unpatched)
- Nodes .29, .31: Our modified codebase with MWEB handling
- All nodes connected to Litecoin mainnet via shared litecoind

### 11.2 MWEB Background

MWEB (MimbleWimble Extension Block) activated on Litecoin mainnet in **May 2022**. It introduces:
- Confidential transactions with Pedersen commitments
- HogEx (Hogwarts Express) transaction format
- Extension blocks for privacy-preserving transactions

MWEB transactions have a different serialization format that standard Bitcoin transaction parsers cannot decode.

### 11.3 jtoomim Failure Mode

When jtoomim's `getwork()` encounters an MWEB transaction:

```python
# jtoomim helper.py line 102 - NO error handling!
unpacked = bitcoin_data.tx_type.unpack(packed)
# → struct.error: unpack str size too short for format
```

The `@deferral.retry('Error getting work from bitcoind:', 3)` decorator:
1. Catches the exception
2. Prints error message
3. Retries after 3 seconds
4. Repeats until MWEB transaction leaves mempool

**Observed from .30 node logs (46 hours):**
```
getwork SUCCESS:  140 times
getwork FAILED:   6,635 times
─────────────────────────────
Failure rate:     97%
Average retries:  47 per success (~141 seconds delay)
```

### 11.4 Impact Analysis

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  JTOOMIM MWEB IMPACT                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DURING RETRY LOOP:                                                         │
│  └─ Node continues mining on LAST SUCCESSFUL template                       │
│  └─ When new LTC block arrives, template becomes STALE                      │
│  └─ All work during retry = 100% WASTED (orphan shares)                     │
│                                                                             │
│  OBSERVED PATTERN:                                                          │
│    15:12:38 - New work! 271 tx                                              │
│    Error getting work (x6 retries)                                          │
│    15:13:41 - New work! 0 tx, 0 kB  ← Empty block after errors!             │
│    15:15:12 - New work! 238 tx                                              │
│                                                                             │
│  LOSSES:                                                                    │
│  └─ ~15-25% effective hashrate lost to stale mining                         │
│  └─ 100% of MWEB transaction fees lost (never in template)                  │
│  └─ Higher orphan/stale share rate                                          │
│                                                                             │
│  ANNUAL IMPACT (per 0.1% network hashrate):                                 │
│  └─ Expected blocks: ~210/year                                              │
│  └─ Lost to MWEB bug: ~30-50 blocks/year                                    │
│  └─ Value: ~190-310 LTC/year + all MWEB fees                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.5 Our Fix

We added try/except handling around transaction parsing:

```python
# Our helper.py - graceful MWEB handling
try:
    unpacked = bitcoin_data.tx_type.unpack(packed)
except Exception as e:
    # Store MWEB tx as raw bytes for block inclusion
    skipped_mweb += 1
    unpacked = {'_raw_tx': packed, '_raw_size': len(packed), '_mweb': True}
```

**Our node stats (same period):**
```
getwork SUCCESS:  16,690 times
getwork FAILED:   160 times
─────────────────────────────
Failure rate:     <1%
```

### 11.6 Share Compatibility with MWEB

**Critical Finding:** V35 shares remain compatible even when containing MWEB transactions!

```python
# p2p.py handle_shares() - VERSION >= 34 behavior
if 13 <= wrappedshare['type'] < 34:
    # OLD: Must lookup all tx hashes in known_txs (would fail for MWEB!)
    for tx_hash in share.share_info['new_transaction_hashes']:
        if tx_hash not in known_txs:
            self.disconnect()  # Would disconnect!
else:
    # V35+: No transaction lookup required!
    txs = None  # Share accepted without tx verification

# data.py check() - VERSION >= 34 behavior  
if self.VERSION < 34:
    other_tx_hashes = [...]  # Must verify transactions
else:
    other_tx_hashes = []  # V35+: Skip tx verification!
```

**Result:** 
- V35 shares don't include inline transaction data
- Legacy nodes CAN receive and verify our V35 shares
- MWEB handling only needed for block template generation
- Share propagation unaffected by MWEB

### 11.7 Block Submission Consideration

When a share finds a block:
- The node that found it must have full transaction data
- Our nodes: Have MWEB txs as raw bytes → CAN submit block
- jtoomim nodes: Missing MWEB txs → Would submit incomplete block

**However:** jtoomim nodes rarely include MWEB txs in their templates (they fail before reaching that tx), so this is unlikely to cause issues in practice.

### 11.8 Recommendations

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MWEB FIX RECOMMENDATIONS                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. CRITICAL FIX (Already implemented in our codebase):                     │
│     └─ Add try/except around tx_type.unpack() in helper.py                  │
│     └─ Store unparseable txs as raw bytes with _mweb flag                   │
│     └─ Include raw MWEB txs in block template                               │
│                                                                             │
│  2. UPSTREAM PR (Recommended):                                              │
│     └─ Submit fix to jtoomim/p2pool repository                              │
│     └─ Benefits all Litecoin P2Pool miners                                  │
│     └─ Prevents 15-25% hashrate waste network-wide                          │
│                                                                             │
│  3. V36 INCLUSION:                                                          │
│     └─ MWEB fix already part of V36 codebase                                │
│     └─ Migration to V36 automatically fixes MWEB issue                      │
│     └─ Additional incentive for V36 adoption                                │
│                                                                             │
│  4. MONITORING:                                                             │
│     └─ Track [MWEB] log messages for transaction counts                     │
│     └─ Compare getwork success rates                                        │
│     └─ Monitor stale share rates                                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.9 Summary: MWEB Issue

**The Problem:**
- jtoomim/p2pool crashes on MWEB transaction parsing
- 97% of getwork attempts fail when MWEB txs in mempool
- Results in ~15-25% effective hashrate loss + lost fees

**Our Solution:**
- Graceful error handling stores MWEB as raw bytes
- <1% failure rate
- Full fee capture from MWEB transactions

**Compatibility:**
- V35 shares work fine across MWEB/non-MWEB nodes
- No protocol change needed
- Pure implementation fix

---

## Appendix A: Chain ID Reference

| Chain | Chain ID (hex) | Chain ID (dec) | Notes |
|-------|----------------|----------------|-------|
| Dogecoin | 0x00000062 | 98 | Reversed from auxpow magic |
| Litecoin | 0x00000000 | 0 | Parent chain (not needed) |
| Bellscoin | TBD | TBD | Future support |
| Reserved | 0x00000001-0x00000007 | 1-7 | Reserved |

---

## Appendix B: Example Merged Block Distribution

**Scenario:** Merged block found with 10,000 DOGE reward

**Share Chain Composition:**
- 100 V36 shares (5,000 weight total)
- 150 pre-V36 P2PKH shares (4,000 weight total)
- 25 pre-V36 P2SH shares (1,000 weight total)
- Total: 275 shares, 10,000 weight

**V36 Adoption:** 50% (5,000 / 10,000)

**Incentive Rate:** 5% (0.10 * (1 - 0.50))

**Distribution:**
```
Total Reward:       10,000 DOGE

Incentive Pool:        500 DOGE (5%)
Primary Pool:        9,500 DOGE (95%)

Unconvertible Portion: 1,000 DOGE (10% of total)
Redistributed to Primary: +1,000 DOGE

Final Primary Pool:  10,500 DOGE (9,500 + 1,000 redistribution)

V36 Miners (5,000 weight):
  10,500 * (5,000/5,000) = 10,500 DOGE total
  Average per V36 share: 105 DOGE

Pre-V36 P2PKH (4,000 weight):
  500 * (4,000/4,000) = 500 DOGE total
  Average per pre-V36 share: 3.33 DOGE

Pre-V36 P2SH (1,000 weight):
  0 DOGE (address not compatible)

Upgrade Incentive:
  V36 miner earns 105 DOGE/share
  Pre-V36 P2PKH earns 3.33 DOGE/share
  Ratio: 31.5x more rewards for upgrading!
```

---

## Part 9: Donation Script Migration Plan

### 9.1 The Problem: Lost Private Key

The original P2Pool donation script is a **P2PK (Pay-to-Public-Key)** format with a **LOST PRIVATE KEY**:

```python
# Original DONATION_SCRIPT (P2PK format) - PRIVATE KEY LOST!
# P2PK script: <65-byte uncompressed pubkey> OP_CHECKSIG
DONATION_SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')

# This pubkey hash160 is: d03da6fca390166d020be0e7c28ac8cc70f58403
# Which corresponds to addresses (P2PKH equivalent):
# - Bitcoin:  1Kz5QaUPDtKrj5SqW5tFkn7WZh8LmQaQi4
# - Litecoin: LeD2fnnDJYZuyt8zgDsZ2oBGmuVcxGKCLd
# - Dogecoin: DQ8AwqR2XJE9G5dSEfspJYH7Spre85dj6L
#
# NOTE: P2PK outputs can be spent without revealing the address,
# but the private key is LOST so these funds are UNSPENDABLE!
```

**Impact:**
- Every P2Pool block sends 0.5-1% to this address
- Estimated lost funds on Litecoin: ~10,000+ LTC over the years
- Funds accumulate but can NEVER be spent
- This is wasteful and reduces miner rewards

### 9.2 CRITICAL CONSTRAINT: Coinbase Must Be Identical Across All Nodes!

**⚠️ THIS IS THE KEY CONSTRAINT THAT LIMITS OUR OPTIONS ⚠️**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  WHY DONATION CANNOT CHANGE UNTIL V35 IS DEPRECATED                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  BLOCK VALIDATION REQUIREMENT:                                              │
│  ├─ When ANY share finds a block, ALL P2Pool nodes must agree on coinbase   │
│  ├─ get_expected_payouts() calculates payouts for ALL miners in PPLNS       │
│  ├─ This function uses donation_script_to_address() → DONATION_SCRIPT       │
│  └─ ALL nodes must compute IDENTICAL coinbase outputs!                      │
│                                                                             │
│  IF V36 USED DIFFERENT DONATION SCRIPT:                                     │
│  ├─ V36 node: donation → SECONDARY_DONATION_SCRIPT                          │
│  ├─ V35 node: donation → DONATION_SCRIPT                                    │
│  ├─ RESULT: Different coinbase structure!                                   │
│  └─ V35 nodes would REJECT blocks from V36 nodes!                           │
│                                                                             │
│  UNLIKE MERGED MINING (which is NEW and V35 doesn't verify):                │
│  ├─ Donation is part of EXISTING coinbase verification                      │
│  ├─ V35 nodes verify ALL blocks against their expected payout structure     │
│  └─ Cannot use different donation until V35 is GONE!                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.3 Why gentx_before_refhash Doesn't Help Here

You might think: "V36 can have different gentx_before_refhash, so it can use different donation!"

**WRONG.** Here's why:

```python
# gentx_before_refhash is for SHARE VERIFICATION, not BLOCK PAYOUT CALCULATION

# Share verification:
# - Each share version has its own gentx_before_refhash
# - V35 share verified with V35's gentx_before_refhash
# - V36 share verified with V36's gentx_before_refhash
# - This works fine for SHARES

# Block payout calculation:
# - When block found, get_expected_payouts() is called
# - This calculates payouts for ALL miners in PPLNS chain
# - Uses SINGLE donation_script_to_address() for ALL shares
# - ALL nodes must compute SAME result!

# The coinbase that actually goes on the blockchain must:
# 1. Match the winning share's hash_link (which share found the block)
# 2. Be accepted by ALL P2Pool nodes (for share chain validation)
# 3. Be consistent with get_expected_payouts() on ALL nodes

# PROBLEM: If V36 coinbase has SECONDARY_DONATION_SCRIPT,
#          but V35 nodes expect DONATION_SCRIPT,
#          V35 nodes reject the block as invalid!
```

### 9.4 The ONLY Valid Migration Path

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DONATION MIGRATION: MUST WAIT FOR V35 DEPRECATION                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PHASE 0: CURRENT STATE (V35 Network)                                       │
│  ├─ All blocks: 100% donation to DONATION_SCRIPT (burned)                   │
│  ├─ Our nodes: Use SECONDARY_DONATION_ENABLED hack                          │
│  │   └─ Adds SECOND output (doesn't change donation amount calculation!)    │
│  └─ This works because we ADD an output, not CHANGE the donation            │
│                                                                             │
│  PHASE 1: V36 DEPLOYMENT (0-95% V36 adoption)                               │
│  ├─ V36 nodes deployed, coexisting with V35 nodes                           │
│  ├─ Coinbase STILL uses DONATION_SCRIPT for donation calculation            │
│  ├─ V36 gentx_before_refhash: Keep same as V35 for now!                     │
│  │   └─ OR: V36 shares only verified by V36 nodes (V35 rejects anyway)      │
│  └─ SECONDARY_DONATION_ENABLED hack continues (adds 2nd output)             │
│                                                                             │
│  PHASE 2: V36 SUPERMAJORITY (95%+ V36 adoption)                             │
│  ├─ Version signaling shows >95% V36                                        │
│  ├─ Prepare for flag day                                                    │
│  └─ Announce deprecation timeline                                           │
│                                                                             │
│  PHASE 3: V35 DEPRECATION (Flag Day)                                        │
│  ├─ Bump MINIMUM_PROTOCOL_VERSION to reject V35 shares                      │
│  ├─ V35 nodes can no longer participate in share chain                      │
│  └─ NOW we can change donation calculation!                                 │
│                                                                             │
│  PHASE 4: POST-DEPRECATION (100% V36)                                       │
│  ├─ Update get_expected_payouts() to use SECONDARY_DONATION_SCRIPT          │
│  ├─ Update gentx_before_refhash to use SECONDARY_DONATION_SCRIPT            │
│  ├─ Remove SECONDARY_DONATION_ENABLED hack                                  │
│  └─ 100% of donations go to controlled address!                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.5 Why We CAN'T Do Per-Block Migration (Like Merged Mining)

**Merged Mining Rewards** - CAN be proportionally split:
- V35 doesn't have merged mining, so it doesn't verify merged outputs
- V36 can distribute merged rewards however it wants
- V35 nodes simply ignore merged outputs they don't understand

**Donation** - CANNOT be changed until V35 is gone:
- V35 DOES verify donation outputs
- V35 nodes use `get_expected_payouts()` which hard-codes DONATION_SCRIPT
- If coinbase doesn't match V35's expectation, V35 rejects the block
- Even if V36 share finds block, V35 nodes must accept it!

### 9.6 Current Transitional Solution: SECONDARY_DONATION_ENABLED

Our current hack works because it ADDS a second output without changing the primary:

```python
# Current implementation (p2pool/data.py):

if SECONDARY_DONATION_ENABLED and secondary_donation_address and not verifying:
    secondary_donation_amount = total_donation // 2  # 50% to secondary
    primary_donation_amount = total_donation - secondary_donation_amount
    amounts[secondary_donation_address] = amounts.get(secondary_donation_address, 0) + secondary_donation_amount
    amounts[donation_address] = amounts.get(donation_address, 0) + primary_donation_amount
else:
    amounts[donation_address] = amounts.get(donation_address, 0) + total_donation

# KEY: We only use this when `not verifying`!
# When verifying shares from others, we use their format (single donation)
# This means our shares have 2 donation outputs, but we still verify theirs correctly
```

**Why this works:**
- We add SECONDARY output to OUR shares only
- When verifying THEIR shares, we use their expected format
- The total donation AMOUNT stays the same
- We just split it between two addresses

**Limitation:**
- 50% still goes to burned address
- Can't improve this until V35 is gone

### 9.7 V36 Donation Strategy: Continue the Hack

For V36, we continue the same strategy:

```python
# V36 donation handling (BEFORE V35 deprecation):

class MergedMiningShare(BaseShare):
    VERSION = 36
    
    # IMPORTANT: Keep same gentx_before_refhash structure as V35!
    # This ensures coinbase format is compatible
    # (OR: Accept that V35 rejects V36 shares - that's expected anyway)
    gentx_before_refhash = pack.VarStrType().pack(DONATION_SCRIPT) + ...

# In generate_transaction:
# - Still calculate donation using DONATION_SCRIPT for compatibility
# - Still add SECONDARY_DONATION_SCRIPT as bonus output (not verifying)
# - V35 nodes can still verify our coinbase structure
```

### 9.8 Post-V35-Deprecation: Full Migration

Only AFTER V35 is deprecated (MINIMUM_PROTOCOL_VERSION bump):

```python
# V36 donation handling (AFTER V35 deprecation):

# Update donation calculation:
def donation_script_to_address(net):
    return bitcoin_data.script2_to_address(SECONDARY_DONATION_SCRIPT, net)

# Update gentx_before_refhash:
class MergedMiningShare(BaseShare):
    gentx_before_refhash = pack.VarStrType().pack(SECONDARY_DONATION_SCRIPT) + ...

# Remove dual-donation hack:
# - Single donation output to SECONDARY_DONATION_SCRIPT
# - 100% of donation saved!
```

### 9.9 Timeline Comparison: Merged Mining vs Donation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FEATURE MIGRATION TIMELINES                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  MERGED MINING REWARDS (Gradual from Day 1):                                │
│  ├─ Day 1: V36 deployed → V36 miners get full merged rewards                │
│  ├─ Week 2: 30% V36 → 30% of merged rewards to V36 miners                   │
│  ├─ Month 1: 70% V36 → 70% of merged rewards to V36 miners                  │
│  └─ Migration complete when V36 dominant in PPLNS                           │
│                                                                             │
│  DONATION (Flag Day after 95% V36):                                         │
│  ├─ Day 1 to Flag Day: BOTH donations (50/50 split continues)               │
│  ├─ Flag Day: MINIMUM_PROTOCOL_VERSION bump, V35 rejected                   │
│  └─ Post Flag Day: 100% donation to controlled address                      │
│                                                                             │
│  WHY THE DIFFERENCE:                                                        │
│  ├─ Merged rewards: NEW feature, V35 doesn't verify                         │
│  └─ Donation: EXISTING feature, V35 DOES verify coinbase structure          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.10 Dashboard: Show Donation Migration Status

```javascript
// In web-static/dashboard.html

function loadDonationStatus() {
    d3.json('../donation_stats', function(stats) {
        if (!stats) return;
        
        var v36Pct = stats.v36_adoption * 100;
        var threshold = 95;
        
        d3.select('#donation_status').html(`
            <div class="donation-status">
                <h4>Donation Migration Status</h4>
                <p>V36 Adoption: ${v36Pct.toFixed(1)}% (need ${threshold}% for migration)</p>
                <div class="progress-bar">
                    <div class="progress" style="width: ${Math.min(v36Pct, 100)}%"></div>
                    <div class="threshold" style="left: ${threshold}%"></div>
                </div>
                <p class="donation-split">
                    Current: 50% saved / 50% burned<br>
                    After migration: 100% saved
                </p>
                ${v36Pct >= threshold 
                    ? '<p class="ready">✓ Ready for donation migration! Awaiting flag day.</p>'
                    : '<p class="waiting">Upgrade to V36 to help reach migration threshold!</p>'
                }
            </div>
        `);
    });
}
```

### 9.11 Summary: Donation Migration is a Flag Day Event

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  KEY TAKEAWAYS                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Donation migration CANNOT be gradual like merged mining                 │
│     └─ All nodes must agree on coinbase structure                           │
│                                                                             │
│  2. Must wait for V35 deprecation (flag day)                                │
│     └─ 95%+ V36 adoption triggers deprecation timeline                      │
│     └─ MINIMUM_PROTOCOL_VERSION bump removes V35 nodes                      │
│                                                                             │
│  3. Until flag day, use SECONDARY_DONATION_ENABLED hack                     │
│     └─ 50/50 split between old (burned) and new (saved)                     │
│     └─ Better than 100% burned, but not ideal                               │
│                                                                             │
│  4. After flag day, full migration                                          │
│     └─ 100% donation to controlled address                                  │
│     └─ No more burned funds!                                                │
│                                                                             │
│  5. This is fundamentally different from merged mining                      │
│     └─ Merged mining: V35 doesn't verify → gradual migration OK             │
│     └─ Donation: V35 DOES verify → flag day required                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

# Part 12: V36 Share Size Optimization

## 12.1 The Problem: Share Size Growth

V36 introduces per-miner merged mining addresses, which significantly increases share payload size:

### Current V35 Share Structure (~700 bytes)
```
V35 Share:
├── Header (80 bytes)
│   ├── version (4)
│   ├── prev_block (32)
│   ├── merkle_root (32)
│   ├── timestamp (4)
│   ├── bits (4)
│   └── nonce (4)
├── Share Info (~200 bytes)
│   ├── share_data
│   │   ├── previous_share_hash (32)
│   │   ├── coinbase (variable, ~50-100)
│   │   ├── nonce (4)
│   │   ├── pubkey_hash (20)         ← SINGLE address
│   │   ├── subsidy (8)
│   │   ├── donation (2)
│   │   └── stale_info (1)
│   ├── new_transaction_hashes (var)
│   └── transaction_hash_refs (var)
├── Merkle Branch (~320 bytes)
│   └── 10 × 32-byte hashes
└── Signature (~70 bytes)

TOTAL: ~700 bytes per share
```

### Naive V36 Addition (~1100 bytes)
```
V36 Share (naive):
├── [All V35 fields] (~700 bytes)
└── merged_mining_addresses (~400 bytes NEW)
    ├── count (1)
    ├── chain_id + address (1 + 20) × N    ← Per chain!
    │   ├── Litecoin (21)
    │   ├── Dogecoin (21)
    │   ├── Bellscoin (21)
    │   └── ... up to 16 chains
    └── derivation_mode (1)

TOTAL: ~1100 bytes per share (+57% increase!)
```

### Impact Analysis
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  BANDWIDTH IMPACT AT SCALE                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Litecoin P2Pool Mainnet:                                                   │
│  - Current share rate: ~1 share/30 seconds = 2880 shares/day                │
│  - V35: 2880 × 700 bytes = 2.0 MB/day                                       │
│  - V36 naive: 2880 × 1100 bytes = 3.2 MB/day (+1.2 MB)                      │
│                                                                             │
│  With target 1 share/10 seconds (higher hashrate):                          │
│  - 8640 shares/day                                                          │
│  - V35: 6.0 MB/day                                                          │
│  - V36 naive: 9.5 MB/day (+3.5 MB)                                          │
│                                                                             │
│  Seems small, but consider:                                                 │
│  - Full share chain sync from 0: 10× more data                              │
│  - Mobile/low-bandwidth miners affected                                     │
│  - More data = more latency = more orphans                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12.2 Optimization Strategies

### Strategy 1: Derivation Mode (Recommended - Simplest)

**Insight:** Most miners use the SAME address for ALL chains (derivation from primary).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DERIVATION MODE APPROACH                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Instead of storing all addresses:                                          │
│                                                                             │
│  Case A: All addresses derived from primary (90%+ of miners)                │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  derivation_mode: 0x01 (DERIVE_ALL)                             │        │
│  │  primary_pubkey_hash: 20 bytes                                  │        │
│  │  TOTAL: 21 bytes                                                │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  Case B: Different addresses per chain (power users)                        │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  derivation_mode: 0x00 (EXPLICIT)                               │        │
│  │  address_count: 1 byte                                          │        │
│  │  addresses: N × (chain_id:1 + pubkey_hash:20)                   │        │
│  │  TOTAL: 2 + (21 × N) bytes                                      │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  SAVINGS: 400 bytes → 21 bytes for 90% of shares!                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Implementation:**
```python
class DerivationMode:
    EXPLICIT = 0x00          # All addresses listed explicitly
    DERIVE_ALL = 0x01        # Derive all from primary pubkey_hash
    DERIVE_WITH_OVERRIDE = 0x02  # Derive all, with specific overrides

# Encoding
if all addresses are same pubkey_hash:
    mode = DERIVE_ALL
    payload = pubkey_hash  # 20 bytes
elif most addresses derive, some override:
    mode = DERIVE_WITH_OVERRIDE
    payload = pubkey_hash + override_count + [(chain_id, alt_pubkey_hash), ...]
else:
    mode = EXPLICIT
    payload = count + [(chain_id, pubkey_hash), ...]
```

### Strategy 2: Coinbase Commitment (Advanced)

**Insight:** V34 doesn't include transactions inline - shares reference block template. Same approach for addresses!

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  COINBASE COMMITMENT APPROACH                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Instead of including full addresses in share:                              │
│                                                                             │
│  Share payload:                                                             │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  merged_address_commitment: SHA256(sorted addresses) = 32 bytes │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  Verification:                                                              │
│  - When share received, check if we have addresses for this commitment      │
│  - If not, request via separate P2P message: get_merged_addresses           │
│  - Cache commitment → addresses mapping (persistent across restarts)        │
│                                                                             │
│  Benefits:                                                                  │
│  - Fixed 32 bytes regardless of chain count                                 │
│  - Addresses fetched once, cached forever                                   │
│  - Same miner = same commitment = no re-fetch                               │
│                                                                             │
│  Drawbacks:                                                                 │
│  - Extra P2P round-trip for first share from new miner                      │
│  - Need new P2P message types                                               │
│  - Cache persistence complexity                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Strategy 3: Miner Registry (Future)

**Insight:** Most miners submit many shares. Register address set once, reference by ID.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MINER REGISTRY APPROACH                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  First share from miner:                                                    │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  registration_flag: 0x01                                        │        │
│  │  miner_id: new unique 4-byte ID                                 │        │
│  │  full_addresses: all addresses (~400 bytes)                     │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  Subsequent shares:                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  registration_flag: 0x00                                        │        │
│  │  miner_id: existing 4-byte ID                                   │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  SAVINGS: 400 bytes → 5 bytes (after first share)                           │
│                                                                             │
│  Challenges:                                                                │
│  - miner_id collision handling                                              │
│  - Registry persistence and sync                                            │
│  - Share chain verification needs full registry                             │
│  - "Orphan" shares if registration share lost                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Strategy 4: General Compression (Complementary)

**Insight:** Compression works well on structured, repetitive data.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  COMPRESSION APPROACHES                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Option A: LZ4 (fast, moderate compression)                                 │
│  - Compression ratio: 40-50% on share data                                  │
│  - Speed: 400 MB/s compress, 1000+ MB/s decompress                          │
│  - CPU impact: negligible                                                   │
│                                                                             │
│  Option B: ZSTD (balanced)                                                  │
│  - Compression ratio: 50-60% on share data                                  │
│  - Speed: 200 MB/s compress, 500 MB/s decompress                            │
│  - Allows dictionary training for even better ratios                        │
│                                                                             │
│  Option C: Zlib (universal, Python built-in)                                │
│  - Compression ratio: 40-55% on share data                                  │
│  - Speed: 50 MB/s compress, 150 MB/s decompress                             │
│  - No additional dependencies                                               │
│                                                                             │
│  Example with zlib level 6:                                                 │
│  - V36 naive 1100 bytes → ~550 bytes compressed                             │
│  - V36 + derivation 721 bytes → ~360 bytes compressed                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12.3 Recommended V36 Optimization Plan

### Phase 1: Derivation Mode (V36 Launch)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  V36 SHARE FORMAT WITH DERIVATION MODE                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  share_info:                                                                │
│    ...existing fields...                                                    │
│    merged_mining_version: 1 byte (0x01 for V36)                             │
│    merged_derivation_mode: 1 byte                                           │
│      └─ 0x00: EXPLICIT (full address list follows)                          │
│      └─ 0x01: DERIVE_ALL (single pubkey_hash, derive for all chains)        │
│      └─ 0x02: DERIVE_WITH_OVERRIDE (pubkey_hash + override list)            │
│    merged_payload: variable                                                 │
│      └─ For DERIVE_ALL: just the primary pubkey_hash (20 bytes)             │
│      └─ For EXPLICIT: count + [(chain_id, pubkey_hash), ...]                │
│      └─ For DERIVE_WITH_OVERRIDE: pubkey_hash + count + overrides           │
│                                                                             │
│  SIZE COMPARISON:                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │  Scenario                         V35    V36-naive  V36-optimized│       │
│  ├──────────────────────────────────────────────────────────────────┤       │
│  │  Single chain (just LTC)          700    721        721 (+3%)    │       │
│  │  2 chains, same address           700    742        722 (+3%)    │       │
│  │  4 chains, same address           700    784        722 (+3%)    │       │
│  │  16 chains, same address          700   1036        722 (+3%)    │       │
│  │  4 chains, all different          700    784        786 (+12%)   │       │
│  │  16 chains, all different         700   1036       1038 (+48%)   │       │
│  └──────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│  EXPECTED REAL-WORLD: 90%+ miners use DERIVE_ALL = ~722 bytes (+3%)         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase 2: Optional Compression (V36.1 or V37)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FUTURE: COMPRESSED SHARE FORMAT                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  share_envelope:                                                            │
│    compression_flag: 1 byte                                                 │
│      └─ 0x00: uncompressed (backward compatible)                            │
│      └─ 0x01: zlib compressed                                               │
│      └─ 0x02: lz4 compressed                                                │
│      └─ 0x03: zstd compressed                                               │
│    payload: compressed or raw share data                                    │
│                                                                             │
│  SIZE WITH LZ4:                                                             │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │  Scenario                          V36-opt  V36-opt+LZ4          │       │
│  ├──────────────────────────────────────────────────────────────────┤       │
│  │  Typical share (DERIVE_ALL)        722      ~360 (-50%)          │       │
│  │  Complex share (16 chains diff)   1038      ~550 (-47%)          │       │
│  └──────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│  NOTE: Compression can be negotiated per-peer at protocol handshake         │
│  - Old nodes see compression_flag=0x00, receive uncompressed                │
│  - New nodes negotiate best mutual compression                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase 3: Commitment Scheme (V37+ Long-term)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LONG-TERM: FULL COMMITMENT SCHEME                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  If merged mining scales to 50+ chains, commitment becomes worthwhile:      │
│                                                                             │
│  share_info:                                                                │
│    merged_commitment: SHA256(canonical_address_serialization) = 32 bytes    │
│                                                                             │
│  New P2P messages:                                                          │
│    get_merged_config(commitment_hash) → request full address mapping        │
│    merged_config(commitment_hash, addresses) → response with full mapping   │
│                                                                             │
│  Node behavior:                                                             │
│    on_share_received:                                                       │
│      if commitment not in cache:                                            │
│        request_merged_config(commitment)                                    │
│        queue share for later processing                                     │
│      else:                                                                  │
│        verify and process immediately                                       │
│                                                                             │
│  SIZE: Fixed 32 bytes regardless of chain count (vs 1000+ for 50 chains)    │
│                                                                             │
│  DEFERRED: Only implement if >16 chains become common                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12.4 Implementation Specification for V36

### Wire Format

```python
# V36 Share Extended Fields
merged_mining_fields = pack.ComposedType([
    ('mm_version', pack.IntType(8)),      # 1 byte: 0x01 for V36
    ('derivation_mode', pack.IntType(8)), # 1 byte: mode selector
    ('mm_payload', pack.VarStrType()),    # variable: depends on mode
])

# Mode 0x01 (DERIVE_ALL) payload:
derive_all_payload = pack.ComposedType([
    ('primary_pubkey_hash', pack.IntType(160)),  # 20 bytes
])

# Mode 0x00 (EXPLICIT) payload:
explicit_payload = pack.ComposedType([
    ('address_count', pack.IntType(8)),   # 1 byte: number of chains
    ('addresses', pack.ListType(pack.ComposedType([
        ('chain_id', pack.IntType(8)),        # 1 byte: chain identifier
        ('pubkey_hash', pack.IntType(160)),   # 20 bytes: address
    ]))),
])

# Mode 0x02 (DERIVE_WITH_OVERRIDE) payload:
override_payload = pack.ComposedType([
    ('primary_pubkey_hash', pack.IntType(160)),  # 20 bytes: default
    ('override_count', pack.IntType(8)),         # 1 byte: override count
    ('overrides', pack.ListType(pack.ComposedType([
        ('chain_id', pack.IntType(8)),           # 1 byte: chain to override
        ('pubkey_hash', pack.IntType(160)),      # 20 bytes: override address
    ]))),
])
```

### Encoder/Decoder

```python
def encode_merged_addresses(primary_hash, chain_addresses):
    """
    Encode merged mining addresses with optimal derivation mode.
    
    Args:
        primary_hash: Primary pubkey_hash (20 bytes)
        chain_addresses: dict of {chain_id: pubkey_hash}
    
    Returns:
        bytes: Optimally encoded payload
    """
    # Check if all addresses match primary
    all_same = all(addr == primary_hash for addr in chain_addresses.values())
    
    if all_same:
        # Mode 0x01: DERIVE_ALL
        return bytes([0x01, 0x01]) + primary_hash
    
    # Check how many differ from primary
    overrides = {k: v for k, v in chain_addresses.items() if v != primary_hash}
    
    if len(overrides) <= len(chain_addresses) // 2:
        # Mode 0x02: DERIVE_WITH_OVERRIDE (fewer overrides than matches)
        payload = bytes([0x01, 0x02]) + primary_hash + bytes([len(overrides)])
        for chain_id, addr in sorted(overrides.items()):
            payload += bytes([chain_id]) + addr
        return payload
    
    # Mode 0x00: EXPLICIT (all different)
    payload = bytes([0x01, 0x00, len(chain_addresses)])
    for chain_id, addr in sorted(chain_addresses.items()):
        payload += bytes([chain_id]) + addr
    return payload


def decode_merged_addresses(payload, supported_chains):
    """
    Decode merged mining addresses from share payload.
    
    Args:
        payload: bytes from share
        supported_chains: list of chain_ids this network supports
    
    Returns:
        dict of {chain_id: pubkey_hash}
    """
    mm_version = payload[0]
    assert mm_version == 0x01, f"Unknown merged mining version: {mm_version}"
    
    mode = payload[1]
    
    if mode == 0x01:  # DERIVE_ALL
        primary_hash = payload[2:22]
        return {chain_id: primary_hash for chain_id in supported_chains}
    
    elif mode == 0x02:  # DERIVE_WITH_OVERRIDE
        primary_hash = payload[2:22]
        override_count = payload[22]
        result = {chain_id: primary_hash for chain_id in supported_chains}
        offset = 23
        for _ in range(override_count):
            chain_id = payload[offset]
            addr = payload[offset+1:offset+21]
            result[chain_id] = addr
            offset += 21
        return result
    
    elif mode == 0x00:  # EXPLICIT
        count = payload[2]
        result = {}
        offset = 3
        for _ in range(count):
            chain_id = payload[offset]
            addr = payload[offset+1:offset+21]
            result[chain_id] = addr
            offset += 21
        return result
    
    else:
        raise ValueError(f"Unknown derivation mode: {mode}")
```

---

## 12.5 Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  V36 SHARE SIZE OPTIMIZATION SUMMARY                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PROBLEM:                                                                   │
│  - V36 adds per-miner merged addresses                                      │
│  - Naive implementation: +400 bytes (+57%) per share                        │
│  - Impacts bandwidth, sync time, latency                                    │
│                                                                             │
│  SOLUTION (V36 Launch):                                                     │
│  - Derivation mode encoding                                                 │
│  - 90%+ miners use DERIVE_ALL: only +22 bytes (+3%)                         │
│  - Power users with different addresses: still supported                    │
│                                                                             │
│  FUTURE OPTIMIZATIONS:                                                      │
│  - V36.1: Optional LZ4/zstd compression (-50% overall)                      │
│  - V37+: Commitment scheme if >16 chains common                             │
│                                                                             │
│  FINAL SIZES:                                                               │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │  Version    Typical Share    Notes                               │       │
│  ├──────────────────────────────────────────────────────────────────┤       │
│  │  V35        ~700 bytes       Current baseline                    │       │
│  │  V36 naive  ~1100 bytes      Without optimization                │       │
│  │  V36 opt    ~722 bytes       With derivation mode (90% of shares)│       │
│  │  V36+LZ4    ~360 bytes       With compression (future)           │       │
│  └──────────────────────────────────────────────────────────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

# Part 13: V36 Security Analysis

## 13.1 P2Pool Block Analysis - MWEB Handling

Analysis of recent P2Pool-mined Litecoin blocks reveals how jtoomim's P2Pool handles MWEB:

### Blocks Examined

| Block | Height | TXs | MWEB Kernels | MWEB TXOs | Mined By |
|-------|--------|-----|--------------|-----------|----------|
| [2751101](https://chainz.cryptoid.info/ltc/block.dws?2751101.htm) | 2,751,101 | 359 | **0** | 76,410 | Toomim Bros/p2pool |
| [2752965](https://chainz.cryptoid.info/ltc/block.dws?2752965.htm) | 2,752,965 | 258 | **0** | 77,176 | Toomim Bros/p2pool |
| [2754657](https://chainz.cryptoid.info/ltc/block.dws?2754657.htm) | 2,754,657 | 82 | **0** | 78,055 | Toomim Bros/p2pool |
| [2760196](https://chainz.cryptoid.info/ltc/block.dws?2760196.htm) | 2,760,196 | 609 | **0** | 80,656 | Toomim Bros/p2pool |
| [2770170](https://chainz.cryptoid.info/ltc/block.dws?2770170.htm) | 2,770,170 | 146 | **0** | 87,814 | Toomim Bros/p2pool |
| [2870037](https://chainz.cryptoid.info/ltc/block.dws?2870037.htm) | 2,870,037 | 154 | **0** | 156,756 | Toomim Bros/p2pool |

### Key Findings

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  JTOOMIM P2POOL MWEB HANDLING                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DISCOVERY: jtoomim P2Pool includes ZERO MWEB transactions!                 │
│                                                                             │
│  Evidence:                                                                  │
│  - All 6 blocks have num_kernels: 0 (no MWEB txs included)                  │
│  - The num_txos field (76k-156k) is cumulative UTXO count, not block txs    │
│  - Checked actual block tx data: no ismweb:true in any vin/vout             │
│                                                                             │
│  Coinbase Signature: "Toomim Bros/p2pool"                                   │
│  SegWit Witness: "[P2Pool][P2Pool][P2Pool][P2Pool]"                         │
│                                                                             │
│  CONSEQUENCE:                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  P2Pool miners on jtoomim's code are LOSING ALL MWEB FEES!      │        │
│  │                                                                 │        │
│  │  Their "fix" for MWEB parsing failures:                         │        │
│  │  → Skip MWEB transactions entirely                              │        │
│  │  → 100% of MWEB fees lost (not just ~25% from retry hashrate)   │        │
│  │                                                                 │        │
│  │  Our fix (Part 11):                                             │        │
│  │  → Try/except around tx_type.unpack()                           │        │
│  │  → Store raw bytes with _mweb marker                            │        │
│  │  → MWEB txs included in blocks, fees collected                  │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Coinbase Structure Analysis (Block 2870037)

```
Coinbase TX: d2fed4972b1b857e08658953ed5ac96a953f51cde19f470ce97e97f2a3d87fb1

Inputs:
  - coinbase: "0315cb2b2cfabe6d6d..." (block height + aux pow + "Toomim Bros/p2pool")
  - witness: "[P2Pool][P2Pool][P2Pool][P2Pool]"

Outputs (33 total):
  - vout[0]:  OP_RETURN (segwit commitment)
  - vout[1-30]: P2Pool miner payouts (various address types)
  - vout[31]: 0.00000016 LTC to P2PK donation (BURNED - no private key)
  - vout[32]: OP_RETURN (share chain commitment)

Notable: Block uses native SegWit (witness data) but excludes all MWEB txs
```

---

## 13.2 Share Modification Attack Analysis

**Question:** Can an attacker intercept and modify V36 shares to steal rewards?

### V35 Security Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  V35 SHARE VERIFICATION CHAIN                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Share Creation:                                                            │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  share_data.pubkey_hash = miner's address (20 bytes)            │        │
│  │           ↓                                                     │        │
│  │  generate_transaction() builds coinbase with payouts            │        │
│  │           ↓                                                     │        │
│  │  gentx_hash = SHA256(SHA256(coinbase_tx))                       │        │
│  │           ↓                                                     │        │
│  │  hash_link = SHA256 state at coinbase prefix                    │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  Share Verification (data.py:669-670):                                      │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  # Reconstruct coinbase from share_data                         │        │
│  │  gentx = generate_transaction(share_data, ...)                  │        │
│  │                                                                 │        │
│  │  # Verify it matches the committed hash                         │        │
│  │  if bitcoin_data.get_txid(gentx) != self.gentx_hash:            │        │
│  │      raise ValueError("gentx doesn't match hash_link")          │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  PROTECTION: pubkey_hash → coinbase outputs → gentx_hash (committed)        │
│              Changing pubkey_hash changes gentx_hash → REJECTED             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Attack Scenario: Litecoin Address Modification

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ATTACK: Modify share_data.pubkey_hash                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Attacker intercepts share in P2P network                                │
│  2. Changes: pubkey_hash = 0xABC... → 0xDEF... (attacker's address)         │
│  3. Forwards modified share to peers                                        │
│                                                                             │
│  Result:                                                                    │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  Receiving node:                                                │        │
│  │  - Unpacks share with modified pubkey_hash = 0xDEF...           │        │
│  │  - Calls generate_transaction(share_data, ...)                  │        │
│  │  - Builds coinbase paying to 0xDEF... (attacker)                │        │
│  │  - Computes gentx_hash of new coinbase                          │        │
│  │  - Compares to share's claimed gentx_hash                       │        │
│  │  - MISMATCH! → ValueError → Share REJECTED                      │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  VERDICT: ✅ SECURE - pubkey_hash modification detected                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### V36 New Attack Surface: Merged Mining Addresses

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  V36 ADDS NEW FIELDS: merged_addresses for secondary chains                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  V36 Share Structure:                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  share_data:                                                    │        │
│  │    pubkey_hash: 20 bytes (Litecoin address) ← PROTECTED         │        │
│  │    ...                                                          │        │
│  │  share_info:                                                    │        │
│  │    ...                                                          │        │
│  │    merged_mining_version: 1 byte                                │        │
│  │    derivation_mode: 1 byte                                      │        │
│  │    merged_payload: variable ← NEW! Is this protected?           │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  QUESTION: What commits to merged_payload?                                  │
│                                                                             │
│  The merged addresses affect SECONDARY CHAIN coinbases (Dogecoin, etc.)     │
│  NOT the PRIMARY CHAIN coinbase (Litecoin)                                  │
│                                                                             │
│  Therefore: gentx_hash does NOT protect merged_payload!                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Attack Scenario: Merged Address Modification

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  POTENTIAL ATTACK: Modify merged_payload without affecting gentx_hash       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Attacker intercepts V36 share                                           │
│  2. Changes merged_payload:                                                 │
│     - Original: DERIVE_ALL, pubkey_hash = 0xABC... (miner's Doge addr)      │
│     - Modified: DERIVE_ALL, pubkey_hash = 0xDEF... (attacker's Doge addr)   │
│  3. Litecoin pubkey_hash unchanged → gentx_hash unchanged                   │
│  4. Share passes gentx verification!                                        │
│                                                                             │
│  IF NO OTHER PROTECTION:                                                    │
│  - Share accepted by network                                                │
│  - When merged block found, Dogecoin rewards go to attacker!                │
│  - Original miner gets Litecoin but loses Dogecoin                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 13.3 Security Solutions for V36

### Solution A: Include merged_payload in share_info (RECOMMENDED)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SOLUTION A: share_info COMMITMENT                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  How it works:                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  share_info = {                                                 │        │
│  │    share_data: {...},                                           │        │
│  │    far_share_hash: ...,                                         │        │
│  │    bits: ...,                                                   │        │
│  │    timestamp: ...,                                              │        │
│  │    merged_mining_version: 0x01,        ← NEW                    │        │
│  │    derivation_mode: 0x01,              ← NEW                    │        │
│  │    merged_payload: pubkey_hash,        ← NEW                    │        │
│  │  }                                                              │        │
│  │                                                                 │        │
│  │  share_hash = SHA256(share_type.pack(share))                    │        │
│  │                  ↑                                              │        │
│  │            includes share_info which includes merged_payload    │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  Verification:                                                              │
│  1. Share received with claimed share_hash                                  │
│  2. Node unpacks share, computes SHA256 of packed data                      │
│  3. If computed hash ≠ claimed hash → Share REJECTED                        │
│  4. If attacker modified merged_payload → hash changes → REJECTED           │
│                                                                             │
│  VERDICT: ✅ SECURE - merged_payload modification changes share_hash        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Solution B: OP_RETURN Commitment in Primary Coinbase

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SOLUTION B: COINBASE OP_RETURN COMMITMENT                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Add commitment to Litecoin coinbase:                                       │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  vout[N]: OP_RETURN <merged_address_commitment>                 │        │
│  │           where commitment = SHA256(sorted_merged_addresses)    │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  Protection:                                                                │
│  - Commitment is in coinbase → affects gentx_hash                           │
│  - Changing merged addresses → changes commitment → changes gentx_hash      │
│  - Share verification fails on gentx mismatch                               │
│                                                                             │
│  Drawbacks:                                                                 │
│  - Adds ~40 bytes to every coinbase (OP_RETURN + 32-byte hash)              │
│  - Affects ALL miners, not just merged mining participants                  │
│  - Requires Litecoin coinbase format change (backward compatibility?)       │
│                                                                             │
│  VERDICT: ⚠️ SECURE but invasive - prefer Solution A                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Solution C: Signed Shares

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SOLUTION C: CRYPTOGRAPHIC SIGNATURES                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Miner signs entire share with their private key:                           │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │  share.signature = sign(private_key, SHA256(share_contents))    │        │
│  │                                                                 │        │
│  │  Verification:                                                  │        │
│  │  - Derive public key from pubkey_hash                           │        │
│  │  - Verify signature over share contents                         │        │
│  │  - If invalid → REJECT                                          │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  Problem:                                                                   │
│  - pubkey_hash is HASH of public key, not public key itself                 │
│  - Cannot derive public key from hash (one-way function)                    │
│  - Would need to include full public key in share (+33 bytes)               │
│  - Current shares already have a signature field (different purpose)        │
│                                                                             │
│  VERDICT: ❌ NOT PRACTICAL - would require major protocol changes           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 13.4 Recommended V36 Security Implementation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  V36 SECURITY SPECIFICATION                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. merged_payload MUST be part of share_info structure                     │
│     - Included in share serialization                                       │
│     - Affects share_hash computation                                        │
│     - Any modification invalidates share                                    │
│                                                                             │
│  2. Verification pseudocode:                                                │
│     ┌─────────────────────────────────────────────────────────────────┐     │
│     │ def verify_share(share):                                        │     │
│     │     # Existing verification                                     │     │
│     │     if get_txid(reconstruct_gentx(share)) != share.gentx_hash:  │     │
│     │         raise ValueError("gentx mismatch")                      │     │
│     │                                                                 │     │
│     │     # share_hash already covers share_info (implicit)           │     │
│     │     # Since merged_payload is IN share_info, it's protected     │     │
│     │                                                                 │     │
│     │     # V36-specific: validate merged_payload format              │     │
│     │     if share.version >= 36:                                     │     │
│     │         validate_merged_payload(share.share_info.merged_payload)│     │
│     │         # Derivation mode must match actual address list        │     │
│     │         verify_derivation_consistency(share)                    │     │
│     └─────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  3. Additional validation for derivation mode:                              │
│     - DERIVE_ALL: All merged addresses must equal primary pubkey_hash       │
│     - DERIVE_WITH_OVERRIDE: Overrides must be for valid chain_ids           │
│     - EXPLICIT: All chain_ids must be unique and valid                      │
│                                                                             │
│  4. Migration safety:                                                       │
│     - V35 nodes ignore merged_payload (don't parse it)                      │
│     - V36 nodes verify merged_payload for V36 shares                        │
│     - No retroactive attacks possible (V35 shares have no merged_payload)   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 13.5 Attack Vector Summary

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  V36 SECURITY THREAT MODEL                                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Attack Vector                    Protected By         Status                │
│  ──────────────────────────────────────────────────────────────────────────  │
│  Modify Litecoin pubkey_hash      gentx_hash           ✅ SECURE             │
│  Modify share_data fields         gentx_hash           ✅ SECURE             │
│  Modify share timestamps          share_info→hash      ✅ SECURE             │
│  Modify transaction refs          merkle_link          ✅ SECURE             │
│  Modify merged_payload            share_info→hash      ✅ SECURE (if in info)│
│  Replay old shares                share_hash unique    ✅ SECURE             │
│  Create fake shares               PoW requirement      ✅ SECURE             │
│                                                                              │
│  REMAINING RISKS:                                                            │
│  ──────────────────────────────────────────────────────────────────────────  │
│  Eclipse attacks (isolate node)   Out of scope         ⚠️ P2P layer issue    │
│  51% attacks on share chain       Inherent to PoW      ⚠️ Fundamental        │
│  Sybil attacks (fake peers)       Peer limits          ⚠️ Mitigated          │
│                                                                              │
│  CONCLUSION: V36 with merged_payload in share_info is cryptographically      │
│  secure against address modification attacks.                                │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 13.6 Implementation Checklist

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  V36 SECURITY IMPLEMENTATION CHECKLIST                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  □ 1. Add merged_payload to share_info structure (data.py)                  │
│       - Ensure it's included in share_type serialization                    │
│       - Verify it affects share_hash computation                            │
│                                                                             │
│  □ 2. Add merged_payload validation in check() method                       │
│       - Validate derivation_mode is 0x00, 0x01, or 0x02                     │
│       - Validate payload length matches mode                                │
│       - Validate chain_ids are valid for network                            │
│                                                                             │
│  □ 3. Add derivation consistency check                                      │
│       - DERIVE_ALL: verify no addresses differ from primary                 │
│       - DERIVE_WITH_OVERRIDE: verify overrides are necessary                │
│       - EXPLICIT: verify all chains present                                 │
│                                                                             │
│  □ 4. Add unit tests for security                                           │
│       - Test: modify merged_payload → share rejected                        │
│       - Test: invalid derivation_mode → share rejected                      │
│       - Test: mismatched derivation → share rejected                        │
│                                                                             │
│  □ 5. Document attack resistance in code comments                           │
│       - Explain why merged_payload is in share_info                         │
│       - Reference this security analysis                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Appendix C: Donation Address Reference

**Script Formats:**
- **DONATION_SCRIPT** (P2PK): `4104ffd03de...ac` - pubkey_hash: `0384f570ccc88ac2e7e00b026d1690a3fca63dd0`
- **SECONDARY_DONATION_SCRIPT** (P2PKH): `76a91420cb5c22...88ac` - pubkey_hash: `20cb5c22b1e4d5947e5c112c7696b51ad9af3c61`

| Chain | Old Donation (P2PK - BURNED) | New Donation (P2PKH - CONTROLLED) |
|-------|------------------------------|-----------------------------------|
| Bitcoin | `1Kz5QaUPDtKrj5SqW5tFkn7WZh8LmQaQi4` | `13zQEqHLKUCvnfJbvq4KRXb96FDrMa72CB` |
| Litecoin | `LeD2fnnDJYZuyt8zgDsZ2oBGmuVcxGKCLd` | `LNDMW3bAQ8Sz3Tzm6y3chYeuJTb8VHSHGM` |
| Dogecoin | `DQ8AwqR2XJE9G5dSEfspJYH7Spre85dj6L` | `D88Vn6Dyct7DKfVCfR3syHkjyNx9gEyyiv` |

**CRITICAL:** 
- Old donation is P2PK format (65-byte pubkey, no address in coinbase) - **PRIVATE KEY LOST!**
- New donation is P2PKH format - **WE CONTROL THIS!**

---

*Document Version: 1.10*
*Last Updated: February 2026*
*Author: P2Pool Merged Mining Team*
*Changelog:*
- *v1.0: Initial V36 merged mining plan*
- *v1.1: Added donation migration plan (Part 9)*
- *v1.2: Updated donation migration to use same gradual principle as merged rewards*
- *v1.3: CORRECTED: Donation migration is per-block (winner takes all), NOT proportional split*
- *v1.4: FINAL CORRECTION: Donation CANNOT change until V35 deprecated - all nodes must compute identical coinbase. Continue SECONDARY_DONATION_ENABLED hack (50/50 split) until flag day.*
- *v1.5: FIXED: Corrected all donation addresses - they were completely wrong. Verified against actual script hash160 values.*
- *v1.6: VERIFIED: BTC donation address confirmed as 1Kz5QaUPDtKrj5SqW5tFkn7WZh8LmQaQi4 (user-provided), all addresses now derived correctly from hash160 d03da6fca390166d020be0e7c28ac8cc70f58403*
- *v1.7: NEW: Added Part 10 - Share Difficulty Stagnation Problem discovered during V35 compatibility testing. Documented death spiral issue and proposed time-based difficulty decay solution.*
- *v1.8: NEW: Added Part 11 - MWEB Compatibility Issue. Documented jtoomim ~15-25% hashrate loss due to MWEB parsing failures. Our fix reduces failure rate from 97% to <1%. V35 shares remain compatible across MWEB/non-MWEB nodes.*
- *v1.9: NEW: Added Part 12 - Share Size Optimization. Derivation mode encoding reduces V36 overhead from +57% to +3% for typical miners. Includes future compression and commitment scheme roadmap.*
- *v1.10: NEW: Added Part 13 - Security Analysis. Analyzed P2Pool blocks (ZERO MWEB txs included - 100% fee loss). Documented share modification attack vectors and security solutions. Recommended: merged_payload in share_info for cryptographic protection.*
