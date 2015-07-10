import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fcd9b7dd'.decode('hex')
P2P_PORT = 1336
ADDRESS_VERSION = 24
RPC_PORT = 1337
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'doubloons' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 1*100000000 >> (height + 1)//1080000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 30 # s targetspacing
SYMBOL = 'DBL'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'doubloons') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Doubloons/') if platform.system() == 'Darwin' else os.path.expanduser('~/.doubloons'), 'doubloons.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://explorer.doubloons.net/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://explorer.doubloons.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://explorer.doubloons.net/transaction/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8
