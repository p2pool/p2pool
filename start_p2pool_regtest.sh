#!/bin/bash
# P2Pool-Dash REGTEST start script for testing

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/p2pool_regtest.log"

# Regtest address (generate one with: dash-cli -regtest getnewaddress)
REGTEST_ADDRESS="yTodnMujHcP34cfsjX2RFgJ56LJiYyDhZc"

# Function to gracefully stop existing regtest instances (SIGTERM)
stop_graceful() {
    local show_logs="${1:-false}"
    
    echo "Checking for existing P2Pool regtest instances..."
    if pgrep -f "pypy.*run_p2pool.*dash_regtest" > /dev/null; then
        echo "Gracefully stopping P2Pool regtest instance(s)..."
        
        # Show last few log lines before shutdown
        if [ "$show_logs" = "true" ] && [ -f "$LOG_FILE" ]; then
            echo ""
            echo "=== Last 5 lines before shutdown ==="
            tail -5 "$LOG_FILE"
            echo "==================================="
            echo ""
        fi
        
        pkill -TERM -f "pypy.*run_p2pool.*dash_regtest"
        
        # Wait up to 10 seconds for graceful shutdown
        for i in {1..10}; do
            if ! pgrep -f "pypy.*run_p2pool.*dash_regtest" > /dev/null; then
                echo "P2Pool regtest stopped gracefully"
                
                # Show shutdown logs if requested
                if [ "$show_logs" = "true" ] && [ -f "$LOG_FILE" ]; then
                    echo ""
                    echo "=== Shutdown logs ==="
                    tail -10 "$LOG_FILE" | grep -A 10 "Graceful shutdown" || tail -10 "$LOG_FILE"
                    echo "====================="
                fi
                
                return 0
            fi
            sleep 1
        done
        
        # Force kill if still running
        if pgrep -f "pypy.*run_p2pool.*dash_regtest" > /dev/null; then
            echo "Warning: Graceful shutdown timed out, forcing kill..."
            pkill -9 -f "pypy.*run_p2pool.*dash_regtest"
            sleep 1
        fi
    else
        echo "No P2Pool regtest instance running"
    fi
}

# Function to force kill existing regtest instances (SIGKILL)
kill_force() {
    echo "Checking for existing P2Pool regtest instances..."
    if pgrep -f "pypy.*run_p2pool.*dash_regtest" > /dev/null; then
        echo "Force killing P2Pool regtest instance(s)..."
        pkill -9 -f "pypy.*run_p2pool.*dash_regtest"
        sleep 1
    fi
}

# Parse arguments
case "$1" in
    stop)
        stop_graceful "true"
        exit 0
        ;;
    kill)
        kill_force
        exit 0
        ;;
esac

# Default: start in foreground
stop_graceful
echo "Starting P2Pool in REGTEST mode..."
echo "Log file: $LOG_FILE"

pypy run_p2pool.py --net dash_regtest \
    --coind-address 127.0.0.1 \
    --coind-rpc-port 19998 \
    -a "$REGTEST_ADDRESS" \
    --give-author 0 \
    "$@" 2>&1 | tee -a "$LOG_FILE"
