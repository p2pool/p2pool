# Dogecoin Testnet Difficulty Bug - Documentation

## Overview

This document describes a critical bug in Dogecoin's testnet difficulty adjustment that prevents reliable merged mining testing. Until the Dogecoin Core team fixes this issue and launches testnet4alpha, we use a private testnet with corrected parameters.

## The Bug

### Root Cause

In `src/dogecoin.cpp`, the `AllowDigishieldMinDifficultyForBlock()` function has a critical flaw:

```cpp
// Dogecoin: Normally minimum difficulty blocks can only occur in between
// retarget blocks. However, once we introduce Digishield every block is
// a retarget, so we need to handle minimum difficulty on all blocks.
bool AllowDigishieldMinDifficultyForBlock(const CBlockIndex* pindexLast, const CBlockHeader *pblock, const Consensus::Params& params)
{
    // check if the chain allows minimum difficulty blocks
    if (!params.fPowAllowMinDifficultyBlocks)
        return false;

    // check if the chain allows minimum difficulty blocks on recalc blocks
    if (pindexLast->nHeight < 157500)
    // if (!params.fPowAllowDigishieldMinDifficultyBlocks)  <-- COMMENTED OUT!
        return false;

    // Allow for a minimum block time if the elapsed time > 2*nTargetSpacing
    return (pblock->GetBlockTime() > pindexLast->GetBlockTime() + params.nPowTargetSpacing*2);
}
```

**The `fPowAllowDigishieldMinDifficultyBlocks` parameter check is COMMENTED OUT** and replaced with a hardcoded height check (`pindexLast->nHeight < 157500`).

### Impact

This allows unlimited chaining of minimum difficulty blocks via timestamp manipulation (time-warp attack):

1. Miner creates block with timestamp > 2 minutes after previous block
2. Block gets minimum difficulty (easiest possible)
3. Miner immediately creates next block with manipulated timestamp
4. Process repeats indefinitely

### Current Testnet Status (January 2026)

| Metric | Expected | Actual |
|--------|----------|--------|
| Block Height | ~5,000,000 | **~31,000,000** |
| Block Rate | 1 per minute | **3.3 per second** (180x faster!) |
| Difficulty | Dynamic | **Frozen at 0.00087** |
| Active Miners | Many | **Only 2 control 100%** |

**Consequences:**
- Block explorers crashing due to memory overflow
- chain.so/DOGETEST is no longer functional
- Testing impossible - blocks arrive faster than indexers can process
- Merged mining blocks go stale before submission

## Official Dogecoin Fix

### PR #3967: Add strict minimum difficulty rules to prevent testnet block storms

**Link:** https://github.com/dogecoin/dogecoin/pull/3967

**Author:** @cf (PsyProtocol)

**Status:** Under review (opened January 22, 2026)

**Core Dev Response:** Patrick Lodder (Dogecoin maintainer) commented:
> "I'm concept ACK on doing this in a testnet4alpha."

### Proposed Fix (from PR #3967)

```cpp
bool AllowDigishieldMinDifficultyForBlock(const CBlockIndex* pindexLast, const CBlockHeader *pblock, const Consensus::Params& params)
{
    // check if the chain allows minimum difficulty blocks
    if (!params.fPowAllowMinDifficultyBlocks)
        return false;

    // New strict rules when fEnforceStrictMinDifficulty is enabled
    if (params.fEnforceStrictMinDifficulty)
    {
        // 1. Prevent block storm attacks - no consecutive min-diff blocks
        if (pindexLast->nBits == UintToArith256(params.powLimit).GetCompact())
            return false;

        // 2. Prevent time-warp attacks via MTP check
        if (pblock->GetBlockTime() <= pindexLast->GetMedianTimePast() + params.nPowTargetSpacing * 10)
            return false;

        // 3. Increased threshold: 10x instead of 2x target spacing
        return (pblock->GetBlockTime() > pindexLast->GetBlockTime() + params.nPowTargetSpacing * 10);
    }

    // Legacy behavior (unchanged for mainnet compatibility)
    if (!params.fPowAllowDigishieldMinDifficultyBlocks)
        return false;

    return (pblock->GetBlockTime() > pindexLast->GetBlockTime() + params.nPowTargetSpacing * 2);
}
```

### Comparison with Bitcoin BIP-94 (Testnet4)

| Feature | BIP-94 (Bitcoin) | PR #3967 (Dogecoin) |
|---------|------------------|---------------------|
| Consecutive min-diff prevention | ✅ | ✅ |
| Time-warp prevention | Via retarget period adjustment | Via MTP + threshold check |
| Min-diff time threshold | 20 minutes (2× 10-min target) | 10 minutes (10× 1-min target) |
| Difficulty retarget fix | Uses first block of 2016-block period | N/A (Digishield retargets every block) |

## Our Workaround: Private Testnet4

Until Dogecoin Core releases official testnet4alpha, we run a private testnet with fixed parameters.

### Key Changes

```cpp
// In chainparams.cpp for our private testnet4alpha:
consensus.fPowAllowMinDifficultyBlocks = false;  // Disable min-diff entirely
consensus.fPowAllowDigishieldMinDifficultyBlocks = false;
consensus.fDigishieldDifficultyCalculation = true;
consensus.nPowTargetSpacing = 60;  // 1 minute blocks
consensus.nPowTargetTimespan = 60; // Retarget every block
```

### Setup Files

- `dogecoin_testnet4alpha.patch` - Patch to add testnet4alpha chain parameters
- `setup_dogecoin_testnet4alpha.sh` - Build script for patched Dogecoin
- `mine_genesis.py` - Genesis block miner using original Satoshi phrase

### Network Configuration

| Parameter | Value |
|-----------|-------|
| Network Magic | 0xd4, 0xd3, 0xd2, 0xd1 |
| Default Port | 44556 |
| RPC Port | 44555 |
| Address Prefix (P2PKH) | 113 ('n') |
| Address Prefix (P2SH) | 196 ('2') |

## Migration Plan

When Dogecoin Core releases official testnet4alpha:

1. **Stop** our private testnet nodes
2. **Update** to official Dogecoin release with testnet4alpha support
3. **Update** P2Pool network configuration:
   - Update `p2pool/networks/dogecoin_testnet.py` with new genesis hash
   - Update port numbers if different
   - Update address prefixes if different
4. **Test** merged mining on official testnet4alpha
5. **Archive** private testnet data

## References

### Dogecoin GitHub

- **PR #3967:** https://github.com/dogecoin/dogecoin/pull/3967
- **dogecoin.cpp (bug location):** https://github.com/dogecoin/dogecoin/blob/master/src/dogecoin.cpp#L22-L39
- **pow.cpp (difficulty logic):** https://github.com/dogecoin/dogecoin/blob/master/src/pow.cpp
- **chainparams.cpp (testnet params):** https://github.com/dogecoin/dogecoin/blob/master/src/chainparams.cpp#L229-L370

### Testnet Health Reports

- **Dogecoin Testnet Health Report:** https://doge-testnet.psy.xyz/testnet-health-report/index.html
- **Testnet Block Explorer:** https://doge-testnet.psy.xyz/

### Related Bitcoin Work

- **BIP-94 (Bitcoin Testnet4):** https://github.com/bitcoin/bips/blob/master/bip-0094.mediawiki
- **Bitcoin PR #29775:** https://github.com/bitcoin/bitcoin/pull/29775

## Git History

The bug was introduced in commit `53068fb220ad` by Ross Nicoll on May 22, 2021:

```
commit 53068fb220ad
Author: Ross Nicoll <ross.nicoll@gmail.com>
Date:   Sat May 22 14:10:45 2021

    Introduce Dogecoin difficulty calculations
```

The `fPowAllowDigishieldMinDifficultyBlocks` check was **already commented out** when the code was first introduced - this was not a later modification. It appears the intent was to enable min-difficulty for testnet after height 157500, but the implementation allows abuse.

## Timeline

| Date | Event |
|------|-------|
| May 22, 2021 | Bug introduced in commit 53068fb220ad |
| ~2024-2025 | Testnet block storms begin as miners exploit the vulnerability |
| January 5, 2026 | Block 24,000,000 mined |
| January 22, 2026 | PR #3967 opened to fix the bug |
| January 26, 2026 | Block count exceeds 31,000,000 |

---

*Document created: January 26, 2026*
*Last updated: January 26, 2026*
*P2Pool-Dash version: 1.1.1 (feature/scrypt-litecoin-dogecoin branch)*
