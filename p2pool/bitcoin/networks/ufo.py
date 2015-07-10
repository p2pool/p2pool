import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fcd9b7dd'.decode('hex') #pchmessagestart
P2P_PORT = 9887
ADDRESS_VERSION = 27 #pubkey_address
RPC_PORT = 9888
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'ufoaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 5000*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 90 # s
SYMBOL = 'UFO'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'ufo') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/ufo/') if platform.system() == 'Darwin' else os.path.expanduser('~/.ufo'), 'ufo.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://ufo.cryptocoinexplorer.com/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://ufo.cryptocoinexplorer.com/address/'
TX_EXPLORER_URL_PREFIX = 'http://ufo.cryptocoinexplorer.com/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
