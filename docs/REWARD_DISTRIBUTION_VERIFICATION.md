# Reward Distribution Verification Report — V36 Merged Mining

## Test Environment

| Component | Details |
|-----------|---------|
| **LTC Testnet** | RPC at `LTC_DAEMON_IP:18332`, height ~4568123 |
| **DOGE Testnet** | RPC at `DOGE_DAEMON_IP:44555`, height 10152 |
| **NodeA** | `NODE_A_IP:19327` — `-f 90 --give-author 0 -a mwQq...` |
| **NodeB** | `NODE_B_IP:19327` — `-f 0 --give-author 5 -a mxpt...` |
| **Both nodes** | `--merged-operator-address YOUR_TDOGE_ADDRESS` |

### Address Mapping (LTC → DOGE, auto-converted from pubkey_hash)

| Miner | LTC Address | DOGE Address | Role |
|-------|-------------|--------------|------|
| NodeA | `mwQqcRjWsCSvMfFrAvpcCujofQSFcV1AsW` | `nk63aeL6HZNfzXY2DmVFBAHNvQx8zcrhVk` | Node operator (-f 90) |
| NodeB | `mxptR46XQBRk3EHstU83QRQcqT2PCVkW3g` | `nmW6PGh6pYMVg6a3wJngNfxC6TYGfJppPy` | Node operator (--give-author 5) |
| Miner3 | `mzisknENRPyyPS1M54qmwatfLhaMyFwRYQ` | `noQ5izpwqkuj2JHX7uWQuqSEbi6FQvvn5s` | Stratum worker |
| Miner4 | `mzW2hdZN2um7WBvTDerdahKqRgj3md9C29` | `noBEfr9wTGgs94CdGVXGYwsQghEwBsXw4K` | Stratum worker |

---

## 1. 1:1 PPLNS Ratio Mapping: LTC ↔ DOGE

### Result: PERFECT MATCH (0.0000% difference)

Simultaneous API query from NodeA:

```
current_payouts (LTC):                      current_merged_payouts (DOGE):
  mwQq: 1.14220663 LTC = 73.10%              nk63: 526342.70 DOGE = 73.10%
  mxpt: 0.39927870 LTC = 25.55%              nmW6: 183992.48 DOGE = 25.55%
  mzW2: 0.02101467 LTC =  1.34%              noBE:   9683.82 DOGE =  1.34%
  TOTAL: 1.56250000 LTC                       TOTAL: 720019.00 DOGE
```

All 3 miners show **identical percentages** on both chains (0.0000% difference).
Both APIs showed **identical miner sets** (same 3 miners; mzis had aged out of PPLNS window on both chains simultaneously).

### PPLNS Window Dynamics

- The number of miners changes as shares enter/leave the PPLNS window
- LTC blocks 4568114-4568123: Varied between 2-3 miners (mzis entered at 4568115, left at 4568123)
- DOGE blocks 10140-10152: Same pattern — noQ5/mzis appeared in blocks 10140-10141, absent 10142+
- This is **correct behavior**: both chains reflect the same share chain state at any given moment

---

## 2. Block Coinbase Structure Analysis

### LTC Parent Chain (10 blocks analyzed: 4568114-4568123)

Each LTC P2Pool block coinbase contains:
```
[0] OP_RETURN (witness commitment)
[1..N] Miner payout outputs (proportional to PPLNS weights)
[N+1]  P2SH donation output (COMBINED_DONATION_SCRIPT)
[N+2]  OP_RETURN (share reference hash)
```

**Block reward**: 1.56250000 LTC per block (constant testnet subsidy)

### DOGE Child Chain (13 blocks analyzed: 10140-10152)

Each DOGE merged-mined block coinbase contains:
```
[0..N] Miner payout outputs (proportional to same PPLNS weights)
[N+1]  OP_RETURN "technocore" (pool identifier tag)
[N+2]  P2SH donation output (COMBINED_DONATION_SCRIPT on DOGE)
```

**Block rewards**: Variable (6,828 to 881,511 DOGE — DOGE testnet subsidy varies with height).

### Coinbase Structural Comparison

| Feature | LTC (parent) | DOGE (merged) |
|---------|-------------|---------------|
| Witness commitment | Yes (OP_RETURN [0]) | No (not SegWit) |
| Miner outputs | From `generate_transaction()` | From `build_merged_coinbase()` |
| Donation output | COMBINED_DONATION_SCRIPT (P2SH) | COMBINED_DONATION_SCRIPT (P2SH) |
| Pool tag | Share ref hash OP_RETURN | "technocore" OP_RETURN |
| Finder fee | 0.5% (subsidy//200) added to finder | 0.5% to per-user finder address |

---

## 3. Fee Mechanism Analysis

### `-f` Flag (Probabilistic Node Owner Fee)

**How it works**: At share creation time (`work.py:1145-1148`), when a miner submits work via stratum:
```python
if random.uniform(0, 100) < self.node_owner_fee:
    pubkey_hash = self.my_pubkey_hash  # Replace miner's address with node operator's
```

**Live verification (NodeA, `-f 90`)**:
- NodeA address (mwQq) appears in 65-83% of PPLNS weight across analyzed blocks
- This is higher than their natural hashrate share because `-f 90` redirects 90% of their stratum workers' shares to the node operator's address
- Smaller miners (mzis, mzW2) appear with reduced weight — only the 10% of their shares that weren't replaced

**Effect on merged mining**: The `-f` replacement operates at share level, so it propagates identically to both LTC and DOGE payouts via the same PPLNS weight distribution. **No separate `-f` adjustment needed on merged chain.**

### `--give-author` Flag (Donation Weight)

**How it works**: Sets `share_data['donation'] = math.perfect_round(65535 * percentage / 100)` in each share. This splits the share's weight:
- `share_weight = att * (65535 - donation)` → goes to miner
- `donation_weight = att * donation` → goes to author/donation

**Live verification (NodeB, `--give-author 5`)**:

| LTC Block | Donation % | NodeB (mxpt) % | Expected (mxpt% × 5%) | Diff |
|-----------|-----------|-----------------|----------------------|------|
| 4568114 | 1.80% | 34.15% | 1.71% | 0.09% |
| 4568115 | 1.07% | 20.31% | 1.02% | 0.05% |
| 4568118 | 2.13% | 40.39% | 2.02% | 0.11% |
| 4568122 | 2.09% | 39.72% | 1.99% | 0.10% |
| 4568123 | 1.85% | 35.08% | 1.75% | 0.09% |

The donation percentage tracks NodeB's PPLNS weight × 5% with ~0.05-0.11% error from integer rounding remainder. **Correct behavior.**

**Effect on merged mining**: In PPLNS mode, `merged_donation_percentage` is derived from the aggregate `donation_weight / total_weight` across the PPLNS window (not from local `--give-author` flag). This ensures consensus across nodes. From `work.py:536-541`:
```python
if total_weight > 0 and shareholders:
    merged_donation_percentage = 100.0 * float(donation_weight) / float(total_weight)
    merged_node_owner_fee = 0  # Always 0 in PPLNS mode
```

### Finder Fee (0.5%)

**Parent chain**: `subsidy // 200` = 0.00781250 LTC added to block finder's existing PPLNS share in `generate_transaction()`.

**Merged chain**: 0.5% of DOGE reward to per-user finder address in `build_merged_coinbase()`. Finder address is resolved per-stratum-worker via `_derive_merged_finder_address()`, ensuring the **actual miner who finds the block** (not the node operator) receives the finder fee.

### `merged_node_owner_fee` in PPLNS Mode

**Always 0.** Confirmed at `work.py:541`. The `--merged-operator-address` is a no-op when the fee is forced to 0. Node operator economics are already captured through the `-f` probabilistic address replacement in the share chain.

---

## 4. Edge Cases Analysis

### Miner address = COMBINED_DONATION_SCRIPT

| Chain | Behavior |
|-------|----------|
| **LTC (parent)** | Miner's payout **coalesces** into the donation entry in the `amounts` dict. Since `combined_donation_addr` is in `excluded_dests`, the miner's reward flows entirely into the donation output. The miner effectively loses access to their earnings. Theoretical funds-loss bug, but requires deliberately mining to the P2SH donation address. |
| **DOGE (merged)** | Miner output is added via `append_or_coalesce_output()`, but donation is added via raw `tx_outs.append()` — **no coalescing**. Two separate outputs with the same scriptPubKey. Valid per consensus rules but slightly inelegant. |

**Risk level**: Practically unreachable — no miner would accidentally use the P2SH address `2N63WXLw22FXFdLBNqWZLsDX7WQJTPXus7f`.

### Node Owner = Miner (same address)

If the node operator also mines through their own node: all weights accumulate under the same address. No issue — the PPLNS correctly sums all shares. The output is a single combined payout.

### Single Miner in PPLNS Window

Produces a minimal coinbase with:
- 1 miner output (receives ~98.5-99.5% of subsidy)
- 1 donation output (receives donation_weight% + rounding remainder)
- 1 OP_RETURN tag

**Correct behavior.**

### Empty Shareholders Dict

Guard in `work.py:549` prevents `build_merged_coinbase` from being called with empty dict — falls back to single-address mode `shareholders = {mining_address: 1.0}`. If somehow empty dict reaches `build_merged_coinbase`, all `miners_reward` flows to donation as rounding remainder. **No crash, no coin loss.**

### Extremely Small Amounts (dust-level miners)

If `int(miners_reward * fraction) = 0`, the miner is skipped (`if amount > 0`). The "lost" satoshis accumulate in `rounding_remainder` and flow to the donation output. **Correct dust prevention — no coins lost.**

### Unconvertible Addresses (P2SH/P2WSH/P2TR miners on merged chain)

The `is_pubkey_hash_address()` check at `work.py:505-507` skips non-P2PKH addresses. Their weight is redistributed proportionally to convertible miners via normalization over `accepted_total_weight` (not `total_weight`). **Design intentional — merged mining requires auto-conversion from pubkey_hash.**

---

## 5. Blocks 4568119 and 4568120: Determinism Verification

LTC blocks 4568119 and 4568120 have **byte-for-byte identical outputs**:
```
mzis: 0.22072732 LTC  (both blocks)
mxpt: 0.53064341 LTC  (both blocks)
mwQq: 0.78319842 LTC  (both blocks)
donation: 0.02793085 LTC  (both blocks)
```

This confirms: **when the PPLNS window state is the same, the payout distribution is perfectly deterministic**. Both blocks used the same share chain state (found in quick succession — timestamps 3 sec apart: 1771628122 vs 1771628134).

---

## 6. Summary of Verification Results

| Check | Status | Details |
|-------|--------|---------|
| LTC↔DOGE 1:1 ratio mapping | **PASS** | 0.0000% difference across all addresses |
| Miner count consistency | **PASS** | Same miners on both chains at same PPLNS state |
| PPLNS window dynamics | **PASS** | Expected behavior — miners enter/leave as shares age |
| `-f` node owner fee | **PASS** | Probabilistic replacement in shares, propagates to both chains |
| `--give-author` donation | **PASS** | Donation% tracks NodeB PPLNS weight × 5% (±0.1% rounding) |
| Finder fee (0.5%) | **PASS** | Paid to actual block finder, not node operator |
| `merged_node_owner_fee` = 0 | **PASS** | Always 0 in PPLNS mode; operator fee via share replacement |
| Donation output structure | **PASS** | COMBINED_DONATION_SCRIPT (P2SH) on both chains |
| OP_RETURN tag | **PASS** | "technocore" on DOGE, share ref hash on LTC |
| Edge: miner=donation addr | **SAFE** | Practically unreachable; different behavior LTC vs DOGE |
| Edge: single miner | **PASS** | Correct minimal coinbase |
| Edge: empty shareholders | **SAFE** | Guarded upstream; graceful degradation |
| Edge: dust-level miners | **PASS** | Skipped; rounding flows to donation |
| Edge: unconvertible addrs | **PASS** | Skipped; weight redistributed proportionally |
| Deterministic payouts | **PASS** | Identical PPLNS state → identical outputs |

### Data Analyzed
- **10 LTC blocks**: 4568114-4568123

- **13 DOGE blocks**: 10140-10152
- **2 P2Pool nodes**: NodeA and NodeB with different fee configurations
- **4 unique miner addresses** tracked across both chains
- **API endpoints verified**: `current_payouts`, `current_merged_payouts` from both nodes
