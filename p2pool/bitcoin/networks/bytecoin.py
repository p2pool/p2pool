import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'f9beef69'.decode('hex')
P2P_PORT = 6333
ADDRESS_VERSION = 18
RPC_PORT = 6332
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'bitcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//210000
POW_FUNC = data.hash256
BLOCK_PERIOD = 600 # s
SYMBOL = 'BTE'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'bytecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/bytecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.bytecoin'), 'bytecoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://blockexplorer.bytecoin.in/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://blockexplorer.bytecoin.in/address/'
TX_EXPLORER_URL_PREFIX = 'http://blockexplorer.bytecoin.in/transaction/'
SANE_TARGET_RANGE = (2**256//2**32//1000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.001e8
