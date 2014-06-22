import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = '336b59c1'.decode('hex')
P2P_PORT = 8080
ADDRESS_VERSION = 0
RPC_PORT = 8079
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue('ecurrencyaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 100*100000000 >> (height + 1)//450000
POW_FUNC = data.hash256
BLOCK_PERIOD = 30 # s
SYMBOL = 'ISO'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'ecurrency') if platform.system() == 'Windows' 
				else os.path.expanduser('~/Library/Application Support/ecurrency/') if platform.system() == 'Darwin' 
				else os.path.expanduser('~/.ecurrency'), 'ecurrency.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://ecurrency.net/block/' #dummy
ADDRESS_EXPLORER_URL_PREFIX = 'http://ecurrency.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://ecrurrency.net/tx/'
SANE_TARGET_RANGE = (2**256//2**32//1000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.001e8
