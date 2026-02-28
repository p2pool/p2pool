# Implementation Roadmap: Trustless Merged Mining

## Current Status

P2Pool currently uses `getauxblock` which doesn't allow controlling coinbase outputs. This requires trusting the pool operator to distribute merged mining rewards.

## Solution: Use getblocktemplate

Implement true trustless merged mining by building merged chain blocks with P2Pool-controlled coinbase outputs.

## Implementation Phases

### Phase 1: Detection & Compatibility Layer
**Goal:** Detect merged chain capabilities without breaking existing functionality

**Tasks:**
- [ ] Add capability detection for merged chains
- [ ] Try `getblocktemplate` first, fall back to `getauxblock`
- [ ] Add configuration flag `--merged-trustless` to opt-in
- [ ] Log warnings when using trusted `getauxblock` mode

**Files to modify:**
- `p2pool/work.py`: Add detection logic
- `p2pool/main.py`: Add CLI options

### Phase 2: Merged Chain Block Builder
**Goal:** Build merged chain blocks with custom coinbase

**Tasks:**
- [ ] Create `p2pool/merged/template.py`
  - Call `getblocktemplate` on merged chain
  - Parse transactions and block structure
  - Handle version, bits, time, etc.

- [ ] Create `p2pool/merged/coinbase.py`
  - Build coinbase with P2Pool outputs (same as main chain)
  - Use same PPLNS weights calculation
  - Add OP_RETURN commitment to parent hash
  - Handle witness commitment if needed

- [ ] Create `p2pool/merged/merkle.py`
  - Calculate merkle root for merged chain
  - Build merkle branches for aux_pow proof
  - Handle witness merkle tree if needed

**New files:**
```
p2pool/merged/
├── __init__.py
├── template.py      # getblocktemplate handling
├── coinbase.py      # Build coinbase with P2Pool payouts
├── merkle.py        # Merkle tree calculations
└── auxpow.py        # Aux PoW proof construction
```

### Phase 3: Aux_Pow Construction
**Goal:** Build proper auxiliary proof-of-work

**Tasks:**
- [ ] Update aux_pow structure
  - Include parent block header
  - Include parent coinbase transaction
  - Include merkle branch (coinbase → parent block)
  - Include blockchain branch (for multi-chain merged mining)

- [ ] Handle different aux_pow versions
  - Namecoin-style (original)
  - Modern variants

**Files to modify:**
- `p2pool/dash/data.py`: Update `aux_pow_type` if needed
- `p2pool/merged/auxpow.py`: New aux_pow builder

### Phase 4: Block Submission
**Goal:** Submit complete blocks to merged chains

**Tasks:**
- [ ] Use `submitblock` instead of `getauxblock`
- [ ] Handle submission errors gracefully
- [ ] Add proper logging and debugging
- [ ] Verify block acceptance

**Files to modify:**
- `p2pool/work.py`: Update submission logic

### Phase 5: Multi-Chain Support
**Goal:** Handle multiple merged chains simultaneously

**Tasks:**
- [ ] Build merged merkle tree for parent coinbase
  - Root includes commitments to all merged chains
  - Each merged chain gets its own branch

- [ ] Coordinate multiple `getblocktemplate` calls
- [ ] Build separate blocks for each merged chain
- [ ] Submit to all chains when solution found

### Phase 6: Testing & Validation
**Goal:** Ensure correctness and stability

**Tasks:**
- [ ] Test with Namecoin testnet
- [ ] Test with multiple merged chains
- [ ] Verify payout amounts match main chain PPLNS
- [ ] Test block acceptance rates
- [ ] Performance testing (latency, CPU usage)

### Phase 7: Web Interface
**Goal:** Show merged mining statistics

**Tasks:**
- [ ] Add merged mining stats to `/global_stats`
- [ ] Show merged blocks found per chain
- [ ] Show miner earnings per chain
- [ ] Add merged mining graphs

**Files to modify:**
- `p2pool/web.py`: Add endpoints
- `web-static/index.html`: Add display

### Phase 8: Documentation & Migration
**Goal:** Help users adopt new system

**Tasks:**
- [ ] Write setup guide for each supported merged chain
- [ ] Document configuration options
- [ ] Create migration guide from old system
- [ ] Update README with merged mining section

## Technical Challenges

### Challenge 1: Merkle Root Calculation
**Problem:** Must calculate merkle root correctly for merged chain

**Solution:**
```python
def calculate_merged_merkle_root(coinbase, transactions):
    # Build merkle tree with our coinbase first
    tx_hashes = [hash256(coinbase)] + [tx['hash'] for tx in transactions]
    return calculate_merkle_root(tx_hashes)
```

### Challenge 2: Aux_Pow Proof
**Problem:** Merged chain must verify aux_pow proof

**Solution:**
- Include parent block header
- Include merkle branch proving coinbase contains merged block hash
- Include blockchain branch for multi-chain scenarios

### Challenge 3: Timing & Latency
**Problem:** `getblocktemplate` adds latency vs `getauxblock`

**Solution:**
- Cache templates and update periodically
- Use background threads for template updates
- Only rebuild when necessary (new block or time elapsed)

### Challenge 4: Compatibility
**Problem:** Not all merged chains support `getblocktemplate`

**Solution:**
- Maintain fallback to `getauxblock` (with big warning)
- Document which chains are compatible
- Encourage chains to add support

## Configuration Example

```bash
# Trustless merged mining (new way)
python run_p2pool.py \
    --merged http://user:pass@localhost:8336/ \
    --merged-mode template \
    --merged-chain-name Namecoin

# Trusted fallback (old way - with warning)
python run_p2pool.py \
    --merged http://user:pass@localhost:8336/ \
    --merged-mode auxblock \
    --merged-trust-operator  # Required to acknowledge trust
```

## Success Criteria

- ✅ Merged chain blocks contain P2Pool miner payouts
- ✅ Payouts match main chain PPLNS weights
- ✅ No pool operator wallet required
- ✅ Works with at least Namecoin
- ✅ Performance impact < 5% vs current implementation
- ✅ Clear documentation and migration path

## Timeline Estimate

- Phase 1: 2-3 days (detection & compatibility)
- Phase 2: 5-7 days (block builder)
- Phase 3: 3-4 days (aux_pow construction)
- Phase 4: 2-3 days (submission)
- Phase 5: 3-4 days (multi-chain)
- Phase 6: 5-7 days (testing)
- Phase 7: 2-3 days (web interface)
- Phase 8: 2-3 days (documentation)

**Total: ~4-5 weeks** for complete implementation

## Next Steps

1. Start with Phase 1 (detection)
2. Test detection with Namecoin testnet
3. Implement Phase 2 (block builder) iteratively
4. Get early feedback from Namecoin community
5. Continue through phases with testing at each step

## Notes

This is a **fundamental improvement** to P2Pool that truly maintains trustless principles for merged mining. It's worth the implementation effort because it:

1. Eliminates trust requirement
2. Provides fair distribution automatically
3. Aligns with P2Pool's core philosophy
4. Sets standard for future merged mining implementations

The current implementation works but requires trust. This roadmap provides a path to eliminate that trust requirement completely.
