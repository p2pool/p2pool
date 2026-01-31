import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


P2P_PREFIX = 'bf0c6bbd'.decode('hex')
P2P_PORT = 9999
ADDRESS_VERSION = 76
SCRIPT_ADDRESS_VERSION = 16
RPC_PORT = 9998
RPC_CHECK = defer.inlineCallbacks(lambda dashd: defer.returnValue(
            (yield helper.check_block_header(dashd, '00000ffd590b1485b3caadc19b22e6379c733355108f107a430458cdf3407ab6')) and
            (yield dashd.rpc_getblockchaininfo())['chain'] == 'main'
        ))
BLOCKHASH_FUNC = lambda data: pack.IntType(256).unpack(__import__('dash_hash').getPoWHash(data))
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('dash_hash').getPoWHash(data))
BLOCK_PERIOD = 150 # s
SYMBOL = 'DASH'
CONF_FILE_FUNC = lambda: os.path.join(os.path.join(os.environ['APPDATA'], 'DashCore') if platform.system() == 'Windows' else os.path.expanduser('~/Library/Application Support/DashCore/') if platform.system() == 'Darwin' else os.path.expanduser('~/.dashcore'), 'dash.conf')
BLOCK_EXPLORER_URL_PREFIX = 'https://chainz.cryptoid.info/dash/block.dws?'
ADDRESS_EXPLORER_URL_PREFIX = 'https://chainz.cryptoid.info/dash/address.dws?'
TX_EXPLORER_URL_PREFIX = 'https://chainz.cryptoid.info/dash/tx.dws?'
# SANE_TARGET_RANGE: (min_target/max_diff, max_target/min_diff)
# max_target = 0xFFFF * 2**208 = standard bdiff difficulty 1 target
# min_target = max_target // max_diff for upper difficulty bound
# At 2 TH/s with 10s share rate: needs diff ~5000 (2^32 hashes per diff-1, 2 TH/s / 4.3 GH/s * 10s)
# Using 10000 as max to allow some headroom for faster ASICs
_DIFF1_TARGET = 0xFFFF * 2**208  # Standard bdiff difficulty 1 target (0x00000000FFFF00...)
SANE_TARGET_RANGE = (_DIFF1_TARGET // 10000, _DIFF1_TARGET)  # Max diff 10000, min diff 1
DUST_THRESHOLD = 0.001e8
DUMB_SCRYPT_DIFF = 1  # X11 uses 1:1 difficulty (unlike Scrypt's 65536)
STRATUM_SHARE_RATE = 10  # Target seconds per pseudoshare for stratum vardiff
