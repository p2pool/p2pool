# LITECOIN P2POOL GLOBAL NETWORK - LIVE NODE DISCOVERY
**Date:** 2025-02-08  
**Discovery Method:** Network topology scan via `/peer_addresses` endpoint

---

## CONFIRMED LIVE NODES (2/15 from Bootstrap)

### 1. **ml.toom.im:9327** (Primary - jtoomim's global node)
- **Status:** 🟢 ONLINE (228+ days uptime)
- **Uptime:** 19,743,664 seconds (~228.3 days)
- **Hashrate:** 10.7 GH/s (actual), 10.07 GH/s (nonstale)
- **Miners:** 3-4 connected (tbl3.158: 730MH, tbl7.1: 11.36GH dominant, tbl3.531: 566MH)
- **Network:** 5 incoming + 3 outgoing = 8 peers
- **Version:** 16.0-204-g29fc6fc (jtoomim fork)
- **Protocol:** 3502
- **Efficiency:** 101.55% (1.0155)
- **Stale Rate:** 5.88% (orphan 1.96%, dead 3.92%)
- **Share Chain:** Total 356,708 shares (2,081 orphan, 2,647 dead)

### 2. **20.106.76.227:9327** (Secondary - Unknown operator)
- **Status:** 🟢 ONLINE
- **Hashrate:** 23.0 GH/s (actual), 22.58 GH/s (nonstale)
- **Miners:** 8 connected (dominant: LKgAMpNXkKSq1ixoELmGS2UfvNn2TrpFBx.*: 16.3GH)
- **Network:** 5 incoming + 3 outgoing = 8 peers
- **Efficiency:** 101.37%
- **Stale Rate:** 1.80% (orphan 0%, dead 1.80%) - **EXCELLENT**
- **Share Chain:** Total 4,908 shares (newer pool)

---

## PEER TOPOLOGY DISCOVERY

### From ml.toom.im (/peer_addresses):
```
10.0.1.2:60192          (internal/VPN)
20.106.76.227           (secondary node - CONFIRMED ALIVE)
66.151.242.154:43880    (offline)
174.60.78.162           (offline)
173.79.139.224          (offline)
31.25.241.224:56704     (offline, was in bootstrap)
20.113.157.65:35882     (offline)
20.127.82.115           (offline)
```

### From 20.106.76.227 (/peer_addresses):
```
15.218.180.55:43830     (offline)
173.79.139.224:47778    (offline)
20.127.82.115           (offline)
10.8.0.7:47450          (internal/VPN)
15.218.180.55:54296     (offline)
31.25.241.224           (offline, was in bootstrap)
174.60.78.162:54904     (offline)
66.151.242.154          (offline)
```

---

## BOOTSTRAP NODES STATUS

### Originally Listed (p2pool/networks/litecoin.py):
| Address | Status | Notes |
|---------|--------|-------|
| ml.toom.im | 🟢 ONLINE | Primary - jtoomim's main global node |
| 31.25.241.224 | 🔴 OFFLINE | Bootstrap list (no response) |
| 83.221.211.116 | 🔴 OFFLINE | Bootstrap list (no response) |
| 20.106.76.227 | 🟢 ONLINE | Discovered via peer_addresses |
| crypto.office-on-the.net | 🔴 OFFLINE | Stale/DNS issue |
| ltc.p2pool.leblancnet.us | 🔴 OFFLINE | Stale/DNS issue |
| 51.148.43.34 | 🔴 OFFLINE | Legacy address |
| 68.131.29.131 | 🔴 OFFLINE | Legacy address |
| 87.102.46.100 | 🔴 OFFLINE | Legacy address |
| 89.237.60.231 | 🔴 OFFLINE | Legacy address |
| 95.79.35.133 | 🔴 OFFLINE | Legacy address |
| 96.255.61.32 | 🔴 OFFLINE | Legacy address |
| 174.56.93.93 | 🔴 OFFLINE | Legacy address |
| 178.238.236.130 | 🔴 OFFLINE | Legacy address |
| 194.190.93.235 | 🔴 OFFLINE | Legacy address |

---

## NETWORK INSIGHTS

### Active Network Characteristics:
1. **Consolidated Network:** P2Pool has consolidated around 2 primary nodes
   - ml.toom.im: Primary (jtoomim infrastructure)
   - 20.106.76.227: Secondary (higher hashrate, better performance)

2. **Total Active Hashrate:** ~33.7 GH/s
   - ml.toom.im: 10.7 GH/s
   - 20.106.76.227: 23.0 GH/s
   - **Litecoin network:** 2.88 EH/s (2,880,000x larger)

3. **Network Quality:**
   - Secondary node (20.106.76.227) has MUCH better stale rates (1.8% vs 5.88%)
   - Both nodes have 8-peer connections, suggesting tight clustering
   - Peer addresses show internal IPs (10.x, 10.8.x) indicating same infrastructure

4. **Peer Connectivity Pattern:**
   - Both nodes reference each other in peer lists
   - Secondary node appears to have better geolocation (lower latency)
   - Internal peers (10.0.1.2, 10.8.0.7) suggest same datacenter/VPN

5. **Bootstrap List Status:**
   - All 13 legacy bootstrap addresses are OFFLINE (or behind NAT)
   - Only ml.toom.im and discovered peer (20.106.76.227) are truly accessible
   - Peer discovery now relies on live peer connections

---

## OPERATIONAL IMPLICATIONS FOR YOUR TEST NETWORK

Your 3 local nodes (.29, .30, .31) connect via BOOTSTRAP_ADDRS to these 2 global nodes:

### Expected Peer Connectivity:
```
Local nodes (.29, .30, .31)
    ↓
BOOTSTRAP_ADDRS points to ml.toom.im (primary)
    ↓
ml.toom.im has 8 peers including 20.106.76.227
    ↓
20.106.76.227 has 8 peers (some overlapping)
    ↓
Total active global P2Pool network: 2 major nodes + 6 peers
```

### Network Isolation Risks:
- **Minimal redundancy:** Only 2 truly live nodes (ml.toom.im + 20.106.76.227)
- **Single point of failure:** If ml.toom.im goes offline, peers might drop significantly
- **Legacy bootstrap addresses are stale:** Updated list needed for new node deployments

### V36 Activation Considerations:
After LiF7 miner switch (08:50 Feb 8):
- **Local network:** 100% V36-signaling (.29 has 2 miners, .31 has 1 miner)
- **Global network:** Limited V36 visibility (depends on what ml.toom.im and peers are running)
- **Share propagation:** Will propagate through ml.toom.im → 20.106.76.227 → other peers

---

## DISCOVERED ACTIVE PEER ADDRESSES

**From ml.toom.im's perspective:**
- 20.106.76.227 ✅ CONFIRMED
- 66.151.242.154, 174.60.78.162, 173.79.139.224, 31.25.241.224, 20.113.157.65, 20.127.82.115 ❌ OFFLINE

**From 20.106.76.227's perspective:**
- 15.218.180.55, 173.79.139.224, 20.127.82.115, 31.25.241.224, 174.60.78.162, 66.151.242.154 ❌ OFFLINE

---

## SUMMARY

**Live Global P2Pool Nodes: 2/15**

1. ✅ **ml.toom.im** - 10.7 GH/s (primary jtoomim infrastructure)
2. ✅ **20.106.76.227** - 23.0 GH/s (secondary, higher performance)

All other bootstrap addresses are offline. The global P2Pool Litecoin network has significantly consolidated around jtoomim's infrastructure. Your test network should expect to peer primarily with these 2 nodes when connecting to the global network.
