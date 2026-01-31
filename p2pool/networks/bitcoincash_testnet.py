from p2pool.bitcoin import networks

PARENT = networks.nets['bitcoincash_testnet']
SHARE_PERIOD = 60 # seconds -- one minute
CHAIN_LENGTH = 3*24*60 # shares -- three days
REAL_CHAIN_LENGTH = 3*24*60 # shares -- three days
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 3 # blocks
IDENTIFIER = 'c9f3de8d9508faef'.decode('hex')
PREFIX = '08c5541df85a8a65'.decode('hex')
P2P_PORT = 19339
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 19338
BOOTSTRAP_ADDRS = 'forre.st liteco.in 78.158.149.247'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: None if 100000 <= v else 'Bitcoin version too old. Upgrade to 0.11.2 or newer!' # not a bug. BIP65 support is ensured by SOFTFORKS_REQUIRED
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set()
MINIMUM_PROTOCOL_VERSION = 3301
BLOCK_MAX_SIZE = 32000000
BLOCK_MAX_WEIGHT = 128000000
