# P2Pool Merged Mining Test Infrastructure - Knowledge Base

**Created**: January 9, 2026  
**Status**: Planning Phase  
**Environment**: VMware ESXi 6.7.0  
**Purpose**: Dogecoin + Litecoin merged mining testing with ASICs

---

## Overview

Complete test infrastructure for P2Pool merged mining with Dogecoin, Litecoin, and ASIC miners (AntRouter L1).

```
┌────────────────────────────────────────────────────────┐
│                   VSphere Environment                  │
├────────────────────────────────────────────────────────┤
│                                                        │
│  ┌──────────────────────┐  ┌──────────────────────┐    │
│  │   DOGE Testnet VM    │  │   LTC Testnet VM     │    │
│  │ (Auxpow Modified)    │  │  (Standard Core)     │    │
│  │ - Dogecoin Core fork │  │ - Litecoin Core      │    │
│  │ - Getblocktemplate   │  │ - Scrypt hashing     │    │
│  │   auxpow support     │  │ - RPC enabled        │    │
│  │ - Port: 19334 (p2p)  │  │ - Port: 18333 (p2p)  │    │
│  │ - Port: 18332 (rpc)  │  │ - Port: 18332 (rpc)  │    │
│  └────────────┬─────────┘  └──────────────┬───────┘    │
│               │                           │            │
│  ┌────────────┴───────────────────────────┴─────┐      │
│  │                                              │      │
│  │         P2Pool Testing Node VM               │      │
│  │  (Merged Mining Aggregator)                  │      │
│  │  - P2Pool with scrypt-litecoin-dogecoin      │      │
│  │  - Stratum port: 7903                        │      │
│  │  - P2P port: 8999                            │      │
│  │  - ASICBOOST enabled                         │      │
│  │  - Extranonce dual protocol                  │      │
│  │                                              │      │
│  └────────────┬─────────────────────────────────┘      │
│               │                                        │
│  ┌────────────┴──────────────────────────────────┐     │
│  │      Scrypt Miners (Local/Network)            │     │
│  │  - CPU miners (cpuminer-multi)                │     │
│  │  - Optional: GPU miners (sgminer)             │     │
│  │                                               │     │
│  └───────────────────────────────────────────────┘     │
│                                                        │
└────────────────────────────────────────────────────────┘
         │
         │ Network Connection (192.168.86.x/24)
         │
    ┌────┴──────────────┐
    │                   │
 ASIC 1            ASIC 2-3
192.168.86.237   192.168.86.236
192.168.86.238   (AntRouter L1 - Scrypt)
```

---

## Hardware & Network Assets

### Available ASICs
- **Device**: AntRouter L1 (Scrypt/LTC-DOGE compatible)
- **Count**: 3 units
- **IPs**: 
  - 192.168.86.237
  - 192.168.86.236
  - 192.168.86.238
- **Specs**: ~500MH/s each (Scrypt)
- **Total Network Hash**: ~1.5GH/s (Scrypt)

### ESXi Cluster
- **Host**: VMware ESXi 6.7.0
- **Current VM**: dashp2pool (192.168.86.244)
  - Status: Active with P2Pool Dash
  - Can be repurposed or cloned

### Network
- **Segment**: 192.168.86.0/24
- **Gateway**: 192.168.86.1
- **Available IPs**: 192.168.86.245 - 192.168.86.254 (for new VMs)

---

## Phase 1: VM Creation & Deployment

### VM 1: Dogecoin Testnet Node (Modified Auxpow)

**Specifications**:
- **Name**: doge-testnet-auxpow
- **IP**: `192.168.86.24` (DEPLOYED - originally planned as 192.168.86.245)- **Public IP**: `10.1.1.129` (ens192 - for inbound peer connections)- **OS**: Ubuntu 24.04 LTS
- **CPU**: 2 cores
- **RAM**: 4 GB
- **Disk**: 50 GB (initial block download ~30GB)

**Installation Steps**:

```bash
# 1. Clone from existing dashp2pool VM or create fresh
# 2. Base OS setup
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y build-essential libssl-dev libboost-all-dev git curl

# 3. Clone Dogecoin Core auxpow branch
cd /opt
git clone --branch dogecoin-getblocktemplate-auxpow \
  https://github.com/dashpay/p2pool-dash.git dogecoin-core-auxpow
cd dogecoin-core-auxpow

# 4. Build Dogecoin Core with auxpow
# (Specific branch has build instructions)
./autogen.sh
./configure --disable-wallet --disable-gui
make -j$(nproc)
sudo make install

# 5. Create dogecoin user and directories
sudo useradd -m dogecoin || true
sudo mkdir -p /var/dogecoin/testnet3
sudo chown dogecoin:dogecoin /var/dogecoin

# 6. Configure testnet with auxpow
cat > /home/dogecoin/.dogecoin/dogecoin.conf << 'EOF'
# Testnet configuration
testnet=1

# RPC settings
server=1
rpcuser=dogetest
rpcpassword=DogeTestPass123!
rpcport=18332
rpcbind=0.0.0.0
rpcallowip=192.168.86.0/24

# Network settings
port=19334
maxconnections=32
datadir=/var/dogecoin

# Auxpow support
auxpow=1

# Logging
debug=rpc
debug=mining
debuglogfile=/var/dogecoin/testnet3/debug.log

# Performance
dbcache=512
maxmempool=512
EOF

# 7. Start Dogecoin daemon
dogecoind -datadir=/var/dogecoin

# Monitor sync progress
dogecoin-cli -datadir=/var/dogecoin getblockchaininfo
```

**Monitoring**:
```bash
# Watch sync progress
watch "dogecoin-cli -datadir=/var/dogecoin getblockchaininfo | jq '.headers, .blocks'"

# Check auxpow capability
dogecoin-cli -datadir=/var/dogecoin help getauxblock | head -20

# Monitor RPC connections
dogecoin-cli -datadir=/var/dogecoin getnetworkinfo
```

---

### VM 2: Litecoin Testnet Node

**Specifications**:
- **Name**: ltc-testnet
- **IP**: `192.168.86.26` (DEPLOYED - originally planned as 192.168.86.246)- **Public IP**: `10.1.1.145` (ens192 - for inbound peer connections)- **OS**: Ubuntu 24.04 LTS
- **CPU**: 2 cores
- **RAM**: 4 GB
- **Disk**: 50 GB (initial block download ~10GB)

**Installation Steps**:

```bash
# 1. Base OS setup
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y build-essential libssl-dev libboost-all-dev git

# 2. Clone and build Litecoin Core
cd /opt
git clone https://github.com/litecoin-project/litecoin.git
cd litecoin
git checkout v0.21.3  # Recent stable version

./autogen.sh
./configure --disable-wallet --disable-gui
make -j$(nproc)
sudo make install

# 3. Create litecoin user
sudo useradd -m litecoin || true
sudo mkdir -p /var/litecoin/testnet4
sudo chown litecoin:litecoin /var/litecoin

# 4. Configure testnet
cat > /home/litecoin/.litecoin/litecoin.conf << 'EOF'
# Testnet configuration
testnet=1

# RPC settings
server=1
rpcuser=ltctest
rpcpassword=LtcTestPass123!
rpcport=18332
rpcbind=0.0.0.0
rpcallowip=192.168.86.0/24

# Network settings
port=18333
maxconnections=32
datadir=/var/litecoin

# Logging
debug=rpc
debug=mining
debuglogfile=/var/litecoin/testnet4/debug.log

# Performance
dbcache=512
maxmempool=512
EOF

# 5. Start Litecoin daemon
litecoind -datadir=/var/litecoin

# Monitor sync
watch "litecoin-cli -datadir=/var/litecoin getblockchaininfo | jq '.headers, .blocks'"
```

---

### VM 3: P2Pool Merged Mining Node

**Specifications**:
- **Name**: p2pool-merged-test
- **IP**: 192.168.86.247
- **OS**: Ubuntu 24.04 LTS
- **CPU**: 4 cores
- **RAM**: 8 GB
- **Disk**: 100 GB

**Installation Steps**:

```bash
# 1. Install PyPy and dependencies
sudo snap install pypy --classic
pypy -m pip install twisted==19.10.0 pycryptodome

# 2. Clone P2Pool with merged mining support
cd /opt
git clone https://github.com/dashpay/p2pool-dash.git p2pool-merged
cd p2pool-merged
git checkout origin/feature/scrypt-litecoin-dogecoin
git submodule init && git submodule update

# 3. Build Scrypt module for LTC/DOGE
# (if ltc_scrypt needed for CPU mining tests)
cd dash_hash
pypy setup.py install --user
cd ..

# 4. Create P2Pool configuration
mkdir -p /opt/p2pool-merged/data
cat > /opt/p2pool-merged/config_merged.py << 'EOF'
# P2Pool Merged Mining Configuration

import sys

# Merged mining sources
MERGED_MINING_SOURCES = [
    # Dogecoin testnet auxpow
    {
        'name': 'dogecoin_testnet',
        'rpc_url': 'http://dogetest:DogeTestPass123!@192.168.86.24:18332',
        'coin': 'dogecoin',
        'enabled': True,
    },
    # Litecoin testnet
    {
        'name': 'litecoin_testnet',
        'rpc_url': 'http://ltctest:LtcTestPass123!@192.168.86.246:18332',
        'coin': 'litecoin',
        'enabled': True,
    },
]

# P2Pool Dash primary (for reference)
DASH_RPC = 'http://dashuser:dashpass@192.168.86.244:9998'

# Stratum configuration
STRATUM_CONFIG = {
    'port': 7903,
    'difficulty_interval': 30,  # seconds
    'target_time': 10,  # seconds per share
    'enable_asicboost': True,
    'enable_extranonce': True,
}

# Test addresses
PAYOUT_ADDRESS = 'DMyTestAddressForP2Pool'
EOF

# 5. Start P2Pool for merged mining testing
# Will be done after testnet nodes are synced
```

---

## Phase 2: Testnet Node Synchronization

### Dogecoin Testnet Initial Block Download (IBD)

**Status Tracking**:
```bash
# SSH to doge-testnet-auxpow (192.168.86.24)
ssh user@192.168.86.24

# Monitor progress
watch -n 5 "dogecoin-cli -datadir=/var/dogecoin getblockchaininfo | \
  jq '{headers: .headers, blocks: .blocks, progress: (.blocks/.headers*100|round)}'"

# Estimated time: 2-4 hours (testnet is smaller)
# Expected final: headers ~1,178,000 blocks (as of Dec 2025)
```

**Alternative: Snapshot Import** (Faster)
```bash
# If available, import snapshot instead of full IBD
# Reduces sync from 3 hours to 30 minutes
cd /var/dogecoin/testnet3
# Download snapshot...
tar -xzf dogecoin-testnet-snapshot.tar.gz
```

---

### Litecoin Testnet Initial Block Download (IBD)

**Status Tracking**:
```bash
# SSH to ltc-testnet (192.168.86.246)
ssh user@192.168.86.246

# Monitor progress
watch -n 5 "litecoin-cli -datadir=/var/litecoin getblockchaininfo | \
  jq '{headers: .headers, blocks: .blocks, progress: (.blocks/.headers*100|round)}'"

# Estimated time: 1-2 hours (testnet smaller than mainnet)
# Expected final: headers ~3,000,000+ blocks
```

---

## Phase 3: P2Pool Configuration & Testing

### P2Pool Startup Command

```bash
cd /opt/p2pool-merged

# Option 1: Merged mining with Dogecoin testnet
pypy run_p2pool.py \
  --net dogecoin_testnet \
  -a YOUR_DOGE_ADDRESS \
  --merged http://dogetest:DogeTestPass123!@192.168.86.245:18332 \
  --merged http://ltctest:LtcTestPass123!@192.168.86.246:18332 \
  -p 7903 \
  --disable-upnp

# Option 2: Dual merged mining with custom addresses
pypy run_p2pool.py \
  --net dogecoin_testnet \
  -a DOGE_ADDRESS+LTC_ADDRESS \
  --merged http://dogetest:DogeTestPass123!@192.168.86.245:18332 \
  --merged http://ltctest:LtcTestPass123!@192.168.86.246:18332 \
  -p 7903
```

### Testing Checklist

- [ ] Dogecoin testnet node synced
- [ ] Litecoin testnet node synced
- [ ] P2Pool connects to both nodes successfully
- [ ] Stratum port 7903 accepting connections
- [ ] Extranonce dual protocol active (BIP310 + NiceHash)
- [ ] Vardiff tuning optimized for Scrypt
- [ ] Note: ASICBOOST implemented in core but not supported by Scrypt algorithm

---

## Phase 4: ASIC Miner Configuration

### AntRouter L1 Setup

**Device Specs**:
- **Algorithm**: Scrypt (LTC/DOGE)
- **Hash Rate**: ~500 MH/s each
- **Firmware**: Factory default
- **Web UI**: Port 8081
- **API**: Port 4028 (CGMiner compatible)

**Configuration Steps**:

```bash
# 1. Access each router via web UI
# http://192.168.86.237:8081
# http://192.168.86.236:8081
# http://192.168.86.238:8081

# 2. Configure mining pool
# Pool URL: stratum+tcp://192.168.86.247:7903
# Worker: MINER_ADDRESS (will auto-route to LTC/DOGE)
# Password: x (dummy)

# 3. Via SSH to verify CGMiner
ssh admin@192.168.86.237
# Check miner status
curl http://127.0.0.1:4028/api

# 4. Start mining
cgminer --scrypt -o stratum+tcp://192.168.86.247:7903 \
  -u MINER_WALLET_ADDRESS -p x
```

**Monitoring via API**:
```bash
# Get miner summary
curl http://192.168.86.237:4028/api | jq '.SUMMARY'

# Watch hashrate
watch 'curl -s http://192.168.86.237:4028/api | jq ".SUMMARY[0] | {MHS5s: .MHS5s, MHSAV: .MHSAV}"'
```

---

## Phase 5: Integration Testing

### Unified Monitoring Dashboard

```bash
# Create monitoring script
cat > /opt/monitor_merged_mining.sh << 'MONITOR'
#!/bin/bash

echo "=== P2Pool Merged Mining Status ==="
date

echo -e "\n--- Dogecoin Testnet Node ---"
dogecoin-cli -datadir=/var/dogecoin \
  -rpcuser=dogetest -rpcpassword=DogeTestPass123! \
  -rpcport=18332 getblockchaininfo | jq '{blocks, headers, progress}'

echo -e "\n--- Litecoin Testnet Node ---"
litecoin-cli -datadir=/var/litecoin \
  -rpcuser=ltctest -rpcpassword=LtcTestPass123! \
  -rpcport=18332 getblockchaininfo | jq '{blocks, headers, progress}'

echo -e "\n--- P2Pool Stratum ---"
curl -s http://192.168.86.247:8000/global_stats 2>/dev/null | jq '.pool' || echo "P2Pool not ready"

echo -e "\n--- ASIC Miners ---"
for ip in 192.168.86.237 192.168.86.236 192.168.86.238; do
  echo "Miner at $ip:"
  curl -s http://$ip:4028/api 2>/dev/null | jq '.SUMMARY[0] | {MHS5s, MHSAV, A}' || echo "Offline"
done
MONITOR

chmod +x /opt/monitor_merged_mining.sh

# Run monitoring
watch /opt/monitor_merged_mining.sh
```

---

## Test Scenarios

### Scenario 1: Basic Connectivity
- [ ] All nodes ping each other
- [ ] RPC calls work from P2Pool to each testnet
- [ ] Stratum port accessible from all IPs
- [ ] Miners can connect to stratum

**Duration**: 30 minutes

### Scenario 2: Single Miner Test
- [ ] Connect 1 ASIC to P2Pool
- [ ] Generate 10-20 shares
- [ ] Verify share distribution (30% LTC, 70% DOGE expected)
- [ ] Check local hashrate tracking

**Duration**: 2 hours

### Scenario 3: Multi-Miner Load Test
- [ ] Connect all 3 ASICs
- [ ] Run for 4+ hours
- [ ] Monitor for orphaned blocks
- [ ] Check network difficulty tracking
- [ ] Verify Extranonce dual protocol functioning

**Duration**: 6+ hours

### Scenario 4: Block Submission
- [ ] Wait for a block to be found
- [ ] Verify submission to both testnets
- [ ] Check block confirmation times
- [ ] Monitor difficulty adjustments

**Duration**: 12+ hours (depends on luck)

---

## VM Network Configuration Summary

| VM | IP | Role | Ports | Status |
|----|----|----|----|----|
| doge-testnet-auxpow | 192.168.86.24 | Dogecoin testnet + auxpow | 18332 (RPC), 19334 (P2P) | ✅ Deployed |
| ltc-testnet | 192.168.86.246 | Litecoin testnet | 18332 (RPC), 18333 (P2P) | Ready for setup |
| p2pool-merged-test | 192.168.86.247 | P2Pool merged mining | 7903 (Stratum), 8000 (Web), 8999 (P2P) | Ready for setup |
| asic-1 | 192.168.86.237 | AntRouter L1 Scrypt | 4028 (API), 8081 (Web) | Already available |
| asic-2 | 192.168.86.236 | AntRouter L1 Scrypt | 4028 (API), 8081 (Web) | Already available |
| asic-3 | 192.168.86.238 | AntRouter L1 Scrypt | 4028 (API), 8081 (Web) | Already available |

---

## Deployment Priority

### Week 1: Infrastructure
- [ ] VM 1: Dogecoin testnet (auxpow)
- [ ] VM 2: Litecoin testnet
- [ ] Wait for IBD completion (~4 hours total)

### Week 2: P2Pool & Testing
- [ ] VM 3: P2Pool merged mining node
- [ ] Configure ASIC miners
- [ ] Run basic connectivity tests

### Week 3: Load Testing
- [ ] Single miner test (Scenario 2)
- [ ] Multi-miner test (Scenario 3)
- [ ] Collect performance metrics

### Week 4: Optimization & Documentation
- [ ] Fine-tune difficulty parameters
- [ ] Optimize block propagation
- [ ] Document findings

---

## Quick Reference: Key Commands

### Dogecoin Testnet
```bash
# Check balance
dogecoin-cli -datadir=/var/dogecoin getbalance

# Get new address
dogecoin-cli -datadir=/var/dogecoin getnewaddress

# Check auxpow support
dogecoin-cli -datadir=/var/dogecoin help getauxblock

# Get peer info
dogecoin-cli -datadir=/var/dogecoin getpeerinfo | jq length
```

### Litecoin Testnet
```bash
# Check balance
litecoin-cli -datadir=/var/litecoin getbalance

# Get new address
litecoin-cli -datadir=/var/litecoin getnewaddress

# Monitor mempool
litecoin-cli -datadir=/var/litecoin getmempoolinfo
```

### P2Pool Monitoring
```bash
# View web UI
firefox http://192.168.86.247:8000

# Check connected miners
curl http://192.168.86.247:8000/miners_list

# Get pool stats
curl http://192.168.86.247:8000/global_stats | jq '.pool'
```

### ASIC Status
```bash
# Check all miners
for ip in 192.168.86.{237,236,238}; do
  echo "=== $ip ==="
  curl -s http://$ip:4028/api | jq '.SUMMARY[0]'
done
```

---

## Troubleshooting Reference

| Issue | Solution |
|-------|----------|
| **Dogecoin IBD stalled** | Check peers: `getpeerinfo \| jq length`. Add peers manually if <2 connected |
| **P2Pool won't connect to RPC** | Verify firewall rules: `ufw allow 18332/tcp` and `ufw allow 18333/tcp` |
| **ASIC miners not connecting** | Check stratum port: `netstat -tlnp \| grep 7903`. Verify firewall rules |
| **Shares not submitting** | Check P2Pool logs for RPC errors. Verify merged mining URLs in config |
| **Orphaned blocks** | Likely network delay. Check block propagation time via logs |
| **Low hashrate from miners** | Check difficulty settings in P2Pool (should be auto-tuned) |

---

## Success Criteria

- ✅ All 3 VMs created and networked
- ✅ Dogecoin & Litecoin testnet nodes fully synced
- ✅ P2Pool successfully aggregating from merged sources
- ✅ All 3 ASICs mining at target hashrate
- ✅ Found at least 1 valid block on merged network
- ✅ Complete monitoring dashboard active
- ✅ All test scenarios completed successfully

---

## Next Steps

1. **Create the 3 VMs** in VSphere
2. **Install and configure** Dogecoin testnet (auxpow)
3. **Install and configure** Litecoin testnet
4. **Wait for IBD** (~4 hours combined)
5. **Deploy P2Pool** on 192.168.86.247
6. **Configure ASICs** to point to P2Pool
7. **Start merged mining** tests
8. **Monitor and optimize**

---

*Document Version: 1.0*  
*Last Updated: January 9, 2026*  
*Maintainer: P2Pool Test Team*
