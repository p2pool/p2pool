import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fab5e8db'.decode('hex')
P2P_PORT = 13434
ADDRESS_VERSION = 22
RPC_PORT = 13435
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'asiccoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height * 1)//210000
POW_FUNC = data.hash256
BLOCK_PERIOD = 45 # s
SYMBOL = 'ASC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'asiccoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/asiccoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.asiccoin'), 'asiccoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/address/'
TX_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/tx/'
SANE_TARGET_RANGE = (2**256//2**32//1000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.001e8
