import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fec1badc'.decode('hex')
P2P_PORT = 24361
ADDRESS_VERSION = 18
RPC_PORT = 24360
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'solcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 1772*100000000 >> (height + 1)//131072
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 188 # s
SYMBOL = 'SOL'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Solcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Solcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.solcoin'), 'solcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://explorer.solcoin.net/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://explorer.solcoin.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://explorer.solcoin.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
