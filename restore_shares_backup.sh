#!/bin/bash
# P2Pool Share Backup Restoration Script
# 
# Usage: ./restore_shares_backup.sh [backup_directory]
#        ./restore_shares_backup.sh         (lists available backups)
#
# IMPORTANT: Stop p2pool before restoring!

DATADIR="data"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "P2Pool Share Backup Restoration Tool"
echo "================================================"
echo ""

# Check if p2pool is running
if pgrep -f "run_p2pool.py" > /dev/null; then
    echo -e "${RED}ERROR: p2pool is currently running!${NC}"
    echo "Please stop p2pool before restoring backups:"
    echo "  pkill -f run_p2pool.py"
    echo ""
    exit 1
fi

BACKUP_DIR="$DATADIR/share_backups"

# Check if backup directory exists
if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${RED}ERROR: Backup directory not found: $BACKUP_DIR${NC}"
    exit 1
fi

# List available backups
BACKUPS=($(ls -1dt "$BACKUP_DIR"/backup_* 2>/dev/null))

if [ ${#BACKUPS[@]} -eq 0 ]; then
    echo -e "${YELLOW}No backups found in $BACKUP_DIR${NC}"
    exit 0
fi

# If no argument provided, list backups and exit
if [ -z "$1" ]; then
    echo "Available backups:"
    echo ""
    for i in "${!BACKUPS[@]}"; do
        backup="${BACKUPS[$i]}"
        backup_name=$(basename "$backup")
        manifest="$backup/MANIFEST.txt"
        
        echo -e "${GREEN}[$i]${NC} $backup_name"
        
        if [ -f "$manifest" ]; then
            echo "    $(grep 'Created:' "$manifest")"
            echo "    $(grep 'Reason:' "$manifest")"
            echo "    $(grep 'Files backed up:' "$manifest")"
            echo "    $(grep 'Total size:' "$manifest")"
            echo "    $(grep 'Chain height:' "$manifest")"
        fi
        echo ""
    done
    
    echo "To restore a backup, run:"
    echo "  ./restore_shares_backup.sh <backup_directory>"
    echo "  or"
    echo "  ./restore_shares_backup.sh [index_number]"
    echo ""
    exit 0
fi

# Determine which backup to restore
if [[ "$1" =~ ^[0-9]+$ ]]; then
    # Numeric index provided
    idx=$1
    if [ $idx -ge ${#BACKUPS[@]} ]; then
        echo -e "${RED}ERROR: Invalid backup index: $idx${NC}"
        echo "Available indices: 0 to $((${#BACKUPS[@]} - 1))"
        exit 1
    fi
    RESTORE_DIR="${BACKUPS[$idx]}"
else
    # Full path or directory name provided
    if [ -d "$1" ]; then
        RESTORE_DIR="$1"
    elif [ -d "$BACKUP_DIR/$1" ]; then
        RESTORE_DIR="$BACKUP_DIR/$1"
    else
        echo -e "${RED}ERROR: Backup not found: $1${NC}"
        exit 1
    fi
fi

# Verify backup directory
if [ ! -d "$RESTORE_DIR" ]; then
    echo -e "${RED}ERROR: Backup directory does not exist: $RESTORE_DIR${NC}"
    exit 1
fi

echo "Selected backup: $(basename "$RESTORE_DIR")"
echo ""

# Show manifest if available
manifest="$RESTORE_DIR/MANIFEST.txt"
if [ -f "$manifest" ]; then
    echo "Backup details:"
    cat "$manifest"
    echo ""
fi

# Count pickle files in backup
pickle_count=$(ls -1 "$RESTORE_DIR"/shares.* 2>/dev/null | wc -l)
if [ $pickle_count -eq 0 ]; then
    echo -e "${RED}ERROR: No pickle files found in backup${NC}"
    exit 1
fi

echo -e "${YELLOW}WARNING: This will replace your current share storage!${NC}"
echo "Pickle files to restore: $pickle_count"
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Restoration cancelled."
    exit 0
fi

# Detect network (dash, dash_testnet, dash_regtest)
for network in dash dash_testnet dash_regtest; do
    NETWORK_DIR="$DATADIR/$network"
    if [ -d "$NETWORK_DIR" ]; then
        echo ""
        echo "Found network directory: $network"
        
        # Create emergency backup of current state
        EMERGENCY_BACKUP="$BACKUP_DIR/emergency_before_restore_$(date +%s)"
        mkdir -p "$EMERGENCY_BACKUP"
        
        echo "Creating emergency backup of current state..."
        cp "$NETWORK_DIR"/shares.* "$EMERGENCY_BACKUP/" 2>/dev/null
        emergency_count=$(ls -1 "$EMERGENCY_BACKUP"/shares.* 2>/dev/null | wc -l)
        echo "  Backed up $emergency_count files to: $(basename "$EMERGENCY_BACKUP")"
        
        # Restore pickle files
        echo "Restoring pickle files..."
        cp "$RESTORE_DIR"/shares.* "$NETWORK_DIR/" 2>/dev/null
        restored_count=$(ls -1 "$NETWORK_DIR"/shares.* 2>/dev/null | wc -l)
        
        echo -e "${GREEN}Successfully restored $restored_count pickle files${NC}"
        echo ""
        echo "Emergency backup created at: $EMERGENCY_BACKUP"
        echo "You can now start p2pool."
        echo ""
    fi
done

echo -e "${GREEN}Restoration complete!${NC}"
