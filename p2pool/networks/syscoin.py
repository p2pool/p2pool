from p2pool.bitcoin import networks

PARENT=networks.nets['syscoin']
SHARE_PERIOD=10 # seconds target spacing
CHAIN_LENGTH=12*60*60//10 # shares
REAL_CHAIN_LENGTH=12*60*60//10 # shares
TARGET_LOOKBEHIND=10 # shares coinbase maturity
SPREAD=20 # blocks
IDENTIFIER='24acdfeb0874eb2e'.decode('hex')
PREFIX='fc8eba5cacdfe446'.decode('hex')
P2P_PORT=8993
MIN_TARGET=0
MAX_TARGET=2**256//2**20 - 1
PERSIST=True
WORKER_PORT=8994
BOOTSTRAP_ADDRS='Node.syscoin.me'.split(' ')
ANNOUNCE_CHANNEL='#p2pool-alt'
VERSION_CHECK=lambda v: True
