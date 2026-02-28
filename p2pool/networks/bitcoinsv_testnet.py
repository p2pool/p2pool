from p2pool.bitcoin import networks

PARENT = networks.nets['bitcoinsv_testnet']
SHARE_PERIOD = 30 # seconds
CHAIN_LENGTH = 24*60*60//30 # shares
REAL_CHAIN_LENGTH = 24*60*60//30 # shares
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 3 # blocks
IDENTIFIER = '1c051dee6ec8bb1e'.decode('hex')
PREFIX = '4B62545B1A631A5C'.decode('hex')
P2P_PORT = 16338
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 16339
BOOTSTRAP_ADDRS = ''.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: None if 100000 <= v else 'Bitcoin version too old. Upgrade to 0.11.2 or newer!' # not a bug. BIP65 support is ensured by SOFTFORKS_REQUIRED
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set(['bip65', 'csv'])
MINIMUM_PROTOCOL_VERSION = 3301
BLOCK_MAX_SIZE = 32000000
BLOCK_MAX_WEIGHT = 128000000
