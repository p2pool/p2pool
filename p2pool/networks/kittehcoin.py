from p2pool.bitcoin import networks

PARENT = networks.nets['kittehcoin']
SHARE_PERIOD = 5 # seconds
CHAIN_LENGTH = 12*60*60//5 # shares
REAL_CHAIN_LENGTH = 12*60*60//5 # shares
TARGET_LOOKBEHIND = 20 # shares
SPREAD = 50 # blocks
IDENTIFIER = 'c0c1c2e3e6e9f1ab'.decode('hex')
PREFIX = 'f1c3e9a023e0f078'.decode('hex')
P2P_PORT = 8566
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = False
WORKER_PORT = 9566
BOOTSTRAP_ADDRS = 'lovok.no-ip.com taken.pl meow-il.zapto.org rav3n.dtdns.net solidpool.org'.split(' ')
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: 80602 <= v
VERSION_WARNING = lambda v: 'Upgrade KittehCoin to >= 0.8.6.2!' if v < 80602 else None
