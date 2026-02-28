#!/bin/bash
# Start P2Pool for Litecoin + Dogecoin Merged Mining (Testnet)
# Updated: 2024-12-24 - Multiaddress coinbase support

cd "$(dirname "$0")"

# Set up PyPy and OpenSSL 1.1.1 environment
export PATH="$HOME/.local/pypy2.7-v7.3.20-linux64/bin:$PATH"
export LD_LIBRARY_PATH="$HOME/.local/openssl-1.1.1/lib:$LD_LIBRARY_PATH"

# Litecoin Testnet RPC credentials
LTC_RPC_USER="litecoinrpc"
LTC_RPC_PASS="LTC_testnet_pass_2024_secure"
LTC_RPC_HOST="127.0.0.1"
LTC_RPC_PORT="19332"

# Dogecoin Testnet RPC credentials
DOGE_RPC_USER="dogeuser"
DOGE_RPC_PASS="dogepass123"
DOGE_RPC_HOST="127.0.0.1"
DOGE_RPC_PORT="44555"

# P2Pool configuration
# For multiaddress coinbase, use LEGACY address format (pubkey_hash based)
# The same pubkey_hash is used to derive Dogecoin addresses automatically
# Litecoin testnet legacy: mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h (ADDRESS_VERSION=111)
# Dogecoin testnet derived: nZj5sSzP9NSYLRBbWUTz4tConRSSeuYQvY (ADDRESS_VERSION=113)
P2POOL_ADDRESS="mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h"  # Must use legacy for multiaddress!
POOL_FEE="1"                                          # 1% pool fee (--give-author)

# Node operator fee for merged mining (optional)
# This address receives the operator fee from merged mining blocks
MERGED_OPERATOR_ADDRESS="nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB"

# Merged mining URL
DOGE_MERGED_URL="http://${DOGE_RPC_USER}:${DOGE_RPC_PASS}@${DOGE_RPC_HOST}:${DOGE_RPC_PORT}"

# Log file
LOG_FILE="/tmp/p2pool_merged.log"

echo "=== Starting P2Pool Scrypt (Litecoin + Dogecoin Merged Mining Testnet) ==="
echo "Network: litecoin --testnet"
echo "Litecoin Payout Address: $P2POOL_ADDRESS"
echo "Dogecoin Auto-Derived:   (same pubkey_hash converted to DOGE testnet format)"
echo "Merged Mining URL: $DOGE_MERGED_URL"
echo "Pool Fee: $POOL_FEE%"
echo "Node Operator Address: $MERGED_OPERATOR_ADDRESS"
echo "Log file: $LOG_FILE"
echo ""
echo "Multiaddress Coinbase Feature:"
echo "  - Miners can specify addresses as: LTC_ADDRESS,DOGE_ADDRESS.worker"
echo "  - If only LTC address provided, DOGE address derived automatically"
echo "  - Example: mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB.rig1"
echo ""
echo "NOTE: Ensure Dogecoin daemon with auxpow support is running:"
echo "  ~/start-dogecoin-auxpow.sh ~/bin-auxpow/dogecoind -testnet -daemon"
echo ""

# Start P2Pool with Dogecoin merged mining
# --net litecoin --testnet = Litecoin testnet
# --address = Pool default address (legacy format required for multiaddress)
# --merged = Merged mining RPC URL (Dogecoin)
# --give-author = Pool fee percentage
# -f = Fee percentage (same as --fee)
# --merged-operator-address = Node operator receives fee from merged blocks
pypy run_p2pool.py \
    --net litecoin \
    --testnet \
    --address "$P2POOL_ADDRESS" \
    --merged "$DOGE_MERGED_URL" \
    --give-author "$POOL_FEE" \
    -f "$POOL_FEE" \
    --merged-operator-address "$MERGED_OPERATOR_ADDRESS" \
    "$@" \
    2>&1 | tee "$LOG_FILE"
