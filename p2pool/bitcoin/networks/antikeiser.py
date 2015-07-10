import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc0c0c0'.decode('hex') #pchmessagestart
P2P_PORT = 39919
ADDRESS_VERSION = 23 #pubkey_address
RPC_PORT = 39918
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'antikeiser' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 40000*100000000 >> (height + 1)//12000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 120 # seconds
SYMBOL = 'AKC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'AntiKeiserCoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/AntiKesierCoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.antikeisercoin'), 'antikeisercoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://altexplorer.net/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://altexplorer.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://altexplorer.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
