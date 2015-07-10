from p2pool.bitcoin import networks

PARENT = networks.nets['asiccoin']
SHARE_PERIOD = 20 # seconds
CHAIN_LENGTH = 12*60*60//20 # shares
REAL_CHAIN_LENGTH = 12*60*60//20 # shares
TARGET_LOOKBEHIND = 10 # shares
SPREAD = 30 # blocks
IDENTIFIER = 'f9eef0abe30faac7'.decode('hex')
PREFIX = 'aa0e7f5b1af50ce7'.decode('hex')
P2P_PORT = 7432
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 9433
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-asc'
VERSION_CHECK = lambda v: True
