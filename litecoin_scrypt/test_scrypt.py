#!/usr/bin/env python
"""Test script for ltc_scrypt module"""

import sys
import binascii

def test_scrypt():
    print("Testing ltc_scrypt module...")
    print("Python version:", sys.version)
    print("")
    
    try:
        import ltc_scrypt
        print("✓ ltc_scrypt module imported successfully")
    except ImportError as e:
        print("✗ Failed to import ltc_scrypt:", e)
        print("\nTry building with: ./build.sh")
        return False
    
    # Test with a sample Litecoin block header (80 bytes)
    # This is block #0 (genesis block) header
    test_header = bytes.fromhex(
        "01000000"  # version
        "0000000000000000000000000000000000000000000000000000000000000000"  # prev block
        "d9ced4ed1130f7b7faad9be25323ffafa33232a17c3edf6cfd97bee6bafbdd97"  # merkle root
        "dae5494d"  # timestamp
        "f0ff0f1e"  # bits
        "0a5e7701"  # nonce (doesn't matter for test)
    )
    
    print("\nTest input (80 bytes):")
    print("  Hex:", binascii.hexlify(test_header).decode())
    
    try:
        result = ltc_scrypt.getPoWHash(test_header)
        print("\n✓ Scrypt hash computed successfully")
        print("  Output length:", len(result), "bytes")
        print("  Hash (hex):", binascii.hexlify(result).decode())
        print("  Hash (int):", int.from_bytes(result, 'little'))
        
        # The hash should be 32 bytes
        assert len(result) == 32, f"Expected 32 bytes, got {len(result)}"
        print("\n✓ All tests passed!")
        return True
        
    except Exception as e:
        print("\n✗ Error computing hash:", e)
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_scrypt()
    sys.exit(0 if success else 1)
