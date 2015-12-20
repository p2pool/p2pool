from p2pool.bitcoin import networks

# CHAIN_LENGTH = number of shares back client keeps
# REAL_CHAIN_LENGTH = maximum number of shares back client uses to compute payout
# REAL_CHAIN_LENGTH must always be <= CHAIN_LENGTH
# REAL_CHAIN_LENGTH must be changed in sync with all other clients
# changes can be done by changing one, then the other

PARENT = networks.nets['crowncoin']
SHARE_PERIOD = 20 # seconds
CHAIN_LENGTH = 12*60*60//20 # shares
REAL_CHAIN_LENGTH = 12*60*60//20 # shares
TARGET_LOOKBEHIND = 15 # shares
SPREAD = 10 # blocks
IDENTIFIER = 'e0b6e1a833f088c1'.decode('hex')
PREFIX = 'a822f60ac511e98a'.decode('hex')
P2P_PORT = 7340
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 8340
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool'
VERSION_CHECK = lambda v: None if 90200 <= v else 'Bitcoin version too old. Upgrade to 0.9.2 or newer!'
VERSION_WARNING = lambda v: None
