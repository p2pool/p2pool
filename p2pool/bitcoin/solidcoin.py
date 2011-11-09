from twisted.internet import defer

class Mainnet(object):
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
