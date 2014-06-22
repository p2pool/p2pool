from p2pool.bitcoin import networks

PARENT = networks.nets['polcoin']
SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 12*60*60//30 # shares
REAL_CHAIN_LENGTH = 12*60*60//30 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'f1f2f3aaa512598f'.decode('hex')
PREFIX = 'e1e2e3b4381a47a0'.decode('hex')
P2P_PORT = 8883
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 9883
BOOTSTRAP_ADDRS = 'wojenny.no-ip.biz wojenny2.no-ip.biz wojenny3.no-ip.biz p2pool-eu.gotgeeks.com p2pool-us.gotgeeks.com rav3n.dtdns.net p2pool.gotgeeks.com p2pool.dndns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
