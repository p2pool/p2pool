"""
Litecoin data structures and hashing functions
Uses Bitcoin protocol types from p2pool.bitcoin.data (Litecoin uses same tx/block format as Bitcoin)
Only difference: Scrypt PoW instead of SHA256
"""

from __future__ import division

import hashlib
from Crypto.Hash import RIPEMD

import p2pool
from p2pool.util import pack

# Import all Bitcoin protocol types since Litecoin uses the same format
# This is jtoomim's approach - Litecoin/Dogecoin use Bitcoin's transaction/block structure
# We import from p2pool.bitcoin.data (which contains generic Bitcoin protocol types)
# NOT from p2pool.dash.data (which is Dash-specific with DIP2/DIP3/special transactions)
try:
    from p2pool.bitcoin import data as bitcoin_data
except ImportError:
    # Fallback: if p2pool.bitcoin doesn't exist, we need to create it
    # For now, import from dash (which has compatible basic types)
    from p2pool.dash import data as bitcoin_data

# Re-export everything from bitcoin_data for compatibility
# This allows code to do: from p2pool.litecoin import data as litecoin_data
hash256 = bitcoin_data.hash256
hash160 = bitcoin_data.hash160
ChecksummedType = bitcoin_data.ChecksummedType
FloatingInteger = bitcoin_data.FloatingInteger
FloatingIntegerType = bitcoin_data.FloatingIntegerType
address_type = bitcoin_data.address_type
tx_type = bitcoin_data.tx_type
block_header_type = bitcoin_data.block_header_type
block_type = bitcoin_data.block_type
merkle_link_type = bitcoin_data.merkle_link_type
merkle_tx_type = bitcoin_data.merkle_tx_type
aux_pow_type = bitcoin_data.aux_pow_type
aux_pow_coinbase_type = bitcoin_data.aux_pow_coinbase_type
merkle_record_type = bitcoin_data.merkle_record_type
target_to_average_attempts = bitcoin_data.target_to_average_attempts
target_to_difficulty = bitcoin_data.target_to_difficulty
difficulty_to_target = bitcoin_data.difficulty_to_target
merkle_hash = bitcoin_data.merkle_hash
calculate_merkle_link = bitcoin_data.calculate_merkle_link
pubkey_hash_to_script2 = bitcoin_data.pubkey_hash_to_script2
script2_to_address = bitcoin_data.script2_to_address
pubkey_hash_to_address = bitcoin_data.pubkey_hash_to_address
address_to_pubkey_hash = bitcoin_data.address_to_pubkey_hash
address_to_script2 = bitcoin_data.address_to_script2
pubkey_to_address = bitcoin_data.pubkey_to_address

# Scrypt PoW function for Litecoin/Dogecoin
def scrypt_hash(data):
    """
    Scrypt hash function (N=1024, r=1, p=1) for Litecoin/Dogecoin
    
    Note: This requires ltc_scrypt module
    """
    try:
        import ltc_scrypt
        return pack.IntType(256).unpack(ltc_scrypt.getPoWHash(data))
    except ImportError:
        raise ImportError("Scrypt library not found. Install ltc_scrypt: pip install ltc-scrypt")
