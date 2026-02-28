# Roadmap & Future Enhancements

This document outlines the forward-looking roadmap for p2pool development.
All enhancements are designed **chain-agnostic** unless tagged **[COIN-SPECIFIC]**.
The ultimate goal is migrating proven features into
[c2pool](https://github.com/frstrtr/c2pool) (C++ reimplementation).

> **Scope**: This file covers *future work only*. For already-implemented features,
> see [CHANGELOG.md](../CHANGELOG.md) and [README.md](../README.md).

---

## Stratum Protocol Enhancements

### 1. `mining.ping` Support
**Difficulty:** Easy | **Impact:** Medium

Ping/pong for connection health monitoring. Detects dead connections faster,
reduces stale work submissions.

```python
def rpc_ping(self):
    return "pong"
```

### 2. SSL/TLS Stratum
**Difficulty:** Hard | **Impact:** High

Encrypted stratum connections — protects against MITM attacks and hash-rate
hijacking on untrusted networks.

```bash
--stratum-ssl-port PORT    # SSL stratum port (e.g., 3334)
--ssl-cert FILE            # Path to SSL certificate
--ssl-key FILE             # Path to SSL private key
```

### 3. Worker Auto-Banning
**Difficulty:** Medium | **Impact:** High

Automatically ban misbehaving workers temporarily:

- High reject rate (>50% over N submissions)
- Rapid reconnection attempts (DoS prevention)
- Invalid authorization attempts

```python
class WorkerBanList:
    def __init__(self, ban_duration=300):  # 5-minute default
        self.banned = {}  # {ip: ban_expiry_time}

    def check_and_ban(self, ip, reject_rate):
        if reject_rate > 0.5:
            self.banned[ip] = time.time() + self.ban_duration
```

### 4. `mining.set_version_mask`
**Difficulty:** Easy | **Impact:** Medium

Allow dynamic version-rolling mask updates mid-session without reconnection:

```python
def rpc_set_version_mask(self, mask):
    self.pool_version_mask = int(mask, 16)
    return True
```

### 5. `client.show_message`
**Difficulty:** Easy | **Impact:** Low

Broadcast operator messages to all connected miners — useful for maintenance
announcements, pool updates, emergency notifications:

```python
def broadcast_message(self, message):
    for conn in pool_stats.connections.values():
        conn.other.svc_client.rpc_show_message(message)
```

### 6. `client.get_version`
**Difficulty:** Easy | **Impact:** Low

Request miner software version for diagnostics and compatibility tracking.

---

## Pool Infrastructure

### 7. CLI Safeguard Arguments
**Difficulty:** Easy | **Impact:** High

Expose pool safety parameters as command-line arguments instead of hardcoded
values:

```bash
--min-difficulty DIFF      # Minimum difficulty floor (default: 0.001)
--max-difficulty DIFF      # Maximum difficulty ceiling (default: 1000000)
--max-connections NUM      # Maximum concurrent connections (default: 10000)
--session-timeout SECS     # Session expiration time (default: 3600)
```

### 8. Prometheus `/metrics` Endpoint
**Difficulty:** Medium | **Impact:** High

Standard Prometheus format for Grafana dashboards:

```
# HELP p2pool_connected_workers Number of connected workers
# TYPE p2pool_connected_workers gauge
p2pool_connected_workers 6

# HELP p2pool_pool_hashrate Pool hashrate in H/s
# TYPE p2pool_pool_hashrate gauge
p2pool_pool_hashrate 948000000000

# HELP p2pool_shares_accepted Total accepted shares
# TYPE p2pool_shares_accepted counter
p2pool_shares_accepted 15234

# HELP p2pool_blocks_found Total blocks found
# TYPE p2pool_blocks_found counter
p2pool_blocks_found 3
```

### 9. Block Found Webhook
**Difficulty:** Easy | **Impact:** Medium

Notify external services when the pool finds a block:

```bash
--block-webhook URL        # URL to POST on block found
```

```json
{
  "event": "block_found",
  "block_hash": "00000000...",
  "block_height": 123456,
  "timestamp": 1702300000,
  "value": 12.5
}
```

### 10. Historical Worker Statistics DB
**Difficulty:** Medium | **Impact:** Medium

Persist worker statistics to SQLite for historical analysis:

```bash
--stats-db FILE            # Path to statistics database
--stats-retention DAYS     # Retention period (default: 30)
```

### 11. API Authentication
**Difficulty:** Medium | **Impact:** Low

Optional API key for sensitive endpoints:

```bash
--api-key KEY              # Required key for API access
--api-key-endpoints LIST   # Comma-separated protected endpoints
```

### 12. Email/SMS Alerts
**Difficulty:** Medium | **Impact:** Medium

Configurable alerts for important events:

```bash
--alert-email ADDRESS      # Email for alerts
--alert-smtp-server HOST   # SMTP server
--alert-events LIST        # Events: block_found, node_down, hashrate_drop
```

---

## Web UI

### 13. WebSocket Real-Time Updates
**Difficulty:** Hard | **Impact:** Medium

Replace HTTP polling with WebSocket for live dashboard updates — instant
statistics, reduced server load, better UX.

### 14. Mobile-Responsive Design
**Difficulty:** Easy | **Impact:** Medium

CSS breakpoints for tablets and phones:

```css
@media (max-width: 768px) {
    .stats-grid { grid-template-columns: 1fr; }
    table { font-size: 12px; }
}
```

### 15. Per-Worker Hash Rate Graphs
**Difficulty:** Medium | **Impact:** Medium

Track hash rate samples over time per worker. New page at
`/static/worker.html?name=<worker>` with D3.js line charts matching the
existing `graphs.html` style.

---

## Share Redistribution System (`--redistribute`)

### Current Implementation (v36-0.03)

The `--redistribute` flag controls what happens to shares from unnamed or broken
miners (empty stratum username, invalid/unparseable address). These shares would
otherwise be lost or default to the node operator.

| Mode | Recipient | Use Case |
|--------|---------------------------------------------|------------------------------------------|
| `pplns` | Existing PPLNS miners (proportional weight) | Default — neutral, as if share didn't exist |
| `fee` | Node operator (100%) | Incentivizes running public nodes |
| `boost` | Connected miners with zero PPLNS shares | Helps tiny miners who can't find shares |
| `donate` | Development donation script (P2SH/P2PK) | Funds protocol maintenance |

Caches use **event-driven invalidation** — zero CPU cost when nothing changes,
instant response when the share chain advances or stratum connections change,
with a 10-second rate limit on recomputation.

### Anti-Gaming Properties

The boost mode is naturally resistant to exploitation:

- **Hash power attacker**: Would quickly earn PPLNS shares and lose boost
  eligibility
- **Zero-hash attacker**: Opens stratum connections but submits no pseudoshares
  — gains nothing since boost only fires when a *different* broken miner's share
  triggers redistribution (rare event)
- **Multi-connection attacker**: Per-IP connection limits in `pool_stats` cap
  the number of unique addresses per IP
- **Sybil via multiple IPs**: Each fake identity must maintain an active stratum
  connection, and redistributable share volume is tiny (only broken miners
  generate it), making the attack uneconomical

### Planned: Graduated Boost
**Difficulty:** Medium | **Impact:** High

Weight by **persistence** instead of equal probability — a miner hashing for
12 hours with zero shares deserves more boost than one connected 5 minutes ago.

Combined score: `uptime_hours × pseudoshare_count × avg_difficulty`

1. **Uptime weight** — `min(connection_duration_hours, 24)`, capped to prevent
   indefinite accumulation
2. **Pseudoshare weight** — Total accepted pseudoshares on this connection,
   directly measuring contributed work
3. **Selection** — Probability proportional to combined score

Data sources already available: `conn.connection_time`,
`conn.shares_accepted`, `conn.target`.

### Planned: Hybrid Mode
**Difficulty:** Medium | **Impact:** High

Split redistributed shares across multiple modes:

```bash
--redistribute boost:70,donate:20,fee:10
```

Per-share probabilistic allocation. Single-mode syntax (`--redistribute boost`)
remains backward-compatible at 100% weight.

### Planned: Share-Rate Threshold Boost
**Difficulty:** Hard | **Impact:** Medium

Boost miners whose PPLNS weight is **below their expected contribution** based
on their stratum pseudoshare rate:

```
expected_weight = miner_hashrate / pool_hashrate
actual_weight   = miner_pplns_weight / total_pplns_weight

if actual_weight / expected_weight < 0.1:
    eligible_for_threshold_boost = True
```

Extends boost beyond zero-share miners to statistically "unlucky" miners.

### Planned: Explicit Opt-In
**Difficulty:** Easy | **Impact:** Medium

Miners signal boost eligibility via stratum password field:

```
Username: LTC_ADDRESS,DOGE_ADDRESS
Password: boost:true
```

The password field is already unused by p2pool, making it a natural channel for
miner preferences. Future keys: `d=N` (min difficulty), `notify:true` (share
notifications).

---

## Block Propagation

### 16. Direct Peer Broadcast
**Difficulty:** Hard | **Impact:** Critical

**Problem:** P2Pool sends found blocks only to the local coin daemon, which
then broadcasts to its ~8 peers. Large pools broadcast to 50–100+ peers
instantly.

**Solution:** Parallel P2P broadcast to multiple full nodes:

```bash
--peer-list FILE           # JSON: [{"host": "1.2.3.4", "port": 9333}, ...]
--broadcast-peers NUM      # Number of peers to broadcast to (default: 10)
```

**Strategy:**
- Mining pools (prevent them getting unfair advantage)
- Block explorers (high uptime, well-connected)
- Exchange nodes (critical for network security)

**Estimated impact:** Could reduce orphan rate from ~5% to <1% for solo miners.

> **[COIN-SPECIFIC]** Chains with instant finality mechanisms (e.g., Dash
> ChainLock) benefit most — first block to reach the quorum wins.

---

## C++ Migration — c2pool

[c2pool](https://github.com/frstrtr/c2pool) is a near-complete C++
reimplementation of p2pool's sharechain protocol. Started in 2020, it provides
a modern, high-performance foundation for the next generation of decentralized
mining pools.

**Repository:** https://github.com/frstrtr/c2pool
**Community:** [Telegram](https://t.me/c2pooldev) ·
[Discord](https://discord.gg/yb6ujsPRsv)

### Architecture

```
┌─────────────────────────────────────────────────┐
│                  c2pool (C++)                   │
├─────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────────┐  │
│  │  Web Server      │  │  P2P Node           │  │
│  │  (Mining)        │  │  (Sharechain)       │  │
│  │                  │  │                     │  │
│  │  • Stratum       │  │  • Share sync       │  │
│  │  • JSON-RPC      │  │  • Peer management  │  │
│  │  • getwork       │  │  • LTC protocol     │  │
│  │  • submitblock   │  │                     │  │
│  └─────────────────┘  └─────────────────────┘  │
├─────────────────────────────────────────────────┤
│  hashrate/  difficulty/  storage/  node/        │
│  (tracking)  (VARDIFF)   (LevelDB)  (NodeImpl)  │
└─────────────────────────────────────────────────┘
```

### Already Implemented in c2pool

| Component | Status | Notes |
|-----------|--------|-------|
| LTC sharechain integration | ✅ Done | Production-ready `NodeImpl` |
| Persistent storage (LevelDB) | ✅ Done | Binary shares + JSON index, auto-backup/recovery |
| Stratum server | ✅ Done | HTTP/JSON-RPC mining interface |
| VARDIFF | ✅ Done | Automatic difficulty adjustment |
| Share serialization | ✅ Done | Network-compatible with Python p2pool |
| Peer management | ✅ Done | Address discovery, connection handling |
| Build system (CMake) | ✅ Done | Builds on Linux, FreeBSD, Windows |
| YAML configuration | ✅ Done | `~/.c2pool/settings.yaml` |

### To Port from p2pool-merged-v36

| Feature | Priority | Complexity | Description |
|---------|----------|------------|-------------|
| V36 share format | **Critical** | Hard | Version-aware ratchet, AutoRatchet, `PUBKEY_TYPE` field |
| Merged mining | **Critical** | Hard | Auxpow construction, multi-chain coinbase, `getblocktemplate` + `submitauxblock` |
| Address conversion | **High** | Medium | P2PKH/P2WPKH/P2SH cross-chain conversion for merged payouts |
| Share redistribution | **High** | Medium | 4-mode `--redistribute` with event-driven cache invalidation |
| Transition messaging | **Medium** | Medium | ECDSA-signed protocol upgrade signals embedded in shares |
| Stratum monitor web UI | **Medium** | Easy | `/stratum_stats` page, security dashboard |
| Pool statistics | **Medium** | Easy | `PoolStatistics` singleton, per-worker tracking |
| Event-driven caching | **Low** | Easy | Pattern: invalidate on state change, rate-limit recomputation |

### Migration Strategy

The recommended approach is **incremental porting** — implement features in
p2pool-merged-v36 (Python) first, validate on production, then port the proven
design to c2pool (C++). This reduces risk: the Python implementation serves as
both a working reference and a test suite.

**Porting order:**
1. **Share format** — V36 shares must be wire-compatible between Python and C++
   nodes on the same p2pool network
2. **Merged mining** — Requires coinbase construction, auxpow proof generation,
   and multi-daemon RPC orchestration
3. **Stratum enhancements** — SSL/TLS, worker banning, CLI safeguards
4. **Web UI** — Port last; web frontends can be shared or swapped independently

---

## Fork Archaeology

Features evaluated from other p2pool forks. This section documents what was
kept, what was rejected, and why — as guidance for future contributors.

### jtoomim/p2pool (Bitcoin Cash Fork)

**Source:** [jtoomim/p2pool](https://github.com/jtoomim/p2pool)

**Evaluated features:**

| Feature | Description | Verdict | Reason |
|---------|-------------|---------|--------|
| `txidcache` | Cache raw tx hex → txid | **Rejected** | Fast-block chains (2.5 min) have high mempool churn; cache hit rate too low to justify overhead |
| `feecache` | Cache txid → fee (LRU, 100K entries) | **Rejected** | Designed for old share structure (VERSION < 34) where subsidy is embedded in shares; modern nodes validate fees in `getblocktemplate` |
| `known_txs` | Reuse parsed transaction objects | **Rejected** | Same reasoning as `txidcache` — low hit rate with fast blocks |
| Naughty share detection | Mark shares claiming excessive rewards | **Rejected** | Not applicable — block reward validation is handled by the coin daemon, not p2pool's share validation |

**What was kept:**

- ✅ **Transaction dependency handling** — Include ALL transactions from
  `getblocktemplate` in BIP 22 order. Original p2pool incorrectly skipped
  transactions with a `depends` field even when dependencies were satisfied.
- ✅ **`--bench` flag** — Performance timing for debugging, adapted to measure
  different aspects than the BCH fork.

---

## Code Quality

### Known XXX/TODO Comments

1. `p2pool/util/graph.py` — Exception handling marked as "XXX blah"
2. `p2pool/data.py` — Uses local stale rate instead of global for pool hash
   calculation
3. `p2pool/main.py` — Windows file rename workaround needs better
   cross-platform handling

### Testing Improvements

- Unit tests for stratum extensions (VARDIFF, version-rolling, session
  resumption)
- Integration tests with mock miners (simulated ASIC behavior)
- Performance benchmarks for high-load scenarios (1000+ concurrent connections)

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/enhancement-name`)
3. Implement the enhancement
4. Add/update tests and documentation
5. Submit a pull request referencing this document

---

## Roadmap

| Phase | Focus | Key Items |
|-------|-------|-----------|
| **v36-0.04** | Stratum hardening | CLI safeguards, `mining.ping`, worker banning, graduated boost |
| **v36-0.05** | Observability | Prometheus metrics, block webhooks, historical stats DB |
| **v36-0.06** | Security & UX | SSL/TLS stratum, API auth, hybrid redistribute, mobile UI |
| **v36-1.0** | Stable release | Full test coverage, documentation freeze, production hardening |
| **c2pool** | C++ migration | Port V36 share format, merged mining, redistribution, stratum enhancements |
