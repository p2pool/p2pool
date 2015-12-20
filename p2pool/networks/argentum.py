from p2pool.bitcoin import networks

PARENT = networks.nets['argentum']
SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = '6d3511cbbed25932'.decode('hex')
PREFIX = 'f63832c5c86038dd'.decode('hex')
P2P_PORT = 18012
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 8012
BOOTSTRAP_ADDRS = 'p2pool.name p2poolmining.org althash.com coinworld.us rav3n.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
