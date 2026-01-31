# Merged Mining with Trustless Coinbase Distribution

## The Problem with getauxblock

The traditional `getauxblock` RPC call has a fundamental limitation:
- Returns a **pre-built block** with coinbase already created
- Coinbase pays to the wallet address configured in merged chain daemon
- **No way to specify custom coinbase outputs**
- This requires trusting the pool operator to redistribute rewards

## The Solution: getblocktemplate for Merged Mining

Modern merged mining should use `getblocktemplate` instead:

### How It Works

1. **Get Block Template from Merged Chain**
   ```json
   mergedchain-cli getblocktemplate '{"rules":["segwit"]}'
   ```
   Returns transactions and block structure WITHOUT a coinbase

2. **Build Custom Coinbase with P2Pool Payouts**
   ```
   Coinbase outputs:
   - Output 1-N: P2Pool miners (using PPLNS weights)
   - Last output: OP_RETURN with aux_pow commitment
   ```

3. **Calculate Merkle Root with Our Coinbase**
   ```
   merkle_root = calculate_merkle([our_coinbase] + transactions)
   ```

4. **Mine the Block**
   - Use parent chain (Dash/Bitcoin) mining
   - When solution found, build aux_pow proof

5. **Submit Complete Block to Merged Chain**
   ```json
   mergedchain-cli submitblock <block_hex>
   ```

## Implementation Requirements

### Merged Chain Requirements

The merged chain daemon must support:
- ✅ `getblocktemplate` RPC call
- ✅ `submitblock` RPC call  
- ✅ Auxiliary proof-of-work (aux_pow) verification
- ✅ Accept blocks without using `getauxblock`

### Compatible Chains

**Fully Compatible:**
- Namecoin (supports getblocktemplate)
- Huntercoin
- Ixcoin
- Devcoin (with updates)

**Requires Updates:**
- Dogecoin (uses getauxblock, needs getblocktemplate support)
- Older merged mining coins

## P2Pool Implementation

### New Merged Mining Flow

```python
# 1. Get template from merged chain
merged_template = merged_daemon.getblocktemplate()

# 2. Calculate PPLNS weights (same as main chain)
weights = tracker.get_cumulative_weights(...)

# 3. Build coinbase with P2Pool payouts
coinbase_outputs = []
for address, weight in weights.items():
    payout = (merged_block_reward * weight) / total_weight
    coinbase_outputs.append({
        'value': payout,
        'script': address_to_script(address)
    })

# 4. Add aux_pow commitment to coinbase
coinbase_outputs.append({
    'value': 0,
    'script': OP_RETURN + parent_block_hash + merkle_proof
})

# 5. Build coinbase transaction
merged_coinbase = create_transaction(
    inputs=[coinbase_input],
    outputs=coinbase_outputs
)

# 6. Calculate merkle root
merged_merkle_root = calculate_merkle_root([merged_coinbase] + merged_template['transactions'])

# 7. Mine parent chain block (Dash)
# When solution found...

# 8. Build aux_pow proof
aux_pow = {
    'parent_block': dash_block_header,
    'coinbase_tx': merged_coinbase,
    'merkle_branch': calculate_merkle_branch(merged_coinbase, merged_template['transactions']),
    'chain_merkle_branch': [], # if using Namecoin-style merged mining
    'parent_block_index': 0
}

# 9. Submit to merged chain
merged_block = build_block(merged_template, merged_coinbase, aux_pow)
merged_daemon.submitblock(block_hex)
```

### Code Structure

```
p2pool/
├── work.py                    # Main mining loop
├── merged/
│   ├── __init__.py
│   ├── template.py           # getblocktemplate for merged chains
│   ├── coinbase.py           # Build coinbase with P2Pool payouts
│   └── auxpow.py             # Auxiliary proof-of-work construction
```

## Configuration

### Enable getblocktemplate Merged Mining

```bash
python run_p2pool.py \
    --merged http://user:pass@localhost:8336/ \
    --merged-use-template  # Use getblocktemplate instead of getauxblock
```

### Merged Chain Configuration

In merged chain's daemon config:
```ini
# Enable getblocktemplate
server=1
rpcuser=user
rpcpassword=pass
rpcallowip=127.0.0.1

# NO wallet needed - P2Pool controls coinbase
# disablewallet=1  # Optional: disable wallet entirely
```

## Advantages

### True Trustlessness
- ✅ Miners paid directly in merged chain coinbase
- ✅ No pool wallet required
- ✅ No trust in pool operator
- ✅ Same PPLNS algorithm as main chain
- ✅ Verifiable by all nodes

### Efficiency
- ✅ Single transaction per block (merged coinbase)
- ✅ No separate payout transactions
- ✅ No transaction fees for payouts
- ✅ No minimum payout thresholds

### Compatibility
- ✅ Works with existing P2Pool infrastructure
- ✅ Same address submission (miners submit one address for all chains)
- ✅ Same web interface
- ✅ Same share chain

## Migration Path

### Phase 1: Detect Capability
```python
# Try getblocktemplate first
try:
    template = merged_daemon.getblocktemplate()
    use_template = True
except:
    # Fall back to getauxblock (requires trust)
    use_template = False
    log.warning("Merged chain doesn't support getblocktemplate - using trusted getauxblock")
```

### Phase 2: Dual Mode Support
- Chains with `getblocktemplate`: trustless distribution
- Chains with only `getauxblock`: trusted fallback (with big warning)

### Phase 3: Encourage Upgrades
- Document which chains need updates
- Provide patches for popular merged mining coins
- Eventually deprecate `getauxblock` mode

## Implementation Checklist

- [ ] Add `getblocktemplate` support for merged chains
- [ ] Build merged coinbase with P2Pool outputs
- [ ] Calculate merged merkle root correctly
- [ ] Construct aux_pow proofs
- [ ] Submit blocks via `submitblock`
- [ ] Test with Namecoin testnet
- [ ] Add configuration options
- [ ] Update documentation
- [ ] Add web UI for merged mining stats
- [ ] Test with multiple merged chains

## Technical Details

### Aux_Pow Structure

```
AuxiliaryProofOfWork:
├── coinbase_tx         # Parent chain coinbase (contains merged hash)
├── block_hash          # Parent chain block hash
├── coinbase_branch     # Merkle branch proving coinbase is in parent block
├── blockchain_branch   # Merkle branch for multiple merged chains (Namecoin)
└── parent_block        # Parent chain block header
```

### Merkle Tree Construction

```
Merged chain merkle tree:
         root
        /    \
    coinbase  tx_branch
              /    \
            tx1    tx2
```

### Commitment in Parent Coinbase

Parent chain (Dash) coinbase includes:
```
OP_RETURN <32-byte merged_merkle_root> [chain_id_bytes]
```

Multiple merged chains can be encoded in a single parent block using a merged merkle tree.

## Summary

**Current (getauxblock):** Trusted pool operator
- ❌ Pool operator controls merged chain wallet
- ❌ Requires trusting payout distribution
- ❌ Separate payout transactions needed

**New (getblocktemplate):** Trustless P2Pool
- ✅ Miners paid directly in merged chain coinbase
- ✅ No trust required
- ✅ True P2Pool principles maintained

This is the **correct way** to do merged mining in P2Pool!
