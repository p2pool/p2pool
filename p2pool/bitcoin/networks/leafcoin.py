import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'aaaaaacc'.decode('hex') #pchmessagestart
P2P_PORT = 22813
ADDRESS_VERSION = 95 #pubkey_address
RPC_PORT = 22812
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'leafcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 100000*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # s
SYMBOL = 'LEAF'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'LeafCoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Leafcoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.leafcoin'), 'leafcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://explorer2.leafco.in/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://explorer2.leafco.in/address/'
TX_EXPLORER_URL_PREFIX = 'http://explorer2.leafco.in/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
