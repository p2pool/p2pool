# P2Pool Installation Guide (Litecoin + Dogecoin Merged Mining)

Complete installation guide for P2Pool on Ubuntu/Debian and **macOS (Intel)** systems with Litecoin (scrypt) mining and Dogecoin merged mining.

> **Windows 10/11 users**: See [WINDOWS_DEPLOYMENT.md](docs/WINDOWS_DEPLOYMENT.md) for WSL2, Docker, and native Windows deployment instructions.
>
> **macOS (Intel) users**: See [macOS (Intel) Installation](#macos-intel-installation) below for Homebrew-based setup — tested on macOS 26.x (x86_64).

## Table of Contents
- [System Requirements](#system-requirements)
- [Litecoin Core Installation](#litecoin-core-installation)
- [Dogecoin Core Installation](#dogecoin-core-installation)
- [macOS (Intel) Installation](#macos-intel-installation)
- [Python Environment Setup](#python-environment-setup)
- [P2Pool Installation](#p2pool-installation)
- [Configuration](#configuration)
- [Running P2Pool](#running-p2pool)
- [MM-Adapter Setup](#mm-adapter-setup)
- [Troubleshooting](#troubleshooting)

---

## System Requirements

### Minimum Requirements
- **OS**: Ubuntu 20.04+ or Debian 11+ (or macOS 12+ Intel — see [macOS section](#macos-intel-installation))
- **CPU**: 2+ cores
- **RAM**: 4GB minimum, 8GB recommended
- **Disk**: 20GB+ (for Litecoin blockchain) + 80GB+ (for Dogecoin blockchain)
- **Network**: Stable internet connection

### Required Ports
- **9333**: Litecoin P2P (incoming connections)
- **9332**: Litecoin RPC (localhost only)
- **22556**: Dogecoin P2P (incoming connections)
- **22555**: Dogecoin RPC (localhost only)
- **9327**: P2Pool Stratum (for miners)
- **9326**: P2Pool P2P (for peer connections)
- **44556**: MM-Adapter RPC (internal, localhost)

---

## Litecoin Core Installation

### 1. Install Dependencies
```bash
sudo apt-get update
sudo apt-get install -y build-essential libtool autotools-dev automake pkg-config \
    bsdmainutils python3 libssl-dev libevent-dev libboost-system-dev \
    libboost-filesystem-dev libboost-chrono-dev libboost-test-dev \
    libboost-thread-dev libminiupnpc-dev libzmq3-dev git wget
```

### 2. Install Litecoin Core (Binary)
```bash
cd ~
wget https://download.litecoin.org/litecoin-0.21.4/linux/litecoin-0.21.4-x86_64-linux-gnu.tar.gz
tar xzf litecoin-0.21.4-x86_64-linux-gnu.tar.gz
sudo install -m 0755 litecoin-0.21.4/bin/* /usr/local/bin/
```

Or build from source:
```bash
cd ~
git clone https://github.com/litecoin-project/litecoin.git
cd litecoin
git checkout v0.21.4
./autogen.sh
./configure --without-gui --disable-tests --disable-bench
make -j$(nproc)
sudo make install
```

### 3. Configure Litecoin Core

> **Deployment topology**: Litecoin Core can run on the **same machine** as P2Pool
> or on a **separate machine** on your LAN. If separate, add `rpcallowip` for
> your P2Pool machine's subnet and set `rpcbind=0.0.0.0`. The examples below
> show both options.

Create `~/.litecoin/litecoin.conf`:

**Same-machine setup** (Litecoin Core and P2Pool on one box):
```ini
# ~/.litecoin/litecoin.conf — same machine as P2Pool
server=1
daemon=1
txindex=1

rpcuser=litecoinrpc
rpcpassword=CHANGE_ME
rpcallowip=127.0.0.1
listen=1
maxconnections=50

[main]
port=9333
rpcport=9332
rpcbind=127.0.0.1
dbcache=4000
par=0

# RPC capacity (increase if P2Pool polls heavily)
rpcworkqueue=512
rpcthreads=32
```

**Separate-machine setup** (verified production config from node LTC_DAEMON_IP):
```ini
# ~/.litecoin/litecoin.conf — separate machine, P2Pool on LAN
server=1
daemon=1
txindex=1

rpcuser=litecoinrpc
rpcpassword=CHANGE_ME
rpcallowip=127.0.0.1
rpcallowip=192.168.0.0/16       # Allow LAN P2Pool nodes
listen=1
maxconnections=50

[main]
port=9333
rpcport=9332
rpcbind=0.0.0.0                 # Listen on all interfaces for LAN RPC
dbcache=4000                    # Increase if RAM allows (production: 64000)
par=0                           # Use all CPU cores for verification

# RPC capacity
rpcworkqueue=512
rpcthreads=32
```

### 4. Start Litecoin Core and Sync
```bash
litecoind

# Monitor sync progress
litecoin-cli getblockchaininfo

# Wait until "blocks" equals "headers" (may take several hours)
```

---

## Dogecoin Core Installation

### 1. Install Dogecoin Core (Binary)
```bash
cd ~
wget https://github.com/dogecoin/dogecoin/releases/download/v1.14.9/dogecoin-1.14.9-x86_64-linux-gnu.tar.gz
tar xzf dogecoin-1.14.9-x86_64-linux-gnu.tar.gz
sudo install -m 0755 dogecoin-1.14.9/bin/* /usr/local/bin/
```

### 2. Configure Dogecoin Core

> **Deployment topology**: Dogecoin Core can run on the same machine as P2Pool
> or on a separate machine. If separate, the **MM-Adapter** must run on the
> same machine as P2Pool (it proxies RPC on `127.0.0.1:44556`), and the
> Dogecoin daemon must allow RPC from the adapter's IP.

Create `~/.dogecoin/dogecoin.conf`:

**Same-machine setup** (Dogecoin Core, MM-Adapter, and P2Pool on one box):
```ini
# ~/.dogecoin/dogecoin.conf — same machine as P2Pool
server=1
daemon=1

rpcuser=dogecoinrpc
rpcpassword=CHANGE_ME
rpcallowip=127.0.0.1
rpcbind=127.0.0.1
rpcport=22555

port=22556
listen=1
maxconnections=50

dbcache=2000
par=4
```

**Separate-machine setup** (verified production config from node DOGE_DAEMON_IP):
```ini
# ~/.dogecoin/dogecoin.conf — separate machine, adapter/P2Pool on LAN
server=1
daemon=1

rpcuser=dogecoinrpc
rpcpassword=CHANGE_ME
rpcallowip=127.0.0.1
rpcallowip=192.168.0.0/16       # Allow LAN adapter/P2Pool
rpcbind=0.0.0.0
rpcport=22555

port=22556
bind=0.0.0.0
listen=1
maxconnections=50

dbcache=2000
par=4
```

### 3. Start Dogecoin Core and Sync
```bash
dogecoind

# Monitor sync progress
dogecoin-cli getblockchaininfo
```

---

## Python Environment Setup

### Problem: Python 2 is End-of-Life
P2Pool requires Python 2.7, which is no longer available in modern Ubuntu/Debian distributions. We use PyPy as a solution.

### 1. Install PyPy (Python 2.7 Alternative)
```bash
# Install PyPy via snap (recommended)
sudo snap install pypy --classic

# Verify installation
pypy --version
# Should show: Python 2.7.18
```

Or install via tarball:
```bash
wget https://downloads.python.org/pypy/pypy2.7-v7.3.20-linux64.tar.bz2
tar xjf pypy2.7-v7.3.20-linux64.tar.bz2
export PATH="$PWD/pypy2.7-v7.3.20-linux64/bin:$PATH"
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
# Core dependencies (includes scrypt hashing)
pypy -m pip install twisted==20.3.0 pycryptodome 'scrypt>=0.8.0,<=0.8.22'

# ECDSA library (required for share messaging signature verification)
pypy -m pip install ecdsa

# Optional: For web interface SSL
pypy -m pip install pyasn1 pyasn1-modules service_identity

# Recommended: coincurve for constant-time ECDSA signing (security hardening)
# See "Security: coincurve Installation" section below
```

**Note on scrypt package version**: Versions above 0.8.22 use Python 3 f-strings and are incompatible with Python 2.7/PyPy.

### 3. Security: coincurve Installation (Recommended)

The `ecdsa` Python library has a known timing side-channel vulnerability (CVE-2024-23342, Minerva attack) in its `sign_digest()` function. P2Pool uses ECDSA signing for share messages. The upstream `ecdsa` project considers side-channel attacks out of scope and will **never** fix this.

**coincurve** wraps Bitcoin Core's `libsecp256k1` — arguably the most audited secp256k1 implementation in existence — which uses constant-time signing. When coincurve is installed, P2Pool **automatically** prefers it over `ecdsa` for all signing operations.

**Snap PyPy installation** (requires building from source due to snap glibc constraints):

```bash
# Install build dependencies
sudo apt-get install -y automake libtool pkg-config

# Download coincurve 13.0.0 (last Python 2 compatible version)
cd /tmp
pypy -m pip download "coincurve==13.0.0" --no-binary :all: -d coincurve-build
cd coincurve-build && tar xzf coincurve-13.0.0.tar.gz && cd coincurve-13.0.0

# Patch: build libsecp256k1 without libgmp to avoid glibc mismatch with snap
# In setup.py, find the line with './configure' flags and add '--with-bignum=no'
sed -i "s|'--disable-dependency-tracking',|'--disable-dependency-tracking', '--with-bignum=no',|" setup.py

# Build and install (use snap's cffi, don't install deps)
pypy -m pip install . --no-build-isolation --no-deps
```

**Non-snap PyPy / system Python 2.7** (simpler):
```bash
pypy -m pip install "coincurve==13.0.0"
```

**Verify installation**:
```bash
pypy -c "import coincurve; pk = coincurve.PrivateKey(); print('coincurve OK')"
```

If coincurve is not installed, P2Pool silently falls back to `ecdsa` for signing. Mining works normally, but the signing code path is vulnerable to timing attacks.

### 4. Handle OpenSSL Import Warnings

**Problem**: You may see `ImportError: No module named OpenSSL` warnings in logs.

**Solution**: These are non-fatal warnings from Twisted trying to import SSL for HTTPS. If they bother you:

```bash
# Option 1: Install pyOpenSSL (may cause issues with snap PyPy)
pypy -m pip install pyOpenSSL

# Option 2: Ignore the warnings (recommended)
# They don't affect P2Pool functionality for local mining
```

---

## P2Pool Installation

### 1. Clone P2Pool Repository
```bash
cd ~
git clone https://github.com/frstrtr/p2pool-merged-v36.git
cd p2pool-merged-v36
```

### 2. Verify Scrypt Hashing

The `ltc_scrypt.py` wrapper auto-detects the scrypt library. Verify it works:

```bash
pypy -c "import ltc_scrypt; print('scrypt hashing OK')"
```

If this fails, ensure `scrypt` is installed:
```bash
pypy -m pip install 'scrypt>=0.8.0,<=0.8.22'
```

**Legacy fallback**: If the pip `scrypt` package won't install (e.g., missing libssl-dev), you can build the C extension:
```bash
cd litecoin_scrypt
pypy setup.py install --user
cd ..
```

---

## Configuration

### Network Modes

P2Pool can run in two modes:

#### 1. Standalone Mode (Testing/Solo Mining)
Edit `p2pool/networks/litecoin.py`:
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
Edit `p2pool/networks/litecoin.py`:
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

### Generate Mining Address

```bash
# Create new wallet (if needed)
litecoin-cli createwallet "mining"

# Get new legacy address (required for P2Pool)
litecoin-cli getnewaddress "" legacy
# Example output: LYourLitecoinAddressHere
```

**Important**: Use a **legacy** address (starts with `L` on mainnet, `m`/`n` on testnet). Bech32 (`ltc1...`) addresses are not directly supported for P2Pool share chain payouts.

---

## Running P2Pool

### Start P2Pool (Litecoin Only)

```bash
cd ~/p2pool-merged-v36

# For Litecoin mainnet
pypy run_p2pool.py \
    --net litecoin \
    --bitcoind-address 127.0.0.1 \
    --bitcoind-rpc-port 9332 \
    -a YOUR_LTC_ADDRESS \
    litecoinrpc YOUR_LTC_RPC_PASSWORD

# For Litecoin testnet
pypy run_p2pool.py \
    --net litecoin_testnet \
    --bitcoind-address 127.0.0.1 \
    --bitcoind-rpc-port 19332 \
    -a YOUR_LTC_TESTNET_ADDRESS \
    litecoinrpc YOUR_LTC_RPC_PASSWORD
```

### Start P2Pool with Merged Mining (Litecoin + Dogecoin)

See the main README for full merged mining startup with MM-Adapter.

> **Note on addresses**: `--coind-address` and `--merged-coind-p2p-address`
> point to the actual daemon IPs. Use `127.0.0.1` if daemons are local, or
> the LAN IP if they are on separate machines (e.g., `LTC_DAEMON_IP` for LTC,
> `DOGE_DAEMON_IP` for DOGE). The `--merged-coind-address` always points to
> the MM-Adapter, which runs on the same machine as P2Pool (`127.0.0.1`).

```bash
pypy run_p2pool.py \
    --net litecoin \
    --coind-address 127.0.0.1 \
    --coind-rpc-port 9332 \
    --coind-p2p-port 9333 \
    --merged-coind-address 127.0.0.1 \
    --merged-coind-rpc-port 44556 \
    --merged-coind-p2p-port 22556 \
    --merged-coind-p2p-address DOGECOIN_DAEMON_IP \
    --merged-coind-rpc-user dogecoinrpc \
    --merged-coind-rpc-password YOUR_DOGE_RPC_PASSWORD \
    --address YOUR_LEGACY_LTC_ADDRESS \
    --give-author 1 \
    -f 1 \
    --disable-upnp \
    litecoinrpc YOUR_LTC_RPC_PASSWORD
```

### Run as Background Service

```bash
cd ~/p2pool-merged-v36
nohup pypy run_p2pool.py \
    --net litecoin \
    --bitcoind-address 127.0.0.1 \
    --bitcoind-rpc-port 9332 \
    -a YOUR_LTC_ADDRESS \
    litecoinrpc YOUR_LTC_RPC_PASSWORD \
    > p2pool.log 2>&1 &

# Monitor logs
tail -f p2pool.log

# Stop P2Pool
pkill -f "pypy.*run_p2pool"
```

### Create Systemd Service (Optional)

Create `/etc/systemd/system/p2pool.service`:
```ini
[Unit]
Description=P2Pool (Litecoin + Dogecoin Merged Mining)
After=litecoind.service
Requires=litecoind.service

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/p2pool-merged-v36
ExecStart=/snap/bin/pypy /home/YOUR_USERNAME/p2pool-merged-v36/run_p2pool.py \
    --net litecoin \
    --bitcoind-address 127.0.0.1 \
    --bitcoind-rpc-port 9332 \
    -a YOUR_LTC_ADDRESS \
    litecoinrpc YOUR_LTC_RPC_PASSWORD
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable p2pool
sudo systemctl start p2pool
sudo systemctl status p2pool
```

---

## MM-Adapter Setup

The MM-Adapter bridges P2Pool and Dogecoin Core for merged mining. See [mm-adapter/README.md](mm-adapter/README.md) for the full reference.

### Installation

```bash
cd mm-adapter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Copy the appropriate example config:

```bash
# Mainnet
cp config.example.yaml config.yaml

# Or testnet
cp config.example.testnet.yaml config.yaml
```

Edit `config.yaml` — the key sections are:

```yaml
# Adapter server (P2Pool connects here)
server:
  host: "127.0.0.1"
  port: 44556                 # --merged-coind-rpc-port in P2Pool
  rpc_user: "dogecoinrpc"    # --merged-coind-rpc-user in P2Pool
  rpc_password: "CHANGE_ME"  # --merged-coind-rpc-password in P2Pool

# Upstream Dogecoin daemon
upstream:
  host: "127.0.0.1"
  port: 22555                 # dogecoin.conf rpcport (testnet: 44555)
  rpc_user: "dogecoinrpc"    # dogecoin.conf rpcuser
  rpc_password: "CHANGE_ME"  # dogecoin.conf rpcpassword
  timeout: 30

# Chain identification
chain:
  name: "dogecoin"
  chain_id: 98
  network_magic: "c0c0c0c0"  # mainnet: c0c0c0c0 | testnet: fcc1b7dc
```

**Credential alignment** — credentials must match on both sides:
- `server.rpc_user` / `server.rpc_password` must match P2Pool's `--merged-coind-rpc-user` / `--merged-coind-rpc-password`
- `upstream.rpc_user` / `upstream.rpc_password` must match `rpcuser` / `rpcpassword` in `dogecoin.conf`

### Running the Adapter

```bash
source venv/bin/activate
python3 adapter.py --config config.yaml
```

**Tip**: Start the adapter before P2Pool. P2Pool will connect to it on startup.

---

## Mining to P2Pool

### Point Your Miner to P2Pool

**Stratum URL**: `stratum+tcp://YOUR_IP:9327`

Example with cpuminer-multi:
```bash
cd ~
git clone https://github.com/tpruvot/cpuminer-multi.git
cd cpuminer-multi
./build.sh

# Mine with limited threads
./cpuminer -t 4 \
    -a scrypt \
    -o stratum+tcp://127.0.0.1:9327 \
    -u YOUR_LTC_ADDRESS \
    -p x
```

### Monitor P2Pool

```bash
# View web interface: http://YOUR_IP:9327/

# Check logs
tail -f ~/p2pool-merged-v36/p2pool.log

# Monitor shares
# P2Pool will show:
# "P2Pool: X shares in chain (Y verified/Z total) Peers: N"
# "Local: XXX kH/s in last N seconds"
```

---

## macOS (Intel) Installation

> **Tested**: macOS 26.3, x86_64 (Intel Mac Pro), PyPy 7.3.20, Homebrew 4.x. Fully operational with merged mining against LAN daemons.
> **Apple Silicon (M1/M2/M3/M4)**: PyPy 2.7 has no native ARM64 builds. Install the x86_64 version and run under Rosetta 2 (`arch -x86_64 brew install pypy`).

### Prerequisites

- [Homebrew](https://brew.sh) package manager
- Git (included with Xcode Command Line Tools: `xcode-select --install`)
- A Litecoin Core daemon accessible on LAN or localhost (P2Pool does **not** require a local blockchain)
- For merged mining: a Dogecoin Core daemon accessible on LAN

Install Homebrew if not already present:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 1. Clone Repository and Install PyPy

```bash
# Clone (skip if you already have the repo)
git clone https://github.com/frstrtr/p2pool-merged-v36.git
cd p2pool-merged-v36
```

```bash
brew install pypy

# Verify
pypy --version
# Python 2.7.18 [PyPy 7.3.x ...]
```

### 2. Install Python Dependencies

```bash
# Pin incremental first (required for Twisted on Python 2.7)
pypy -m pip install 'incremental<22'

# Core dependencies
pypy -m pip install twisted==20.3.0 pycryptodome 'scrypt>=0.8.0,<=0.8.22' ecdsa
```

> **Note**: You will see `DEPRECATION: pip 21.0 will drop support for Python 2.7` warnings.
> This is expected and harmless — pip 20.3.4 is the last version supporting PyPy 2.7 and works correctly.

### 3. Verify scrypt hashing

```bash
cd ~/p2pool-merged-v36   # or wherever you cloned the repo
pypy -c "import ltc_scrypt; print('scrypt OK')"
```

### 4. Install coincurve (recommended, constant-time ECDSA)

coincurve wraps libsecp256k1 for constant-time signing. On macOS with PyPy, pip will download the source tarball and compile it automatically (there are no pre-built wheels for pypy27):

```bash
pypy -m pip install "coincurve==13.0.0"
pypy -c "import coincurve; print('coincurve OK')"
```

If compilation fails (e.g., missing autotools), install build tools first:
```bash
brew install automake libtool
pypy -m pip install "coincurve==13.0.0"
```

### 5. MM-Adapter Setup (for Dogecoin merged mining)

The MM-Adapter requires Python 3 (separate from P2Pool's PyPy 2.7):

```bash
cd ~/p2pool-merged-v36/mm-adapter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create or edit `config_mainnet.yaml` — key fields:
```yaml
server:
  host: "0.0.0.0"
  port: 44556
  rpc_user: "dogecoinrpc"
  rpc_password: "YOUR_DOGE_RPC_PASSWORD"

upstream:
  host: "DOGE_DAEMON_IP"       # e.g. 192.0.2.100
  port: 22555
  rpc_user: "dogecoinrpc"
  rpc_password: "YOUR_DOGE_RPC_PASSWORD"
  timeout: 30

chain:
  name: "dogecoin_mainnet"
  chain_id: 98
```

Start the adapter:
```bash
cd ~/p2pool-merged-v36/mm-adapter
source venv/bin/activate
python3 adapter.py --config config_mainnet.yaml
```

> **Important**: Always `cd` into the `mm-adapter/` directory before activating the venv.
> The `source venv/bin/activate` command uses a relative path.

Verify the adapter is responding:
```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"1.0","id":"test","method":"getbestblockhash","params":[]}' \
  http://dogecoinrpc:YOUR_DOGE_RPC_PASSWORD@127.0.0.1:44556/
# Should return a JSON response with a block hash
```

### 6. Running P2Pool on macOS

P2Pool needs access to a Litecoin Core daemon (local or on LAN). It does **not** need a local blockchain — you can point to a remote daemon.

#### LTC-only mode (no merged mining)
```bash
cd ~/p2pool-merged-v36
pypy run_p2pool.py \
    --net litecoin \
    --coind-address LTC_DAEMON_IP \
    --coind-rpc-port 9332 \
    --coind-p2p-port 9333 \
    --address YOUR_LTC_ADDRESS \
    --disable-upnp \
    litecoinrpc YOUR_LTC_RPC_PASSWORD
```

#### LTC + DOGE merged mining (with MM-Adapter running locally)
```bash
cd ~/p2pool-merged-v36
pypy run_p2pool.py \
    --net litecoin \
    --coind-address LTC_DAEMON_IP \
    --coind-rpc-port 9332 \
    --coind-p2p-port 9333 \
    --merged-coind-address 127.0.0.1 \
    --merged-coind-rpc-port 44556 \
    --merged-coind-p2p-port 22556 \
    --merged-coind-p2p-address DOGE_DAEMON_IP \
    --merged-coind-rpc-user dogecoinrpc \
    --merged-coind-rpc-password YOUR_DOGE_RPC_PASSWORD \
    --address YOUR_LTC_ADDRESS \
    --give-author 2 \
    -f 0 \
    --disable-upnp \
    --max-conns 20 \
    -n EXISTING_P2POOL_NODE:9326 \
    litecoinrpc YOUR_LTC_RPC_PASSWORD
```

Replace `LTC_DAEMON_IP`, `DOGE_DAEMON_IP`, addresses, and passwords with your actual values.

> **Tip**: Add `--redistribute boost` (or `donate`, `pplns`, `fee`) to control
> how shares from unnamed/broken miners are handled. See `--help` for details.

#### Seed from existing nodes

Use `-n HOST:PORT` to connect to known P2Pool peers for faster share chain sync:
```bash
-n PEER_IP_1:9326 -n PEER_IP_2:9326
```

#### Verify the node is operational

After ~30 seconds, check the local API:
```bash
curl -s http://127.0.0.1:9327/local_stats | python3 -m json.tool
```

Key fields to check:
- `"peers"` — should show outgoing connections (e.g., `{"incoming": 0, "outgoing": 8}`)
- `"version"` — should show your p2pool version (e.g., `v36-0.08-alpha`)
- `"protocol_version"` — should be `3503`
- `"block_value"` — current LTC block reward

The web dashboard is also available at `http://127.0.0.1:9327/`.

Share chain sync typically completes within 1–2 minutes when seeded from existing peers. You'll see `Received good share` messages in the log during sync.

### 7. Run as Background Service (launchd)

Create `~/Library/LaunchAgents/com.p2pool.merged.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.p2pool.merged</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/pypy</string>
        <string>run_p2pool.py</string>
        <string>--net</string>
        <string>litecoin</string>
        <string>--coind-address</string>
        <string>LTC_DAEMON_IP</string>
        <string>--coind-rpc-port</string>
        <string>9332</string>
        <string>--disable-upnp</string>
        <string>--address</string>
        <string>YOUR_LTC_ADDRESS</string>
        <string>litecoinrpc</string>
        <string>YOUR_LTC_RPC_PASSWORD</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USERNAME/p2pool-merged-v36</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USERNAME/p2pool-merged-v36/data/litecoin/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USERNAME/p2pool-merged-v36/data/litecoin/launchd.log</string>
</dict>
</plist>
```

Load the service:
```bash
launchctl load ~/Library/LaunchAgents/com.p2pool.merged.plist
launchctl start com.p2pool.merged

# Check status
launchctl list | grep p2pool

# Stop
launchctl stop com.p2pool.merged
launchctl unload ~/Library/LaunchAgents/com.p2pool.merged.plist
```

### 8. macOS Firewall

macOS firewall is off by default. If enabled, allow P2Pool ports:
```bash
# Check firewall status
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate

# Allow incoming connections (if firewall is on)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/pypy
```

Alternatively, allow specific ports via `pfctl` or System Settings > Network > Firewall.

### Tested Deployment Example

The following deployment was verified on macOS 26.3 (Intel Mac Pro, x86_64):

```
Network topology (example — replace IPs with your own):
  LAN_HOST_A   — Litecoin Core (RPC 9332, P2P 9333)
  LAN_HOST_B   — Dogecoin Core (RPC 22555, P2P 22556)
  LAN_HOST_C   — P2Pool node #1 (Ubuntu, --redistribute boost)
  LAN_HOST_D   — P2Pool node #2 (Ubuntu, --redistribute donate)
  macOS Mac    — P2Pool node #3 (this machine)

Result:
  ✓ PyPy 7.3.20 (Python 2.7.18) via Homebrew
  ✓ All dependencies installed (twisted 20.3.0, pycryptodome 3.23.0,
    scrypt 0.8.20, ecdsa 0.19.1, coincurve 13.0.0)
  ✓ MM-Adapter running on 127.0.0.1:44556 → DOGE daemon
  ✓ P2Pool v36-0.08-alpha, protocol 3503
  ✓ 8 outgoing peers, share chain synced in ~90 seconds
  ✓ Merged mining active (DOGE block updates observed)
  ✓ Web dashboard at http://127.0.0.1:9327/
```

### macOS-specific notes

| Area | Notes |
|------|-------|
| **Reactor** | Twisted auto-selects `SelectReactor` on macOS (kqueue also available) |
| **Memory reporting** | Reports peak RSS via `resource.getrusage()` — cosmetic difference from Linux |
| **Conf file paths** | Reads from `~/Library/Application Support/Litecoin/litecoin.conf` (if using local daemon) |
| **UPnP** | Use `--disable-upnp` (recommended on macOS; NAT traversal via router UI) |
| **Apple Silicon** | No native PyPy 2.7 ARM64 — use Rosetta 2 (x86_64). Performance ~30% slower than native |

---

## Troubleshooting

### Common Issues

#### 1. ImportError: No module named ltc_scrypt
```bash
pypy -m pip install 'scrypt>=0.8.0,<=0.8.22'
```

#### 2. AttributeError: ComposedWithContextualOptionalsType
Update to latest version:
```bash
cd ~/p2pool-merged-v36 && git pull
```

#### 3. ValueError: Block not found
Update to latest version:
```bash
cd ~/p2pool-merged-v36 && git pull
```

#### 4. "p2pool is not connected to any peers"
**Fixed**: P2Pool no longer requires peer connections to generate work. Works standalone even with PERSIST=True.

#### 5. PyPy Cache Issues
After code changes, clear bytecode cache:
```bash
cd ~/p2pool-merged-v36
find . -name "*.pyc" -delete
rm -rf __pycache__ */__pycache__ */*/__pycache__
```

#### 6. High CPU Usage
Limit miner threads:
```bash
./cpuminer -t 4 -a scrypt -o stratum+tcp://127.0.0.1:9327 -u ADDRESS -p x
```

#### 7. Stratum Connection Refused
```bash
ps aux | grep pypy          # Check P2Pool is running
ss -tuln | grep 9327        # Check port is listening
sudo ufw allow 9327/tcp     # Check firewall
```

### Log Analysis

```bash
grep -i error ~/p2pool-merged-v36/p2pool.log
grep "New work for worker" ~/p2pool-merged-v36/p2pool.log
grep "GOT SHARE" ~/p2pool-merged-v36/p2pool.log
tail -f ~/p2pool-merged-v36/p2pool.log | grep -E "(shares|Local:|Peers:)"
```

---

## Performance Tuning

### Litecoin Core Optimizations

Add to `~/.litecoin/litecoin.conf` (already included in the verified configs above):
```ini
dbcache=4000            # More RAM = faster IBD and reorg handling
maxconnections=50       # Production value; reduce if bandwidth limited
rpcworkqueue=512        # Prevent RPC queue exhaustion under P2Pool polling
rpcthreads=32           # Match P2Pool's template polling concurrency
par=0                   # Use all available CPU cores for block verification
```

### Dogecoin Core Optimizations

Add to `~/.dogecoin/dogecoin.conf`:
```ini
dbcache=2000
maxconnections=50
par=4
```

### System Optimizations

```bash
echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216
```

---

## Updating P2Pool

```bash
cd ~/p2pool-merged-v36
pkill -f "pypy.*run_p2pool"
git pull
find . -name "*.pyc" -delete
pypy run_p2pool.py --net litecoin --bitcoind-address 127.0.0.1 --bitcoind-rpc-port 9332 -a YOUR_ADDRESS litecoinrpc YOUR_PASSWORD
```

---

## Security Considerations

1. **Firewall Configuration**:
```bash
sudo ufw allow 9333/tcp   # Litecoin P2P
sudo ufw allow 22556/tcp  # Dogecoin P2P
sudo ufw allow 9326/tcp   # P2Pool P2P
sudo ufw allow 9327/tcp   # Stratum (if mining remotely)
sudo ufw enable
```

2. **RPC Security**:
   - Keep Litecoin RPC on localhost only (never expose port 9332)
   - Keep Dogecoin RPC on localhost only (never expose port 22555)
   - Use strong random passwords

3. **P2Pool Security**:
   - Keep software updated
   - Monitor logs for suspicious activity
   - Use fail2ban for stratum port if publicly exposed

---

## Getting Help

- **GitHub Issues**: https://github.com/frstrtr/p2pool-merged-v36/issues
- **P2Pool Wiki**: https://en.bitcoin.it/wiki/P2Pool

---

## Credits

- P2Pool original: forrestv
- Litecoin/Scrypt adaptation and merged mining: community contributors

## License

See LICENSE file in repository.
