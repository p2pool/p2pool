# P2Pool Windows 10/11 Deployment Guide

> **Tested on**: Windows 11 23H2 + WSL2 Ubuntu 22.04 (kernel 5.15.167.4-microsoft-standard-WSL2)
> with bridged networking to LAN daemon nodes.
>
> **Last verified**: 2026-02-28 — Full merged mining (LTC+DOGE) successfully started in WSL2.
> P2Pool connected to LTC daemon, synced shares from 6 peers, MM-Adapter bridged to DOGE mainnet
> at block 6,104,322.

## TL;DR — Which Approach Should I Use?

| Approach | Difficulty | Recommended For |
|----------|-----------|-----------------|
| **WSL2 (Ubuntu)** | Easy | Most users — best compatibility, zero code changes needed |
| **Docker (WSL2 backend)** | Medium | Users who want full-stack isolation and reproducibility |
| **Native Windows** | Hard | Only if you need bare-metal performance or can't use WSL2 |

**Our recommendation: WSL2 (Ubuntu 22.04+)**. P2Pool requires Python 2.7 (via PyPy), and the entire install guide, community tooling, and CI are Linux-native. WSL2 gives you a real Linux kernel with near-native I/O performance, and all existing instructions work verbatim.

---

## Option 1: WSL2 (Recommended)

### Prerequisites
- Windows 10 version 2004+ (Build 19041+) or Windows 11
- 8GB+ RAM, 120GB+ free disk (blockchain data)

### Step 1 — Install WSL2

Open PowerShell **as Administrator**:
```powershell
wsl --install -d Ubuntu-22.04
```

Reboot when prompted, then launch "Ubuntu 22.04" from Start Menu and create a UNIX user.

Verify:
```powershell
wsl -l -v
#  NAME            STATE           VERSION
#  Ubuntu-22.04    Running         2
```

> **Tip:** If VERSION shows 1, upgrade with `wsl --set-version Ubuntu-22.04 2`.

### Step 2 — Enable systemd and passwordless sudo

Check `/etc/wsl.conf` inside WSL:
```bash
cat /etc/wsl.conf
```

It must contain:
```ini
[boot]
systemd=true
```

If missing, add it and restart WSL (`wsl --shutdown` from PowerShell, then relaunch).

#### Passwordless sudo (eliminates password prompts in WSL)

By default, WSL will ask for your password on every `sudo` command. Since `wsl -u root`
runs as root without a password, you can use it to configure `NOPASSWD`:

```powershell
# From PowerShell — replace <username> with your WSL username
wsl -d Ubuntu-22.04 -u root -- bash -c "echo '<username> ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/<username> && chmod 440 /etc/sudoers.d/<username>"
```

Verify — this should print `root` with **no password prompt**:
```powershell
wsl -d Ubuntu-22.04 -- sudo whoami
# root
```

> **Why this matters**: Many installation steps use `sudo`. Without `NOPASSWD`,
> every `sudo apt install`, `sudo systemctl`, etc. will interrupt you with a
> password prompt — especially annoying when running multi-step scripts.

### Step 3 — Configure Bridged Networking (for LAN daemon access)

If your Litecoin/Dogecoin daemons run on separate LAN machines,
WSL2 needs to be on the same subnet. There are two approaches:

#### Option A: Mirrored Networking (Windows 11 22H2+, simplest)

Create or edit `%UserProfile%\.wslconfig` on Windows:
```ini
[wsl2]
networkingMode=mirrored
```

Then restart WSL:
```powershell
wsl --shutdown
wsl -d Ubuntu-22.04
```

WSL2 shares the host's IP and can reach LAN devices directly.

#### Option B: Bridged Adapter (any Windows 10/11)

Create or edit `%UserProfile%\.wslconfig`:
```ini
[wsl2]
networkingMode=bridged
vmSwitch=WSLBridge
```

Then create the Hyper-V switch in PowerShell (Admin):
```powershell
# Find your physical adapter name
Get-NetAdapter | Where-Object {$_.Status -eq "Up"} | Select-Object Name, InterfaceDescription

# Create external switch (replace "Ethernet" with your adapter name)
New-VMSwitch -Name "WSLBridge" -NetAdapterName "Ethernet" -AllowManagementOS $true
```

Restart WSL. Inside WSL, verify connectivity:
```bash
ip addr show eth0  # or eth1 — should have a LAN IP
ping -c1 <LTC_DAEMON_IP>  # test reach to your LAN daemon
```

### Step 4 — SSH Key Setup (passwordless access to LAN nodes and WSL)

#### Generate key (if none exists)

From PowerShell on the Windows host:
```powershell
# Check if key exists
Test-Path ~/.ssh/id_ed25519.pub

# If False, generate one:
ssh-keygen -t ed25519 -C "p2pool-win"
```

#### Deploy to LAN nodes

Use WSL to deploy (`ssh-copy-id` handles authorized_keys permissions):
```bash
# From inside WSL2, use the Windows key
# Replace <winuser> with your Windows username, <remoteuser>@<ip> with each target
ssh-copy-id -f -i /mnt/c/Users/<winuser>/.ssh/id_ed25519.pub <remoteuser>@<LTC_DAEMON_IP>
ssh-copy-id -f -i /mnt/c/Users/<winuser>/.ssh/id_ed25519.pub <remoteuser>@<DOGE_DAEMON_IP>
```

> **Note**: The `-f` flag is needed because the private key is on the Windows
> side and `ssh-copy-id` can't find it at the default WSL path.

#### Deploy to WSL2 itself (for SSH from Windows into WSL)

```bash
# Inside WSL2 — replace <winuser> with your Windows username
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cat /mnt/c/Users/<winuser>/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Install and enable sshd in WSL2:
```bash
sudo apt-get install -y openssh-server
sudo systemctl enable ssh
sudo systemctl start ssh
```

For security, disable password auth (key-only):
```bash
sudo sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

Test from PowerShell:
```powershell
ssh -o BatchMode=yes <username>@localhost "hostname && echo SSH-OK"
# Should print your WSL hostname and SSH-OK with no password prompt
```

#### Verify all connections

```powershell
ssh <username>@<LTC_DAEMON_IP> "hostname"   # → your LTC daemon host
ssh <username>@<DOGE_DAEMON_IP> "hostname"  # → your DOGE daemon host
ssh <username>@localhost "hostname"          # → your WSL hostname
```

> **Host key changes**: If WSL2 is restarted, its SSH host key may change.
> Fix with: `ssh-keygen -R localhost` then reconnect.

### Step 5 — Install PyPy 2.7

Inside WSL2:

```bash
# Install build dependencies
sudo apt-get update
sudo apt-get install -y build-essential libssl-dev libffi-dev wget curl git screen tmux

# Download PyPy 2.7 (same version used on production nodes)
# NOTE: Download to ~ not /tmp — WSL2 cleans /tmp on restart
cd ~
wget https://downloads.python.org/pypy/pypy2.7-v7.3.17-linux64.tar.bz2

# Extract
tar xjf ~/pypy2.7-v7.3.17-linux64.tar.bz2
rm ~/pypy2.7-v7.3.17-linux64.tar.bz2

# Add to PATH (add this to ~/.bashrc for persistence)
export PATH="$HOME/pypy2.7-v7.3.17-linux64/bin:$PATH"
echo 'export PATH="$HOME/pypy2.7-v7.3.17-linux64/bin:$PATH"' >> ~/.bashrc

# Verify
pypy --version
# Python 2.7.18 (...)
```

> **Why tarball instead of snap?** Snap works too (`sudo snap install pypy --classic`),
> but the tarball matches the production nodes (pypy2.7-v7.3.20) and avoids snap's
> glibc isolation issues when building C extensions like coincurve.

### Step 6 — Install pip and Python dependencies

```bash
# Install pip for PyPy
cd /tmp
wget https://bootstrap.pypa.io/pip/2.7/get-pip.py
pypy get-pip.py

# IMPORTANT: Pin incremental before installing twisted
# Without this, pip pulls incremental>=22 which uses `typing` (absent in Python 2.7)
pypy -m pip install 'incremental<22'

# Install core dependencies
pypy -m pip install twisted==20.3.0 pycryptodome 'scrypt>=0.8.0,<=0.8.22' ecdsa

# Verify scrypt works (this is the primary hashing backend)
pypy -c "import scrypt; print('scrypt OK')"
```

> **Note on scrypt version**: Versions above 0.8.22 use Python 3 f-strings and
> are incompatible with PyPy 2.7.
>
> **Note on incremental**: Must be pinned to `<22` *before* running `pip install twisted`.
> Otherwise twisted pulls incremental 22.10+ which fails with `ImportError: No module named typing`.

### Step 7 — Clone and verify P2Pool

```bash
cd ~
git clone https://github.com/frstrtr/p2pool-merged-v36.git
cd p2pool-merged-v36

# Verify scrypt hashing works
# ltc_scrypt.py is a wrapper — it imports the pip `scrypt` package automatically.
# No need to build the litecoin_scrypt/ C extension when pip scrypt is installed.
pypy -c "import ltc_scrypt; print('ltc_scrypt OK')"
```

> **How scrypt hashing works**: `ltc_scrypt.py` tries `import scrypt` (the pip package)
> first. Only if that fails does it fall back to the bundled `litecoin_scrypt/` C extension.
> Since we installed `scrypt` in Step 6, the C extension build is **not needed**.

### Step 8 — Set up MM-Adapter (for merged mining)

The MM-Adapter bridges P2Pool and Dogecoin Core. It runs on Python 3 (separate from P2Pool).

```bash
# Install python3-venv if not present (common on minimal Ubuntu installs)
sudo apt install -y python3.10-venv

cd ~/p2pool-merged-v36/mm-adapter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `config_mainnet.yaml`:
```yaml
# MM Adapter - Mainnet Configuration
# Litecoin + Dogecoin Merged Mining

# Adapter server settings (P2Pool connects here)
server:
  host: "0.0.0.0"
  port: 44556
  rpc_user: "dogecoinrpc"
  rpc_password: "<DOGE_RPC_PASSWORD>"    # Must match P2Pool --merged-coind-rpc-password

# Upstream daemon (Dogecoin Mainnet)
upstream:
  host: "<DOGE_DAEMON_IP>"               # e.g. 127.0.0.1 or LAN IP
  port: 22555                             # Dogecoin mainnet RPC port
  rpc_user: "dogecoinrpc"                # Must match dogecoin.conf rpcuser
  rpc_password: "<DOGE_RPC_PASSWORD>"    # Must match dogecoin.conf rpcpassword
  timeout: 30

# Chain configuration
chain:
  name: "dogecoin_mainnet"
  chain_id: 98

# Pool branding in OP_RETURN
coinbase_text: "my-p2pool-node"

# Logging
logging:
  level: "INFO"
  format: "text"
  file: null                              # Set to "adapter.log" for file logging
```

> **Credential alignment**: `server.rpc_user`/`server.rpc_password` must match
> P2Pool's `--merged-coind-rpc-user`/`--merged-coind-rpc-password`.
> `upstream` credentials must match `dogecoin.conf`.

### Step 9 — Run P2Pool

```bash
# Set PATH (if not in .bashrc already)
export PATH="$HOME/pypy2.7-v7.3.17-linux64/bin:$PATH"

cd ~/p2pool-merged-v36
```

#### Start MM-Adapter first (in a screen session)

```bash
screen -dmS mm-adapter bash -c '
    cd ~/p2pool-merged-v36/mm-adapter
    source venv/bin/activate
    python3 adapter.py --config config_mainnet.yaml 2>&1 | tee -a adapter.log
'
```

#### Start P2Pool with merged mining

```bash
screen -dmS p2pool bash -c '
    export PATH="$HOME/pypy2.7-v7.3.17-linux64/bin:$PATH"
    cd ~/p2pool-merged-v36
    pypy run_p2pool.py \
        --net litecoin \
        --coind-address <LTC_DAEMON_IP> \
        --coind-rpc-port 9332 \
        --coind-p2p-port 9333 \
        --merged-coind-address 127.0.0.1 \
        --merged-coind-rpc-port 44556 \
        --merged-coind-p2p-port 22556 \
        --merged-coind-p2p-address <DOGE_DAEMON_IP> \
        --merged-coind-rpc-user dogecoinrpc \
        --merged-coind-rpc-password <DOGE_RPC_PASSWORD> \
        --address <YOUR_LTC_ADDRESS> \
        --give-author 2 \
        -f 0 \
        --disable-upnp \
        --max-conns 20 \
        --no-console \
        --redistribute boost \
        litecoinrpc <LTC_RPC_PASSWORD> \
        2>&1 | tee -a data/litecoin/log
'
```

#### Placeholder Reference

| Placeholder | Where to find it | Description |
|-------------|-------------------|-------------|
| `<LTC_DAEMON_IP>` | Your Litecoin Core host | `127.0.0.1` if local, or LAN IP |
| `<DOGE_DAEMON_IP>` | Your Dogecoin Core host | `127.0.0.1` if local, or LAN IP |
| `<YOUR_LTC_ADDRESS>` | `litecoin-cli getnewaddress "" legacy` | Must be **legacy** format (starts with `L`) |
| `<LTC_RPC_PASSWORD>` | `litecoin.conf` → `rpcpassword` | Litecoin RPC password |
| `<DOGE_RPC_PASSWORD>` | `dogecoin.conf` → `rpcpassword` | Dogecoin RPC password |

#### Standalone mode (Litecoin only, no merged mining)

```bash
pypy run_p2pool.py \
    --net litecoin \
    --coind-address 127.0.0.1 \
    --coind-rpc-port 9332 \
    --coind-p2p-port 9333 \
    -a <YOUR_LTC_ADDRESS> \
    --disable-upnp \
    litecoinrpc <LTC_RPC_PASSWORD>
```

#### Monitor running sessions

```bash
# Reattach to P2Pool session
screen -r p2pool

# Reattach to MM-Adapter session
screen -r mm-adapter

# Detach from screen: Ctrl+A, then D
```

#### Initial share chain sync

When P2Pool first starts, it downloads and verifies the share chain from peers.
This takes **several minutes** — the dashboard will show zeros and incomplete data
until verification catches up.

You can track progress by reattaching to the P2Pool screen session (`screen -r p2pool`).
Look for lines like:

```
P2Pool: 17289 shares in chain (8669 verified/17289 total) Peers: 6 (0 incoming)
```

The share chain has ~17,280 shares. Once `verified` reaches `total`, the dashboard
will display full pool statistics, payout estimates, and the version transition
progress bar.

> **Tip**: Even before full sync, the dashboard at `http://localhost:9327/static/dashboard.html`
> will show peer connections, broadcaster status, and the new dashboard graphs.

### WSL2 Networking Reference

| Scenario | Address to use |
|----------|---------------|
| P2Pool → LTC daemon (same WSL) | `127.0.0.1` |
| P2Pool → LTC daemon (LAN machine) | LAN IP of LTC host |
| P2Pool → MM-Adapter (always local) | `127.0.0.1` |
| P2Pool → DOGE daemon P2P (LAN) | LAN IP of DOGE host |
| Miner → P2Pool stratum | `localhost:9327` from Windows, or WSL IP from LAN |
| Browser → P2Pool Web UI | `http://localhost:9327/` from Windows |
| Inbound P2Pool P2P (port 9326) | Forward in Windows Firewall for external peers |

### WSL2 Disk Performance

Store blockchain data **inside the WSL2 filesystem** (e.g., `~/.litecoin/`), not on `/mnt/c/`. Accessing Windows drives through the 9P mount is ~50% slower for random I/O.

```bash
# Good — native ext4 inside WSL
~/.litecoin/
~/.dogecoin/

# Bad — slow cross-filesystem access
/mnt/c/Users/you/.litecoin/
```

---

## Option 2: Docker on WSL2

The project ships a root `Dockerfile`, `docker-compose.yml`, and `.env.example` for
one-command deployment. Tested: first build ~3 min (cached builds instant), P2Pool image ~757MB, MM-Adapter ~226MB.

### Prerequisites
- [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) with WSL2 backend enabled
  (or Docker Engine installed directly in WSL2: `curl -fsSL https://get.docker.com | sudo sh`)
- 8GB+ RAM, 120GB+ free disk

### Step 1 — Configure

```bash
cd ~/p2pool-merged-v36

# Create .env with your credentials and payout address
cp .env.example .env
# Edit .env: set LTC_RPC_PASSWORD, DOGE_RPC_PASSWORD, LTC_PAYOUT_ADDRESS, daemon IPs

# Create MM-Adapter config
cp mm-adapter/config.docker.example.yaml mm-adapter/config.docker.yaml
# Edit config.docker.yaml: set upstream DOGE credentials and host
```

### Step 2 — Build and Run

```bash
# Build and start both P2Pool + MM-Adapter
docker compose up -d

# Check status
docker compose ps
docker compose logs -f p2pool    # watch P2Pool logs
docker compose logs -f mm-adapter # watch adapter logs

# Dashboard
# Open http://localhost:9327/static/dashboard.html
```

### Step 3 — Standalone mode (manual docker run, no compose)

```powershell
# Build image
docker build -t p2pool-ltc .

# Run LTC-only (no merged mining)
docker run -d --name p2pool `
    -p 9327:9327 -p 9326:9326 `
    -v p2pool-data:/app/data `
    p2pool-ltc `
    --net litecoin `
    --coind-address <LTC_DAEMON_IP> `
    --coind-rpc-port 9332 `
    --coind-p2p-port 9333 `
    -a <YOUR_LTC_ADDRESS> `
    --disable-upnp `
    litecoinrpc <LTC_RPC_PASSWORD>
```

> **Note:** Use `host.docker.internal` to reach services running on the
> Windows host or in another WSL2 distro. For LAN daemons, use their actual
> LAN IPs directly (Docker with bridge networking can route to LAN).

### Docker file reference

| File | Purpose |
|------|---------|
| [`Dockerfile`](../Dockerfile) | Multi-stage build: Ubuntu 22.04 + PyPy 2.7 + all deps |
| [`docker-compose.yml`](../docker-compose.yml) | Full stack: P2Pool + MM-Adapter with health checks |
| [`.env.example`](../.env.example) | All configurable settings (passwords, IPs, ports, fees) |
| [`mm-adapter/config.docker.example.yaml`](../mm-adapter/config.docker.example.yaml) | Docker-specific adapter config template |
| [`.dockerignore`](../.dockerignore) | Keeps image small (~180MB) by excluding docs, tests, git |

---

## Option 3: Native Windows (Advanced)

The codebase has Phase 1 Windows compatibility patches (see Changelog v36-0.07-alpha), but native Windows requires manual setup and has limitations.

### What Already Works on Windows

| Component | Status | Notes |
|-----------|--------|-------|
| Config path resolution | OK | Uses `%APPDATA%\Litecoin\` and `%APPDATA%\Dogecoin\` |
| Memory reporting | OK | Uses ctypes `kernel32`/`psapi` — no WMI needed |
| Atomic file writes | OK | `os.rename()` with `os.remove()` fallback |
| IOCP reactor | OK | `--iocp` flag for high socket counts |
| Signal handling | OK | `SIGALRM` gracefully skipped on Windows |
| py2exe packaging | OK | `setup.py` builds Windows executables |
| scrypt C extension | OK | MSVC-compatible `__forceinline` macro |

### What Doesn't Work / Needs Manual Setup

| Gap | Impact | Workaround |
|-----|--------|------------|
| No PowerShell scripts | Dev convenience | Run commands manually |
| Python 2.7 requirement | **Major** — PyPy Windows builds exist but pip ecosystem is fragile | Use PyPy 2.7 for Windows (see below) |
| Build tools (Makefile, configure) | Dev only | Not needed for running |
| `snap` not available | Can't use snap PyPy install method | Use tarball or msi |

### Native Windows Step-by-Step

#### 1. Install Litecoin Core for Windows
Download from https://download.litecoin.org/litecoin-0.21.4/win/ and install.

Configure `%APPDATA%\Litecoin\litecoin.conf`:
```ini
server=1
txindex=1
rpcuser=litecoinrpc
rpcpassword=CHANGE_ME
rpcallowip=127.0.0.1
rpcbind=127.0.0.1
rpcport=9332
rpcworkqueue=512
rpcthreads=32
```

#### 2. Install Dogecoin Core for Windows
Download from https://github.com/dogecoin/dogecoin/releases (Windows installer).

Configure `%APPDATA%\Dogecoin\dogecoin.conf`:
```ini
server=1
rpcuser=dogecoinrpc
rpcpassword=CHANGE_ME
rpcallowip=127.0.0.1
rpcbind=127.0.0.1
rpcport=22555
```

#### 3. Install PyPy 2.7 for Windows

Download PyPy 2.7 from https://downloads.python.org/pypy/ — get the Windows x86_64 zip.

```powershell
# Extract and add to PATH
Expand-Archive pypy2.7-v7.3.17-win64.zip -DestinationPath C:\pypy27
$env:PATH = "C:\pypy27\pypy2.7-v7.3.17-win64;$env:PATH"

# Verify
pypy --version
# Python 2.7.18 ...
```

#### 4. Install pip and Dependencies

```powershell
# Get pip
Invoke-WebRequest -Uri https://bootstrap.pypa.io/pip/2.7/get-pip.py -OutFile get-pip.py
pypy get-pip.py

# Pin incremental first (required for twisted on Python 2.7)
pypy -m pip install "incremental<22"

# Install deps
pypy -m pip install twisted==20.3.0 pycryptodome ecdsa
```

> **Warning:** The `scrypt` pip package requires OpenSSL headers and a C compiler (Visual Studio Build Tools). This is the hardest part of a native Windows install.

```powershell
# Option A: Install Visual Studio Build Tools + OpenSSL, then:
pypy -m pip install "scrypt>=0.8.0,<=0.8.22"

# Option B: Build the bundled C extension (requires C compiler)
cd litecoin_scrypt
pypy setup.py install --user
cd ..
```

#### 5. Run P2Pool

```powershell
cd C:\path\to\p2pool-merged-v36

pypy run_p2pool.py `
    --net litecoin `
    --iocp `
    --coind-address 127.0.0.1 `
    --coind-rpc-port 9332 `
    --coind-p2p-port 9333 `
    -a <YOUR_LTC_ADDRESS> `
    --disable-upnp `
    litecoinrpc <LTC_RPC_PASSWORD>
```

> **Important:** Always use `--iocp` on Windows to avoid socket-related errors.

#### 6. Windows Firewall

```powershell
# Allow P2Pool stratum + P2P (run as Administrator)
New-NetFirewallRule -DisplayName "P2Pool Stratum" -Direction Inbound -Protocol TCP -LocalPort 9327 -Action Allow
New-NetFirewallRule -DisplayName "P2Pool P2P" -Direction Inbound -Protocol TCP -LocalPort 9326 -Action Allow
New-NetFirewallRule -DisplayName "Litecoin P2P" -Direction Inbound -Protocol TCP -LocalPort 9333 -Action Allow
New-NetFirewallRule -DisplayName "Dogecoin P2P" -Direction Inbound -Protocol TCP -LocalPort 22556 -Action Allow
```

---

## Example Network Topology

A typical LAN deployment with separate daemon machines:

| Host | Role | Ports |
|------|------|-------|
| LTC daemon machine | Litecoin Core mainnet | RPC 9332, P2P 9333 |
| DOGE daemon machine | Dogecoin Core mainnet | RPC 22555, P2P 22556 |
| P2Pool node (WSL2) | P2Pool + MM-Adapter | Stratum 9327, P2P 9326, Adapter 44556 |

All nodes run PyPy 2.7.18 with the mm-adapter using `config_mainnet.yaml`.
Daemons can also run on the same machine as P2Pool — use `127.0.0.1` for all addresses.

---

## Decision Matrix

| Factor | WSL2 | Docker | Native |
|--------|------|--------|--------|
| Setup complexity | Low | Medium | High |
| Python 2.7 / PyPy | tarball or snap — just works | Built into image | Manual .zip + PATH + pip bootstrap |
| scrypt C extension | `apt install libssl-dev` then pip | Pre-built in image | Needs Visual Studio Build Tools + OpenSSL |
| coincurve (security) | Easy (`pip install coincurve==13.0.0`) | Add to Dockerfile | Very hard (needs autotools on Windows) |
| LAN daemon access | Bridged/mirrored networking | `host.docker.internal` or LAN IPs | Direct |
| Blockchain I/O perf | ~95% native (ext4 inside WSL) | ~90% (Docker volume overlay) | 100% native (NTFS) |
| RAM overhead | ~256MB for WSL VM | ~256MB WSL VM + container overhead | None |
| Daemon co-location | Easy (all in one WSL instance) | Separate containers or host-networking | All native |
| systemd / auto-start | Yes (with `systemd=true` in wsl.conf) | Docker restart policies | Windows Task Scheduler |
| SSH management | Passwordless with key deployment | N/A (docker exec) | N/A |
| Community support | All Linux guides apply | Varies | Very limited |

---

## FAQ

**Q: Can Litecoin/Dogecoin daemons run on separate LAN machines?**
Yes — this is the production topology. Point `--coind-address` and `--merged-coind-p2p-address`
to the LAN IPs. The `--merged-coind-address` always points to `127.0.0.1` (the local MM-Adapter).
With WSL2 bridged/mirrored networking, WSL reaches LAN IPs directly.

**Q: Can daemons run as native Windows apps while P2Pool runs in WSL2?**
Yes. From WSL2, point `--coind-address` to the Windows host IP. With mirrored networking,
use `127.0.0.1`. With NAT networking, find the host IP:
```bash
# Inside WSL2
ip route show default | awk '{print $3}'
```

**Q: How do I set up SSH keys for multiple nodes?**
Generate once on Windows, deploy to all targets (including WSL2 itself):
```powershell
# Generate (once)
ssh-keygen -t ed25519 -C "p2pool-win"

# Deploy via WSL to each target (handles permissions correctly)
wsl -d Ubuntu-22.04 -- ssh-copy-id -f -i /mnt/c/Users/<winuser>/.ssh/id_ed25519.pub <remoteuser>@<TARGET_IP>
```

**Q: How much disk does WSL2 use?**
The WSL2 virtual disk (ext4.vhdx) grows dynamically. Blockchain data is the main consumer (~100GB for LTC+DOGE mainnet). You can move the WSL distro to another drive:
```powershell
wsl --export Ubuntu-22.04 D:\wsl-backup.tar
wsl --unregister Ubuntu-22.04
wsl --import Ubuntu-22.04 D:\WSL\Ubuntu D:\wsl-backup.tar
```

**Q: Is the py2exe build still viable?**
The `setup.py` with py2exe is legacy and targets Python 2.7 + py2exe. It can produce a standalone `.exe` but requires a working native Windows Python 2.7 environment with all deps installed first. Not recommended for new deployments.

**Q: Will P2Pool eventually support Python 3?**
The project roadmap includes C++ migration (see [FUTURE.md](FUTURE.md)). Python 3 porting is not planned — the path forward is c2pool (C++ rewrite). For now, PyPy 2.7 is the supported runtime.

---

## Summary

For Windows 10/11 users: **use WSL2 with Ubuntu 22.04**. It gives you:
- Zero Windows-specific workarounds needed
- Full compatibility with the Linux install guide
- Near-native performance
- Bridged/mirrored networking for direct LAN daemon access
- Passwordless SSH management to WSL and remote nodes
- Easy access from Windows browsers and miners via `localhost`
- The ability to run all components (MM-Adapter, P2Pool, cpuminer) in one environment

Native Windows is possible thanks to the Phase 1 patches (v36-0.07-alpha) but the Python 2.7 dependency and C extension compilation make it significantly harder with no real benefit.
