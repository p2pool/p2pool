import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'f9f7c0e8'.decode('hex')
P2P_PORT = 41338
ADDRESS_VERSION = 11
RPC_PORT = 41337
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'coinyecoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 666666*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 90 # s
SYMBOL = 'COYE'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'coinyecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/coinyecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.coinyecoin'), 'coinyecoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://coinyechain.info/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://coinyechain.info/address/'
TX_EXPLORER_URL_PREFIX = 'http://coinyechain.info/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
