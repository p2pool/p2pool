#!/usr/bin/env python3
"""Decode LTC coinbase from JSON on stdin."""
import json, sys

data = json.load(sys.stdin)
cb = data['tx'][0]
print(f'  Height: {data["height"]}  Confirmations: {data["confirmations"]}  Time: {data["time"]}')
print(f'  Tx count: {len(data["tx"])}  Coinbase txid: {cb["txid"]}')

# Known addresses
KNOWN = {
    'mwQqcRjWsCSvMfFrAvpcCujofQSFcV1AsW': 'Node29',
    'mxptR46XQBRk3EHstU83QRQcqT2PCVkW3g': 'Node31',
    'mzisknENRPyyPS1M54qmwatfLhaMyFwRYQ': 'Miner3',
    'mzW2hdZN2um7WBvTDerdahKqRgj3md9C29': 'Miner4',
}

miner_outputs = []
for i, vout in enumerate(cb['vout']):
    addr = vout.get('scriptPubKey', {}).get('addresses', vout.get('scriptPubKey', {}).get('address', ['???']))
    if isinstance(addr, list):
        addr = addr[0] if addr else '???'
    stype = vout.get('scriptPubKey', {}).get('type', '???')
    val = vout['value']
    
    if stype == 'nulldata':
        hex_data = vout.get('scriptPubKey', {}).get('hex', '')
        try:
            ascii_part = bytes.fromhex(hex_data[4:]).decode('ascii', errors='replace')
        except:
            ascii_part = ''
        print(f'  [{i}] {val:>14.8f} LTC  OP_RETURN  {ascii_part[:40]}')
    elif stype == 'scripthash':
        print(f'  [{i}] {val:>14.8f} LTC  {addr}  (P2SH donation)')
    else:
        label = KNOWN.get(addr, '')
        print(f'  [{i}] {val:>14.8f} LTC  {addr}  {label}')
        miner_outputs.append((addr, val, label))

total = sum(v['value'] for v in cb['vout'])
miner_total = sum(v for _, v, _ in miner_outputs)
print(f'  TOTAL: {total:.8f} LTC  |  Miners: {len(miner_outputs)}  |  Miner total: {miner_total:.8f}')

if miner_total > 0:
    for addr, val, label in sorted(miner_outputs, key=lambda x: -x[1]):
        pct = val / miner_total * 100
        print(f'    {addr[:20]}... {label:>8}: {pct:.2f}%')
