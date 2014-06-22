import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'a9c5bdd1'.decode('hex') #pchmessagestart
P2P_PORT = 24057
ADDRESS_VERSION = 28 #pubkey_address
RPC_PORT = 24055
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'Coinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 0*1200000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # seconds
SYMBOL = 'COIN'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Coin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Coin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.Coin'), 'Coin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://explorer.coin-project.org/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://explorer.coin-project.org/address/'
TX_EXPLORER_URL_PREFIX = 'http://explorer.coin-project.org/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
