import os
import platform

from twisted.internet import defer

from . import data
from p2pool.util import math, pack
from operator import *

def get_subsidy(nCap, nMaxSubsidy, bnTarget):
    bnLowerBound = 0.01
    bnUpperBound = bnSubsidyLimit = nMaxSubsidy
    bnTargetLimit = 0x00000fffff000000000000000000000000000000000000000000000000000000

    while bnLowerBound + 0.01 <= bnUpperBound:
        bnMidValue = (bnLowerBound + bnUpperBound) / 2
        if pow(bnMidValue, nCap) * bnTargetLimit > pow(bnSubsidyLimit, nCap) * bnTarget:
            bnUpperBound = bnMidValue
        else:
            bnLowerBound = bnMidValue

    nSubsidy = round(bnMidValue, 2)

    if nSubsidy > bnMidValue:
        nSubsidy = nSubsidy - 0.01

    return int(nSubsidy * 1000000)

nets = dict(
    novacoin=math.Object(
        P2P_PREFIX='e4e8e9e5'.decode('hex'),
        P2P_PORT=7777,
        ADDRESS_VERSION=8,
        RPC_PORT=8344,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'novacoinaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda target: get_subsidy(6, 100, target),
        BLOCKHASH_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=600, # s
        SYMBOL='NVC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'NovaCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/NovaCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.novacoin'), 'novacoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://nvc.cryptocoinexplorer.com/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://nvc.cryptocoinexplorer.com/address/',
        SANE_TARGET_RANGE=(2**256//2**20//1000 - 1, 2**256//2**20 - 1),
    ),
    novacoin_testnet=math.Object(
        P2P_PREFIX='cdf2c0ef'.decode('hex'),
        P2P_PORT=17777,
        ADDRESS_VERSION=111,
        RPC_PORT=8344,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'novacoinaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda target: get_subsidy(6, 100, target),
        BLOCKHASH_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=600, # s
        SYMBOL='tNVC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'NovaCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/NovaCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.novacoin'), 'novacoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://nonexistent-novacoin-testnet-explorer/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://nonexistent-novacoin-testnet-explorer/address/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
    ),
     bottlecaps=math.Object(
        P2P_PREFIX='e4e8e9e5'.decode('hex'),
        P2P_PORT=7685,
        ADDRESS_VERSION=34,
        RPC_PORT=8385,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'BottleCapsaddress' in (yield bitcoind.rpc_help()) and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        BLOCKHASH_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        SUBSIDY_FUNC= lambda height:  10000000000, ## CAP has 10 per block forever
        POW_FUNC=lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data)),
        BLOCK_PERIOD=60, # s targetspacing
        SYMBOL='CAP',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'bottlecaps') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/Bottlecaps/') if platform.system() == 'Darwin' else os.path.expanduser('~/.BottleCaps'), 'BottleCaps.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://bottlecaps.kicks-ass.net/block_crawler.php?block_hash=',
        ADDRESS_EXPLORER_URL_PREFIX='http://bottlecaps.kicks-ass.net/block_crawler.php?address=',
        SANE_TARGET_RANGE=(2**256//100000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=1e8,
    ),

)
for net_name, net in nets.iteritems():
    net.NAME = net_name
