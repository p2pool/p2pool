import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


#P2P_PREFIX = '0b110907'.decode('hex') # disk magic and old netmagic
P2P_PREFIX = 'f4e5f3f4'.decode('hex') # new net magic
P2P_PORT = 18333
ADDRESS_VERSION = 111
ADDRESS_P2SH_VERSION = 196
HUMAN_READABLE_PART = 'bchtest'
RPC_PORT = 18332
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'getreceivedbyaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//210000
POW_FUNC = data.hash256
BLOCK_PERIOD = 600 # s
SYMBOL = 'tBSV'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Bitcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Bitcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.bitcoin'), 'bitcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'https://test.whatsonchain.com/block-height/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://test.whatsonchain.com/tx/'
TX_EXPLORER_URL_PREFIX = 'https://test.whatsonchain.com/address/'
SANE_TARGET_RANGE = (2**256//2**32//100000000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 1e8
