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

# P2Pool author donation script (1% of merged mining blocks)
# This is SEPARATE from the parent chain donation
# P2PKH format - Dash address: XdgF55wEHBRWwbuBniNYH4GvvaoYMgL84u
# Format: OP_DUP OP_HASH160 <20-byte pubkey_hash> OP_EQUALVERIFY OP_CHECKSIG
DONATION_SCRIPT = '76a91420cb5c22b1e4d5947e5c112c7696b51ad9af3c6188ac'.decode('hex')

# P2Pool merged mining identifier for OP_RETURN
P2POOL_TAG = 'P2Pool merged mining'


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


def build_merged_coinbase(template, shareholders, net, donation_percentage=1.0, node_operator_address=None, worker_fee=0, parent_net=None, coinbase_text=None):
    """
    Build coinbase transaction for MERGED CHAIN (Dogecoin) with multiple outputs
    
    This is SEPARATE from parent chain (Litecoin) coinbase!
    Parent chain uses gentx_before_refhash. Merged chain needs its own structure.
    
    Includes:
    - Miner outputs (proportional to shares, after fees)
    - Node operator fee (if worker_fee > 0 and node_operator_address provided)
    - OP_RETURN tag (identifies merged P2Pool blocks on Dogecoin chain)
    - P2Pool donation (configurable %, always present as blockchain marker)
    
    ADDRESS CONVERSION:
    Shareholder addresses are auto-converted from pubkey_hash stored in share chain.
    If a parent chain address is provided (e.g., LTC), it will be automatically
    converted to the merged chain address by extracting the pubkey_hash and
    re-encoding with the merged chain's ADDRESS_VERSION.
    
    Args:
        template: Block template from getblocktemplate (with auxpow)
        shareholders: Dict of {address: fraction} OR {address: (fraction, net_obj)}
                     Addresses can be in parent chain format - will be auto-converted
        net: Merged chain network object (e.g., Dogecoin testnet)
        donation_percentage: Donation percentage (0-100, default 1.0 for 1%)
        node_operator_address: Address of P2Pool node operator (for worker_fee)
        worker_fee: Node operator fee percentage (0-100, default 0)
        parent_net: Parent chain network object (e.g., Litecoin testnet) for address conversion
        coinbase_text: Custom text for OP_RETURN (default: P2POOL_TAG constant)
        parent_net: Parent chain network object (e.g., Litecoin testnet) for address conversion
    
    Returns:
        Dict representing the coinbase transaction
    """
    total_reward = template['coinbasevalue']
    height = template['height']
    
    # Calculate fees from total reward
    # Order: donation first, then worker fee, then miners split the rest
    donation_amount = int(total_reward * donation_percentage / 100)
    worker_fee_amount = int(total_reward * worker_fee / 100) if worker_fee > 0 and node_operator_address else 0
    miners_reward = total_reward - donation_amount - worker_fee_amount
    
    print >>sys.stderr, '[MERGED COINBASE] Total reward: %d satoshis' % total_reward
    print >>sys.stderr, '[MERGED COINBASE] - Donation (%.1f%%): %d' % (donation_percentage, donation_amount)
    print >>sys.stderr, '[MERGED COINBASE] - Node fee (%.1f%%): %d' % (worker_fee, worker_fee_amount)
    print >>sys.stderr, '[MERGED COINBASE] - Miners (%.1f%%): %d' % (
        100 - donation_percentage - worker_fee, miners_reward)
    print >>sys.stderr, '[MERGED COINBASE] Building for %d shareholders' % len(shareholders)
    
    # Build outputs for each shareholder (from miners_reward after fees)
    tx_outs = []
    total_distributed = 0
    
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
            try:
                # First try: address is already in merged chain format
                script2 = bitcoin_data.address_to_script2(address, addr_net)
                tx_outs.append({
                    'value': amount,
                    'script': script2,
                })
                print >>sys.stderr, '[MINER PAYOUT] %s: %d satoshis (%.1f%% of %.1f%%)' % (
                    address[:20] + '...', amount, fraction * 100, 100 - donation_percentage - worker_fee)
            except ValueError as e:
                # Second try: address might be in parent chain format - convert it
                if parent_net is not None:
                    try:
                        # Extract pubkey_hash from parent chain address
                        pubkey_hash_info = bitcoin_data.address_to_pubkey_hash(address, parent_net)
                        pubkey_hash = pubkey_hash_info[0]
                        
                        # Re-encode with merged chain address version
                        converted_address = bitcoin_data.pubkey_hash_to_address(
                            pubkey_hash, addr_net.ADDRESS_VERSION, -1, addr_net)
                        
                        script2 = bitcoin_data.address_to_script2(converted_address, addr_net)
                        tx_outs.append({
                            'value': amount,
                            'script': script2,
                        })
                        print >>sys.stderr, '[MINER PAYOUT] %s -> %s: %d satoshis (%.1f%% of %.1f%%) [auto-converted from parent chain]' % (
                            address[:15] + '...', converted_address[:15] + '...', amount, fraction * 100, 100 - donation_percentage - worker_fee)
                    except Exception as conv_e:
                        print >>sys.stderr, 'Warning: Failed to decode/convert address %s: %s (original: %s)' % (address, conv_e, e)
                else:
                    print >>sys.stderr, 'Warning: Failed to decode address %s: %s (no parent_net for conversion)' % (address, e)
    
    # Add node operator fee output (if configured)
    if worker_fee_amount > 0 and node_operator_address:
        try:
            # First try: address is already in merged chain format
            node_script = bitcoin_data.address_to_script2(node_operator_address, net)
            tx_outs.append({
                'value': worker_fee_amount,
                'script': node_script,
            })
            print >>sys.stderr, '[NODE FEE] %s: %d satoshis (%.1f%%)' % (
                node_operator_address[:20] + '...', worker_fee_amount, worker_fee)
        except ValueError as e:
            # Second try: address might be in parent chain format - convert it
            if parent_net is not None:
                try:
                    # Extract pubkey_hash from parent chain address
                    pubkey_hash_info = bitcoin_data.address_to_pubkey_hash(node_operator_address, parent_net)
                    pubkey_hash = pubkey_hash_info[0]
                    
                    # Re-encode with merged chain address version
                    converted_address = bitcoin_data.pubkey_hash_to_address(
                        pubkey_hash, net.ADDRESS_VERSION, -1, net)
                    
                    node_script = bitcoin_data.address_to_script2(converted_address, net)
                    tx_outs.append({
                        'value': worker_fee_amount,
                        'script': node_script,
                    })
                    print >>sys.stderr, '[NODE FEE] %s -> %s: %d satoshis (%.1f%%) [auto-converted from parent chain]' % (
                        node_operator_address[:15] + '...', converted_address[:15] + '...', worker_fee_amount, worker_fee)
                except Exception as conv_e:
                    print >>sys.stderr, 'Warning: Failed to decode/convert node operator address %s: %s (original: %s)' % (
                        node_operator_address, conv_e, e)
                    print >>sys.stderr, '         Skipping node operator fee.'
            else:
                print >>sys.stderr, 'Warning: Failed to decode node operator address %s for merged chain: %s' % (node_operator_address, e)
                print >>sys.stderr, '         Skipping node operator fee. Check --merged-operator-address matches merged chain network.'
    
    # Add OP_RETURN output with pool identifier (0 value, data only)
    # This marks the block as pool-mined on the DOGECOIN blockchain
    # Use custom coinbase_text if provided, otherwise fall back to default P2POOL_TAG
    op_return_text = coinbase_text if coinbase_text else P2POOL_TAG
    op_return_script = '\x6a' + chr(len(op_return_text)) + op_return_text  # OP_RETURN + length + data
    tx_outs.append({
        'value': 0,
        'script': op_return_script,
    })
    print >>sys.stderr, '[OP_RETURN] Added pool identifier to merged block: "%s"' % op_return_text
    
    # Add P2Pool author donation output (ALWAYS included as blockchain marker)
    # Even if donation_percentage=0, this output marks every block as P2Pool-mined
    # This is equivalent to gentx_before_refhash on parent chain
    tx_outs.append({
        'value': donation_amount,
        'script': DONATION_SCRIPT,
    })
    
    print >>sys.stderr, '[DONATION] Added P2Pool marker/donation to merged block: %d satoshis (%.1f%%)' % (
        donation_amount, donation_percentage)
    print >>sys.stderr, '[MERGED COINBASE] Total outputs: %d (miners) + 1 (OP_RETURN) + 1 (donation marker) = %d' % (
        len(tx_outs) - 2, len(tx_outs))
    
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
