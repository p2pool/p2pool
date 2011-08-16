from twisted.internet import defer

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
