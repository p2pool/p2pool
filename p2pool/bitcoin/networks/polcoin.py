import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'a6736083'.decode('hex') #pchmessagestart
P2P_PORT = 9338
ADDRESS_VERSION = 0 #pubkey_address
RPC_PORT = 9337
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'polcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 50*100000000 >> (height + 1)//2100000
POW_FUNC = data.hash256
BLOCK_PERIOD = 60 # s
SYMBOL = 'PLC'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'polcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/polcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.polcoin'), 'polcoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://explorer.e-waluty.net.pl/PLC/block_hash/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://explorer.e-waluty.net.pl/PLC/address/'
TX_EXPLORER_URL_PREFIX = 'http://explorer.e-waluty.net.pl/PLC/transaction/'
SANE_TARGET_RANGE = (2**256//2**32//1000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.001e8
