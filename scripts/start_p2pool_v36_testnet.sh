#!/bin/bash
# P2Pool v36 Merged Mining — Litecoin + Dogecoin (Testnet)
# Phase 2: Experimental v36 node alongside canonical v35 nodes (nodeC/33)
# Updated: 2026-02-14 - Scrypt migration (py-scrypt) + v36 merged mining
#
# This script contains credentials - DO NOT COMMIT TO GIT
# Node: NODE_A_IP (nodeA)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Node configuration
NODE_NAME="${1:-p2pool-v36}"
LTC_ADDRESS="${2:-YOUR_TLTC_ADDRESS}"

# Litecoin Testnet RPC (shared daemon on .26)
LTC_RPC_HOST="LTC_DAEMON_IP"
LTC_RPC_PORT="19332"
LTC_P2P_PORT="19335"
LTC_RPC_USER="litecoinrpc"
LTC_RPC_PASS="YOUR_LTC_RPC_PASSWORD"

# Dogecoin Testnet RPC via MM-Adapter (local proxy for coinbase manipulation)
# The mm-adapter proxies getblocktemplate to the Dogecoin daemon, allowing
# p2pool to inject PPLNS shareholder payouts into the merged coinbase.
# Direct daemon is used for P2P block propagation only.
DOGE_ADAPTER_HOST="127.0.0.1"
DOGE_ADAPTER_PORT="44556"
DOGE_RPC_USER="dogecoinrpc"
DOGE_RPC_PASS="testpass"

# Dogecoin daemon direct connection (for P2P block broadcasting)
DOGE_P2P_HOST="DOGE_DAEMON_IP"
DOGE_P2P_PORT="44557"

# Dogecoin testnet payout address (operator fee)
DOGE_OPERATOR_ADDRESS="YOUR_TDOGE_ADDRESS"

# P2Pool settings
GIVE_AUTHOR="0"       # 0% author fee (testnet)
POOL_FEE="0"          # 0% node fee (testnet)
MAX_CONNS="20"
COINB_TEXT="p2pool-v36-testnet"

# Bootstrap peers (canonical v35 nodes)
PEER_NODE30="NODE_C_IP:19338"
PEER_NODE33="PEER_IP:19338"

# PyPy path
PYPY_PATH="$HOME/pypy2.7-v7.3.20-linux64/bin"
export PATH="$PYPY_PATH:$PATH"

# OpenSSL 1.1 (if available)
if [ -d "$HOME/openssl-1.1/lib" ]; then
    export LD_LIBRARY_PATH="$HOME/openssl-1.1/lib:${LD_LIBRARY_PATH:-}"
elif [ -d "$HOME/.local/openssl-1.1.1/lib" ]; then
    export LD_LIBRARY_PATH="$HOME/.local/openssl-1.1.1/lib:${LD_LIBRARY_PATH:-}"
fi

# Log file
LOG_FILE="$SCRIPT_DIR/data/litecoin_testnet/log"
mkdir -p "$SCRIPT_DIR/data/litecoin_testnet"

# --- Functions ---

stop_graceful() {
    echo "Checking for existing P2Pool testnet instances..."
    if pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null 2>&1; then
        echo "Gracefully stopping P2Pool testnet instance(s)..."
        pkill -TERM -f "pypy.*run_p2pool.*testnet"
        for i in {1..10}; do
            if ! pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null 2>&1; then
                echo "P2Pool testnet stopped gracefully"
                return 0
            fi
            sleep 1
        done
        echo "Warning: Graceful shutdown timed out, forcing kill..."
        pkill -9 -f "pypy.*run_p2pool.*testnet" 2>/dev/null || true
        sleep 1
    else
        echo "No P2Pool testnet instance running"
    fi
}

show_status() {
    echo ""
    echo "=== P2Pool v36 Testnet — Litecoin + Dogecoin Merged Mining ==="
    echo "Node:      nodeA (NODE_A_IP)"
    echo "Code:      p2pool-merged-v36 (experimental v36 shares)"
    echo "Network:   litecoin --testnet"
    echo "LTC RPC:   ${LTC_RPC_HOST}:${LTC_RPC_PORT}"
    echo "DOGE RPC:  ${DOGE_ADAPTER_HOST}:${DOGE_ADAPTER_PORT} (mm-adapter)"
    echo "DOGE P2P:  ${DOGE_P2P_HOST}:${DOGE_P2P_PORT} (direct daemon)"
    echo "LTC Addr:  $LTC_ADDRESS"
    echo "DOGE Addr: $DOGE_OPERATOR_ADDRESS"
    echo "Coinbase:  $COINB_TEXT"
    echo "Peers:     $PEER_NODE30, $PEER_NODE33"
    echo ""
    echo "Ports:"
    echo "  Stratum (miners): 19327"
    echo "  P2P (sharechain): 19338"
    echo "  Web interface:    19327"
    echo ""
    echo "Phase 2 Testing:"
    echo "  v35 baseline: nodeC (.30), node33 (.33)"
    echo "  v36 experimental: nodeA (.29) [this node]"
    echo ""
}

# --- Main ---

case "${1:-start}" in
    stop)
        stop_graceful
        ;;
    restart)
        stop_graceful
        sleep 2
        show_status

        echo "Starting in screen session '$NODE_NAME'..."
        screen -dmS "$NODE_NAME" bash -c "
            export PATH=\"$PYPY_PATH:\$PATH\"
            export LD_LIBRARY_PATH=\"${LD_LIBRARY_PATH:-}\"
            cd $SCRIPT_DIR
            pypy run_p2pool.py \\
                --net litecoin \\
                --testnet \\
                --bitcoind-address $LTC_RPC_HOST \\
                --bitcoind-rpc-port $LTC_RPC_PORT \\
                --bitcoind-p2p-port $LTC_P2P_PORT \\
                --merged-coind-address $DOGE_ADAPTER_HOST \\
                --merged-coind-rpc-port $DOGE_ADAPTER_PORT \\
                --merged-coind-rpc-user $DOGE_RPC_USER \\
                --merged-coind-rpc-password $DOGE_RPC_PASS \\
                --merged-coind-p2p-address $DOGE_P2P_HOST \\
                --merged-coind-p2p-port $DOGE_P2P_PORT \\
                --merged-operator-address $DOGE_OPERATOR_ADDRESS \\
                -a $LTC_ADDRESS \\
                --coinbtext $COINB_TEXT \\
                --give-author $GIVE_AUTHOR \\
                -f $POOL_FEE \\
                --disable-upnp \\
                --max-conns $MAX_CONNS \\
                -n $PEER_NODE30 \\
                -n $PEER_NODE33 \\
                --no-console \\
                $LTC_RPC_USER $LTC_RPC_PASS \\
                2>&1 | tee -a $LOG_FILE
        "

        sleep 3
        if pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null 2>&1; then
            echo "P2Pool v36 testnet started in screen '$NODE_NAME'"
            echo "  Attach:   screen -r $NODE_NAME"
            echo "  Logs:     tail -f $LOG_FILE"
            echo "  Web UI:   http://NODE_A_IP:19327/"
        else
            echo "FAILED to start. Check: $LOG_FILE"
            tail -50 "$LOG_FILE" 2>/dev/null
            exit 1
        fi
        ;;
    fg|foreground)
        stop_graceful
        sleep 1
        show_status

        echo "Starting in foreground mode (Ctrl+C to stop)..."
        pypy run_p2pool.py \
            --net litecoin \
            --testnet \
            --bitcoind-address "$LTC_RPC_HOST" \
            --bitcoind-rpc-port "$LTC_RPC_PORT" \
            --bitcoind-p2p-port "$LTC_P2P_PORT" \
            --merged-coind-address "$DOGE_ADAPTER_HOST" \
            --merged-coind-rpc-port "$DOGE_ADAPTER_PORT" \
            --merged-coind-rpc-user "$DOGE_RPC_USER" \
            --merged-coind-rpc-password "$DOGE_RPC_PASS" \
            --merged-coind-p2p-address "$DOGE_P2P_HOST" \
            --merged-coind-p2p-port "$DOGE_P2P_PORT" \
            --merged-operator-address "$DOGE_OPERATOR_ADDRESS" \
            -a "$LTC_ADDRESS" \
            --coinbtext "$COINB_TEXT" \
            --give-author "$GIVE_AUTHOR" \
            -f "$POOL_FEE" \
            --disable-upnp \
            --max-conns "$MAX_CONNS" \
            -n "$PEER_NODE30" \
            -n "$PEER_NODE33" \
            "$LTC_RPC_USER" "$LTC_RPC_PASS" \
            2>&1 | tee -a "$LOG_FILE"
        ;;
    start|*)
        stop_graceful
        sleep 2
        show_status

        echo "Starting in screen session '$NODE_NAME'..."
        screen -dmS "$NODE_NAME" bash -c "
            export PATH=\"$PYPY_PATH:\$PATH\"
            export LD_LIBRARY_PATH=\"${LD_LIBRARY_PATH:-}\"
            cd $SCRIPT_DIR
            pypy run_p2pool.py \\
                --net litecoin \\
                --testnet \\
                --bitcoind-address $LTC_RPC_HOST \\
                --bitcoind-rpc-port $LTC_RPC_PORT \\
                --bitcoind-p2p-port $LTC_P2P_PORT \\
                --merged-coind-address $DOGE_ADAPTER_HOST \\
                --merged-coind-rpc-port $DOGE_ADAPTER_PORT \\
                --merged-coind-rpc-user $DOGE_RPC_USER \\
                --merged-coind-rpc-password $DOGE_RPC_PASS \\
                --merged-coind-p2p-address $DOGE_P2P_HOST \\
                --merged-coind-p2p-port $DOGE_P2P_PORT \\
                --merged-operator-address $DOGE_OPERATOR_ADDRESS \\
                -a $LTC_ADDRESS \\
                --coinbtext $COINB_TEXT \\
                --give-author $GIVE_AUTHOR \\
                -f $POOL_FEE \\
                --disable-upnp \\
                --max-conns $MAX_CONNS \\
                -n $PEER_NODE30 \\
                -n $PEER_NODE33 \\
                --no-console \\
                $LTC_RPC_USER $LTC_RPC_PASS \\
                2>&1 | tee -a $LOG_FILE
        "

        sleep 3
        if pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null 2>&1; then
            echo "P2Pool v36 testnet started in screen '$NODE_NAME'"
            echo "  Attach:   screen -r $NODE_NAME"
            echo "  Logs:     tail -f $LOG_FILE"
            echo "  Web UI:   http://NODE_A_IP:19327/"
        else
            echo "FAILED to start. Check: $LOG_FILE"
            tail -50 "$LOG_FILE" 2>/dev/null
            exit 1
        fi
        ;;
esac
