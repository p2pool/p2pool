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

@defer.inlineCallbacks
def get_subsidy(bitcoind, target):
    res = yield bitcoind.rpc_getblock(target)

    defer.returnValue(res)

nets = dict(
    novacoin=math.Object(
        P2P_PREFIX='e4e8e9e5'.decode('hex'),
        P2P_PORT=7777,
        ADDRESS_VERSION=8,
        RPC_PORT=8344,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            0 == (yield bitcoind.rpc_getblock('00000a060336cbb72fe969666d337b87198b1add2abaa59cca226820b32933a4'))['height'] and
            not (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda bitcoind, target: get_subsidy(bitcoind, target),
        BLOCK_PERIOD=600, # s
        SYMBOL='NVC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'NovaCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/NovaCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.novacoin'), 'novacoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://explorer.novaco.in/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://explorer.novaco.in/address/',
        TX_EXPLORER_URL_PREFIX='http://explorer.novaco.in/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.01e6,
    ),
    novacoin_testnet=math.Object(
        P2P_PREFIX='cdf2c0ef'.decode('hex'),
        P2P_PORT=17777,
        ADDRESS_VERSION=111,
        RPC_PORT=18344,
        RPC_CHECK=defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            0 == (yield bitcoind.rpc_getblock('0000c763e402f2436da9ed36c7286f62c3f6e5dbafce9ff289bd43d7459327eb'))['height'] and
            (yield bitcoind.rpc_getinfo())['testnet']
        )),
        SUBSIDY_FUNC=lambda bitcoind, target: get_subsidy(bitcoind, target),
        BLOCK_PERIOD=600, # s
        SYMBOL='tNVC',
        CONF_FILE_FUNC=lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'NovaCoin') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/NovaCoin/') if platform.system() == 'Darwin' else os.path.expanduser('~/.novacoin'), 'novacoin.conf'),
        BLOCK_EXPLORER_URL_PREFIX='http://novacoin.su/block/',
        ADDRESS_EXPLORER_URL_PREFIX='http://novacoin.su/address/',
        TX_EXPLORER_URL_PREFIX='http://novacoin.su/tx/',
        SANE_TARGET_RANGE=(2**256//1000000000 - 1, 2**256//1000 - 1),
        DUMB_SCRYPT_DIFF=2**16,
        DUST_THRESHOLD=0.01e6,
    ),
)
for net_name, net in nets.iteritems():
    net.NAME = net_name
