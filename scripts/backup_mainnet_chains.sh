#!/bin/bash
# Backup Mainnet Chains to Storage Server
# Run after both chains are fully synced

STORAGE_SERVER="STORAGE_SERVER"
STORAGE_PATH="/media/nvme2tb"
DATE=$(date +%Y%m%d)

echo "=== Mainnet Blockchain Backup Script ==="
echo "Date: $DATE"
echo "Storage: $STORAGE_SERVER:$STORAGE_PATH"
echo ""

# Check sync status first
check_sync() {
    echo "=== Checking Sync Status ==="
    
    echo "Litecoin:"
    ssh YOUR_USER@LTC_DAEMON_IP "~/.local/bin/litecoin-cli getblockchaininfo 2>&1 | grep -E 'blocks|headers|verificationprogress'"
    
    echo ""
    echo "Dogecoin:"
    ssh YOUR_USER@DOGE_DAEMON_IP "~/dogecoin-1.14.8/bin/dogecoin-cli getblockchaininfo 2>&1 | grep -E 'blocks|headers|verificationprogress'"
    
    echo ""
    read -p "Both chains fully synced? (y/n): " confirm
    if [ "$confirm" != "y" ]; then
        echo "Aborting. Wait for sync to complete."
        exit 1
    fi
}

# Stop daemons before backup
stop_daemons() {
    echo "=== Stopping Daemons for Clean Backup ==="
    
    echo "Stopping Litecoin..."
    ssh YOUR_USER@LTC_DAEMON_IP "~/.local/bin/litecoin-cli stop" 2>/dev/null
    
    echo "Stopping Dogecoin..."
    ssh YOUR_USER@DOGE_DAEMON_IP "~/dogecoin-1.14.8/bin/dogecoin-cli stop" 2>/dev/null
    
    sleep 10
    echo "Daemons stopped."
}

# Backup Litecoin
backup_litecoin() {
    echo "=== Backing up Litecoin Mainnet ==="
    echo "From: LTC_DAEMON_IP:/litecoin-blockchain/mainnet/"
    echo "To: $STORAGE_SERVER:$STORAGE_PATH/.litecoin-mainnet-$DATE/"
    
    # Need 10G interface on Litecoin machine
    ssh YOUR_USER@LTC_DAEMON_IP "sudo ip link set ens224 up; sudo ip addr add STORAGE_NET_LTC/24 dev ens224 2>/dev/null"
    
    # Rsync over 10G
    ssh YOUR_USER@LTC_DAEMON_IP "rsync -av --progress /litecoin-blockchain/mainnet/ YOUR_USER@$STORAGE_SERVER:$STORAGE_PATH/.litecoin-mainnet-$DATE/"
    
    echo "Litecoin backup complete!"
}

# Backup Dogecoin
backup_dogecoin() {
    echo "=== Backing up Dogecoin Mainnet ==="
    echo "From: DOGE_DAEMON_IP:~/.dogecoin/"
    echo "To: $STORAGE_SERVER:$STORAGE_PATH/.dogecoin-mainnet-$DATE/"
    
    # Dogecoin machine may need 10G setup too
    # For now use 1G if 10G not available
    
    ssh YOUR_USER@DOGE_DAEMON_IP "rsync -av --progress ~/.dogecoin/ YOUR_USER@$STORAGE_SERVER:$STORAGE_PATH/.dogecoin-mainnet-$DATE/ --exclude='testnet*' --exclude='debug.log' --exclude='.lock' --exclude='*.pid'"
    
    echo "Dogecoin backup complete!"
}

# Restart daemons after backup
start_daemons() {
    echo "=== Restarting Daemons ==="
    
    ssh YOUR_USER@LTC_DAEMON_IP "sudo systemctl start litecoind-mainnet.service"
    ssh YOUR_USER@DOGE_DAEMON_IP "sudo systemctl start dogecoind-mainnet.service"
    
    sleep 5
    echo "Daemons restarted."
}

# Main
case "${1:-all}" in
    check)
        check_sync
        ;;
    litecoin)
        stop_daemons
        backup_litecoin
        start_daemons
        ;;
    dogecoin)
        stop_daemons
        backup_dogecoin
        start_daemons
        ;;
    all)
        check_sync
        stop_daemons
        backup_litecoin
        backup_dogecoin
        start_daemons
        echo ""
        echo "=== All Backups Complete ==="
        echo "Litecoin: $STORAGE_SERVER:$STORAGE_PATH/.litecoin-mainnet-$DATE/"
        echo "Dogecoin: $STORAGE_SERVER:$STORAGE_PATH/.dogecoin-mainnet-$DATE/"
        ;;
    *)
        echo "Usage: $0 [check|litecoin|dogecoin|all]"
        exit 1
        ;;
esac
