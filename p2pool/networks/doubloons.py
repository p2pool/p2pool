from p2pool.bitcoin import networks

PARENT = networks.nets['doubloons']
SHARE_PERIOD = 5 # seconds target spacing
CHAIN_LENGTH = 12*60*60//5 # shares
REAL_CHAIN_LENGTH = 12*60*60//5 # shares
TARGET_LOOKBEHIND = 20 # blocks
SPREAD = 30 # blocks
IDENTIFIER = 'fe43a6b9f6924a10'.decode('hex')
PREFIX = 'fe8f19aba6d7729a'.decode('hex')
P2P_PORT = 8346
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 8345
BOOTSTRAP_ADDRS = 'p2pool-eu.gotgeeks.com p2pool-us.gotgeeks.com rav3n.dtdns.net doge.dtdns.net pool.hostv.pl p2pool.org p2pool.gotgeeks.com p2pool.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
