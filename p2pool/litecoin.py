from twisted.internet import defer

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
