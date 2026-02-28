#!/usr/bin/env python3
"""
Simple Stratum Server for Mining Genesis Block with ASIC

This server feeds genesis block work to scrypt ASICs like AntRouter L1.
Once a valid nonce is found, it prints the genesis parameters.
"""

import socket
import json
import struct
import sys
import time
import threading

sys.path.insert(0, '/home/user0/litecoin_scrypt')
try:
    import ltc_scrypt
    print("Using ltc_scrypt for hash verification")
except ImportError:
    print("Warning: ltc_scrypt not available, hash verification disabled")
    ltc_scrypt = None

# Genesis block parameters
GENESIS_VERSION = 1
GENESIS_PREV_BLOCK = "0" * 64
GENESIS_MERKLE_ROOT = "5b2a3f53f605d62c53e62932dac6925e3d74afa5a4b459745c36d42d0ed26a69"
GENESIS_TIMESTAMP = 1737907200  # Jan 26, 2026 12:00:00 UTC
GENESIS_BITS = 0x1e0ffff0

# Stratum parameters
EXTRANONCE1 = "00000000"
EXTRANONCE2_SIZE = 4

def bytes_to_hex_le(data):
    """Convert bytes to little-endian hex string"""
    return data[::-1].hex()

def hex_to_bytes_le(hex_str):
    """Convert hex string to little-endian bytes"""
    return bytes.fromhex(hex_str)[::-1]

def compact_to_target(bits):
    """Convert compact representation to target"""
    size = bits >> 24
    word = bits & 0x007fffff
    if size <= 3:
        word >>= 8 * (3 - size)
    else:
        word <<= 8 * (size - 3)
    return word

def target_to_hex(target):
    """Convert target integer to 64-char hex (big-endian for display)"""
    return f"{target:064x}"

def create_coinbase_tx():
    """Create the coinbase transaction for genesis block"""
    # Genesis coinbase is special - just return placeholder
    # The merkle root is already known
    return "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff0804ffff001d02fd04ffffffff0100f2052a0100000043410496b538e853519c726a2c91e61ec11600ae1390813a627c66fb8be7947be63c52da7589379515d4e0a604f8141781e62294721166bf621e73a82cbf2342c858eeac00000000"

def get_job_id():
    """Generate a unique job ID"""
    return f"{int(time.time()):08x}"

class StratumServer:
    def __init__(self, host='0.0.0.0', port=3333):
        self.host = host
        self.port = port
        self.clients = {}
        self.found_genesis = None
        self.target = compact_to_target(GENESIS_BITS)
        self.running = True
        
    def create_mining_notify(self, job_id, clean_jobs=True):
        """Create mining.notify message for genesis block"""
        # Stratum mining.notify format:
        # [job_id, prevhash, coinb1, coinb2, merkle_branches, version, nbits, ntime, clean_jobs]
        
        prev_hash = GENESIS_PREV_BLOCK
        coinbase = create_coinbase_tx()
        
        # Split coinbase for extranonce insertion (not really needed for genesis)
        coinb1 = coinbase[:len(coinbase)//2]
        coinb2 = coinbase[len(coinbase)//2:]
        
        # No merkle branches for genesis (single tx)
        merkle_branches = []
        
        version = f"{GENESIS_VERSION:08x}"
        nbits = f"{GENESIS_BITS:08x}"
        ntime = f"{GENESIS_TIMESTAMP:08x}"
        
        return {
            "id": None,
            "method": "mining.notify",
            "params": [
                job_id,
                prev_hash,
                coinb1,
                coinb2,
                merkle_branches,
                version,
                nbits,
                ntime,
                clean_jobs
            ]
        }
    
    def create_set_difficulty(self, difficulty=1):
        """Create mining.set_difficulty message"""
        return {
            "id": None,
            "method": "mining.set_difficulty",
            "params": [difficulty]
        }
    
    def handle_subscribe(self, client_id, msg_id):
        """Handle mining.subscribe"""
        response = {
            "id": msg_id,
            "result": [
                [["mining.notify", "ae6812eb4cd7735a302a8a9dd95cf71f"]],
                EXTRANONCE1,
                EXTRANONCE2_SIZE
            ],
            "error": None
        }
        return response
    
    def handle_authorize(self, client_id, msg_id, params):
        """Handle mining.authorize"""
        username = params[0] if params else "unknown"
        print(f"Client {client_id} authorized as: {username}")
        return {"id": msg_id, "result": True, "error": None}
    
    def handle_submit(self, client_id, msg_id, params):
        """Handle mining.submit - check if valid genesis found"""
        # params: [worker, job_id, extranonce2, ntime, nonce]
        worker = params[0]
        job_id = params[1]
        extranonce2 = params[2]
        ntime = params[3]
        nonce = params[4]
        
        print(f"\n=== SHARE SUBMITTED ===")
        print(f"  Worker: {worker}")
        print(f"  Nonce: {nonce}")
        print(f"  Time: {ntime}")
        
        # Reconstruct block header and verify
        nonce_int = int(nonce, 16)
        nonce_int = struct.unpack('<I', struct.pack('>I', nonce_int))[0]  # Swap endianness
        
        # Build header
        header = struct.pack('<I', GENESIS_VERSION)
        header += bytes.fromhex(GENESIS_PREV_BLOCK)[::-1]
        header += bytes.fromhex(GENESIS_MERKLE_ROOT)[::-1]
        header += struct.pack('<I', GENESIS_TIMESTAMP)
        header += struct.pack('<I', GENESIS_BITS)
        header += struct.pack('<I', nonce_int)
        
        if ltc_scrypt:
            hash_result = ltc_scrypt.getPoWHash(header)
            hash_int = int.from_bytes(hash_result, 'little')
            hash_hex = hash_result[::-1].hex()
            
            print(f"  Hash: {hash_hex}")
            print(f"  Target: {target_to_hex(self.target)}")
            
            if hash_int <= self.target:
                print(f"\n*** GENESIS BLOCK FOUND! ***")
                print(f"  Nonce: {nonce_int}")
                print(f"  Hash: {hash_hex}")
                print(f"\nUse these values in chainparams.cpp:")
                print(f'  genesis = CreateGenesisBlock({GENESIS_TIMESTAMP}, {nonce_int}, 0x{GENESIS_BITS:08x}, 1, 88 * COIN);')
                print(f'  assert(consensus.hashGenesisBlock == uint256S("0x{hash_hex}"));')
                self.found_genesis = (nonce_int, hash_hex)
                return {"id": msg_id, "result": True, "error": None}
            else:
                print("  Share valid but doesn't meet genesis target")
        
        return {"id": msg_id, "result": True, "error": None}
    
    def handle_client(self, conn, addr):
        """Handle a single client connection"""
        client_id = f"{addr[0]}:{addr[1]}"
        print(f"Client connected: {client_id}")
        self.clients[client_id] = conn
        
        buffer = ""
        job_id = get_job_id()
        
        try:
            while self.running and not self.found_genesis:
                data = conn.recv(4096).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if not line.strip():
                        continue
                    
                    try:
                        msg = json.loads(line)
                        method = msg.get('method', '')
                        msg_id = msg.get('id')
                        params = msg.get('params', [])
                        
                        print(f"Received: {method}")
                        
                        if method == 'mining.subscribe':
                            response = self.handle_subscribe(client_id, msg_id)
                            conn.send((json.dumps(response) + '\n').encode())
                            
                            # Send difficulty and job
                            diff_msg = self.create_set_difficulty(0.001)  # Low difficulty for shares
                            conn.send((json.dumps(diff_msg) + '\n').encode())
                            
                            notify_msg = self.create_mining_notify(job_id)
                            conn.send((json.dumps(notify_msg) + '\n').encode())
                            
                        elif method == 'mining.authorize':
                            response = self.handle_authorize(client_id, msg_id, params)
                            conn.send((json.dumps(response) + '\n').encode())
                            
                        elif method == 'mining.submit':
                            response = self.handle_submit(client_id, msg_id, params)
                            conn.send((json.dumps(response) + '\n').encode())
                            
                        elif method == 'mining.extranonce.subscribe':
                            conn.send((json.dumps({"id": msg_id, "result": True, "error": None}) + '\n').encode())
                            
                    except json.JSONDecodeError as e:
                        print(f"JSON error: {e}")
                        
        except Exception as e:
            print(f"Client error: {e}")
        finally:
            print(f"Client disconnected: {client_id}")
            conn.close()
            del self.clients[client_id]
    
    def run(self):
        """Start the stratum server"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(5)
        server.settimeout(1.0)
        
        print(f"\n{'='*60}")
        print(f"Genesis Block Stratum Server")
        print(f"{'='*60}")
        print(f"Listening on {self.host}:{self.port}")
        print(f"Target difficulty: 0x{GENESIS_BITS:08x}")
        print(f"Merkle root: {GENESIS_MERKLE_ROOT}")
        print(f"Timestamp: {GENESIS_TIMESTAMP}")
        print(f"\nPoint your AntRouter L1 to:")
        print(f"  stratum+tcp://<this-ip>:{self.port}")
        print(f"  Username: anything")
        print(f"  Password: anything")
        print(f"{'='*60}\n")
        
        try:
            while self.running and not self.found_genesis:
                try:
                    conn, addr = server.accept()
                    thread = threading.Thread(target=self.handle_client, args=(conn, addr))
                    thread.daemon = True
                    thread.start()
                except socket.timeout:
                    continue
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            server.close()
            
        if self.found_genesis:
            print(f"\n\nGENESIS MINING COMPLETE!")
            print(f"Nonce: {self.found_genesis[0]}")
            print(f"Hash: {self.found_genesis[1]}")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3333
    server = StratumServer(port=port)
    server.run()
