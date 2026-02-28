"""
Drop-in replacement for the legacy litecoin_scrypt C extension module.

Uses the maintained py-scrypt package (C bindings to Colin Percival's scrypt)
instead of the old unmaintained custom C extension. Performance is equivalent
since both use the same underlying C implementation.

Install:
    pip install 'scrypt>=0.8.0,<=0.8.22'   # 0.8.23+ uses f-strings, breaks Python 2.7/PyPy

Original C extension parameters: N=1024, r=1, p=1, buflen=32
Input: 80-byte block header used as both password and salt.

Fallback: if py-scrypt is not installed, attempts to import the old C
extension from litecoin_scrypt/ so existing installations keep working.
"""

try:
    import scrypt as _scrypt
    # Eagerly verify the C library loads (catches GLIBC mismatches, etc.)
    _scrypt.hash(b'\x00' * 80, b'\x00' * 80, N=1024, r=1, p=1, buflen=32)

    def getPoWHash(header):
        """Return the 32-byte scrypt proof-of-work hash for a block header.

        Equivalent to the original ltc_scrypt C extension's getPoWHash(),
        which called scrypt_1024_1_1_256(input, output) using the 80-byte
        block header as both password and salt.

        Args:
            header: 80-byte block header (bytes/str).

        Returns:
            32-byte scrypt hash (bytes/str).
        """
        return _scrypt.hash(header, header, N=1024, r=1, p=1, buflen=32)

except (ImportError, OSError):
    # Fallback: try the old C extension from litecoin_scrypt/
    import sys
    import os

    _ext_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'litecoin_scrypt')
    if _ext_dir not in sys.path:
        sys.path.insert(0, _ext_dir)

    try:
        # Import the C extension .so directly — it registers as 'ltc_scrypt'
        # but since *this* file is ltc_scrypt.py and shadows it at the top level,
        # we need to use imp to load the .so from the subdirectory.
        # The module name MUST match the C init function (initltc_scrypt).
        import imp
        _mod_info = imp.find_module('ltc_scrypt', [_ext_dir])
        _c_ext = imp.load_module('ltc_scrypt', *_mod_info)
        getPoWHash = _c_ext.getPoWHash
    except (ImportError, OSError):
        raise ImportError(
            "Neither py-scrypt package nor litecoin_scrypt C extension found.\n"
            "Install one of:\n"
            "  pip install 'scrypt>=0.8.0,<=0.8.22'  (recommended, maintained package)\n"
            "  cd litecoin_scrypt && python setup.py install  (legacy C extension)\n"
        )
