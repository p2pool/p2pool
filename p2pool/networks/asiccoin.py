from p2pool.bitcoin import networks

PARENT = networks.nets['asiccoin']
SHARE_PERIOD = 30 # seconds
CHAIN_LENGTH = 24*60*60//10 # shares
REAL_CHAIN_LENGTH = 24*60*60//10 # shares
TARGET_LOOKBEHIND = 200 # shares
SPREAD = 3 # blocks
IDENTIFIER = '2c80035c7a81bc6f'.decode('hex')
PREFIX = '2472ef181efcd37c'.decode('hex')
P2P_PORT = 7432
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 9433
BOOTSTRAP_ADDRS = 'japool.com:13432 p2pool-eu.gotgeeks.com p2pool-us.gotgeeks.com rav3n.dtdns.net doge.dtdns.net pool.hostv.pl p2pool.org p2pool.gotgeeks.com p2pool.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-asc'
VERSION_CHECK = lambda v: True
