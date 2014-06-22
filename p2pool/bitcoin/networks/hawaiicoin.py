import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = '7c1f9184'.decode('hex')
P2P_PORT = 9335
ADDRESS_VERSION = 0
RPC_PORT = 9334
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'hawaiicoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 500*100000000 >> (height + 1)//500000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 50 # s
SYMBOL = 'HIC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Hawaiicoin') if platform.system() == 'Windows' 
				else os.path.expanduser('~/Library/Application Support/Hawaiicoin/') if platform.system() == 'Darwin' 
				else os.path.expanduser('~/.hawaiicoin'), 'hawaiicoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://pool.privanon.com:8080/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://pool.privanon.com:8080/address/'
TX_EXPLORER_URL_PREFIX = 'http://pool.privanon.com:8080/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
