import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'd9d9f9bd'.decode('hex') #pchmessagestart
P2P_PORT = 54449
ADDRESS_VERSION = 38 #pubkey_address
RPC_PORT = 54448
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'usdeaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 1000*100000000 if height>1000 else 100*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # s
SYMBOL = 'USDe'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'usde') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/usde/') if platform.system() == 'Darwin' else os.path.expanduser('~/.usde'), 'usde.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://altexplorer.net/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://altexplorer.net/address/'
TX_EXPLORER_URL_PREFIX = 'https://altexplorer.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
