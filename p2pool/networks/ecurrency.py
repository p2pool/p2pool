from p2pool.bitcoin import networks

PARENT = networks.nets['ecurrency']
SHARE_PERIOD = 10 # seconds
CHAIN_LENGTH = 12*60*60//10 # shares
REAL_CHAIN_LENGTH = 12*60*60//10 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 20 # blocks
IDENTIFIER = 'f0e41ab70eff1e12'.decode('hex')
PREFIX = 'e01fa73e0af1e40a'.decode('hex')
P2P_PORT = 8179
MIN_TARGET = 0
MAX_TARGET = 2**256//2**32 - 1
PERSIST = False
WORKER_PORT = 9179
BOOTSTRAP_ADDRS = '46.19.142.14 23.95.9.59 p2pool-eu.eCurrency.io rav3n.dtdns.net pool.hostv.pl p2pool.org solidpool.org taken.pl'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
