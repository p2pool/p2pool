from twisted.internet import defer

from . import data


class BitcoinMainnet(object):
    BITCOIN_P2P_PREFIX = 'f9beb4d9'.decode('hex')
    BITCOIN_P2P_PORT = 8333
    BITCOIN_ADDRESS_VERSION = 0
    BITCOIN_RPC_PORT = 8332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'name_firstupdate' not in (yield bitcoind.rpc_help()) and
        'ixcoinaddress' not in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//210000)
    BITCOIN_POW_FUNC = data.block_header_type.hash256
    BITCOIN_SYMBOL = 'BTC'

class BitcoinTestnet(object):
    BITCOIN_P2P_PREFIX = 'fabfb5da'.decode('hex')
    BITCOIN_P2P_PORT = 18333
    BITCOIN_ADDRESS_VERSION = 111
    BITCOIN_RPC_PORT = 8332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'name_firstupdate' not in (yield bitcoind.rpc_help()) and
        'ixcoinaddress' not in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//210000)
    BITCOIN_POW_FUNC = data.block_header_type.hash256
    BITCOIN_SYMBOL = 'tBTC'


class NamecoinMainnet(object):
    BITCOIN_P2P_PREFIX = 'f9beb4fe'.decode('hex')
    BITCOIN_P2P_PORT = 8334
    BITCOIN_ADDRESS_VERSION = 52
    BITCOIN_RPC_PORT = 8332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'name_firstupdate' in (yield bitcoind.rpc_help()) and
        'ixcoinaddress' not in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//210000)
    BITCOIN_POW_FUNC = data.block_header_type.hash256
    BITCOIN_SYMBOL = 'NMC'

class NamecoinTestnet(object):
    BITCOIN_P2P_PREFIX = 'fabfb5fe'.decode('hex')
    BITCOIN_P2P_PORT = 18334
    BITCOIN_ADDRESS_VERSION = 111
    BITCOIN_RPC_PORT = 8332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'name_firstupdate' in (yield bitcoind.rpc_help()) and
        'ixcoinaddress' not in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//210000)
    BITCOIN_POW_FUNC = data.block_header_type.hash256
    BITCOIN_SYMBOL = 'tNMC'


class LitecoinMainnet(object):
    BITCOIN_P2P_PREFIX = 'fbc0b6db'.decode('hex')
    BITCOIN_P2P_PORT = 9333
    BITCOIN_ADDRESS_VERSION = 48
    BITCOIN_RPC_PORT = 9332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'litecoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//840000)
    BITCOIN_POW_FUNC = data.block_header_type.scrypt
    BITCOIN_SYMBOL = 'LTC'

class LitecoinTestnet(object):
    BITCOIN_P2P_PREFIX = 'fcc1b7dc'.decode('hex')
    BITCOIN_P2P_PORT = 19333
    BITCOIN_ADDRESS_VERSION = 111
    BITCOIN_RPC_PORT = 19332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'litecoinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 50*100000000 >> (height + 1)//840000)
    BITCOIN_POW_FUNC = data.block_header_type.scrypt
    BITCOIN_SYMBOL = 'tLTC'
