from p2pool.bitcoin import networks

PARENT = networks.nets['litecoin']
SHARE_PERIOD = 15 # seconds
CHAIN_LENGTH = 24*60*60//10 # shares
REAL_CHAIN_LENGTH = 24*60*60//10 # shares
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 3 # blocks
# Global Litecoin P2Pool network identifiers
IDENTIFIER = 'e037d5b8c6923410'.decode('hex')
PREFIX = '7208c1a53ef629b0'.decode('hex')
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
# PERSIST: Sharechain persistence and peer sync mode
# ===================================================
# Controls whether node participates in sharechain sync with network:
#
# True  = Normal operation (RECOMMENDED for production):
#         - Saves sharechain to disk (shares.0, shares.1, ...)
#         - Loads sharechain from disk at startup
#         - Downloads missing parent shares from peers
#         - Connects to BOOTSTRAP_ADDRS and syncs with network
#         - Stricter work event tolerance (3 events) for network consistency
#
# False = Bootstrap/solo mode (for testing or new network):
#         - Does NOT save shares to disk (fresh start each time)
#         - Does NOT require peers - can start its own sharechain
#         - Higher work event tolerance (30 events) for isolated testing
#         - Use when: bootstrapping new sharechain, running solo, testing
PERSIST = True
WORKER_PORT = 9327
BOOTSTRAP_ADDRS = [
        # Active nodes discovered 2025 (protocol 3502)
        'ml.toom.im',           # jtoomim's node - healthy, 1.5% orphan rate
        '31.25.241.224',        # peer from ml.toom.im
        '20.106.76.227',        # peer from ml.toom.im
        '83.221.211.116',       # peer from ml.toom.im
        # Legacy nodes (may be offline)
        'crypto.office-on-the.net',
        'ltc.p2pool.leblancnet.us',
        '51.148.43.34',
        '68.131.29.131',
        '87.102.46.100',
        '89.237.60.231',
        '95.79.35.133',
        '96.255.61.32',
        '174.56.93.93',
        '178.238.236.130',
        '194.190.93.235',
]
ANNOUNCE_CHANNEL = '#p2pool-ltc'
VERSION_CHECK = lambda v: None if 100400 <= v else 'Litecoin version too old. Upgrade to 0.10.4 or newer!'
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit', 'taproot', 'mweb'])
MINIMUM_PROTOCOL_VERSION = 3301
SEGWIT_ACTIVATION_VERSION = 17
BLOCK_MAX_SIZE = 1000000
BLOCK_MAX_WEIGHT = 4000000
