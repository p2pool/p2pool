import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc0b6db'.decode('hex')
P2P_PORT = 9333
ADDRESS_VERSION = 50
RPC_PORT = 8338
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'marscoin' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//395699
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 123 # s
SYMBOL = 'MRS'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Marscoin') if platform.system() == 'Windows' 
		    else os.path.expanduser('~/Library/Application Support/Marscoin/') if platform.system() == 'Darwin' 
		    else os.path.expanduser('~/.marscoin'), 'marscoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://explore.marscoin.org/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://explore.marscoin.org/address/'
TX_EXPLORER_URL_PREFIX = 'http://explore.marscoin.org/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
