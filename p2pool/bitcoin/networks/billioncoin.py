import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'c0c0c0c0'.decode('hex')
P2P_PORT = 22576
ADDRESS_VERSION = 26
RPC_PORT = 22565
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'billioncoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 1000*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # s
SYMBOL = 'BIL'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'BillionCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Billioncoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.billioncoin'), 'billioncoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://115.28.52.63/bil/block/index.php?block_hash='
ADDRESS_EXPLORER_URL_PREFIX = 'http://115.28.52.63/bil/block/index.php?address=' #dummy - not supported by crawler
TX_EXPLORER_URL_PREFIX = 'http://115.28.52.63/bil/block/index.php?transaction='
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
