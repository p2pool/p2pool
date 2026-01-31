from p2pool.bitcoin import networks

PARENT = networks.nets['litecoin']
SHARE_PERIOD = 15 # seconds
CHAIN_LENGTH = 24*60*60//10 # shares
REAL_CHAIN_LENGTH = 24*60*60//10 # shares
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 3 # blocks
# EXPERIMENTAL: Changed magic bytes to isolate from production network
IDENTIFIER = 'deadbeef12345678'.decode('hex')  # was e037d5b8c6923410
PREFIX = 'cafebabe87654321'.decode('hex')  # was 7208c1a53ef629b0
P2P_PORT = 9326
MIN_TARGET = 0
# MAX_TARGET: Share Difficulty Floor (easiest allowed)
# =====================================================
# This sets the MINIMUM share difficulty. Vardiff auto-adjusts UP from here.
#
# Formula: stratum_diff = (0xffff0000 * 2**192 / target) * 65536
#   2**256//2**20 = diff 16  -> 5.3 sec/share at 13 GH/s (too fast, floods)
#   2**256//2**21 = diff 32  -> 10.6 sec/share at 13 GH/s (good balance)
#   2**256//2**22 = diff 64  -> 21.1 sec/share at 13 GH/s
#   2**256//2**24 = diff 256 -> 84.6 sec/share at 13 GH/s (too slow for small pools)
#
# If floor is too easy: share flooding -> network can't propagate -> orphans
# If floor is too hard: small miners wait too long -> vardiff stuck at floor
#
# Current: diff 32, optimal for ~10-50 GH/s pools. Larger pools auto-adjust higher.
MAX_TARGET = 2**256//2**21 - 1
PERSIST = True
WORKER_PORT = 9327
# EXPERIMENTAL: Bootstrap disabled for isolated testing
BOOTSTRAP_ADDRS = []
ANNOUNCE_CHANNEL = '#p2pool-ltc'
VERSION_CHECK = lambda v: None if 100400 <= v else 'Litecoin version too old. Upgrade to 0.10.4 or newer!'
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit', 'taproot', 'mweb'])
MINIMUM_PROTOCOL_VERSION = 3301
SEGWIT_ACTIVATION_VERSION = 17
BLOCK_MAX_SIZE = 1000000
BLOCK_MAX_WEIGHT = 4000000
