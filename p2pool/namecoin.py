from .bitcoin import p2p as bitcoin_p2p

class NamecoinMainnet(object):
    BITCOIN_P2P_PREFIX = 'f9beb4fe'.decode('hex')
    BITCOIN_P2P_PORT = 8334
    BITCOIN_ADDRESS_VERSION = 52

class NamecoinTestnet(object):
    BITCOIN_P2P_PREFIX = 'fabfb5fe'.decode('hex')
    BITCOIN_P2P_PORT = 18334
    BITCOIN_ADDRESS_VERSION = 111
