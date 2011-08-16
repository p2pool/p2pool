from twisted.internet import defer

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
