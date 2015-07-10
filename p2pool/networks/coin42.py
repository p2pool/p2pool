from p2pool.bitcoin import networks

PARENT = networks.nets['coin42']
SHARE_PERIOD = 5 # seconds
CHAIN_LENGTH = 12*60*60//5 # shares
REAL_CHAIN_LENGTH = 12*60*60//5 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'ff42c01442c0c0ff'.decode('hex')
PREFIX = 'ee42c014aa42c014'.decode('hex')
P2P_PORT = 8042
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9042
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
