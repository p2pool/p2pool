import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'cee2caff'.decode('hex')
P2P_PORT = 19999
ADDRESS_VERSION = 140
SCRIPT_ADDRESS_VERSION = 19
RPC_PORT = 19998
RPC_CHECK = defer.inlineCallbacks(lambda dashd: defer.returnValue(
            (yield helper.check_block_header(dashd, '00000bafbc94add76cb75e2ec92894837288a481e5c005f6563d91623bf8bc2c')) and
            (yield dashd.rpc_getblockchaininfo())['chain'] != 'main'
        ))
BLOCKHASH_FUNC = lambda data: pack.IntType(256).unpack(__import__('dash_hash').getPoWHash(data))
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('dash_hash').getPoWHash(data))
BLOCK_PERIOD = 150 # s
SYMBOL = 'tDASH'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'DashCore') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/DashCore/') if platform.system() == 'Darwin' else os.path.expanduser('~/.dashcore'), 'dash.conf')
BLOCK_EXPLORER_URL_PREFIX = 'https://blockexplorer.one/dash/testnet/blockHash/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://blockexplorer.one/dash/testnet/address/'
TX_EXPLORER_URL_PREFIX = 'https://blockexplorer.one/dash/testnet/tx/'
SANE_TARGET_RANGE = (2**256//2**32//1000000 - 1, 2**256//2**20 - 1)
DUST_THRESHOLD = 0.001e8
