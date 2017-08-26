from p2pool.bitcoin import networks

PARENT = networks.nets['bitcoin_testnet']
SHARE_PERIOD = 30 # seconds
CHAIN_LENGTH = 60*60//10 # shares
REAL_CHAIN_LENGTH = 60*60//10 # shares
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 3 # blocks
IDENTIFIER = '5fc2be2d4f0d6bfb'.decode('hex')
PREFIX = '3f6057a15036f441'.decode('hex')
P2P_PORT = 19333
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 19332
BOOTSTRAP_ADDRS = 'forre.st vps.forre.st liteco.in 78.158.149.247'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: None if 100000 <= v else 'Bitcoin version too old. Upgrade to 0.11.2 or newer!' # not a bug. BIP65 support is ensured by SOFTFORKS_REQUIRED
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit'])
MINIMUM_PROTOCOL_VERSION = 1600
NEW_MINIMUM_PROTOCOL_VERSION = 1700
SEGWIT_ACTIVATION_VERSION = 15
