from twisted.internet import defer

from . import data
from p2pool.util import math

BitcoinMainnet = math.Object(
    P2P_PREFIX='f9beb4d9'.decode('hex'),
    P2P_PORT=8333,
    ADDRESS_VERSION=0,
    RPC_PORT=8332,
    RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'bitcoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )),
    POW_FUNC=data.block_header_type.hash256,
    SYMBOL='BTC',
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
    POW_FUNC=data.block_header_type.hash256,
    SYMBOL='tBTC',
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
    POW_FUNC=data.block_header_type.hash256,
    SYMBOL='NMC',
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
    POW_FUNC=data.block_header_type.hash256,
    SYMBOL='tNMC',
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
    POW_FUNC=data.block_header_type.scrypt,
    SYMBOL='LTC',
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
    POW_FUNC=data.block_header_type.scrypt,
    SYMBOL='tLTC',
)
