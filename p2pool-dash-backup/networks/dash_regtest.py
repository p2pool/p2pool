from p2pool.dash import networks

PARENT = networks.nets['dash_regtest']
SHARE_PERIOD = 10 # seconds - faster for testing
CHAIN_LENGTH = 100 # shares - shorter chain for testing
REAL_CHAIN_LENGTH = 100 # shares
TARGET_LOOKBEHIND = 10 # shares - quick adjustment
SPREAD = 3 # blocks
IDENTIFIER = 'e8d4e5c6f7a8b9c0'.decode('hex')  # Unique for regtest
PREFIX = 'c0d1e2f3a4b5c6d7'.decode('hex')       # Unique for regtest
COINBASEEXT = '0F2F5032506F6F6C2D724441534828'.decode('hex')  # /P2Pool-rDASH/
P2P_PORT = 19799  # Regtest p2pool P2P port
MIN_TARGET = 0
MAX_TARGET = 2**256 - 1  # Allow any difficulty in regtest
PERSIST = False
WORKER_PORT = 19703  # Regtest stratum port
BOOTSTRAP_ADDRS = ''.split(' ')  # No bootstrap for regtest
ANNOUNCE_CHANNEL = ''
VERSION_CHECK = lambda v: v >= 200000

# ==== Stratum Vardiff Configuration ====
STRATUM_SHARE_RATE = 5  # Target seconds per pseudoshare - faster for testing

# Default stratum difficulty - very low for CPU testing
STRATUM_DEFAULT_DIFFICULTY = 0.001  # Low difficulty for CPU miners

# Vardiff settings - aggressive for regtest
VARDIFF_SHARES_TRIGGER = 3
VARDIFF_TIMEOUT_MULT = 3
VARDIFF_QUICKUP_SHARES = 2
VARDIFF_QUICKUP_DIVISOR = 4

VARDIFF_MIN_ADJUST = 0.25
VARDIFF_MAX_ADJUST = 4.0

# ==== Connection Threat Detection ====
CONNECTION_WORKER_ELEVATED = 4.0   # Elevated threat: >4 connections per worker
CONNECTION_WORKER_WARNING = 6.0     # Warning threat: >6 connections per worker

