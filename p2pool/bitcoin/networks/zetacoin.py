import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fab503df'.decode('hex') #chainparams.cpp pchMessageStart
P2P_PORT = 17333
ADDRESS_VERSION = 80 #PUBKEY_ADDRESS
RPC_PORT = 9332
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'zetacoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 1000*100000000 >> (height + 1)//80640
POW_FUNC = data.hash256
BLOCK_PERIOD = 30 # s
SYMBOL = 'ZET'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Zetacoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Zetacoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.zetacoin'), 'zetacoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/address/'
TX_EXPLORER_URL_PREFIX = 'http://bit.usr.sh:2750/tx/'
SANE_TARGET_RANGE = (2**256//2**32//1000 - 1, 2**256//2**32 - 1)
DUMB_SCRYPT_DIFF = 1
DUST_THRESHOLD = 0.001e8
