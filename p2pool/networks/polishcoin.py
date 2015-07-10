from p2pool.bitcoin import networks

PARENT = networks.nets['polishcoin']
SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 4*60*60//10 # shares
REAL_CHAIN_LENGTH = 4*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 120 # blocks
IDENTIFIER = 'a0ffe405a16b99fb'.decode('hex')
PREFIX = 'afa00aeffe4004c9'.decode('hex')
P2P_PORT = 4823
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9995
BOOTSTRAP_ADDRS = 'rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org taken.pl polishcoin.info pcc.paybtc.pl'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
