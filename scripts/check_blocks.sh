#!/bin/bash
# Check payout distribution in recent p2pool-mined blocks
# Usage: bash check_blocks.sh [num_blocks]
NUM=${1:-3}
SSH_NODE="NODE_A_IP"

ltc_rpc() {
    ssh $SSH_NODE "curl -s --user litecoinrpc:YOUR_LTC_RPC_PASSWORD --data-binary '{\"jsonrpc\":\"1.0\",\"method\":\"$1\",\"params\":$2}' -H 'content-type:text/plain;' http://LTC_DAEMON_IP:19332/" 2>/dev/null
}

doge_rpc() {
    ssh $SSH_NODE "curl -s --user dogecoinrpc:testpass --data-binary '{\"jsonrpc\":\"1.0\",\"method\":\"$1\",\"params\":$2}' -H 'content-type:text/plain;' http://127.0.0.1:44556/" 2>/dev/null
}

echo "======================================================================"
echo "  PARENT CHAIN: Litecoin Testnet (tLTC) — Last $NUM blocks"
echo "======================================================================"

LTC_HEIGHT=$(ltc_rpc getblockcount "[]" | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])")
echo "Current height: $LTC_HEIGHT"

for ((i=0; i<NUM; i++)); do
    H=$((LTC_HEIGHT - i))
    BHASH=$(ltc_rpc getblockhash "[$H]" | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])")
    ltc_rpc getblock "[\"$BHASH\",2]" | python3 -c "
import json, sys

KNOWN = {
    'mwQqcRjWsCSvMfFrAvpcCujofQSFcV1AsW': 'nodeA-miner',
    'mxptR46XQBRk3EHstU83QRQcqT2PCVkW3g': 'nodeB-miner',
}
KNOWN_HEX = {
    '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac': 'DONATION(P2PK,pre-V36)',
    'a9148c6272621d89e8fa526dd86acff60c7136be8e8587': 'COMBINED_DONATION(P2SH,V36)',
}

resp = json.load(sys.stdin)
block = resp['result']
cb = block['tx'][0]
height = block['height']
bhash = block['hash']

print(f'\n--- tLTC Block #{height} hash={bhash[:20]}... ---')
print(f'    Time: {block[\"time\"]} | Txs: {len(block[\"tx\"])}')

total = 0.0
for i, vout in enumerate(cb['vout']):
    v = vout['value']
    total += v
    sp = vout.get('scriptPubKey', {})
    stype = sp.get('type', '?')
    shex = sp.get('hex', '')
    addr = sp.get('address', sp.get('addresses', [''])[0] if 'addresses' in sp else '')
    
    label = ''
    if addr in KNOWN: label = f' [{KNOWN[addr]}]'
    if shex in KNOWN_HEX: label = f' [{KNOWN_HEX[shex]}]'
    if stype == 'nulldata': label = ' [OP_RETURN]'
    
    pct = v/total*100 if total > 0 else 0
    addr_show = addr if addr else stype
    print(f'    vout[{i}]: {v:>14.8f} ({pct:>6.2f}%) -> {addr_show}{label}')

# Recalc percentages with final total
print(f'    ---- Final distribution (total={total:.8f}) ----')
for i, vout in enumerate(cb['vout']):
    v = vout['value']
    sp = vout.get('scriptPubKey', {})
    stype = sp.get('type', '?')
    shex = sp.get('hex', '')
    addr = sp.get('address', sp.get('addresses', [''])[0] if 'addresses' in sp else '')
    label = ''
    if addr in KNOWN: label = f' [{KNOWN[addr]}]'
    if shex in KNOWN_HEX: label = f' [{KNOWN_HEX[shex]}]'
    if stype == 'nulldata': label = ' [OP_RETURN]'
    pct = v/total*100 if total > 0 else 0
    addr_show = addr if addr else stype
    print(f'    vout[{i}]: {v:>14.8f} ({pct:>6.2f}%) -> {addr_show}{label}')
"
done

echo ""
echo "======================================================================"
echo "  CHILD CHAIN: Dogecoin Testnet (tDOGE) — Last $NUM blocks"
echo "======================================================================"

DOGE_HEIGHT=$(doge_rpc getblockcount "[]" | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])")
echo "Current height: $DOGE_HEIGHT"

for ((i=0; i<NUM; i++)); do
    H=$((DOGE_HEIGHT - i))
    BHASH=$(doge_rpc getblockhash "[$H]" | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])")
    doge_rpc getblock "[\"$BHASH\",2]" | python3 -c "
import json, sys

KNOWN_DOGE = {
    'YOUR_TDOGE_ADDRESS': 'merged-operator',
    'nUYUjP3X8PuHULZz3jZ5HvVVkc2aT3Tr8t': 'nodeA-doge-addr',
    'neu16vaJrZtDvpWy8EfE4KPYMRUXFsCh9t': 'nodeB-doge-addr',
}

resp = json.load(sys.stdin)
block = resp['result']
cb = block['tx'][0]
height = block['height']
bhash = block['hash']

print(f'\n--- tDOGE Block #{height} hash={bhash[:20]}... ---')
print(f'    Time: {block[\"time\"]} | Txs: {len(block[\"tx\"])}')

total = 0.0
for i, vout in enumerate(cb['vout']):
    v = vout['value']
    total += v

for i, vout in enumerate(cb['vout']):
    v = vout['value']
    sp = vout.get('scriptPubKey', {})
    stype = sp.get('type', '?')
    addr = sp.get('address', sp.get('addresses', [''])[0] if 'addresses' in sp else '')
    
    label = ''
    if addr in KNOWN_DOGE: label = f' [{KNOWN_DOGE[addr]}]'
    if stype == 'nulldata': label = ' [OP_RETURN]'
    
    pct = v/total*100 if total > 0 else 0
    addr_show = addr if addr else stype
    print(f'    vout[{i}]: {v:>14.8f} ({pct:>6.2f}%) -> {addr_show}{label}')

print(f'    Total: {total:>14.8f} tDOGE')
"
done
