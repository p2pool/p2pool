# P2Pool-Dash

Decentralized pool mining software for Dash, Litecoin, and Dogecoin cryptocurrencies.

## 🎉 Litecoin + Dogecoin Merged Mining

**Status:** ✅ **PRODUCTION READY** - Mainnet merged mining operational

Branch: `feature/scrypt-litecoin-dogecoin`

### Key Features
- ✅ Litecoin scrypt mining with Dogecoin AuxPoW merged mining
- ✅ Multiaddress coinbase - miners specify both LTC and DOGE addresses
- ✅ Automatic address conversion (same pubkey_hash, correct network format)
- ✅ Modern P2PKH donation script (saves 42 bytes vs old P2PK)
- ✅ Node operator fees for merged mining infrastructure
- ✅ Real-time monitoring dashboard
- ✅ MM-Adapter bridge for standard Dogecoin daemon compatibility

### Architecture

```
┌─────────────┐    Stratum   ┌─────────────┐   JSON-RPC   ┌─────────────┐
│   Miners    │◀────────────▶│   P2Pool    │◀────────────▶│  Litecoin   │
│  (scrypt)   │   Port 9327  │  (PyPy 2.7) │  Port 9332   │   Core      │
└─────────────┘              └──────┬──────┘              └─────────────┘
                                    │
                                    │ JSON-RPC (Port 44556)
                                    ▼
                             ┌──────────────┐   JSON-RPC   ┌─────────────┐
                             │  MM-Adapter  │◀────────────▶│  Dogecoin   │
                             │ (Python 3)   │  Port 22555  │   Core      │
                             └──────────────┘              └─────────────┘
```

See [MERGED_MINING_DONATION.md](MERGED_MINING_DONATION.md) for technical details.

## 📋 Documentation

**⚠️ IMPORTANT**: For complete installation instructions, troubleshooting, and configuration, please see:

### **[📖 INSTALL.md - Complete Installation Guide](INSTALL.md)**

The installation guide covers:
- ✅ System requirements and dependencies
- ✅ Dash Core installation and configuration
- ✅ Python 2.7 / PyPy setup (modern Ubuntu/Debian)
- ✅ dash_hash module compilation
- ✅ Standalone vs Multi-node configuration
- ✅ Common issues and solutions (OpenSSL, missing modules, etc.)
- ✅ Performance tuning and security

### Other Documentation

| Document | Description |
|----------|-------------|
| [MERGED_MINING_DONATION.md](MERGED_MINING_DONATION.md) | LTC+DOGE merged mining technical details |
| [mm-adapter/README.md](mm-adapter/README.md) | Merged mining adapter setup |
| [MULTIADDRESS_MINING_GUIDE.md](MULTIADDRESS_MINING_GUIDE.md) | Multi-address mining configuration |
| [CUSTOM_NETWORK_GUIDE.md](CUSTOM_NETWORK_GUIDE.md) | Adding support for new cryptocurrencies |
| [ASIC_SUPPORT_COMPLETE.md](ASIC_SUPPORT_COMPLETE.md) | ASICBOOST implementation details |
| [SHARE_ARCHIVE_README.md](SHARE_ARCHIVE_README.md) | Share archival and recovery |

---

## 🚀 Quick Start: Litecoin + Dogecoin Merged Mining

### Prerequisites

1. **Litecoin Core** (v0.21+) - Fully synced on mainnet
2. **Dogecoin Core** (v1.14.7+) - Fully synced on mainnet
3. **PyPy 2.7** - For running P2Pool
4. **Python 3.10+** - For running MM-Adapter

### Step 1: Install P2Pool

```bash
# Clone repository
git clone https://github.com/dashpay/p2pool-dash.git
cd p2pool-dash
git checkout feature/scrypt-litecoin-dogecoin

# Install PyPy 2.7 (Ubuntu 24.04+)
wget https://downloads.python.org/pypy/pypy2.7-v7.3.20-linux64.tar.bz2
tar xjf pypy2.7-v7.3.20-linux64.tar.bz2
export PATH="$PWD/pypy2.7-v7.3.20-linux64/bin:$PATH"

# Install P2Pool dependencies
pypy -m ensurepip
pypy -m pip install twisted pycryptodome

# Build litecoin_scrypt module
cd litecoin_scrypt
pypy setup.py install --user
cd ..
```

### Step 2: Configure Litecoin Core

Add to `~/.litecoin/litecoin.conf`:
```ini
server=1
rpcuser=litecoinrpc
rpcpassword=YOUR_SECURE_PASSWORD
rpcallowip=127.0.0.1
rpcport=9332
```

### Step 3: Configure Dogecoin Core

Add to `~/.dogecoin/dogecoin.conf`:
```ini
server=1
rpcuser=dogecoinrpc
rpcpassword=YOUR_SECURE_PASSWORD
rpcallowip=127.0.0.1
rpcport=22555
```

### Step 4: Setup MM-Adapter

The MM-Adapter bridges P2Pool and Dogecoin Core for merged mining:

```bash
cd mm-adapter

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure adapter
cp config.example.yaml config.yaml
```

Edit `config.yaml`:
```yaml
adapter:
  host: "127.0.0.1"
  port: 44556
  rpc_user: "dogecoinrpc"
  rpc_password: "YOUR_SECURE_PASSWORD"

dogecoin:
  host: "127.0.0.1"
  port: 22555
  rpc_user: "dogecoinrpc"
  rpc_password: "YOUR_SECURE_PASSWORD"
```

Start the adapter:
```bash
python3 adapter.py --config config.yaml
```

### Step 5: Start P2Pool

```bash
# Get a legacy Litecoin address (L... format, not ltc1...)
litecoin-cli getnewaddress "" legacy

# Start P2Pool with merged mining
pypy run_p2pool.py \
    --net litecoin \
    --coind-address 127.0.0.1 \
    --coind-rpc-port 9332 \
    --coind-p2p-port 9333 \
    --merged-coind-address 127.0.0.1 \
    --merged-coind-rpc-port 44556 \
    --merged-coind-rpc-user dogecoinrpc \
    --merged-coind-rpc-password YOUR_SECURE_PASSWORD \
    --address YOUR_LEGACY_LTC_ADDRESS \
    --give-author 1 \
    -f 1 \
    --disable-upnp \
    litecoinrpc YOUR_LTC_RPC_PASSWORD
```

### Step 6: Connect Miners

Point your scrypt miners to:
```
stratum+tcp://YOUR_IP:9327
```

**Username formats:**
- Basic: `LTC_ADDRESS`
- With DOGE address: `LTC_ADDRESS,DOGE_ADDRESS`
- With worker name: `LTC_ADDRESS,DOGE_ADDRESS.worker1`

**Example:**
```
Username: LVzy9mWFCQDBebZwvdSChevDJTJTxVbazc,DFv7Rp94R9sQvo4PV5STp2qJPsBCprauFe.rig1
Password: x
```

---

---

## Dash Mining (Original)

### Requirements

* **Dash Core**: >=23.0.0 (Protocol 70238+)
* **Python**: 2.7 (via PyPy recommended)
* **Twisted**: >=19.10.0
* **pycryptodome**: >=3.9.0
* **dash_hash**: X11 hashing module (included as submodule)

### Features

* ✅ **ASICBOOST Support**: Full BIP320 version-rolling implementation
* ✅ **Modern ASIC Compatible**: Works with Antminer D3/D5/D7
* ✅ **Enhanced Difficulty Control**: Support for +difficulty and /difficulty modifiers
* ✅ **Variable Difficulty**: Configurable vardiff with --share-rate parameter
* ✅ **Backward Compatible**: CPU/GPU miners still supported

### Modern Ubuntu/Debian (24.04+)

Python 2 is no longer available. Use PyPy:

```bash
# Install PyPy
sudo snap install pypy --classic

# Install dependencies
pypy -m pip install twisted==19.10.0 pycryptodome

# Clone and setup
git clone https://github.com/dashpay/p2pool-dash.git
cd p2pool-dash
git submodule init
git submodule update

# Build dash_hash
cd dash_hash
pypy setup.py install --user
cd ..

# Run P2Pool
pypy run_p2pool.py --net dash -a YOUR_DASH_ADDRESS
```

**See [INSTALL.md](INSTALL.md) for detailed instructions.**

### Ubuntu 24.04 Automated Installer

For Ubuntu 24.04 systems, we provide an automated installer script that sets up PyPy2, builds a local OpenSSL 1.1, and configures p2pool with systemd integration:

```bash
./install_p2pool_ubuntu_2404.sh
```

### Older Systems (Ubuntu 20.04 and earlier)

If Python 2.7 is still available:

```bash
sudo apt-get install python2 python2-dev python2-twisted python2-pip gcc g++
git clone https://github.com/dashpay/p2pool-dash.git
cd p2pool-dash
git submodule init && git submodule update
cd dash_hash && python2 setup.py install --user && cd ..
python2 run_p2pool.py --net dash -a YOUR_DASH_ADDRESS
```

## Mining to P2Pool

Point your miner to:
```
stratum+tcp://YOUR_IP:7903
```

Username: Your Dash address  
Password: anything

### Advanced Username Options

You can append difficulty modifiers to your Dash address:

**Pseudoshare difficulty** (for vardiff tuning):
```
YOUR_ADDRESS+DIFFICULTY
Example: XdgF55wEHBRWwbuBniNYH4GvvaoYMgL84u+4096
```

**Actual share difficulty** (fixed minimum):
```
YOUR_ADDRESS/DIFFICULTY
Example: XdgF55wEHBRWwbuBniNYH4GvvaoYMgL84u/65536
```

**Worker names** (for monitoring):
```
YOUR_ADDRESS.worker_name
Example: XdgF55wEHBRWwbuBniNYH4GvvaoYMgL84u.antminer1
```

## Configuration Modes

### Standalone Mode (Solo/Testing)
Edit `p2pool/networks/dash.py`:
```python
PERSIST = False  # No peers required
```

### Multi-Node Mode (Pool Mining)
Edit `p2pool/networks/dash.py`:
```python
PERSIST = True  # Connect to P2Pool network
```

**⚠️ IMPORTANT**: When upgrading to the latest version with Dash Platform support:
- **Delete old sharechain data**: `data/dash/shares.*` and `data/dash/graph_db`
- Old shares are incompatible due to `_script` field changes
- All nodes in the P2Pool network must update together
- **Protection**: Incompatible shares are validated and rejected BEFORE entering sharechain
- Outdated peers receive clear upgrade instructions in logs

**For detailed configuration, see [INSTALL.md](INSTALL.md).**

## Command Line Options

```bash
pypy run_p2pool.py --help
```

Common options:
- `--net dash` - Use Dash mainnet
- `--net dash_testnet` - Use Dash testnet
- `-a ADDRESS` - Your Dash payout address
- `--dashd-rpc-port 9998` - Dash RPC port (default: 9998)
- `--dashd-address 127.0.0.1` - Dash RPC address
- `--share-rate SECONDS` - Target seconds per pseudoshare (default: 10)

## Troubleshooting

### Common Issues

All issues and solutions are documented in **[INSTALL.md](INSTALL.md)**, including:

- ❌ `ImportError: No module named dash_hash` → Rebuild dash_hash module
- ❌ `AttributeError: ComposedWithContextualOptionalsType` → Update to latest version
- ❌ `ValueError: Block not found` → Update to commit e9b5f57+
- ❌ `ImportError: No module named bitcoin` → Update to latest version
- ❌ `ImportError: No module named OpenSSL` → Non-fatal, can ignore or see INSTALL.md
- ✅ `p2pool is not connected to any peers` → Fixed! No longer blocks work generation
- ❌ High CPU usage → Limit miner threads with `-t` flag

**See [INSTALL.md](INSTALL.md) for complete troubleshooting guide.**

## Recent Updates

### v23.0+ Critical Fixes
- ✅ Missing type classes in pack.py (ComposedWithContextualOptionalsType, ContextualOptionalType, BoolType)
- ✅ Wrong module import (bitcoin → dash)
- ✅ Block hash formatting (zero-padding)
- ✅ Empty payee address handling
- ✅ Removed defunct bootstrap nodes
- ✅ Standalone mode support (PERSIST=False)

### Enhanced Features (December 2025)
- ✅ Enhanced difficulty control (+diff, /diff modifiers)
- ✅ X11 DUMB_SCRYPT_DIFF constant for accurate difficulty display
- ✅ Worker IP tracking infrastructure
- ✅ Configurable vardiff with --share-rate parameter (default: 10 seconds)
- ✅ Improved min_share_target bounds for better difficulty adjustment
- ✅ Fixed Dash-specific got_response() signature compatibility
- ✅ **Block luck calculation** with time-weighted average hashrate
- ✅ **Hashrate sampling** for precise luck statistics
- ✅ **Telegram notifications** for block announcements
- ✅ **Block status tracking** (confirmed/orphaned/pending)
- ✅ **Dash Platform support** (v20+): Handles OP_RETURN platform payments (22.5% block subsidy)
- ✅ **Packed object compatibility**: Fixed share verification for _script field handling
- ✅ **Mainnet ready**: Full support for masternode/platform/superblock payment structures
- ✅ **Solo mining support**: Removed peer connection requirement - works standalone with PERSIST=True
- ✅ **Incompatible share protection**: Pre-validation prevents outdated shares from entering sharechain
- ✅ **Smart peer connections**: Temporary bans for failing peers, counts total connections (incoming+outgoing)

## Port Forwarding

If behind NAT, forward these ports:
- **8999**: P2Pool P2P (for peer connections)
- **7903**: Stratum (for miners)

Do NOT forward port 9998 (Dash RPC - security risk)

## Web Interface & API

P2Pool provides a web interface at `http://YOUR_IP:7903/`:

### Web Pages
- `/static/index.html` - Classic status page
- `/static/dashboard.html` - Modern dashboard with graphs
- `/static/graphs.html` - Detailed statistics graphs

### API Endpoints
- `/local_stats` - Local node statistics
- `/global_stats` - Pool-wide statistics
- `/recent_blocks` - Recently found blocks with luck info
- `/current_payouts` - Current payout distribution
- `/hashrate_samples` - Hashrate sampling stats for luck calculation
- `/block_history` - Historical block data

### Luck Calculation

Block luck shows how "lucky" the pool was finding each block:
- **>100%** (green): Found faster than expected
- **75-100%** (yellow): Normal range
- **<75%** (red): Found slower than expected

Luck is calculated using: `(expected_time / actual_time) × 100%`

The pool uses three methods for hashrate estimation (in order of preference):
1. **Time-weighted average**: Uses actual hashrate samples between blocks (most precise)
2. **Simple average**: Average of hashrates at previous and current block
3. **Single hashrate**: Fallback to current pool hashrate

### Telegram Notifications

To enable Telegram block announcements:
1. Create a bot via [@BotFather](https://t.me/botfather)
2. Edit `data/dash/telegram_config.json`:
```json
{
  "enabled": true,
  "bot_token": "YOUR_BOT_TOKEN",
  "chat_id": "YOUR_CHAT_ID"
}
```

### Connection Threat Detection

The Stratum interface includes intelligent threat detection that monitors connection patterns per IP address. The system calculates a **connection-to-worker ratio** to distinguish between:

- **Normal**: Legitimate multi-rig miners (e.g., 7 connections running 7 unique workers = 1:1 ratio)
- **Elevated**: Suspicious patterns (e.g., 10 connections but only 2 workers = 5:1 ratio)
- **High**: Likely attack or misconfiguration (e.g., 20 connections with 3 workers = 6.7:1 ratio)

#### Configuration

Thresholds are configurable per network in `p2pool/networks/*.py`:

```python
# Default values (dash.py)
CONNECTION_WORKER_ELEVATED = 4.0   # Flag if >4 connections per worker
CONNECTION_WORKER_WARNING = 6.0     # Flag as high if >6 connections per worker
```

This ensures legitimate miners running multiple machines from the same IP are not incorrectly flagged as threats, while still detecting actual connection flooding attempts.

### Persistent Block History

P2Pool stores all found blocks in `data/dash/block_history.json` for permanent record-keeping. This allows the web interface to display complete historical data including:

- Block height, hash, and timestamp
- Network difficulty and block reward
- Pool hashrate at the time of discovery
- Block status (confirmed/orphaned/pending)
- Luck calculation with time-weighted averages

#### Populating Historical Blocks

If you want to add previously mined blocks to the persistent history (e.g., after a fresh install), use the `populate_block_history.py` utility:

```bash
# Create a file with block heights (one per line)
cat > historical_blocks.txt <<EOF
2389670
2389615
2389577
EOF

# Populate block history from blockchain
pypy populate_block_history.py \
    --datadir data/dash \
    --blocks-file historical_blocks.txt \
    --dashd-rpc-username YOUR_RPC_USER \
    --dashd-rpc-password YOUR_RPC_PASS
```

Or specify blocks directly:
```bash
pypy populate_block_history.py \
    --datadir data/dash \
    --blocks 2389670,2389615,2389577 \
    --dashd-rpc-username YOUR_RPC_USER \
    --dashd-rpc-password YOUR_RPC_PASS
```

The script will query dashd to fetch block rewards, timestamps, and difficulty, then merge this data into your block history. This ensures consistent graphs and statistics even for blocks found before the current p2pool installation.

Official wiki :
-------------------------
https://en.bitcoin.it/wiki/P2Pool

Alternate web front end :
-------------------------
* https://github.com/hardcpp/P2PoolExtendedFrontEnd
* https://github.com/johndoe75/p2pool-node-status
* https://github.com/justino/p2pool-ui-punchy

Sponsors:
-------------------------

Thanks to:
* The Bitcoin Foundation for its generous support of P2Pool
* The Litecoin Project for its generous donations to P2Pool
* The Vertcoin Community for its great contribution to P2Pool
* jakehaas, vertoe, chaeplin, dstorm, poiuty, elbereth  and mr.slaveg from the Darkcoin/Dash Community
