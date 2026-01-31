#!/usr/bin/env python3
"""
Test script for the Merged Mining RPC Adapter.

Usage:
    python test_adapter.py [adapter_url]

Example:
    python test_adapter.py http://adapter:adapterpass@127.0.0.1:44555/
"""

import json
import sys
import urllib.request


def make_rpc_call(url: str, method: str, params: list = None):
    """Make a JSON-RPC call."""
    if params is None:
        params = []
    
    # Parse URL for auth
    from urllib.parse import urlparse
    parsed = urlparse(url)
    
    # Build request
    payload = json.dumps({
        "jsonrpc": "1.0",
        "id": 1,
        "method": method,
        "params": params
    }).encode('utf-8')
    
    # Create request with auth
    req = urllib.request.Request(
        f"{parsed.scheme}://{parsed.hostname}:{parsed.port}/",
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': 'Basic ' + __import__('base64').b64encode(
                f"{parsed.username}:{parsed.password}".encode()
            ).decode()
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None


def test_adapter(url: str):
    """Run tests against the adapter."""
    
    print(f"Testing adapter at: {url}")
    print("=" * 60)
    
    # Test 1: getblocktemplate with auxpow capability
    print("\n1. Testing getblocktemplate({capabilities: [auxpow]})...")
    result = make_rpc_call(url, 'getblocktemplate', [{"capabilities": ["auxpow"]}])
    if result and result.get('result'):
        template = result['result']
        print(f"   ✓ Got template with {len(template.get('transactions', []))} transactions")
        if 'auxpow' in template:
            auxpow = template['auxpow']
            print(f"   ✓ auxpow.chainid = {auxpow.get('chainid')}")
            print(f"   ✓ auxpow.hash = {auxpow.get('hash', '')[:32]}...")
            print(f"   ✓ auxpow.target = {auxpow.get('target', '')[:16]}...")
        else:
            print("   ✗ No auxpow object in response!")
    else:
        print(f"   ✗ Failed: {result}")
    
    # Test 2: getauxblock (work request)
    print("\n2. Testing getauxblock() (work request)...")
    result = make_rpc_call(url, 'getauxblock', [])
    if result and result.get('result'):
        auxblock = result['result']
        print(f"   ✓ chainid = {auxblock.get('chainid')}")
        print(f"   ✓ hash = {auxblock.get('hash', '')[:32]}...")
        print(f"   ✓ target = {auxblock.get('target', '')[:16]}...")
    else:
        print(f"   ✗ Failed: {result}")
    
    # Test 3: Simple passthrough (getinfo or getblockchaininfo)
    print("\n3. Testing passthrough (getblockchaininfo)...")
    result = make_rpc_call(url, 'getblockchaininfo', [])
    if result and result.get('result'):
        info = result['result']
        print(f"   ✓ chain = {info.get('chain')}")
        print(f"   ✓ blocks = {info.get('blocks')}")
    elif result and result.get('error'):
        print(f"   ~ Method might not exist: {result['error'].get('message')}")
    else:
        print(f"   ✗ Failed: {result}")
    
    print("\n" + "=" * 60)
    print("Tests completed!")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "http://adapter:adapterpass@127.0.0.1:44555/"
    
    test_adapter(url)
