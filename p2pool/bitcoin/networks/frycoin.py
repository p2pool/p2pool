import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc0b6db'.decode('hex')
P2P_PORT = 55901
ADDRESS_VERSION = 35
RPC_PORT = 55900
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'Frycoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 300*100000000 >> (height + 1)//16666
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 120 # s
SYMBOL = 'FRY'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Frycoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Frycoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.Frycoin'), 'Frycoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://altexplorer.net/block/' #dummy
ADDRESS_EXPLORER_URL_PREFIX = 'http://altexplorer.net/address/'
TX_EXPLORER_URL_PREFIX = 'http://altexplorer.net/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.0001e8
