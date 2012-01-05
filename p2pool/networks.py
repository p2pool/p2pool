from p2pool.bitcoin import networks
from p2pool.util import math

# CHAIN_LENGTH = number of shares back client keeps
# REAL_CHAIN_LENGTH = maximum number of shares back client uses to compute payout
# REAL_CHAIN_LENGTH must always be <= CHAIN_LENGTH
# REAL_CHAIN_LENGTH must be changed in sync with all other clients
# changes can be done by changing one, then the other

BitcoinMainnet = math.Object(
    PARENT=networks.BitcoinMainnet,
    SHARE_PERIOD=10, # seconds
    CHAIN_LENGTH=24*60*60//10, # shares
    REAL_CHAIN_LENGTH_FUNC=lambda ts: 24*60*60//10 if ts >= 1325805105 else 24*60*60//10//2, # shares
    TARGET_LOOKBEHIND=200, # shares
    SPREAD=3, # blocks
    IDENTIFIER='fc70035c7a81bc6f'.decode('hex'),
    PREFIX='2472ef181efcd37b'.decode('hex'),
    NAME='bitcoin',
    P2P_PORT=9333,
    MAX_TARGET=2**256//2**32 - 1,
    PERSIST=True,
    WORKER_PORT=9332,
    BOOTSTRAP_ADDRS='74.220.242.6:9334 93.97.192.93 66.90.73.83 67.83.108.0 219.84.64.174 24.167.17.248 109.74.195.142 83.211.86.49 89.78.212.44 94.23.34.145 168.7.116.243 72.14.191.28 94.174.40.189:9344'.split(' '),
)
BitcoinTestnet = math.Object(
    PARENT=networks.BitcoinTestnet,
    SHARE_PERIOD=10, # seconds
    CHAIN_LENGTH=24*60*60//10, # shares
    REAL_CHAIN_LENGTH_FUNC=lambda ts: 24*60*60//10 if ts >= 1325805105 else 24*60*60//10//2, # shares
    TARGET_LOOKBEHIND=200, # shares
    SPREAD=3, # blocks
    IDENTIFIER='5fc2be2d4f0d6bfb'.decode('hex'),
    PREFIX='3f6057a15036f441'.decode('hex'),
    NAME='bitcoin_testnet',
    P2P_PORT=19333,
    MAX_TARGET=2**256//2**32 - 1,
    PERSIST=False,
    WORKER_PORT=19332,
    BOOTSTRAP_ADDRS='72.14.191.28'.split(' '),
)

NamecoinMainnet = math.Object(
    PARENT=networks.NamecoinMainnet,
    SHARE_PERIOD=10, # seconds
    CHAIN_LENGTH=24*60*60//10, # shares
    REAL_CHAIN_LENGTH=24*60*60//10, # shares
    TARGET_LOOKBEHIND=3600//10, # shares
    SPREAD=3, # blocks
    IDENTIFIER='d5b1192062c4c454'.decode('hex'),
    PREFIX='b56f3d0fb24fc982'.decode('hex'),
    NAME='namecoin',
    P2P_PORT=9334,
    MAX_TARGET=2**256//2**32 - 1,
    PERSIST=True,
    WORKER_PORT=9331,
    BOOTSTRAP_ADDRS='72.14.191.28'.split(' '),
)
NamecoinTestnet = math.Object(
    PARENT=networks.NamecoinTestnet,
    SHARE_PERIOD=10, # seconds
    CHAIN_LENGTH=24*60*60//10, # shares
    REAL_CHAIN_LENGTH=24*60*60//10, # shares
    TARGET_LOOKBEHIND=200, # shares
    SPREAD=3, # blocks
    IDENTIFIER='8dd303d014a01a60'.decode('hex'),
    PREFIX='4d6581d24f51acbf'.decode('hex'),
    NAME='namecoin_testnet',
    P2P_PORT=19334,
    MAX_TARGET=2**256//2**32 - 1,
    PERSIST=False,
    WORKER_PORT=19331,
    BOOTSTRAP_ADDRS='72.14.191.28'.split(' '),
)

LitecoinMainnet = math.Object(
    PARENT=networks.LitecoinMainnet,
    SHARE_PERIOD=10, # seconds
    CHAIN_LENGTH=24*60*60//10, # shares
    REAL_CHAIN_LENGTH_FUNC=lambda ts: 24*60*60//10 if ts >= 1325805105 else 24*60*60//10//2, # shares
    TARGET_LOOKBEHIND=200, # shares
    SPREAD=12, # blocks
    IDENTIFIER='e037d5b8c6923410'.decode('hex'),
    PREFIX='7208c1a53ef629b0'.decode('hex'),
    NAME='litecoin',
    P2P_PORT=9338,
    MAX_TARGET=2**256//2**20 - 1,
    PERSIST=True,
    WORKER_PORT=9327,
    BOOTSTRAP_ADDRS='72.14.191.28 176.31.249.89'.split(' ')
)
LitecoinTestnet = math.Object(
    PARENT=networks.LitecoinTestnet,
    SHARE_PERIOD=10, # seconds
    CHAIN_LENGTH=24*60*60//10, # shares
    REAL_CHAIN_LENGTH_FUNC=lambda ts: 24*60*60//10 if ts >= 1325805105 else 24*60*60//10//2, # shares
    TARGET_LOOKBEHIND=200, # shares
    SPREAD=12, # blocks
    IDENTIFIER='cca5e24ec6408b1e'.decode('hex'),
    PREFIX='ad9614f6466a39cf'.decode('hex'),
    NAME='litecoin_testnet',
    P2P_PORT=19338,
    MAX_TARGET=2**256//2**17 - 1,
    PERSIST=False,
    WORKER_PORT=19327,
    BOOTSTRAP_ADDRS='72.14.191.28 176.31.249.89'.split(' ')
)

nets=dict((net.NAME, net) for net in set([BitcoinMainnet, BitcoinTestnet, NamecoinMainnet, NamecoinTestnet, LitecoinMainnet, LitecoinTestnet]))
realnets=dict((net.NAME, net) for net in nets.itervalues() if '_testnet' not in net.NAME)
