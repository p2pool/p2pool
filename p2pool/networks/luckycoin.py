from p2pool.bitcoin import networks

PARENT = networks.nets['luckycoin']
SHARE_PERIOD = 10
CHAIN_LENGTH = 12*60*60//10
REAL_CHAIN_LENGTH = 12*60*60//10
TARGET_LOOKBEHIND = 20
SPREAD = 50
IDENTIFIER = 'cdbb6c0fbc0b6dcb'.decode('hex')
PREFIX = 'bbcd0f0f6d6dbcbc'.decode('hex')
P2P_PORT = 8817
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9817
BOOTSTRAP_ADDRS = 'p2pool-eu.gotgeeks.com p2pool-us.gotgeeks.com rav3n.dtdns.net doge.dtdns.net pool.hostv.pl p2pool.org p2pool.gotgeeks.com p2pool.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: True
