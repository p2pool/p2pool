import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fabfb5fe'.decode('hex')
P2P_PORT = 18334
ADDRESS_VERSION = 111
RPC_PORT = 18336
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'namecoinaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getblockchaininfo())['chain'] == 'test'
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//210000
POW_FUNC = data.hash256
BLOCK_PERIOD = 600 # s
SYMBOL = 'tNMC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Namecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Namecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.namecoin'), 'namecoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://testnet.explorer.dot-bit.org/b/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://testnet.explorer.dot-bit.org/a/'
TX_EXPLORER_URL_PREFIX = 'http://testnet.explorer.dot-bit.org/tx/'
SANE_TARGET_RANGE = (2**256//2**32 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 1e8
