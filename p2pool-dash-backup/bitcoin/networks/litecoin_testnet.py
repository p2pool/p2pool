import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fdd2c8f1'.decode('hex')
P2P_PORT = 19335
ADDRESS_VERSION = 111
ADDRESS_P2SH_VERSION = 58
HUMAN_READABLE_PART = 'tltc'
RPC_PORT = 19332
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'getreceivedbyaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getblockchaininfo())['chain'] == 'test'
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//840000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 150 # s
SYMBOL = 'tLTC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Litecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Litecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.litecoin'), 'litecoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'https://chain.so/block/LTCTEST/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://chain.so/address/LTCTEST/'
TX_EXPLORER_URL_PREFIX = 'https://chain.so/tx/LTCTEST/'
SANE_TARGET_RANGE = (1<<128-1, 1<<240-1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 1e8
SOFTFORKS_REQUIRED = set(['bip65', 'csv', 'segwit', 'mweb'])
