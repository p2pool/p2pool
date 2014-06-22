from p2pool.bitcoin import networks

PARENT = networks.nets['fckbankscoin']
SHARE_PERIOD = 10 # seconds #How often should P2Pool generate a new share (rule of thumb: 1/5 - 1/10 of the block period)
CHAIN_LENGTH = 24*60*60//10 # shares
REAL_CHAIN_LENGTH = 24*60*60//10 # shares #CHAIN_LENGTH & REAL_CHAIN_LENGTH are set up to allow for 3 Hour PPLNS.
TARGET_LOOKBEHIND = 30 # is set to 30 (shares) giving a 300 second (5min) difficulty adjustment.
SPREAD = 30 # blocks #SPREAD=30 block every 60 seconds 600/60=10 10x3=30 because bitcoin's SPREAD=3 block every 600 seconds and litecoin'sSPREAD=12 block every 150 seconds 600/150=4 4x3=12
IDENTIFIER = '41a7d0b44d0b3d36'.decode('hex') #some random s-it (I think its used to identify others p2pool's mining this coin)
PREFIX = '9117d0b44d0538cf'.decode('hex') #IDENTIFIER & PREFIX: P2Pool will only sync with other nodes who have Identifier and Prefix matching yours (and using same p2p port).. if any of the above values change, a new identifier & prefix need to be created in order to prevent problems.
P2P_PORT = 11779 #port that p2pool is comunicating on with other p2pools
MIN_TARGET = 0
MAX_TARGET = 2**256//2**20 - 1
PERSIST = True #this value tells the p2pool if it should mine solo or connect to other p2pools.
WORKER_PORT = 19334
BOOTSTRAP_ADDRS = 'hashattack.com b1czu.sytes.net 37.139.19.246'.split(' ') #here we need to add working p2pool fck nodes to allow others connecting
ANNOUNCE_CHANNEL = '#p2pool-alt'
VERSION_CHECK = lambda v: 10000 <= v
VERSION_WARNING = lambda v: 'Upgrade FCKbankscoin to >=1.0.0.0!' if v < 10000 else None
