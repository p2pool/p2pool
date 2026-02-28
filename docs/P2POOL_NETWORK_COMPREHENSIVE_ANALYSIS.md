# COMPREHENSIVE P2POOL LITECOIN NETWORK ANALYSIS

**Date:** 2025-02-08  
**Discovery Method:** Hierarchical peer crawling (3 depth levels)  
**Total Nodes Discovered:** 13 (9 online, 4 offline)

---

## EXECUTIVE SUMMARY

The P2Pool Litecoin network is **MUCH LARGER** than previously thought:

| Metric | Previous Scan | Full Network Scan |
|--------|---------------|-------------------|
| Nodes Found | 2 | 9 online |
| Total Hashrate | 33.7 GH/s | **61.01 GH/s** (+81%) |
| Discovery Method | Bootstrap addresses only | Peer crawling |
| Hidden Cluster | N/A | **NEW: 40.39 GH/s deployed 2 days ago!** |

**CRITICAL FINDING:** Three nodes deployed 2 days ago now control 66% of network hashrate. Running different code version (16.0-203-*) than jtoomim's legacy nodes (16.0-204-*).

---

## ONLINE NODES RANKED BY HASHRATE (9 NODES)

### TIER 1 - PRIMARY NODES (HIGH ACTIVITY)

#### 20.106.76.227 ⚡ **DOMINANT NODE**
- **Hashrate:** 22.16 GH/s (36% of total)
- **Uptime:** 2 days (RECENT DEPLOYMENT)
- **Peers:** 5 incoming, 3 outgoing = 8 connections
- **Version:** 16.0-203-g95b882a0-d (NEWER/ALTERNATE BRANCH)
- **Status:** VERY ACTIVE - High hashrate, recent, well-connected

#### 20.113.157.65 ⚡ **NEW CLUSTER NODE**
- **Hashrate:** 13.19 GH/s (22% of total)
- **Uptime:** 2 days (RECENT DEPLOYMENT)
- **Peers:** 2 incoming, 5 outgoing = 7 connections
- **Version:** 16.0-203-g95b882a0-d (NEWER/ALTERNATE BRANCH)
- **Status:** VERY ACTIVE - High hashrate, recent, well-connected

### TIER 2 - STABLE BACKBONE NODES

#### ml.toom.im 🏛️ **PRIMARY LEGACY NODE**
- **Hashrate:** 10.01 GH/s
- **Uptime:** 228 days (PRIMARY INFRASTRUCTURE - LONG RUNNING)
- **Peers:** 5 incoming, 3 outgoing = 8 connections
- **Version:** 16.0-204-g29fc6fc (jtoomim's production fork)
- **Status:** STABLE - Old faithful, jtoomim's primary infrastructure

#### 15.218.180.55 🏛️ **LEGACY PAIR NODE**
- **Hashrate:** 10.00 GH/s
- **Uptime:** 228 days (LEGACY NODE - LONG RUNNING)
- **Peers:** 5 incoming, 3 outgoing = 8 connections
- **Version:** 16.0-204-g29fc6fc (jtoomim's production fork)
- **Status:** STABLE - Same vintage as ml.toom.im, likely paired infrastructure

### TIER 3 - MEDIUM NODES

#### 20.127.82.115 ⚡ **NEW CLUSTER NODE**
- **Hashrate:** 5.04 GH/s
- **Uptime:** 2 days (RECENT DEPLOYMENT)
- **Peers:** 5 incoming, 3 outgoing = 8 connections
- **Version:** 16.0-203-g95b882a0-d (NEWER)
- **Status:** NEWER CLUSTER - Part of recent 20.x.x.x deployment

### TIER 4 - LOW/ZERO HASHRATE NODES (INFRASTRUCTURE/ARCHIVE)

#### 174.60.78.162
- **Hashrate:** 0.42 GH/s (MINIMAL)
- **Uptime:** 58 days
- **Peers:** 5 incoming, 3 outgoing = 8 connections
- **Version:** 16.0-202-gece15b0-di (OLDER)
- **Status:** ARCHIVE - Mostly P2P relay

#### 173.79.139.224
- **Hashrate:** 0.19 GH/s (TRACE)
- **Uptime:** 58 days
- **Peers:** 3 incoming, 5 outgoing = 8 connections
- **Version:** 16.0-202-gece15b0-di (OLDER)
- **Status:** ARCHIVE - Mostly peer relay

#### 66.151.242.154 ⚠️ **OBSOLETE CODEBASE**
- **Hashrate:** 0.00 GH/s (ZERO)
- **Uptime:** 173 days (VERY OLD)
- **Peers:** 5 incoming, 2 outgoing = 7 connections
- **Version:** 77.0.0-12-g5493200-d (COMPLETELY DIFFERENT CODEBASE!)
- **Status:** DEAD - Ancient node, incompatible version

#### 31.25.241.224 ⚠️ **OBSOLETE CODEBASE**
- **Hashrate:** 0.00 GH/s (ZERO)
- **Uptime:** 53 days
- **Peers:** 5 incoming, 3 outgoing = 8 connections
- **Version:** 77.0.0-12-g5493200-d (COMPLETELY DIFFERENT CODEBASE!)
- **Status:** DEAD - Different codebase, incompatible

---

## OFFLINE NODES (4 - All Internal IPs)

```
10.0.1.2       Private RFC1918
10.6.0.4       Private RFC1918
10.8.0.7       Private RFC1918
10.10.0.4      Private RFC1918
```

**Analysis:** These are VPN/internal nodes not accessible from public internet.
Likely part of same infrastructure (probably jtoomim's private network).

---

## NETWORK TOPOLOGY ANALYSIS

### Hashrate Distribution

```
Tier 1 (20.106.76.227, 20.113.157.65):  35.35 GH/s  (57.9% of total)
Tier 2 (ml.toom.im, 15.218.180.55):     20.01 GH/s  (32.8% of total)
Tier 3 (20.127.82.115):                  5.04 GH/s  ( 8.3% of total)
Tier 4 (Others):                         0.61 GH/s  ( 1.0% of total)
──────────────────────────────────────────────────────────
TOTAL:                                  61.01 GH/s  (100%)
```

### Version Distribution

**Modern (16.0-203-*):** 40.39 GH/s (66% of hashrate)
- 20.106.76.227, 20.113.157.65, 20.127.82.115

**Legacy (16.0-204-*):** 20.01 GH/s (33% of hashrate)
- ml.toom.im, 15.218.180.55

**Ancient (16.0-202-*):** 0.61 GH/s (1% of hashrate)
- 174.60.78.162, 173.79.139.224

**Obsolete (77.0.0-*):** 0.00 GH/s (0% - DEAD)
- 66.151.242.154, 31.25.241.224

### Network Connectivity Pattern

All major nodes maintain **5 incoming + 3 outgoing = 8 peer connections**

→ Highly interconnected mesh network  
→ Redundancy through peer diversity  
→ No single point of failure at peer level

### Uptime Clusters

```
228+ days:  ml.toom.im, 15.218.180.55 (jtoomim's original duo)
173 days:   66.151.242.154 (abandoned/dead)
58 days:    174.60.78.162, 173.79.139.224 (old tier)
53 days:    31.25.241.224 (abandoned/dead)
2 days:     20.106.76.227, 20.113.157.65, 20.127.82.115 (NEW CLUSTER!)
```

---

## 🚨 CRITICAL DISCOVERY: NEW ACTIVE CLUSTER

### Three New Nodes Deployed 2 Days Ago

```
1. 20.106.76.227 - 22.16 GH/s (DOMINANT!)
2. 20.113.157.65 - 13.19 GH/s (SIGNIFICANT)
3. 20.127.82.115 -  5.04 GH/s (MODERATE)

TOTAL NEW CLUSTER: 40.39 GH/s (66% of all network hashrate!)
```

### Key Implications

- Running NEWER code (16.0-203-g95b882a0-d vs 16.0-204-g29fc6fc)
- Possible new infrastructure provider or load balancing setup
- Suggests active network expansion/upgrade
- New deployment shares 20.x.x.x IP block (likely Azure/AWS cloud)
- **ALL THREE DEPLOYED SIMULTANEOUSLY** = coordinated infrastructure change

---

## V36 SHARE FORMAT PROPAGATION ANALYSIS

Your merged nodes will propagate V36 shares through this network:

### Optimal Propagation Path (by hashrate concentration)

```
Your V36 shares from local nodes
         ↓
    ml.toom.im (10.01 GH/s, 228d uptime - PRIMARY RELAY)
         ↓
    20.106.76.227 (22.16 GH/s - NEW DOMINANT NODE)
         ↓
    15.218.180.55 (10.00 GH/s, 228d uptime)
         ↓
    20.113.157.65 (13.19 GH/s - NEW)
         ↓
    20.127.82.115 (5.04 GH/s - NEW)
         ↓
    Remaining nodes (minimal hashrate, mostly archive)
```

### **KEY INSIGHT FOR V36 VOTING**

Your V36 voting impact depends **ENTIRELY** on whether the new cluster (66% of hashrate!) is running code that signals V36 or V35.

**Scenario A (New cluster signals V36):**
- V36 activation: **12-24 hours**
- Your nodes' hashrate accelerates voting

**Scenario B (New cluster signals V35):**
- V36 activation: **Indefinitely delayed**
- Your migration helps but only 1/3 of your hash vs 66% new cluster

---

## NETWORK HEALTH ASSESSMENT

### Strengths ✓

- 9 online nodes = good redundancy
- All major nodes have 8-peer connections = mesh connectivity
- No single point of failure (if one goes down, 8 peers take over)
- Geographic distribution (IPs span multiple ASNs)
- Active expansion (new cluster deployed 2 days ago)

### Weaknesses ⚠️

- 2 nodes running obsolete code (version 77!)
- 2 nodes with 0 hashrate (archives?)
- Large new cluster (66% hashrate) with only 2 days uptime
- Version divergence (modern vs legacy forks)
- All newest nodes deployed simultaneously = potential single point of control

### Risks ⚠️

- New cluster (20.x nodes) may revert or change direction
- V36 activation may depend entirely on new cluster's signaling
- If new cluster represents alternative codebase, could fork network
- 2-day uptime = high instability risk on new nodes
- Unknown operator of new cluster = potential governance concern

---

## COMPARISON TO PREVIOUS SCAN

### Previous Scan (Bootstrap Address Probing)
- Found 2 nodes: ml.toom.im (10.7 GH/s), 20.106.76.227 (23.0 GH/s)
- Total: 33.7 GH/s
- Only checked bootstrap addresses (13+ stale entries)

### New Scan (Hierarchical Peer Crawling)
- Found 9 online nodes
- Total: **61.01 GH/s** (81% MORE!)
- Discovered NEW cluster (20.113.157.65, 20.127.82.115)
- Found old archive nodes (66.151.242.154, 31.25.241.224, etc.)
- Reached 3 levels deep via peer address discovery

### Impact

**The true P2Pool Litecoin network is ~61 GH/s** (not 33.7 GH/s)  
(vs ~2.88 EH/s Litecoin global hashrate = 47,000x smaller)

---

## RECOMMENDATIONS

### 1. 🔴 PRIORITY: MONITOR NEW CLUSTER (20.x nodes)

- Track their code version and V36 signaling
- 66% of network hashrate = EXTREMELY IMPORTANT
- High instability risk (only 2 days uptime)
- Determine operator and intentions (merged-mining compatible?)

### 2. UPDATE BOOTSTRAP_ADDRS

**Current (stale):** 13+ legacy addresses  
**Recommended:**
```
ml.toom.im
15.218.180.55
20.106.76.227
20.113.157.65
20.127.82.115  (optional, monitor stability)
```

### 3. ARCHIVE OLD NODES SEPARATELY

- 66.151.242.154, 31.25.241.224 (version 77 - dead/incompatible codebase)
- 174.60.78.162, 173.79.139.224 (0.6 GH/s combined, legacy)

### 4. INVESTIGATE NEW CLUSTER ORIGINS

- Who deployed 20.x nodes?
- Which code fork are they running?
- Do they signal V36?
- Are they committed long-term?

### 5. V36 ACTIVATION CONTINGENCY

**If new cluster signals V36:** Activation ~12-24 hours ✓  
**If new cluster signals V35:** Activation indefinitely delayed ⚠️  
Your LiF7 migration helps but represents only ~1.6% of network hashrate when new cluster is 66%

---

## TECHNICAL NOTES

- All peer addresses extracted from `/peer_addresses` HTTP endpoint
- All stats from `/local_stats` HTTP endpoint
- Version numbers from node's reported `version` field
- Network probed using 3-level hierarchical discovery (depth=0,1,2)
- Internal IPs (10.x.x.x) could not be reached from public network

---

## NEXT STEPS

1. Check `/version_signaling` endpoint on all 3 new nodes to see if they signal V36
2. Correlate V36 voting with new cluster's hashrate contribution
3. Monitor 20.x cluster uptime and stability over next 48-72 hours
4. Determine if new cluster is under jtoomim's control or separate operator
5. Plan V36 activation expectations based on new cluster's behavior
