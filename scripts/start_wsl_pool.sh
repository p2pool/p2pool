#!/bin/bash
# Start P2Pool + MM-Adapter in WSL2
# Usage: bash ~/p2pool-merged-v36/scripts/start_wsl_pool.sh

set -e
export PATH="$HOME/pypy2.7-v7.3.17-linux64/bin:$PATH"

echo "=== Starting MM-Adapter ==="
cd ~/p2pool-merged-v36/mm-adapter
source venv/bin/activate
python3 adapter.py --config config_mainnet.yaml > /tmp/mm-adapter.log 2>&1 &
ADAPTER_PID=$!
echo "MM-Adapter started (PID=$ADAPTER_PID)"
sleep 3

if ! kill -0 $ADAPTER_PID 2>/dev/null; then
    echo "ERROR: MM-Adapter failed to start!"
    cat /tmp/mm-adapter.log
    exit 1
fi
echo "MM-Adapter running OK"

echo ""
echo "=== Starting P2Pool ==="
cd ~/p2pool-merged-v36
pypy run_p2pool.py \
    --net litecoin \
    --coind-address LTC_DAEMON_IP \
    --coind-rpc-port 9332 \
    --coind-p2p-port 9333 \
    --merged-coind-address 127.0.0.1 \
    --merged-coind-rpc-port 44556 \
    --merged-coind-p2p-port 22556 \
    --merged-coind-p2p-address DOGE_DAEMON_IP \
    --merged-coind-rpc-user dogecoinrpc \
    --merged-coind-rpc-password YOUR_DOGE_RPC_PASSWORD \
    --address YOUR_LTC_ADDRESS \
    --give-author 2 \
    -f 0 \
    --disable-upnp \
    --max-conns 20 \
    -w 9327 \
    --redistribute boost \
    litecoinrpc YOUR_LTC_RPC_PASSWORD \
    > /tmp/p2pool.log 2>&1 &
P2POOL_PID=$!
echo "P2Pool started (PID=$P2POOL_PID)"
sleep 8

if ! kill -0 $P2POOL_PID 2>/dev/null; then
    echo "ERROR: P2Pool failed to start!"
    tail -30 /tmp/p2pool.log
    exit 1
fi

echo ""
echo "=== Status ==="
echo "MM-Adapter PID: $ADAPTER_PID"
echo "P2Pool PID:     $P2POOL_PID"
echo ""
echo "--- MM-Adapter log ---"
cat /tmp/mm-adapter.log
echo ""
echo "--- P2Pool log (last 30 lines) ---"
tail -30 /tmp/p2pool.log
echo ""
echo "=== Dashboard: http://localhost:9327/ ==="
