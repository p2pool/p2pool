# Example: Custom Private P2Pool Network Configuration
# This demonstrates how to create a private pool with custom CHAIN_LENGTH
# Copy and modify this file to create your own private network

from p2pool.dash import networks

PARENT = networks.nets['dash']
SHARE_PERIOD = 20 # seconds between shares

# ===== CUSTOM CHAIN LENGTH =====
# Example: 5 days worth of shares
# 5 days * 24 hours/day * 60 min/hour * 60 sec/min / 20 sec/share = 21,600 shares
CHAIN_LENGTH = 5*24*60*60//SHARE_PERIOD  # 21600 shares = 5 days
REAL_CHAIN_LENGTH = 5*24*60*60//SHARE_PERIOD  # Must equal CHAIN_LENGTH for new networks

# Important: REAL_CHAIN_LENGTH determines payout window
# With 5 day chain, miners get paid from shares in last 5 days
# Longer chain = more stable payouts but slower response to hashrate changes

TARGET_LOOKBEHIND = 100 # shares for difficulty adjustment (keep at 100)
SPREAD = 10 # blocks
IDENTIFIER = 'CUSTOM01'.encode('hex').decode('hex')  # Change this to make unique network
PREFIX = 'PRIV0001'.encode('hex').decode('hex')      # Change this too
COINBASEEXT = '0D2F43757374506F6F6C2F'.decode('hex')  # "/CustPool/" in hex
P2P_PORT = 8998  # Change to avoid conflicts
MIN_TARGET = 0
MAX_TARGET = 0xFFFF * 2**208  # Standard difficulty 1
PERSIST = True
WORKER_PORT = 7902  # Change to avoid conflicts
BOOTSTRAP_ADDRS = ''.split(' ')  # No bootstrap for private network
ANNOUNCE_CHANNEL = '#my-custom-pool'
VERSION_CHECK = lambda v: v >= 200000
MINIMUM_PROTOCOL_VERSION = 1700

# Stratum Vardiff Configuration
STRATUM_SHARE_RATE = 10

# ===== IMPORTANT NOTES =====
# 
# 1. ARCHIVAL AUTOMATICALLY ADJUSTS:
#    - Archives shares older than 2*CHAIN_LENGTH (43,200 shares = 10 days)
#    - Always keeps 2× safety margin
#    - Works with any CHAIN_LENGTH value
#
# 2. MEMORY USAGE:
#    - Larger CHAIN_LENGTH = more RAM needed
#    - 21,600 shares ≈ 5× memory vs default (4,320 shares)
#    - Plan accordingly for your server capacity
#
# 3. DISK USAGE:
#    - Pickle files grow with CHAIN_LENGTH
#    - Archives accumulate faster with longer chains
#    - Set up archive cleanup (see SHARE_ARCHIVE_README.md)
#
# 4. PAYOUT BEHAVIOR:
#    - Miners receive payouts based on REAL_CHAIN_LENGTH window
#    - 5 day window = very stable payouts
#    - But takes 5 days for new miners to reach full payout
#
# 5. ALL FEATURES AUTO-SCALE:
#    - Difficulty adjustment (uses TARGET_LOOKBEHIND, not CHAIN_LENGTH)
#    - Archive threshold (2*CHAIN_LENGTH)
#    - Statistics lookback (min of CHAIN_LENGTH and specific periods)
#    - Share validation (far_share_hash at 99 shares back)
#
# 6. NETWORK ISOLATION:
#    - Custom IDENTIFIER and PREFIX ensure network isolation
#    - Won't connect to mainnet nodes
#    - Need to manually connect private pool nodes
#
# 7. TESTING FIRST:
#    - Test with dash_regtest network first (CHAIN_LENGTH=100)
#    - Verify archival works before going to production
#    - Monitor memory/disk usage patterns

# To use this network:
# python run_p2pool.py --net dash_custom_example <address>
