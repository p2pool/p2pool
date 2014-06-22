from p2pool.bitcoin import networks

PARENT = networks.nets['terracoin_testnet']
SHARE_PERIOD = 30 # seconds
CHAIN_LENGTH = 60*60//30 # shares
REAL_CHAIN_LENGTH = 60*60//30 # shares
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 15 # blocks
IDENTIFIER = 'b41b2356a5b7d35d'.decode('hex')
PREFIX = '1623b92172d2b8a2'.decode('hex')
P2P_PORT = 19323
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 19322
BOOTSTRAP_ADDRS = 'seed1.p2pool.terracoin.org seed2.p2pool.terracoin.org forre.st vps.forre.st'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
VERSION_WARNING = lambda v: 'Upgrade Terracoin to >= 0.8.0.1!' if v < 80001 else None
