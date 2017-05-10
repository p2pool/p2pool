from p2pool.bitcoin import networks

# CHAIN_LENGTH = number of shares back client keeps
# REAL_CHAIN_LENGTH = maximum number of shares back client uses to compute payout
# REAL_CHAIN_LENGTH must always be <= CHAIN_LENGTH
# REAL_CHAIN_LENGTH must be changed in sync with all other clients
# changes can be done by changing one, then the other

PARENT = networks.nets['bitcoin']
SHARE_PERIOD = 30 # seconds
CHAIN_LENGTH = 24*60*60//10 # shares
REAL_CHAIN_LENGTH = 24*60*60//10 # shares
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 3 # blocks
IDENTIFIER = 'fc70035c7a81bc6f'.decode('hex')
PREFIX = '2472ef181efcd37b'.decode('hex')
P2P_PORT = 9333
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = True
WORKER_PORT = 9332
BOOTSTRAP_ADDRS = 'ml.toom.im ml.toom.im:9336 ml.toom.im:9334 93.77.99.166 whortonda.noip.me:9333 btc-fork.coinpool.pw:9335 crypto.office-on-the.net:9335'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool'
VERSION_CHECK = lambda v: None if 100000 <= v else 'Bitcoin version too old. Upgrade to 0.11.2 or newer!' # not a bug. BIP65 support is ensured by SOFTFORKS_REQUIRED
VERSION_WARNING = lambda v: None
SOFTFORKS_REQUIRED = set(['bip65', 'csv'])
MINIMUM_PROTOCOL_VERSION = 3200 # 1700 is currently used by the segwit support PR; we need to refuse to connect to those
