from twisted.internet import defer


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
    BITCOIN_SYMBOL = 'tNMC'


class IxcoinMainnet(object):
    BITCOIN_P2P_PREFIX = 'f9beb4d9'.decode('hex')
    BITCOIN_P2P_PORT = 8337
    BITCOIN_ADDRESS_VERSION = 138
    BITCOIN_RPC_PORT = 8338
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'name_firstupdate' not in (yield bitcoind.rpc_help()) and
        'ixcoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 96*100000000 >> (height + 1)//210000)
    BITCOIN_SYMBOL = 'IXC'

class IxcoinTestnet(object):
    BITCOIN_P2P_PREFIX = 'fabfb5da'.decode('hex')
    BITCOIN_P2P_PORT = 18337
    BITCOIN_ADDRESS_VERSION = 111
    BITCOIN_RPC_PORT = 8338
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'name_firstupdate' not in (yield bitcoind.rpc_help()) and
        'ixcoinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 96*100000000 >> (height + 1)//210000)
    BITCOIN_SYMBOL = 'tIXC'


class I0coinMainnet(object):
    BITCOIN_P2P_PREFIX = 'f1b2b3d4'.decode('hex')
    BITCOIN_P2P_PORT = 7333
    BITCOIN_ADDRESS_VERSION = 105
    BITCOIN_RPC_PORT = 7332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'name_firstupdate' not in (yield bitcoind.rpc_help()) and
        'ixcoinaddress' not in (yield bitcoind.rpc_help()) and
        'i0coinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 48*100000000 >> (height + 1)//218750)
    BITCOIN_SYMBOL = 'I0C'

class I0coinTestnet(object):
    BITCOIN_P2P_PREFIX = 'f5b6b7d8'.decode('hex')
    BITCOIN_P2P_PORT = 17333
    BITCOIN_ADDRESS_VERSION = 112
    BITCOIN_RPC_PORT = 7332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'name_firstupdate' not in (yield bitcoind.rpc_help()) and
        'ixcoinaddress' not in (yield bitcoind.rpc_help()) and
        'i0coinaddress' in (yield bitcoind.rpc_help()) and
        (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 48*100000000 >> (height + 1)//218750)
    BITCOIN_SYMBOL = 'tI0C'


class SolidcoinMainnet(object):
    BITCOIN_P2P_PREFIX = 'deadbabe'.decode('hex')
    BITCOIN_P2P_PORT = 7555
    BITCOIN_ADDRESS_VERSION = 125
    BITCOIN_RPC_PORT = 8332
    BITCOIN_RPC_CHECK = staticmethod(defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
        'solidcoinaddress' in (yield bitcoind.rpc_help()) and
        not (yield bitcoind.rpc_getinfo())['testnet']
    )))
    BITCOIN_SUBSIDY_FUNC = staticmethod(lambda height: 32*100000000 >> (height + 1)//300000)
    BITCOIN_SYMBOL = 'SC'


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
    BITCOIN_POW_SCRYPT = True;
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
    BITCOIN_POW_SCRYPT = True;
    BITCOIN_SYMBOL = 'tLTC'
