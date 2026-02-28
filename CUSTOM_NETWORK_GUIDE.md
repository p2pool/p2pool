# Custom Network Configuration Guide

This guide explains how to create a private P2Pool-Dash network with custom parameters.

## Quick Start

1. **Copy example config:**
   ```bash
   cp p2pool/networks/dash_custom_example.py p2pool/networks/dash_mypool.py
   ```

2. **Edit key parameters:**
   ```python
   # Make network unique
   IDENTIFIER = 'MYPOOL01'.encode('hex').decode('hex')
   PREFIX = 'MYPR0001'.encode('hex').decode('hex')
   
   # Adjust chain length for your needs
   CHAIN_LENGTH = 5*24*60*60//20  # 5 days
   REAL_CHAIN_LENGTH = CHAIN_LENGTH
   
   # Change ports to avoid conflicts
   P2P_PORT = 8998
   WORKER_PORT = 7902
   ```

3. **Run your custom network:**
   ```bash
   python run_p2pool.py --net dash_mypool <your-address>
   ```

## Chain Length Selection

Choose based on your pool's goals:

### Small Pool (< 100 GH/s)
```python
CHAIN_LENGTH = 24*60*60//20  # 24 hours (default)
```
- **Pros:** Lower memory, responsive payouts
- **Cons:** More payout variance for miners

### Medium Pool (100 GH/s - 1 TH/s)
```python
CHAIN_LENGTH = 2*24*60*60//20  # 48 hours
```
- **Pros:** Balanced stability and responsiveness
- **Cons:** 2× memory usage

### Large Pool (> 1 TH/s)
```python
CHAIN_LENGTH = 5*24*60*60//20  # 5 days
```
- **Pros:** Very stable payouts, smooth variance
- **Cons:** 5× memory usage, slower adaptation

### Testing Network
```python
CHAIN_LENGTH = 100  # Short chain for testing
```
- **Pros:** Fast iteration, low resources
- **Cons:** Not suitable for production

## Archival Behavior

**Automatically scales with CHAIN_LENGTH:**

```python
# Your config:
CHAIN_LENGTH = X

# Archival behavior:
Active shares kept: 2 × X
Archive threshold: > 2 × X
```

**No configuration needed** - it just works!

## Memory Planning

Estimate memory needs:

```
Base RAM = 512 MB (p2pool overhead)
Share RAM = CHAIN_LENGTH × 200 bytes per share (approximate)

Examples:
- 4,320 shares (24h):  512 MB + 0.8 MB = ~600 MB
- 21,600 shares (5d):  512 MB + 4.3 MB = ~1 GB
- 43,200 shares (10d): 512 MB + 8.6 MB = ~1.5 GB
```

**Note:** Actual usage varies with:
- Number of transactions per share
- Share difficulty distribution
- Orphan/DOA rate

## Disk Planning

Archive accumulation rate:

```
Archives per day = (shares per day - 2×CHAIN_LENGTH) / archive_frequency
Archive size = ~100 bytes per share

Examples (after chain is full):
- 24h chain: ~0 archives/day (chain not full daily)
- 5d chain:  ~1 archive/hour after 10 days
- 10d chain: ~1 archive/hour after 20 days
```

**Cleanup strategy:**
```bash
# Keep last 30 days of archives
find data/share_archive -name "shares_*.txt" -mtime +30 -delete

# Or compress old archives
find data/share_archive -name "shares_*.txt" -mtime +7 -exec gzip {} \;
```

## Network Isolation

**Critical:** Custom networks are isolated from mainnet.

### Making Network Unique:

```python
# Change these to create unique network:
IDENTIFIER = 'YOURPOOL'.encode('hex').decode('hex')
PREFIX = 'YOURPREF'.encode('hex').decode('hex')
COINBASEEXT = 'YOUR_COINBASE_TAG'.decode('hex')
P2P_PORT = 8997  # Different from mainnet (8999)
```

### Connecting Nodes:

Since there are no bootstrap nodes, manually connect:

```bash
# Node 1 (first node)
python run_p2pool.py --net dash_mypool <address>

# Node 2 (connect to node 1)
python run_p2pool.py --net dash_mypool <address> --p2pool-node <node1-ip>:8997
```

## Payout Behavior

**Important:** REAL_CHAIN_LENGTH determines payout window.

```python
REAL_CHAIN_LENGTH = 5*24*60*60//20  # 5 days
```

**This means:**
- Miners get paid from shares in last 5 days
- New miners take 5 days to reach full payout rate
- More stable earnings, less variance
- But slower response to hashrate changes

**Trade-off:**
- Shorter chain: More responsive, more variance
- Longer chain: More stable, slower response

## Testing Before Production

**Always test with regtest first:**

```bash
# Use regtest network (CHAIN_LENGTH=100)
python run_p2pool.py --net dash_regtest <address>

# Verify:
# 1. Shares accumulate properly
# 2. Archives created after 200 shares
# 3. Startup optimization works
# 4. Memory usage acceptable
# 5. Graceful shutdown archives correctly
```

**Then move to testnet:**

```bash
python run_p2pool.py --net dash_testnet <address>
```

**Finally, deploy custom network:**

```bash
python run_p2pool.py --net dash_mypool <address>
```

## Monitoring

### Check Archive Status:
```bash
# List archives
ls -lh data/share_archive/

# Count archived shares
wc -l data/share_archive/shares_*.txt

# Check latest
tail data/share_archive/shares_*.txt | tail -1
```

### Watch Logs:
```bash
# Look for archival messages
tail -f data/log | grep -i archive

# Example output:
# Checking for old shares to archive on startup...
# Archived 1523 old shares to shares_1702826400.txt (startup cleanup)
# Archived 342 old shares to shares_1702826460.txt (periodic)
```

### Monitor Resources:
```bash
# Memory usage
free -h
ps aux | grep python

# Disk usage
du -sh data/shares*
du -sh data/share_archive/
```

## Troubleshooting

### Archives not being created?
- Pool needs to run longer than 2×CHAIN_LENGTH
- Check disk space
- Check directory permissions
- Look for errors in logs

### Too much memory usage?
- Reduce CHAIN_LENGTH
- Or upgrade server RAM
- Check for memory leaks (shouldn't happen)

### Payouts not stable?
- Increase CHAIN_LENGTH (longer window)
- But requires more memory
- Trade-off with responsiveness

### Can't connect to other nodes?
- Verify IDENTIFIER and PREFIX match
- Check P2P_PORT matches
- Verify firewall rules
- Use --p2pool-node to manually connect

## Example Configurations

### Solo Mining Pool (Personal Use)
```python
CHAIN_LENGTH = 24*60*60//20  # 24 hours
REAL_CHAIN_LENGTH = 24*60*60//20
BOOTSTRAP_ADDRS = ''.split(' ')  # No bootstrap
P2P_PORT = 8997
WORKER_PORT = 7901
```

### Small Public Pool
```python
CHAIN_LENGTH = 2*24*60*60//20  # 48 hours
REAL_CHAIN_LENGTH = 2*24*60*60//20
BOOTSTRAP_ADDRS = 'node1.example.com node2.example.com'.split(' ')
P2P_PORT = 8996
WORKER_PORT = 7900
```

### Large Stable Pool
```python
CHAIN_LENGTH = 5*24*60*60//20  # 5 days
REAL_CHAIN_LENGTH = 5*24*60*60//20
BOOTSTRAP_ADDRS = 'pool1.example.com pool2.example.com pool3.example.com'.split(' ')
P2P_PORT = 8995
WORKER_PORT = 7899
```

## Key Takeaways

1. ✅ **Archival auto-scales** - no manual configuration needed
2. ✅ **Longer chains = more stable payouts** but use more resources
3. ✅ **Always test** with regtest/testnet first
4. ✅ **Plan resources** - memory and disk scale with CHAIN_LENGTH
5. ✅ **Monitor archives** - set up cleanup automation
6. ✅ **Unique identifiers** - prevent accidental mainnet connection

## References

- See `p2pool/networks/dash_custom_example.py` for annotated example
- See `SHARE_ARCHIVE_README.md` for archive management details
- See mainnet configs for production examples:
  - `dash.py` - 24 hour chain
  - `dash_testnet.py` - testnet with same parameters
  - `dash_regtest.py` - testing with 100 share chain
