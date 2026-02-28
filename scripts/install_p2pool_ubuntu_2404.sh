#!/bin/bash
set -e

# P2Pool Merged Mining Installer for Ubuntu 24.04
# Sets up PyPy2, P2Pool dependencies, and optionally creates
# coin daemon configs and a systemd service.
#
# Deployment topology:
#   All-in-one  — LTC Core + DOGE Core + MM-Adapter + P2Pool on one machine
#   Distributed — daemons on separate LAN machines, P2Pool on another
#
# This script installs P2Pool itself. Coin daemon installation is covered
# in INSTALL.md. If daemons are already running (same or separate machine),
# this script can generate matching config files.

echo "=== P2Pool Merged Mining (V36) Installer ==="
echo ""

# Update packages
echo "Updating system packages..."
sudo apt-get update
sudo apt-get install -y build-essential git wget tar libbz2-dev zlib1g-dev \
    libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev \
    libffi-dev curl screen

INSTALL_DIR="/opt/p2pool"
PYPY_VERSION="pypy2.7-v7.3.20-linux64"
REPO_URL="https://github.com/frstrtr/p2pool-merged-v36.git"

echo "Creating installation directory at $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo chown "$USER:$USER" "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 1. Install PyPy 2.7
if [ ! -d "$PYPY_VERSION" ]; then
    echo "Downloading PyPy 2.7..."
    wget "https://downloads.python.org/pypy/$PYPY_VERSION.tar.bz2"
    tar xjf "$PYPY_VERSION.tar.bz2"
    rm -f "$PYPY_VERSION.tar.bz2"
else
    echo "PyPy 2.7 already present."
fi

PYPY_BIN="$INSTALL_DIR/$PYPY_VERSION/bin/pypy"

# 2. Install pip for PyPy
echo "Installing pip for PyPy..."
curl -sS https://bootstrap.pypa.io/pip/2.7/get-pip.py -o get-pip.py
"$PYPY_BIN" get-pip.py
rm -f get-pip.py

# 3. Install Python dependencies
echo "Installing Python dependencies..."
"$PYPY_BIN" -m pip install twisted==19.10.0 pycryptodome 'scrypt>=0.8.0,<=0.8.22' ecdsa

# 4. Clone/Update P2Pool
REPO_DIR="$HOME/p2pool-merged-v36"
if [ ! -d "$REPO_DIR" ]; then
    echo "Cloning p2pool-merged-v36 repository..."
    git clone "$REPO_URL" "$REPO_DIR"
else
    echo "Repository already exists at $REPO_DIR, pulling latest..."
    cd "$REPO_DIR" && git pull && cd "$INSTALL_DIR"
fi

# 5. Verify scrypt hashing works
echo "Verifying scrypt hashing..."
cd "$REPO_DIR"
"$PYPY_BIN" -c "import ltc_scrypt; print('scrypt hashing OK')" || {
    echo "WARNING: scrypt hashing not available. Check installation."
}

echo ""
echo "=== P2Pool Installation complete! ==="
echo ""
echo "PyPy:   $PYPY_BIN"
echo "P2Pool: $REPO_DIR"
echo ""

# ------------------------------------------------------------------
# 6. Optional: Generate coin daemon configs
# ------------------------------------------------------------------
echo "--- Coin Daemon Configuration ---"
echo ""
echo "P2Pool needs Litecoin Core and Dogecoin Core (for merged mining)."
echo "They can run on THIS machine or on SEPARATE LAN machines."
echo ""

read -p "Generate example litecoin.conf? [y/N]: " GEN_LTC
if [[ "$GEN_LTC" =~ ^[Yy]$ ]]; then
    read -p "Will Litecoin Core run on this machine? [Y/n]: " LTC_LOCAL
    LTC_LOCAL=${LTC_LOCAL:-Y}

    LTC_RPC_PASS=$(openssl rand -hex 16)
    LTC_CONF_DIR="$HOME/.litecoin"
    mkdir -p "$LTC_CONF_DIR"

    if [[ "$LTC_LOCAL" =~ ^[Yy]$ ]]; then
        cat > "$LTC_CONF_DIR/litecoin.conf" <<LTCEOF
# Litecoin Core — same machine as P2Pool
server=1
daemon=1
txindex=1

rpcuser=litecoinrpc
rpcpassword=$LTC_RPC_PASS
rpcallowip=127.0.0.1
listen=1
maxconnections=50

[main]
port=9333
rpcport=9332
rpcbind=127.0.0.1
dbcache=4000
par=0

rpcworkqueue=512
rpcthreads=32
LTCEOF
        echo "  Written: $LTC_CONF_DIR/litecoin.conf (localhost-only RPC)"
    else
        cat > "$LTC_CONF_DIR/litecoin.conf" <<LTCEOF
# Litecoin Core — separate machine, P2Pool on LAN
server=1
daemon=1
txindex=1

rpcuser=litecoinrpc
rpcpassword=$LTC_RPC_PASS
rpcallowip=127.0.0.1
rpcallowip=192.168.0.0/16
listen=1
maxconnections=50

[main]
port=9333
rpcport=9332
rpcbind=0.0.0.0
dbcache=4000
par=0

rpcworkqueue=512
rpcthreads=32
LTCEOF
        echo "  Written: $LTC_CONF_DIR/litecoin.conf (LAN RPC enabled)"
    fi
    echo "  RPC password: $LTC_RPC_PASS"
    echo ""
fi

read -p "Generate example dogecoin.conf? [y/N]: " GEN_DOGE
if [[ "$GEN_DOGE" =~ ^[Yy]$ ]]; then
    read -p "Will Dogecoin Core run on this machine? [Y/n]: " DOGE_LOCAL
    DOGE_LOCAL=${DOGE_LOCAL:-Y}

    DOGE_RPC_PASS=$(openssl rand -hex 16)
    DOGE_CONF_DIR="$HOME/.dogecoin"
    mkdir -p "$DOGE_CONF_DIR"

    if [[ "$DOGE_LOCAL" =~ ^[Yy]$ ]]; then
        cat > "$DOGE_CONF_DIR/dogecoin.conf" <<DOGEEOF
# Dogecoin Core — same machine as P2Pool
server=1
daemon=1

rpcuser=dogecoinrpc
rpcpassword=$DOGE_RPC_PASS
rpcallowip=127.0.0.1
rpcbind=127.0.0.1
rpcport=22555

port=22556
listen=1
maxconnections=50

dbcache=2000
par=4
DOGEEOF
        echo "  Written: $DOGE_CONF_DIR/dogecoin.conf (localhost-only RPC)"
    else
        cat > "$DOGE_CONF_DIR/dogecoin.conf" <<DOGEEOF
# Dogecoin Core — separate machine, adapter/P2Pool on LAN
server=1
daemon=1

rpcuser=dogecoinrpc
rpcpassword=$DOGE_RPC_PASS
rpcallowip=127.0.0.1
rpcallowip=192.168.0.0/16
rpcbind=0.0.0.0
rpcport=22555

port=22556
bind=0.0.0.0
listen=1
maxconnections=50

dbcache=2000
par=4
DOGEEOF
        echo "  Written: $DOGE_CONF_DIR/dogecoin.conf (LAN RPC enabled)"
    fi
    echo "  RPC password: $DOGE_RPC_PASS"
    echo ""
fi

# ------------------------------------------------------------------
# 7. Quick start summary
# ------------------------------------------------------------------
echo ""
echo "--- Quick Start ---"
echo ""
echo "  Litecoin only (no merged mining):"
echo "    cd $REPO_DIR"
echo "    $PYPY_BIN run_p2pool.py \\"
echo "        --net litecoin \\"
echo "        --coind-address 127.0.0.1 \\"
echo "        --coind-rpc-port 9332 \\"
echo "        --address YOUR_LTC_ADDRESS \\"
echo "        litecoinrpc YOUR_LTC_RPC_PASSWORD"
echo ""
echo "  With Dogecoin merged mining (requires MM-Adapter):"
echo "    cd $REPO_DIR"
echo "    $PYPY_BIN run_p2pool.py \\"
echo "        --net litecoin \\"
echo "        --coind-address LTC_DAEMON_IP \\"
echo "        --coind-rpc-port 9332 \\"
echo "        --coind-p2p-port 9333 \\"
echo "        --merged-coind-address 127.0.0.1 \\"
echo "        --merged-coind-rpc-port 44556 \\"
echo "        --merged-coind-p2p-port 22556 \\"
echo "        --merged-coind-p2p-address DOGE_DAEMON_IP \\"
echo "        --merged-coind-rpc-user dogecoinrpc \\"
echo "        --merged-coind-rpc-password YOUR_DOGE_RPC_PASSWORD \\"
echo "        --address YOUR_LEGACY_LTC_ADDRESS \\"
echo "        --give-author 1 \\"
echo "        --disable-upnp \\"
echo "        litecoinrpc YOUR_LTC_RPC_PASSWORD"
echo ""
echo "  See README.md for full MM-Adapter setup."
echo ""

# ------------------------------------------------------------------
# 8. Optional: Create systemd service
# ------------------------------------------------------------------
read -p "Create systemd service? [y/N]: " CREATE_SERVICE
if [[ "$CREATE_SERVICE" =~ ^[Yy]$ ]]; then
    read -p "Litecoin daemon IP [127.0.0.1]: " LTC_HOST
    LTC_HOST=${LTC_HOST:-127.0.0.1}
    read -p "Litecoin RPC user [litecoinrpc]: " RPC_USER
    RPC_USER=${RPC_USER:-litecoinrpc}
    read -p "Litecoin RPC password: " RPC_PASS
    read -p "Your LTC payout address (legacy L... format): " PAYOUT_ADDR

    SERVICE_FILE="/etc/systemd/system/p2pool.service"
    sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=P2Pool Litecoin Merged Mining (V36)
After=network.target

[Service]
User=$USER
WorkingDirectory=$REPO_DIR
ExecStart=$PYPY_BIN $REPO_DIR/run_p2pool.py \\
    --net litecoin \\
    --coind-address $LTC_HOST \\
    --coind-rpc-port 9332 \\
    --coind-p2p-port 9333 \\
    --address $PAYOUT_ADDR \\
    --give-author 1 \\
    --disable-upnp \\
    $RPC_USER $RPC_PASS
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

    sudo systemctl daemon-reload
    sudo systemctl enable p2pool
    echo ""
    echo "Systemd service created."
    echo "  Start:  sudo systemctl start p2pool"
    echo "  Logs:   sudo journalctl -u p2pool -f"
    echo "  Status: sudo systemctl status p2pool"
fi
