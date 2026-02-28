# P2Pool Merged Mining Test Environment - Complete Package

**Creation Date**: January 9, 2026  
**Status**: 🟢 Ready for Deployment  
**Version**: 1.0

---

## 📦 What's Included

This test infrastructure package contains everything needed to set up and run merged mining for Dogecoin, Litecoin, and Dash with 3 ASIC miners (AntRouter L1).

### Documentation Files

1. **TEST_INFRASTRUCTURE_KB.md** ⭐
   - Complete infrastructure design
   - Detailed VM specifications (3 VMs)
   - Step-by-step installation instructions
   - Network architecture diagram
   - Testnet sync procedures
   - Integration testing scenarios

2. **DEPLOYMENT_CHECKLIST.md** 📋
   - Phase-by-phase deployment tracking
   - Pre-filled status checkboxes
   - Timeline tracking for each phase
   - Testing validation scenarios
   - Success criteria verification
   - Troubleshooting reference table

3. **QUICK_REFERENCE.md** ⚡
   - Quick command reference
   - All CLI commands for all services
   - Log monitoring commands
   - Troubleshooting commands
   - Useful aliases for ~/.bashrc
   - Web dashboard URLs

4. **setup_test_infrastructure.sh** 🔧
   - Automated setup script
   - Interactive menu system
   - Phase-based deployment
   - Service validation
   - Monitoring script generation

---

## 🏗️ Infrastructure Overview

```
┌─ VSPHERE (ESXi 6.7.0) ──────────────────────────────────┐
│                                                           │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │ Dogecoin Testnet │  │ Litecoin Testnet │             │
│  │ P2POOL_VM_IP   │  │ LTC_VM_IP   │             │
│  │ RPC: 18332       │  │ RPC: 18332       │             │
│  └────────┬─────────┘  └────────┬─────────┘             │
│           └──────────────────┬──────────────────┘        │
│                              │                           │
│              ┌───────────────▼──────────────┐            │
│              │   P2Pool Merged Mining       │            │
│              │   DOGE_VM_IP             │            │
│              │   Stratum: 7903              │            │
│              │   Web: 8000                  │            │
│              └───────────────┬──────────────┘            │
│                              │                           │
│           ┌──────────────────┴──────────────────┐       │
│           │                                      │       │
│      ┌────▼───┐  ┌────────┐  ┌────────┐        │       │
│      │ ASIC 1 │  │ ASIC 2 │  │ ASIC 3 │        │       │
│      │.237    │  │.236    │  │.238    │        │       │
│      └────────┘  └────────┘  └────────┘        │       │
│                                                 │       │
└─────────────────────────────────────────────────┘       
```

---

## 🚀 Quick Start

### Option A: Guided Setup (Recommended)
```bash
cd /home/YOUR_USER/Github/p2pool-dash
bash setup_test_infrastructure.sh
# Follow interactive menu
```

### Option B: Manual Deployment
Follow the detailed instructions in `TEST_INFRASTRUCTURE_KB.md`

### Option C: Check Status Only
```bash
# View current infrastructure (requires VMs to exist)
bash setup_test_infrastructure.sh
# Select: "Exit" or just run monitoring
```

---

## 📋 Deployment Phases

### Phase 1: VM Creation (Week 1)
- Create 3 Ubuntu 24.04 VMs in VSphere
- Network configuration
- Basic software installation
- **Duration**: 2-4 hours

### Phase 2: Testnet Synchronization (Parallel)
- Dogecoin testnet IBD (~2-4 hours)
- Litecoin testnet IBD (~1-2 hours)
- **Duration**: 4 hours (parallel)

### Phase 3: P2Pool Configuration
- Deploy P2Pool merged mining aggregator
- RPC connectivity testing
- Stratum port activation
- **Duration**: 30 minutes

### Phase 4: ASIC Miner Setup
- Configure 3 AntRouter L1 units
- Pool connection verification
- Hashrate validation
- **Duration**: 30 minutes

### Phase 5: Testing & Validation
- Connectivity tests (30 min)
- Single miner test (2 hours)
- Multi-miner load test (6+ hours)
- Block finding test (12+ hours)
- **Duration**: 20+ hours

---

## 🎯 Key Resources

### Hardware Assets
- **3x AntRouter L1** (Scrypt miners)
  - MINER_IP_1 (500 MH/s)
  - MINER_IP_2 (500 MH/s)
  - MINER_IP_3 (500 MH/s)
  - **Total**: 1.5 GH/s Scrypt

### VM Specifications
| VM | IP | CPU | RAM | Disk | Purpose |
|----|----|----|----|----|---------|
| YOUR_DOGE_HOSTNAME | DOGE_DAEMON_IP / YOUR_PUBLIC_IP_1 | 4 | 8GB | 500GB | ✅ Dogecoin testnet + auxpow + systemd (DEPLOYED) |
| ltc-testnet | LTC_DAEMON_IP / YOUR_PUBLIC_IP_2 | 4 | 8GB | 420GB | ✅ Litecoin testnet + systemd (DEPLOYED) |
- **Network**: INTERNAL_SUBNET
- **Gateway**: GATEWAY_IP
- **DNS**: 8.8.8.8, 8.8.4.4
- **Total IPs Required**: 3 for VMs (already allocated)

---

## 📊 Testing Scenarios

### Scenario 1: Basic Connectivity (30 min)
✅ All nodes reachable  
✅ RPC calls working  
✅ Stratum port accessible  

### Scenario 2: Single Miner (2 hours)
✅ 1 ASIC connected  
✅ Shares being found  
✅ Hashrate tracking accurate  

### Scenario 3: Multi-Miner Load (6+ hours)
✅ All 3 ASICs connected  
✅ Combined 1.5 GH/s achievable  
✅ No network instability  

### Scenario 4: Block Finding (12+ hours)
✅ Valid block submitted  
✅ Confirmed on blockchain  
✅ Payout recorded  

---

## 🔍 Monitoring & Validation

### Real-time Monitoring
```bash
# Full system dashboard
watch /opt/monitor_merged_mining.sh

# Individual components
watch "dogecoin-cli -datadir=/var/dogecoin getblockchaininfo | jq"
watch "litecoin-cli -datadir=/var/litecoin getblockchaininfo | jq"
curl http://DOGE_VM_IP:8000/global_stats | jq
```

### Key Metrics to Track
- ✅ Dogecoin block sync (target: ~1,178,000)
- ✅ Litecoin block sync (target: ~3,000,000)
- ✅ P2Pool hashrate (target: 1.5 GH/s)
- ✅ ASIC individual rates (target: ~500 MH/s each)
- ✅ Share acceptance rate (target: >95%)
- ✅ Block orphan rate (target: <5%)

---

## 🐛 Troubleshooting Quick Links

### Common Issues
- **VM Creation Fails**: See TEST_INFRASTRUCTURE_KB.md → VM Creation
- **Testnet IBD Stalled**: See QUICK_REFERENCE.md → Troubleshooting
- **P2Pool RPC Timeout**: See TEST_INFRASTRUCTURE_KB.md → Phase 3
- **Miners Not Connecting**: See QUICK_REFERENCE.md → ASIC Miner Commands
- **Zero Hashrate**: See DEPLOYMENT_CHECKLIST.md → Troubleshooting

---

## ✨ Success Criteria

| Item | Target | Status |
|------|--------|--------|
| VMs Created | 3/3 | ⬜ |
| Dogecoin Synced | 1,178,000 blocks | ⬜ |
| Litecoin Synced | 3,000,000+ blocks | ⬜ |
| P2Pool Running | No RPC errors | ⬜ |
| ASIC Connection | 3/3 connected | ⬜ |
| Combined Hashrate | 1.5 GH/s | ⬜ |
| Block Found | ≥1 block | ⬜ |
| All Tests Pass | 4/4 scenarios | ⬜ |

---

## 📞 Support & Documentation

### Files in This Package
- ✅ [TEST_INFRASTRUCTURE_KB.md](TEST_INFRASTRUCTURE_KB.md) - Complete infrastructure guide
- ✅ [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) - Step-by-step checklist
- ✅ [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Command reference
- ✅ [setup_test_infrastructure.sh](setup_test_infrastructure.sh) - Automated setup
- ✅ [TEST_ENVIRONMENT_SUMMARY.md](TEST_ENVIRONMENT_SUMMARY.md) - This file

### External References
- P2Pool-Dash: https://github.com/dashpay/p2pool-dash
- Dogecoin: https://github.com/dogecoin/dogecoin
- Litecoin: https://github.com/litecoin-project/litecoin

---

## 🎓 Learning Resources

### Understanding Merged Mining
- [BIP309 - Merged Mining Specification](https://github.com/bitcoin/bips/blob/master/bip-0309.mediawiki)
- [Scrypt Algorithm](https://en.wikipedia.org/wiki/Scrypt)
- [Proof of Work](https://en.wikipedia.org/wiki/Proof_of_work)

### P2Pool Specific
- [P2Pool Architecture](https://github.com/dashpay/p2pool-dash/blob/master/README.md)
- [Stratum Protocol](https://slushpool.com/stratum-mining-protocol/)
- [ASICBOOST (BIP320)](https://github.com/bitcoin/bips/blob/master/bip-0320.mediawiki)

---

## 📝 Next Steps After Deployment

1. ✅ Complete all deployment phases
2. 📊 Collect performance metrics for 24+ hours
3. 🔧 Optimize pool difficulty settings
4. 📈 Document findings and results
5. 🚀 Plan mainnet deployment strategy
6. 📁 Archive test data for analysis

---

## 📦 Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 9, 2026 | Initial release - Complete test infrastructure |

---

## 🏆 Success Story

When completed, this test environment will enable:
- ✅ Verified merged mining capability
- ✅ Production-ready P2Pool instance
- ✅ ASIC miner optimization
- ✅ Performance baseline data
- ✅ Confidence for mainnet deployment

---

**Ready to deploy? Start with: `bash setup_test_infrastructure.sh`**

*Created: January 9, 2026*  
*Maintainer: P2Pool Development Team*
