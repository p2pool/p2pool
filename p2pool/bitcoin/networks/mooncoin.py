import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'f9f7c0e8'.decode('hex')
P2P_PORT = 44664
ADDRESS_VERSION = 3
RPC_PORT = 44663
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'tomooncoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 2000000*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 90 # s
SYMBOL = 'MOON'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'MoonCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Mooncoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.mooncoin'), 'mooncoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://moonchain.net/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://moonchain.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://moonchain.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
