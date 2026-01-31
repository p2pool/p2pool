# Task: Implement getblocktemplate auxpow Support in Dogecoin Core

## Objective

Fork Dogecoin Core and add `auxpow` capability to the `getblocktemplate` RPC method, enabling trustless merged mining for P2Pool without requiring single-address coinbase transactions.

## Repository Setup

### 1. Fork and Clone
```bash
# Fork https://github.com/dogecoin/dogecoin on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/dogecoin.git
cd dogecoin

# Add upstream remote
git remote add upstream https://github.com/dogecoin/dogecoin.git

# Create feature branch from v1.14.9
git checkout v1.14.9
git checkout -b feature/getblocktemplate-auxpow
```

### 2. Build Environment
```bash
# Install dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install build-essential libtool autotools-dev automake \
  pkg-config bsdmainutils python3 libssl-dev libevent-dev \
  libboost-system-dev libboost-filesystem-dev libboost-chrono-dev \
  libboost-test-dev libboost-thread-dev libdb-dev libdb++-dev

# Build
./autogen.sh
./configure --without-gui --with-incompatible-bdb
make -j$(nproc)
```

## Technical Analysis

### Files to Review

1. **src/rpc/mining.cpp** - Main getblocktemplate implementation
   - `getblocktemplate()` function
   - Template generation logic
   - Capabilities parsing

2. **src/rpc/mining.h** - RPC declarations

3. **src/primitives/block.h** - Block structure
   - `CAuxPow` class
   - Auxpow serialization

4. **src/primitives/block.cpp** - Block implementation
   - Auxpow validation
   - Merkle proof construction

5. **src/pow.cpp** - Proof-of-work logic
   - Auxpow verification
   - Target calculation

### Existing Auxpow Implementation (Reference)

Study these existing RPC methods:
- `createauxblock()` - How auxpow blocks are created
- `getauxblock()` - Legacy merged mining interface
- `submitauxblock()` - How auxpow is submitted

Key insights needed:
- How chainid is determined
- How auxpow structure is built
- What fields are required
- How target is formatted

## Implementation Tasks

### Phase 1: Code Analysis (2-3 days)

**Deliverables:**
- [ ] Document current getblocktemplate flow
- [ ] Document createauxblock flow
- [ ] Identify differences between the two
- [ ] Map required changes

**Files to analyze:**
```bash
# Find getblocktemplate implementation
grep -rn "getblocktemplate" src/rpc/

# Find createauxblock implementation
grep -rn "createauxblock" src/rpc/

# Find auxpow structure
grep -rn "CAuxPow" src/
```

**Key Questions:**
1. Where is coinbasetxn added to getblocktemplate response?
2. How does createauxblock build the coinbase?
3. What auxpow-specific data is needed?
4. How is chainid stored/retrieved?

### Phase 2: Implement auxpow Capability (3-5 days)

**Changes to src/rpc/mining.cpp:**

#### 2.1 Add Capability Detection
```cpp
// In getblocktemplate() function
bool fAuxPow = false;

// Parse capabilities array
if (request.params.size() > 0) {
    const UniValue& capabilities = request.params[0]["capabilities"];
    if (capabilities.isArray()) {
        for (unsigned int idx = 0; idx < capabilities.size(); idx++) {
            if (capabilities[idx].get_str() == "auxpow") {
                fAuxPow = true;
                break;
            }
        }
    }
}
```

#### 2.2 Modify Response for auxpow
```cpp
// When fAuxPow is true:
// 1. Omit "coinbasetxn" field
// 2. Add auxpow-specific fields

if (fAuxPow) {
    // Add chainid
    result.pushKV("chainid", Params().GetConsensus().nAuxpowChainId);
    
    // Don't include pre-built coinbase
    // (Let P2Pool build it with multiple outputs)
    
} else {
    // Normal behavior - include coinbasetxn
    result.pushKV("coinbasetxn", coinbasetxn);
}
```

#### 2.3 Add auxpow-Specific Fields
```cpp
if (fAuxPow) {
    UniValue auxpow(UniValue::VOBJ);
    
    // Chain ID for merged mining
    auxpow.pushKV("chainid", Params().GetConsensus().nAuxpowChainId);
    
    // Target in auxpow format (reversed)
    auxpow.pushKV("target", HexStr(arith_uint256().SetCompact(nBits).GetHex()));
    
    // Indicate that coinbase must be built by caller
    auxpow.pushKV("coinbasevalue", nCoinbaseValue);
    auxpow.pushKV("coinbaseaux", coinbaseaux);
    
    result.pushKV("auxpow", auxpow);
}
```

**Deliverables:**
- [ ] Modified getblocktemplate() function
- [ ] Capability detection logic
- [ ] Auxpow-specific response fields
- [ ] Code compiles without errors

### Phase 3: Testing (3-4 days)

#### 3.1 Unit Tests
```cpp
// Add to src/test/rpc_tests.cpp
BOOST_AUTO_TEST_CASE(getblocktemplate_auxpow)
{
    // Test auxpow capability detection
    // Test response format
    // Test field presence/absence
}
```

#### 3.2 Testnet Testing
```bash
# Start testnet node with your changes
./src/dogecoind -testnet -daemon

# Test basic getblocktemplate
./src/dogecoin-cli -testnet getblocktemplate

# Test with auxpow capability
./src/dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}'

# Verify response contains:
# - chainid field
# - NO coinbasetxn field
# - auxpow-specific data
```

#### 3.3 Integration Test with P2Pool
```bash
# Build test block with P2Pool
# Verify auxpow structure
# Submit to testnet
# Confirm block acceptance
```

**Deliverables:**
- [ ] Unit tests pass
- [ ] Testnet deployment successful
- [ ] Manual RPC testing complete
- [ ] Block construction verified
- [ ] Block submission verified
- [ ] Block acceptance confirmed

### Phase 4: Documentation (1-2 days)

#### 4.1 RPC Help Text
```cpp
// Update getblocktemplate help in src/rpc/mining.cpp
"If 'auxpow' is included in capabilities array:\n"
"  - 'coinbasetxn' will be omitted\n"
"  - 'auxpow' object will be added with:\n"
"    - 'chainid': merged mining chain ID\n"
"    - 'target': block target for auxpow\n"
"  - Caller must build coinbase transaction\n"
```

#### 4.2 Update README
Add section explaining:
- New auxpow capability
- How to use it
- Differences from createauxblock
- P2Pool integration

**Deliverables:**
- [ ] RPC help text updated
- [ ] README.md updated
- [ ] Example usage documented

### Phase 5: Deployment (1 day)

```bash
# Tag your release
git tag -a v1.14.9-auxpow-p2pool -m "Add getblocktemplate auxpow support for P2Pool"
git push origin feature/getblocktemplate-auxpow --tags

# Build release binaries
make clean
./configure --without-gui --with-incompatible-bdb
make -j$(nproc)
strip src/dogecoind src/dogecoin-cli

# Package
tar czf dogecoin-1.14.9-auxpow-p2pool-x86_64-linux-gnu.tar.gz \
  src/dogecoind src/dogecoin-cli
```

**Deliverables:**
- [ ] Release tagged
- [ ] Binaries built
- [ ] Package created
- [ ] Installation instructions

## Expected Response Format

### Before (createauxblock)
```json
{
  "hash": "...",
  "chainid": 98,
  "previousblockhash": "...",
  "coinbasevalue": 10000000000,
  "bits": "1e0ffff0",
  "height": 12345,
  "target": "..."
}
```

### After (getblocktemplate with auxpow)
```json
{
  "version": 6422788,
  "rules": [],
  "previousblockhash": "...",
  "transactions": [...],
  "coinbaseaux": {
    "flags": "062f503253482f"
  },
  "coinbasevalue": 10000000000,
  "target": "...",
  "mintime": 1234567890,
  "mutable": ["time", "transactions", "prevblock"],
  "noncerange": "00000000ffffffff",
  "curtime": 1234567890,
  "bits": "1e0ffff0",
  "height": 12345,
  "auxpow": {
    "chainid": 98,
    "target": "00000000ffff0000000000000000000000000000000000000000000000000000"
  }
}
```

**Key Differences:**
- ❌ No `coinbasetxn` field (caller builds it)
- ✅ Add `auxpow` object with chainid
- ✅ Include full transaction list
- ✅ Include coinbaseaux for scriptSig
- ✅ Include coinbasevalue for calculations

## Validation Checklist

### Functional Requirements
- [ ] Detects "auxpow" in capabilities array
- [ ] Omits coinbasetxn when auxpow requested
- [ ] Includes auxpow object with chainid
- [ ] Returns correct coinbasevalue
- [ ] Returns correct bits/target
- [ ] Returns transaction list
- [ ] Backward compatible (works without auxpow)

### Testing Requirements
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Testnet blocks accepted
- [ ] P2Pool can construct valid blocks
- [ ] Standard nodes accept resulting blocks
- [ ] Performance acceptable (no slowdown)

### Documentation Requirements
- [ ] RPC help text accurate
- [ ] Examples provided
- [ ] Installation instructions clear
- [ ] P2Pool integration documented

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 1. Code Analysis | 2-3 days | Documentation of current flow |
| 2. Implementation | 3-5 days | Working code changes |
| 3. Testing | 3-4 days | Verified functionality |
| 4. Documentation | 1-2 days | Complete docs |
| 5. Deployment | 1 day | Release package |
| **Total** | **10-15 days** | **Production-ready fork** |

## Success Criteria

✅ **Functionality:**
- getblocktemplate accepts `{"capabilities":["auxpow"]}`
- Response omits coinbasetxn
- Response includes chainid
- P2Pool can build valid blocks

✅ **Compatibility:**
- Backward compatible (non-auxpow requests unchanged)
- Blocks accepted by standard Dogecoin nodes
- No consensus changes
- No breaking changes

✅ **Quality:**
- Code compiles cleanly
- Tests pass
- No memory leaks
- Performance unchanged

✅ **Documentation:**
- Clear usage instructions
- RPC help updated
- Examples provided

## Reference Resources

### Dogecoin Core
- Main repo: https://github.com/dogecoin/dogecoin
- Latest release: v1.14.9
- Auxpow spec: https://en.bitcoin.it/wiki/Merged_mining_specification

### Namecoin (Reference Implementation)
- Repo: https://github.com/namecoin/namecoin-core
- Already has getblocktemplate with auxpow
- Study their implementation for guidance

### Bitcoin Core (Base Implementation)
- getblocktemplate: https://github.com/bitcoin/bips/blob/master/bip-0022.mediawiki
- BIP 22: getblocktemplate fundamentals
- BIP 23: Pooled mining extensions

### P2Pool Integration
- P2Pool repo: https://github.com/frstrtr/p2pool-dash
- Work module: p2pool/work.py (lines 84-99, 510-534)
- Integration point for merged mining

## Notes

### Why This Works Without Consensus Changes

The resulting blocks are **identical** regardless of how they're constructed:

```
createauxblock Method:
  Dogecoin Core builds coinbase → auxpow block → network accepts

getblocktemplate Method:
  P2Pool builds coinbase → auxpow block → network accepts
```

Both produce valid auxpow blocks with:
- Same block structure
- Same auxpow format
- Same validation rules
- Same merkle proof
- Same difficulty

The only difference is **who builds the coinbase** (Dogecoin Core vs P2Pool).

### Security Considerations

- ✅ No new attack vectors (same validation)
- ✅ No consensus changes (same rules)
- ✅ No trust requirements (P2Pool verifiable)
- ✅ Backward compatible (optional capability)

### Maintenance

This fork only needs updates when:
- Dogecoin Core releases major versions
- Auxpow specification changes (unlikely)
- Bugs discovered in implementation

Estimated maintenance: < 4 hours per year

## Questions to Answer During Implementation

1. **Where is chainid stored?** → Params().GetConsensus().nAuxpowChainId
2. **How is target formatted for auxpow?** → Study createauxblock output
3. **What goes in coinbaseaux?** → Same as regular getblocktemplate
4. **How to handle version bits?** → Same as regular blocks
5. **Any special auxpow validation?** → No, handled by existing code

## Contact

For questions or issues during implementation:
- Dogecoin Core docs: https://dogecoin.com/
- P2Pool integration: Check p2pool/work.py
- Auxpow specification: Bitcoin wiki merged mining page
