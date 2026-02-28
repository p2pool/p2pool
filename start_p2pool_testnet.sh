#!/bin/bash
# P2Pool-Dash TESTNET start script with restart support

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/p2pool_testnet.log"
PID_FILE="$SCRIPT_DIR/p2pool_testnet.pid"

# Testnet address (generate one with: dash-cli -testnet getnewaddress)
TESTNET_ADDRESS="yZkx49ksZKSmFK6caVA2dAK61JsQJqceD8"

# Function to gracefully stop existing testnet instances (SIGTERM)
stop_graceful() {
    local show_logs="${1:-false}"
    
    echo "Checking for existing P2Pool testnet instances..."
    if pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null; then
        echo "Gracefully stopping P2Pool testnet instance(s)..."
        
        # Show last few log lines before shutdown
        if [ "$show_logs" = "true" ] && [ -f "$LOG_FILE" ]; then
            echo ""
            echo "=== Last 5 lines before shutdown ==="
            tail -5 "$LOG_FILE"
            echo "==================================="
            echo ""
        fi
        
        pkill -TERM -f "pypy.*run_p2pool.*testnet"
        
        # Wait up to 10 seconds for graceful shutdown
        for i in {1..10}; do
            if ! pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null; then
                echo "P2Pool testnet stopped gracefully"
                
                # Show shutdown logs if requested
                if [ "$show_logs" = "true" ] && [ -f "$LOG_FILE" ]; then
                    echo ""
                    echo "=== Shutdown logs ==="
                    tail -10 "$LOG_FILE" | grep -A 10 "Graceful shutdown" || tail -10 "$LOG_FILE"
                    echo "====================="
                fi
                
                [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
                return 0
            fi
            sleep 1
        done
        
        # Force kill if still running
        if pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null; then
            echo "Warning: Graceful shutdown timed out, forcing kill..."
            pkill -9 -f "pypy.*run_p2pool.*testnet"
            sleep 1
        fi
    else
        echo "No P2Pool testnet instance running"
    fi
    [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
}

# Function to force kill existing testnet instances (SIGKILL)
kill_force() {
    echo "Checking for existing P2Pool testnet instances..."
    if pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null; then
        echo "Force killing P2Pool testnet instance(s)..."
        pkill -9 -f "pypy.*run_p2pool.*testnet"
        sleep 1
    fi
    [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
}

# Parse arguments
case "$1" in
    restart)
        stop_graceful
        echo "Starting P2Pool in TESTNET daemon mode..."
        echo "Log file: $LOG_FILE"
        
        nohup bash -c "cd '$SCRIPT_DIR' && pypy run_p2pool.py --net dash --testnet \
            --coind-address 127.0.0.1 \
            --coind-rpc-port 19998 \
            --coind-p2p-port 19999 \
            -a $TESTNET_ADDRESS \
            --give-author 0 \
            --web-static web-static \
            >> '$LOG_FILE' 2>&1" > /dev/null 2>&1 &
        disown
        echo $! > "$PID_FILE"
        sleep 3
        
        if pgrep -f "pypy.*run_p2pool.*testnet" > /dev/null; then
            echo "P2Pool testnet restarted successfully (PID: $(pgrep -f 'pypy.*run_p2pool.*testnet' | head -1))"
            tail -20 "$LOG_FILE"
        else
            echo "ERROR: P2Pool failed to restart. Check $LOG_FILE"
            tail -50 "$LOG_FILE"
            exit 1
        fi
        ;;
    stop)
        stop_graceful "true"
        ;;
    kill)
        kill_force
        ;;
    *)
        # Foreground mode with console output
        stop_graceful
        echo "Starting P2Pool in TESTNET foreground mode..."
        echo "Log file: $LOG_FILE"
        
        pypy run_p2pool.py --net dash --testnet \
            --coind-address 127.0.0.1 \
            --coind-rpc-port 19998 \
            --coind-p2p-port 19999 \
            -a "$TESTNET_ADDRESS" \
            --give-author 0 \
            --web-static web-static \
            2>&1 | tee -a "$LOG_FILE"
        ;;
esac
