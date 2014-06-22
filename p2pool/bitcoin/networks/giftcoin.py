import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fbc0b6db'.decode('hex')
P2P_PORT = 8854
ADDRESS_VERSION = 39
RPC_PORT = 8855
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'giftcoinaddress' in (yield bitcoind.rpc_help()) and 
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 50*100000000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 300
SYMBOL = 'GFT'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Giftcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Giftcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.giftcoin'), 'giftcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://giftchain.info/block/' #dummy for now
ADDRESS_EXPLORER_URL_PREFIX = 'http://giftchain.info/address/'
TX_EXPLORER_URL_PREFIX = 'http://giftchain.info/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 0.03e8
