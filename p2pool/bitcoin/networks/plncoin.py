import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc0b6db'.decode('hex') #pchmessagestart
P2P_PORT = 9334
ADDRESS_VERSION = 22 #pubkey_address
RPC_PORT = 9331
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'plncoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 44*100000000 >> (height + 1)//438000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # seconds
SYMBOL = 'PLNc'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'PlnCoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/PlnCoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.plncoin'), 'plncoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://explorer.zaplnc.pl/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://explorer.zaplnc.pl/address/'
TX_EXPLORER_URL_PREFIX = 'http://explorer.zaplnc.pl/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
