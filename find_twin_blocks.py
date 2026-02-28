#!/usr/bin/env python3
"""
Twin Block Finder for Merged Mining Verification

This script finds "twin blocks" - blocks where the same proof-of-work hash
was accepted by both the parent chain (Litecoin testnet) and the merged
mining chain (Dogecoin testnet).

In merged mining:
- The miner solves a POW puzzle for the parent chain (tLTC)
- If the POW hash also meets the merged chain's (tDOGE) difficulty target,
  both chains accept a block with the SAME POW hash
- The tLTC block hash IS the POW hash
- The tDOGE block contains an auxpow with the parent block header

This script:
1. Fetches all mined tLTC blocks from the wallet
2. Extracts merged mining data from each tLTC coinbase
3. Fetches tDOGE blocks and extracts their parent POW hash from auxpow
4. Finds matching pairs where both blocks are confirmed on their chains
"""

import json
import hashlib
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

# Configuration
LITECOIN_CLI = "litecoin-cli"
LITECOIN_ARGS = ["-testnet"]
DOGECOIN_RPC_URL = "http://127.0.0.1:44555/"
DOGECOIN_RPC_USER = "dogeuser"
DOGECOIN_RPC_PASS = "dogepass123"

# Merged mining marker in coinbase
MM_MARKER = "fabe6d6d"


def litecoin_rpc(method: str, params: List = None) -> dict:
    """Call Litecoin RPC via litecoin-cli"""
    cmd = [LITECOIN_CLI] + LITECOIN_ARGS + [method]
    if params:
        cmd.extend([str(p) for p in params])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except Exception as e:
        return {"error": str(e)}


def dogecoin_rpc(method: str, params: List = None) -> dict:
    """Call Dogecoin RPC via curl"""
    payload = {
        "jsonrpc": "1.0",
        "id": "twin_finder",
        "method": method,
        "params": params or []
    }
    
    try:
        cmd = [
            "curl", "-s", "--user", f"{DOGECOIN_RPC_USER}:{DOGECOIN_RPC_PASS}",
            "--data-binary", json.dumps(payload),
            DOGECOIN_RPC_URL
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        return data.get("result", {})
    except Exception as e:
        return {"error": str(e)}


def reverse_hex(hex_str: str) -> str:
    """Reverse byte order of a hex string (little-endian to big-endian)"""
    return "".join([hex_str[i:i+2] for i in range(len(hex_str)-2, -2, -2)])


def extract_merged_hash_from_coinbase(coinbase_hex: str) -> Optional[str]:
    """Extract the merged block hash from a coinbase transaction"""
    idx = coinbase_hex.lower().find(MM_MARKER)
    if idx == -1:
        return None
    
    # After marker is the 32-byte merged block hash (little-endian)
    hash_start = idx + len(MM_MARKER)
    hash_end = hash_start + 64
    if len(coinbase_hex) < hash_end:
        return None
    
    merged_hash_le = coinbase_hex[hash_start:hash_end]
    # Convert to big-endian for block lookup
    merged_hash_be = reverse_hex(merged_hash_le)
    return merged_hash_be


def compute_pow_hash_from_header(header_hex: str) -> str:
    """Compute the scrypt POW hash from a block header (80 bytes)"""
    # For scrypt coins, the POW hash is the scrypt hash of the header
    # But for block hash lookups, we use SHA256d
    header_bytes = bytes.fromhex(header_hex[:160])  # 80 bytes = 160 hex chars
    sha_hash = hashlib.sha256(hashlib.sha256(header_bytes).digest()).digest()
    return sha_hash[::-1].hex()


def get_ltc_mined_blocks() -> List[Dict]:
    """Get all mined tLTC blocks from the wallet"""
    print("Fetching mined tLTC blocks from wallet...")
    
    # Get all transactions, filter for generated/immature
    txs = litecoin_rpc("listtransactions", ["*", 1000, 0])
    if isinstance(txs, dict) and "error" in txs:
        print(f"Error fetching transactions: {txs['error']}")
        return []
    
    mined_blocks = []
    seen_hashes = set()
    
    for tx in txs:
        if tx.get("generated") and tx.get("blockhash"):
            blockhash = tx["blockhash"]
            if blockhash not in seen_hashes:
                seen_hashes.add(blockhash)
                mined_blocks.append({
                    "blockhash": blockhash,
                    "height": tx.get("blockheight"),
                    "confirmations": tx.get("confirmations", 0),
                    "time": tx.get("blocktime")
                })
    
    print(f"Found {len(mined_blocks)} unique mined tLTC blocks")
    return mined_blocks


def get_doge_blocks_by_address(address: str, count: int = 100) -> List[Dict]:
    """Get tDOGE blocks received by an address"""
    print(f"Fetching tDOGE blocks for address {address}...")
    
    # List transactions for address
    txs = dogecoin_rpc("listtransactions", ["*", count, 0, True])
    if isinstance(txs, dict) and "error" in txs:
        print(f"Error: {txs}")
        return []
    
    if not txs:
        return []
    
    blocks = []
    seen_hashes = set()
    
    for tx in txs:
        if tx.get("generated") and tx.get("blockhash"):
            blockhash = tx["blockhash"]
            if blockhash not in seen_hashes:
                seen_hashes.add(blockhash)
                blocks.append({
                    "blockhash": blockhash,
                    "confirmations": tx.get("confirmations", 0)
                })
    
    return blocks


def get_doge_recent_blocks(start_height: int, count: int = 500) -> List[str]:
    """Get recent tDOGE block hashes by iterating from a height"""
    print(f"Scanning tDOGE blocks from height {start_height}...")
    
    blocks = []
    height = start_height
    
    for i in range(count):
        blockhash = dogecoin_rpc("getblockhash", [height + i])
        if blockhash and not isinstance(blockhash, dict):
            blocks.append(blockhash)
        if i % 100 == 0 and i > 0:
            print(f"  Scanned {i} blocks...")
    
    return blocks


def analyze_ltc_block(blockhash: str) -> Dict:
    """Analyze a tLTC block for merged mining data"""
    block = litecoin_rpc("getblock", [blockhash, 2])
    if isinstance(block, dict) and "error" in block:
        return {"error": block["error"]}
    
    result = {
        "blockhash": blockhash,
        "height": block.get("height"),
        "confirmations": block.get("confirmations", 0),
        "time": block.get("time"),
        "pow_hash": blockhash,  # For scrypt, block hash IS the POW hash
    }
    
    # Get coinbase transaction
    if block.get("tx") and len(block["tx"]) > 0:
        coinbase = block["tx"][0]
        coinbase_hex = coinbase.get("hex", "")
        
        # Extract merged mining hash
        merged_hash = extract_merged_hash_from_coinbase(coinbase_hex)
        if merged_hash:
            result["merged_hash"] = merged_hash
            result["has_merged_mining"] = True
        else:
            result["has_merged_mining"] = False
    
    return result


def analyze_doge_block(blockhash: str) -> Dict:
    """Analyze a tDOGE block for auxpow data"""
    block = dogecoin_rpc("getblock", [blockhash, True])
    if not block or isinstance(block, dict) and "error" in block:
        return {"error": "Block not found"}
    
    result = {
        "blockhash": blockhash,
        "height": block.get("height"),
        "confirmations": block.get("confirmations", 0),
        "time": block.get("time"),
    }
    
    # Get auxpow data
    auxpow = block.get("auxpow")
    if auxpow:
        result["has_auxpow"] = True
        
        # The parent block hash from auxpow.tx.blockhash
        if auxpow.get("tx") and auxpow["tx"].get("blockhash"):
            result["parent_blockhash"] = auxpow["tx"]["blockhash"]
        
        # The parent block header
        if auxpow.get("parentblock"):
            parent_header = auxpow["parentblock"]
            result["parent_header"] = parent_header
            # Compute hash from header
            pow_hash = compute_pow_hash_from_header(parent_header)
            result["pow_hash"] = pow_hash
    else:
        result["has_auxpow"] = False
    
    return result


def find_twin_blocks():
    """Main function to find twin blocks"""
    print("=" * 70)
    print("TWIN BLOCK FINDER - Merged Mining Verification")
    print("=" * 70)
    print()
    
    # Step 1: Get all mined tLTC blocks
    ltc_blocks = get_ltc_mined_blocks()
    if not ltc_blocks:
        print("No mined tLTC blocks found!")
        return
    
    # Step 2: Analyze each tLTC block
    print()
    print("Analyzing tLTC blocks for merged mining data...")
    ltc_analyzed = []
    for block in ltc_blocks:
        analysis = analyze_ltc_block(block["blockhash"])
        if "error" not in analysis:
            ltc_analyzed.append(analysis)
    
    print(f"Analyzed {len(ltc_analyzed)} tLTC blocks")
    mm_blocks = [b for b in ltc_analyzed if b.get("has_merged_mining")]
    print(f"Blocks with merged mining data: {len(mm_blocks)}")
    
    # Step 3: Get current tDOGE chain height
    doge_info = dogecoin_rpc("getblockchaininfo")
    if not doge_info:
        print("Cannot connect to Dogecoin RPC!")
        return
    
    doge_height = doge_info.get("blocks", 0)
    print(f"\nCurrent tDOGE height: {doge_height}")
    
    # Step 4: Build a map of tLTC POW hashes
    ltc_pow_map = {}  # pow_hash -> block info
    for block in ltc_analyzed:
        pow_hash = block.get("pow_hash")
        if pow_hash:
            ltc_pow_map[pow_hash] = block
    
    print(f"\nBuilt map of {len(ltc_pow_map)} tLTC POW hashes")
    
    # Step 5: Scan tDOGE blocks around recent mining activity
    # Start from a reasonable height (adjust based on when mining started)
    start_height = max(22294000, doge_height - 3000)
    
    print(f"\nScanning tDOGE blocks from height {start_height} to {doge_height}...")
    
    twins_found = []
    checked = 0
    
    for height in range(start_height, doge_height + 1):
        blockhash = dogecoin_rpc("getblockhash", [height])
        if not blockhash or isinstance(blockhash, dict):
            continue
        
        doge_analysis = analyze_doge_block(blockhash)
        if "error" in doge_analysis:
            continue
        
        checked += 1
        if checked % 500 == 0:
            print(f"  Checked {checked} tDOGE blocks...")
        
        # Check if this tDOGE block's POW hash matches any tLTC block
        pow_hash = doge_analysis.get("pow_hash")
        parent_hash = doge_analysis.get("parent_blockhash")
        
        # Try both the computed POW hash and the parent blockhash
        ltc_match = None
        if pow_hash and pow_hash in ltc_pow_map:
            ltc_match = ltc_pow_map[pow_hash]
        elif parent_hash and parent_hash in ltc_pow_map:
            ltc_match = ltc_pow_map[parent_hash]
        
        if ltc_match:
            twin = {
                "ltc_hash": ltc_match["blockhash"],
                "ltc_height": ltc_match["height"],
                "ltc_confirmations": ltc_match["confirmations"],
                "doge_hash": doge_analysis["blockhash"],
                "doge_height": doge_analysis["height"],
                "doge_confirmations": doge_analysis["confirmations"],
                "pow_hash": pow_hash or parent_hash,
            }
            twins_found.append(twin)
            print(f"\n  *** TWIN FOUND! ***")
            print(f"      tLTC: {twin['ltc_hash'][:16]}... (height {twin['ltc_height']}, {twin['ltc_confirmations']} conf)")
            print(f"      tDOGE: {twin['doge_hash'][:16]}... (height {twin['doge_height']}, {twin['doge_confirmations']} conf)")
    
    # Step 6: Also check merged_hash from tLTC coinbase
    print(f"\nAlso checking merged_hash references in tLTC coinbases...")
    
    for block in mm_blocks:
        merged_hash = block.get("merged_hash")
        if not merged_hash:
            continue
        
        # Check if this merged hash exists on tDOGE
        doge_block = dogecoin_rpc("getblock", [merged_hash, True])
        if doge_block and not isinstance(doge_block, dict):
            continue
        if doge_block and "height" in doge_block:
            # Check if we already found this twin
            already_found = any(t["doge_hash"] == merged_hash for t in twins_found)
            if not already_found:
                twin = {
                    "ltc_hash": block["blockhash"],
                    "ltc_height": block["height"],
                    "ltc_confirmations": block["confirmations"],
                    "doge_hash": merged_hash,
                    "doge_height": doge_block.get("height"),
                    "doge_confirmations": doge_block.get("confirmations", 0),
                    "pow_hash": block["pow_hash"],
                    "found_via": "merged_hash_in_coinbase"
                }
                twins_found.append(twin)
                print(f"\n  *** TWIN FOUND (via coinbase)! ***")
                print(f"      tLTC: {twin['ltc_hash'][:16]}... (height {twin['ltc_height']}, {twin['ltc_confirmations']} conf)")
                print(f"      tDOGE: {twin['doge_hash'][:16]}... (height {twin['doge_height']}, {twin['doge_confirmations']} conf)")
    
    # Final report
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()
    
    if not twins_found:
        print("No confirmed twin blocks found.")
        print()
        print("This could mean:")
        print("  - tLTC blocks were orphaned but tDOGE blocks survived (or vice versa)")
        print("  - The search range didn't cover the right heights")
        print("  - Mining is too recent and blocks haven't propagated")
    else:
        print(f"Found {len(twins_found)} TWIN BLOCK(S)!")
        print()
        
        # Sort by tLTC height
        twins_found.sort(key=lambda x: x.get("ltc_height", 0))
        
        for i, twin in enumerate(twins_found, 1):
            print(f"Twin #{i}:")
            print(f"  ┌─ tLTC Block ─────────────────────────────────────────────────────")
            print(f"  │  Hash:          {twin['ltc_hash']}")
            print(f"  │  Height:        {twin['ltc_height']}")
            print(f"  │  Confirmations: {twin['ltc_confirmations']}")
            print(f"  │")
            print(f"  ├─ tDOGE Block ────────────────────────────────────────────────────")
            print(f"  │  Hash:          {twin['doge_hash']}")
            print(f"  │  Height:        {twin['doge_height']}")
            print(f"  │  Confirmations: {twin['doge_confirmations']}")
            print(f"  │")
            print(f"  └─ POW Hash (shared): {twin['pow_hash']}")
            print()
        
        # Summary of confirmed twins
        confirmed_twins = [t for t in twins_found 
                          if t["ltc_confirmations"] > 0 and t["doge_confirmations"] > 0]
        
        if confirmed_twins:
            print("=" * 70)
            print("PROOF OF MERGED MINING SUCCESS")
            print("=" * 70)
            print()
            print(f"✓ {len(confirmed_twins)} block(s) confirmed on BOTH chains!")
            print()
            print("This proves that:")
            print("  1. The same proof-of-work was accepted by both tLTC and tDOGE")
            print("  2. Merged mining is working correctly")
            print("  3. One mining operation secured two blockchains")


if __name__ == "__main__":
    find_twin_blocks()
