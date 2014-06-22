import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc1b8dc'.decode('hex') #pchmessagestart
P2P_PORT = 13580
ADDRESS_VERSION = 23 #pubkey_address
RPC_PORT = 13581
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'Argentumaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 1*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 120 # s
SYMBOL = 'ARG'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'argentum') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Argentum/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.Argentum'), 'Argentum.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://arg.webboise.com/chain/Argentum/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://arg.webboise.com/chain/Argentum/address/'
TX_EXPLORER_URL_PREFIX = 'http://arg.webboise.com/chain/Argentum/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.0001e8
