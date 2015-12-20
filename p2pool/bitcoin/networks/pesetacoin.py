import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'c0c0c0c0'.decode('hex')
P2P_PORT = 16639
ADDRESS_VERSION = 47
RPC_PORT = 26640
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'pesetacoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 166386*100000 >> (height + 1)//840000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # s
SYMBOL = 'PTC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Pesetacoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Pesetacoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.pesetacoin'), 'pesetacoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://pesetacoin.info/block/' #dummy
ADDRESS_EXPLORER_URL_PREFIX = 'http://pesetacoin.info/address/'
TX_EXPLORER_URL_PREFIX = 'http://pesetacoin.info/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
