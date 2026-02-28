#!/usr/bin/env python3
"""
Test P2Pool Extranonce Support - Both NiceHash and BIP310 Styles

Tests both extranonce subscription methods:
1. NiceHash style: mining.extranonce.subscribe (separate method)
2. BIP310 style: mining.configure with subscribe-extranonce extension

Usage:
    python3 test_extranonce_compatibility.py [host] [port]
"""

import socket
import json
import sys
import time

def send_request(sock, method, params, req_id):
    """Send a JSON-RPC request"""
    request = {"id": req_id, "method": method, "params": params}
    print(f"\n>>> Request [{req_id}]: {method}")
    if params:
        print(f"    Params: {params}")
    sock.sendall((json.dumps(request) + "\n").encode())
    return req_id

def read_until_response(sock, expected_id, timeout=5):
    """Read lines until we get the response with expected_id"""
    sock.settimeout(timeout)
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            line = b''
            while True:
                char = sock.recv(1)
                if not char or char == b'\n':
                    break
                line += char
            
            if not line:
                continue
                
            try:
                msg = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            
            # Check if notification or response
            if 'method' in msg:
                method = msg['method']
                if method == "mining.set_extranonce":
                    print(f"    📢 mining.set_extranonce: params={msg.get('params')}")
                continue
            
            msg_id = msg.get('id')
            if msg_id == expected_id:
                return msg, None
                
        except socket.timeout:
            break
        except Exception as e:
            print(f"    Error: {e}")
            break
    
    return None, None

def test_nicehash_style(host, port):
    """Test NiceHash mining.extranonce.subscribe method"""
    print("\n" + "=" * 70)
    print("TEST 1: NiceHash Style (mining.extranonce.subscribe)")
    print("=" * 70)
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        print("✅ Connected")
        
        # 1. Subscribe
        send_request(sock, "mining.subscribe", ["test-nicehash/1.0"], 1)
        resp, _ = read_until_response(sock, 1)
        if not resp or 'result' not in resp:
            print("❌ FAILED: mining.subscribe")
            return False
        print("    ✅ mining.subscribe OK")
        
        time.sleep(0.2)
        
        # 2. NiceHash extranonce.subscribe
        send_request(sock, "mining.extranonce.subscribe", [], 2)
        resp, _ = read_until_response(sock, 2)
        if not resp:
            print("❌ FAILED: mining.extranonce.subscribe - no response")
            return False
        
        result = resp.get('result')
        error = resp.get('error')
        
        if result is True:
            print("    ✅ mining.extranonce.subscribe SUPPORTED")
            print(f"       Result: {result}")
        elif result is False:
            print("    ❌ mining.extranonce.subscribe NOT SUPPORTED")
            print(f"       Error: {error}")
            return False
        else:
            print(f"    ⚠ Unexpected response: {resp}")
            return False
        
        time.sleep(0.2)
        
        # 3. Authorize
        send_request(sock, "mining.authorize", ["XsFe6mGpLM3R6ZieYJXhsmGyYg8jn3Lth6", "x"], 3)
        resp, _ = read_until_response(sock, 3)
        if not resp:
            print("❌ FAILED: mining.authorize")
            return False
        print("    ✅ mining.authorize OK")
        
        # 4. Wait for mining.set_extranonce
        print("\n    Waiting for mining.set_extranonce notification (35 sec)...")
        sock.settimeout(35)
        start = time.time()
        extranonce_received = False
        
        while time.time() - start < 35:
            try:
                line = b''
                while True:
                    char = sock.recv(1)
                    if not char or char == b'\n':
                        break
                    line += char
                
                if line:
                    msg = json.loads(line.decode())
                    if 'method' in msg and msg['method'] == "mining.set_extranonce":
                        extranonce_received = True
                        params = msg.get('params', [])
                        print(f"    ✅ mining.set_extranonce received!")
                        print(f"       extranonce1: '{params[0] if params else 'N/A'}'")
                        print(f"       extranonce2_size: {params[1] if len(params) > 1 else 'N/A'}")
                        break
            except socket.timeout:
                break
            except:
                break
        
        sock.close()
        
        if not extranonce_received:
            print("    ⚠ No mining.set_extranonce received (might be timing)")
        
        return extranonce_received
        
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def test_bip310_style(host, port):
    """Test BIP310 mining.configure with subscribe-extranonce"""
    print("\n" + "=" * 70)
    print("TEST 2: BIP310 Style (mining.configure with subscribe-extranonce)")
    print("=" * 70)
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        print("✅ Connected")
        
        # 1. Subscribe
        send_request(sock, "mining.subscribe", ["test-bip310/1.0"], 1)
        resp, _ = read_until_response(sock, 1)
        if not resp:
            print("❌ FAILED: mining.subscribe")
            return False
        print("    ✅ mining.subscribe OK")
        
        time.sleep(0.2)
        
        # 2. Configure with subscribe-extranonce
        send_request(sock, "mining.configure", 
            [["subscribe-extranonce"], {}], 
            2)
        resp, _ = read_until_response(sock, 2, timeout=10)
        if not resp:
            print("❌ FAILED: mining.configure")
            return False
        
        result = resp.get('result', {})
        if result.get('subscribe-extranonce') is True:
            print("    ✅ subscribe-extranonce ENABLED")
            print(f"       Result: {result}")
        else:
            print(f"    ❌ subscribe-extranonce not in result: {result}")
            return False
        
        time.sleep(0.2)
        
        # 3. Authorize
        send_request(sock, "mining.authorize", ["XsFe6mGpLM3R6ZieYJXhsmGyYg8jn3Lth6", "x"], 3)
        resp, _ = read_until_response(sock, 3)
        if not resp:
            print("❌ FAILED: mining.authorize")
            return False
        print("    ✅ mining.authorize OK")
        
        # 4. Wait for mining.set_extranonce
        print("\n    Waiting for mining.set_extranonce notification (35 sec)...")
        sock.settimeout(35)
        start = time.time()
        extranonce_received = False
        
        while time.time() - start < 35:
            try:
                line = b''
                while True:
                    char = sock.recv(1)
                    if not char or char == b'\n':
                        break
                    line += char
                
                if line:
                    msg = json.loads(line.decode())
                    if 'method' in msg and msg['method'] == "mining.set_extranonce":
                        extranonce_received = True
                        params = msg.get('params', [])
                        print(f"    ✅ mining.set_extranonce received!")
                        print(f"       extranonce1: '{params[0] if params else 'N/A'}'")
                        print(f"       extranonce2_size: {params[1] if len(params) > 1 else 'N/A'}")
                        break
            except socket.timeout:
                break
            except:
                break
        
        sock.close()
        
        if not extranonce_received:
            print("    ⚠ No mining.set_extranonce received (might be timing)")
        
        return extranonce_received
        
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.86.244"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 7903
    
    print("=" * 70)
    print("P2Pool Extranonce Compatibility Test")
    print(f"Testing: {host}:{port}")
    print("=" * 70)
    
    nicehash_ok = test_nicehash_style(host, port)
    time.sleep(1)
    bip310_ok = test_bip310_style(host, port)
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"NiceHash Style (mining.extranonce.subscribe): {'✅ PASS' if nicehash_ok else '❌ FAIL'}")
    print(f"BIP310 Style (mining.configure): {'✅ PASS' if bip310_ok else '❌ FAIL'}")
    
    if nicehash_ok and bip310_ok:
        print("\n✅ BOTH METHODS SUPPORTED - Full ASIC Compatibility!")
    elif nicehash_ok or bip310_ok:
        print("\n⚠ PARTIAL SUPPORT - Some ASICs may not work")
    else:
        print("\n❌ NO SUPPORT - ASICs will not work")
    print("=" * 70)
    
    sys.exit(0 if (nicehash_ok and bip310_ok) else 1)
