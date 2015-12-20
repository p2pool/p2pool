import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'defaced0'.decode('hex') #pchmessagestart
P2P_PORT = 58585
ADDRESS_VERSION = 63 #pubkey_address
RPC_PORT = 58583
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'smartcoin' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 64*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 40 # s
SYMBOL = 'SMC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'smartcoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/smartcoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.smartcoin'), 'smartcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://altexplorer.net/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://altexplorer.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://altexplorer.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.0001e8
