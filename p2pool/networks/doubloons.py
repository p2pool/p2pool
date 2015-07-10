from p2pool.bitcoin import networks

PARENT = networks.nets['doubloons']
SHARE_PERIOD = 20 # seconds target spacing
CHAIN_LENGTH = 12*60*60//20 # shares
REAL_CHAIN_LENGTH = 12*60*60//20 # shares
TARGET_LOOKBEHIND = 20 # blocks
SPREAD = 30 # blocks
IDENTIFIER = 'fe00ef33b8e122a0'.decode('hex')
PREFIX = 'e100b4e377a284e1'.decode('hex')
P2P_PORT = 8346
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 8345
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
