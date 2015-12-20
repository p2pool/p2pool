from p2pool.bitcoin import networks

PARENT = networks.nets['joulecoin']
SHARE_PERIOD = 20 # seconds
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 10 # blocks
IDENTIFIER = 'ac556af4e900ca61'.decode('hex')
PREFIX = '16ac009e4fa655ac'.decode('hex')
P2P_PORT = 7844
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 9844
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
