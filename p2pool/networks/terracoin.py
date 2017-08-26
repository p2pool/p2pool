from p2pool.bitcoin import networks

PARENT = networks.nets['terracoin']
SHARE_PERIOD = 45 # seconds
CHAIN_LENGTH = 24*60*60//30 # shares
REAL_CHAIN_LENGTH = 24*60*60//30 # shares
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 10 # blocks
IDENTIFIER = 'a42a265ad1b6d42b'.decode('hex')
PREFIX = '56a3f62173d2a9b5'.decode('hex')
P2P_PORT = 9323
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = True
WORKER_PORT = 9322
BOOTSTRAP_ADDRS = 'seed1.p2pool.terracoin.org seed2.p2pool.terracoin.org seed3.p2pool.terracoin.org forre.st vps.forre.st 93.97.192.93 66.90.73.83 67.83.108.0 219.84.64.174 24.167.17.248 109.74.195.142 83.211.86.49 94.23.34.145 168.7.116.243 94.174.40.189:9344 89.79.79.195 portals94.ns01.us p2pool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: 80002 <= v
VERSION_WARNING = lambda v: 'Upgrade Terracoin to >= 0.8.0.4!' if v < 80004 else None
