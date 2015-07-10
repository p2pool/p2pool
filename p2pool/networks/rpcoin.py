from p2pool.bitcoin import networks

PARENT = networks.nets['rpcoin']
SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'faf1e34fb0c7ef21'.decode('hex')
PREFIX = 'e0ff56a1340e56f1'.decode('hex')
P2P_PORT = 8127
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9127
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
