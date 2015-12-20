import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'fcd9b7dd'.decode('hex') #stripped from fckbankscoind's main.cpp -> pchMessageStart[4] = { 0xfc, 0xd9, 0xb7, 0xdd };
P2P_PORT = 21779 #fckbankscoind 's p2p port
ADDRESS_VERSION = 36 #look again in the sourcecode in the file base58.h, and find the value of PUBKEY_ADDRESS.
RPC_PORT = 21778 #fckbankscoind 's rpc port
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'fckbankscoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        ))
SUBSIDY_FUNC = lambda height: 100000*100000000 >> (height + 1)//100000
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD = 60 # one block generation time
SYMBOL = 'FCK'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'fckbankscoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/fckbankscoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.fckbankscoin'), 'fckbankscoin.conf')
BLOCK_EXPLORER_URL_PREFIX = 'http://explorer.fckbanks.org/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://explorer.fckbanks.org/address/'
TX_EXPLORER_URL_PREFIX = 'http://explorer.fckbanks.org/tx/'
SANE_TARGET_RANGE = (2**256//1000000000 - 1, 2**256//1000 - 1) #??
DUMB_SCRYPT_DIFF = 2**16 #??
DUST_THRESHOLD = 0.03e8 #??
