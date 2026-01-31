from p2pool.dash import networks

PARENT = networks.nets['dash_testnet']
SHARE_PERIOD = 20 # seconds
CHAIN_LENGTH = 24*60*60//20 # shares
REAL_CHAIN_LENGTH = 24*60*60//20 # shares
TARGET_LOOKBEHIND = 100 # shares  //with that the pools share diff is adjusting faster, important if huge hashing power comes to the pool
SPREAD = 10 # blocks
IDENTIFIER = 'b6deb1e543fe2427'.decode('hex')
PREFIX = '198b644f6821e3b3'.decode('hex')
COINBASEEXT = '0E2F5032506F6F6C2D74444153482F'.decode('hex')
P2P_PORT = 18999
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 17903
BOOTSTRAP_ADDRS = 'p2pool.dashninja.pl test.p2pool.masternode.io test.p2pool.dash.siampm.com'.split(' ')
ANNOUNCE_CHANNEL = ''
VERSION_CHECK = lambda v: v >= 200000
MINIMUM_PROTOCOL_VERSION = 1700  # Protocol v1700: '!' prefix for script payments

# ==== Stratum Vardiff Configuration ====
# Testnet can use more aggressive settings for faster testing
STRATUM_SHARE_RATE = 10  # Target seconds per pseudoshare

# Vardiff trigger thresholds (more aggressive for testnet)
VARDIFF_SHARES_TRIGGER = 5      # Adjust after this many shares
VARDIFF_TIMEOUT_MULT = 3        # Adjust if no shares for (timeout_mult * target_time)
VARDIFF_QUICKUP_SHARES = 2      # Minimum shares for quick upward adjustment
VARDIFF_QUICKUP_DIVISOR = 4     # Adjust up if time < target_time / divisor

# Vardiff adjustment limits (wider range for testnet)
VARDIFF_MIN_ADJUST = 0.25       # Minimum adjustment multiplier
VARDIFF_MAX_ADJUST = 4.0        # Maximum adjustment multiplier

# ==== Connection Threat Detection ====
CONNECTION_WORKER_ELEVATED = 4.0   # Elevated threat: >4 connections per worker
CONNECTION_WORKER_WARNING = 6.0     # Warning threat: >6 connections per worker

