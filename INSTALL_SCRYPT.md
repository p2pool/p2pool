# P2Pool Scrypt Installation Guide (Litecoin + Dogecoin)

Complete guide for installing P2Pool with Scrypt support for Litecoin and Dogecoin merged mining on Ubuntu 24.04+.

## Prerequisites

- Ubuntu 24.04 or later
- Synced Litecoin Core node (testnet or mainnet)
- Synced Dogecoin Core node (testnet or mainnet) - for merged mining
- Minimum 4 GB RAM
- 20+ GB free disk space

## Step 1: Install System Dependencies

```bash
# Update package lists
sudo apt-get update

# Install build tools and development libraries
sudo apt-get install -y \
    build-essential \
    python3-dev \
    git \
    libssl-dev \
    zlib1g-dev
```

## Step 2: Install PyPy (Python 2.7 JIT Compiler)

P2Pool requires PyPy for optimal performance. Install via snap:

```bash
# Install PyPy 2.7 via snap
sudo snap install pypy --classic

# Verify installation
pypy --version
# Expected: Python 2.7.18 (PyPy 7.3.20)
```

## Step 3: Install PyPy Dependencies

### Install pip for PyPy

```bash
pypy -m ensurepip
```

### Install typing module (required by Twisted)

```bash
pypy -m pip install --user typing
```

### Install Twisted (networking framework)

```bash
pypy -m pip install --user 'Twisted<21' argparse
```

### Workaround: pyOpenSSL Installation Issue

On Ubuntu 24.04+ with OpenSSL 3.0, pyOpenSSL cannot be compiled for Python 2.7 due to API incompatibilities. **This is expected and will not affect P2Pool functionality** for local mining operations.

**What works without pyOpenSSL:**
- ✓ Mining operations
- ✓ Share chain
- ✓ HTTP web interface
- ✓ RPC communication with blockchain nodes
- ✓ Peer-to-peer connectivity

**What requires pyOpenSSL (optional features):**
- ✗ HTTPS web interface (use HTTP instead)
- ✗ SSL-encrypted RPC (not needed for local nodes)

**If you absolutely need pyOpenSSL**, you have two options:

**Option A: Use Ubuntu 22.04 or earlier** (has OpenSSL 1.1.1)

**Option B: Manual OpenSSL 1.1.1 installation** (successfully tested on Ubuntu 24.04)

This approach compiles OpenSSL 1.1.1w locally and uses the official PyPy tarball (which uses system glibc):

```bash
# 1. Download and compile OpenSSL 1.1.1w
cd /tmp
wget https://www.openssl.org/source/openssl-1.1.1w.tar.gz
tar xzf openssl-1.1.1w.tar.gz
cd openssl-1.1.1w
./config --prefix=$HOME/.local/openssl-1.1.1 shared
make -j$(nproc)
make install

# 2. Download official PyPy tarball (uses system glibc)
cd /tmp
wget https://downloads.python.org/pypy/pypy2.7-v7.3.20-linux64.tar.bz2
tar xjf pypy2.7-v7.3.20-linux64.tar.bz2
mv pypy2.7-v7.3.20-linux64 ~/.local/

# 3. Add to PATH and install pip
export PATH="$HOME/.local/pypy2.7-v7.3.20-linux64/bin:$PATH"
pypy -m ensurepip --user

# 4. Install cryptography and pyOpenSSL with custom OpenSSL
export LDFLAGS="-L$HOME/.local/openssl-1.1.1/lib"
export CPPFLAGS="-I$HOME/.local/openssl-1.1.1/include"
pypy -m pip install --user --no-binary :all: 'cryptography<3' 'pyOpenSSL<21'

# 5. Verify installation (must set LD_LIBRARY_PATH)
export LD_LIBRARY_PATH=$HOME/.local/openssl-1.1.1/lib:$LD_LIBRARY_PATH
pypy -c 'import OpenSSL; print("✓ OpenSSL version:", OpenSSL.__version__)'
```

**Important:** The startup script will automatically set `PATH` and `LD_LIBRARY_PATH` to use the custom OpenSSL build.

For most users, **skip pyOpenSSL** and proceed without it.

## Step 4: Clone P2Pool Repository

```bash
# Clone the repository
cd ~
git clone https://github.com/frstrtr/p2pool-dash.git
cd p2pool-dash

# Checkout the Scrypt branch
git checkout feature/scrypt-litecoin-dogecoin
```

## Step 5: Build ltc_scrypt Module

The Scrypt algorithm requires a C extension for performance:

```bash
cd ~/p2pool-dash/litecoin_scrypt
bash build.sh
```

Expected output:
```
=== Building ltc_scrypt module ===
✓ Found PyPy: Python 2.7.18
✓ Python 2 build complete
```

### Verify installation

```bash
pypy -c 'import ltc_scrypt; print("✓ ltc_scrypt module loaded successfully")'
```

## Step 6: Configure Blockchain Nodes

### Litecoin Configuration

Edit `~/.litecoin/litecoin.conf`:

```ini
# Testnet
testnet=1
server=1
rpcuser=litecoinrpc
rpcpassword=YOUR_SECURE_PASSWORD_HERE
rpcallowip=127.0.0.1
rpcport=19332

# Mainnet (comment out testnet=1 above)
#server=1
#rpcuser=litecoinrpc
#rpcpassword=YOUR_SECURE_PASSWORD_HERE
#rpcallowip=127.0.0.1
#rpcport=9332
```

### Dogecoin Configuration

Edit `~/.dogecoin/dogecoin.conf`:

```ini
# Testnet
testnet=1
server=1
rpcuser=dogeuser
rpcpassword=YOUR_SECURE_PASSWORD_HERE
rpcallowip=127.0.0.1
rpcport=44555

# Mainnet (comment out testnet=1 above)
#server=1
#rpcuser=dogeuser
#rpcpassword=YOUR_SECURE_PASSWORD_HERE
#rpcallowip=127.0.0.1
#rpcport=22555
```

### Start and sync both nodes

```bash
# Start Litecoin
litecoind -daemon

# Start Dogecoin
dogecoind -daemon

# Wait for full sync (may take several hours/days)
# Check Litecoin sync status
litecoin-cli getblockchaininfo

# Check Dogecoin sync status
dogecoin-cli getblockchaininfo
```

## Step 7: Configure P2Pool Startup Script

Edit `~/p2pool-dash/start_p2pool_scrypt_testnet.sh`:

```bash
#!/bin/bash
# Start P2Pool for Litecoin + Dogecoin Merged Mining (Testnet)

cd "$(dirname "$0")"

# Litecoin Testnet RPC credentials (match litecoin.conf)
LTC_RPC_USER="litecoinrpc"
LTC_RPC_PASS="YOUR_SECURE_PASSWORD_HERE"
LTC_RPC_HOST="127.0.0.1"
LTC_RPC_PORT="19332"

# Dogecoin Testnet RPC credentials (match dogecoin.conf)
DOGE_RPC_USER="dogeuser"
DOGE_RPC_PASS="YOUR_SECURE_PASSWORD_HERE"
DOGE_RPC_HOST="127.0.0.1"
DOGE_RPC_PORT="44555"

# P2Pool configuration
P2POOL_ADDRESS="YOUR_LITECOIN_TESTNET_ADDRESS"  # Get from: litecoin-cli getnewaddress
P2POOL_FEE="0.5"                                # 0.5% pool fee
NET="litecoin_testnet"

echo "=== Starting P2Pool Scrypt (Litecoin + Dogecoin Testnet) ==="
echo "Network: $NET"
echo "Payout Address: $P2POOL_ADDRESS"
echo "Pool Fee: $P2POOL_FEE%"
echo ""

# Start P2Pool
pypy run_p2pool.py \
    --net $NET \
    --address $P2POOL_ADDRESS \
    --fee $P2POOL_FEE \
    --bitcoind-rpc-username $LTC_RPC_USER \
    --bitcoind-rpc-password $LTC_RPC_PASS \
    --bitcoind-address $LTC_RPC_HOST \
    --bitcoind-rpc-port $LTC_RPC_PORT \
    --worker-port 9327 \
    --p2pool-port 9338 \
    --max-conns 40 \
    --outgoing-conns 8 \
    "$@"
```

Make it executable:
```bash
chmod +x ~/p2pool-dash/start_p2pool_scrypt_testnet.sh
```

### For Mainnet

Create `start_p2pool_scrypt_mainnet.sh` with:
- `NET="litecoin"`
- `LTC_RPC_PORT="9332"`
- `DOGE_RPC_PORT="22555"`
- `P2POOL_ADDRESS="YOUR_LITECOIN_MAINNET_ADDRESS"`
- `--worker-port 9327`
- `--p2pool-port 9338`

## Step 8: Start P2Pool

```bash
cd ~/p2pool-dash
./start_p2pool_scrypt_testnet.sh
```

### Expected Output

```
=== Starting P2Pool Scrypt (Litecoin + Dogecoin Testnet) ===
Network: litecoin_testnet
Payout Address: mwjUmhAW68zCtgZpW5b1xD5g7MZew6xPV4
Pool Fee: 0.5%

2025-12-22 04:00:00.000000 P2Pool (version 17.0-123-g1234567)
2025-12-22 04:00:00.000000 
2025-12-22 04:00:00.000000 Testing bitcoind RPC connection...
2025-12-22 04:00:00.000000 Connected to Litecoin Core version 240000
2025-12-22 04:00:00.000000 Current block height: 2476217
2025-12-22 04:00:00.000000 
2025-12-22 04:00:00.000000 Loading ltc_scrypt module for Scrypt hashing...
2025-12-22 04:00:00.000000 ✓ ltc_scrypt module loaded successfully
2025-12-22 04:00:00.000000 
2025-12-22 04:00:00.000000 Starting P2Pool node...
2025-12-22 04:00:00.000000 Listening for workers on 0.0.0.0:9327
2025-12-22 04:00:00.000000 Listening for peers on 0.0.0.0:9338
2025-12-22 04:00:00.000000 
2025-12-22 04:00:00.000000 Web interface available at http://localhost:9327/
```

## Step 9: Configure Mining Software

### For CPU Mining (cpuminer-multi)

```bash
cpuminer-multi \
    -a scrypt \
    -o stratum+tcp://127.0.0.1:9327 \
    -u YOUR_LITECOIN_ADDRESS \
    -p x \
    -t 2
```

### For GPU Mining (cgminer)

```bash
cgminer \
    --scrypt \
    -o stratum+tcp://127.0.0.1:9327 \
    -u YOUR_LITECOIN_ADDRESS \
    -p x
```

### For ASIC Mining

Point your ASIC to:
- **URL:** `stratum+tcp://YOUR_SERVER_IP:9327`
- **Username:** Your Litecoin address
- **Password:** `x`

## Step 10: Monitor P2Pool

### Web Interface

Open browser to: `http://localhost:9327/`

Shows:
- Pool hashrate
- Connected miners
- Recent shares
- Recent blocks found
- Your personal statistics

### Command Line

```bash
# Watch p2pool output
tail -f ~/.p2pool/data/litecoin_testnet/log

# Check connected peers
curl http://localhost:9327/peer_addresses

# Check local stats
curl http://localhost:9327/local_stats
```

## Troubleshooting

### ltc_scrypt module not found

```bash
cd ~/p2pool-dash/litecoin_scrypt
pypy setup.py install --user
```

### Cannot connect to Litecoin/Dogecoin node

1. Verify nodes are running:
```bash
ps aux | grep -E 'litecoind|dogecoind'
```

2. Test RPC connection:
```bash
litecoin-cli getblockchaininfo
dogecoin-cli getblockchaininfo
```

3. Check RPC credentials match in config files

### No peers connecting

- Wait 5-10 minutes for peer discovery
- Check firewall allows port 9338:
```bash
sudo ufw allow 9338/tcp
```

### High CPU usage

- PyPy uses JIT compilation (high CPU initially, then improves)
- Reduce miner threads if needed
- Consider upgrading hardware for higher hashrates

### Share difficulty too high/low

P2Pool automatically adjusts share difficulty based on pool hashrate. This is normal behavior.

## Advanced Configuration

### Running as a Service

Create `/etc/systemd/system/p2pool-scrypt.service`:

```ini
[Unit]
Description=P2Pool Scrypt (Litecoin+Dogecoin)
After=network.target litecoind.service dogecoind.service

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/p2pool-dash
ExecStart=/snap/bin/pypy /home/YOUR_USERNAME/p2pool-dash/run_p2pool.py --net litecoin_testnet --address YOUR_ADDRESS --fee 0.5 --bitcoind-rpc-username litecoinrpc --bitcoind-rpc-password YOUR_PASSWORD --bitcoind-address 127.0.0.1 --bitcoind-rpc-port 19332 --worker-port 9327 --p2pool-port 9338
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable p2pool-scrypt
sudo systemctl start p2pool-scrypt
sudo systemctl status p2pool-scrypt
```

### Firewall Configuration

```bash
# Allow P2Pool peer port
sudo ufw allow 9338/tcp

# Allow worker/stratum port (if remote miners)
sudo ufw allow 9327/tcp

# Allow web interface (if remote access needed)
sudo ufw allow 9327/tcp
```

### Backup Share Chain

Important: Backup your share chain periodically to preserve payout history:

```bash
# Backup
tar czf p2pool-shares-backup-$(date +%Y%m%d).tar.gz ~/.p2pool/data/

# Restore
tar xzf p2pool-shares-backup-YYYYMMDD.tar.gz -C ~/
```

## Network Ports Reference

| Service | Testnet Port | Mainnet Port | Protocol |
|---------|-------------|--------------|----------|
| Litecoin RPC | 19332 | 9332 | HTTP |
| Dogecoin RPC | 44555 | 22555 | HTTP |
| P2Pool Workers | 9327 | 9327 | Stratum |
| P2Pool Web | 9327 | 9327 | HTTP |
| P2Pool Peers | 9338 | 9338 | TCP |

## Performance Tips

1. **Use PyPy** (not CPython) - 5-10x faster
2. **Enable huge pages** for better memory performance:
```bash
sudo sysctl -w vm.nr_hugepages=128
```
3. **Use SSD** for share chain storage
4. **Increase open file limits** if running many connections:
```bash
ulimit -n 65536
```

## Getting Help

- **GitHub Issues:** https://github.com/frstrtr/p2pool-dash/issues
- **Documentation:** Check `MERGED_MINING_ROADMAP.md` for development status
- **Logs:** Check `~/.p2pool/data/litecoin_testnet/log` for error messages

## Success Indicators

You'll know P2Pool is working when you see:

1. ✓ "Testing bitcoind RPC connection..." succeeds
2. ✓ "ltc_scrypt module loaded successfully"
3. ✓ "Listening for workers on 0.0.0.0:9327"
4. ✓ "Listening for peers on 0.0.0.0:9338"
5. ✓ Periodic "GOT SHARE" messages when miners submit work
6. ✓ Peer connections (check web interface)
7. ✓ Shares in chain (visible on web interface)

Happy mining! 🚀
