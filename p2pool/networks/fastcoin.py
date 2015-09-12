from p2pool.bitcoin import networks

PARENT = networks.nets['fastcoin']
SHARE_PERIOD = 6 # seconds
NEW_SHARE_PERIOD = 6 # seconds
CHAIN_LENGTH = 24*60*60//10 # shares
REAL_CHAIN_LENGTH = 24*60*60//10 # shares
TARGET_LOOKBEHIND = 60 # shares
SPREAD = 150 # blocks
NEW_SPREAD = 150 # blocks
IDENTIFIER = '9f2e390aa41ffade'.decode('hex')
PREFIX = '50f713ab040dfade'.decode('hex')
P2P_PORT = 23660
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = True
WORKER_PORT = 5150
BOOTSTRAP_ADDRS = 'inetrader.com'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-fst'
VERSION_CHECK = lambda v: True
VERSION_WARNING = lambda v: 'Upgrade Fastcoin to >= 0.10.2.2!' if v < 100202 else None
