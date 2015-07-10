import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fac3b6da'.decode('hex')
P2P_PORT = 47950
ADDRESS_VERSION = 28
RPC_PORT = 47970
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'casinocoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//3153600
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 30 # s targetspacing
SYMBOL = 'CSC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'casinocoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/casinocoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.casinocoin'), 'casinocoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://casinocoin.mooo.com/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://casinocoin.mooo.com/address/'
TX_EXPLORER_URL_PREFIX = 'http://casinocoin.mooo.com/transaction/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8
