from p2pool.bitcoin import networks

class BitcoinMainnet(networks.BitcoinMainnet):
    SHARE_PERIOD = 10 # seconds
    CHAIN_LENGTH = 24*60*60//10//2 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = 'fc70035c7a81bc6f'.decode('hex')
    PREFIX = '2472ef181efcd37b'.decode('hex')
    NAME = 'bitcoin'
    P2P_PORT = 9333
    MAX_TARGET = 2**256//2**32 - 1
    PERSIST = True
    WORKER_PORT = 9332

class BitcoinTestnet(networks.BitcoinTestnet):
    SHARE_PERIOD = 1 # seconds
    CHAIN_LENGTH = 24*60*60//10//2 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = '5fc2be2d4f0d6bfb'.decode('hex')
    PREFIX = '3f6057a15036f441'.decode('hex')
    NAME = 'bitcoin_testnet'
    P2P_PORT = 19333
    MAX_TARGET = 2**256//2**32 - 1
    PERSIST = False
    WORKER_PORT = 19332

class NamecoinMainnet(networks.NamecoinMainnet):
    SHARE_PERIOD = 10 # seconds
    CHAIN_LENGTH = 24*60*60//10 # shares
    TARGET_LOOKBEHIND = 3600//10 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = 'd5b1192062c4c454'.decode('hex')
    PREFIX = 'b56f3d0fb24fc982'.decode('hex')
    NAME = 'namecoin'
    P2P_PORT = 9334
    MAX_TARGET = 2**256//2**32 - 1
    PERSIST = True
    WORKER_PORT = 9331

class NamecoinTestnet(networks.NamecoinTestnet):
    SHARE_PERIOD = 1 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = '8dd303d014a01a60'.decode('hex')
    PREFIX = '4d6581d24f51acbf'.decode('hex')
    NAME = 'namecoin_testnet'
    P2P_PORT = 19334
    MAX_TARGET = 2**256//2**20 - 1
    PERSIST = False
    WORKER_PORT = 19331

class IxcoinMainnet(networks.IxcoinMainnet):
    SHARE_PERIOD = 10 # seconds
    CHAIN_LENGTH = 24*60*60//10 # shares
    TARGET_LOOKBEHIND = 3600//10 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = '27b564116e2a2666'.decode('hex')
    PREFIX = '9dd6c4a619401f2f'.decode('hex')
    NAME = 'ixcoin'
    P2P_PORT = 9335
    MAX_TARGET = 2**256//2**32 - 1
    PERSIST = True
    WORKER_PORT = 9330

class IxcoinTestnet(networks.IxcoinTestnet):
    SHARE_PERIOD = 1 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = '7430cbeb01249e44'.decode('hex')
    PREFIX = '7cfffda946709c1f'.decode('hex')
    NAME = 'ixcoin_testnet'
    P2P_PORT = 19335
    MAX_TARGET = 2**256//2**20 - 1
    PERSIST = False
    WORKER_PORT = 19330

class I0coinMainnet(networks.I0coinMainnet):
    SHARE_PERIOD = 10 # seconds
    CHAIN_LENGTH = 24*60*60//10 # shares
    TARGET_LOOKBEHIND = 3600//10 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = 'b32e3f10c2ff221b'.decode('hex')
    PREFIX = '6155537ed977a3b5'.decode('hex')
    NAME = 'i0coin'
    P2P_PORT = 9336
    MAX_TARGET = 2**256//2**32 - 1
    PERSIST = False
    WORKER_PORT = 9329

class I0coinTestnet(networks.I0coinTestnet):
    SHARE_PERIOD = 1 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = '7712c1a8181b5f2e'.decode('hex')
    PREFIX = '792d2e7d770fbe68'.decode('hex')
    NAME = 'i0coin_testnet'
    P2P_PORT = 19336
    MAX_TARGET = 2**256//2**20 - 1
    PERSIST = False
    WORKER_PORT = 19329

class SolidcoinMainnet(networks.SolidcoinMainnet):
    SHARE_PERIOD = 10
    CHAIN_LENGTH = 24*60*60//10 # shares
    TARGET_LOOKBEHIND = 3600//10 # shares
    SPREAD = 3 # blocks
    IDENTIFIER = '9cc9c421cca258cd'.decode('hex')
    PREFIX = 'c059125b8070f00a'.decode('hex')
    NAME = 'solidcoin'
    P2P_PORT = 9337
    MAX_TARGET = 2**256//2**32 - 1
    PERSIST = True
    WORKER_PORT = 9328

class LitecoinMainnet(networks.LitecoinMainnet):
    SHARE_PERIOD = 10 # seconds
    CHAIN_LENGTH = 24*60*60//10//2 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 12 # blocks
    IDENTIFIER = 'e037d5b8c6923410'.decode('hex')
    PREFIX = '7208c1a53ef629b0'.decode('hex')
    NAME = 'litecoin'
    P2P_PORT = 9338
    MAX_TARGET = 2**256//2**20 - 1
    PERSIST = True
    WORKER_PORT = 9327

class LitecoinTestnet(networks.LitecoinTestnet):
    SHARE_PERIOD = 1 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 12 # blocks
    IDENTIFIER = 'cca5e24ec6408b1e'.decode('hex')
    PREFIX = 'ad9614f6466a39cf'.decode('hex')
    NAME = 'litecoin_testnet'
    P2P_PORT = 19338
    MAX_TARGET = 2**256//2**17 - 1
    PERSIST = False
    WORKER_PORT = 19327

nets = dict((net.NAME, net) for net in set([BitcoinMainnet, BitcoinTestnet, NamecoinMainnet, NamecoinTestnet, IxcoinMainnet, IxcoinTestnet, I0coinMainnet, I0coinTestnet, SolidcoinMainnet, LitecoinMainnet, LitecoinTestnet]))
