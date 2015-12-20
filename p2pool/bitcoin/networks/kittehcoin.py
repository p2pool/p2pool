import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'c0c0c0c0'.decode('hex') #pchmessagestart
P2P_PORT = 22566
ADDRESS_VERSION = 45 #pubkey_address
RPC_PORT = 22565
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'kittehcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 1000*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # s
SYMBOL = 'MEOW'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'kittehcoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/kittehcoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.kittehcoin'), 'kittehcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://kitexplorer.tk/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://kitexplorer.tk/address/'
TX_EXPLORER_URL_PREFIX = 'http://kitexplorer.tk/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.00001e8
