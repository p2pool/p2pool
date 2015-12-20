from p2pool.bitcoin import networks

PARENT = networks.nets['Coin']
SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 30 # blocks
IDENTIFIER = 'a0cfe405c16bc9cb'.decode('hex')
PREFIX = 'afcc0aecfe4c04c9'.decode('hex')
P2P_PORT = 24001
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 24002
BOOTSTRAP_ADDRS = 'p2pool-us.coin-project.org p2pool-eu.coin-project.org rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org taken.pl'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
