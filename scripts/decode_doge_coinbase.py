#!/usr/bin/env python3
"""Decode DOGE coinbase from JSON on stdin."""
import json, sys

data = json.load(sys.stdin)
cb = data['tx'][0]
print(f'  Height: {data["height"]}  Confirmations: {data["confirmations"]}')
print(f'  Tx count: {len(data["tx"])}  Coinbase txid: {cb["txid"]}')
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
        print(f'  [{i}] {val:>20.8f} DOGE  OP_RETURN  {ascii_part[:40]}')
    else:
        print(f'  [{i}] {val:>20.8f} DOGE  {addr}  ({stype})')
total = sum(v['value'] for v in cb['vout'])
print(f'  TOTAL: {total:.8f} DOGE')
