from p2pool.bitcoin import networks

PARENT = networks.nets['frycoin']
SHARE_PERIOD = 10 # seconds target spacing
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares coinbase maturity
SPREAD = 50 # blocks
IDENTIFIER = 'fd467279436f696e'.decode('hex')
PREFIX = 'fe436f696e465259'.decode('hex')
P2P_PORT = 8900
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9900
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org taken.pl'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
