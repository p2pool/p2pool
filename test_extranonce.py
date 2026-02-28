#!/usr/bin/env python3
"""
Test P2Pool Extranonce Support

This script verifies that P2Pool correctly implements mining.extranonce.subscribe
extension required for ASIC miners.

Usage:
    python3 test_extranonce.py [host] [port]
    
Example:
    python3 test_extranonce.py 192.168.86.244 7903
"""

import socket
import json
import sys
import time

def send_request(sock, method, params, req_id):
    """Send a JSON-RPC request"""
    request = {"id": req_id, "method": method, "params": params}
    print(f"\n>>> Request [{req_id}]: {method}")
    sock.sendall((json.dumps(request) + "\n").encode())
    return req_id

def read_until_response(sock, expected_id, timeout=5):
    """Read lines until we get the response with expected_id"""
    sock.settimeout(timeout)
    start = time.time()
    notifications = []
    
    print(f"    Waiting for response id={expected_id}...")
    
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
            except json.JSONDecodeError as e:
                print(f"    ⚠ JSON decode error: {e}")
                continue
            
            # Check if this is a notification or response
            if 'method' in msg:
                method = msg['method']
                msg_id = msg.get('id', 'N/A')
                notifications.append((method, msg.get('params')))
                print(f"    📢 Notification: {method} [id={msg_id}]")
                if method == "mining.set_extranonce":
                    print(f"       → extranonce1={msg['params'][0]}, size={msg['params'][1]}")
                continue
            
            msg_id = msg.get('id')
            if msg_id == expected_id:
                print(f"    ✅ Response received [id={expected_id}]")
                return msg, notifications
                
        except socket.timeout:
            break
        except Exception as e:
            print(f"    ❌ Error: {e}")
            break
    
    print(f"    ❌ Timeout - no response for id={expected_id}")
    return None, notifications

def test_extranonce(host, port):
    """Test P2Pool extranonce support"""
    print("=" * 70)
    print(f"Testing P2Pool Extranonce Support (ASIC Compatibility)")
    print(f"Host: {host}:{port}")
    print("=" * 70)
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        print("✅ Connected to P2Pool")
        
        # 1. mining.subscribe
        send_request(sock, "mining.subscribe", ["test-extranonce/1.0"], 1)
        resp, notifs = read_until_response(sock, 1)
        if not resp:
            print("❌ FAILED: No response to mining.subscribe")
            return False
        
        print(f"    ✅ Subscribed")
        time.sleep(0.2)
        
        # 2. mining.configure with subscribe-extranonce
        print("\n" + "=" * 70)
        print("CRITICAL TEST: mining.configure with subscribe-extranonce")
        print("=" * 70)
        
        send_request(sock, "mining.configure", 
            [["subscribe-extranonce"], {}], 
            2)
        
        resp, notifs = read_until_response(sock, 2, timeout=10)
        if not resp:
            print("❌ FAILED: No response to mining.configure")
            return False
        
        if 'result' in resp and resp['result']:
            result = resp['result']
            extranonce_enabled = result.get('subscribe-extranonce', False)
            
            if extranonce_enabled:
                print(f"    ✅ EXTRANONCE SUPPORT ENABLED!")
                print(f"       Response: {result}")
            else:
                print(f"    ❌ Extranonce not enabled: {result}")
                return False
        else:
            print(f"    ⚠ Response: {resp}")
        
        time.sleep(0.2)
        
        # 3. mining.authorize
        send_request(sock, "mining.authorize", 
            ["XsFe6mGpLM3R6ZieYJXhsmGyYg8jn3Lth6", "x"], 
            3)
        
        resp, notifs = read_until_response(sock, 3)
        if not resp:
            print("❌ FAILED: No response to mining.authorize")
            return False
        
        print(f"    ✅ Authorized")
        
        # 4. Wait for extranonce notifications
        print("\n" + "=" * 70)
        print("Waiting for mining.set_extranonce notifications (35 seconds)...")
        print("=" * 70)
        
        extranonce_received = False
        sock.settimeout(35)
        start = time.time()
        
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
                    if 'method' in msg:
                        method = msg['method']
                        if method == "mining.set_extranonce":
                            extranonce_received = True
                            params = msg.get('params', [])
                            print(f"\n    ✅ mining.set_extranonce received!")
                            print(f"       extranonce1: {params[0] if params else 'N/A'}")
                            print(f"       extranonce2_size: {params[1] if len(params) > 1 else 'N/A'}")
                            break
                        else:
                            print(f"    📢 {method}")
                            
            except socket.timeout:
                break
            except Exception as e:
                print(f"    Error: {e}")
                break
        
        sock.close()
        
        print("\n" + "=" * 70)
        if extranonce_enabled and extranonce_received:
            print("✅ ALL TESTS PASSED!")
        elif extranonce_enabled:
            print("⚠ PARTIAL SUCCESS - Extranonce enabled but no periodic updates")
        else:
            print("❌ TESTS FAILED")
        print("=" * 70)
        
        print("\nResults:")
        print(f"  • subscribe-extranonce extension: {'✅ Supported' if extranonce_enabled else '❌ Not supported'}")
        print(f"  • mining.set_extranonce notifications: {'✅ Working' if extranonce_received else '⚠ Not received'}")
        
        if extranonce_enabled:
            print("\n✅ ASIC Compatibility: ENABLED")
            print("   ASICs like Antminer D3, Innosilicon A5 should now work!")
        else:
            print("\n❌ ASIC Compatibility: DISABLED")
            print("   ASICs will NOT work without extranonce support")
        
        print("=" * 70)
        
        return extranonce_enabled
        
    except ConnectionRefusedError:
        print(f"❌ Connection refused - is P2Pool running on {host}:{port}?")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.86.244"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 7903
    
    success = test_extranonce(host, port)
    sys.exit(0 if success else 1)
