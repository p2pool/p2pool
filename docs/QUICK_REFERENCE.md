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
Dogecoin Testnet (auxpow)  → DOGE_DAEMON_IP / YOUR_PUBLIC_IP_1 (RPC: 44555)
Litecoin Testnet           → LTC_DAEMON_IP / YOUR_PUBLIC_IP_2 (RPC: 18332)
P2Pool Aggregator          → DOGE_VM_IP (Stratum: 7903)
External IP                → YOUR_PUBLIC_IP
ASIC Miner 1               → MINER_IP_1
ASIC Miner 2               → MINER_IP_2
ASIC Miner 3               → MINER_IP_3
```

---

## VM Access

### SSH into VMs
```bash
# Dogecoin testnet (YOUR_DOGE_HOSTNAME)
ssh YOUR_USER@DOGE_DAEMON_IP

# Litecoin testnet (YOUR_LTC_HOSTNAME)
ssh YOUR_USER@LTC_DAEMON_IP

# P2Pool node
ssh YOUR_USER@DOGE_VM_IP
```

---

## Node Configuration

### Dogecoin Testnet (DOGE_DAEMON_IP)
- **Hostname**: YOUR_DOGE_HOSTNAME
- **RPC Port**: 44555 (testnet)
- **P2P Port**: 44556
- **RPC User**: dogeuser
- **RPC Password**: YOUR_DOGE_RPC_PASSWORD
- **External IP**: YOUR_PUBLIC_IP:44556
- **Service**: systemd (dogecoind.service) - enabled
- **Binary**: /home/YOUR_USER/dogecoin-1.14.8/bin/dogecoind
- **Config**: ~/.dogecoin/dogecoin.conf

### Litecoin Testnet (LTC_DAEMON_IP)
- **Hostname**: YOUR_LTC_HOSTNAME
- **RPC Port**: 18332 (testnet)
- **P2P Port**: 18333
- **RPC User**: litecoinrpc
- **RPC Password**: YOUR_LTC_RPC_PASSWORD
- **External IP**: YOUR_PUBLIC_IP:18333
- **Service**: systemd (litecoind.service) - enabled
- **Binary**: /home/YOUR_USER/.local/bin/litecoind
- **Config**: ~/.litecoin/litecoin.conf

---

## Dogecoin Testnet Commands

### Node Status & Monitoring
```bash
# Get blockchain info
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getblockchaininfo

# Get network info
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getnetworkinfo

# Count connected peers
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getpeerinfo | jq length

# Get block count
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getblockcount

# Monitor sync progress (real-time)
watch "dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getblockchaininfo | jq '{blocks, headers, progress: .verificationprogress}'"

# Check auxpow support
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD help getauxblock | head -10

# Test AuxPoW API
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getauxblock
```

### Wallet Operations
```bash
# Get new address
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getnewaddress

# Get address balance
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getbalance

# Validate address
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD validateaddress YOUR_ADDRESS

# Get received by address
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getreceivedbyaddress YOUR_ADDRESS
```

### Mining Related
```bash
# Get mining info
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getmininginfo

# Get block template
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getblocktemplate

# Get auxblock (for merged mining)
dogecoin-cli -testnet -rpcuser=dogeuser -rpcpassword=YOUR_DOGE_RPC_PASSWORD getauxblock
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
  http://P2POOL_NODE_IP:18332

# Test RPC connection to Litecoin
curl -s -u ltctest:LtcTestPass123! \
  -d '{"jsonrpc":"1.0","id":"test","method":"getblockcount"}' \
  http://LTC_VM_IP:18332

# Test Stratum port
nc -zv DOGE_VM_IP 7903

# Test P2Pool web UI
curl http://DOGE_VM_IP:8000/global_stats | jq '.pool'
```

### P2Pool Monitoring
```bash
# Get global stats
curl http://DOGE_VM_IP:8000/global_stats | jq

# Get connected miners
curl http://DOGE_VM_IP:8000/miners_list | jq

# Get worker stats
curl http://DOGE_VM_IP:8000/worker_stats | jq

# Access web dashboard
firefox http://DOGE_VM_IP:8000 &
```

---

## ASIC Miner Commands

### Web UI Access
```
ASIC 1: http://MINER_IP_1:8081
ASIC 2: http://MINER_IP_2:8081
ASIC 3: http://MINER_IP_3:8081
```

### CGMiner API (SSH)
```bash
# SSH to miner
ssh admin@MINER_IP_1

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
cgminer --scrypt -o stratum+tcp://DOGE_VM_IP:7903 \
  -u WALLET_ADDRESS -p x --api-listen --api-port 4028

# Run in background
nohup cgminer --scrypt -o stratum+tcp://DOGE_VM_IP:7903 \
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
curl -s http://DOGE_VM_IP:8000/global_stats | jq '.pool | {hashrate, miners}'

echo "=== ASIC Miners ==="
for ip in MINER_IP_1 MINER_IP_2 MINER_IP_3; do
  curl -s http://$ip:4028/api 2>/dev/null | jq ".SUMMARY[0] | {ip: \"$ip\", mhs: .MHS5s}" || echo "{ip: $ip, status: offline}"
done
```

### Network Connectivity Check
```bash
# Ping all nodes
for ip in P2POOL_NODE_IP LTC_VM_IP DOGE_VM_IP MINER_IP_1 MINER_IP_2 MINER_IP_3; do
  ping -c 1 -W 2 $ip && echo "$ip OK" || echo "$ip OFFLINE"
done
```

### Port Availability Check
```bash
# Check if ports are listening
echo "Checking Dogecoin RPC (18332)..."
nc -zv P2POOL_NODE_IP 18332

echo "Checking Litecoin RPC (18332)..."
nc -zv LTC_VM_IP 18332

echo "Checking P2Pool Stratum (7903)..."
nc -zv DOGE_VM_IP 7903

echo "Checking P2Pool Web (8000)..."
nc -zv DOGE_VM_IP 8000
```

---

## Log Monitoring

### Real-time Log Tailing
```bash
# P2Pool logs
ssh user@DOGE_VM_IP "tail -f /var/log/p2pool-merged.log"

# Dogecoin logs
ssh user@P2POOL_VM_IP "tail -f /var/dogecoin/testnet3/debug.log"

# Litecoin logs
ssh user@LTC_VM_IP "tail -f /var/litecoin/testnet4/debug.log"
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
    s.connect(('P2POOL_VM_IP', 18332))
    print("Dogecoin RPC: REACHABLE")
    s.close()
except Exception as e:
    print(f"Dogecoin RPC: ERROR - {e}")
EOF

# Alternative using curl
curl -v telnet://P2POOL_VM_IP:18332
```

### Check Firewall Rules
```bash
# SSH to P2Pool node
ssh user@DOGE_VM_IP

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
s.connect(('DOGE_VM_IP', 7903))
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
    MINERS=$(curl -s http://DOGE_VM_IP:8000/miners_list 2>/dev/null | jq 'length' || echo "0")
    MHS=$(curl -s http://DOGE_VM_IP:8000/global_stats 2>/dev/null | jq '.pool.hashrate' || echo "0")
    
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
alias p2pool-stats='curl -s http://DOGE_VM_IP:8000/global_stats | jq ".pool"'
alias p2pool-miners='curl -s http://DOGE_VM_IP:8000/miners_list | jq'
alias p2pool-logs='tail -f /var/log/p2pool-merged.log'

# ASIC monitoring
alias asics='for ip in MINER_IP_1 MINER_IP_2 MINER_IP_3; do echo "$ip:"; curl -s http://$ip:4028/api | jq ".SUMMARY[0] | {mhs: .MHS5s, accepted: .ACCEPTED, rejected: .REJECTED}"; done'
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
ssh user@P2POOL_VM_IP "tail -f /var/dogecoin/testnet3/debug.log"
ssh user@LTC_VM_IP "tail -f /var/litecoin/testnet4/debug.log"
ssh user@DOGE_VM_IP "tail -f /var/log/p2pool-merged.log"
```

---

## Useful Web Dashboards

| Service | URL | Purpose |
|---------|-----|---------|
| P2Pool | http://DOGE_VM_IP:8000 | Pool dashboard |
| P2Pool Stats API | http://DOGE_VM_IP:8000/global_stats | JSON stats |
| P2Pool Miners | http://DOGE_VM_IP:8000/miners_list | Connected miners |
| ASIC 1 Web | http://MINER_IP_1:8081 | Miner control |
| ASIC 2 Web | http://MINER_IP_2:8081 | Miner control |
| ASIC 3 Web | http://MINER_IP_3:8081 | Miner control |

---

## Reference Documentation Links

- **P2Pool-Dash**: https://github.com/dashpay/p2pool-dash
- **Dogecoin**: https://github.com/dogecoin/dogecoin
- **Litecoin**: https://github.com/litecoin-project/litecoin
- **Test Infrastructure KB**: `TEST_INFRASTRUCTURE_KB.md`
- **Deployment Checklist**: `DEPLOYMENT_CHECKLIST.md`

---

*Last Updated: January 9, 2026*
