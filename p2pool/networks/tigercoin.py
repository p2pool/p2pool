from p2pool.bitcoin import networks

PARENT = networks.nets['tigercoin']
SHARE_PERIOD = 5 # seconds
CHAIN_LENGTH = 12*60*60//5 # shares
REAL_CHAIN_LENGTH = 12*60*60//5 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'b5fafab5dbfdfdd5'.decode('hex')
PREFIX = 'd5fddf5bb5faaffd'.decode('hex')
P2P_PORT = 8660
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 9660
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org japool.com'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
