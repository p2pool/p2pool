# ASIC Support Fixes - December 2025

This document summarizes the fixes made to support high-hashrate ASIC miners (particularly Antminer D9 with ~1.7 TH/s each, ~10 TH/s total for 6 miners).

**Release v1.4.6** - Share Hash Rate Tracking Bug Fix (December 29, 2025)
**Release v1.4.5** - Protocol Version & Bootstrap Nodes Update (December 29, 2025)
**Release v1.4.4** - Stratum Statistics & Connected Miners API (December 29, 2025)
**Release v1.4.3** - Bug Fixes from Production Logs (December 26, 2025)
**Release v1.4.2** - Vardiff Critical Bug Fix (December 26, 2025)
**Release v1.4.1** - Share Difficulty & DOA Fixes (December 26, 2025)
**Release v1.4.0** - Twin Blocks Verified on Testnet (December 25, 2025)
**Release v1.2.1** - Share Version Switchover & SSL Handling (December 25, 2025)
**Release v1.2.0** - Litecoin+Dogecoin Merged Mining (December 25, 2025)
**Release v1.1.0** - Dash Platform support + Protocol v1700 (December 13, 2025)
**Release v1.0.0** - First stable release with full ASIC support (December 11, 2025)

## v1.4.6 - Share Hash Rate Tracking Bug Fix (December 29, 2025)

### Critical Bug: Miner Hash Rate Not Tracked for Valid Shares

**File:** `p2pool/work.py`

**Problem:** Valid P2Pool shares were not being tracked in `local_rate_monitor`, causing:
- Only 1 of 4 miners appearing in `miner_hash_rates` 
- Incorrect hash rate attribution
- Share broadcast and tracking code was inside wrong `elif` branch

**Root Cause:** Code flow bug in `got_response()`:
```python
# BEFORE (broken):
if pow_hash <= share_info['bits'].target and ... and work_merkle_root == header['merkle_root']:
    share = get_share(...)
    self.node.tracker.add(share)
    self.node.set_best_share()
    # Missing: share broadcast, share_received, local_rate_monitor!
elif pow_hash <= share_info['bits'].target and work_merkle_root != header['merkle_root']:
    pass  # Stale work
    # Code below was unreachable for valid shares!
    self.node.p2p_node.broadcast_share(share.hash)  # share undefined!
    self.share_received.happened(...)
    self.local_rate_monitor.add_datum(...)
```

**Solution:** Moved share broadcast and rate tracking into the valid share block:
```python
# AFTER (fixed):
if pow_hash <= share_info['bits'].target and ... and work_merkle_root == header['merkle_root']:
    share = get_share(...)
    self.node.tracker.add(share)
    self.node.set_best_share()
    # Now properly broadcasts and tracks valid shares
    self.node.p2p_node.broadcast_share(share.hash)
    self.share_received.happened(...)
    self.local_rate_monitor.add_datum(...)
elif pow_hash <= share_info['bits'].target and work_merkle_root != header['merkle_root']:
    # Stale work - track as dead, don't create share
    print 'Worker submitted P2Pool-quality share on stale work template'
    self.local_rate_monitor.add_datum(..., dead=True, ...)
```

**Impact:**
- All miners now properly tracked in `miner_hash_rates`
- Shares broadcast to P2P network when found
- Stale P2Pool shares counted as dead work (not lost)

## v1.4.5 - Protocol Version & Bootstrap Nodes Update (December 29, 2025)

### Critical Fix: 50% Orphan Rate Due to Network Isolation

**Problem:** Node had 50% share orphan rate because it was running on a separate, isolated share chain with 0 P2P peers connected.

**Root Cause Analysis:**
- All legacy bootstrap nodes offline
- Protocol version 3501 incompatible with active network running 3502
- Share chain diverged (absheight 16,862 vs network's 25,903,165)

**Solution:**

1. **Updated Protocol Version** (`p2pool/p2p.py`):
   ```python
   class Protocol(p2protocol.Protocol):
       VERSION = 3502  # Updated from 3501 to match active network
   ```

2. **Updated Bootstrap Nodes** (`p2pool/networks/litecoin.py`):
   ```python
   BOOTSTRAP_ADDRS = [
       # Active nodes discovered 2025 (protocol 3502)
       'ml.toom.im',           # jtoomim's node - healthy, 1.5% orphan rate
       '31.25.241.224',        # peer from ml.toom.im
       '20.106.76.227',        # peer from ml.toom.im
       '83.221.211.116',       # peer from ml.toom.im
       # Legacy nodes (may be offline)
       ...
   ]
   ```

**Impact:** Node should now connect to the active Litecoin p2pool network and sync proper share chain.

## v1.4.4 - Stratum Statistics & Connected Miners API (December 29, 2025)

### PoolStatistics Class Added to Stratum

**File:** `p2pool/bitcoin/stratum.py`

**Problem:** The web interface showed empty "Active miners" table because `miner_hash_rates` only tracked miners who submitted work within the activity window (~17 minutes). The `/payout_addrs` endpoint showed operator addresses, not connected miners.

**Solution:** Added `PoolStatistics` class (adapted from `p2pool-dash-backup/dash/stratum.py`) that tracks:

- **Connected workers** via weak references (auto-cleanup on disconnect)
- **Per-worker statistics**: shares, accepted/rejected, hash rate, last seen
- **Per-IP connection counts**
- **Global submission rate**

Key integration points:
```python
# On connection
pool_stats.register_connection(self.conn_id, self, self.worker_ip)

# On share submission
pool_stats.record_share(worker_name, current_diff, accepted=True/False)

# On disconnect
pool_stats.unregister_connection(self.conn_id, self.worker_ip)
```

### New API Endpoints

**File:** `p2pool/web.py`

Added two new endpoints:

1. **`/stratum_stats`** - Detailed stratum statistics:
```json
{
  "pool": {
    "connections": 5,
    "workers": 3,
    "unique_addresses": 2,
    "total_accepted": 1234,
    "total_rejected": 5,
    "submission_rate": 0.5,
    "uptime": 3600
  },
  "workers": {
    "LKNsF7AKzKHjN6neEbGn94ncc2qXbfYPkL.worker1": {
      "shares": 100,
      "accepted": 99,
      "rejected": 1,
      "hash_rate": 2190466744,
      "connections": 2
    }
  }
}
```

2. **`/connected_miners`** - List of currently connected miner addresses:
```json
["LKNsF7AKzKHjN6neEbGn94ncc2qXbfYPkL", "LTss57coTsCM58iGwox5wqExvKP37J6Ddt"]
```

## v1.4.3 - Bug Fixes from Production Logs (December 26, 2025)


### P2PNode banscore Typo Fix

**File:** `p2pool/p2p.py`

**Problem:** `AttributeError: 'P2PNode' object has no attribute 'banscore'`

The `forgive_transgressions()` method used `self.banscore` (singular) but the attribute is defined as `self.banscores` (plural).

**Fix:** Corrected typo and improved cleanup logic:
```python
def forgive_transgressions(self):
    for host in list(self.banscores.keys()):
        self.banscores[host] -= 1
        if self.banscores[host] <= 0:
            del self.banscores[host]
```

### WorkerBridge.address Missing Attribute

**File:** `p2pool/work.py`

**Problem:** `AttributeError: 'WorkerBridge' object has no attribute 'address'`

The `/payout_addr` web endpoint tried to access `wb.address` but this attribute was only set if `--dynamic-address` mode was used.

**Fix:** Initialize `self.address = None` in `__init__` so the attribute always exists.

## v1.4.2 - Vardiff Critical Bug Fix (December 26, 2025)

### Stratum Variable Difficulty Fix

**File:** `p2pool/bitcoin/stratum.py`

**Problem:** High-hashrate miners (18+ GH/s) were flooding the pool with shares, causing:
- 50% stale/orphan rate
- 5% mining efficiency  
- CPU overload preventing coind communication ("lost contact with coind")
- 400-600 shares/minute instead of target ~6 shares/minute

**Root Cause:** Two bugs in vardiff implementation:

1. **Target reset on new work (line 87):**
   ```python
   # BUG: max() always picks LARGER target (easier difficulty)
   self.target = x['share_target'] if self.target == None else max(x['min_share_target'], self.target)
   ```
   Every new work event (~72/min) reset the difficulty back to floor, preventing vardiff from ever increasing it.

2. **Same bug in vardiff adjustment loop (line 183):**
   ```python
   self.target = max(x['min_share_target'], self.target)  # Wrong direction!
   ```

3. **Slow convergence:** Original `clip(ratio, 0.5, 2.0)` limited adjustment to 2x per cycle, requiring ~200 cycles to reach proper difficulty for high-hashrate miners.

**Solution:**
```python
# Fix 1 & 2: Only enforce floor when target is TOO EASY (not too hard)
if self.target > x['min_share_target']:  # larger = easier
    self.target = x['min_share_target']

# Fix 3: Widen adjustment range for faster convergence
self.target = int(self.target * clip(ratio, 0.1, 10.) + 0.5)  # Was 0.5-2x
```

**Impact:**
| Metric | Before | After |
|--------|--------|-------|
| Stratum difficulty | ~61 (stuck at floor) | ~18,000-25,000 |
| Shares/minute | 400-600 | ~6 |
| Orphan rate | 50%+ | <5% |
| Efficiency | 5% | 95%+ |
| CPU load | Overloaded | Normal |

## v1.4.1 - Share Difficulty & DOA Fixes (December 26, 2025)

### Mainnet Share Difficulty Tuning

**Files:** `p2pool/networks/litecoin.py`, `p2pool/bitcoin/networks/litecoin.py`, `p2pool/bitcoin/networks/dogecoin.py`

**Problem:** With modern Scrypt ASICs (L9 at 16 GH/s each), the default MAX_TARGET was causing issues:
- Original `2**256//2**20` (diff 16) was too easy for ASIC farms
- At 160 GH/s pool hashrate, shares came every 0.4 seconds
- This caused massive orphan flooding (97% of shares wasted)

**Solution:** Adjusted MAX_TARGET to `2**256//2**21` (diff 32):
- At 13 GH/s: ~10.6 seconds per share (good balance)
- At 160 GH/s: ~1.4 seconds per share (acceptable, vardiff adjusts up)
- Larger pools auto-adjust to higher difficulty via vardiff

**Reference Table:**
| MAX_TARGET | Stratum Diff | 13 GH/s Time | 160 GH/s Time |
|------------|--------------|--------------|---------------|
| 2**256//2**20 | 16 | 5.3s | 0.4s (floods) |
| 2**256//2**21 | 32 | 10.6s ✓ | 0.9s |
| 2**256//2**24 | 256 | 84.6s (slow) | 6.9s |

### DOA (Dead On Arrival) Share Fix

**Files:** `p2pool/work.py`

**Problem:** In isolated testing (PERSIST=False, no peers), shares were marked "DEAD ON ARRIVAL" at 100% rate:
- Each new share triggers `new_work_event.happened()`
- With rapid share finding, work events fire faster than shares arrive
- Original tolerance of 3 work events was too tight
- All shares DOA → chain never grows → vardiff stuck at floor

**Solution:** Increased tolerance for isolated/testing nodes:
```python
# PERSIST=False (isolated testing): 30 events tolerance
# PERSIST=True (production): 3 events tolerance
max_work_events = 30 if not self.node.net.PERSIST else 3
on_time = work_event_diff <= max_work_events
```

### Transaction Parsing Bug Fix

**Files:** `p2pool/bitcoin/helper.py`

**Problem:** Error "AttributeError: 'long' object has no attribute 'encode'" when parsing failed transactions.

**Root Cause:** `txid` from `hash256()` is an integer, but code tried `txid.encode('hex')`.

**Solution:** Use format string instead: `'%064x' % txid`

---

## v1.2.1 - Share Version Switchover & SSL Handling (December 25, 2025)

### Critical Fixes for Litecoin Share Compatibility

**Files:** `p2pool/work.py`, `p2pool/main.py`

#### Share Version Switchover Bug Fix

**Problem:** When P2Pool hit the 95% threshold to upgrade share versions, it crashed with `AssertionError` during share packing. The error occurred because the share_data dict contained Dash-specific fields that don't exist in Litecoin's share structure.

**Root Cause:** The code was passing three Dash-specific fields in `share_data`:
- `payment_amount` - Reserved for Dash masternode/superblock payments
- `packed_payments` - List of masternode/superblock payee addresses and amounts
- `coinbase_payload` - Dash DIP2/DIP3 special transaction payload

These fields are part of the p2pool-dash share structure for Dash cryptocurrency, but Litecoin uses a different share format without these fields. When the share packing code tried to serialize the share_data dict, it failed because Litecoin's `share_info_type` doesn't include these fields.

**Solution:** Removed the three Dash-specific fields from `work.py` line ~635-655:
```python
# BEFORE (with Dash fields):
share_data=dict(
    previous_share_hash=self.node.best_share_var.value,
    coinbase=...,
    coinbase_payload=self.current_work.value.get('coinbase_payload', b''),  # REMOVED
    nonce=random.randrange(2**32),
    pubkey_hash=pubkey_hash,
    subsidy=self.current_work.value['subsidy'],
    donation=...,
    stale_info=...,
    desired_version=...,
    payment_amount=self.current_work.value.get('payment_amount', 0),  # REMOVED
    packed_payments=self.current_work.value.get('packed_payments', b''),  # REMOVED
),

# AFTER (Litecoin-compatible):
share_data=dict(
    previous_share_hash=self.node.best_share_var.value,
    coinbase=...,
    nonce=random.randrange(2**32),
    pubkey_hash=pubkey_hash,
    subsidy=self.current_work.value['subsidy'],
    donation=...,
    stale_info=...,
    desired_version=...,
),
```

**Impact:** P2Pool now successfully upgrades share versions at 95% threshold without crashing. Share chain continues growing normally through version transitions.

#### SSL Error Handling & Documentation

**Problem:** Twisted's HTTP client was generating repetitive `ImportError: No module named OpenSSL` errors that cluttered logs. These errors occurred when Twisted tried to handle HTTP 301/302 redirects.

**Root Cause:** The cryptography and pyOpenSSL packages were removed (they weren't needed for P2Pool's core functionality and had glibc compatibility issues with PyPy snap on Ubuntu 24.04). However, Twisted's HTTP client still tried to import OpenSSL for HTTPS redirect support, logging errors each time.

**Solution:** Added comprehensive SSL handling in `main.py`:

1. **Startup SSL Check** (lines ~713-727):
   - Detects if OpenSSL is available
   - Prints clear informational message explaining SSL is optional
   - Documents when/how to install if needed

2. **SSLErrorFilter Class** (lines ~729-756):
   - Custom log observer that filters out repetitive OpenSSL import errors
   - Includes detailed docstring for future maintainers
   - Explains why SSL isn't needed for P2Pool core functionality

3. **Bug Reporter Filter** (lines ~767-772):
   - Prevents SSL errors from being sent to automatic bug reporting service

4. **Comprehensive Documentation:**
   ```python
   # SSL/TLS is optional in P2Pool and only needed for:
   # 1. HTTPS RPC connections (--bitcoind-rpc-ssl flag) - rarely used
   # 2. HTTPS block explorer links - just text URLs, no connections
   # 3. Twisted HTTP client redirect handling - fails gracefully
   # 
   # For Litecoin/Dogecoin merged mining, SSL is not required:
   # - Both daemons use HTTP RPC by default
   # - P2Pool share chain uses custom binary protocol
   # - Merged mining data embedded in coinbase
   ```

**Impact:** Clean, professional logs with clear startup messaging. No more error spam. Future maintainers have clear guidance on SSL usage.

#### Share Persistence Compatibility

**Issue:** Old shares saved with Dash-specific fields were incompatible with new code after removing those fields.

**Solution:** Share loading gracefully handles incompatible formats via exception handling in `data.py` line ~1103. Old shares are skipped (logged as "HARMLESS error"), and new shares are saved in correct Litecoin format.

**User Action:** Backup old shares file if needed:
```bash
mv data/litecoin_testnet/shares.0 shares.0.backup-dash-fields
```

#### Testing Results
- ✅ Share version switchover successful at 95% threshold
- ✅ 230+ verified shares loading correctly from disk after restart
- ✅ Clean logs with informational SSL status message
- ✅ No more repetitive OpenSSL ImportError spam
- ✅ Merged mining operational with proper share persistence

## v1.2.0 - Litecoin+Dogecoin Merged Mining (December 25, 2025)

### Merged Mining Support for Scrypt Coins

**Full merged mining implementation for Litecoin mining Dogecoin**

**Files:** `p2pool/work.py`, `p2pool/bitcoin/helper.py`, `p2pool/data.py`, `p2pool/merged_mining.py`, `p2pool/networks/litecoin_testnet.py`

#### Key Features:
- **Merged Mining Coinbase:** Build proper Dogecoin coinbase with PPLNS distribution from P2Pool share chain
- **Block Submission:** Fixed `submit_block()` to properly return Deferred and use correct node attributes
- **Share Chain Bootstrap:** Graceful fallback during bootstrap phase when share chain is empty
- **Address Auto-Conversion:** Automatically convert Litecoin addresses to Dogecoin format for payouts

#### Critical Bug Fixes:

1. **submit_block() signature mismatch** (`helper.py`)
   - **Problem:** `submit_block()` was called with 6 arguments but only accepts 3
   - **Solution:** Pass `self.node` object instead of individual attributes
   - **Also:** Changed `node.coind` → `node.bitcoind` (attribute name fix)
   - **Also:** Added `return` statement to return Deferred for error handling

2. **Share chain bootstrap KeyError** (`work.py`)
   - **Problem:** PPLNS calculation failed with `KeyError: None` when traversing empty share chain
   - **Solution:** Initialize variables before try block, catch exceptions, fall back to single-address mode
   - **Behavior:** During bootstrap, merged blocks pay to single address; PPLNS activates when chain matures

3. **Merkle root mismatch** (`work.py`, `data.py`)
   - **Problem:** Share validation failed because merkle_root wasn't preserved through coinbase modification
   - **Solution:** Pass `actual_header_merkle_root` in share contents for merged mining shares

4. **Target difficulty parsing** (`work.py`)
   - **Problem:** `template['bits']` unpacking failed for merged mining targets
   - **Solution:** Use `int(target_hex, 16)` to parse target directly from hex string

#### Configuration:
```bash
# Start P2Pool with merged mining:
pypy run_p2pool.py --net litecoin --testnet \
  --address mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h \
  --merged http://dogeuser:dogepass@127.0.0.1:44555 \
  --merged-operator-address nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB \
  --give-author 1 -f 1
```

#### Status:
- ✅ P2Pool shares being created (150+)
- ✅ Merged mining work distributed to miners  
- ✅ Block submission working (returns proper Deferred)
- ✅ PPLNS fallback during bootstrap (no crashes)
- ⏳ Waiting for hash to meet Dogecoin target for first merged block

---

## v1.1.0 - Dash Platform Payment Support (December 13, 2025)

### Protocol v1700: Script-Only Payment Encoding

**Critical fix for Dash mainnet blocks with platform credit pool payments**

**Files:** `p2pool/dash/helper.py`, `p2pool/data.py`, `p2pool/p2p.py`, `p2pool/networks/*.py`

- **Problem:** Dash platform introduces credit pool OP_RETURN payments with empty `payee` field. The `packed_payments` serialization format only transmits `payee` and `amount`, causing the script to be lost when shares are transmitted between nodes. This resulted in "gentx mismatch" errors and inability to mine valid blocks.

- **Solution:** Encode script-only payments with `!<hex>` prefix in the `payee` field:
  - Regular masternode: `"XvTXYLoB6..."` → decoded as Dash address
  - Platform OP_RETURN: `"!6a"` → decoded as raw hex script `\x6a`
  - Uses `!` prefix (1 byte) which is not in base58 alphabet
  - Saves 6 bytes vs original `"script:"` prefix (7 bytes)

- **Protocol Version:** Bumped from 1600 → 1700
  - Nodes reject peers with version < 1700
  - Added `MINIMUM_PROTOCOL_VERSION` to network configs
  - Incompatible with old nodes (they can't decode `!` prefix)

- **Payment Types Supported:**
  - ✅ Regular masternode payments (address-based)
  - ✅ Platform/credit pool payments (script-only OP_RETURN)
  - ✅ Superblock/treasury payments (every 16616 blocks)
  - ✅ DIP3/DIP4 coinbase payloads

**Result:** First successful mainnet block mined with correct platform payments! 🎉

- **Block #2387690** - First accepted P2Pool-Dash mainnet block
  - Hash: `000000000000000d3a4d8da8dc189ceaec6f442e825cd8922fa492c920a799eb`
  - Explorer: https://chainz.cryptoid.info/dash/block.dws?000000000000000d3a4d8da8dc189ceaec6f442e825cd8922fa492c920a799eb
  - Earlier blocks were orphaned due to missing platform payment handling

```python
# Example getblocktemplate masternode payments:
"masternode": [
  {
    "payee": "",                              # Empty for platform
    "script": "6a",                           # OP_RETURN
    "amount": 49787579                        # Platform credit pool
  },
  {
    "payee": "XvTXYLoB6MkyVBkZ2UPntVhfy337QCq9xW",
    "script": "76a914d8ddd6d187c74c22bc770b3d07d7d087feaace2d88ac",
    "amount": 82979299                        # Regular masternode
  }
]
```

### Strict Peer Validation (jtoomim-style)

- Reverted to strict peer banning for all validation failures
- Removed soft pass for gentx mismatch (no longer needed with proper encoding)
- All invalid shares result in peer penalization
- Cleaner `attempt_verify()` returns simple bool instead of tuple

## Summary of Changes

### 1. Fixed SANE_TARGET_RANGE for Correct Difficulty Calculation
**Files:** `p2pool/dash/networks/dash.py`

- **Problem:** The original `SANE_TARGET_RANGE` used incorrect target values that resulted in wrong difficulty calculations for vardiff.
- **Solution:** Changed to use standard bdiff difficulty 1 target (`0xFFFF * 2**208`) as the maximum target (minimum difficulty).
- **Max Difficulty:** Reduced from 100,000 to 10,000 to ensure 2 TH/s ASICs can submit pseudoshares frequently enough (every ~20 seconds at max difficulty vs ~200 seconds before).

```python
# Before:
SANE_TARGET_RANGE = (2**256//2**32//1000000 - 1, 2**256//2**32 - 1)

# After:
_DIFF1_TARGET = 0xFFFF * 2**208  # Standard bdiff difficulty 1 target
SANE_TARGET_RANGE = (_DIFF1_TARGET // 10000, _DIFF1_TARGET)  # Max diff 10000
```

### 2. Fixed MAX_TARGET for P2Pool Share Difficulty
**Files:** `p2pool/networks/dash.py`

- **Problem:** `MAX_TARGET = 2**256//2**20 - 1` gave an extremely easy difficulty (~0.000244) that caused share spam.
- **Solution:** Changed to standard bdiff difficulty 1 target for reasonable minimum share difficulty.

```python
# Before:
MAX_TARGET = 2**256//2**20 - 1  # ~0.000244 difficulty

# After:
MAX_TARGET = 0xFFFF * 2**208  # Standard bdiff difficulty 1
```

### 3. Improved Stratum Vardiff Algorithm
**Files:** `p2pool/dash/stratum.py`

Major improvements to handle high-hashrate ASIC miners:

- **Initial Difficulty 100:** New workers start at difficulty 100 instead of 1, preventing share flood from high-hashrate ASICs while still allowing slower miners to submit shares quickly.
- **Job-Specific Target Tracking:** Each job stores its own target when created. When shares are submitted, they're validated against the job's original target, not the current target. This prevents race conditions during vardiff adjustments.
- **Bidirectional Vardiff:** Difficulty adjusts both UP (for fast miners) and DOWN (for slow miners) to maintain ~10 second share intervals.
- **Faster Adjustment:** Triggers vardiff recalculation after 3 shares instead of 12.
- **Larger Adjustment Range:** Allows 0.25x to 4x adjustment per iteration (was 0.5x to 2x).
- **Rate Limiting:** Drops submissions if more than 100/sec to prevent server overload.
- **Short Job IDs:** Changed from 128-bit to 32-bit (8 hex chars) for ASIC compatibility.
- **Better Error Handling:** Don't disconnect on temporary dashd errors.

### 4. Fixed "hash > target" Race Condition
**Files:** `p2pool/dash/stratum.py`, `p2pool/work.py`

- **Problem:** When vardiff adjusted difficulty, shares submitted for old jobs would be validated against the new (harder) target, causing "hash > target" rejections even though the share was valid for its original job.
- **Solution:** Store `job_target` with each job in `handler_map`. When a share is submitted, retrieve and use that job's original target for validation.
- **Result:** Miners no longer see share rejections during vardiff transitions.

```python
# Job creation: capture target at dispatch time
job_target = self.target
self.handler_map[jobid] = x, got_response, job_target

# Share submission: use the job's original target
x, got_response, job_target = self.handler_map[job_id]
result = got_response(header, worker_name, coinb_nonce, job_target)
```

### 5. Fixed Weakref Callback Errors
**Files:** `p2pool/util/forest.py`, `p2pool/util/variable.py`

- **Problem:** Weakref callbacks could crash with "TypeError: 'NoneType' object is not callable" during garbage collection.
- **Solution:** Added safe wrappers that check for None before calling the referenced object.

### 6. Improved Work Generation
**Files:** `p2pool/work.py`

- **Fixed Share Difficulty Floor:** Properly enforce minimum difficulty from `SANE_TARGET_RANGE` during bootstrap and normal operation.
- **Submitted Target Support:** `got_response()` now accepts an optional `submitted_target` parameter for vardiff compatibility.
- The P2Pool share floor now respects both `share_info['bits'].target` and network's `SANE_TARGET_RANGE[1]`.

### 7. Better Dashd Error Handling
**Files:** `p2pool/dash/helper.py`

- Added specific handling for `TimeoutError` and `ConnectionRefusedError` from dashd RPC calls.
- Retry silently on temporary errors instead of crashing.

### 8. Web Interface Improvements
**Files:** `p2pool/web.py`, `p2pool/data.py`

- Fixed `best_share_hash` endpoint to handle `None` value during bootstrap (returns 64 zeros instead of crashing).
- **Added `parse_bip0034()` function** (from jtoomim's fork) to extract block height from coinbase transaction (BIP 34 standard).
- **Enhanced `recent_blocks` endpoint** to include:
  - Block number (height) extracted from coinbase
  - Direct block explorer URL for each found block
  - Graceful error handling when no blocks found yet
- **Added `currency_info` endpoint** providing SYMBOL, BLOCK_EXPLORER_URL_PREFIX, ADDRESS_EXPLORER_URL_PREFIX, and TX_EXPLORER_URL_PREFIX for web interface.

The web interface now properly displays found blocks with their height and provides clickable links to the Dash blockchain explorer (chainz.cryptoid.info).

## Testing Results

With 6× Antminer D9 miners (~1.7 TH/s each):
- **Total Hashrate:** ~9-10 TH/s (correctly measured)
- **Share Rejections:** 0% "hash > target" errors after fix
- **Dead on Arrival:** ~0%
- **Vardiff Range:** 3000-10000 depending on individual miner speed
- **Miners Stay Connected:** No disconnections due to vardiff changes

## Testing Configuration

For testing without peers, `CHAIN_LENGTH` and `REAL_CHAIN_LENGTH` are temporarily reduced to 10 in `p2pool/networks/dash.py`. **Revert to 4320 for production use.**

## Deployment Notes

After deploying these changes:
1. Restart P2Pool to apply new configuration
2. Workers will reconnect and start at difficulty 100
3. Vardiff will ramp up to appropriate difficulty within seconds
4. Local hashrate display should show correct values (~1.7 TH/s per D9 ASIC)
5. Vardiff should stabilize around 3000-10000 for D9 miners with 10s target rate

---

## v1.1.0 Improvements (December 11, 2025)

Based on comparison with jtoomim's p2pool fork, the following additional improvements were added:

### 9. Performance Benchmarking (`--bench` flag)
**Files:** `p2pool/__init__.py`, `p2pool/main.py`, `p2pool/work.py`, `p2pool/dash/stratum.py`

- Added `BENCH` global flag (similar to jtoomim's implementation)
- New `--bench` command-line argument to enable performance timing
- `get_work()` and `rpc_submit()` now print timing info when BENCH enabled
- Useful for identifying performance bottlenecks

```bash
# Enable benchmarking
./run_p2pool.py --bench ...
```

### 10. Improved Stratum Error Handling
**Files:** `p2pool/dash/stratum.py`

- Changed stale job handling from raising exceptions to returning `False`
- Better compatibility with various miner implementations
- Added timing benchmarks for submit processing
- Improved error logging with worker name context

### 11. Hash Rate Estimation Integration
**Files:** `p2pool/work.py`

- Hash rate estimation already present via `_estimate_local_hash_rate()` and `get_local_addr_rates()`
- Used for:
  - Automatic share difficulty adjustment
  - Dust threshold protection (prevents unpayable shares from low-hashrate miners)
  - Local rate monitoring per address

### 12. Dust Threshold Protection
**Files:** `p2pool/work.py`, `p2pool/dash/networks/dash.py`

Already implemented:
- `DUST_THRESHOLD = 0.001e8` (0.001 DASH) in network config
- Workers with expected payout < DUST_THRESHOLD get increased share difficulty
- Prevents wasted work from miners who can't achieve payable share amounts

### Features from jtoomim's fork already present in p2pool-dash:
- ✅ Variable difficulty (vardiff) in stratum
- ✅ Hash rate estimation
- ✅ Dust threshold protection  
- ✅ Version rolling / ASICBoost (BIP320)
- ✅ Share rate parameter (`--share-rate`)
- ✅ `parse_bip0034()` for block height extraction
- ✅ Enhanced web interface with block explorer links
- ✅ `currency_info` endpoint

### Command Line Arguments

```bash
# New in v1.1.0:
--bench              # Enable benchmarking mode (print performance timing)

# Existing:
--debug              # Enable debug mode
--share-rate SECS    # Target seconds per pseudoshare (default: 10)
```

---

## v1.2.0 - Enhanced Stratum Protocol (December 11, 2025)

Major Stratum protocol enhancements with careful attention to pool performance protection.

### 13. `mining.suggest_difficulty` Support (NEW)
**Files:** `p2pool/dash/stratum.py`

Miners can now suggest their preferred starting difficulty using the standard `mining.suggest_difficulty` method.

**PERFORMANCE SAFEGUARDS:**
- Pool-wide minimum difficulty floor (0.001 by default)
- Dynamic adjustment based on pool load - when submission rate is high, minimum difficulty is automatically raised
- Vardiff still operates after initial difficulty is set
- Suggested difficulty is validated against pool safety limits

```python
# Miner request:
{"method": "mining.suggest_difficulty", "params": [1024]}

# Pool accepts or adjusts to safe minimum
```

### 14. `minimum-difficulty` BIP310 Extension (NEW)
**Files:** `p2pool/dash/stratum.py`

Full support for BIP310 minimum-difficulty extension, allowing miners to set a difficulty floor for their connection.

**PERFORMANCE SAFEGUARDS:**
- Pool-wide minimum difficulty enforcement
- Dynamic minimum based on current pool load
- Vardiff cannot go below the negotiated minimum

```python
# Miner negotiates via mining.configure:
{"method": "mining.configure", "params": [["minimum-difficulty"], {"minimum-difficulty.value": 100}]}

# Pool response includes actual minimum (may be higher than requested if pool is under load)
```

### 15. Global Pool Statistics Tracking (NEW)
**Files:** `p2pool/dash/stratum.py`

New `PoolStatistics` singleton class providing:
- Total connected workers count
- Per-worker hash rates and share counts
- Global share submission rate monitoring
- Connection history for session resumption
- Pool performance metrics

**Available via web API:**
```bash
curl http://localhost:7903/stratum_stats
```

Returns:
```json
{
  "pool": {
    "connections": 6,
    "workers": 3,
    "total_accepted": 15234,
    "total_rejected": 12,
    "submission_rate": 45.2,
    "uptime": 86400
  },
  "workers": {
    "miner1": {"shares": 5000, "accepted": 4998, "rejected": 2, "hash_rate": 1700000000000},
    ...
  }
}
```

### 16. Per-Worker Statistics (NEW)
**Files:** `p2pool/dash/stratum.py`

Track per-worker metrics:
- Share count (submitted/accepted/rejected)
- Estimated hash rate
- First/last seen timestamps
- Current difficulty
- Connection duration

### 17. Dynamic Share Rate Configuration (NEW)
**Files:** `p2pool/dash/stratum.py`

Workers can specify custom share rate via username suffix:
```
address+s5    # 5 seconds per share
address+100+s3  # difficulty 100, 3 seconds per share
```

Clamped to reasonable range (1-60 seconds).

### 18. Session Resumption (NEW)
**Files:** `p2pool/dash/stratum.py`

When miners reconnect with their session ID, the pool can restore:
- Previous difficulty setting
- Suggested difficulty
- Minimum difficulty floor
- Custom share rate

Reduces initial difficulty negotiation time after reconnects.

### 19. `client.reconnect` Support (NEW)
**Files:** `p2pool/dash/stratum.py`

Pool can request miners to reconnect (for load balancing):
```python
# Pool to miner:
{"method": "client.reconnect", "params": ["hostname", 3333, 0]}
```

Session state is preserved for seamless resumption.

### 20. Structured Connection Logging (NEW)
**Files:** `p2pool/dash/stratum.py`

Enhanced logging with:
- Connection/disconnection events with session IDs
- Per-session statistics (duration, shares)
- Worker identification
- Difficulty change tracking

### Performance Protection Summary

The new difficulty-related features include multiple safeguards to prevent pool overload and protect miners:

| Safeguard | Description |
|-----------|-------------|
| MIN_DIFFICULTY_FLOOR | Absolute minimum difficulty (0.001) - prevents share flooding |
| MAX_DIFFICULTY_CEILING | Maximum difficulty (1,000,000) - prevents miner timeout from impossibly high diff |
| MAX_SUBMISSIONS_PER_SECOND | Global rate limit (1000/sec default) |
| Dynamic minimum adjustment | When submission rate > 50% of max, minimum difficulty increases |
| Per-connection rate limiting | Drop shares if > 100/sec from single connection |
| Vardiff continues operating | Even with suggest_difficulty, vardiff adjusts based on actual performance |

### 21. Stratum Statistics Web Page (NEW)
**Files:** `web-static/stratum.html`, `web-static/index.html`

New dedicated web page for stratum statistics accessible from main index:

**Features:**
- Pool overview (connections, workers, accept/reject rates)
- Per-worker statistics table with hash rates
- Protocol extensions status display
- Pool safeguards documentation
- Auto-refresh every 10 seconds

**Access:** `http://localhost:7903/static/stratum.html`

### Web UI Pages

| Page | URL | Description |
|------|-----|-------------|
| Main | `/static/index.html` | Pool overview, payouts, blocks |
| Graphs | `/static/graphs.html` | Hash rate graphs |
| **Stratum Stats** | `/static/stratum.html` | **NEW** - Worker stats, protocol extensions |
| Share Explorer | `/static/share.html` | Individual share details |

### Web API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/stratum_stats` | Pool and worker statistics |
| `/global_stats` | General pool stats (existing) |
| `/local_stats` | Local node stats (existing) |

### Stratum Protocol Extensions Supported

| Extension | BIP | Status |
|-----------|-----|--------|
| `version-rolling` | BIP320 | ✅ Full support |
| `minimum-difficulty` | BIP310 | ✅ NEW |
| `subscribe-extranonce` | NiceHash | ✅ Full support |
| `mining.suggest_difficulty` | Standard | ✅ NEW |

---

## v1.2.1 - Block Submission Logging & ChainLock Monitoring (December 11, 2025)

Enhanced block submission tracking to help diagnose orphaned blocks.

### 22. Comprehensive Block Submission Logging (NEW)
**Files:** `p2pool/work.py`, `p2pool/dash/helper.py`

When a Dash block is found, detailed logging now includes:

**Block Discovery (work.py):**
```
######################################################################
### DASH BLOCK FOUND! ###
######################################################################
Time:        2025-12-11 05:11:17
Miner:       XminerAddress...
Block hash:  0000000000000012efc296b9f6cc978c22391d63f93d8cb5732e202206577cd5
POW hash:    000000000000000...
Target:      000000000021...
Height:      2386600
Txs:         8
Explorer:    https://chainz.cryptoid.info/dash/block.dws?...
######################################################################
```

**Block Submission (helper.py):**
```
======================================================================
BLOCK SUBMISSION STARTED at 2025-12-11 05:11:17
  Block hash:   0000000000000012...
  POW hash:     000000000000000...
  Target:       000000000021...
  Transactions: 8
======================================================================
BLOCK SUBMISSION RESULT:
  Success: True (result: None)
  Expected success: True
```

### 23. ChainLock Status Monitoring (NEW)
**Files:** `p2pool/dash/helper.py`

New `check_block_chainlock()` function monitors the chainlock status of submitted blocks:

- Checks at 2s, 5s, 10s, 30s, and 60s after submission
- Reports confirmations count and chainlock status
- Warns if block may be orphaned (confirmations < 0)
- Shows competing block if our block was orphaned

**Sample output:**
```
CHAINLOCK STATUS CHECK (10s after submission):
  Block hash:    0000000000000012...
  Height:        2386600
  Confirmations: 1
  ChainLock:     YES - LOCKED!

*** BLOCK CHAINLOCKED SUCCESSFULLY! ***
  Explorer: https://chainz.cryptoid.info/dash/block.dws?...
```

**Orphan detection:**
```
CHAINLOCK STATUS CHECK (30s after submission):
  Block hash:    0000000000000012...
  Height:        2386600
  Confirmations: -1
  ChainLock:     NO - not yet locked

*** WARNING: BLOCK MAY BE ORPHANED (confirmations=-1) ***
  Another block may have been chainlocked at this height.
  Current block at height 2386600: 000000000000000f2c6b...
  Current block chainlock: True
```

### Why Blocks Get Orphaned

Based on analysis of the orphaned block at height 2386600:

| Our Block | Winning Block |
|-----------|---------------|
| Found at 05:11:17 | Found at 05:14:46 |
| ChainLock: **false** | ChainLock: **true** |
| 8 transactions | 30 transactions |
| Confirmations: -1 | Confirmations: 267 |

**Root Cause:** Our block was found 3.5 minutes EARLIER but the competing block received ChainLock first. Dash's ChainLock consensus overrides first-seen ordering.

**Contributing Factor:** P2Pool had 0 peers, meaning our block propagated only via dashd (slower) rather than P2Pool's direct peer network.

### P2Pool Bootstrap Node Status

Current bootstrap nodes in `p2pool/networks/dash.py`:
- `dash01.p2poolmining.us` - **OFFLINE** (DNS resolves, no service)
- `dash02.p2poolmining.us` - **OFFLINE**
- `dash03.p2poolmining.us` - **OFFLINE**
- `dash04.p2poolmining.us` - **OFFLINE**
- `crypto.office-on-the.net` - **OFFLINE** (connection refused)

**Note:** All known Dash P2Pool bootstrap nodes are currently offline. The pool operates in solo mode, which increases orphan risk due to slower block propagation via dashd-only network.

### Recommendations to Reduce Orphan Risk

1. **Maximize dashd Peer Connections:**
   ```bash
   dash-cli getconnectioncount  # Should be high (100+)
   ```

2. **Ensure Low Latency to dashd:**
   - Run dashd on same machine or LAN as P2Pool
   - Use fast SSD for dashd blockchain storage

3. **Include More Transactions:**
   - Blocks with more transactions may receive ChainLock priority
   - Don't filter out valid transactions from block template

4. **Find Other P2Pool Nodes:**
   - If other Dash P2Pool nodes exist, add them as peers
   - Use `--p2pool-node` argument to specify known nodes

---

## v1.2.2 - Vardiff Improvements & Multi-Connection Support (December 12, 2025)

Improved vardiff algorithm and better support for ASICs with multiple connections.

### 24. Fixed SANE_TARGET_RANGE Clipping for Low-Difficulty Miners (FIX)
**Files:** `p2pool/dash/stratum.py`

- **Problem:** `SANE_TARGET_RANGE[1]` (diff 1.0) was clamping vardiff adjustments, preventing miners from getting difficulty below 1.0. CPU miners (like cpuminer at ~1 MH/s) would have vardiff jump from 0.01 to 1.0 on first share, then repeatedly timeout.
- **Solution:** For stratum vardiff, use `MIN_DIFFICULTY_FLOOR` (0.001) as the lower bound instead of `SANE_TARGET_RANGE[1]`.
- **Result:** CPU miners can now maintain appropriate low difficulties (0.001-0.1) without oscillation.

### 25. Timeout-Based Vardiff Reduction (NEW)
**Files:** `p2pool/dash/stratum.py`

Added safety mechanism to reduce difficulty when no shares are received for too long:

- If no shares received for 3× the target share time, reduce difficulty by 50%
- Respects minimum_difficulty floor (BIP310) and pool-wide minimum
- Prevents miners from being stuck at impossibly high difficulty after aggressive vardiff jumps
- Helps slow miners (CPU, older GPUs) stabilize at appropriate difficulty

### 26. Improved Vardiff Logging Precision (IMPROVEMENT)
**Files:** `p2pool/dash/stratum.py`

Changed vardiff log formatting from `%.2f` to `%.4f` to show precise difficulty values for low-difficulty miners:
```
# Before: Vardiff worker: 0.00 -> 0.00 (misleading)
# After:  Vardiff worker: 0.0100 -> 0.0200 (precise)
```

### 27. Multi-Connection Worker Support (NEW)
**Files:** `p2pool/dash/stratum.py`, `p2pool/web.py`

ASICs often create multiple stratum connections per worker (for redundancy, per-hashboard isolation, or failover). Added three features to handle this properly:

**Option A - Aggregate Worker Stats:**
- `get_worker_connections()` - Get all connections for a worker name
- `get_worker_aggregate_stats()` - Aggregate stats across all connections
- API returns connection breakdown: total, active (submitted shares), backup (idle)

**Option B - Suppress Idle Connection Logs:**
- Vardiff timeout logs only appear for connections that have actually submitted shares
- Reduces log noise from idle backup/redundant connections
- Difficulty still adjusts silently for idle connections

**Option C - Session Linkage:**
- `update_worker_last_share_time()` - When any connection submits a share, updates `last_share_time` for ALL connections of that worker
- Prevents false timeout vardiff on backup connections when primary is active
- Works correctly for multi-hashboard ASICs where all boards submit shares

**API Enhancement:**
```json
{
  "workers": {
    "XworkerAddress.D1": {
      "shares": 1500,
      "hash_rate": 1700000000000,
      "connections": 2,
      "active_connections": 1,
      "backup_connections": 1,
      "connection_difficulties": [10000.0, 100.0]
    }
  }
}
```

### Multi-Connection Scenarios Supported

| Scenario | Behavior |
|----------|----------|
| All hashboards active | Each connection adjusts vardiff independently; session linkage prevents false timeouts |
| Some hashboards idle | Active boards' shares keep all timers fresh via session linkage |
| Pure backup connections | Silent vardiff adjustments, no log spam |
| Failover activation | Backup connection immediately usable at reduced difficulty |

---

## v1.2.3 - Suggest Difficulty Timing Fix (December 12, 2025)

Fixed timing issue with `mining.suggest_difficulty` for CPU miners and low-hashrate devices.

### 28. Re-send Work After Suggest Difficulty (FIX)
**Files:** `p2pool/dash/stratum.py`

- **Problem:** CPU miners send `mining.suggest_difficulty` AFTER `mining.authorize`, but `_send_work()` is called during `mining.authorize`. This means the first work is sent with default difficulty (100) instead of the suggested difficulty (e.g., 0.005). The miner then has to wait for vardiff to gradually reduce the difficulty, wasting time and causing "share above target" rejections.

- **Protocol Flow (Before Fix):**
  1. `mining.subscribe` → work sent at diff 100
  2. `mining.configure` → minimum-difficulty set  
  3. `mining.authorize` → work sent at diff 100 again
  4. `mining.suggest_difficulty(0.005)` → difficulty updated but no new work sent
  5. Miner submits share at diff 0.005 → **REJECTED** (work was at diff 100)
  6. Vardiff slowly reduces difficulty... eventually works

- **Protocol Flow (After Fix):**
  1. `mining.subscribe` → work sent at diff 100
  2. `mining.configure` → minimum-difficulty set
  3. `mining.authorize` → work sent at diff 100
  4. `mining.suggest_difficulty(0.005)` → difficulty updated AND new work sent at diff 0.005 ✓
  5. Miner submits share at diff 0.005 → **ACCEPTED** ✓

- **Solution:** Call `_send_work()` immediately after processing `rpc_suggest_difficulty()` to send new work at the suggested difficulty. Uses a 0.1s delay to avoid race conditions with the difficulty update notification.

```python
# After updating difficulty in suggest_difficulty:
self.other.svc_mining.rpc_set_difficulty(safe_diff).addErrback(lambda err: None)

# NEW: Re-send work with correct difficulty
reactor.callLater(0.1, self._send_work)
```

- **Result:** CPU miners and other low-hashrate devices using `suggest_difficulty` now immediately receive work at their requested difficulty, eliminating warmup time and share rejections.

### Impact on CPU Miners

| Metric | Before | After |
|--------|--------|-------|
| Initial difficulty | 100 (default) | 0.005 (suggested) |
| Time to first valid share | ~30s+ (vardiff warmup) | Immediate |
| Initial share rejections | Multiple | None |
| Vardiff oscillation | Severe | None |

### Important Note: CPU Miners and P2Pool Shares

While CPU miners can now submit **pseudoshares** at appropriate low difficulty (verified working at ~1 MH/s with difficulty 0.004), they will almost never find actual **P2Pool shares** due to the share chain difficulty.

**Why CPU Miners Can't Find P2Pool Shares:**

| Parameter | Value |
|-----------|-------|
| P2Pool share difficulty | ~63,000 |
| CPU miner hashrate | ~1 MH/s |
| Expected time per P2Pool share | **~9 years** |

The P2Pool share difficulty is set by the network based on total pool hashrate (~14 TH/s) to achieve one share every 20 seconds for the entire pool. A 1 MH/s CPU miner has essentially zero probability of finding a P2Pool share.

**Pseudoshares vs P2Pool Shares:**
- **Pseudoshares** (diff 0.004): Used for local pool statistics and vardiff calibration only
- **P2Pool Shares** (diff ~63,000): Required for coinbase inclusion and payout

**Implication:** CPU miners mining to P2Pool will see their pseudoshares accepted but will never receive payouts because they cannot find P2Pool shares to be included in the share chain.

**Recommendation:** Low-hashrate miners (< 100 GH/s) should use a traditional centralized pool that tracks shares internally, not P2Pool.

---

## Understanding P2Pool Share Timing

### Share Period and Expected Time

P2Pool is configured with `SHARE_PERIOD = 20 seconds`, meaning the **entire pool** should find one P2Pool share every 20 seconds on average.

Individual miner's expected time to find a share depends on their proportion of total pool hashrate:

```
Your expected share time = SHARE_PERIOD / (your_hashrate / total_pool_hashrate)
```

**Example with current pool:**
| Metric | Value |
|--------|-------|
| Pool total hashrate | 14.3 TH/s |
| Your local hashrate | 3.6 TH/s |
| Your share of pool | 25% |
| Pool share period | 20 seconds |
| **Your expected share time** | 20s / 0.25 = **80 seconds (1.3 min)** |

The remaining ~75% of shares are found by other miners connected to peer P2Pool nodes.

### Multi-Node P2Pool Network

When connected to other P2Pool nodes (peers), the share difficulty adjusts based on **total network hashrate**, not just your local miners:

- More peers with miners → Higher share difficulty → Longer time between your shares
- Shares are distributed proportionally to hashrate contribution
- Block rewards are split based on shares in the chain


