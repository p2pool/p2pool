# P2Pool Share Archive System

## Overview

P2Pool automatically archives old shares that are no longer needed for active operations. This keeps the working share storage clean while preserving historical data for recovery or analysis.

## How It Works

### Active Shares (In Memory & Pickle)
- **Target**: Last `2 × CHAIN_LENGTH = 8640` shares (~48 hours on mainnet)
- **Purpose**: Used for all pool calculations and operations
- **Storage**: `data/shares` pickle files

### Archived Shares
- **Target**: Shares older than 8640 depth
- **Purpose**: Historical backup and recovery
- **Storage**: `data/share_archive/shares_<timestamp>.txt`
- **Frequency**: 
  - **Startup**: Immediately archives old shares (optimization)
  - **Periodic**: Every 60 seconds if old shares exist
  - **Shutdown**: Gracefully archives on clean exit

### Startup Optimization
On startup, p2pool immediately checks for and archives old shares before they're fully loaded into memory. This:
- ✅ **Reduces memory usage** - doesn't keep orphaned shares
- ✅ **Faster startup** - fewer shares to process
- ✅ **Cleaner state** - removes accumulation from previous runs

### Graceful Shutdown
When p2pool exits cleanly (CTRL+C, systemd stop), it:
- ✅ **Archives pending old shares** - no data loss
- ✅ **Saves current state** - clean restart
- ✅ **Prevents corruption** - atomic operations

### Crash Safety
If p2pool crashes or is killed (kill -9):
- ⚠️ **Shares remain in pickle** - not archived yet
- ✅ **No corruption** - pickle files are intact
- ✅ **Recovered on restart** - startup optimization archives them
- ✅ **No data loss** - worst case: slightly larger pickle until restart

## Why Archival is Safe

P2Pool uses shares for specific lookback periods:

| Operation | Lookback | Safe? |
|-----------|----------|-------|
| **Difficulty Adjustment** | 100 shares (TARGET_LOOKBEHIND) | ✅ Safe - only uses last 100 |
| **Payout Calculation** | 4320 shares (REAL_CHAIN_LENGTH) | ✅ Safe - 24 hour window |
| **Statistics (Local/Global)** | 720-3600 shares | ✅ Safe - max 1 hour |
| **Chain Scoring** | 4320 shares (CHAIN_LENGTH) | ✅ Safe - 24 hour window |
| **Share Generation** | 100 shares (transaction refs) | ✅ Safe - only recent history |

**We keep 8640 shares - almost 2× the maximum needed!**

Shares older than 8640 are **never used** for any calculation or validation.

## Archive File Format

Archive files are plain text with human-readable format:

```
# P2Pool Share Archive - Created: 2024-12-17 15:30:00 UTC
# Reason: startup cleanup
# Chain height: 12500, Shares in active chain: 8640
# Format: share_hash timestamp verified

00000000000abcdef1234567890... 1702826400 verified
00000000000fedcba9876543210... 1702826380 unverified
```

### Fields:
- **share_hash**: 64-character hex hash
- **timestamp**: Unix timestamp when share was created
- **verified**: `verified` or `unverified` status

## Recovery Procedure

If you need to restore archived shares (e.g., after corruption):

1. **Stop p2pool**
   ```bash
   # Stop the running instance
   pkill -f run_p2pool.py
   ```

2. **Backup current data**
   ```bash
   cd ~/p2pool-dash/data
   cp -r shares shares_backup
   cp -r share_archive share_archive_backup
   ```

3. **Parse and restore archives** (manual process)
   
   Archive files are text-based for easy parsing. You can:
   - Read share hashes and timestamps
   - Filter by date range
   - Manually reconstruct share chains if needed
   
   Note: Share data itself is not preserved (only metadata). Archives are primarily for:
   - Verifying historical chain structure
   - Debugging share chain issues
   - Understanding pool history

4. **Restart p2pool**
   ```bash
   ./run_p2pool.py
   ```

## Storage Management

### Archive Location
```
data/
├── shares          # Active shares (pickle format)
├── share_archive/  # Historical archives (text files)
│   ├── shares_1702826400.txt
│   ├── shares_1702826460.txt
│   └── shares_1702826520.txt
```

### Cleanup Old Archives

Archives accumulate over time. To clean up:

```bash
# Keep only last 7 days of archives
find data/share_archive -name "shares_*.txt" -mtime +7 -delete

# Keep only last 30 days
find data/share_archive -name "shares_*.txt" -mtime +30 -delete

# Or compress old archives
find data/share_archive -name "shares_*.txt" -mtime +7 -exec gzip {} \;
```

### Archive Size Estimates

Typical archive file sizes:
- **Per share entry**: ~100 bytes (hash + timestamp + status)
- **Per archive file**: 10-100 KB (100-1000 shares)
- **Daily accumulation**: ~5-20 MB (depending on share rate)
- **Monthly accumulation**: ~150-600 MB

## Monitoring

Check if archival is working:

```bash
# List recent archives
ls -lh data/share_archive/

# Count archived shares
wc -l data/share_archive/shares_*.txt

# Check latest archive
tail data/share_archive/shares_*.txt | tail -1
```

Watch p2pool logs for archival messages:
```
# On startup
Checking for old shares to archive on startup...
Archived 1523 old shares to shares_1702826400.txt (startup cleanup)
Startup optimization: removed 1523 old shares from active storage

# During operation
Archived 342 old shares to shares_1702826460.txt (periodic)

# On shutdown
Graceful shutdown: archiving shares...
Archived 89 old shares to shares_1702826520.txt (periodic)
Shutdown archival complete
```

## Configuration

### Automatic Scaling with Custom CHAIN_LENGTH

The archival system **automatically adapts** to any `CHAIN_LENGTH` setting. If you create a private pool with custom chain length:

#### Example: 5-Day Chain
```python
# In your custom network config (e.g., dash_custom.py)
CHAIN_LENGTH = 5*24*60*60//20  # 21,600 shares = 5 days
REAL_CHAIN_LENGTH = 5*24*60*60//20
```

**Automatic adjustments:**
- ✅ Archives at `2 × CHAIN_LENGTH = 43,200` shares (10 days)
- ✅ Keeps 2× safety margin automatically
- ✅ All statistics scale correctly
- ✅ Memory and disk usage scale proportionally

#### Scaling Table:

| CHAIN_LENGTH | Time Period | Archive Threshold | Memory Impact | Disk Impact |
|--------------|-------------|-------------------|---------------|-------------|
| 4,320 (default) | 24 hours | 8,640 shares (48h) | Baseline | Baseline |
| 8,640 | 48 hours | 17,280 shares (96h) | ~2× | ~2× |
| 21,600 | 5 days | 43,200 shares (10d) | ~5× | ~5× |
| 43,200 | 10 days | 86,400 shares (20d) | ~10× | ~10× |

#### Important Considerations:

**Memory:**
- Longer chains keep more shares in memory
- Plan server RAM accordingly
- Monitor with `free -h` and `top`

**Disk:**
- Pickle files grow proportionally
- Archives accumulate faster
- More frequent cleanup needed

**Payouts:**
- Payout window = REAL_CHAIN_LENGTH
- Longer window = more stable payouts
- But slower response to hashrate changes

**Network Isolation:**
- Custom networks need unique IDENTIFIER
- Won't connect to mainnet automatically
- See `p2pool/networks/dash_custom_example.py`

### Future Configuration Options

Future versions may add:
- Configurable archive retention periods
- Automatic compression
- Configurable archive multiplier (default 2×)
- Archive format options (JSON, CSV, etc.)

## Technical Details

### Why Not Just Delete?

Archiving provides:
1. **Recovery path** if share chain corruption occurs
2. **Historical analysis** of pool performance
3. **Audit trail** for debugging
4. **Peace of mind** - shares aren't lost forever

### Performance Impact

- **Negligible CPU**: Archival runs every 60s, takes <100ms
- **Minimal I/O**: Only writes when old shares exist
- **No memory impact**: Archives are not loaded into memory

### Share Storage Details

P2Pool stores shares in two places:
1. **In-memory tracker**: Fast access for calculations (forest.Tracker)
2. **Persistent storage**: Pickle files for restart recovery (ShareStore)

Archives preserve metadata from shares being removed from persistent storage.

## Troubleshooting

### Archives not being created?

Check:
1. Pool has been running long enough (>48 hours on mainnet)
2. Share chain height > 8640
3. Directory permissions on `data/share_archive/`
4. Disk space available

### Share chain corruption?

If share chain becomes corrupted:
1. Check archive timestamps to identify problem period
2. Compare archived hashes with blockchain data
3. Restart with fresh `data/shares` (will resync from network)

### Too many archive files?

Normal behavior. Clean up old archives as needed (see cleanup commands above).

## Questions?

- Check p2pool logs for archival messages
- Archives are safe to delete if disk space is an issue
- Only active shares (last 8640) are needed for operation
- Contact pool operator if unsure about recovery procedures
