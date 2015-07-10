from p2pool.bitcoin import networks

PARENT = networks.nets['coinye']
SHARE_PERIOD = 15 # seconds
CHAIN_LENGTH = 3*60*60//10 # shares
REAL_CHAIN_LENGTH = 3*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 10 # blocks
IDENTIFIER = 'D0D1F1D3B2F68CDD'.decode('hex')
PREFIX = 'F2D3D4D541C11DDD'.decode('hex')
P2P_PORT = 8557
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9557
BOOTSTRAP_ADDRS = 'us-east1.cryptovein.com rav3n.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
