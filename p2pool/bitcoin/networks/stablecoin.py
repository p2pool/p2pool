import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fcc3b4da'.decode('hex')
P2P_PORT = 17500
ADDRESS_VERSION = 125
RPC_PORT = 17501
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'StableCoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 25*100000000 >> (height + 1)//3000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 45
SYMBOL = 'SBC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'StableCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/StableCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.StableCoin'), 'StableCoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://sbc.blockexplorer.io/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://sbc.blockexplorer.io/address/'
TX_EXPLORER_URL_PREFIX = 'http://sbc.blockexplorer.io/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8
