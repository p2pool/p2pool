import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


# Dogecoin mainnet network parameters
# Reference: https://github.com/dogecoin/dogecoin/blob/master/src/chainparams.cpp

P2P_PREFIX = 'c0c0c0c0'.decode('hex')  # Dogecoin mainnet magic bytes
P2P_PORT = 22556
P2P_VERSION = 70015  # Dogecoin requires 70003+, use 70015 for best compatibility
ADDRESS_VERSION = 30  # 0x1e - mainnet addresses start with 'D'
ADDRESS_P2SH_VERSION = 22  # 0x16 - mainnet P2SH addresses start with '9' or 'A'
HUMAN_READABLE_PART = 'doge'  # For potential future bech32 support
RPC_PORT = 22555
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'getreceivedbyaddress' in (yield bitcoind.rpc_help()) and
            (yield helper.check_block_header(bitcoind, '1a91e3dace36e2be3bf030a65679fe821aa1d6ef92e7c9902eb318182c355691')) and
            (yield bitcoind.rpc_getblockchaininfo())['chain'] == 'main'
        ))

# Dogecoin subsidy schedule
# Block 600000+: 10,000 DOGE (fixed forever)
def _subsidy_func(height):
    if height >= 600000:
        return 10000 * 100000000  # 10,000 DOGE forever
    elif height >= 500000:
        return 15625 * 100000000
    elif height >= 400000:
        return 31250 * 100000000
    elif height >= 300000:
        return 62500 * 100000000
    elif height >= 200000:
        return 125000 * 100000000
    elif height >= 145000:
        return 250000 * 100000000
    else:
        # Random rewards for early blocks (use max for estimation)
        return 500000 * 100000000

SUBSIDY_FUNC = _subsidy_func

# Dogecoin uses Scrypt PoW (same as Litecoin)
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCKHASH_FUNC = POW_FUNC  # For scrypt coins, block hash and PoW hash are the same

BLOCK_PERIOD = 60  # 1 minute blocks
SYMBOL = 'DOGE'
CONF_FILE_FUNC = lambda: os.path.join(
    os.path.join(os.environ['APPDATA'], 'Dogecoin') if platform.system() == 'Windows' 
    else os.path.expanduser('~/Library/Application Support/Dogecoin/') if platform.system() == 'Darwin' 
    else os.path.expanduser('~/.dogecoin'), 
    'dogecoin.conf'
)
BLOCK_EXPLORER_URL_PREFIX = 'https://dogechain.info/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://dogechain.info/address/'
TX_EXPLORER_URL_PREFIX = 'https://dogechain.info/tx/'

# Dogecoin mainnet target range for stratum vardiff
# Floor (hardest): diff ~15B for large ASIC farms, Ceiling (easiest): diff ~61 for small miners
# These bounds apply if running standalone Dogecoin P2Pool (rare - most use merged mining via Litecoin)
SANE_TARGET_RANGE = (2**256 // 10**15 - 1, 2**256 // 4000000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 1 * 100000000  # 1 DOGE dust threshold

# No segwit on Dogecoin
SOFTFORKS_REQUIRED = set()
