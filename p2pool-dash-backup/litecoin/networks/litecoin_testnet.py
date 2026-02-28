import os
import platform

from twisted.internet import defer

from .. import data
from p2pool.util import pack


P2P_PREFIX = 'fdd2c8f1'.decode('hex')  # Litecoin testnet magic
P2P_PORT = 19335  # Litecoin testnet P2P port
ADDRESS_VERSION = 111  # Testnet address version (same as Bitcoin testnet)
ADDRESS_P2SH_VERSION = 58  # Litecoin testnet P2SH version
HUMAN_READABLE_PART = 'tltc'  # for bech32 segwit addresses
SCRIPT_ADDRESS_VERSION = 196  # Testnet script address version
RPC_PORT = 19332  # Litecoin testnet RPC port
RPC_CHECK = defer.inlineCallbacks(lambda litecoind: defer.returnValue(
            (yield litecoind.rpc_getblockchaininfo())['chain'] == 'test'
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//840000  # Litecoin halving
BLOCKHASH_FUNC = lambda block_data: data.scrypt_hash(block_data)
POW_FUNC = lambda block_data: data.scrypt_hash(block_data)
BLOCK_PERIOD = 150  # 2.5 minutes
SYMBOL = 'tLTC'
CONF_FILE_FUNC = lambda: os.path.join(
    os.path.join(os.environ['APPDATA'], 'Litecoin') if platform.system() == 'Windows' 
    else os.path.expanduser('~/Library/Application Support/Litecoin/') if platform.system() == 'Darwin' 
    else os.path.expanduser('~/.litecoin'), 
    'litecoin.conf'
)
BLOCK_EXPLORER_URL_PREFIX = 'https://chain.so/block/LTCTEST/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://chain.so/address/LTCTEST/'
TX_EXPLORER_URL_PREFIX = 'https://chain.so/tx/LTCTEST/'
SANE_TARGET_RANGE = (2**256//2**32//1000 - 1, 2**256//2**20 - 1)
DUMB_SCRYPT_DIFF = 2**16  # Scrypt difficulty multiplier (from jtoomim/p2pool)
DUST_THRESHOLD = 1e8
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit', 'mweb'])  # MWEB = MimbleWimble Extension Blocks
