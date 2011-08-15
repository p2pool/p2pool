from twisted.internet import defer

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
