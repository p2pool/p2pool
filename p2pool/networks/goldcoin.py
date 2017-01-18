from p2pool.bitcoin import networks

PARENT = networks.nets['goldcoin']
SHARE_PERIOD = 10 # seconds
NEW_SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 24*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
NEW_SPREAD = 50 # blocks
IDENTIFIER = '673C4A194010994F'.decode('hex')
PREFIX = '673C4A1922156F1F'.decode('hex')
P2P_PORT = 23220
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = True
WORKER_PORT = 8221
BOOTSTRAP_ADDRS = 'inetrader.com'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-gld'
VERSION_CHECK = lambda v: True
VERSION_WARNING = lambda v: 'Upgrade Goldcoin to >= 0.7.2!' if v < 70200 else None