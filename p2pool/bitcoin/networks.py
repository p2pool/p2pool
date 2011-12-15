from twisted.internet import defer

from . import data


class BitcoinMainnet(object):
    P2P_PREFIX = 'f9beb4d9'.decode('hex')
    P2P_PORT = 8333
    ADDRESS_VERSION = 0
    RPC_PORT = 8332
    RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'bitcoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//210000)
    POW_FUNC = data.block_header_type.hash256
    SYMBOL = 'BTC'

class BitcoinTestnet(object):
    P2P_PREFIX = 'fabfb5da'.decode('hex')
    P2P_PORT = 18333
    ADDRESS_VERSION = 111
    RPC_PORT = 8332
    RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'bitcoinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )))
    SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//210000)
    POW_FUNC = data.block_header_type.hash256
    SYMBOL = 'tBTC'


class NamecoinMainnet(object):
    P2P_PREFIX = 'f9beb4fe'.decode('hex')
    P2P_PORT = 8334
    ADDRESS_VERSION = 52
    RPC_PORT = 8332
    RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'namecoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//210000)
    POW_FUNC = data.block_header_type.hash256
    SYMBOL = 'NMC'

class NamecoinTestnet(object):
    P2P_PREFIX = 'fabfb5fe'.decode('hex')
    P2P_PORT = 18334
    ADDRESS_VERSION = 111
    RPC_PORT = 8332
    RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'namecoinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )))
    SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//210000)
    POW_FUNC = data.block_header_type.hash256
    SYMBOL = 'tNMC'


class LitecoinMainnet(object):
    P2P_PREFIX = 'fbc0b6db'.decode('hex')
    P2P_PORT = 9333
    ADDRESS_VERSION = 48
    RPC_PORT = 9332
    RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'litecoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//840000)
    POW_FUNC = data.block_header_type.scrypt
    SYMBOL = 'LTC'

class LitecoinTestnet(object):
    P2P_PREFIX = 'fcc1b7dc'.decode('hex')
    P2P_PORT = 19333
    ADDRESS_VERSION = 111
    RPC_PORT = 19332
    RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'litecoinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )))
    SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//840000)
    POW_FUNC = data.block_header_type.scrypt
    SYMBOL = 'tLTC'
