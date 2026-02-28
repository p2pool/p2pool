# P2Pool Merged Mining (V36)

> **Lineage:** [`p2pool/p2pool`](https://github.com/p2pool/p2pool) (forrestv) → [`jtoomim/p2pool`](https://github.com/jtoomim/p2pool) (V35) → **`frstrtr/p2pool-merged-v36`** (V36 + merged mining)

[![Latest Release](https://img.shields.io/github/v/release/frstrtr/p2pool-merged-v36)](https://github.com/frstrtr/p2pool-merged-v36/releases/latest)
[![License](https://img.shields.io/github/license/frstrtr/p2pool-merged-v36)](LICENSE)

Decentralized Scrypt mining pool for **Litecoin + Dogecoin** (merged mining), building on the p2pool protocol with V36 share format.

## What's different from jtoomim/p2pool (V35)

### Protocol & Consensus
- **V36 share format** — extends the share chain with `pubkey_type` field (native P2SH and bech32 address support) and AuxPoW commitment fields; backward-compatible transition via built-in version signaling with 95% activation threshold
- **Merged mining (AuxPoW)** — mine LTC and DOGE simultaneously on the same decentralized share chain; merged chain rewards are distributed through the same PPLNS consensus mechanism as parent chain rewards
- **MM-Adapter bridge** — Python 3 adapter that translates between P2Pool's merged mining protocol and standard Dogecoin Core RPC (`createauxblock`/`submitauxblock`), enabling merged mining without custom daemon patches
- **Multi-chain address handling** — automatic cross-chain address conversion (LTC P2SH → DOGE P2SH, bech32 → P2PKH for chains without SegWit); full validation pipeline for P2PKH, P2SH, P2WPKH

### Node Operation
- **Share redistribution (`--redistribute`)** — configurable handling of shares from unnamed/broken miners: `pplns` (proportional), `fee` (operator), `boost` (help tiny miners get their first payout), `donate` (development fund)
- **Multiaddress coinbase** — miners specify both LTC and DOGE payout addresses via stratum; each chain's coinbase pays to the miner's native address format

### Dashboard
- Live V35→V36 transition signaling with version counts and activation progress
- Best share display with network difficulty comparison (parent + merged chains)
- Share format distribution visualization
- Context-aware transition status indicators

### Architecture
- Event-driven cache invalidation (replaces fixed-interval polling)
- Clean separation of parent/merged chain logic throughout the codebase
- Comprehensive address type preservation across all code paths

## 🎉 Litecoin + Dogecoin Merged Mining

**Status:** ✅ **PRODUCTION READY** - Mainnet merged mining operational

### Key Features
- ✅ Litecoin scrypt mining with Dogecoin AuxPoW merged mining
- ✅ Multiaddress coinbase - miners specify both LTC and DOGE addresses
- ✅ Automatic address conversion (same pubkey_hash, correct network format)
- ✅ V36 combined donation marker (P2SH scriptPubKey over 1-of-2 redeem policy)
- ✅ Node-owner fees are sharechain-weighted on both parent and merged chains
- ✅ Real-time monitoring dashboard
- ✅ MM-Adapter bridge for standard Dogecoin daemon compatibility

### Architecture

```
┌─────────────┐    Stratum   ┌─────────────┐   JSON-RPC   ┌─────────────┐
│   Miners    │◀───────────▶│   P2Pool    │◀───────────▶│  Litecoin   │
│  (scrypt)   │   Port 9327  │  (PyPy 2.7) │  Port 9332   │   Core      │
└─────────────┘              └──────┬──────┘              └─────────────┘
                                    │
                                    │ JSON-RPC (Port 44556)
                                    ▼
                             ┌──────────────┐   JSON-RPC   ┌─────────────┐
                             │  MM-Adapter  │◀───────────▶│  Dogecoin   │
                             │ (Python 3)   │  Port 22555  │   Core      │
                             └──────────────┘              └─────────────┘
```

## 📋 Documentation

**⚠️ IMPORTANT**: For complete installation instructions, troubleshooting, and configuration, please see:

### **[📖 INSTALL.md - Complete Installation Guide](INSTALL.md)**

The installation guide covers:
- ✅ System requirements and dependencies
- ✅ Litecoin Core & Dogecoin Core installation and configuration
- ✅ Python 2.7 / PyPy setup (modern Ubuntu/Debian)
- ✅ Scrypt hashing setup (`pip install scrypt` or legacy ltc_scrypt C extension)
- ✅ Standalone vs Multi-node configuration
- ✅ Common issues and solutions (OpenSSL, missing modules, etc.)
- ✅ Performance tuning and security
- ✅ **macOS (Intel)** setup via Homebrew (PyPy 2.7 + MM-Adapter)

> **Windows users**: See **[WINDOWS_DEPLOYMENT.md](docs/WINDOWS_DEPLOYMENT.md)** for WSL2, Docker, and native Windows setup instructions.
>
> **macOS (Intel) users**: See the **[macOS section in INSTALL.md](INSTALL.md#macos-intel-installation)** for Homebrew-based setup — tested on macOS 26.x (x86_64).

### Other Documentation

| Document | Description |
|----------|-------------|
| [mm-adapter/README.md](mm-adapter/README.md) | Merged mining adapter setup & config reference |
| [MULTIADDRESS_MINING_GUIDE.md](docs/MULTIADDRESS_MINING_GUIDE.md) | Multi-address mining configuration |
| [CUSTOM_NETWORK_GUIDE.md](docs/CUSTOM_NETWORK_GUIDE.md) | Adding support for new cryptocurrencies |
| [ASIC_SUPPORT_COMPLETE.md](docs/ASIC_SUPPORT_COMPLETE.md) | BIP320 version-rolling & Scrypt ASIC support details |
| [SHARE_ARCHIVE_README.md](docs/SHARE_ARCHIVE_README.md) | Share archival and recovery |
| [V36_TRANSITION_GUIDE.md](docs/V36_TRANSITION_GUIDE.md) | V35→V36 transition stages, AutoRatchet, dashboard legend |
| [WINDOWS_DEPLOYMENT.md](docs/WINDOWS_DEPLOYMENT.md) | Windows 10/11 deployment (WSL2, Docker, Native) — tested end-to-end |
| [SECURITY_AUDIT_2026_02.md](docs/SECURITY_AUDIT_2026_02.md) | Security audit report — 41 findings, origin classification, fix status |
| [FUTURE.md](docs/FUTURE.md) | Roadmap — redistribution system (`--redistribute`), graduated boost, hybrid mode |

---

## 🚀 Quick Start: Litecoin + Dogecoin Merged Mining

### Docker (fastest)

Requires [Docker Engine](https://docs.docker.com/engine/install/) or [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/).
First build takes ~3 minutes; subsequent starts are instant. Share chain sync takes ~2 minutes after first start.

```bash
git clone https://github.com/frstrtr/p2pool-merged-v36.git
cd p2pool-merged-v36

# Configure
cp .env.example .env                                    # edit: set passwords and LTC payout address
cp mm-adapter/config.docker.example.yaml mm-adapter/config.docker.yaml  # edit: set DOGE credentials

# Start everything (builds on first run)
docker compose up -d

# Check status
docker compose ps          # both containers should show "healthy"
docker compose logs -f     # watch startup logs

# Dashboard — available once share chain syncs
# http://localhost:9327/static/dashboard.html
```

See [docker-compose.yml](docker-compose.yml) and [.env.example](.env.example) for all settings.
For standalone LTC-only mode (no Dogecoin), see [WINDOWS_DEPLOYMENT.md](docs/WINDOWS_DEPLOYMENT.md#option-2-docker-on-wsl2).

### Manual Install (Linux/WSL2)

#### Prerequisites

1. **Litecoin Core** (v0.21+) - Fully synced on mainnet
2. **Dogecoin Core** (v1.14.7+) - Fully synced on mainnet
3. **PyPy 2.7** - For running P2Pool
4. **Python 3.10+** - For running MM-Adapter

### Step 1: Install P2Pool

```bash
# Clone repository
git clone https://github.com/frstrtr/p2pool-merged-v36.git
cd p2pool-merged-v36

# Install PyPy 2.7 (Ubuntu 24.04+)
wget https://downloads.python.org/pypy/pypy2.7-v7.3.20-linux64.tar.bz2
tar xjf pypy2.7-v7.3.20-linux64.tar.bz2
export PATH="$PWD/pypy2.7-v7.3.20-linux64/bin:$PATH"

# Install P2Pool dependencies (includes scrypt hashing)
pypy -m ensurepip
pypy -m pip install twisted pycryptodome 'scrypt>=0.8.0,<=0.8.22' ecdsa
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

Edit `config.yaml` (see [mm-adapter/config.example.yaml](mm-adapter/config.example.yaml) for all options):
```yaml
server:
  host: "127.0.0.1"
  port: 44556
  rpc_user: "dogecoinrpc"
  rpc_password: "YOUR_SECURE_PASSWORD"

upstream:
  host: "127.0.0.1"
  port: 22555
  rpc_user: "dogecoinrpc"
  rpc_password: "YOUR_SECURE_PASSWORD"
  timeout: 30

chain:
  name: "dogecoin"
  chain_id: 98
  network_magic: "c0c0c0c0"
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
# Replace IPs with 127.0.0.1 if all daemons run on the same machine,
# or use LAN IPs if daemons run on separate machines.
# --merged-coind-address always points to the local MM-Adapter (127.0.0.1).
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
    --merged-coind-rpc-password YOUR_SECURE_PASSWORD \
    --address YOUR_LEGACY_LTC_ADDRESS \
    --give-author 1 \
    -f 1 \
    --redistribute pplns \
    --disable-upnp \
    litecoinrpc YOUR_LTC_RPC_PASSWORD
```

  Notes on payout semantics:
  - `-f/--fee` and `--give-author` influence sharechain weights (PPLNS), so per-block percentages are probabilistic and can vary block-to-block.
  - A separate merged-chain node-fee output may be `0` in normal PPLNS mode; node-owner value is represented through weighted payout addresses.
  - As more shares/blocks are observed (especially with substantial window turnover), measured averages converge toward configured percentages.

### Step 6: Connect Miners

Point your scrypt miners to:
```
stratum+tcp://YOUR_IP:9327
```

**Username formats:**
- Basic: `LTC_ADDRESS`
- With DOGE address: `LTC_ADDRESS,DOGE_ADDRESS`
- With worker name (dot): `LTC_ADDRESS,DOGE_ADDRESS.worker1`
- With worker name (underscore): `LTC_ADDRESS,DOGE_ADDRESS_worker1`

**Example:**
```
Username: YOUR_LTC_ADDRESS,YOUR_DOGE_ADDRESS.rig1
Password: x
```

### Supported Address Types

P2Pool supports three Litecoin address types for the operator (`-a`) and stratum miner addresses.
Each type produces its **native** scriptPubKey in the LTC coinbase — no unnecessary conversions.

| Address Type | Prefix (Mainnet) | Prefix (Testnet) | Script Type in Coinbase | How to Generate |
|---|---|---|---|---|
| **P2PKH** (Legacy) | `L...` | `m...` / `n...` | `OP_DUP OP_HASH160 <hash> OP_EQUALVERIFY OP_CHECKSIG` | `litecoin-cli getnewaddress "" legacy` |
| **P2SH** (Script Hash) | `M...` / `3...` | `Q...` / `2...` | `OP_HASH160 <hash> OP_EQUAL` | `litecoin-cli getnewaddress "" p2sh-segwit` |
| **P2WPKH** (Bech32 SegWit v0) | `ltc1q...` (42 chars) | `tltc1q...` (43 chars) | `OP_0 <20-byte-hash>` (`witness_v0_keyhash`) | `litecoin-cli getnewaddress "" bech32` |

> **Note:** P2WSH (`ltc1q...` 62 chars), P2TR/Taproot (`ltc1p...`) and future witness versions are **not supported** — their 32-byte hashes cannot be safely converted to 20-byte merged chain addresses.

### Supported Merged Chain Address Types (Dogecoin)

Miners can provide an explicit Dogecoin address via the stratum username (separated by `,`).
Each type produces its **native** scriptPubKey in the DOGE merged coinbase. Dogecoin does **not** support SegWit.

| Address Type | Prefix (Mainnet) | Prefix (Testnet) | Script Type in Coinbase | How to Generate |
|---|---|---|---|---|
| **P2PKH** (Legacy) | `D...` | `n...` | `OP_DUP OP_HASH160 <hash> OP_EQUALVERIFY OP_CHECKSIG` | `dogecoin-cli getnewaddress "" legacy` |
| **P2SH** (Script Hash) | `9...` / `A...` | `2...` | `OP_HASH160 <hash> OP_EQUAL` | `dogecoin-cli getnewaddress "" p2sh-segwit` |

> **Note:** Dogecoin has **no SegWit support** (`SOFTFORKS_REQUIRED = set()`). Bech32 addresses cannot be used.
> If no explicit DOGE address is provided, P2Pool auto-converts the LTC address hash to a DOGE address
> using the corresponding version byte (P2PKH→P2PKH, P2SH→P2SH, Bech32→P2PKH).

#### Merged Chain (Dogecoin) Address Conversion

When mining Litecoin + Dogecoin, miner payouts are distributed on **both chains**. The merged chain address is derived as follows:

| Miner Provides | Merged Chain Payout | Notes |
|---|---|---|
| `LTC_ADDR,DOGE_ADDR` | Uses the explicit DOGE address directly | **Recommended** — full control over DOGE payouts |
| `LTC_ADDR` only (P2PKH) | Auto-converts `HASH160(pubkey)` → DOGE P2PKH | Same pubkey hash, different version byte |
| `LTC_ADDR` only (Bech32) | Auto-converts 20-byte witness program → DOGE P2PKH | Bech32 → P2PKH on DOGE (no SegWit on DOGE) |
| `LTC_ADDR` only (P2SH) | Auto-converts `HASH160(script)` → DOGE P2SH | See ⚠️ warning below |
| `LTC_ADDR,INVALID_ADDR` | Logs warning, falls back to auto-conversion | Invalid addresses are rejected gracefully |

> ### ⚠️ V35→V36 Transition: Merged Address Limitations
>
> **Current status (Feb 2026):** The network is in hybrid mode — nodes create **V35 shares** while voting for V36 activation (95% threshold). V35 shares structurally **cannot store** explicit merged chain addresses. This has important consequences:
>
> | Scenario | DOGE Payout Address Used |
> |---|---|
> | **Your node** finds a merged block | ✅ Your explicit DOGE address (from stratum) — used for the 0.5% finder fee AND the PPLNS distribution on your local node |
> | **Another node** finds a merged block | ❌ Auto-converted from your LTC pubkey_hash — the other node has no access to your stratum session and V35 shares don't carry merged addresses |
>
> **What this means for miners:**
> - If you use a **P2PKH** LTC address (`L...`), the auto-converted DOGE address is derived from the **same public key hash**. If you control the private key, you likely control both addresses. The explicit DOGE address you provide may differ but is only used when your local node finds the block.
> - If you use a **bech32** LTC address (`ltc1q...`), the auto-converted DOGE address is a P2PKH derived from the same 20-byte hash — same situation as P2PKH.
> - If you use a **P2SH** LTC address (`M...`/`3...`), the auto-converted DOGE P2SH may be **unspendable** (see P2SH warning below). Providing an explicit DOGE address via stratum only protects you on your own node's blocks.
>
> **What this means for node operators:**
> - The `current_merged_payouts` API endpoint shows the correct stratum-explicit address for locally connected miners (marked `source: "stratum-explicit"`).
> - Shares from remote peers always use auto-converted addresses until V36 activates.
> - Check `/local_stats` for `v36_active` and `auto_ratchet_state` to monitor activation progress.
>
> **After V36 activates:** Every V36 share embeds the miner's explicit DOGE address in the share chain (`merged_addresses` field). All nodes — local and remote — will use the correct address for PPLNS distribution. This is the permanent fix.

#### Invalid Address Redistribution

When a miner connects with an invalid or unparseable parent chain (LTC) address, their mining
rewards are **probabilistically redistributed** to all other valid miners proportional to their
PPLNS hashrate contribution. This uses the same consensus-safe mechanism as the node operator fee
(`-f` flag): the share's `pubkey_hash` field is replaced at creation time with a randomly-selected
valid miner's address, weighted by PPLNS work. No coinbase or consensus changes are required.

**Policy:** If the parent (LTC) address is invalid, parent chain rewards are redistributed.
However, a valid explicit merged (DOGE) address is **preserved** — the miner still receives
their merged chain payouts. Only when no valid merged address is provided does the merged
payout auto-convert from the redistributed miner's pubkey_hash.

| # | Parent (LTC) | Merged (DOGE) | LTC Payout | DOGE Payout |
|---|---|---|---|---|
| 1 | Valid | Valid (explicit) | Miner (correct) | Miner (correct) |
| 2 | Valid | Invalid / missing | Miner (correct) | Auto-converts from LTC pubkey_hash |
| 3 | Invalid | Invalid / missing | Redistributed to random PPLNS miner | Auto-converts from redistributed pubkey_hash |
| 4 | Invalid | **Valid (explicit)** | Redistributed to random PPLNS miner | **Miner keeps DOGE** (valid address preserved) |

**Stratum separators:** `,` separates parent from merged address. `.` or `_` separates the worker
name. `+` and `/` set pseudoshare and share difficulty. Any other characters in the address portion
that prevent parsing will make the address invalid, triggering redistribution.

**Example:** A miner connecting as `XXX_rig1` has user=`XXX` (invalid LTC address), worker=`rig1`.
Their share rewards go to a randomly-selected valid miner from the PPLNS window.

#### `--redistribute` Mode

The `--redistribute` flag controls **how** shares from miners with invalid/empty/broken stratum
credentials are handled. It only affects the `pubkey_hash` stamped into shares created on your
node — no consensus or coinbase changes are required, so all modes are safe to use on any node.

```bash
pypy run_p2pool.py ... --redistribute MODE
```

| Mode | Behaviour | Use Case |
|---|---|---|
| `pplns` | **Default.** Redistributes to a random valid miner, weighted by PPLNS hashrate share. Equivalent to spreading the invalid miner's rewards across all current miners proportionally. | Fair default — rewards flow back to the pool in proportion to work done. |
| `fee` | 100 % to the **node operator** (same address as `-f 100` would use for these shares). | Node operators who want to capture unclaimed rewards as additional operator income. |
| `boost` | Gives the share to a random **connected stratum miner who currently has zero shares** in the PPLNS window. If no zero-share miners are connected, falls back to `pplns` behaviour. | Altruistic nodes that want to help tiny/new miners get their first payout faster. |
| `donate` | 100 % to the **development donation address**. V36-aware: uses a combined P2SH donation address when V36 is active, otherwise uses the legacy P2PK→P2PKH donation script. | Support continued P2Pool development with unclaimed shares. |

**Interaction with other flags:**
- `--redistribute` only applies to shares where the miner's parent-chain address is invalid. Miners with valid addresses are never affected.
- `-f` / `--fee` (node operator fee) is applied **separately** as a percentage of every share. `--redistribute fee` is a distinct mechanism that only kicks in for broken credentials.
- `--give-author` (donation percentage) is also separate. `--redistribute donate` sends the entire invalid share to the donation address, while `--give-author` donates a fraction of every share.

**Examples:**
```bash
# Help small miners get started
pypy run_p2pool.py ... --redistribute boost

# Support development
pypy run_p2pool.py ... --redistribute donate
```

> ⚠️ **P2SH Conversion Warning:** When a P2SH Litecoin address (starting with `M` or `3`) is auto-converted to Dogecoin, the resulting DOGE P2SH address references the **same redeem script hash**. P2Pool cannot reverse a script hash to inspect the underlying redeem script, so it converts all P2SH addresses unconditionally. Miners using P2SH have **two options**:
>
> 1. **Ensure the redeem script uses only Dogecoin-compatible opcodes** — bare multisig (`OP_CHECKMULTISIG`), P2PK (`OP_CHECKSIG`), P2PKH-in-P2SH (`OP_DUP OP_HASH160 ... OP_EQUALVERIFY OP_CHECKSIG`), or any script built from opcodes that both Litecoin and Dogecoin support. These convert safely and funds are spendable on both chains.
> 2. **Provide an explicit Dogecoin address** via stratum comma syntax to bypass auto-conversion entirely:
>    ```
>    Username: MLTCp2shAddress,DDOGElegacyAddress.worker1
>    ```
>
> **What to avoid:** If the P2SH redeem script contains SegWit witness programs (P2SH-P2WPKH / P2SH-P2WSH), the converted DOGE P2SH address becomes **anyone-can-spend** — the redeemScript `OP_0 <20-byte-hash>` evaluates to `true` without any signature on a non-SegWit chain, and anyone who learns the redeemScript (revealed on the first LTC spend from that address) can steal the DOGE funds. Most modern Litecoin wallets default to P2SH-P2WPKH, so **if in doubt, use option 2**.

#### Example: Getting Addresses for Mining

```bash
# Litecoin addresses (pick one format)
litecoin-cli getnewaddress "" legacy         # P2PKH:  LV...
litecoin-cli getnewaddress "" p2sh-segwit    # P2SH:   M...
litecoin-cli getnewaddress "" bech32         # Bech32: ltc1q...

# Dogecoin address (always use legacy - DOGE has no SegWit)
dogecoin-cli getnewaddress "" legacy         # P2PKH:  D...

# Connect with explicit DOGE address (recommended)
# Username: ltc1q...,DDogeAddress.rig1

# Connect with auto-conversion (bech32 → DOGE P2PKH)
# Username: ltc1q....rig1
```

---

## General Installation & Usage

### Requirements

* **Litecoin Core**: >=0.21.0 (for parent chain)
* **Dogecoin Core**: >=1.14.7 (for merged mining child chain)
* **Python**: 2.7 (via PyPy recommended)
* **Twisted**: >=19.10.0
* **pycryptodome**: >=3.9.0
* **ltc_scrypt**: Scrypt hashing — `pip install 'scrypt>=0.8.0,<=0.8.22'` (v0.8.23+ uses f-strings, breaks Python 2.7/PyPy). Falls back to legacy C extension in `litecoin_scrypt/` if py-scrypt is unavailable.

### Features

* ✅ **Scrypt PoW**: Litecoin/Dogecoin Scrypt (N=1024, r=1, p=1) mining
* ✅ **Merged Mining**: Simultaneous LTC + DOGE mining with AuxPoW
* ✅ **Modern Scrypt ASIC Compatible**: Works with Antminer L3+/L7, Goldshell LT5/LT6, Elphapex DG1, etc.
* ✅ **BIP320 Version-Rolling**: Stratum `mining.configure` for version-mask negotiation
* ✅ **Enhanced Difficulty Control**: Support for +difficulty and /difficulty modifiers
* ✅ **Variable Difficulty**: Configurable vardiff with --share-rate parameter
* ✅ **Backward Compatible**: CPU/GPU miners still supported

### Modern Ubuntu/Debian (24.04+)

Python 2 is no longer available. Use PyPy:

```bash
# Install PyPy
sudo snap install pypy --classic

# Install dependencies
pypy -m pip install twisted==19.10.0 pycryptodome 'scrypt>=0.8.0,<=0.8.22' ecdsa

# Clone and setup
git clone https://github.com/frstrtr/p2pool-merged-v36.git
cd p2pool-merged-v36

# Run P2Pool (Litecoin + Dogecoin merged mining)
pypy run_p2pool.py --net litecoin -a YOUR_LTC_ADDRESS
```

**See [INSTALL.md](INSTALL.md) for detailed instructions.**

### Ubuntu 24.04 Automated Installer

For Ubuntu 24.04 systems, we provide an automated installer script that sets up PyPy2, builds a local OpenSSL 1.1, and configures p2pool with systemd integration:

```bash
./scripts/install_p2pool_ubuntu_2404.sh
```

### Older Systems (Ubuntu 20.04 and earlier)

If Python 2.7 is still available:

```bash
sudo apt-get install python2 python2-dev python2-twisted python2-pip gcc g++
git clone https://github.com/frstrtr/p2pool-merged-v36.git
cd p2pool-merged-v36
pip install 'scrypt>=0.8.0,<=0.8.22'
python2 run_p2pool.py --net litecoin -a YOUR_LTC_ADDRESS
```

## Mining to P2Pool

Point your miner to:
```
stratum+tcp://YOUR_IP:9327
```

Username: Your Litecoin address (optionally with DOGE address — see [Multiaddress Mining](#-multiaddress-mining))
Password: anything

### Advanced Username Options

You can append difficulty modifiers to your Litecoin address:

**Pseudoshare difficulty** (for vardiff tuning):
```
YOUR_ADDRESS+DIFFICULTY
Example: ltc1qexampleaddress+4096
```

**Actual share difficulty** (fixed minimum):
```
YOUR_ADDRESS/DIFFICULTY
Example: ltc1qexampleaddress/65536
```

**Worker names** (for monitoring — both `.` and `_` are valid separators):
```
YOUR_ADDRESS.worker_name
YOUR_ADDRESS_worker_name
Example: ltc1qexampleaddress.asic1
Example: ltc1qexampleaddress_asic1
```

## Configuration Modes

### Standalone Mode (Solo/Testing)
Edit `p2pool/networks/litecoin.py`:
```python
PERSIST = False  # No peers required
```

### Multi-Node Mode (Pool Mining)
Edit `p2pool/networks/litecoin.py`:
```python
PERSIST = True  # Connect to P2Pool network
```

**⚠️ IMPORTANT**: When upgrading to the latest version with V36 share format:
- **Delete old sharechain data**: `data/litecoin/shares.*` and `data/litecoin/graph_db`
- Old shares are incompatible due to V36 field changes
- All nodes in the P2Pool network must update together
- **Protection**: Incompatible shares are validated and rejected BEFORE entering sharechain
- Outdated peers receive clear upgrade instructions in logs

**For detailed configuration, see [INSTALL.md](INSTALL.md).**

## Command Line Options

```bash
pypy run_p2pool.py --help
```

Common options:
- `--net litecoin` - Use Litecoin mainnet
- `--net litecoin_testnet` - Use Litecoin testnet
- `-a ADDRESS` - Your Litecoin payout address
- `--bitcoind-rpc-port 9332` - Litecoin RPC port (default: 9332)
- `--bitcoind-address 127.0.0.1` - Litecoin RPC address
- `--share-rate SECONDS` - Target seconds per pseudoshare (default: 3)
- `--merged URL` - Merged mining daemon URL (Dogecoin)

## Troubleshooting

### Common Issues

All issues and solutions are documented in **[INSTALL.md](INSTALL.md)**, including:

- ❌ `ImportError: No module named ltc_scrypt` → Run `pip install 'scrypt>=0.8.0,<=0.8.22'` (or build legacy C extension: `cd litecoin_scrypt && python setup.py install`)
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
- ✅ Wrong module import paths fixed
- ✅ Block hash formatting (zero-padding)
- ✅ Empty payee address handling
- ✅ Removed defunct bootstrap nodes
- ✅ Standalone mode support (PERSIST=False)

### Enhanced Features (December 2025)
- ✅ Enhanced difficulty control (+diff, /diff modifiers)
- ✅ DUMB_SCRYPT_DIFF constant for accurate scrypt difficulty display
- ✅ Worker IP tracking infrastructure
- ✅ Configurable vardiff with --share-rate parameter (default: 10 seconds)
- ✅ Improved min_share_target bounds for better difficulty adjustment
- ✅ Fixed got_response() signature compatibility
- ✅ **Block luck calculation** with time-weighted average hashrate
- ✅ **Hashrate sampling** for precise luck statistics
- ✅ **Telegram notifications** for block announcements
- ✅ **Block status tracking** (confirmed/orphaned/pending)
- ✅ **Extended coinbase support**: Handles OP_RETURN platform payments in coinbase
- ✅ **Packed object compatibility**: Fixed share verification for _script field handling
- ✅ **Mainnet ready**: Full support for masternode/platform/superblock payment structures
- ✅ **Solo mining support**: Removed peer connection requirement - works standalone with PERSIST=True
- ✅ **Incompatible share protection**: Pre-validation prevents outdated shares from entering sharechain
- ✅ **Smart peer connections**: Temporary bans for failing peers, counts total connections (incoming+outgoing)

## Port Forwarding

If behind NAT, forward these ports:
- **9326**: P2Pool P2P (for peer connections)
- **9327**: Stratum (for miners)

Do NOT forward port 9332 (Litecoin RPC - security risk)

## Web Interface & API

P2Pool provides a web interface at `http://YOUR_IP:9327/`:

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
2. Edit `data/litecoin/telegram_config.json`:
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
# Default values (litecoin.py)
CONNECTION_WORKER_ELEVATED = 4.0   # Flag if >4 connections per worker
CONNECTION_WORKER_WARNING = 6.0     # Flag as high if >6 connections per worker
```

This ensures legitimate miners running multiple machines from the same IP are not incorrectly flagged as threats, while still detecting actual connection flooding attempts.

### Persistent Block History

P2Pool stores all found blocks in `data/litecoin/block_history.json` for permanent record-keeping. This allows the web interface to display complete historical data including:

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
    --datadir data/litecoin \
    --blocks-file historical_blocks.txt \
    --bitcoind-rpc-username YOUR_RPC_USER \
    --bitcoind-rpc-password YOUR_RPC_PASS
```

Or specify blocks directly:
```bash
pypy populate_block_history.py \
    --datadir data/litecoin \
    --blocks 2389670,2389615,2389577 \
    --bitcoind-rpc-username YOUR_RPC_USER \
    --bitcoind-rpc-password YOUR_RPC_PASS
```

The script will query litecoind to fetch block rewards, timestamps, and difficulty, then merge this data into your block history. This ensures consistent graphs and statistics even for blocks found before the current p2pool installation.

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
* jakehaas, vertoe, chaeplin, dstorm, poiuty, elbereth and mr.slaveg from the early P2Pool community
