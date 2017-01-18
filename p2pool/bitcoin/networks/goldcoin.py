import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fdc2b4dd'.decode('hex')
P2P_PORT = 8121
ADDRESS_VERSION = 32
RPC_PORT = 8122
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'goldcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 45*100000000 >> (height + 1)//26325000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 120 # s
SYMBOL = 'GLD'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Goldcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Goldcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.goldcoin'), 'goldcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'https://chainz.cryptoid.info/gld/block.dws?'
ADDRESS_EXPLORER_URL_PREFIX = 'https://chainz.cryptoid.info/gld/address.dws?'
TX_EXPLORER_URL_PREFIX = 'https://chainz.cryptoid.info/gld/tx.dws?'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.0001e8