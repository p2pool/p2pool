#!/usr/bin/env python3
"""
Mine a new genesis block for Dogecoin Testnet4

This script calculates the nonce needed for a valid genesis block.
Uses scrypt algorithm like Dogecoin/Litecoin.
"""

import hashlib
import struct
import time
import sys

# Try ltc_scrypt first (P2Pool module), then fallback to scrypt
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser('~/litecoin_scrypt'))
sys.path.insert(0, script_dir)

USE_LTC_SCRYPT = False
HAS_SCRYPT = False

try:
    import ltc_scrypt
    HAS_SCRYPT = True
    USE_LTC_SCRYPT = True
    print("Using ltc_scrypt module (P2Pool)")
except ImportError:
    try:
        import scrypt
        HAS_SCRYPT = True
        print("Using scrypt module")
    except ImportError:
        print("Warning: scrypt not available, using hashlib (won't match Dogecoin)")

def double_sha256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()

def scrypt_hash(header):
    """Scrypt hash as used by Dogecoin/Litecoin"""
    if USE_LTC_SCRYPT:
        return ltc_scrypt.getPoWHash(header)
    elif HAS_SCRYPT:
        return scrypt.hash(header, header, N=1024, r=1, p=1, buflen=32)
    else:
        return double_sha256(header)

def uint256_from_bytes(b):
    """Convert 32 bytes (little-endian) to integer"""
    return int.from_bytes(b, 'little')

def bytes_from_uint256(n):
    """Convert integer to 32 bytes (little-endian)"""
    return n.to_bytes(32, 'little')

def compact_to_target(bits):
    """Convert compact representation to target"""
    size = bits >> 24
    word = bits & 0x007fffff
    if size <= 3:
        word >>= 8 * (3 - size)
    else:
        word <<= 8 * (size - 3)
    return word

def create_block_header(version, prev_block, merkle_root, timestamp, bits, nonce):
    """Create block header bytes"""
    header = struct.pack('<I', version)  # 4 bytes version
    header += prev_block[::-1]  # 32 bytes prev_block (reversed)
    header += merkle_root[::-1]  # 32 bytes merkle_root (reversed)
    header += struct.pack('<I', timestamp)  # 4 bytes timestamp
    header += struct.pack('<I', bits)  # 4 bytes bits
    header += struct.pack('<I', nonce)  # 4 bytes nonce
    return header

def mine_genesis(timestamp, bits, merkle_root_hex, prev_block_hex="0"*64, start_nonce=0, version=1):
    """Mine a genesis block"""
    target = compact_to_target(bits)
    print(f"Mining genesis block...")
    print(f"  Timestamp: {timestamp} ({time.ctime(timestamp)})")
    print(f"  Bits: 0x{bits:08x}")
    print(f"  Target: {target:064x}")
    print(f"  Merkle root: {merkle_root_hex}")
    print()
    
    prev_block = bytes.fromhex(prev_block_hex)
    merkle_root = bytes.fromhex(merkle_root_hex)
    
    nonce = start_nonce
    start_time = time.time()
    last_print = start_time
    
    while True:
        header = create_block_header(version, prev_block, merkle_root, timestamp, bits, nonce)
        hash_result = scrypt_hash(header)
        hash_int = uint256_from_bytes(hash_result)
        
        if hash_int <= target:
            elapsed = time.time() - start_time
            hash_hex = hash_result[::-1].hex()
            print(f"\n*** GENESIS FOUND! ***")
            print(f"  Nonce: {nonce}")
            print(f"  Hash: {hash_hex}")
            print(f"  Time: {elapsed:.2f} seconds")
            print(f"\nUse these values in chainparams.cpp:")
            print(f"  genesis = CreateGenesisBlock({timestamp}, {nonce}, 0x{bits:08x}, {version}, 88 * COIN);")
            print(f"  assert(consensus.hashGenesisBlock == uint256S(\"0x{hash_hex}\"));")
            return nonce, hash_hex
        
        nonce += 1
        
        if nonce % 100000 == 0:
            now = time.time()
            if now - last_print >= 5:
                rate = nonce / (now - start_time)
                print(f"  Nonce: {nonce:,} ({rate:.0f} H/s)")
                last_print = now
        
        if nonce > 0xFFFFFFFF:
            print("Nonce overflow - increase timestamp and retry")
            return None, None

if __name__ == "__main__":
    # Dogecoin genesis merkle root (same for all Dogecoin chains)
    # From: CreateGenesisBlock with "Nintondo" timestamp
    MERKLE_ROOT = "5b2a3f53f605d62c53e62932dac6925e3d74afa5a4b459745c36d42d0ed26a69"
    
    # Testnet4 parameters
    TIMESTAMP = 1737907200  # Jan 26, 2026 12:00:00 UTC
    BITS = 0x1e0ffff0  # Same as testnet starting difficulty
    
    print("=" * 60)
    print("Dogecoin Testnet4 Genesis Block Miner")
    print("=" * 60)
    print()
    
    nonce, hash_hex = mine_genesis(
        timestamp=TIMESTAMP,
        bits=BITS,
        merkle_root_hex=MERKLE_ROOT,
        start_nonce=0
    )
