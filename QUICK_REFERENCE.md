# P2Pool Merged Mining - Quick Reference Commands

## ⚠️ Important: ASICBOOST & Scrypt

**ASICBOOST (BIP320 version-rolling) is implemented in P2Pool core but NOT supported by Scrypt algorithm.**

This test environment uses **Scrypt coins (Dogecoin + Litecoin)** which feature:
- ✅ Vardiff (automatic difficulty adjustment)
- ✅ Extranonce dual protocol (BIP310 + NiceHash)
- ❌ ASICBOOST (N/A for Scrypt; designed for SHA256/X11)

---

## Network Overview
```
Dogecoin Testnet (auxpow)  → 192.168.86.27 / 10.1.1.129 (RPC: 44555)
Litecoin Testnet           → 192.168.86.26 / 10.1.1.145 (RPC: 18332)
P2Pool Aggregator          → 192.168.86.247 (Stratum: 7903)
External IP                → 102.115.4.171
ASIC Miner 1               → 192.168.86.237
ASIC Miner 2               → 192.168.86.236
ASIC Miner 3               → 192.168.86.238
```

---

## VM Access

### SSH into VMs
```bash
# Dogecoin testnet (doge-testnet-auxpow)
ssh user0@192.168.86.27

# Litecoin testnet (ltc-testnet)
ssh user0@192.168.86.26

# P2Pool node
ssh user0@192.168.86.247
```

---

## Node Configuration

### Dogecoin Testnet (192.168.86.27)
- **Hostname**: doge-testnet-auxpow
- **RPC Port**: 44555 (testnet)
- **P2P Port**: 44556
- **RPC User**: dogeuser
- **RPC Password**: dogepass123secure
- **External IP**: 102.115.4.171:44556
- **Service**: systemd (dogecoind.service) - enabled
- **Binary**: /home/user0/dogecoin-1.14.8/bin/dogecoind
- **Config**: ~/.dogecoin/dogecoin.conf

### Litecoin Testnet (192.168.86.26)
- **Hostname**: ltc-testnet
- **RPC Port**: 18332 (testnet)
- **P2P Port**: 18333
- **RPC User**: litecoinrpc
- **RPC Password**: litecoinrpc_testnet_1767955680
- **External IP**: 102.115.4.171:18333
- **Service**: systemd (litecoind.service) - enabled
- **Binary**: /home/user0/.local/bin/litecoind
- **Config**: ~/.litecoin/litecoin.conf

---

## Dogecoin Testnet Commands

### Node Status & Monitoring
```bash
# Get blockchain info
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getblockchaininfo

# Get network info
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getnetworkinfo

# Count connected peers
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getpeerinfo | jq length

# Get block count
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getblockcount

# Monitor sync progress (real-time)
watch "dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getblockchaininfo | jq '{blocks, headers, progress: .verificationprogress}'"

# Check auxpow support
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure help getauxblock | head -10

# Test AuxPoW API
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getauxblock
```

### Wallet Operations
```bash
# Get new address
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getnewaddress

# Get address balance
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getbalance

# Validate address
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure validateaddress YOUR_ADDRESS

# Get received by address
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getreceivedbyaddress YOUR_ADDRESS
```

### Mining Related
```bash
# Get mining info
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getmininginfo

# Get block template
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getblocktemplate

# Get auxblock (for merged mining)
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=dogepass123secure getauxblock
```

### Service Management
```bash
# Check service status
sudo systemctl status dogecoind.service

# Start/Stop/Restart service
sudo systemctl start dogecoind.service
sudo systemctl stop dogecoind.service
sudo systemctl restart dogecoind.service

# View logs
sudo journalctl -u dogecoind.service -f
tail -f ~/.dogecoin/testnet3/debug.log
```

### Peer Management
```bash
# List all peers
dogecoin-cli -datadir=/var/dogecoin getpeerinfo

# Add node manually
dogecoin-cli -datadir=/var/dogecoin addnode "IP:PORT" "add"

# Remove node
dogecoin-cli -datadir=/var/dogecoin addnode "IP:PORT" "remove"
```

### Service Management
```bash
# Start daemon
dogecoind -datadir=/var/dogecoin

# Systemd status
sudo systemctl status dogecoind

# View logs
sudo journalctl -u dogecoind -f

# Restart service
sudo systemctl restart dogecoind

# Stop daemon
dogecoin-cli -datadir=/var/dogecoin stop
```

---

## Litecoin Testnet Commands

### Node Status & Monitoring
```bash
# Get blockchain info
litecoin-cli -datadir=/var/litecoin getblockchaininfo

# Monitor sync progress
watch "litecoin-cli -datadir=/var/litecoin getblockchaininfo | jq '{blocks, headers, progress: (.blocks/.headers*100|round)}'"

# Get network peers
litecoin-cli -datadir=/var/litecoin getpeerinfo | jq length
```

### Wallet Operations
```bash
# Get new address
litecoin-cli -datadir=/var/litecoin getnewaddress

# Get balance
litecoin-cli -datadir=/var/litecoin getbalance
```

### Mining Related
```bash
# Get mining info
litecoin-cli -datadir=/var/litecoin getmininginfo

# Get block template
litecoin-cli -datadir=/var/litecoin getblocktemplate
```

### Service Management
```bash
# Systemd status
sudo systemctl status litecoind

# View logs
sudo journalctl -u litecoind -f

# Restart service
sudo systemctl restart litecoind
```

---

## P2Pool Merged Mining Commands

### P2Pool Control
```bash
# Start P2Pool
cd /opt/p2pool-merged
screen -S p2pool -d -m bash run_merged_mining.sh

# Attach to screen session
screen -S p2pool -r

# Detach from session
# (Press Ctrl+A then D)

# Stop P2Pool
screen -S p2pool -X quit

# View logs
tail -f /var/log/p2pool-merged.log

# Search for specific events
grep "share\|block\|error" /var/log/p2pool-merged.log | tail -20
```

### Connectivity Testing
```bash
# Test RPC connection to Dogecoin
curl -s -u dogetest:DogeTestPass123! \
  -d '{"jsonrpc":"1.0","id":"test","method":"getblockcount"}' \
  http://192.168.86.24:18332

# Test RPC connection to Litecoin
curl -s -u ltctest:LtcTestPass123! \
  -d '{"jsonrpc":"1.0","id":"test","method":"getblockcount"}' \
  http://192.168.86.246:18332

# Test Stratum port
nc -zv 192.168.86.247 7903

# Test P2Pool web UI
curl http://192.168.86.247:8000/global_stats | jq '.pool'
```

### P2Pool Monitoring
```bash
# Get global stats
curl http://192.168.86.247:8000/global_stats | jq

# Get connected miners
curl http://192.168.86.247:8000/miners_list | jq

# Get worker stats
curl http://192.168.86.247:8000/worker_stats | jq

# Access web dashboard
firefox http://192.168.86.247:8000 &
```

---

## ASIC Miner Commands

### Web UI Access
```
ASIC 1: http://192.168.86.237:8081
ASIC 2: http://192.168.86.236:8081
ASIC 3: http://192.168.86.238:8081
```

### CGMiner API (SSH)
```bash
# SSH to miner
ssh admin@192.168.86.237

# Check miner summary
curl http://127.0.0.1:4028/api | jq '.SUMMARY'

# Check miner stats
curl http://127.0.0.1:4028/api | jq '.STATS'

# Monitor hash rate (real-time)
watch 'curl http://127.0.0.1:4028/api | jq ".SUMMARY[0] | {MHS5s, MHSAV, GETWORKS, ACCEPTED, REJECTED}"'

# Check device info
curl http://127.0.0.1:4028/api | jq '.DEVS'
```

### Configure Pool (via SSH)
```bash
# List running processes
ps aux | grep cgminer

# Kill current miner
killall cgminer

# Start new miner instance
cgminer --scrypt -o stratum+tcp://192.168.86.247:7903 \
  -u WALLET_ADDRESS -p x --api-listen --api-port 4028

# Run in background
nohup cgminer --scrypt -o stratum+tcp://192.168.86.247:7903 \
  -u WALLET_ADDRESS -p x --api-listen --api-port 4028 > /tmp/cgminer.log 2>&1 &
```

---

## Monitoring & Health Checks

### Full System Status
```bash
#!/bin/bash
echo "=== Dogecoin Testnet ==="
dogecoin-cli -datadir=/var/dogecoin getblockchaininfo | jq '{blocks, peers: (.connections//"?")}'

echo "=== Litecoin Testnet ==="
litecoin-cli -datadir=/var/litecoin getblockchaininfo | jq '{blocks, peers: (.connections//"?")}'

echo "=== P2Pool ==="
curl -s http://192.168.86.247:8000/global_stats | jq '.pool | {hashrate, miners}'

echo "=== ASIC Miners ==="
for ip in 192.168.86.237 192.168.86.236 192.168.86.238; do
  curl -s http://$ip:4028/api 2>/dev/null | jq ".SUMMARY[0] | {ip: \"$ip\", mhs: .MHS5s}" || echo "{ip: $ip, status: offline}"
done
```

### Network Connectivity Check
```bash
# Ping all nodes
for ip in 192.168.86.24 192.168.86.246 192.168.86.247 192.168.86.237 192.168.86.236 192.168.86.238; do
  ping -c 1 -W 2 $ip && echo "$ip OK" || echo "$ip OFFLINE"
done
```

### Port Availability Check
```bash
# Check if ports are listening
echo "Checking Dogecoin RPC (18332)..."
nc -zv 192.168.86.24 18332

echo "Checking Litecoin RPC (18332)..."
nc -zv 192.168.86.246 18332

echo "Checking P2Pool Stratum (7903)..."
nc -zv 192.168.86.247 7903

echo "Checking P2Pool Web (8000)..."
nc -zv 192.168.86.247 8000
```

---

## Log Monitoring

### Real-time Log Tailing
```bash
# P2Pool logs
ssh user@192.168.86.247 "tail -f /var/log/p2pool-merged.log"

# Dogecoin logs
ssh user@192.168.86.245 "tail -f /var/dogecoin/testnet3/debug.log"

# Litecoin logs
ssh user@192.168.86.246 "tail -f /var/litecoin/testnet4/debug.log"
```

### Search for Errors
```bash
# Find all errors in P2Pool log
grep -i error /var/log/p2pool-merged.log | tail -20

# Find all rejected shares
grep -i rejected /var/log/p2pool-merged.log | tail -20

# Find all found blocks
grep -i "block found\|accepted block" /var/log/p2pool-merged.log
```

---

## Troubleshooting Commands

### Test RPC Connectivity
```bash
# Test Dogecoin RPC
python3 << 'EOF'
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('192.168.86.245', 18332))
    print("Dogecoin RPC: REACHABLE")
    s.close()
except Exception as e:
    print(f"Dogecoin RPC: ERROR - {e}")
EOF

# Alternative using curl
curl -v telnet://192.168.86.245:18332
```

### Check Firewall Rules
```bash
# SSH to P2Pool node
ssh user@192.168.86.247

# List firewall rules
sudo ufw status verbose

# Allow Stratum port
sudo ufw allow 7903/tcp

# Allow P2Pool web UI
sudo ufw allow 8000/tcp
```

### Test Stratum Connection
```bash
# Connect to Stratum and test
python3 << 'EOF'
import socket

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('192.168.86.247', 7903))
s.send(b'{"id": 1, "method": "mining.subscribe", "params": []}\n')
print(s.recv(1024).decode())
s.close()
EOF
```

---

## Performance Metrics Collection

### Collect Hourly Stats
```bash
#!/bin/bash
# Save to CSV for analysis

LOG_FILE="/tmp/merged_mining_stats.csv"

# Header
echo "timestamp,doge_blocks,ltc_blocks,p2pool_miners,total_mhs" > $LOG_FILE

# Collect every hour
while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    DOGE_BLOCKS=$(dogecoin-cli -datadir=/var/dogecoin getblockcount 2>/dev/null || echo "ERROR")
    LTC_BLOCKS=$(litecoin-cli -datadir=/var/litecoin getblockcount 2>/dev/null || echo "ERROR")
    MINERS=$(curl -s http://192.168.86.247:8000/miners_list 2>/dev/null | jq 'length' || echo "0")
    MHS=$(curl -s http://192.168.86.247:8000/global_stats 2>/dev/null | jq '.pool.hashrate' || echo "0")
    
    echo "$TIMESTAMP,$DOGE_BLOCKS,$LTC_BLOCKS,$MINERS,$MHS" >> $LOG_FILE
    
    sleep 3600
done
```

---

## Useful Aliases (Add to ~/.bashrc)

```bash
# Dogecoin shortcuts
alias doge-cli='dogecoin-cli -datadir=/var/dogecoin'
alias doge-info='doge-cli getblockchaininfo | jq "{blocks, headers, synced: (.blocks == .headers)}"'
alias doge-peers='doge-cli getpeerinfo | jq length'

# Litecoin shortcuts
alias ltc-cli='litecoin-cli -datadir=/var/litecoin'
alias ltc-info='ltc-cli getblockchaininfo | jq "{blocks, headers, synced: (.blocks == .headers)}"'
alias ltc-peers='ltc-cli getpeerinfo | jq length'

# P2Pool shortcuts
alias p2pool-stats='curl -s http://192.168.86.247:8000/global_stats | jq ".pool"'
alias p2pool-miners='curl -s http://192.168.86.247:8000/miners_list | jq'
alias p2pool-logs='tail -f /var/log/p2pool-merged.log'

# ASIC monitoring
alias asics='for ip in 192.168.86.237 192.168.86.236 192.168.86.238; do echo "$ip:"; curl -s http://$ip:4028/api | jq ".SUMMARY[0] | {mhs: .MHS5s, accepted: .ACCEPTED, rejected: .REJECTED}"; done'
```

---

## Emergency Commands

### Kill P2Pool (if needed)
```bash
screen -S p2pool -X quit
# OR
pkill -f "p2pool"
# OR
sudo systemctl stop p2pool-merged
```

### Restart All Services
```bash
# Restart Dogecoin
sudo systemctl restart dogecoind

# Restart Litecoin
sudo systemctl restart litecoind

# Restart P2Pool
screen -S p2pool -X quit
sleep 2
screen -S p2pool -d -m bash /opt/p2pool-merged/run_merged_mining.sh
```

### Clear P2Pool Cache (if needed)
```bash
cd /opt/p2pool-merged
rm -rf data/*.pickle
# Restart P2Pool
```

### Tail All Logs Simultaneously
```bash
# In separate terminals
ssh user@192.168.86.245 "tail -f /var/dogecoin/testnet3/debug.log"
ssh user@192.168.86.246 "tail -f /var/litecoin/testnet4/debug.log"
ssh user@192.168.86.247 "tail -f /var/log/p2pool-merged.log"
```

---

## Useful Web Dashboards

| Service | URL | Purpose |
|---------|-----|---------|
| P2Pool | http://192.168.86.247:8000 | Pool dashboard |
| P2Pool Stats API | http://192.168.86.247:8000/global_stats | JSON stats |
| P2Pool Miners | http://192.168.86.247:8000/miners_list | Connected miners |
| ASIC 1 Web | http://192.168.86.237:8081 | Miner control |
| ASIC 2 Web | http://192.168.86.236:8081 | Miner control |
| ASIC 3 Web | http://192.168.86.238:8081 | Miner control |

---

## Reference Documentation Links

- **P2Pool-Dash**: https://github.com/dashpay/p2pool-dash
- **Dogecoin**: https://github.com/dogecoin/dogecoin
- **Litecoin**: https://github.com/litecoin-project/litecoin
- **Test Infrastructure KB**: `TEST_INFRASTRUCTURE_KB.md`
- **Deployment Checklist**: `DEPLOYMENT_CHECKLIST.md`

---

*Last Updated: January 9, 2026*
