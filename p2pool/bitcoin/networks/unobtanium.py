import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = '03d5b503'.decode('hex') #messagestart
P2P_PORT = 65534
ADDRESS_VERSION = 130 #pubkey_address
RPC_PORT = 65535
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'unobtaniumaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 0.001*100000000 if height<2000  else 1*100000000 >> (height * 1)//120000
POW_FUNC = data.hash256
BLOCK_PERIOD = 180 # s
SYMBOL = 'Un'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'unobtanium') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/unobtanium/') if platform.system() == 'Darwin' else os.path.expanduser('~/.unobtanium'), 'unobtanium.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/address/'
TX_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/tx/'
SANE_TARGET_RANGE = (2**256//2**32//1000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.00001e8
