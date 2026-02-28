"""
Helper functions for merged mining with multiaddress coinbase support

This module provides utilities for building merged mining blocks with
multiaddress coinbase transactions, allowing proportional payouts to
multiple miners on merged chains (e.g., Dogecoin).

IMPORTANT: gentx_before_refhash (data.py) is for PARENT chain (Litecoin) shares.
Merged chain blocks (Dogecoin) need their OWN coinbase with donation/OP_RETURN!
"""

import sys
from p2pool.bitcoin import data as bitcoin_data
from p2pool.bitcoin import script
from p2pool.util import pack
from p2pool import data as p2pool_data

# Debug flag - set to True to enable verbose coinbase building output
DEBUG_COINBASE = False

# ============================================================================
# MERGED CHAIN DONATION SCRIPTS
# ============================================================================
# These mirror the parent chain donation system (data.py) for merged mining.
# Raw scripts are chain-agnostic (P2PK, P2PKH, redeem scripts).
#
# V36: Full donation to COMBINED (P2SH-wrapped 1-of-2 P2MS redeem script).
# ============================================================================

# PRIMARY_DONATION_SCRIPT: Original P2Pool donation (forrestv, P2PK format)
# Same raw script as data.py DONATION_SCRIPT - chain-agnostic
# P2PK: 0x41 <65-byte uncompressed pubkey> 0xac (OP_CHECKSIG)
# Kept for fallback if V36 is not active.
PRIMARY_DONATION_SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')

# COMBINED_DONATION_REDEEM_SCRIPT: 1-of-2 P2MS redeem script (V36+)
COMBINED_DONATION_REDEEM_SCRIPT = '512103ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d12102fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a52ae'.decode('hex')

# COMBINED_DONATION_SCRIPT: P2SH-wrapped scriptPubKey for COMBINED_DONATION_REDEEM_SCRIPT
COMBINED_DONATION_SCRIPT = 'a9148c6272621d89e8fa526dd86acff60c7136be8e8587'.decode('hex')

# Default donation script alias (points to combined P2SH)
DONATION_SCRIPT = COMBINED_DONATION_SCRIPT

# DONATION MARKER MONITORING MEMO (merged chain coinbase):
# - Pre-V36 monitor output paying PRIMARY_DONATION_SCRIPT address on merged chain
# - Post-V36 monitor output paying COMBINED_DONATION_SCRIPT-derived P2SH address
#   (derive with script2_to_address using merged chain ADDRESS_P2SH_VERSION)
# - Dogecoin mainnet pre-V36  : DQ8AwqR2XJE9G5dSEfspJYH7Spre85dj6L
# - Dogecoin mainnet post-V36 : A5EZCT4tUrtoKuvJaWbtVQADzdUKdtsqpr
# - Dogecoin testnet pre-V36  : noBEfr9wTGgs94CdGVXGYwsQghEwBsXw4K
# - Dogecoin testnet post-V36 : 2N63WXLw22FXFdLBNqWZLsDX7WQJTPXus7f
# Parent-chain example for same post-V36 script hash (different version bytes):
#   Litecoin mainnet post-V36 : MLhSmVQxMusLE3pjGFvp4unFckgjeD8LUA

# P2Pool merged mining identifier for OP_RETURN
P2POOL_TAG = 'technocore'


def build_coinbase_input_script(height, extradata=''):
    """
    Build coinbase input script with block height (BIP 34)
    
    Uses the same method as parent chain coinbase (script.create_push_script)
    
    Args:
        height: Block height (integer)
        extradata: Optional extra data to include
    
    Returns:
        Packed script bytes
    """
    # Use the same method as parent chain - this is already tested and working
    script_bytes = script.create_push_script([height])
    if extradata:
        script_bytes += extradata
    
    return script_bytes


def build_merged_coinbase(template, shareholders, net, donation_percentage=1.0, node_owner_address=None, node_owner_fee=0, parent_net=None, coinbase_text=None, v36_active=False, finder_address=None, finder_fee_percentage=0.5, **kwargs):
    """
    Build coinbase transaction for MERGED CHAIN (Dogecoin) with multiple outputs
    
    This is SEPARATE from parent chain (Litecoin) coinbase!
    Parent chain uses gentx_before_refhash. Merged chain needs its own structure.
    
    Includes:
    - Miner outputs (proportional to shares, after fees)
    - OP_RETURN tag (identifies merged P2Pool blocks on Dogecoin chain)
    - P2Pool donation (configurable %, always present as blockchain marker)
    
    DONATION SYSTEM:
    Always uses COMBINED_DONATION_SCRIPT (P2SH-wrapped 1-of-2 P2MS redeem script).
    Either party can spend independently via the redeem script.
    
    ADDRESS CONVERSION:
    Shareholder addresses are auto-converted from pubkey_hash stored in share chain.
    If a parent chain address is provided (e.g., LTC), it will be automatically
    converted to the merged chain address by extracting the pubkey_hash and
    re-encoding with the merged chain's ADDRESS_VERSION.
    
    Note: node_owner_address and node_owner_fee are accepted for backward
    compatibility but are ignored — merged chain payouts always use PPLNS
    distribution. Node operator economics come from the -f probabilistic
    address replacement in share_data, which flows through PPLNS weights.
    
    Args:
        template: Block template from getblocktemplate (with auxpow)
        shareholders: Dict of {address: fraction} OR {address: (fraction, net_obj)}
                     Addresses can be in parent chain format - will be auto-converted
        net: Merged chain network object (e.g., Dogecoin testnet)
        donation_percentage: Donation percentage (0-100, default 1.0 for 1%)
        parent_net: Parent chain network object (e.g., Litecoin testnet) for address conversion
        coinbase_text: Custom text for OP_RETURN (default: P2POOL_TAG constant)
        v36_active: Whether V36 share version is active (95%+ signaling)
    
    Returns:
        Dict representing the coinbase transaction
    """
    # node_owner_address and node_owner_fee are forced to zero/None — merged
    # chain always relies on PPLNS distribution, never per-block node fees.
    node_owner_address = None
    node_owner_fee = 0
    legacy_node_operator_address = kwargs.pop('node_operator_address', None)
    legacy_worker_fee = kwargs.pop('worker_fee', None)
    if kwargs:
        raise TypeError('Unexpected keyword argument(s): %s' % ', '.join(sorted(kwargs.keys())))

    total_reward = template['coinbasevalue']
    height = template['height']
    
    # Calculate fees from total reward
    # Order: donation first, then worker fee, then miners split the rest
    #
    # DONATION: Always COMBINED_DONATION_SCRIPT (1-of-2 P2MS).
    # Only V36 nodes build merged coinbases, so v36_active is irrelevant here.
    # Either party can spend independently.
    #
    # The donation/marker output MUST always carry a nonzero value (at least dust
    # threshold) so the output is standard and identifiable on-chain.
    donation_script = COMBINED_DONATION_SCRIPT
    donation_amount = int(total_reward * donation_percentage / 100)
    if DEBUG_COINBASE:
        print >>sys.stderr, '[MERGED COINBASE] Using COMBINED_DONATION_SCRIPT (1-of-2 P2MS)'
    
    # Ensure minimum dust for marker output (like parent chain rounding remainder)
    # Use the merged chain's DUST_THRESHOLD if available, else 1e8 (1 coin)
    dust_threshold = getattr(net, 'DUST_THRESHOLD', int(1e8))
    if donation_amount < dust_threshold and total_reward > dust_threshold:
        donation_amount = dust_threshold
    
    node_owner_fee_amount = 0  # Always 0: merged chain relies on PPLNS distribution
    finder_fee_amount = int(total_reward * finder_fee_percentage / 100) if finder_fee_percentage > 0 and finder_address else 0
    miners_reward = total_reward - donation_amount - finder_fee_amount
    
    if DEBUG_COINBASE:
        print >>sys.stderr, '[MERGED COINBASE] Total reward: %d satoshis' % total_reward
        print >>sys.stderr, '[MERGED COINBASE] - Donation/marker (%.1f%%): %d (dust_threshold=%d)' % (donation_percentage, donation_amount, dust_threshold)
        print >>sys.stderr, '[MERGED COINBASE] - Finder fee (%.1f%%): %d' % (finder_fee_percentage, finder_fee_amount)
        print >>sys.stderr, '[MERGED COINBASE] - Miners (%.1f%%): %d' % (
            100 - donation_percentage - finder_fee_percentage, miners_reward)
        print >>sys.stderr, '[MERGED COINBASE] Building for %d shareholders' % len(shareholders)
    
    # Build outputs for each shareholder (from miners_reward after fees)
    tx_outs = []
    output_index_by_script = {}
    total_distributed = 0

    def append_or_coalesce_output(script2, amount):
        if amount <= 0:
            return
        existing_index = output_index_by_script.get(script2)
        if existing_index is None:
            output_index_by_script[script2] = len(tx_outs)
            tx_outs.append({
                'value': amount,
                'script': script2,
            })
        else:
            tx_outs[existing_index]['value'] += amount
    
    for address, value in shareholders.iteritems():
        # Handle both old format (address: fraction) and new format (address: (fraction, net))
        if isinstance(value, tuple):
            fraction, addr_net = value
        else:
            fraction = value
            addr_net = net  # Use the passed merged chain network directly
        
        amount = int(miners_reward * fraction)
        total_distributed += amount
        
        if amount > 0:  # Skip dust outputs
            # MERGED: prefix = raw hex-encoded script from get_v36_merged_weights().
            # These are already valid merged-chain scriptPubKeys (P2PKH, P2SH, etc.)
            # stored in shares' merged_addresses field. Use directly — no address
            # conversion needed (and conversion may fail for P2SH scripts).
            if address.startswith('MERGED:'):
                script2 = address[7:].decode('hex')
                append_or_coalesce_output(script2, amount)
                if DEBUG_COINBASE:
                    print >>sys.stderr, '[MINER PAYOUT] MERGED:%s...: %d satoshis (%.1f%% of %.1f%%) [raw script]' % (
                        address[7:21], amount, fraction * 100, 100 - donation_percentage - finder_fee_percentage)
                continue
            try:
                # First try: address is already in merged chain format
                script2 = bitcoin_data.address_to_script2(address, addr_net)
                append_or_coalesce_output(script2, amount)
                if DEBUG_COINBASE:
                    print >>sys.stderr, '[MINER PAYOUT] %s: %d satoshis (%.1f%% of %.1f%%)' % (
                        address[:20] + '...', amount, fraction * 100, 100 - donation_percentage - finder_fee_percentage)
            except ValueError as e:
                # Second try: address might be in parent chain format - convert it
                if parent_net is not None:
                    try:
                        # Extract pubkey_hash from parent chain address
                        pubkey_hash_info = bitcoin_data.address_to_pubkey_hash(address, parent_net)
                        pubkey_hash = pubkey_hash_info[0]
                        version = pubkey_hash_info[1]
                        
                        # Re-encode with appropriate merged chain address version
                        if version == parent_net.ADDRESS_P2SH_VERSION:
                            # P2SH: re-encode with merged chain P2SH version
                            converted_address = bitcoin_data.pubkey_hash_to_address(
                                pubkey_hash, addr_net.ADDRESS_P2SH_VERSION, -1, addr_net)
                        else:
                            # P2PKH (or bech32 P2WPKH): re-encode with merged chain P2PKH version
                            converted_address = bitcoin_data.pubkey_hash_to_address(
                                pubkey_hash, addr_net.ADDRESS_VERSION, -1, addr_net)
                        
                        script2 = bitcoin_data.address_to_script2(converted_address, addr_net)
                        append_or_coalesce_output(script2, amount)
                        if DEBUG_COINBASE:
                            print >>sys.stderr, '[MINER PAYOUT] %s -> %s: %d satoshis (%.1f%% of %.1f%%) [auto-converted from parent chain]' % (
                                address[:15] + '...', converted_address[:15] + '...', amount, fraction * 100, 100 - donation_percentage - finder_fee_percentage)
                    except Exception as conv_e:
                        print >>sys.stderr, 'Warning: Failed to decode/convert address %s: %s (original: %s)' % (address, conv_e, e)
                else:
                    print >>sys.stderr, 'Warning: Failed to decode address %s: %s (no parent_net for conversion)' % (address, e)
    
    # Add finder fee output (if configured)
    if finder_fee_amount > 0 and finder_address:
        try:
            finder_script = bitcoin_data.address_to_script2(finder_address, net)
            append_or_coalesce_output(finder_script, finder_fee_amount)
            if DEBUG_COINBASE:
                print >>sys.stderr, '[FINDER FEE] %s: %d satoshis (%.1f%%)' % (
                    finder_address[:20] + '...', finder_fee_amount, finder_fee_percentage)
        except ValueError as e:
            if parent_net is not None:
                try:
                    pubkey_hash_info = bitcoin_data.address_to_pubkey_hash(finder_address, parent_net)
                    pubkey_hash = pubkey_hash_info[0]
                    converted_address = bitcoin_data.pubkey_hash_to_address(
                        pubkey_hash, net.ADDRESS_VERSION, -1, net)
                    finder_script = bitcoin_data.address_to_script2(converted_address, net)
                    append_or_coalesce_output(finder_script, finder_fee_amount)
                    if DEBUG_COINBASE:
                        print >>sys.stderr, '[FINDER FEE] %s -> %s: %d satoshis (%.1f%%) [auto-converted from parent chain]' % (
                            finder_address[:15] + '...', converted_address[:15] + '...', finder_fee_amount, finder_fee_percentage)
                except Exception as conv_e:
                    print >>sys.stderr, 'Warning: Failed to decode/convert finder address %s: %s (original: %s)' % (
                        finder_address, conv_e, e)
                    print >>sys.stderr, '         Skipping finder fee output.'
            else:
                print >>sys.stderr, 'Warning: Failed to decode finder address %s for merged chain: %s' % (finder_address, e)
                print >>sys.stderr, '         Skipping finder fee output.'
    
    # Add OP_RETURN output with pool identifier (0 value, data only)
    # This marks the block as pool-mined on the DOGECOIN blockchain
    # Use custom coinbase_text if provided, otherwise fall back to default P2POOL_TAG
    op_return_text = coinbase_text if coinbase_text else P2POOL_TAG
    # CRITICAL: Ensure op_return_text is bytes (str), not unicode.
    # When coinbase_text comes from JSON (mm-adapter), it's unicode in Python 2.
    # Concatenating unicode with byte literals like '\x6a' produces unicode,
    # which later causes StringIO unicode/bytes mixing when packing transactions
    # (e.g., previous_output index 0xffffffff bytes can't be ASCII-decoded).
    if isinstance(op_return_text, unicode):
        op_return_text = op_return_text.encode('utf-8')
    op_return_script = '\x6a' + chr(len(op_return_text)) + op_return_text  # OP_RETURN + length + data
    tx_outs.append({
        'value': 0,
        'script': op_return_script,
    })
    if DEBUG_COINBASE:
        print >>sys.stderr, '[OP_RETURN] Added pool identifier to merged block: "%s"' % op_return_text
    
    # Add P2Pool donation output (ALWAYS included as blockchain marker)
    # Even if donation_percentage=0, this output marks every block as P2Pool-mined
    # This is equivalent to gentx_before_refhash on parent chain
    #
    # Always COMBINED_DONATION_SCRIPT (P2SH-wrapped 1-of-2 P2MS) — full amount
    #
    # Collect rounding remainder from miner distribution (like parent chain).
    # Integer truncation in amount = int(miners_reward * fraction) means
    # total_distributed < miners_reward. That remainder goes to the marker.
    rounding_remainder = miners_reward - total_distributed
    final_donation = donation_amount + rounding_remainder
    
    tx_outs.append({
        'value': final_donation,
        'script': donation_script,
    })
    
    if DEBUG_COINBASE:
        print >>sys.stderr, '[DONATION] P2Pool marker/donation to COMBINED (P2SH-wrapped 1-of-2 P2MS): %d satoshis (%.1f%% + %d rounding)' % (
            final_donation, donation_percentage, rounding_remainder)
        print >>sys.stderr, '[MERGED COINBASE] Total outputs after coalescing (incl OP_RETURN + donation marker): %d' % (
            len(tx_outs),)
    
    # If no valid outputs, create a single output to a default address
    # (This should never happen in normal operation)
    if not tx_outs:
        print >>sys.stderr, 'ERROR: No valid shareholder outputs, merged mining will fail!'
        # Create dummy output to prevent transaction from being invalid
        tx_outs.append({
            'value': total_reward,
            'script': '\x76\xa9\x14' + '\x00' * 20 + '\x88\xac',  # OP_DUP OP_HASH160 <zeros> OP_EQUALVERIFY OP_CHECKSIG
        })
    
    # Build coinbase transaction
    # Note: For coinbase, use None for previous_output and sequence
    # PossiblyNoneType will encode them properly during serialization
    coinbase_tx = {
        'version': 1,
        'tx_ins': [{
            'previous_output': None,  # Will be encoded as dict(hash=0, index=2**32-1)
            'sequence': None,  # Will be encoded as 0xffffffff
            'script': build_coinbase_input_script(height, '/P2Pool-Scrypt/'),
        }],
        'tx_outs': tx_outs,
        'lock_time': 0,
    }
    
    return coinbase_tx


def build_merged_block(template, coinbase_tx, auxpow_proof, parent_block_header, merkle_link_to_parent):
    """
    Build complete merged mining block with auxpow
    
    Args:
        template: Block template from getblocktemplate
        coinbase_tx: Coinbase transaction dict
        auxpow_proof: Dict with merkle_tx, merkle_link, parent_block_header for auxpow
        parent_block_header: Parent chain (Litecoin) block header
        merkle_link_to_parent: Merkle link from coinbase to parent block
    
    Returns:
        Complete block dict ready for packing and submitblock
    """
    # Collect all transaction hashes for merkle root calculation
    # Start with coinbase transaction (packed)
    coinbase_packed = bitcoin_data.tx_type.pack(coinbase_tx)
    tx_hashes = [bitcoin_data.hash256(coinbase_packed)]
    
    # Collect both hashes and unpacked txs (needed for block packing later)
    tx_list = [coinbase_tx]
    
    # Add transactions from template
    for tx in template.get('transactions', []):
        # Transactions in template are hex-encoded raw format
        tx_data = tx['data'].decode('hex')
        # Calculate hash directly from raw data
        tx_hashes.append(bitcoin_data.hash256(tx_data))
        # Unpack for including in block
        tx_unpacked = bitcoin_data.tx_type.unpack(tx_data)
        tx_list.append(tx_unpacked)
    
    # Calculate merkle root from transaction hashes
    merkle_root = bitcoin_data.merkle_hash(tx_hashes)
    
    # Debug bits unpacking
    bits_hex = template['bits']
    bits_bytes = bits_hex.decode('hex')
    bits_reversed = bits_bytes[::-1]
    print >>sys.stderr, '[DEBUG merged_mining] Dogecoin template bits=%s' % bits_hex
    print >>sys.stderr, '[DEBUG merged_mining] Bits bytes=%s, reversed=%s' % (bits_bytes.encode('hex'), bits_reversed.encode('hex'))
    
    # Build block header
    # NOTE: Bits field needs byte reversal! Dogecoin getblocktemplate returns bits in 
    # big-endian hex format but the header expects little-endian uint32
    header = {
        'version': template['version'],
        'previous_block': int(template['previousblockhash'], 16),
        'merkle_root': merkle_root,
        'timestamp': template['curtime'],
        'bits': bitcoin_data.FloatingIntegerType().unpack(bits_reversed),
        'nonce': parent_block_header['nonce'],  # Use nonce from parent chain
    }
    
    print >>sys.stderr, '[DEBUG merged_mining] Created FloatingInteger: %r' % header['bits']
    print >>sys.stderr, '[DEBUG merged_mining] FloatingInteger.bits (raw 32-bit): 0x%08x' % header['bits'].bits
    
    # Build complete block with auxpow
    # Note: For multiaddress merged mining, we need to submit via submitauxblock or submitblock
    # The block structure includes the auxpow proof
    block = {
        'header': header,
        'txs': tx_list,
    }
    
    return block, auxpow_proof


def calculate_shareholder_fractions(tracker, min_payout=1000000):
    """
    Calculate payout fractions from share chain tracker
    
    Args:
        tracker: ShareTracker object with recent shares
        min_payout: Minimum payout amount in satoshis (to avoid dust)
    
    Returns:
        Dict of {address: fraction} where fractions sum to 1.0
    """
    # This is a placeholder - actual implementation will integrate with
    # P2Pool's share chain tracking
    
    # For now, return empty dict (will use getauxblock fallback)
    return {}
