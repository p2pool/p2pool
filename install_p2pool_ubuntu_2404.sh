#!/bin/bash
set -e

# P2Pool Installer for Ubuntu 24.04
# This script sets up PyPy2, builds a local OpenSSL 1.1, and configures p2pool.

echo "Updating system packages..."
sudo apt-get update
sudo apt-get install -y build-essential git wget tar libbz2-dev zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev curl

INSTALL_DIR="/opt/p2pool-dash"
OPENSSL_VERSION="1.1.1w"
PYPY_VERSION="pypy2.7-v7.3.17-linux64"

echo "Creating installation directory at $INSTALL_DIR..."
sudo mkdir -p $INSTALL_DIR
sudo chown $USER:$USER $INSTALL_DIR
cd $INSTALL_DIR

# 1. Build OpenSSL 1.1 locally (required for PyPy2 on Ubuntu 24.04)
if [ ! -d "openssl-$OPENSSL_VERSION" ]; then
    echo "Downloading and building OpenSSL $OPENSSL_VERSION..."
    wget https://www.openssl.org/source/openssl-$OPENSSL_VERSION.tar.gz
    tar xzf openssl-$OPENSSL_VERSION.tar.gz
    cd openssl-$OPENSSL_VERSION
    ./config --prefix=$INSTALL_DIR/openssl --openssldir=$INSTALL_DIR/openssl shared zlib
    make -j$(nproc)
    make install
    cd ..
else
    echo "OpenSSL already present."
fi

# 2. Install PyPy2
if [ ! -d "$PYPY_VERSION" ]; then
    echo "Downloading PyPy2..."
    wget https://downloads.python.org/pypy/$PYPY_VERSION.tar.bz2
    tar xjf $PYPY_VERSION.tar.bz2
    # Link local OpenSSL to PyPy
    # We need to make sure PyPy finds our local OpenSSL libraries
    export LD_LIBRARY_PATH=$INSTALL_DIR/openssl/lib:$LD_LIBRARY_PATH
else
    echo "PyPy2 already present."
fi

PYPY_BIN="$INSTALL_DIR/$PYPY_VERSION/bin/pypy"

# 3. Install pip for PyPy
echo "Installing pip..."
curl https://bootstrap.pypa.io/pip/2.7/get-pip.py -o get-pip.py
$PYPY_BIN get-pip.py

# 4. Install Dependencies
echo "Installing Python dependencies..."
# Twisted 15.4.0 and Zope.interface are required for p2pool
$PYPY_BIN -m pip install zope.interface==4.1.3
$PYPY_BIN -m pip install Twisted==15.4.0
$PYPY_BIN -m pip install pycrypto

# 5. Clone/Update P2Pool
REPO_DIR="$HOME/p2pool-dash"
if [ ! -d "$REPO_DIR" ]; then
    echo "Cloning p2pool-dash repository..."
    git clone https://github.com/frstrtr/p2pool-dash.git $REPO_DIR
else
    echo "p2pool-dash repository already exists at $REPO_DIR"
fi

# Install dash_hash
if [ -d "$REPO_DIR/dash_hash" ]; then
    echo "Installing dash_hash module..."
    cd "$REPO_DIR/dash_hash"
    $PYPY_BIN setup.py install
    cd "$INSTALL_DIR"
else
    echo "Warning: dash_hash directory not found in $REPO_DIR"
fi

# 6. Create Systemd Service
echo "Creating systemd service..."
SERVICE_FILE="/etc/systemd/system/p2pool-dash.service"

# Ask for configuration details
read -p "Enter Dash Node RPC User: " RPC_USER
read -p "Enter Dash Node RPC Password: " RPC_PASS
read -p "Enter Dash Node RPC Port (default 9998): " RPC_PORT
RPC_PORT=${RPC_PORT:-9998}
read -p "Enter P2Pool P2P Port (default 8999): " P2P_PORT
P2P_PORT=${P2P_PORT:-8999}
read -p "Enter P2Pool Worker Port (default 7903): " WORKER_PORT
WORKER_PORT=${WORKER_PORT:-7903}
read -p "Enter Fee Address (your Dash address): " FEE_ADDR

sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=P2Pool Dash
After=network.target

[Service]
User=$USER
WorkingDirectory=$REPO_DIR
Environment="LD_LIBRARY_PATH=$INSTALL_DIR/openssl/lib"
ExecStart=$PYPY_BIN run_p2pool.py --net dash --coind-rpc-port $RPC_PORT --coind-rpc-user $RPC_USER --coind-rpc-pass $RPC_PASS --p2p-port $P2P_PORT --worker-port $WORKER_PORT --give-author 0 --fee 0 -a $FEE_ADDR
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

echo "Reloading systemd..."
sudo systemctl daemon-reload
sudo systemctl enable p2pool-dash

echo "Installation complete!"
echo "You can start p2pool with: sudo systemctl start p2pool-dash"
echo "Check logs with: sudo journalctl -u p2pool-dash -f"
