from p2pool.bitcoin import networks

PARENT = networks.nets['lennycoin']
SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'c1e2b3c4e0b5fefe'.decode('hex')
PREFIX = 'e2e3c4c5b7b9e1ec'.decode('hex')
P2P_PORT = 8556
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9556
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
