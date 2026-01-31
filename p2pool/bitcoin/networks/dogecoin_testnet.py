import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


# Dogecoin testnet network parameters
# Reference: https://github.com/dogecoin/dogecoin/blob/master/src/chainparams.cpp

P2P_PREFIX = 'fcc1b7dc'.decode('hex')  # Dogecoin testnet magic bytes
P2P_PORT = 44556
P2P_VERSION = 70015  # Dogecoin requires 70003+, use 70015 for best compatibility
ADDRESS_VERSION = 113  # 0x71 - testnet addresses start with 'n'
ADDRESS_P2SH_VERSION = 196  # 0xc4 - testnet P2SH addresses start with '2'
HUMAN_READABLE_PART = 'tdge'  # For potential future bech32 support
RPC_PORT = 44555
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'getreceivedbyaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getblockchaininfo())['chain'] == 'test'
        ))

# Dogecoin subsidy schedule (different from Litecoin!)
# Block 0-99999: random 0-1,000,000 DOGE
# Block 100000-144999: random 0-500,000 DOGE  
# Block 145000-199999: 250,000 DOGE
# Block 200000-299999: 125,000 DOGE
# Block 300000-399999: 62,500 DOGE
# Block 400000-499999: 31,250 DOGE
# Block 500000-599999: 15,625 DOGE
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

BLOCK_PERIOD = 60  # 1 minute blocks (faster than Litecoin's 2.5 min)
SYMBOL = 'tDOGE'
CONF_FILE_FUNC = lambda: os.path.join(
    os.path.join(os.environ['APPDATA'], 'Dogecoin') if platform.system() == 'Windows' 
    else os.path.expanduser('~/Library/Application Support/Dogecoin/') if platform.system() == 'Darwin' 
    else os.path.expanduser('~/.dogecoin'), 
    'dogecoin.conf'
)
BLOCK_EXPLORER_URL_PREFIX = 'https://blockexplorer.one/dogecoin/testnet/blockHash/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://blockexplorer.one/dogecoin/testnet/address/'
TX_EXPLORER_URL_PREFIX = 'https://blockexplorer.one/dogecoin/testnet/tx/'

# Dogecoin has very easy difficulty on testnet
SANE_TARGET_RANGE = ((1 << 200) - 1, (1 << 256) - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 1 * 100000000  # 1 DOGE dust threshold

# No segwit on Dogecoin
SOFTFORKS_REQUIRED = set()
