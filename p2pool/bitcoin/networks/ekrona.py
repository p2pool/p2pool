import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'dcc1c104'.decode('hex') #pchmessagestart
P2P_PORT = 9445
ADDRESS_VERSION = 45 #pubkey_address
RPC_PORT = 9444
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'ekronaaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 40*100000000 >> (height + 1)//500000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 200 #seconds
SYMBOL = 'KRN'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Ekrona') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/ekrona/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.ekrona'), 'ekrona.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://altexplorer.net/block/' #dummy
ADDRESS_EXPLORER_URL_PREFIX = 'http://altexplorer.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://altexplorer.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8
