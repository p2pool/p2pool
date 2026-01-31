#!/usr/bin/env python
"""Test ASICBOOST stratum extension"""
import socket
import json

def send_stratum(sock, method, params, msg_id=1):
    msg = json.dumps({"id": msg_id, "method": method, "params": params}) + "\n"
    print(">>> SEND:", msg.strip())
    sock.sendall(msg.encode())
    response = sock.recv(4096).decode()
    print("<<< RECV:", response.strip()[:200] + "..." if len(response) > 200 else response.strip())
    # Parse first JSON object (may be multiple lines)
    for line in response.split('\n'):
        if line.strip():
            try:
                return json.loads(line)
            except:
                pass
    return {}

def test_asicboost(host, port):
    print("\n=== Testing ASICBOOST Support ===")
    print("Connecting to %s:%s" % (host, port))
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    # 1. Test mining.subscribe
    print("\n1. Testing mining.subscribe...")
    resp = send_stratum(sock, "mining.subscribe", ["test-asicboost/1.0"])
    
    # 2. Test mining.configure (ASICBOOST)
    print("\n2. Testing mining.configure (ASICBOOST extension)...")
    resp = send_stratum(sock, "mining.configure", [
        ["version-rolling"],
        {"version-rolling.mask": "1fffe000", "version-rolling.min-bit-count": 2}
    ], msg_id=2)
    
    if resp.get('result'):
        vr = resp['result'].get('version-rolling')
        if vr:
            print("\n✅ ASICBOOST IS ENABLED!")
            print("   Version-rolling supported:", vr)
            print("   Pool mask:", resp['result'].get('version-rolling.mask', 'N/A'))
        else:
            print("\n❌ ASICBOOST NOT SUPPORTED")
    else:
        print("\n❌ mining.configure failed:", resp.get('error'))
    
    # 3. Test mining.authorize
    print("\n3. Testing mining.authorize...")
    resp = send_stratum(sock, "mining.authorize", ["XdgF55wEHBRWwbuBniNYH4GvvaoYMgL84u", "x"], msg_id=3)
    
    sock.close()
    print("\n=== Test Complete ===\n")

if __name__ == '__main__':
    test_asicboost('192.168.86.244', 7903)
