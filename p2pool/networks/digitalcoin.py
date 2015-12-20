from p2pool.bitcoin import networks

PARENT = networks.nets['digitalcoin']
SHARE_PERIOD = 10 # seconds target spacing
CHAIN_LENGTH = 24*60*60//10 # shares
REAL_CHAIN_LENGTH = 24*60*60//10 # shares
TARGET_LOOKBEHIND = 200 # shares coinbase maturity
SPREAD = 45 # blocks
IDENTIFIER = '797EC5BC40AFA22E'.decode('hex')
PREFIX = '23CD74AF85036A9F'.decode('hex')
P2P_PORT = 23610
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 8810
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org xpool.net'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
