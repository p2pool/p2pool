from p2pool.bitcoin import networks

PARENT = networks.nets['digibyte']
SHARE_PERIOD = 10 # seconds target spacing
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares diff regulation
SPREAD = 50 # blocks
IDENTIFIER = '48a4ebc31b798115'.decode('hex')
PREFIX = '5685a276c2dd81db'.decode('hex')
P2P_PORT = 8022
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9022
BOOTSTRAP_ADDRS = 'p2p.mine.bz pool2eu.dgbmining.com dgbpool.cloudapp.net pool2na.dgbmining.com pool2me.dgbmining.com rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org taken.pl'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
