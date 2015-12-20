from p2pool.bitcoin import networks

PARENT = networks.nets['reddcoin']
SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'aad90ef5c6caba7e'.decode('hex')
PREFIX = 'de161ae1bc2e58a0'.decode('hex')
P2P_PORT = 8443
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9443
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org redd.freily.com'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
