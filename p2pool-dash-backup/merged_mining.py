"""
Helper functions for merged mining with multiaddress coinbase support

This module provides utilities for building merged mining blocks with
multiaddress coinbase transactions, allowing proportional payouts to
multiple miners on merged chains (e.g., Dogecoin).
"""

from p2pool.dash import data as dash_data
from p2pool.util import pack


def build_coinbase_input_script(height, extradata=''):
    """
    Build coinbase input script with block height (BIP 34)
    
    Args:
        height: Block height (integer)
        extradata: Optional extra data to include
    
    Returns:
        Packed script bytes
    """
    # Encode height as compact size (BIP 34 requirement)
    height_bytes = pack.IntType(32).pack(height)
    # Remove leading zero bytes
    while len(height_bytes) > 1 and height_bytes[0] == '\x00':
        height_bytes = height_bytes[1:]
    
    script_bytes = chr(len(height_bytes)) + height_bytes
    if extradata:
        script_bytes += extradata
    
    return script_bytes


def build_merged_coinbase(template, shareholders, net):
    """
    Build coinbase transaction with multiple outputs for merged mining
    
    Args:
        template: Block template from getblocktemplate (with auxpow)
        shareholders: Dict of {address: fraction} where fractions sum to ~1.0
        net: Network object
    
    Returns:
        Dict representing the coinbase transaction
    """
    total_reward = template['coinbasevalue']
    height = template['height']
    
    # Build outputs for each shareholder
    tx_outs = []
    for address, fraction in shareholders.iteritems():
        amount = int(total_reward * fraction)
        if amount > 0:  # Skip dust outputs
            try:
                # Use existing dash_data.address_to_script2 function
                script2 = dash_data.address_to_script2(address, net)
                tx_outs.append({
                    'value': amount,
                    'script': script2,
                })
            except ValueError as e:
                print 'Warning: Failed to decode address %s: %s' % (address, e)
    
    # If no valid outputs, create a single output to a default address
    # (This should never happen in normal operation)
    if not tx_outs:
        print 'ERROR: No valid shareholder outputs, merged mining will fail!'
        # Create dummy output to prevent transaction from being invalid
        tx_outs.append({
            'value': total_reward,
            'script': '\x76\xa9\x14' + '\x00' * 20 + '\x88\xac',  # OP_DUP OP_HASH160 <zeros> OP_EQUALVERIFY OP_CHECKSIG
        })
    
    # Build coinbase transaction
    coinbase_tx = {
        'version': 1,
        'tx_ins': [{
            'previous_output': None,  # Coinbase marker
            'sequence': 0xffffffff,
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
    # Collect all transactions (coinbase first, then template transactions)
    tx_list = [coinbase_tx]
    
    # Add transactions from template
    for tx in template.get('transactions', []):
        # Transactions in template are hex-encoded, need to unpack them
        tx_data = tx['data'].decode('hex')
        tx_unpacked = dash_data.tx_type.unpack(tx_data)
        tx_list.append(tx_unpacked)
    
    # Calculate merkle root from transaction hashes
    tx_hashes = [dash_data.hash256(dash_data.tx_type.pack(tx)) for tx in tx_list]
    merkle_root = dash_data.merkle_hash(tx_hashes)
    
    # Build block header
    header = {
        'version': template['version'],
        'previous_block': int(template['previousblockhash'], 16),
        'merkle_root': merkle_root,
        'timestamp': template['curtime'],
        'bits': dash_data.FloatingIntegerType().unpack(template['bits'].decode('hex')[::-1]),
        'nonce': parent_block_header['nonce'],  # Use nonce from parent chain
    }
    
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
