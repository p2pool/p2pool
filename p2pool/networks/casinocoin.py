from p2pool.bitcoin import networks

PARENT = networks.nets['casinocoin']
SHARE_PERIOD = 5 # seconds target spacing
CHAIN_LENGTH = 3*60*60//5 # shares (3 hr PPLNS)
REAL_CHAIN_LENGTH = 3*60*60//5 # shares (3 hr PPLNS)
TARGET_LOOKBEHIND = 60 # shares coinbase maturity (5 min diff adj)
SPREAD = 60 # blocks (share valid up to 60 blocks - better for smaller miners)
IDENTIFIER = '7696C5EF0B281C2F'.decode('hex')
PREFIX = '4C2E2CD651764B9F'.decode('hex')
P2P_PORT = 23640
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 8840
BOOTSTRAP_ADDRS = 'csc.xpool.net bigiron.homelinux.com rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
