#!/usr/bin/env python
"""
Populate block_history.json with historical blocks from the blockchain.

This script queries dashd to get historical blocks mined by this p2pool node
and populates the block_history.json file with reward, difficulty, and timestamp data.

Usage:
    python populate_block_history.py --datadir data/dash --blocks BLOCK_HEIGHT1,BLOCK_HEIGHT2,...
    
Example:
    python populate_block_history.py --datadir data/dash --blocks 2389670,2389615,2389577,2389439
    
Or from a file (one block height per line):
    python populate_block_history.py --datadir data/dash --blocks-file blocks.txt
"""

import json
import os
import sys
import time
from twisted.internet import defer, reactor
from twisted.python import log

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)
sys.path.insert(0, os.path.join(script_dir, 'p2pool'))

from p2pool import networks
from dash import data as bitcoin_data
from p2pool.util import jsonrpc

@defer.inlineCallbacks
def fetch_block_data(dashd, block_height, net):
    """Fetch block data from dashd for a specific height."""
    try:
        # Get block hash from height
        block_hash = yield dashd.rpc_getblockhash(block_height)
        
        # Get block details
        block_info = yield dashd.rpc_getblock(block_hash)
        
        if not block_info:
            print 'Block %d not found' % block_height
            defer.returnValue(None)
        
        # Get coinbase transaction for reward
        block_reward = None
        miner_address = None
        if 'tx' in block_info and len(block_info['tx']) > 0:
            coinbase_txid = block_info['tx'][0]
            try:
                tx_info = yield dashd.rpc_getrawtransaction(coinbase_txid, 1)
                if tx_info and 'vout' in tx_info:
                    # Sum all outputs (block reward + fees)
                    block_reward = sum(vout['value'] for vout in tx_info['vout'])
                    
                    # Try to extract miner address from first output
                    if len(tx_info['vout']) > 0 and 'scriptPubKey' in tx_info['vout'][0]:
                        spk = tx_info['vout'][0]['scriptPubKey']
                        if 'addresses' in spk and len(spk['addresses']) > 0:
                            miner_address = spk['addresses'][0]
            except Exception as e:
                log.err(e, 'Error fetching coinbase transaction for block %d:' % block_height)
        
        # Calculate difficulty from bits
        # Handle both string (hex) and integer bits values
        if isinstance(block_info['bits'], (str, unicode)):
            bits = int(block_info['bits'], 16)
        else:
            bits = int(block_info['bits'])
        
        # Convert bits to target
        exp = bits >> 24
        mant = bits & 0xffffff
        target = mant * (1 << (8 * (exp - 3)))
        network_diff = float(0x00000000FFFF0000000000000000000000000000000000000000000000000000) / float(target)
        
        # Calculate Hash Diff (actual difficulty of the block hash)
        hash_int = int(block_hash, 16)
        max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
        actual_hash_difficulty = float(max_target) / float(hash_int) if hash_int > 0 else 0
        
        result = {
            'hash': block_hash,
            'block_height': block_height,
            'ts': block_info.get('time', int(time.time())),
            'network_diff': network_diff,
            'actual_hash_difficulty': actual_hash_difficulty,
            'block_reward': block_reward,
            'miner': miner_address,
            'status': 'confirmed',  # Historical blocks are confirmed
            'share_hash': None,  # Unknown for historical blocks
            'pool_hashrate': None,  # Unknown for historical blocks
            'stale_prop': None,  # Unknown for historical blocks
            'expected_time': None,  # Can't calculate without pool hashrate
        }
        
        print 'Fetched block %d: hash=%s reward=%.8f DASH diff=%.1fM' % (
            block_height, block_hash[:16], block_reward if block_reward else 0, network_diff / 1e6)
        
        defer.returnValue(result)
        
    except Exception as e:
        log.err(e, 'Error fetching block %d:' % block_height)
        defer.returnValue(None)

@defer.inlineCallbacks
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Populate block history from blockchain')
    parser.add_argument('--datadir', type=str, default='data/dash',
                        help='Data directory (default: data/dash)')
    parser.add_argument('--net', type=str, default='dash',
                        help='Network name (default: dash)')
    parser.add_argument('--blocks', type=str,
                        help='Comma-separated list of block heights to fetch')
    parser.add_argument('--blocks-file', type=str,
                        help='File containing block heights (one per line)')
    parser.add_argument('--dashd-address', type=str, default='127.0.0.1',
                        help='Dashd RPC address (default: 127.0.0.1)')
    parser.add_argument('--dashd-rpc-port', type=int, default=9998,
                        help='Dashd RPC port (default: 9998)')
    parser.add_argument('--dashd-rpc-username', type=str, required=True,
                        help='Dashd RPC username')
    parser.add_argument('--dashd-rpc-password', type=str, required=True,
                        help='Dashd RPC password')
    
    args = parser.parse_args()
    
    # Get block heights to fetch
    block_heights = []
    if args.blocks:
        block_heights = [int(h.strip()) for h in args.blocks.split(',')]
    elif args.blocks_file:
        with open(args.blocks_file, 'r') as f:
            block_heights = [int(line.strip()) for line in f if line.strip().isdigit()]
    else:
        print 'Error: Must specify either --blocks or --blocks-file'
        reactor.stop()
        defer.returnValue(None)
    
    print 'Fetching %d blocks...' % len(block_heights)
    
    # Get network
    net = networks.nets[args.net]
    
    # Connect to dashd
    dashd = jsonrpc.HTTPProxy('http://%s:%d/' % (args.dashd_address, args.dashd_rpc_port),
                               dict(Authorization='Basic ' + 
                                    ('%s:%s' % (args.dashd_rpc_username, args.dashd_rpc_password)).encode('base64').strip()))
    
    # Test connection
    try:
        info = yield dashd.rpc_getblockchaininfo()
        print 'Connected to dashd: height=%d' % info['blocks']
    except Exception as e:
        log.err(e, 'Error connecting to dashd:')
        reactor.stop()
        defer.returnValue(None)
    
    # Load existing block history
    block_history_file = os.path.join(args.datadir, 'block_history.json')
    block_history = {}
    if os.path.exists(block_history_file):
        try:
            with open(block_history_file, 'rb') as f:
                block_history = json.loads(f.read())
            print 'Loaded %d existing blocks from history' % len(block_history)
        except Exception as e:
            log.err(e, 'Error loading block history:')
    
    # Fetch blocks
    new_count = 0
    updated_count = 0
    
    for block_height in block_heights:
        block_data = yield fetch_block_data(dashd, block_height, net)
        
        if block_data:
            block_hash = block_data['hash']
            if block_hash in block_history:
                print 'Block %d already in history, updating...' % block_height
                block_history[block_hash].update(block_data)
                updated_count += 1
            else:
                print 'Adding block %d to history' % block_height
                block_history[block_hash] = block_data
                new_count += 1
    
    # Save updated history
    print 'Saving block history...'
    try:
        # Create datadir if it doesn't exist
        if not os.path.exists(args.datadir):
            os.makedirs(args.datadir)
        
        with open(block_history_file + '.new', 'wb') as f:
            f.write(json.dumps(block_history, indent=2, sort_keys=True))
        
        # Atomic rename
        if os.path.exists(block_history_file):
            os.remove(block_history_file)
        os.rename(block_history_file + '.new', block_history_file)
        
        print 'Saved block history: %d total blocks (%d new, %d updated)' % (
            len(block_history), new_count, updated_count)
    except Exception as e:
        log.err(e, 'Error saving block history:')
    
    reactor.stop()

if __name__ == '__main__':
    log.startLogging(sys.stdout)
    reactor.callWhenRunning(main)
    reactor.run()
