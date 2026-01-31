# Copyright (c) 2018 Robert LeBlanc
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from math import convertbits

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

# Cashaddr format
#
# <prefix>:<hash_in_bech32>
#
# Unlike bech32, cashaddr stores it's header in an 8-bit byte instead of 5 bits.
# You have to convert the 5-bit bech32 to bytes in order to read the header.
# The checksum for cashaddr is 40 bits so it makes it a nice round number for
# both 8-bit (5 values) and 5-bit (8 values) values. When converting the payload
# verify the checksum, then drop the checksum when converting from 5-bits to
# 8-bits. Since the payload is padded, if you try to convert the payload and
# checksum at the same time and then drop the last 5 bytes, you will get an
# incorrect payload.
#
# The expanded format is as follows:
#
# <prefix>:<header_8_bits><payload_variable_length><checksum_40_bits>
#
# Header:
#
# The most significant bit is reserved and must be 0.
# The next four bits are the type bits. Only the following is valid:
#   0: PUBKEY Type
#   1: SCRIPT Type
#  15: UNKNOWN (not listed in the spec, but the spec includes valid addresses
#               with type 15)
# The last three bits indicate the hash size excluding the header and the checksum.
#   +-----------+-----------+
#   | Size bits | Hash bits |
#   +-----------+-----------+
#   |     0     |    160    |
#   |     1     |    192    |
#   |     2     |    224    |
#   |     3     |    256    |
#   |     4     |    320    |
#   |     5     |    384    |
#   |     6     |    448    |
#   |     7     |    512    |
#   +-----------+-----------+
#
# Payload:
#
# The payload length is specified by the size in the header and must match.
#
# Checksum:
#
# The 40-bits of checksum are only used in validating the bech32 hash. Although
# the checksum is powerful enough to fix minor errors, since we are dealing
# with money, it is best to just error if the checksum does not match and have
# the hash manually verified to find the error.

def polymod(values):
    """Internal function that computes the cashaddr checksum."""
    generator = [0x98f2bc8e61, 0x79b76d99e2, 0xf33e5fb3c4, 0xae2eabe2a8, 0x1e4f43e470]
    chk = 1
    for value in values:
        top = chk >> 35
        chk = ((chk & 0x07ffffffff) << 5) ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk ^ 1

def expand_prefix(prefix):
    """Expand the address prefix into values for checksum computation."""
    data = [ord(x) & 31 for x in prefix] + [0]
    return [ord(x) & 31 for x in prefix] + [0]

def verify_checksum(prefix, data):
    """Verify a checksum given prefix and converted data characters."""
    return polymod(expand_prefix(prefix) + data) == 0

def create_checksum(prefix, data):
    """Compute the checksum values given prefix and data."""
    values = expand_prefix(prefix) + data
    out = polymod(values + [0, 0, 0, 0, 0, 0, 0, 0])
    return [(out >> 5 * (7 - i)) & 31 for i in range(8)]

def assemble(prefix, data):
    """Compute a cashaddr string given prefix and data values."""
    combined = data + create_checksum(prefix, data)
    return prefix + ':' + ''.join([CHARSET[d] for d in combined])

def valid_version(data):
    """Check that the version is correct for the data.
        Do not include the checksum."""
    converted = convertbits(data, 5, 8, False)
    if converted == None:
        return False
    ver = converted[0]
    # First bit is reserved
    if ver & (1 << 8):
        return False
    # Last three bits specify the length we expect
    bits = 160 + (ver & 3) * 32
    # Bit six is a multiplier
    if ver & 4:
        bits *= 2
    if (len(converted) - 1) != (bits / 8):
        return False
    return True

def disassemble(cashaddr, default_prefix):
    """Validate a cashaddr string, and determine prefix and data."""
    if ((any(ord(x) < 33 or ord(x) > 126 for x in cashaddr)) or
            (cashaddr.lower() != cashaddr and cashaddr.upper() != cashaddr)):
        return (None, None)
    cashaddr = cashaddr.lower()
    pos = cashaddr.rfind(':')
    if pos < 0:
        cashaddr = "%s:%s" % (default_prefix.lower(), cashaddr)
        pos = len(default_prefix)
    if len(cashaddr) - pos - 1 <= 8 or len(cashaddr) - pos - 1 > 112:
        return (None, None)
    if not all(x in CHARSET for x in cashaddr[pos+1:]):
        return (None, None)
    prefix = cashaddr[:pos]
    data = [CHARSET.find(x) for x in cashaddr[pos+1:]]
    if not valid_version(data[:-8]):
        return (None, None)
    if not verify_checksum(prefix, data):
        return (None, None)
    return (prefix, data[:-8])

def decode(prefix, addr):
    """Decode a cashaddr address."""
    prefixgot, data = disassemble(addr, prefix)
    if prefixgot != prefix:
        return (None, None)
    decoded = convertbits(data, 5, 8, False)
    if decoded is None or not len(decoded):
        return (None, None)
    ver = (decoded[0] & 0x78) >> 3
    return (ver, decoded[1:])

def encode(prefix, ver, data):
    """Encode a cashaddr address."""
    if not len(data) in [20, 24, 28, 32, 40, 48, 56, 64]:
        # Make sure length is valid.
        return None
    if not (0 <= ver <= 1 or ver == 15):
        # Only versions (type) 1,2 and 15 are supported.
        return None
    ver <<= 3
    dlen = 0
    tmp = len(data) * 8
    if tmp > 256:
        dlen ^= 0x04
        tmp /= 2
    dlen += (tmp - 160) / 32
    ver += dlen
    bits = convertbits([ver] + data, 8, 5)
    ret = assemble(prefix, bits)
    if decode(prefix, ret) == (None, None):
        return None
    return ret
