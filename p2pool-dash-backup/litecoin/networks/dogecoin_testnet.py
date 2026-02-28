import os
import platform

from twisted.internet import defer

from .. import data
from p2pool.util import pack


P2P_PREFIX = 'fcc1b7dc'.decode('hex')  # Dogecoin testnet magic
P2P_PORT = 44556  # Dogecoin testnet P2P port
ADDRESS_VERSION = 113  # Dogecoin testnet address version
ADDRESS_P2SH_VERSION = 196  # Dogecoin testnet P2SH version
SCRIPT_ADDRESS_VERSION = 196  # Dogecoin testnet script address
RPC_PORT = 44555  # Dogecoin testnet RPC port
RPC_CHECK = defer.inlineCallbacks(lambda dogecoind: defer.returnValue(
            (yield dogecoind.rpc_getblockchaininfo())['chain'] == 'test'
        ))
SUBSIDY_FUNC = lambda height: 10000*100000000  # Dogecoin has fixed reward
BLOCKHASH_FUNC = lambda block_data: data.scrypt_hash(block_data)
POW_FUNC = lambda block_data: data.scrypt_hash(block_data)
BLOCK_PERIOD = 60  # 1 minute
SYMBOL = 'tDOGE'
CONF_FILE_FUNC = lambda: os.path.join(
    os.path.join(os.environ['APPDATA'], 'Dogecoin') if platform.system() == 'Windows' 
    else os.path.expanduser('~/Library/Application Support/Dogecoin/') if platform.system() == 'Darwin' 
    else os.path.expanduser('~/.dogecoin'), 
    'dogecoin.conf'
)
BLOCK_EXPLORER_URL_PREFIX = 'https://sochain.com/block/DOGETEST/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://sochain.com/address/DOGETEST/'
TX_EXPLORER_URL_PREFIX = 'https://sochain.com/tx/DOGETEST/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)  # Dogecoin has lower difficulty
DUMB_SCRYPT_DIFF = 2**16  # Scrypt difficulty multiplier (from jtoomim/p2pool)
DUST_THRESHOLD = 1e8

# Dogecoin-specific: Chain ID for merged mining
CHAIN_ID = 98  # Dogecoin's chain ID for auxpow
