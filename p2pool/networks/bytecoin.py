from p2pool.bitcoin import networks

PARENT = networks.nets['bytecoin']
SHARE_PERIOD = 30 # seconds
CHAIN_LENGTH = 24*60*60//30 # shares
REAL_CHAIN_LENGTH = 24*60*60//30 # shares
TARGET_LOOKBEHIND = 10 # shares
SPREAD = 12 # blocks
IDENTIFIER = 'b3f956dceaab0c5d'.decode('hex')
PREFIX = '2671ae5f267aafb6'.decode('hex')
P2P_PORT = 8743
PERSIST = False
WORKER_PORT = 9743
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
