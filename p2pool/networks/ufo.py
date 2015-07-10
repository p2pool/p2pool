from p2pool.bitcoin import networks

PARENT = networks.nets['ufo']
SHARE_PERIOD = 15 # seconds
CHAIN_LENGTH = 24*60*60//15 # shares
REAL_CHAIN_LENGTH = 24*60*60//15 # shares
TARGET_LOOKBEHIND = 30 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'fc656266636f696e'.decode('hex')
PREFIX = 'fe636e696e6c656a'.decode('hex')
P2P_PORT = 18720
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 19720
BOOTSTRAP_ADDRS = 'dutchpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
