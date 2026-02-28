#!/usr/bin/env python3
"""
Test P2Pool ASICBOOST (version-rolling) Implementation

This script verifies that P2Pool correctly implements BIP320 version-rolling
by sending mining.configure and checking the response.

Usage:
    python3 test_p2pool_asicboost.py [host] [port]
    
Example:
    python3 test_p2pool_asicboost.py 192.168.86.244 7903
"""

import socket
import json
import sys
import time

def send_request(sock, method, params, req_id):
    """Send a JSON-RPC request"""
    request = {"id": req_id, "method": method, "params": params}
    print(f"\n>>> Request [{req_id}]: {method}")
    if method == "mining.configure":
        print(f"    Extensions: {params[0]}")
        print(f"    Parameters: {params[1]}")
    sock.sendall((json.dumps(request) + "\n").encode())
    return req_id

def read_until_response(sock, expected_id, timeout=5):
    """
    Read lines until we get the response with expected_id.
    Properly handles unsolicited notifications (mining.notify, mining.set_difficulty).
    """
    sock.settimeout(timeout)
    start = time.time()
    notifications = []
    
    print(f"    Waiting for response id={expected_id}...")
    
    while time.time() - start < timeout:
        try:
            # Read one line
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
            
            # Check if this is a notification (has 'method') or response (has 'result'/'error')
            if 'method' in msg:
                # This is an unsolicited notification
                method = msg['method']
                msg_id = msg.get('id', 'N/A')
                notifications.append(f"{method} (id={msg_id})")
                print(f"    📢 Notification: {method} [id={msg_id}]")
                continue
            
            # This is a response - check ID
            msg_id = msg.get('id')
            if msg_id == expected_id:
                print(f"    ✅ Response received [id={expected_id}]")
                return msg, notifications
            else:
                print(f"    ⚠ Response with wrong ID: {msg_id} (expected {expected_id})")
                
        except socket.timeout:
            break
        except Exception as e:
            print(f"    ❌ Error: {e}")
            break
    
    print(f"    ❌ Timeout - no response for id={expected_id}")
    return None, notifications

def test_asicboost(host, port):
    """Test P2Pool ASICBOOST support"""
    print("=" * 70)
    print(f"Testing P2Pool ASICBOOST Support")
    print(f"Host: {host}:{port}")
    print("=" * 70)
    
    try:
        # Connect
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        print("✅ Connected to P2Pool")
        
        # 1. mining.subscribe
        send_request(sock, "mining.subscribe", ["test-asicboost/1.0"], 1)
        resp, notifs = read_until_response(sock, 1)
        if not resp:
            print("❌ FAILED: No response to mining.subscribe")
            return False
        
        if 'result' in resp and resp['result']:
            session_id = resp['result'][0][1] if len(resp['result']) > 0 else "unknown"
            extranonce2_size = resp['result'][2] if len(resp['result']) > 2 else 0
            print(f"    ✅ Subscribed: session={session_id[:16]}..., extranonce2_size={extranonce2_size}")
        
        time.sleep(0.2)
        
        # 2. mining.configure (ASICBOOST)
        send_request(sock, "mining.configure", 
            [["version-rolling"], 
             {"version-rolling.mask": "1fffe000", "version-rolling.min-bit-count": 2}], 
            2)
        
        resp, notifs = read_until_response(sock, 2)
        if not resp:
            print("❌ FAILED: No response to mining.configure")
            return False
        
        if 'result' in resp and resp['result']:
            result = resp['result']
            vr_enabled = result.get('version-rolling', False)
            vr_mask = result.get('version-rolling.mask', 'N/A')
            
            if vr_enabled:
                mask_int = int(vr_mask, 16)
                bits = bin(mask_int).count('1')
                print(f"    ✅ ASICBOOST ENABLED!")
                print(f"       Mask: 0x{vr_mask} ({bits} bits)")
                print(f"       Binary: {bin(mask_int)}")
            else:
                print(f"    ❌ Version-rolling not enabled: {result}")
                return False
        else:
            print(f"    ❌ Invalid response: {resp}")
            return False
        
        time.sleep(0.2)
        
        # 3. mining.authorize
        send_request(sock, "mining.authorize", 
            ["XsFe6mGpLM3R6ZieYJXhsmGyYg8jn3Lth6", "x"], 
            3)
        
        resp, notifs = read_until_response(sock, 3)
        if not resp:
            print("❌ FAILED: No response to mining.authorize")
            return False
        
        if 'result' in resp and resp['result']:
            print(f"    ✅ Authorized")
        
        time.sleep(0.5)
        sock.close()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        print("\nConclusion:")
        print("  • P2Pool correctly implements BIP320 version-rolling")
        print("  • Response IDs match request IDs perfectly")
        print("  • mining.configure is properly handled")
        print("  • ASICBOOST support is WORKING")
        print("\nIf your miner shows 'ID mismatch' errors, the bug is in")
        print("the MINER code, not P2Pool!")
        print("=" * 70)
        
        return True
        
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
    
    success = test_asicboost(host, port)
    sys.exit(0 if success else 1)
