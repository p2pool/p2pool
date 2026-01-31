import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'f9beb4d9'.decode('hex')
P2P_PORT = 8333
ADDRESS_VERSION = 0
ADDRESS_P2SH_VERSION = 5
HUMAN_READABLE_PART = 'bc'
RPC_PORT = 8332
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            (yield helper.check_block_header(bitcoind, '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f')) and # genesis block
            (yield helper.check_block_header(bitcoind, '00000000000000000019f112ec0a9982926f1258cdcc558dd7c3b7e5dc7fa148')) and # 478559 -- Bitcoin Cash fork
            (yield helper.check_block_header(bitcoind, '0000000000000000002ac644c9ba8ac3be966276fb7fc8f3baa1a3b9bdc615f1')) and # 491408 -- Bitcoin Gold fork
            (yield bitcoind.rpc_getblockchaininfo())['chain'] == 'main'
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//210000
POW_FUNC = data.hash256
BLOCK_PERIOD = 600 # s
SYMBOL = 'BTC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Bitcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Bitcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.bitcoin'), 'bitcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'https://blockchain.info/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'https://blockchain.info/address/'
TX_EXPLORER_URL_PREFIX = 'https://blockchain.info/tx/'
SANE_TARGET_RANGE = (2**256//2**32//1000000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.001e8
