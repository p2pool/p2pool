from p2pool.bitcoin import networks

PARENT = networks.nets['mooncoin']
SHARE_PERIOD = 25 # seconds target spacing
CHAIN_LENGTH = 12*60*60//25 # shares
REAL_CHAIN_LENGTH = 12*60*60//25 # shares
TARGET_LOOKBEHIND = 20 # shares coinbase maturity
SPREAD = 10 # blocks
IDENTIFIER = 'e8e8c0c0f7f7f9f9'.decode('hex')
PREFIX = 'c0c0e8e8f7f7f9f9'.decode('hex')
P2P_PORT = 8664
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9664
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
