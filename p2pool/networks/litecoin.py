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
#   2**256//2**20 = diff 16  -> 5.3 sec/share at 13 GH/s (jtoomim default)
#   2**256//2**21 = diff 32  -> 10.6 sec/share at 13 GH/s
#   2**256//2**22 = diff 64  -> 21.1 sec/share at 13 GH/s
#   2**256//2**24 = diff 256 -> 84.6 sec/share at 13 GH/s (too slow for small pools)
#
# If floor is too easy: share flooding -> network can't propagate -> orphans
# If floor is too hard: small miners wait too long -> vardiff stuck at floor
#
# NOTE: MUST match jtoomim/p2pool for V35 compatibility!
MAX_TARGET = 2**256//2**20 - 1
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
        # Active p2pool nodes (verified 2026-02-26 via peer_addresses API)
        'ml.toom.im',           # jtoomim's node (protocol 3502)
        'usa.p2p-spb.xyz',      # p2p-spb pool node (protocol 3502)
        # V36 nodes (protocol 3503)
        '102.160.209.121',      # technocore node29 (v36)
        '5.188.104.245',        # V36 peer
        # Live peers seen by ml.toom.im and usa.p2p-spb.xyz
        '20.127.82.115',        # Azure peer
        '31.25.241.224',        # EU peer
        '20.113.157.65',        # Azure peer
        '20.106.76.227',        # Azure peer
        '15.218.180.55',        # AWS peer
        '173.79.139.224',       # US peer
        '174.60.78.162',        # US peer
]
ANNOUNCE_CHANNEL = '#p2pool-ltc'
VERSION_CHECK = lambda v: None if 100400 <= v else 'Litecoin version too old. Upgrade to 0.10.4 or newer!'
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit', 'taproot', 'mweb'])
MINIMUM_PROTOCOL_VERSION = 3301  # Runtime ratchet in data.py raises this when share versions reach 95%
SEGWIT_ACTIVATION_VERSION = 17
BLOCK_MAX_SIZE = 1000000
BLOCK_MAX_WEIGHT = 4000000
# Some networks have block inclusion/order rules that p2pool doesn't understand (e.g. Litecoin's MWEB)
IMMUTABLE_BLOCKS = True
