from p2pool.bitcoin import networks

PARENT = networks.nets['dubstepcoin']
SHARE_PERIOD = 25 # seconds target spacing
CHAIN_LENGTH = 12*60*60//25 # shares
REAL_CHAIN_LENGTH = 12*60*60//25 # shares
TARGET_LOOKBEHIND = 20 # shares coinbase maturity
SPREAD = 20 # blocks
IDENTIFIER = 'dcb7c1fcfbc0b6db'.decode('hex')
PREFIX = 'bd6b0cbcffc1f0fd'.decode('hex')
P2P_PORT = 8033
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9033
BOOTSTRAP_ADDRS = 'p2pool-eu.gotgeeks.com p2pool-us.gotgeeks.com rav3n.dtdns.net doge.dtdns.net pool.hostv.pl p2pool.org p2pool.gotgeeks.com p2pool.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
