from p2pool.dash import networks

PARENT = networks.nets['dash']
SHARE_PERIOD = 20 # seconds
CHAIN_LENGTH = 24*60*60//20 # shares  # 4320 shares = 24 hours
REAL_CHAIN_LENGTH = 24*60*60//20 # shares
TARGET_LOOKBEHIND = 100 # shares  //with that the pools share diff is adjusting faster, important if huge hashing power comes to the pool
SPREAD = 10 # blocks
IDENTIFIER = '7242ef345e1bed6b'.decode('hex')
PREFIX = '3b3e1286f446b891'.decode('hex')
COINBASEEXT = '0D2F5032506F6F6C2D444153482F'.decode('hex')
P2P_PORT = 8999
MIN_TARGET = 0
# MAX_TARGET defines the easiest P2Pool share difficulty
# Use standard bdiff difficulty 1 target (0x00000000FFFF00...) for ~1.0 minimum difficulty
# Old value 2**256//2**20 - 1 gave difficulty ~0.000244 which is way too easy
MAX_TARGET = 0xFFFF * 2**208  # Standard bdiff difficulty 1 target
PERSIST = True  # Enable peer connections (works in solo mode too)
WORKER_PORT = 7903
BOOTSTRAP_ADDRS = 'rov.p2p-spb.xyz'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-dash'
VERSION_CHECK = lambda v: v >= 200000
MINIMUM_PROTOCOL_VERSION = 1700  # Protocol v1700: '!' prefix for script payments

# ==== Stratum Vardiff Configuration ====
# These parameters are tuned for ASIC miners with stable hashrates
# Based on jtoomim's p2pool vardiff algorithm

STRATUM_SHARE_RATE = 10  # Target seconds per pseudoshare for stratum vardiff

# Vardiff trigger thresholds (jtoomim uses 12 shares, 10x timeout)
VARDIFF_SHARES_TRIGGER = 8      # Adjust after this many shares collected
VARDIFF_TIMEOUT_MULT = 5        # Adjust if no shares for (timeout_mult * target_time)
VARDIFF_QUICKUP_SHARES = 2      # Minimum shares for quick upward adjustment
VARDIFF_QUICKUP_DIVISOR = 3     # Adjust up if time < target_time / divisor

# Vardiff adjustment limits (jtoomim uses 0.5-2.0)
VARDIFF_MIN_ADJUST = 0.5        # Minimum adjustment multiplier (halve difficulty)
VARDIFF_MAX_ADJUST = 2.0        # Maximum adjustment multiplier (double difficulty)

# ==== Connection Threat Detection ====
# Detect suspicious connection patterns per IP address
# These thresholds define connection/worker ratios that trigger threat alerts

# Normal: Legitimate multi-rig miners (e.g., 4 machines = 4 workers = 4 connections)
CONNECTION_WORKER_ELEVATED = 4.0   # Elevated threat: >4 connections per worker
CONNECTION_WORKER_WARNING = 6.0     # Warning threat: >6 connections per worker

