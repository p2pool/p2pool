import os
import platform

from twisted.internet import defer

from .. import data, helper
from p2pool.util import pack


# Dogecoin Testnet4Alpha - P2Pool Private Merged Mining Testnet
# Created: January 2026
# Purpose: Work around official testnet block storm bug (PR #3967)
#
# Key features:
# - fEnforceStrictMinDifficulty = true (prevents block storms)
# - fMiningRequiresPeers = false (solo mining OK)
# - AuxPoW enabled from block 0
# - Digishield difficulty from block 0
# - Isolated network (no seeds)
#
# Genesis block mined 2025-01-26:
#   PoW hash (scrypt): 000005b78b201bb5e9d115cf18d55e8688480cb48bb7c9cf890d45d5ae9f785b
#   Block hash (SHA256): de2bcf594a4134cef164a2204ca2f9bce745ff61c22bd714ebc88a7f2bdd8734
#
# See: https://github.com/dogecoin/dogecoin/pull/3967

P2P_PREFIX = 'd4a1f4a1'.decode('hex')  # Testnet4alpha magic bytes (unique)
P2P_PORT = 44557
ADDRESS_VERSION = 113  # 0x71 - testnet addresses start with 'n' (same as testnet)
ADDRESS_P2SH_VERSION = 196  # 0xc4 - testnet P2SH addresses start with '2'
HUMAN_READABLE_PART = 't4dge'  # For potential future bech32 support
RPC_PORT = 44555
RPC_CHECK = defer.inlineCallbacks(lambda bitcoind: defer.returnValue(
            'getreceivedbyaddress' in (yield bitcoind.rpc_help()) and
            (yield bitcoind.rpc_getblockchaininfo())['chain'] == 'testnet4alpha'
        ))

# Dogecoin subsidy schedule (same as testnet)
def _subsidy_func(height):
    if height >= 600000:
        return 10000 * 100000000  # 10,000 DOGE forever
    elif height >= 500000:
        return 15625 * 100000000
    elif height >= 400000:
        return 31250 * 100000000
    elif height >= 300000:
        return 62500 * 100000000
    elif height >= 200000:
        return 125000 * 100000000
    elif height >= 145000:
        return 250000 * 100000000
    else:
        # Random rewards for early blocks (use max for estimation)
        return 500000 * 100000000

SUBSIDY_FUNC = _subsidy_func

# Dogecoin uses Scrypt PoW (same as Litecoin)
POW_FUNC = lambda data: pack.IntType(256).unpack(__import__('ltc_scrypt').getPoWHash(data))
BLOCKHASH_FUNC = POW_FUNC  # For scrypt coins, block hash and PoW hash are the same

BLOCK_PERIOD = 60  # 1 minute blocks
SYMBOL = 't4DOGE'
CONF_FILE_FUNC = lambda: os.path.join(
    os.path.join(os.environ['APPDATA'], 'Dogecoin') if platform.system() == 'Windows' 
    else os.path.expanduser('~/Library/Application Support/Dogecoin/') if platform.system() == 'Darwin' 
    else os.path.expanduser('~/.dogecoin'), 
    'dogecoin.conf'
)

# No public block explorers for testnet4alpha (private network)
BLOCK_EXPLORER_URL_PREFIX = 'http://localhost:44555/block/'
ADDRESS_EXPLORER_URL_PREFIX = 'http://localhost:44555/address/'
TX_EXPLORER_URL_PREFIX = 'http://localhost:44555/tx/'

# Standard difficulty range (proper difficulty with PR #3967 fix)
SANE_TARGET_RANGE = ((1 << 200) - 1, (1 << 256) - 1)
DUMB_SCRYPT_DIFF = 2**16
DUST_THRESHOLD = 1 * 100000000  # 1 DOGE dust threshold

# No segwit on Dogecoin
SOFTFORKS_REQUIRED = set()
