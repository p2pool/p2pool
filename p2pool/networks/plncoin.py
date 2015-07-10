from p2pool.bitcoin import networks

PARENT = networks.nets['plncoin']
SHARE_PERIOD = 20 # seconds
CHAIN_LENGTH = 12*60*60//20 # shares
REAL_CHAIN_LENGTH = 12*60*60//20 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 10 # blocks
IDENTIFIER = 'ffdd0a3ba17e00a1'.decode('hex')
PREFIX = 'ee3b819a0133e7fa'.decode('hex')
P2P_PORT = 7133
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9133
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net p2p.zaplnc.pl'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
