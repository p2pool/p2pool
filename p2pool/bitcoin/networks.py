import os
import platform

from twisted.internet import defer

from . import data
from p2pool.util import math, pack

BitcoinMainnet = math.Object(
    P2P_PREFIX='f9beb4d9'.decode('hex'),
    P2P_PORT=8333,
    ADDRESS_VERSION=0,
    RPC_PORT=8332,
    RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'bitcoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )),
    POW_FUNC=data.hash256,
    SYMBOL='BTC',
    CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Bitcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Bitcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.bitcoin'), 'bitcoin.conf'),
)
BitcoinTestnet = math.Object(
    P2P_PREFIX='fabfb5da'.decode('hex'),
    P2P_PORT=18333,
    ADDRESS_VERSION=111,
    RPC_PORT=8332,
    RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'bitcoinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )),
    POW_FUNC=data.hash256,
    SYMBOL='tBTC',
    CONF_FILE_FUNC=BitcoinMainnet.CONF_FILE_FUNC,
)

NamecoinMainnet = math.Object(
    P2P_PREFIX='f9beb4fe'.decode('hex'),
    P2P_PORT=8334,
    ADDRESS_VERSION=52,
    RPC_PORT=8332,
    RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'namecoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )),
    POW_FUNC=data.hash256,
    SYMBOL='NMC',
    CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Namecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Namecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.namecoin'), 'bitcoin.conf'),
)
NamecoinTestnet = math.Object(
    P2P_PREFIX='fabfb5fe'.decode('hex'),
    P2P_PORT=18334,
    ADDRESS_VERSION=111,
    RPC_PORT=8332,
    RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'namecoinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )),
    POW_FUNC=data.hash256,
    SYMBOL='tNMC',
    CONF_FILE_FUNC=NamecoinMainnet.CONF_FILE_FUNC,
)

LitecoinMainnet = math.Object(
    P2P_PREFIX='fbc0b6db'.decode('hex'),
    P2P_PORT=9333,
    ADDRESS_VERSION=48,
    RPC_PORT=9332,
    RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'litecoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )),
    POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
    SYMBOL='LTC',
    CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Litecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Litecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.litecoin'), 'litecoin.conf'),
)
LitecoinTestnet = math.Object(
    P2P_PREFIX='fcc1b7dc'.decode('hex'),
    P2P_PORT=19333,
    ADDRESS_VERSION=111,
    RPC_PORT=19332,
    RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'litecoinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )),
    POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
    SYMBOL='tLTC',
    CONF_FILE_FUNC=LitecoinMainnet.CONF_FILE_FUNC,
)
