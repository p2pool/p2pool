import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'b8ebb3df'.decode('hex')
P2P_PORT = 9340
ADDRESS_VERSION = 0
RPC_PORT = 9341
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            (yield helper.check_genesis_block(bitcoind, '0000000085370d5e122f64f4ab19c68614ff3df78c8d13cb814fd7e69a1dc6da')) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 10*100000000 >> (height + 1)//2100000
POW_FUNC = data.hash256
BLOCK_PERIOD = 60 # s
SYMBOL = 'CRW'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Crowncoin') if platform.system() == 'Windows' 
    else os.path.expanduser('~/Library/Application Support/Crowncoin/') if platform.system() == 'Darwin' 
    else os.path.expanduser('~/.crowncoin'), 'crowncoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'https://blockexperts.com/crw/hash/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://blockexperts.com/crw/address/'
TX_EXPLORER_URL_PREFIX = 'https://blockexperts.com/crw/tx/'
SANE_TARGET_RANGE = (2**256//2**32//1000000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.001e8
