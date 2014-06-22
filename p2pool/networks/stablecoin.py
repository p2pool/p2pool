from p2pool.bitcoin import networks

PARENT = networks.nets['stablecoin']
SHARE_PERIOD = 20
CHAIN_LENGTH = 12*60*60//20
REAL_CHAIN_LENGTH = 12*60*60//20
TARGET_LOOKBEHIND = 20
SPREAD = 5 # blocks
IDENTIFIER = 'e00007b8c60242af'.decode('hex')
PREFIX = 'b666601991aa19a2'.decode('hex')
P2P_PORT = 7979
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 7977
BOOTSTRAP_ADDRS = 'p2pool-eu.gotgeeks.com p2pool-us.gotgeeks.com rav3n.dtdns.net doge.dtdns.net pool.hostv.pl p2pool.org p2pool.gotgeeks.com p2pool.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
