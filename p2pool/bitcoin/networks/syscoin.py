import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX='dcececdc'.decode('hex') 
P2P_PORT=8369
ADDRESS_VERSION=63
RPC_PORT=8368
RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue('syscoinaddress' in (yield bitcoind.rpc_help()) and not (yield bitcoind.rpc_getinfo())['testnet']))
SUBSIDY_FUNC=lambda height: 128*100000000 >> (height + 1)//840000
POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCK_PERIOD=60
SYMBOL='SYS'
CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'SysCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/SysCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.SysCoin'), 'SysCoin.conf')
BLOCK_EXPLORER_URL_PREFIX='http://sys.coinzone.info/chain/SysCoin/block/'
ADDRESS_EXPLORER_URL_PREFIX='http://sys.coinzone.info/chain/SysCoin/address/'
TX_EXPLORER_URL_PREFIX='http://sys.coinzone.info/chain/SysCoin/tx/'
SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1)
DUMB_SCRYPT_DIFF=2**16
DUST_THRESHOLD=0.03e8
