from p2pool.bitcoin import networks

PARENT = networks.nets['marscoin']
SHARE_PERIOD = 15 # seconds
CHAIN_LENGTH = 12*60*60//15 # shares
REAL_CHAIN_LENGTH = 12*60*60//15 # shares
TARGET_LOOKBEHIND = 10 # shares
SPREAD = 30 # blocks
IDENTIFIER = 'eeaa00ee72b8e1a0'.decode('hex')
PREFIX = 'e7bbaa99ee510be1'.decode('hex')
P2P_PORT = 8218
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9218
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
VERSION_WARNING = lambda v: 'Upgrade Litecoin to >=0.8.5.1!' if v < 80501 else None
