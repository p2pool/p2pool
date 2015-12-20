import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fcd9b7dd'.decode('hex') #pchmessagestart
P2P_PORT = 9929
ADDRESS_VERSION = 136 #pubkey_address
RPC_PORT = 9919
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'FoxCoin' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 250*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # s
SYMBOL = 'FOX'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'FoxCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/FoxCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.FoxCoin'), 'FoxCoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://altexplorer.net/block/' #dummy
ADDRESS_EXPLORER_URL_PREFIX = 'http://altexplorer.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://altexplorer.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8
