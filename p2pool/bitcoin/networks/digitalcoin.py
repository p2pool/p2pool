import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc0b6db'.decode('hex')
P2P_PORT = 7999
ADDRESS_VERSION = 30
RPC_PORT = 7998
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'digitalcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 15*100000000 >> (height + 1)//4730400
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 40 # s targetspacing
SYMBOL = 'DGC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'digitalcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/digitalcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.digitalcoin'), 'digitalcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://dgc.cryptocoinexplorer.com/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://dgc.cryptocoinexplorer.com/address/'
TX_EXPLORER_URL_PREFIX = 'http://dgc.cryptocoinexplorer.com/transaction/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.001e8
