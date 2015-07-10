from p2pool.bitcoin import networks

PARENT = networks.nets['giftcoin']
SHARE_PERIOD = 10
CHAIN_LENGTH = 12*60*60//10
REAL_CHAIN_LENGTH = 12*60*60//10
TARGET_LOOKBEHIND = 20
SPREAD = 50
IDENTIFIER = 'f0e77e5ea777f087'.decode('hex')
PREFIX = 'aafe077ab57af772'.decode('hex')
P2P_PORT = 8777
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9777
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
