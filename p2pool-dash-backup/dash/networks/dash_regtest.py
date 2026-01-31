import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fcc1b7dc'.decode('hex')  # Regtest P2P magic (from chainparams.cpp)
P2P_PORT = 19899  # Regtest P2P port (from chainparams.cpp)
ADDRESS_VERSION = 140  # Same as testnet (y prefix)
SCRIPT_ADDRESS_VERSION = 19
RPC_PORT = 19998  # Same as our config
RPC_CHECK = defer.inlineCallbacks(lambda dashd: defer.returnValue(
            (yield dashd.rpc_getblockchaininfo())['chain'] == 'regtest'
        ))
BLOCKHASH_FUNC = lambda data: pack.IntType(256).unpack(__import__('dash_hash').getPoWHash(data))
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('dash_hash').getPoWHash(data))
BLOCK_PERIOD = 150 # s (can be instant in regtest with generate)
SYMBOL = 'rDASH'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'DashCore') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/DashCore/') if platform.system() == 'Darwin' else os.path.expanduser('~/.dashcore'), 'dash.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://localhost/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://localhost/'
TX_EXPLORER_URL_PREFIX = 'http://localhost/'
# Regtest has very low difficulty - allow extremely easy targets
SANE_TARGET_RANGE = (1, 2**256 - 1)  # Allow any target in regtest
DUST_THRESHOLD = 0.001e8
