import os
import platform

from twisted.internet import defer

from . import data
from p2pool.util import math, pack, jsonrpc

@defer.inlineCallbacks
def check_genesis_block(bitcoind, genesis_block_hash):
    try:
        yield bitcoind.rpc_getblock(genesis_block_hash)
    except jsonrpc.Error_for_code(-5):
        defer.returnValue(False)
    else:
        defer.returnValue(True)

nets = dict(
    bitcoin=math.Object(
        P2P_PREFIX='f9beb4d9'.decode('hex'),
        P2P_PORT=8333,
        ADDRESS_VERSION=0,
        RPC_PORT=8332,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            (yield check_genesis_block(bitcoind, '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f')) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000 >> (height + 1)//210000,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=600, # s
        SYMBOL='BTC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Bitcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Bitcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.bitcoin'), 'bitcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='https://blockchain.info/block/',
        ADDRESS_EXPLORER_URL_PREFIX='https://blockchain.info/address/',
        TX_EXPLORER_URL_PREFIX='https://blockchain.info/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=0.001e8,
    ),
    bitcoin_testnet=math.Object(
        P2P_PREFIX='0b110907'.decode('hex'),
        P2P_PORT=18333,
        ADDRESS_VERSION=111,
        RPC_PORT=18332,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'bitcoinaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000 >> (height + 1)//210000,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=600, # s
        SYMBOL='tBTC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Bitcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Bitcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.bitcoin'), 'bitcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://blockexplorer.com/testnet/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://blockexplorer.com/testnet/address/',
        TX_EXPLORER_URL_PREFIX='http://blockexplorer.com/testnet/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=1e8,
    ),
    litecoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=9333,
        ADDRESS_VERSION=48,
        RPC_PORT=9332,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'litecoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000 >> (height + 1)//840000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=150, # s
        SYMBOL='LTC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Litecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Litecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.litecoin'), 'litecoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://explorer.litecoin.net/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://explorer.litecoin.net/address/',
        TX_EXPLORER_URL_PREFIX='http://explorer.litecoin.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    litecoin_testnet=math.Object(
        P2P_PREFIX='fcc1b7dc'.decode('hex'),
        P2P_PORT=19333,
        ADDRESS_VERSION=111,
        RPC_PORT=19332,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'litecoinaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000 >> (height + 1)//840000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=150, # s
        SYMBOL='tLTC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Litecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Litecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.litecoin'), 'litecoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://nonexistent-litecoin-testnet-explorer/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://nonexistent-litecoin-testnet-explorer/address/',
        TX_EXPLORER_URL_PREFIX='http://nonexistent-litecoin-testnet-explorer/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=1e8,
    ),
    terracoin=math.Object(
        P2P_PREFIX='42babe56'.decode('hex'),
        P2P_PORT=13333,
        ADDRESS_VERSION=0,
        RPC_PORT=13332,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'terracoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 20*100000000 >> (height + 1)//1050000,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=120, # s
        SYMBOL='TRC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Terracoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Terracoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.terracoin'), 'terracoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://trc.cryptocoinexplorer.com/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://trc.cryptocoinexplorer.com/address/',
        TX_EXPLORER_URL_PREFIX='http://trc.cryptocoinexplorer.com/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=1e8,
    ),  
    terracoin_testnet=math.Object(
        P2P_PREFIX='41babe56'.decode('hex'),
        P2P_PORT=23333,
        ADDRESS_VERSION=111,
        RPC_PORT=23332,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'terracoinaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 20*100000000 >> (height + 1)//1050000,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=120, # s
        SYMBOL='tTRC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Terracoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Terracoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.terracoin'), 'terracoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://trc.cryptocoinexplorer.com/testnet/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://trc.cryptocoinexplorer.com/testnet/address/',
        TX_EXPLORER_URL_PREFIX='http://trc.cryptocoinexplorer.com/testnet/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=1e8,
    ),
    stablecoin=math.Object(
        P2P_PREFIX='fcc3b4da'.decode('hex'),
        P2P_PORT=17500,
        ADDRESS_VERSION=125,
        RPC_PORT=17501,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'StableCoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 25*100000000 >> (height + 1)//3000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=45,
        SYMBOL='SBC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'StableCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/StableCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.StableCoin'), 'StableCoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://sbc.blockexplorer.io/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://sbc.blockexplorer.io/address/',
        TX_EXPLORER_URL_PREFIX='http://sbc.blockexplorer.io/tx/',
	SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.001e8,
    ),
    zetacoin=math.Object(
        P2P_PREFIX='fab503df'.decode('hex'), #chainparams.cpp pchMessageStart
        P2P_PORT=17333,
        ADDRESS_VERSION=80, #PUBKEY_ADDRESS
        RPC_PORT=9332,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'zetacoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 1000*100000000 >> (height + 1)//80640,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=30, # s
        SYMBOL='ZET',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Zetacoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Zetacoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.zetacoin'), 'zetacoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/address/',
	TX_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=0.001e8,
    ),
    feathercoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=9336,
        ADDRESS_VERSION=14,
        RPC_PORT=9337,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'feathercoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 200*100000000 >> (height + 1)//3360000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=150, # s
        SYMBOL='FTC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Feathercoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Feathercoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.feathercoin'), 'feathercoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://cryptocoinexplorer.com:5750/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://cryptocoinexplorer.com:5750/address/',
        TX_EXPLORER_URL_PREFIX='http://cryptocoinexplorer.com:5750/transaction/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.001e8,
    ),
    digitalcoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=7999,
        ADDRESS_VERSION=30,
        RPC_PORT=7998,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'digitalcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 15*100000000 >> (height + 1)//4730400,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=40, # s targetspacing
        SYMBOL='DGC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'digitalcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/digitalcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.digitalcoin'), 'digitalcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://dgc.cryptocoinexplorer.com/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://dgc.cryptocoinexplorer.com/address/',
        TX_EXPLORER_URL_PREFIX='http://dgc.cryptocoinexplorer.com/transaction/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.001e8,
    ),
    worldcoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=11081,
        ADDRESS_VERSION=73,
        RPC_PORT=11082,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'worldcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 32*100000000 >> (height + 1)//2650000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=15, # s targetspacing
        SYMBOL='WDC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'worldcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/worldcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.worldcoin'), 'worldcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://wdc.cryptocoinexplorer.com/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://wdc.cryptocoinexplorer.com/address/',
        TX_EXPLORER_URL_PREFIX='http://wdc.cryptocoinexplorer.com/transaction/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.001e8,
    ),
    doubloons=math.Object(
        P2P_PREFIX='fcd9b7dd'.decode('hex'),
        P2P_PORT=1336,
        ADDRESS_VERSION=24,
        RPC_PORT=1337,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'doubloons address' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 1*100000000 >> (height + 1)//1080000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=30, # s targetspacing
        SYMBOL='DBL',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'doubloons') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Doubloons/') if platform.system() == 'Darwin' else os.path.expanduser('~/.doubloons'), 'doubloons.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://explorer.doubloons.net/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://explorer.doubloons.net/address/',
        TX_EXPLORER_URL_PREFIX='http://explorer.doubloons.net/transaction/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.001e8,
    ),
    casinocoin=math.Object(
        P2P_PREFIX='fac3b6da'.decode('hex'),
        P2P_PORT=47950,
        ADDRESS_VERSION=28,
        RPC_PORT=47970,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'casinocoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000 >> (height + 1)//3153600,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=30, # s targetspacing
        SYMBOL='CSC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'casinocoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/casinocoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.casinocoin'), 'casinocoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://casinocoin.mooo.com/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://casinocoin.mooo.com/address/',
	TX_EXPLORER_URL_PREFIX='http://casinocoin.mooo.com/transaction/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.001e8,
    ),
    bytecoin=math.Object(
        P2P_PREFIX='f9beef69'.decode('hex'),
        P2P_PORT=6333,
        ADDRESS_VERSION=18,
        RPC_PORT=6332,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'bitcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000 >> (height + 1)//210000,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=600, # s
        SYMBOL='BTE',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'bytecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/bytecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.bytecoin'), 'bytecoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://blockexplorer.bytecoin.in/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://blockexplorer.bytecoin.in/address/',
	TX_EXPLORER_URL_PREFIX='http://blockexplorer.bytecoin.in/transaction/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=0.001e8,
    ),
    asiccoin=math.Object(
        P2P_PREFIX='fab5e8db'.decode('hex'),
        P2P_PORT=13434,
        ADDRESS_VERSION=22,
        RPC_PORT=13435,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'asiccoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000 >> (height * 1)//210000,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=45, # s
        SYMBOL='ASC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'asiccoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/asiccoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.asiccoin'), 'asiccoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/address/',
	TX_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=0.001e8,
    ),
    joulecoin=math.Object(
        P2P_PREFIX='a5c07955'.decode('hex'),
        P2P_PORT=26789,
        ADDRESS_VERSION=43,
        RPC_PORT=8844,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'joulecoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 16*100000000 >> (height * 1)//1401600,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=45, # s
        SYMBOL='XJO',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'joulecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/joulecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.joulecoin'), 'joulecoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://xjo-explorer.cryptohaus.com:2750/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://xjo-explorer.cryptohaus.com:2750/address/',
	TX_EXPLORER_URL_PREFIX='http://xjo-explorer.cryptohaus.com:2750/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=0.001e8,
    ),
    unobtanium=math.Object(
        P2P_PREFIX='03d5b503'.decode('hex'), #messagestart
        P2P_PORT=65534,
        ADDRESS_VERSION=130, #pubkey_address
        RPC_PORT=65535,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'unobtaniumaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 0.001*100000000 if height<2000  else 1*100000000 >> (height * 1)//120000,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=180, # s
        SYMBOL='Un',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'unobtanium') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/unobtanium/') if platform.system() == 'Darwin' else os.path.expanduser('~/.unobtanium'), 'unobtanium.conf'),
	BLOCK_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/block/',
	ADDRESS_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/address/',
	TX_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/tx/',
	SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=0.00001e8,
    ),
    dogecoin=math.Object(
        P2P_PREFIX='c0c0c0c0'.decode('hex'),
        P2P_PORT=22556,
        ADDRESS_VERSION=30,
        RPC_PORT=22555,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'dogecoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 10000*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='DOGE',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'DogeCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Dogecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.dogecoin'), 'dogecoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://dogechain.info/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://dogechain.info/address/',
        TX_EXPLORER_URL_PREFIX='http://dogechain.info/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    billioncoin=math.Object(
        P2P_PREFIX='c0c0c0c0'.decode('hex'),
        P2P_PORT=22576,
        ADDRESS_VERSION=26,
        RPC_PORT=22565,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'billioncoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 1000*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='BIL',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'BillionCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Billioncoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.billioncoin'), 'billioncoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://115.28.52.63/bil/block/index.php?block_hash=',
        ADDRESS_EXPLORER_URL_PREFIX='http://115.28.52.63/bil/block/index.php?address=', #dummy - not supported by crawler
        TX_EXPLORER_URL_PREFIX='http://115.28.52.63/bil/block/index.php?transaction=',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    mooncoin=math.Object(
        P2P_PREFIX='f9f7c0e8'.decode('hex'),
        P2P_PORT=44664,
        ADDRESS_VERSION=3,
        RPC_PORT=44663,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'tomooncoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 2000000*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=90, # s
        SYMBOL='MOON',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'MoonCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Mooncoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.mooncoin'), 'mooncoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://moonchain.info/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://moonchain.info/address/',
        TX_EXPLORER_URL_PREFIX='http://moonchain.info/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    catcoin=math.Object(
        P2P_PREFIX='fcc1b7dc'.decode('hex'),
        P2P_PORT=9933,
        ADDRESS_VERSION=21,
        RPC_PORT=9932,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'catcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='CAT',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'CatCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Catcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.catcoin'), 'catcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://catchain.info/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://catchain.info/address/',
        TX_EXPLORER_URL_PREFIX='http://catchain.info/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    dubstepcoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=62030,
        ADDRESS_VERSION=29,
        RPC_PORT=62040,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'dubstepcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 200*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=180, # s
        SYMBOL='WUBS',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'DubstepCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Dubstepcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.dubstepcoin'), 'dubstepcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://wub.info/block/', #dummy for now
        ADDRESS_EXPLORER_URL_PREFIX='http://wub.info/address/',
        TX_EXPLORER_URL_PREFIX='http://wub.info/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    monacoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'), #pchmessagestart
        P2P_PORT=9401,
        ADDRESS_VERSION=50, #pubkey_
        RPC_PORT=9402,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'monacoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=90, # s
        SYMBOL='MONA',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'monacoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Monacoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.monacoin'), 'monacoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://monacoin.org/crawler/block_crawler.php?block_hash=',
        ADDRESS_EXPLORER_URL_PREFIX='http://monacoin.org/crawler/block_crawler.php?address=',  #dummy for now, not supported by explorer
        TX_EXPLORER_URL_PREFIX='http://monacoin.org/crawler/block_crawler.php?transaction=',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    luckycoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=9917,
        ADDRESS_VERSION=47,
        RPC_PORT=9918,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'luckycoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 88*100000000 >> (height + 1)//1036800,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60,
        SYMBOL='LKY',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Luckycoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Luckycoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.luckycoin'), 'luckycoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://d.evco.in/abe/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://d.evco.in/abe/address/',
        TX_EXPLORER_URL_PREFIX='http://d.evco.in/abe/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    giftcoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=8854,
        ADDRESS_VERSION=39,
        RPC_PORT=8855,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'giftcoinaddress' in (yield bitcoind.rpc_help()) and 
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=300,
        SYMBOL='GFT',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Giftcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Giftcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.giftcoin'), 'giftcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://giftchain.info/block/', #dummy for now
        ADDRESS_EXPLORER_URL_PREFIX='http://giftchain.info/address/',
        TX_EXPLORER_URL_PREFIX='http://giftchain.info/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,

    ),
    pesetacoin=math.Object(
        P2P_PREFIX='c0c0c0c0'.decode('hex'),
        P2P_PORT=16639,
        ADDRESS_VERSION=47,
        RPC_PORT=16638,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'pesetacoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 166386*100000 >> (height + 1)//840000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='PTC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Pesetacoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Pesetacoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.pesetacoin'), 'pesetacoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://pesetacoin.info/block/', #dummy
        ADDRESS_EXPLORER_URL_PREFIX='http://pesetacoin.info/address/',
        TX_EXPLORER_URL_PREFIX='http://pesetacoin.info/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    lennycoin=math.Object(
        P2P_PREFIX='c0c0c0c0'.decode('hex'),
        P2P_PORT=62556,
        ADDRESS_VERSION=8,
        RPC_PORT=62555,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'lennycoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 100*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=180, # s
        SYMBOL='LENNY',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'lennycoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/lennycoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.lennycoin'), 'lennycoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://lennycoin.info/block/', #dummy
        ADDRESS_EXPLORER_URL_PREFIX='http://lennycoin.info/address/',
        TX_EXPLORER_URL_PREFIX='http://lennycoin.info/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    coinye=math.Object(
        P2P_PREFIX='f9f7c0e8'.decode('hex'),
        P2P_PORT=41338,
        ADDRESS_VERSION=11,
        RPC_PORT=41337,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'coinyecoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 666666*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=90, # s
        SYMBOL='COYE',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'coinyecoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/coinyecoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.coinyecoin'), 'coinyecoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://coinyechain.info/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://coinyechain.info/address/',
        TX_EXPLORER_URL_PREFIX='http://coinyechain.info/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    aliencoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'), #pchmessagestart
        P2P_PORT=52112,
        ADDRESS_VERSION=23, #pubkey_address
        RPC_PORT=52111,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'aliencoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 40*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=30, # s
        SYMBOL='ALN',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'aliencoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/aliencoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.aliencoin'), 'aliencoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://cryptexplorer.com/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://cryptexplorer.com/address/',
        TX_EXPLORER_URL_PREFIX='http://cryptexplorer.com/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    usde=math.Object(
        P2P_PREFIX='d9d9f9bd'.decode('hex'), #pchmessagestart
        P2P_PORT=54449,
        ADDRESS_VERSION=38, #pubkey_address
        RPC_PORT=54448,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'usdeaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 1000*100000000 if height>1000 else 100*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='USDe',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'usde') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/usde/') if platform.system() == 'Darwin' else os.path.expanduser('~/.usde'), 'usde.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/',
        ADDRESS_EXPLORER_URL_PREFIX='https://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='https://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    rpcoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'), #pchmessagestart
        P2P_PORT=9027,
        ADDRESS_VERSION=60, #pubkey_address
        RPC_PORT=9026,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'ronpaulcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 1*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=120, # s
        SYMBOL='RPC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'ronpaulcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/ronpaulcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.ronpaulcoin'), 'ronpaulcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://cryptexplorer.com/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://cryptexplorer.com/address/',
        TX_EXPLORER_URL_PREFIX='http://cryptexplorer.com/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.0001e8,
    ),
    polcoin=math.Object(
        P2P_PREFIX='a5725982'.decode('hex'), #pchmessagestart
        P2P_PORT=9338,
        ADDRESS_VERSION=0, #pubkey_address
        RPC_PORT=9337,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'polcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 50*100000000 >> (height + 1)//210000,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=60, # s
        SYMBOL='PLC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'polcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/polcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.polcoin'), 'polcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://plcexplorer.com/block/', #dummy
        ADDRESS_EXPLORER_URL_PREFIX='http://plcexplorer.com/address/',
        TX_EXPLORER_URL_PREFIX='http://plcexplorer.com/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=0.001e8,
    ),
    coin42=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'), #pchmessagestart
        P2P_PORT=24242,
        ADDRESS_VERSION=8, #pubkey_address
        RPC_PORT=4242,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            '42address' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 0.00004200*100000000 if height>420 else 0.00000010*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=42, # s
        SYMBOL='42c',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], '42') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/42/') if platform.system() == 'Darwin' else os.path.expanduser('~/.42'), '42.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='http://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0,
    ),
    foxcoin=math.Object(
        P2P_PREFIX='fcd9b7dd'.decode('hex'), #pchmessagestart
        P2P_PORT=9929,
        ADDRESS_VERSION=136, #pubkey_address
        RPC_PORT=9919,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'FoxCoin' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 250*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='FOX',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'FoxCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/FoxCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.FoxCoin'), 'FoxCoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/', #dummy
        ADDRESS_EXPLORER_URL_PREFIX='http://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='http://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.001e8,
    ),
    argentum=math.Object(
        P2P_PREFIX='fbc1b8dc'.decode('hex'), #pchmessagestart
        P2P_PORT=13580,
        ADDRESS_VERSION=23, #pubkey_address
        RPC_PORT=13581,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'Argentumaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
	SUBSIDY_FUNC=lambda height: 1*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=120, # s
        SYMBOL='ARG',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'argentum') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Argentum/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.Argentum'), 'Argentum.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://arg.webboise.com/chain/Argentum/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://arg.webboise.com/chain/Argentum/address/',
        TX_EXPLORER_URL_PREFIX='http://arg.webboise.com/chain/Argentum/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.0001e8,
    ),
    smartcoin=math.Object(
        P2P_PREFIX='defaced0'.decode('hex'), #pchmessagestart
        P2P_PORT=58585,
        ADDRESS_VERSION=63, #pubkey_address
        RPC_PORT=58583,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'smartcoin' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
	SUBSIDY_FUNC=lambda height: 64*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=40, # s
        SYMBOL='SMC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'smartcoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/smartcoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.smartcoin'), 'smartcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='http://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.0001e8,
    ),
    kittehcoin=math.Object(
        P2P_PREFIX='c0c0c0c0'.decode('hex'), #pchmessagestart
        P2P_PORT=22566,
        ADDRESS_VERSION=45, #pubkey_address
        RPC_PORT=22565,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'kittehcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
	SUBSIDY_FUNC=lambda height: 1000*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='MEOW',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'kittehcoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/kittehcoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.kittehcoin'), 'kittehcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://kitexplorer.tk/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://kitexplorer.tk/address/',
        TX_EXPLORER_URL_PREFIX='http://kitexplorer.tk/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.00001e8,
    ),
    leafcoin=math.Object(
        P2P_PREFIX='aaaaaacc'.decode('hex'), #pchmessagestart
        P2P_PORT=22813,
        ADDRESS_VERSION=95, #pubkey_address
        RPC_PORT=22812,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'leafcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 100000*100000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='LEAF',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'LeafCoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Leafcoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.leafcoin'), 'leafcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://explorer2.leafco.in/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://explorer2.leafco.in/address/',
        TX_EXPLORER_URL_PREFIX='http://explorer2.leafco.in/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    ekrona=math.Object(
        P2P_PREFIX='dcc1c104'.decode('hex'), #pchmessagestart
        P2P_PORT=9445,
        ADDRESS_VERSION=45, #pubkey_address
        RPC_PORT=9444,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'ekronaaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 40*100000000 >> (height + 1)//500000 ,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=200, #seconds
        SYMBOL='KRN',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Ekrona') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/ekrona/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.ekrona'), 'ekrona.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/', #dummy
        ADDRESS_EXPLORER_URL_PREFIX='http://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='http://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.001e8,
    ),
    reddcoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=45444,
        ADDRESS_VERSION=61,
        RPC_PORT=45443,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'reddcoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 100000*100000000 >> (height + 1)//500000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='RDD',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Reddcoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Reddcoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.reddcoin'), 'reddcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://cryptexplorer.com/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://cryptexplorer.com/address/',
        TX_EXPLORER_URL_PREFIX='http://cryptexplorer.com/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0,
    ),
    tigercoin=math.Object(
        P2P_PREFIX='fab5dfdb'.decode('hex'),
        P2P_PORT=15660,
        ADDRESS_VERSION=127,
        RPC_PORT=15661,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue('tigercoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 128*100000000 >> (height + 1)//172800,
        POW_FUNC=data.hash256,
        BLOCK_PERIOD=45, # s
        SYMBOL='TGC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'tigercoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/tigercoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.tigercoin'), 'tigercoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/address/',
        TX_EXPLORER_URL_PREFIX='http://bit.usr.sh:2750/tx/',
        SANE_TARGET_RANGE=(2**256//2**32//1000 - 1, 2**256//2**32 - 1),
        DUMB_SCRYPT_DIFF=1,
        DUST_THRESHOLD=0.001e8,
    ),
    frycoin=math.Object(
        P2P_PREFIX='fbc0b6db'.decode('hex'),
        P2P_PORT=55901,
        ADDRESS_VERSION=35,
        RPC_PORT=55900,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'Frycoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 300*100000000 >> (height + 1)//16666,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=120, # s
        SYMBOL='FRY',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Frycoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Frycoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.Frycoin'), 'Frycoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/', #dummy
        ADDRESS_EXPLORER_URL_PREFIX='http://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='http://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.0001e8,
    ),
    digibyte=math.Object(
        P2P_PREFIX='fac3b6da'.decode('hex'), #pchmessagestart
        P2P_PORT=12024,
        ADDRESS_VERSION=30, #pubkey_address
        RPC_PORT=14022,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'digibyteaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: __import__('digibyte_subsidy').GetBlockBaseValue(height),
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s
        SYMBOL='DGB',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'digibyte') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/digibyte/') if platform.system() == 'Darwin' else os.path.expanduser('~/.digibyte'), 'digibyte.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='http://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.0001e8,
    ),
    antikeiser=math.Object(
        P2P_PREFIX='fbc0c0c0'.decode('hex'), #pchmessagestart
        P2P_PORT=39919,
        ADDRESS_VERSION=23, #pubkey_address
        RPC_PORT=39918,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'antikeiser' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 40000*100000000 >> (height + 1)//12000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=120, # seconds
        SYMBOL='AKC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'AntiKeiserCoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/AntiKesierCoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.antikeisercoin'), 'antikeisercoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='http://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    polishcoin=math.Object(
        P2P_PREFIX='fcd9b7dd'.decode('hex'), #pchmessagestart
        P2P_PORT=4824,
        ADDRESS_VERSION=22, #pubkey_address
        RPC_PORT=4822,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'polishcoin' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 100*150000000 >> (height + 1)//750000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # seconds
        SYMBOL='PCC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'PolishCoin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/PolishCoin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.polishcoin'), 'polishcoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://altexplorer.net/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://altexplorer.net/address/',
        TX_EXPLORER_URL_PREFIX='http://altexplorer.net/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    Coin=math.Object(
        P2P_PREFIX='a9c5bdd1'.decode('hex'), #pchmessagestart
        P2P_PORT=24057,
        ADDRESS_VERSION=28, #pubkey_address
        RPC_PORT=24055,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'Coinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 0*1200000000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # seconds
        SYMBOL='COIN',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'Coin') 
		if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Coin/') 
		if platform.system() == 'Darwin' else os.path.expanduser('~/.Coin'), 'Coin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://explorer.coin-project.org/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://explorer.coin-project.org/address/',
        TX_EXPLORER_URL_PREFIX='http://explorer.coin-project.org/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.03e8,
    ),
    fckbankscoin=math.Object(
        P2P_PREFIX='fcd9b7dd'.decode('hex'), #stripped from fckbankscoind's main.cpp -> pchMessageStart[4] = { 0xfc, 0xd9, 0xb7, 0xdd };
        P2P_PORT=21779, #fckbankscoind 's p2p port
        ADDRESS_VERSION=36, #look again in the sourcecode in the file base58.h, and find the value of PUBKEY_ADDRESS.
        RPC_PORT=21778, #fckbankscoind 's rpc port
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'fckbankscoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda height: 100000*100000000 >> (height + 1)//100000,
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # one block generation time
        SYMBOL='FCK',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'fckbankscoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/fckbankscoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.fckbankscoin'), 'fckbankscoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://explorer.fckbanks.org/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://explorer.fckbanks.org/address/',
        TX_EXPLORER_URL_PREFIX='http://explorer.fckbanks.org/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1), #??
        DUMB_SCRYPT_DIFF=2**16, #??
        DUST_THRESHOLD=0.03e8, #??
    ),


)
for net_name, net in nets.iteritems():
    net.NAME = net_name
