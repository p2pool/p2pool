from p2pool.bitcoin import networks

PARENT = networks.nets['smartcoin']
SHARE_PERIOD = 5 # seconds
CHAIN_LENGTH = 12*60*60//5 # shares
REAL_CHAIN_LENGTH = 12*60*60//5 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'defadefaced0ced0'.decode('hex')
PREFIX = 'd0cededefafac0ce'.decode('hex')
P2P_PORT = 8585
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9585
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
