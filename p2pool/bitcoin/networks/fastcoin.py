import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc0b6db'.decode('hex')
P2P_PORT = 9526
ADDRESS_VERSION = 96
RPC_PORT = 9527
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'fastcoinaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getblockchaininfo())['chain'] != 'test'
        ))
SUBSIDY_FUNC = lambda height: 32*100000000 >> (height + 1)//2592000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 12 # s
SYMBOL = 'FST'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Fastcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Fastcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.fastcoin'), 'fastcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://fst.blockexp.info/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://fst.blockexp.info/address/'
TX_EXPLORER_URL_PREFIX = 'http://fst.blockexp.info/tx/'
SANE_TARGET_RANGE = (2**256//100000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
