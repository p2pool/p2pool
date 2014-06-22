import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fcd9b7dd'.decode('hex') #pchmessagestart
P2P_PORT = 4824
ADDRESS_VERSION = 22 #pubkey_address
RPC_PORT = 4822
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'polishcoin' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 100*150000000 >> (height + 1)//750000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # seconds
SYMBOL = 'PCC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'PolishCoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/PolishCoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.polishcoin'), 'polishcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://altexplorer.net/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://altexplorer.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://altexplorer.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
