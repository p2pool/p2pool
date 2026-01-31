# P2Pool-Dash Installation Guide

Complete installation guide for P2Pool-Dash on Ubuntu/Debian systems.

## Table of Contents
- [System Requirements](#system-requirements)
- [Dash Core Installation](#dash-core-installation)
- [Python Environment Setup](#python-environment-setup)
- [P2Pool-Dash Installation](#p2pool-dash-installation)
- [Configuration](#configuration)
- [Running P2Pool](#running-p2pool)
- [Troubleshooting](#troubleshooting)

---

## System Requirements

### Minimum Requirements
- **OS**: Ubuntu 20.04+ or Debian 11+
- **CPU**: 2+ cores
- **RAM**: 4GB minimum, 8GB recommended
- **Disk**: 50GB+ (for Dash blockchain)
- **Network**: Stable internet connection

### Required Ports
- **9999**: Dash P2P (incoming connections)
- **9998**: Dash RPC (localhost only)
- **7903**: P2Pool Stratum (for miners)
- **8999**: P2Pool P2P (for peer connections)

---

## Dash Core Installation

### 1. Install Dependencies
```bash
sudo apt-get update
sudo apt-get install -y build-essential libtool autotools-dev automake pkg-config \
    bsdmainutils python3 libssl-dev libevent-dev libboost-system-dev \
    libboost-filesystem-dev libboost-chrono-dev libboost-test-dev \
    libboost-thread-dev libminiupnpc-dev libzmq3-dev libqt5gui5 \
    libqt5core5a libqt5dbus5 qttools5-dev qttools5-dev-tools git
```

### 2. Clone and Build Dash Core
```bash
cd ~
git clone https://github.com/dashpay/dash.git
cd dash

# Checkout latest stable version (v23.0.2 or newer)
git checkout v23.0.2

# Build
./autogen.sh
./configure --without-gui --disable-tests --disable-bench
make -j$(nproc)
sudo make install
```

### 3. Configure Dash Core
Create `~/.dashcore/dash.conf`:
```bash
mkdir -p ~/.dashcore
cat > ~/.dashcore/dash.conf << EOF
server=1
daemon=1
rpcuser=dashrpc
rpcpassword=$(openssl rand -hex 32)
rpcallowip=127.0.0.1
txindex=1
addressindex=1
timestampindex=1
spentindex=1
EOF
```

### 4. Start Dash Core and Sync
```bash
dashd

# Monitor sync progress
dash-cli getblockchaininfo

# Wait until "blocks" equals "headers" (may take several hours)
```

---

## Python Environment Setup

### Problem: Python 2 is End-of-Life
P2Pool-Dash requires Python 2.7, which is no longer available in modern Ubuntu/Debian distributions. We'll use PyPy as a solution.

### 1. Install PyPy (Python 2.7 Alternative)
```bash
# Install PyPy via snap (recommended)
sudo snap install pypy --classic

# Verify installation
pypy --version
# Should show: Python 2.7.18
```

### 2. Install Python Dependencies

#### Install pip for PyPy
```bash
cd /tmp
wget https://bootstrap.pypa.io/pip/2.7/get-pip.py
pypy get-pip.py
```

#### Install Required Packages
```bash
# Core dependencies
pypy -m pip install twisted==19.10.0
pypy -m pip install pycryptodome

# Optional: For web interface
pypy -m pip install pyasn1 pyasn1-modules service_identity
```

### 3. Handle OpenSSL Import Warnings

**Problem**: You may see `ImportError: No module named OpenSSL` warnings in logs.

**Solution**: These are non-fatal warnings from Twisted trying to import SSL for HTTPS. If they bother you:

```bash
# Option 1: Install pyOpenSSL (may cause issues with snap PyPy)
pypy -m pip install pyOpenSSL

# Option 2: Ignore the warnings (recommended)
# They don't affect P2Pool functionality for local mining
```

**Note**: If you get glibc compatibility errors with snap PyPy, use Option 2 and ignore the warnings.

---

## P2Pool-Dash Installation

### 1. Clone P2Pool-Dash Repository
```bash
cd ~
git clone https://github.com/dashpay/p2pool-dash.git
cd p2pool-dash
```

### 2. Initialize and Build dash_hash Submodule

**Critical**: The `dash_hash` module provides X11 hashing and must be compiled.

```bash
# Initialize submodule
git submodule init
git submodule update

# Build dash_hash
cd dash_hash
pypy setup.py install --user

# Verify installation
pypy -c "import dash_hash; print('dash_hash OK')"
```

**Troubleshooting dash_hash**:
```bash
# If build fails, install build dependencies
sudo apt-get install -y python-dev libssl-dev

# If using PyPy and get errors, try:
cd dash_hash
pypy setup.py build
pypy setup.py install --user --prefix=
```

---

## Configuration

### Network Modes

P2Pool-Dash can run in two modes:

#### 1. Standalone Mode (Testing/Solo Mining)
Edit `p2pool/networks/dash.py`:
```python
PERSIST = False
```

**Pros**: 
- No peers required
- Works immediately
- Good for testing

**Cons**:
- No share chain benefits
- Mining alone (higher variance)

#### 2. Multi-Node Mode (Production/Pool Mining)
Edit `p2pool/networks/dash.py`:
```python
PERSIST = True
```

**Pros**:
- Part of P2Pool share chain
- Lower variance
- Collaborative mining

**Cons**:
- Requires peer connections
- Must sync P2Pool share chain

### Bootstrap Nodes

Current active bootstrap nodes in `p2pool/networks/dash.py`:
```python
BOOTSTRAP_ADDRS = 'dash01.p2poolmining.us dash02.p2poolmining.us dash03.p2poolmining.us crypto.office-on-the.net dash04.p2poolmining.us'.split(' ')
```

**Note**: The node `p2pool.2sar.ru` has been removed as it's no longer active.

### Generate Mining Address

```bash
# Create new wallet
dash-cli createwallet "mining"

# Get new address
dash-cli getnewaddress "mining"
# Example output: XdgF55wEHBRWwbuBniNYH4GvvaoYMgL84u
```

---

## Running P2Pool

### Start P2Pool-Dash

```bash
cd ~/p2pool-dash

# For Dash mainnet
pypy run_p2pool.py \
    --net dash \
    --dashd-address 127.0.0.1 \
    --dashd-rpc-port 9998 \
    -a YOUR_DASH_ADDRESS

# For Dash testnet
pypy run_p2pool.py \
    --net dash_testnet \
    --dashd-address 127.0.0.1 \
    --dashd-rpc-port 19998 \
    -a YOUR_DASH_TESTNET_ADDRESS
```

### Run as Background Service

```bash
# Start in background
cd ~/p2pool-dash
nohup pypy run_p2pool.py \
    --net dash \
    --dashd-address 127.0.0.1 \
    --dashd-rpc-port 9998 \
    -a YOUR_DASH_ADDRESS \
    > p2pool.log 2>&1 &

# Monitor logs
tail -f p2pool.log

# Stop P2Pool
pkill -f "pypy.*run_p2pool"
```

### Create Systemd Service (Optional)

Create `/etc/systemd/system/p2pool-dash.service`:
```ini
[Unit]
Description=P2Pool-Dash
After=dashd.service
Requires=dashd.service

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/p2pool-dash
ExecStart=/snap/bin/pypy /home/YOUR_USERNAME/p2pool-dash/run_p2pool.py \
    --net dash \
    --dashd-address 127.0.0.1 \
    --dashd-rpc-port 9998 \
    -a YOUR_DASH_ADDRESS
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable p2pool-dash
sudo systemctl start p2pool-dash
sudo systemctl status p2pool-dash
```

---

## Mining to P2Pool

### Point Your Miner to P2Pool

**Stratum URL**: `stratum+tcp://YOUR_IP:7903`

Example with cpuminer-multi:
```bash
# Install cpuminer-multi
cd ~
git clone https://github.com/tpruvot/cpuminer-multi.git
cd cpuminer-multi
./build.sh

# Mine with limited threads (reduce CPU heat)
./cpuminer -t 4 \
    -a x11 \
    -o stratum+tcp://127.0.0.1:7903 \
    -u YOUR_DASH_ADDRESS \
    -p x
```

### Monitor P2Pool

```bash
# View web interface
# Open browser: http://YOUR_IP:7903/

# Check logs
tail -f ~/p2pool-dash/p2pool.log

# Monitor shares
# P2Pool will show:
# "P2Pool: X shares in chain (Y verified/Z total) Peers: N"
# "Local: XXX kH/s in last N seconds"
```

---

## Troubleshooting

### Common Issues

#### 1. ImportError: No module named dash_hash
```bash
# Rebuild dash_hash
cd ~/p2pool-dash/dash_hash
pypy setup.py install --user
```

#### 2. AttributeError: 'module' object has no attribute 'ComposedWithContextualOptionalsType'
This means you have an old version. Update to latest:
```bash
cd ~/p2pool-dash
git pull
git log --oneline -1
# Should show commit e9b5f57 or newer
```

#### 3. ValueError: {'code': -5, 'message': 'Block not found'}
This was fixed in commit e9b5f57. Update your installation:
```bash
cd ~/p2pool-dash
git pull
```

#### 4. ImportError: No module named bitcoin
Fixed in latest version. Update:
```bash
cd ~/p2pool-dash
git pull
```

#### 5. exceptions.ValueError: none_value used
Fixed in latest version (commit e9b5f57). Update:
```bash
cd ~/p2pool-dash
git pull
```

#### 6. "p2pool is not connected to any peers" (FIXED - no longer blocks work)

**Fixed in latest version**: P2Pool no longer requires peer connections to generate work.

```bash
# Old behavior (before fix): Work was blocked when PERSIST=True and no peers
# New behavior (after fix): P2Pool works standalone even with PERSIST=True

# You can now mine solo while still accepting incoming peer connections
# No need to set PERSIST=False anymore
```

#### 7. PyPy Cache Issues
After code changes, clear bytecode cache:
```bash
cd ~/p2pool-dash
find . -name "*.pyc" -delete
rm -rf __pycache__ */__pycache__ */*/__pycache__
```

#### 8. High CPU Usage / Overheating
Limit miner threads:
```bash
# Use -t flag to limit threads (e.g., 4 threads)
./cpuminer -t 4 -a x11 -o stratum+tcp://127.0.0.1:7903 -u ADDRESS -p x
```

#### 9. Stratum Connection Refused
```bash
# Check P2Pool is running
ps aux | grep pypy

# Check port is listening
ss -tuln | grep 7903

# Check firewall
sudo ufw allow 7903/tcp
```

### Log Analysis

```bash
# Check for errors
grep -i error ~/p2pool-dash/p2pool.log

# Check worker connections
grep "New work for worker" ~/p2pool-dash/p2pool.log

# Check share submissions
grep "GOT SHARE" ~/p2pool-dash/p2pool.log

# Monitor in real-time
tail -f ~/p2pool-dash/p2pool.log | grep -E "(shares|Local:|Peers:)"
```

---

## Performance Tuning

### Dash Core Optimizations

Add to `~/.dashcore/dash.conf`:
```ini
# Increase database cache (adjust based on available RAM)
dbcache=2000

# Increase max connections
maxconnections=125

# Optimize for SSD
disablewallet=0
```

### P2Pool Optimizations

```bash
# Increase worker difficulty for high hashrate miners
# Edit p2pool/networks/dash.py:
# SHARE_PERIOD = 20  # Lower = more frequent shares
```

### System Optimizations

```bash
# Increase file descriptor limits
echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf

# Optimize network
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216
```

---

## Updating P2Pool-Dash

```bash
cd ~/p2pool-dash

# Stop P2Pool
pkill -f "pypy.*run_p2pool"

# Update code
git pull

# Update submodules
git submodule update

# Rebuild dash_hash if updated
cd dash_hash
pypy setup.py install --user
cd ..

# Clear cache
find . -name "*.pyc" -delete

# Restart P2Pool
pypy run_p2pool.py --net dash --dashd-address 127.0.0.1 --dashd-rpc-port 9998 -a YOUR_ADDRESS
```

---

## Security Considerations

1. **Firewall Configuration**:
```bash
sudo ufw allow 9999/tcp   # Dash P2P
sudo ufw allow 8999/tcp   # P2Pool P2P
sudo ufw allow 7903/tcp   # Stratum (if mining remotely)
sudo ufw enable
```

2. **Dash RPC Security**:
   - Keep RPC on localhost only
   - Use strong random password
   - Never expose port 9998 to internet

3. **P2Pool Security**:
   - Keep software updated
   - Monitor logs for suspicious activity
   - Use fail2ban for stratum port if publicly exposed

---

## Getting Help

- **GitHub Issues**: https://github.com/dashpay/p2pool-dash/issues
- **Dash Forum**: https://www.dash.org/forum/
- **Discord**: https://discord.gg/dash

---

## Credits

- P2Pool original: forrestv
- P2Pool-Dash port: dashpay team
- Bug fixes and improvements: Community contributors

## License

See LICENSE file in repository.
