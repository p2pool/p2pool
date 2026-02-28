#!/usr/bin/env python3
"""Check payout distribution in recent p2pool-mined blocks on parent (LTC) and child (DOGE) testnets."""
import json
import subprocess
import sys

# Known addresses
KNOWN_ADDRS = {
    # LTC testnet
    'mwQqcRjWsCSvMfFrAvpcCujofQSFcV1AsW': 'nodeA-miner',
    'mxptR46XQBRk3EHstU83QRQcqT2PCVkW3g': 'nodeB-miner',
    # Donation scripts (by script hex pattern)
}

KNOWN_SCRIPTS = {
    '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac': 'DONATION_SCRIPT (P2PK, pre-V36)',
    'a9148c6272621d89e8fa526dd86acff60c7136be8e8587': 'COMBINED_DONATION (P2SH, V36)',
}

def rpc_call(host, port, user, password, method, params=[]):
    data = json.dumps({"jsonrpc": "1.0", "method": method, "params": params})
    cmd = [
        'ssh', host,
        'curl', '-s', '--user', f'{user}:{password}',
        '--data-binary', data,
        '-H', 'content-type:text/plain;',
        f'http://LTC_DAEMON_IP:{port}/' if 'ltc' in method or port == 19332 else f'http://127.0.0.1:{port}/'
    ]
    # For LTC, RPC is on .26; for DOGE, RPC is on local 127.0.0.1 from inside nodes
    if port == 19332:
        cmd[-1] = f'http://LTC_DAEMON_IP:{port}/'
    else:
        cmd[-1] = f'http://127.0.0.1:{port}/'
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return None
    try:
        resp = json.loads(result.stdout)
        return resp.get('result')
    except:
        return None

def analyze_coinbase(coinbase_tx, chain_name, block_height, block_hash, subsidy=None):
    """Analyze coinbase transaction outputs."""
    print(f'\n{"="*70}')
    print(f'  {chain_name} Block #{block_height}')
    print(f'  Hash: {block_hash[:20]}...{block_hash[-8:]}')
    print(f'{"="*70}')
    
    total = 0.0
    outputs = []
    for i, vout in enumerate(coinbase_tx['vout']):
        val = vout['value']
        total += val
        sp = vout.get('scriptPubKey', {})
        script_type = sp.get('type', '?')
        script_hex = sp.get('hex', '')
        
        # Try to identify the address
        addr = None
        if 'addresses' in sp:
            addr = sp['addresses'][0] if sp['addresses'] else None
        elif 'address' in sp:
            addr = sp['address']
        
        label = ''
        if addr and addr in KNOWN_ADDRS:
            label = f' [{KNOWN_ADDRS[addr]}]'
        if script_hex in KNOWN_SCRIPTS:
            label = f' [{KNOWN_SCRIPTS[script_hex]}]'
        if script_type == 'nulldata':
            label = ' [OP_RETURN/commitment]'
        
        addr_str = addr if addr else script_type
        outputs.append((i, val, addr_str, label, script_hex))
    
    # Calculate percentages
    for i, val, addr_str, label, script_hex in outputs:
        pct = (val / total * 100) if total > 0 else 0
        print(f'  vout[{i}]: {val:>14.8f}  ({pct:>6.2f}%)  -> {addr_str}{label}')
    
    print(f'  {"─"*60}')
    print(f'  Total:  {total:>14.8f}')
    if subsidy:
        print(f'  Subsidy:{subsidy:>14.8f}')
    
    return total, outputs


def check_ltc_blocks(ssh_host, num_blocks=3):
    """Check latest LTC testnet blocks."""
    print('\n' + '#'*70)
    print('  PARENT CHAIN: Litecoin Testnet (tLTC)')
    print('#'*70)
    
    height = rpc_call(ssh_host, 19332, 'litecoinrpc', 'YOUR_LTC_RPC_PASSWORD',
                      'getblockcount')
    if height is None:
        print('ERROR: Cannot reach LTC RPC')
        return
    
    print(f'Current height: {height}')
    
    for h in range(height, height - num_blocks, -1):
        bhash = rpc_call(ssh_host, 19332, 'litecoinrpc', 'YOUR_LTC_RPC_PASSWORD',
                         'getblockhash', [h])
        if not bhash:
            continue
        block = rpc_call(ssh_host, 19332, 'litecoinrpc', 'YOUR_LTC_RPC_PASSWORD',
                         'getblock', [bhash, 2])
        if not block:
            continue
        
        coinbase = block['tx'][0]
        analyze_coinbase(coinbase, 'tLTC', h, bhash)


def check_doge_blocks(ssh_host, num_blocks=3):
    """Check latest DOGE testnet blocks."""
    print('\n' + '#'*70)
    print('  CHILD CHAIN: Dogecoin Testnet (tDOGE)')
    print('#'*70)
    
    height = rpc_call(ssh_host, 44556, 'dogecoinrpc', 'testpass',
                      'getblockcount')
    if height is None:
        print('ERROR: Cannot reach DOGE RPC')
        return
    
    print(f'Current height: {height}')
    
    for h in range(height, height - num_blocks, -1):
        bhash = rpc_call(ssh_host, 44556, 'dogecoinrpc', 'testpass',
                         'getblockhash', [h])
        if not bhash:
            continue
        block = rpc_call(ssh_host, 44556, 'dogecoinrpc', 'testpass',
                         'getblock', [bhash, 2])
        if not block:
            continue
        
        coinbase = block['tx'][0]
        analyze_coinbase(coinbase, 'tDOGE', h, bhash)


if __name__ == '__main__':
    num = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    # Use nodeA as SSH gateway
    check_ltc_blocks('NODE_A_IP', num)
    check_doge_blocks('NODE_A_IP', num)
