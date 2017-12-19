import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fcc1b7dc'.decode('hex')
P2P_PORT = 19333
ADDRESS_VERSION = 111
RPC_PORT = 19332
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'litecoinaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getblockchaininfo())['chain'] == 'test'
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//840000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 150 # s
SYMBOL = 'tLTC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Litecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Litecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.litecoin'), 'litecoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://nonexistent-litecoin-testnet-explorer/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://chain.so/address/LTCTEST/'
TX_EXPLORER_URL_PREFIX = 'https://chain.so/tx/LTCTEST/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 1e8
