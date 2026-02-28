# ltc_scrypt - Litecoin Scrypt Hash Module

Fast C implementation of Scrypt (N=1024, r=1, p=1) proof-of-work hash function used by Litecoin.

## Features

- **Fast**: C implementation is 10-100x faster than pure Python
- **Compatible**: Works with Python 2.7, PyPy, and Python 3.x
- **Standard**: Implements Litecoin's Scrypt parameters (N=1024, r=1, p=1)
- **Tested**: Includes test suite for verification

## Installation

### Quick Build (Automatic)

```bash
./build.sh
```

This will detect available Python interpreters and build for all of them.

### Manual Build

**For Python 2/PyPy (p2pool default):**
```bash
python2 setup.py build
python2 setup.py install --user
```

Or with PyPy (recommended for p2pool):
```bash
pypy setup.py build
pypy setup.py install --user
```

**For Python 3:**
```bash
python3 setup_py3.py build
python3 setup_py3.py install --user
```

## Testing

```bash
# Python 2/PyPy
python2 test_scrypt.py
pypy test_scrypt.py

# Python 3
python3 test_scrypt.py
```

Expected output:
```
✓ ltc_scrypt module imported successfully
✓ Scrypt hash computed successfully
✓ All tests passed!
```

## Usage

```python
import ltc_scrypt

# Input: 80-byte block header
block_header = b'...'  # 80 bytes

# Output: 32-byte Scrypt hash
hash_output = ltc_scrypt.getPoWHash(block_header)
```

## Algorithm Details

- **Function**: Scrypt (N=1024, r=1, p=1)
- **Input**: 80 bytes (block header)
- **Output**: 32 bytes (hash)
- **Memory**: ~131KB scratchpad per hash operation
- **Base**: PBKDF2-HMAC-SHA256 + Salsa20/8

## Files

- `scrypt.c` - Core Scrypt implementation (from jtoomim/p2pool)
- `scrypt.h` - Header file with function declarations
- `scryptmodule.c` - Python 2.x binding
- `scryptmodule_py3.c` - Python 3.x binding
- `setup.py` - Python 2 build script
- `setup_py3.py` - Python 3 build script
- `build.sh` - Automatic build for all Python versions
- `test_scrypt.py` - Test suite

## Performance

Compared to pure Python implementations:
- **ltc_scrypt (C)**: ~1000-5000 hashes/sec (CPU dependent)
- **scrypt (Python)**: ~10-50 hashes/sec

The C extension is essential for mining pool operation.

## Credits

- Original Scrypt: Colin Percival
- Litecoin adaptation: ArtForz, pooler
- p2pool integration: forrestv, jtoomim
- Source: https://github.com/jtoomim/p2pool/tree/master/litecoin_scrypt

## License

BSD 2-Clause License (see scrypt.c header)
