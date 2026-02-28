#!/bin/bash
# P2Pool-Dash start script with auto-kill of existing instances
# Supports: foreground mode, background mode (--daemon), and SSH launching

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/p2pool.log"
PID_FILE="$SCRIPT_DIR/p2pool.pid"

# Function to gracefully stop existing instances (SIGTERM)
stop_graceful() {
    local show_logs="${1:-false}"
    
    echo "Checking for existing P2Pool instances..."
    if pgrep -f "pypy.*run_p2pool" > /dev/null; then
        echo "Gracefully stopping P2Pool instance(s)..."
        
        # Show last few log lines before shutdown
        if [ "$show_logs" = "true" ] && [ -f "$LOG_FILE" ]; then
            echo ""
            echo "=== Last 5 lines before shutdown ==="
            tail -5 "$LOG_FILE"
            echo "==================================="
            echo ""
        fi
        
        # Send SIGTERM for graceful shutdown (allows cleanup/archival)
        pkill -TERM -f "pypy.*run_p2pool"
        
        # Wait up to 10 seconds for graceful shutdown, showing log output
        for i in {1..10}; do
            if ! pgrep -f "pypy.*run_p2pool" > /dev/null; then
                echo "P2Pool stopped gracefully"
                
                # Show shutdown logs if requested
                if [ "$show_logs" = "true" ] && [ -f "$LOG_FILE" ]; then
                    echo ""
                    echo "=== Shutdown logs ==="
                    # Show last 10 lines which should include shutdown messages
                    tail -10 "$LOG_FILE" | grep -A 10 "Graceful shutdown" || tail -10 "$LOG_FILE"
                    echo "====================="
                fi
                
                [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
                return 0
            fi
            sleep 1
        done
        
        # Force kill if still running after 10 seconds
        if pgrep -f "pypy.*run_p2pool" > /dev/null; then
            echo "Warning: Graceful shutdown timed out, forcing kill..."
            pkill -9 -f "pypy.*run_p2pool"
            sleep 1
        fi
    else
        echo "No P2Pool instance running"
    fi
    # Clean up stale PID file
    [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
}

# Function to force kill existing instances (SIGKILL)
kill_force() {
    echo "Checking for existing P2Pool instances..."
    if pgrep -f "pypy.*run_p2pool" > /dev/null; then
        echo "Force killing P2Pool instance(s)..."
        pkill -9 -f "pypy.*run_p2pool"
        sleep 1
    fi
    [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
}

# Function to rotate log if too large (>10MB)
rotate_log() {
    if [ -f "$LOG_FILE" ]; then
        LOG_SIZE=$(stat -c%s "$LOG_FILE" 2>/dev/null || stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)
        if [ "$LOG_SIZE" -gt 10485760 ]; then
            mv "$LOG_FILE" "${LOG_FILE}.old"
            echo "Rotated old log file"
        fi
    fi
}

# Function to start p2pool
start_p2pool() {
    pypy run_p2pool.py --net dash \
        --coind-address 127.0.0.1 \
        --coind-rpc-port 9998 \
        -a XrTwUgw3ikobuXdLKvvSUjL9JpuPs9uqL7 \
        "$@"
}

# Parse arguments
DAEMON_MODE=false
for arg in "$@"; do
    case $arg in
        --daemon|-d)
            DAEMON_MODE=true
            shift
            ;;
        --restart|-r|restart)
            # Restart in daemon mode
            stop_graceful
            rotate_log
            echo "Starting P2Pool in daemon mode (logging to $LOG_FILE)..."
            nohup bash -c "cd '$SCRIPT_DIR' && pypy run_p2pool.py --net dash \
                --coind-address 127.0.0.1 \
                --coind-rpc-port 9998 \
                -a XrTwUgw3ikobuXdLKvvSUjL9JpuPs9uqL7 \
                >> '$LOG_FILE' 2>&1" > /dev/null 2>&1 &
            disown
            echo $! > "$PID_FILE"
            sleep 2
            if pgrep -f "pypy.*run_p2pool" > /dev/null; then
                echo "P2Pool restarted successfully (PID: $(pgrep -f 'pypy.*run_p2pool' | head -1))"
                echo "Log file: $LOG_FILE"
            else
                echo "ERROR: P2Pool failed to restart. Check $LOG_FILE"
                exit 1
            fi
            exit 0
            ;;
        --stop)
            stop_graceful "true"
            exit 0
            ;;
        --kill|-k)
            kill_force
            exit 0
            ;;
        --status|-s)
            if pgrep -f "pypy.*run_p2pool" > /dev/null; then
                echo "P2Pool is running (PID: $(pgrep -f 'pypy.*run_p2pool'))"
                exit 0
            else
                echo "P2Pool is not running"
                exit 1
            fi
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --daemon, -d    Run in background (daemon mode)"
            echo "  --restart, -r   Restart in daemon mode (graceful stop)"
            echo "  --stop          Gracefully stop P2Pool (allows archival)"
            echo "  --kill, -k      Force kill P2Pool (immediate termination)"
            echo "  --status, -s    Check if P2Pool is running"
            echo "  --help, -h      Show this help"
            exit 0
            ;;
    esac
done

# Gracefully stop existing instances before starting
stop_graceful

# Rotate log if needed
rotate_log

if [ "$DAEMON_MODE" = true ]; then
    # Background/daemon mode - suitable for SSH launching
    echo "Starting P2Pool in daemon mode (logging to $LOG_FILE)..."
    nohup bash -c "cd '$SCRIPT_DIR' && pypy run_p2pool.py --net dash \
        --coind-address 127.0.0.1 \
        --coind-rpc-port 9998 \
        -a XrTwUgw3ikobuXdLKvvSUjL9JpuPs9uqL7 \
        >> '$LOG_FILE' 2>&1" > /dev/null 2>&1 &
    disown
    
    # Save PID
    echo $! > "$PID_FILE"
    sleep 2
    
    # Verify it started
    if pgrep -f "pypy.*run_p2pool" > /dev/null; then
        echo "P2Pool started successfully (PID: $(pgrep -f 'pypy.*run_p2pool' | head -1))"
        echo "Log file: $LOG_FILE"
        echo "Use 'tail -f $LOG_FILE' to follow logs"
        exit 0
    else
        echo "ERROR: P2Pool failed to start. Check $LOG_FILE for details."
        exit 1
    fi
else
    # Foreground mode - for interactive use or systemd
    echo "Starting P2Pool in foreground mode (logging to $LOG_FILE)..."
    start_p2pool 2>&1 | tee -a "$LOG_FILE"
fi
