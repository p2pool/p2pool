from p2pool.bitcoin import networks
from p2pool.util import math

# CHAIN_LENGTH = number of shares back client keeps
# REAL_CHAIN_LENGTH = maximum number of shares back client uses to compute payout
# REAL_CHAIN_LENGTH must always be <= CHAIN_LENGTH
# REAL_CHAIN_LENGTH must be changed in sync with all other clients
# changes can be done by changing one, then the other

nets = dict(
    bitcoin=math.Object(
        PARENT=networks.nets['bitcoin'],
        SHARE_PERIOD=10, # seconds
        CHAIN_LENGTH=24*60*60//10, # shares
        REAL_CHAIN_LENGTH=24*60*60//10, # shares
        TARGET_LOOKBEHIND=200, # shares
        SPREAD=3, # blocks
        IDENTIFIER='fc70035c7a81bc6f'.decode('hex'),
        PREFIX='2472ef181efcd37b'.decode('hex'),
        P2P_PORT=9333,
        MAX_TARGET=2**256//2**32 - 1,
        PERSIST=True,
        WORKER_PORT=9332,
        BOOTSTRAP_ADDRS='74.220.242.6:9334 93.97.192.93 66.90.73.83 67.83.108.0 219.84.64.174 24.167.17.248 109.74.195.142 83.211.86.49 89.78.212.44 94.23.34.145 168.7.116.243 72.14.191.28 94.174.40.189:9344'.split(' '),
        ANNOUNCE_CHANNEL='#p2pool',
        VERSION_CHECK=lambda v, temp_work: 50400 <= v < 60000 or 60003 <= v or '/P2SH/' in temp_work['coinbaseflags'],
    ),
    bitcoin_testnet=math.Object(
        PARENT=networks.nets['bitcoin_testnet'],
        SHARE_PERIOD=10, # seconds
        CHAIN_LENGTH=24*60*60//10, # shares
        REAL_CHAIN_LENGTH=24*60*60//10, # shares
        TARGET_LOOKBEHIND=200, # shares
        SPREAD=3, # blocks
        IDENTIFIER='5fc2be2d4f0d6bfb'.decode('hex'),
        PREFIX='3f6057a15036f441'.decode('hex'),
        P2P_PORT=19333,
        MAX_TARGET=2**256//2**32 - 1,
        PERSIST=False,
        WORKER_PORT=19332,
        BOOTSTRAP_ADDRS='72.14.191.28'.split(' '),
        ANNOUNCE_CHANNEL='#p2pool-alt',
        VERSION_CHECK=lambda v, temp_work: 50400 <= v < 60000 or 60003 <= v or '/P2SH/' in temp_work['coinbaseflags'],
    ),
    
    litecoin=math.Object(
        PARENT=networks.nets['litecoin'],
        SHARE_PERIOD=10, # seconds
        CHAIN_LENGTH=24*60*60//10, # shares
        REAL_CHAIN_LENGTH=24*60*60//10, # shares
        TARGET_LOOKBEHIND=200, # shares
        SPREAD=12, # blocks
        IDENTIFIER='e037d5b8c6923410'.decode('hex'),
        PREFIX='7208c1a53ef629b0'.decode('hex'),
        P2P_PORT=9338,
        MAX_TARGET=2**256//2**20 - 1,
        PERSIST=True,
        WORKER_PORT=9327,
        BOOTSTRAP_ADDRS='76.26.53.101 124.205.120.178 190.195.79.161 173.167.113.73 82.161.65.210 67.83.108.0 78.101.67.239 78.100.161.252 87.58.117.233 78.100.162.223 216.239.45.4 78.101.131.221 72.14.191.28 97.81.163.217 69.126.183.240 219.84.64.174 78.101.119.27 89.211.228.244 178.152.122.30 172.16.0.3 76.26.53.101:51319'.split(' '),
        ANNOUNCE_CHANNEL='#p2pool-alt',
        VERSION_CHECK=lambda v, temp_work: True,
    ),
    litecoin_testnet=math.Object(
        PARENT=networks.nets['litecoin_testnet'],
        SHARE_PERIOD=10, # seconds
        CHAIN_LENGTH=24*60*60//10, # shares
        REAL_CHAIN_LENGTH=24*60*60//10, # shares
        TARGET_LOOKBEHIND=200, # shares
        SPREAD=12, # blocks
        IDENTIFIER='cca5e24ec6408b1e'.decode('hex'),
        PREFIX='ad9614f6466a39cf'.decode('hex'),
        P2P_PORT=19338,
        MAX_TARGET=2**256//2000 - 1,
        PERSIST=False,
        WORKER_PORT=19327,
        BOOTSTRAP_ADDRS='72.14.191.28'.split(' '),
        ANNOUNCE_CHANNEL='#p2pool-alt',
        VERSION_CHECK=lambda v, temp_work: True,
    ),
)
for net_name, net in nets.iteritems():
    net.NAME = net_name
