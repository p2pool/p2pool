from p2pool.bitcoin import networks

PARENT = networks.nets['litecoin_testnet']
SHARE_PERIOD = 4 # seconds - target time between shares
CHAIN_LENGTH = 20*60//3 # shares - length of the share chain to track (~400 shares)
REAL_CHAIN_LENGTH = 20*60//3 # shares - actual chain length for weight calculations
TARGET_LOOKBEHIND = 200 # shares - how many shares to look back for difficulty adjustment
SPREAD = 3 # blocks - number of blocks to spread share submissions over
IDENTIFIER = 'cca5e24ec6408b1e'.decode('hex')  # Unique network identifier for P2Pool protocol
PREFIX = 'ad9614f6466a39cf'.decode('hex')      # Message prefix for P2Pool protocol

P2P_PORT = 19338  # Port for P2Pool peer-to-peer communication (share propagation)
MIN_TARGET = 0    # Minimum share target (hardest difficulty allowed)
MAX_TARGET = 2**256//20 - 1  # Match jtoomim canonical (2**256//20) for cross-version interop

# PERSIST = False means this node can start its own new sharechain if no peers available.
# When PERSIST=False:
#   - Node creates a "genesis share" with previous_share_hash=None
#   - Genesis share uses MAX_TARGET (easiest difficulty) since there's no history for difficulty calculation
#   - Arbitrary data: nonce=random, timestamp=current_time, coinbase=block_height+mm_data
#   - No need to sync with existing P2Pool network before mining
# When PERSIST=True:
#   - Node must connect to peers and sync existing sharechain before mining
#   - Prevents accidental network splits in production
# Set to False for: testnet, regtest, solo mining, or starting a new isolated pool
PERSIST = False

WORKER_PORT = 19327  # Stratum port for miners to connect (stratum+tcp://IP:19327)
BOOTSTRAP_ADDRS = [
    'NODE_C_IP',  # nodeC - canonical v35 test node
    'PEER_IP',  # node33 - canonical v35 test node
    'NODE_A_IP',  # nodeA - v36 experimental node
]
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True  # Accept any version (testnet is permissive)
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit', 'taproot', 'mweb'])
MINIMUM_PROTOCOL_VERSION = 3301  # Runtime ratchet in data.py raises this when share versions reach 95%
SEGWIT_ACTIVATION_VERSION = 17
BLOCK_MAX_SIZE = 1000000
BLOCK_MAX_WEIGHT = 4000000
IMMUTABLE_BLOCKS = True
