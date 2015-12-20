from p2pool.bitcoin import networks

PARENT = networks.nets['polcoin']
SHARE_PERIOD = 20 # seconds
CHAIN_LENGTH = 12*60*60//20 # shares
REAL_CHAIN_LENGTH = 12*60*60//20 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'f6eef0aab1cc0abb'.decode('hex')
PREFIX = 'e6ff0baacc6eeaa1'.decode('hex')
P2P_PORT = 8883
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 9883
BOOTSTRAP_ADDRS = 'salomon.styx.net.pl rav3n.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
