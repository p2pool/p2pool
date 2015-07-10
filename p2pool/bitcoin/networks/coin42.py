import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc0b6db'.decode('hex') #pchmessagestart
P2P_PORT = 24242
ADDRESS_VERSION = 8 #pubkey_address
RPC_PORT = 4242
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            '42address' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 0.00004200*100000000 if height>420 else 0.00000010*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 42 # s
SYMBOL = '42c'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], '42') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/42/') if platform.system() == 'Darwin' else os.path.expanduser('~/.42'), '42.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://altexplorer.net/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://altexplorer.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://altexplorer.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0
