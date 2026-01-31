from p2pool.litecoin import networks

PARENT = networks.nets['litecoin_testnet']
SHARE_PERIOD = 15  # seconds (faster than Litecoin's 2.5 min blocks)
CHAIN_LENGTH = 24*60*60//15  # 24 hours worth of shares
REAL_CHAIN_LENGTH = 24*60*60//15
TARGET_LOOKBEHIND = 100  # shares
SPREAD = 10  # blocks
IDENTIFIER = 'cca5e24ec6408b1e'.decode('hex')  # From jtoomim/p2pool
PREFIX = 'ad9614f6466a39cf'.decode('hex')  # From jtoomim/p2pool
COINBASEEXT = '0D2F5032506F6F6C2D744C54432F'.decode('hex')  # "/P2Pool-tLTC/" in hex
P2P_PORT = 19338  # P2Pool share chain port (from jtoomim/p2pool)
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False  # Don't persist shares for testnet
WORKER_PORT = 19327  # Stratum port for miners (from jtoomim/p2pool)
BOOTSTRAP_ADDRS = 'forre.st'.split(' ')  # From jtoomim/p2pool
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True  # Accept all versions for testnet
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit', 'mweb'])  # Litecoin softforks
MINIMUM_PROTOCOL_VERSION = 3301  # From jtoomim/p2pool
SEGWIT_ACTIVATION_VERSION = 17  # From jtoomim/p2pool

# Stratum Vardiff Configuration
STRATUM_SHARE_RATE = 10  # Target 10 seconds per pseudoshare

# Vardiff settings
VARDIFF_SHARES_TRIGGER = 5
VARDIFF_TIMEOUT_MULT = 3
VARDIFF_QUICKUP_SHARES = 2
VARDIFF_QUICKUP_DIVISOR = 4
VARDIFF_MIN_ADJUST = 0.25
VARDIFF_MAX_ADJUST = 4.0

# Connection threat detection  
CONNECTION_WORKER_ELEVATED = 4.0
CONNECTION_WORKER_WARNING = 6.0
