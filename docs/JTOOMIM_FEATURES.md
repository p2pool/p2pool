# Features Adopted from jtoomim/p2pool

This document tracks the features we adopted from Jonathan Toomim's p2pool implementation for Scrypt-based coins.

## Repository
- Source: https://github.com/jtoomim/p2pool
- Focus: Litecoin/Scrypt support with segwit, MWEB, and modern features

## Key Features Implemented

### 1. Scrypt Hash Module (`litecoin_scrypt/`)
- **C Extension**: `scryptmodule.c` + `scrypt.c` 
- **Function**: `ltc_scrypt.getPoWHash()` - optimized Scrypt N=1024, r=1, p=1
- **Setup**: `litecoin_scrypt/setup.py` for building extension
- **Scratchpad**: 131,583 bytes (defined in scrypt.h)
- **Algorithm**: Salsa20/8, PBKDF2-SHA256 based
- **Performance**: Significantly faster than pure Python implementation

### 2. DUMB_SCRYPT_DIFF Multiplier
```python
DUMB_SCRYPT_DIFF = 2**16  # Applied to all Scrypt networks
```
- **Purpose**: Corrects difficulty display for Scrypt vs SHA256
- **Usage**: In stratum.py line 89 and data.py line 574
- **Calculation**: `diff = DUMB_SCRYPT_DIFF * target_to_difficulty(target)`
- **Reason**: Scrypt hashes are not directly comparable to SHA256 difficulty

### 3. Segwit Support
**Network Parameters:**
```python
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit', 'mweb'])
MINIMUM_PROTOCOL_VERSION = 3301
SEGWIT_ACTIVATION_VERSION = 17
```

**Address Support:**
- Bech32 encoding/decoding (`p2pool/util/segwit_addr.py`)
- `HUMAN_READABLE_PART = 'ltc'` (mainnet) or `'tltc'` (testnet)
- `ADDRESS_P2SH_VERSION = 50` (mainnet) or `58` (testnet)

**Transaction Handling:**
- Witness commitment hash in coinbase
- wtxid merkle root calculation
- Marker/flag bytes for segwit tx
- Witness data stripping for txid calculation

### 4. MWEB (MimbleWimble Extension Blocks)
- **Feature**: Litecoin-specific privacy extension
- **Integration**: Part of SOFTFORKS_REQUIRED set
- **RPC**: `getblocktemplate` includes 'mweb' field when available
- **Helper**: `helper.py` line 141 handles MWEB data in work construction

### 5. Network Configuration Details

**Litecoin Testnet:**
```python
P2P_PREFIX = 'fdd2c8f1'
P2P_PORT = 19335
RPC_PORT = 19332
BLOCK_PERIOD = 150  # 2.5 minutes
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//840000
SANE_TARGET_RANGE = (2**256//2**32//1000 - 1, 2**256//2**20 - 1)
```

**P2Pool Share Chain (Litecoin Testnet):**
```python
SHARE_PERIOD = 4  # seconds (very fast)
CHAIN_LENGTH = 20*60//3  # ~400 shares
P2P_PORT = 19338
WORKER_PORT = 19327
IDENTIFIER = 'cca5e24ec6408b1e'
PREFIX = 'ad9614f6466a39cf'
```

### 6. Stratum Implementation
**Key Features:**
- ASICBoost support (version_bits parameter in submit)
- Vardiff based on `STRATUM_SHARE_RATE` (default 10s target)
- `DUMB_SCRYPT_DIFF` applied to difficulty announcements
- Clean job handling for new work

**Mining Notify:**
```python
rpc_mining.rpc_set_difficulty(bitcoin_data.target_to_difficulty(self.target)*self.wb.net.DUMB_SCRYPT_DIFF)
```

### 7. Merged Mining Support
**Implementation** (`work.py` lines 276-288):
```python
if self.merged_work.value:
    tree, size = bitcoin_data.make_auxpow_tree(self.merged_work.value)
    mm_hashes = [self.merged_work.value.get(tree.get(i), dict(hash=0))['hash'] for i in xrange(size)]
    mm_data = '\xfa\xbemm' + bitcoin_data.aux_pow_coinbase_type.pack(dict(
        merkle_root=bitcoin_data.merkle_hash(mm_hashes),
        size=size,
        nonce=0,
    ))
```

**Auxpow Support:**
- `aux_pow_type` and `aux_pow_coinbase_type` structures
- Merkle tree construction for multiple merge-mined chains
- Chain ID tracking (Dogecoin = 98)

### 8. Block Template Enhancements
**Segwit Rules:**
```python
bitcoind.rpc_getblocktemplate(dict(
    mode='template', 
    rules=['segwit','mweb'] if 'mweb' in getattr(net, 'SOFTFORKS_REQUIRED', set()) else ['segwit']
))
```

**Transaction Processing:**
- wtxid calculation for segwit transactions
- Witness commitment in coinbase output
- Segregated witness data handling

### 9. Address Handling
**Bech32 Implementation:**
- `bech32_polymod()` - checksum computation
- `bech32_encode()` / `bech32_decode()` - address encoding
- HRP (Human Readable Part) expansion
- convertbits() for 5-bit encoding

**Cash Address Support:**
- BCH cash address format (separate from our implementation)
- Multiple address format coexistence

### 10. Share Chain Improvements
**Version Tracking:**
- `BaseShare.VERSION` determines feature availability
- `is_segwit_activated()` checks share version vs network
- Graceful feature rollout mechanism

**Share Types:**
- `PaddingBugfixShare`
- `SegwitMiningShare` (VERSION 17+)
- `NewShare`
- `PreSegwitShare`
- `Share` (latest)

## Installation Notes

### ltc_scrypt Module
```bash
cd litecoin_scrypt/
python setup.py build
python setup.py install
```

Or via pip (if available):
```bash
pip install ltc-scrypt
```

Fallback to pure Python:
```bash
pip install scrypt
```

## References

1. **Main Repo**: https://github.com/jtoomim/p2pool
2. **Litecoin Network**: `p2pool/bitcoin/networks/litecoin.py` and `litecoin_testnet.py`
3. **Scrypt Module**: `litecoin_scrypt/scrypt.c` and `scryptmodule.c`
4. **Segwit**: `p2pool/util/segwit_addr.py` and segwit handling in `data.py`
5. **Stratum**: `p2pool/bitcoin/stratum.py` with DUMB_SCRYPT_DIFF
6. **Work Construction**: `p2pool/work.py` with merge mining
7. **Share Chain**: `p2pool/networks/litecoin.py` and `litecoin_testnet.py`

## Differences from Our Implementation

### What We Kept Different:
1. **Module Structure**: We use `p2pool/litecoin/` parallel to `p2pool/dash/`
2. **Network Names**: We use `litecoin_testnet` and `dogecoin_testnet` in `p2pool/litecoin/networks/`
3. **Dogecoin Focus**: We specifically target Dogecoin auxpow testing

### What We Adopted:
1. ✅ DUMB_SCRYPT_DIFF = 2**16
2. ✅ Segwit address support (HUMAN_READABLE_PART)
3. ✅ SOFTFORKS_REQUIRED set
4. ✅ Proper SANE_TARGET_RANGE
5. ✅ ADDRESS_P2SH_VERSION for P2SH
6. ✅ SUBSIDY_FUNC for halvings
7. ✅ Share chain identifiers (IDENTIFIER, PREFIX)
8. ✅ Protocol version constants

### What We'll Add Later:
- [ ] ltc_scrypt C extension compilation
- [ ] Full segwit transaction handling
- [ ] MWEB support (if needed for Litecoin mainnet)
- [ ] Bech32 address generation in worker interface
- [ ] Vardiff with DUMB_SCRYPT_DIFF correction

## Next Steps

1. **Install ltc_scrypt**: Compile and install the C extension for performance
2. **Test Scrypt Hash**: Verify `scrypt_hash()` works with both backends
3. **Verify Networks**: Check that network parameters are correctly set
4. **Test Segwit**: Ensure bech32 address handling works (if needed)
5. **Merge Mining**: Test auxpow construction with Dogecoin node
6. **Stratum**: Verify DUMB_SCRYPT_DIFF is applied correctly in difficulty announcements

## Performance Notes

From jtoomim's implementation:
- C extension is **~10-100x faster** than pure Python scrypt
- Scratchpad allocation is optimized for cache efficiency
- Salsa20/8 implementation is hand-optimized assembly in some builds
- Memory usage: ~131KB scratchpad per hash operation

## Compatibility

Our implementation should be compatible with:
- ✅ jtoomim/p2pool Litecoin testnet nodes (share chain format)
- ✅ Standard Litecoin Core RPC (getblocktemplate)
- ✅ Dogecoin Core RPC with auxpow extensions
- ✅ Standard Stratum mining protocol
- ⚠️ Segwit transactions (requires full implementation)
- ⚠️ MWEB transactions (Litecoin-specific, optional)
