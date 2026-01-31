import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


#P2P_PREFIX = 'f9beb4d9'.decode('hex') # disk magic and old net magic
P2P_PREFIX = 'e3e1f3e8'.decode('hex') # new net magic
P2P_PORT = 8333
ADDRESS_VERSION = 0
ADDRESS_P2SH_VERSION = 5
HUMAN_READABLE_PART = 'bitcoincash'
RPC_PORT = 8332
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            (yield helper.check_block_header(bitcoind, '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f')) and # genesis block
            (yield helper.check_block_header(bitcoind, '000000000000000000651ef99cb9fcbe0dadde1d424bd9f15ff20136191a5eec')) and # 478559 -- Bitcoin Cash fork
            (yield bitcoind.rpc_getblockchaininfo())['chain'] == 'main'
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//210000
POW_FUNC = data.hash256
BLOCK_PERIOD = 600 # s
SYMBOL = 'BCH'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Bitcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Bitcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.bitcoin'), 'bitcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'https://explorer.bitcoin.com/bch/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://explorer.bitcoin.com/bch/address/'
TX_EXPLORER_URL_PREFIX = 'https://explorer.bitcoin.com/bch/tx/'
SANE_TARGET_RANGE = (2**256//2**32//100000000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.001e8
