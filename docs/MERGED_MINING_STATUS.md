# P2Pool Merged Mining Status

## Date: February 15, 2026

## Current State: ✅ OPERATIONAL - V36 Multi-Output Merged Mining VALIDATED

### Recent Updates (Feb 2026)

- ✅ **Three-node V35/V36 mixed testnet validated** — no breakage
- ✅ **Multi-output PPLNS coinbase** verified on DOGE chain (5 vouts per block: 3 miner payouts + OP_RETURN + donation marker)
- ✅ **Critical endianness bug fixed** (commit 3e2b3f6) — was preventing ALL merged block detection
- ✅ **Donation marker dust** (commit cbf9047) — donation output always carries minimum 1 DOGE
- ✅ **Secondary donation script** — pre-V36 fake miner + post-V36 P2MS implemented
- ✅ **Web dashboard** — Est. Payout, merged blocks table, summary cards in miner.html
- ✅ **RPC fallback** for block verification after node restarts
- ✅ **Design docs updated** — Added Parts 14-16 to V36_IMPLEMENTATION_PLAN.md

### Infrastructure Status

#### ✅ Litecoin Core Testnet
- **Status**: Fully synced and operational
- **RPC Port**: 19332 (on LTC_DAEMON_IP)
- **Version**: Standard Litecoin Core with Segwit/MWEB support

#### ✅ Dogecoin Core Testnet4alpha
- **Status**: Running and operational
- **RPC Port**: 44555 (on DOGE_DAEMON_IP)
- **P2P Port**: 44557 (testnet4alpha — stable alternative to official DOGE testnet)
- **Version**: v1.14.99.0-436b09bb8 (MODIFIED with auxpow/getblocktemplate)
- **Feature**: getblocktemplate with auxpow capability ✅ VERIFIED
- **Note**: testnet4alpha (Dogecoin PR #3967) adds fEnforceStrictMinDifficulty=true to prevent block storms that plague official DOGE testnet

#### ✅ P2Pool V36 Nodes (2 of 3)
- **nodeA** (NODE_A_IP): V36, miner `mwQqcRjWsCSvMfFrAvpcCujofQSFcV1AsW`, ~1.2 MH/s
- **nodeB** (NODE_B_IP): V36, miner `mxptR46XQBRk3EHstU83QRQcqT2PCVkW3g`, ~1.2 MH/s
- **nodeC** (NODE_C_IP): V35 (jtoomim baseline), miner `mzisknENRPyyPS1M54qmwatfLhaMyFwRYQ`, ~1.2 MH/s
- **mm-adapter**: 127.0.0.1:44556 on each V36 node (adapter.py in screen session)
- **Runtime**: PyPy 2.7 (pypy2.7-v7.3.20-linux64)
- **Pool Stats**: ~4 MH/s total, ~1000+ shares, 3 peers

### Addresses

#### Litecoin Testnet (per node)
- **nodeA**: `mwQqcRjWsCSvMfFrAvpcCujofQSFcV1AsW`
- **nodeB**: `mxptR46XQBRk3EHstU83QRQcqT2PCVkW3g`
- **nodeC**: `mzisknENRPyyPS1M54qmwatfLhaMyFwRYQ`

#### Dogecoin Testnet (auto-converted from LTC via pubkey_hash)
- Address conversion: LTC testnet (v111) → DOGE testnet (v113)
- Same pubkey_hash produces correct address for each chain

### Modified Dogecoin Features

#### Auxpow Capability Test Results ✅

**Command:**
```bash
~/start-dogecoin-auxpow.sh ~/bin-auxpow/dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}'
```

**Response (excerpt):**
```json
{
  "version": 6422788,
  "height": 21482578,
  "coinbasevalue": 1000000000000,
  "previousblockhash": "8cdfedd0d08acd6b...",
  "auxpow": {
    "chainid": 98,
    "target": "000000000000000000000000000000000000000000000000000000ffff0f0000"
  }
}
```

**Verification**: ✅ PASS
- Auxpow object present in response
- Chain ID correctly set to 98 (Dogecoin)
- Target provided in reversed byte order
- Full block template includes transactions, coinbasevalue, etc.

#### Key Differences from Standard Dogecoin

| Feature | Standard Dogecoin | Modified Dogecoin |
|---------|------------------|-------------------|
| RPC Method | `getauxblock()` | `getblocktemplate({"capabilities": ["auxpow"]})` |
| Coinbase Control | Dogecoin Core builds | P2Pool builds (multiaddress) |
| Payout Model | Single address | Multiple addresses per share |
| Transaction List | Not provided | Full list included |
| Submission | `getauxblock(hash, auxpow)` | `submitblock(block_hex)` |
| BIP 22/23 Compliant | ❌ No | ✅ Yes |

### Implementation Status

#### ✅ Completed
1. **Segwit/MWEB Support**: Added conditional rules to getblocktemplate
2. **Universal Coind Naming**: Renamed dashd→coind across entire codebase
3. **Transaction Parsing**: Fixed LateEnd errors with proper Segwit support
4. **Dynamic Helper Selection**: Automatically selects bitcoin/litecoin helper based on network
5. **P2Pool Startup**: Successfully starts and connects to Litecoin testnet
6. **Address Generation**: Created all necessary testnet addresses
7. **Modified Dogecoin**: Found, verified, and started auxpow-capable daemon
8. **Auxpow Testing**: Verified getblocktemplate with auxpow capability works

#### 🔄 In Progress
1. **Merged Mining Refactoring**: Transitioning from getauxblock to getblocktemplate with auxpow

#### ⏳ Pending
1. **Detection and Compatibility**: Add auxpow capability detection to P2Pool
2. **Coinbase Building**: Implement multiaddress coinbase construction
3. **Block Building**: Implement complete Dogecoin block construction
4. **Submission Logic**: Update to use submitblock instead of getauxblock
5. **Integration Testing**: Test complete merged mining flow
6. **Production Deployment**: Deploy to remote server and monitor

### Current Merged Mining Implementation

#### How getauxblock Works (Current)
```python
# Get work
auxblock = yield merged_proxy.rpc_getauxblock()
# Returns: {"hash": "...", "target": "...", "chainid": 98}

# Store work
self.merged_work.set({chainid: {
    'hash': int(auxblock['hash'], 16),
    'target': unpack(auxblock['target']),
    'merged_proxy': merged_proxy,
}})

# Submit solved block
merged_proxy.rpc_getauxblock(
    hash_hex,  # Block hash
    auxpow_hex # Auxpow proof
)
```

**Limitations:**
- Pool operator provides single Dogecoin address to daemon
- All Dogecoin rewards go to that one address
- Miners only get paid in Litecoin
- Pool operator must manually distribute Dogecoin

#### How getblocktemplate with auxpow Works (Target)
```python
# Get template with auxpow capability
template = yield merged_proxy.rpc_getblocktemplate({"capabilities": ["auxpow"]})
# Returns: Full block template including auxpow object

# Build coinbase with multiple outputs (one per shareholder)
coinbase_outputs = []
for miner_address, share_fraction in shareholders:
    amount = template['coinbasevalue'] * share_fraction
    coinbase_outputs.append({'address': miner_address, 'value': amount})

# Build complete Dogecoin block
dogecoin_block = build_block(
    template=template,
    coinbase=build_tx(outputs=coinbase_outputs),
    auxpow=build_auxpow_proof(litecoin_block),
)

# Submit complete block
merged_proxy.rpc_submitblock(dogecoin_block.encode('hex'))
```

**Benefits:**
- Each miner provides both Litecoin AND Dogecoin addresses
- Dogecoin rewards distributed proportionally based on shares
- Trustless: No pool operator custody
- Fair: Same payout model for both chains

### File Locations

#### Local Development
- **P2Pool**: /home/YOUR_USER/Documents/GitHub/p2pool-dash
- **Reference Repo**: /home/YOUR_USER/Documents/GitHub/jtoomim-p2pool
- **Modified Dogecoin Repo**: /home/YOUR_USER/dogecoin-auxpow-gbt

#### Remote Server (YOUR_SERVER_IP)
- **P2Pool**: /home/YOUR_USER/p2pool-dash
- **Dogecoin Binaries**: /home/YOUR_USER/bin-auxpow/
- **Dogecoin Libraries**: /home/YOUR_USER/lib/
- **Startup Script**: /home/YOUR_USER/start-dogecoin-auxpow.sh
- **Dogecoin Source**: /home/YOUR_USER/dogecoin-auxpow-gbt (not built on server)
- **Litecoin Binaries**: /home/YOUR_USER/bin/
- **Blockchain Data**:
  - Litecoin: /home/YOUR_USER/.litecoin/testnet4/
  - Dogecoin: /home/YOUR_USER/.dogecoin/testnet3/

### Key Code Files

#### Modified for Segwit Support
- `p2pool/dash/helper.py` - Added conditional segwit/mweb rules
- `p2pool/bitcoin/data.py` - Segwit-aware transaction parsing (from jtoomim)
- `p2pool/litecoin/helper.py` - Scrypt-specific helper with Segwit support
- `p2pool/node.py` - Dynamic helper selection based on SOFTFORKS_REQUIRED

#### Needs Modification for Auxpow
- `p2pool/work.py` - Lines 87-98: set_merged_work() function
- `p2pool/work.py` - Lines 475-495: Block submission logic
- `p2pool/merged_mining.py` - NEW: Helper functions for multiaddress coinbase

#### Configuration Files
- `start_p2pool_scrypt_testnet.sh` - Startup script with merged mining URL
- `p2pool/networks/dash_testnet.py` - Network configuration (if needed)
- `MERGED_MINING_REFACTOR_PLAN.md` - Detailed implementation plan

### Testing Checklist

#### ✅ Completed Tests
- [x] Litecoin Core RPC connectivity
- [x] Dogecoin Core RPC connectivity (auxpow version)
- [x] P2Pool startup with Litecoin testnet
- [x] Segwit transaction parsing
- [x] Address generation for both chains
- [x] getblocktemplate with auxpow capability
- [x] Modified Dogecoin daemon functionality
- [x] Auxpow capability detection in P2Pool
- [x] Multiaddress coinbase construction (5-vout: 3 miners + OP_RETURN + donation)
- [x] Complete Dogecoin block building with AuxPoW proof
- [x] Block submission via submitblock (through mm-adapter)
- [x] Share chain integration with multiaddress (V36 shares accepted by V35 peers)
- [x] End-to-end merged mining flow (14+ DOGE blocks found)
- [x] Payout verification on both chains (PPLNS proportional confirmed on-chain)
- [x] Donation marker with dust amount (1 DOGE minimum)
- [x] V35/V36 mixed pool stability (3-node cluster, ~4 MH/s)
- [x] Web dashboard: merged blocks table, Est. Payout, summary cards

#### ⏳ Pending Tests
- [ ] Three-Pool distribution model (V36 vs pre-V36 vs unconvertible categories)
- [ ] Hierarchical sub-chain architecture (small miner inclusion)
- [ ] Anti-hopping defenses (asymmetric difficulty adjustment)
- [ ] Mainnet deployment with real hashrate
- [ ] 24-hour stability test under sustained load
- [ ] Multiple merged chains simultaneously

### Next Steps (Prioritized)

#### Immediate (Today)
1. **Implement Auxpow Detection** (1 hour)
   - Modify `set_merged_work()` to try getblocktemplate first
   - Detect auxpow capability in response
   - Store flag for multiaddress support
   - Fallback to getauxblock if not supported

2. **Create Helper Module** (1 hour)
   - Create `p2pool/merged_mining.py`
   - Implement address decoding for Dogecoin
   - Implement coinbase script building
   - Add unit tests

#### Short Term (This Week)
3. **Build Coinbase Constructor** (2 hours)
   - Implement `build_merged_coinbase()` function
   - Calculate output amounts based on share fractions
   - Handle multiple outputs correctly
   - Test with mock shareholder data

4. **Build Block Constructor** (2 hours)
   - Implement `build_merged_block()` function
   - Integrate template transactions
   - Calculate merkle root
   - Attach auxpow proof

5. **Update Submission Logic** (1 hour)
   - Modify block submission in work.py
   - Add submitblock call for multiaddress
   - Keep getauxblock for backward compatibility
   - Add error handling

#### Medium Term (Next Week)
6. **Integration Testing** (3 hours)
   - Test with regtest first
   - Test with testnet
   - Connect real miner
   - Verify payouts

7. **Production Deployment** (2 hours)
   - Deploy to remote server
   - Update startup scripts
   - Monitor logs
   - Document procedures

### Known Issues

1. **None currently** - All previous issues resolved ✅

### Risk Factors

1. **Block Validation**: Dogecoin may reject blocks with incorrect format
   - **Mitigation**: Extensive testing on regtest before testnet

2. **Merkle Root Calculation**: Complex with multiple transactions
   - **Mitigation**: Use existing P2Pool merkle functions

3. **Share Chain Sync**: Need current shareholder state for coinbase
   - **Mitigation**: Cache recent state, use snapshot approach

4. **Performance**: Building complete blocks may be slower
   - **Mitigation**: Profile and optimize critical paths

### Resources

#### Documentation
- **Modified Dogecoin Impl**: /home/YOUR_USER/dogecoin-auxpow-gbt/IMPLEMENTATION_SUMMARY.md
- **Refactor Plan**: /home/YOUR_USER/Documents/GitHub/p2pool-dash/MERGED_MINING_REFACTOR_PLAN.md
- **Address Guide**: /home/YOUR_USER/Documents/GitHub/p2pool-dash/TESTNET_ADDRESSES.md
- **Test Report**: /home/YOUR_USER/dogecoin-auxpow-gbt/TEST_REPORT.md

#### Reference Code
- **jtoomim P2Pool**: /home/YOUR_USER/Documents/GitHub/jtoomim-p2pool
- **Modified Dogecoin**: /home/YOUR_USER/dogecoin-auxpow-gbt/src/rpc/mining.cpp (lines 370-781)
- **P2Pool Work Module**: /home/YOUR_USER/Documents/GitHub/p2pool-dash/p2pool/work.py

#### Key Git Commits
- **Segwit/MWEB Support**: Local changes in feature/scrypt-litecoin-dogecoin
- **Coind Rename**: 197 occurrences across 9 files
- **Auxpow Feature**: dogecoin-auxpow-gbt@436b09bb8

### ✅ SUCCESS - All Metrics Achieved!

**December 25, 2025** - System is fully operational:

1. ✅ **P2Pool Startup**: Successfully connects to both Litecoin and Dogecoin (auxpow)
2. ✅ **Template Retrieval**: Gets auxpow-capable templates from Dogecoin
3. ✅ **Coinbase Construction**: Builds multiaddress coinbase with shareholder outputs and auto-conversion
4. ✅ **Block Mining**: Miners work on Litecoin blocks as usual
5. ✅ **Block Submission**: Successfully submits blocks to both chains - **6+ Dogecoin blocks accepted!**
6. ✅ **Address Conversion**: Automatic LTC→DOGE address conversion working correctly
7. ✅ **Hash Link Validation**: gentx validation proven working (state/extra/length match perfectly)
8. ✅ **Pseudoshare Handling**: Normal miner behavior (low-difficulty work) correctly identified
9. ⏳ **Sharechain**: Waiting for first P2Pool share (~3.8 minutes with 126 kH/s)
10. ⏳ **Payout Distribution**: Will be verified once sharechain has history

### Implementation Timeline

- **Phase 1-3** (Dec 19-22): Infrastructure setup and auxpow verification
- **Phase 4** (Dec 23): Multiaddress coinbase implementation
- **Phase 5** (Dec 24): Address conversion and payout consolidation
- **Phase 6** (Dec 25): Hash link debugging and validation confirmation

**Total**: ~6 days from start to working merged mining system

### Contact Information

- **User**: YOUR_USER@YOUR_SERVER_IP
- **Modified Dogecoin Repo**: frstrtr/dogecoin-auxpow-gbt
- **P2Pool Repo**: Local fork with feature/scrypt-litecoin-dogecoin branch

---

## Summary

✅ **Infrastructure**: Both Litecoin and modified Dogecoin (with auxpow) running successfully
✅ **Auxpow Capability**: getblocktemplate with auxpow confirmed working
✅ **P2Pool Core**: Successfully starts and mines Litecoin testnet
✅ **Merged Mining**: **OPERATIONAL** - Multiaddress coinbase with auto-conversion working
✅ **Block Acceptance**: **6+ Dogecoin merged mining blocks accepted!**
✅ **Validation**: gentx hash_link mechanism proven correct
⏳ **Sharechain**: Waiting for first P2Pool share (expected in ~3.8 minutes)

### Key Findings

**Hash Link Validation (Dec 25)**:
- Extensive debug instrumentation captured complete hash_link lifecycle
- PREFIX_TO_HASH_LINK and CHECK_HASH_LINK show IDENTICAL values (state/extra/length)
- gentx_hash reconstruction working correctly
- "share PoW invalid" errors are **pseudoshares** (normal low-difficulty miner submissions)
- Actual merged mining blocks that meet difficulty ARE being accepted
- System is working correctly - no validation issues!

**Next Actions**: 
1. Wait for P2Pool share to verify sharechain functionality
2. Monitor PPLNS payout distribution once sharechain has history  
3. Clean up debug output for production deployment
