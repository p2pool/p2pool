"""
P2Pool Share-Based Messaging System (V36 Integrated)

Messages are embedded directly in V36 shares via ref_hash extension.
Protected by share PoW -- only miners who produce valid shares can send messages.
This prevents spam without any additional infrastructure.

Architecture:
- Messages stored in V36 ref_type as 'message_data' field
- Included in ref_hash computation (PoW-protected)
- NOT included in coinbase/gentx (never written to parent blockchain)
- Propagated via existing p2pool P2P share protocol (no new message types)
- Signed with derived signing keys (master private key stays secret)

Derived Signing Key Scheme:
  signing_privkey = HMAC-SHA256(master_privkey, "p2pool-msg-v1" || key_index_le32)
  signing_pubkey  = secp256k1_point(signing_privkey)
  signing_id      = HASH160(signing_pubkey_compressed)

  - master_privkey: miner's payout address private key (NEVER exposed)
  - key_index: uint32, incremented for key rotation
  - signing_id: 20-byte identifier announced in shares, used for verification
  - Key rotation: new key_index -> new signing_privkey -> old signatures unverifiable
  - Trust anchor: must mine a valid share to announce a signing_id (PoW anti-spam)

Message Types:
  0x01 NODE_STATUS    - Node health/capability announcements
  0x02 MINER_MESSAGE  - Miner-to-miner text messages (signed)
  0x03 POOL_ANNOUNCE  - Node operator announcements
  0x04 VERSION_SIGNAL - Extended version signaling with metadata
  0x05 MERGED_STATUS  - Merged mining chain status
  0x10 EMERGENCY      - Security/upgrade alerts

Wire Format (per message in share ref_data):
  [type:1] [flags:1] [timestamp:4] [payload_len:2] [payload:N]
  [signing_id:20] [sig_len:1] [signature:M]

Envelope Format (in share ref_type.message_data):
  [version:1] [flags:1] [msg_count:1] [announcement_len:1]
  [signing_key_announcement:57?]  (signing_id:20 + key_index:4 + pubkey:33)
  [message1] [message2] ...
"""

from __future__ import division

import os
import struct
import time
import hashlib
import hmac
import json


# ============================================================================
# Constants
# ============================================================================

# Message types
MSG_NODE_STATUS = 0x01
MSG_MINER_MESSAGE = 0x02
MSG_POOL_ANNOUNCE = 0x03
MSG_VERSION_SIGNAL = 0x04
MSG_MERGED_STATUS = 0x05
MSG_EMERGENCY = 0x10
MSG_TRANSITION_SIGNAL = 0x20      # Protocol-level version transition alert

# Message flags
FLAG_HAS_SIGNATURE = 0x01
FLAG_BROADCAST = 0x02
FLAG_PERSISTENT = 0x04
FLAG_PROTOCOL_AUTHORITY = 0x08    # Signed by a donation script key (forrestv or maintainer)

# Limits
MAX_MESSAGE_PAYLOAD = 220       # bytes per message payload
MAX_MESSAGES_PER_SHARE = 3      # max messages embedded in one share
MAX_TOTAL_MESSAGE_BYTES = 512   # total bytes for all messages in one share
MAX_MESSAGE_AGE = 24 * 60 * 60  # fallback; callers should pass CHAIN_LENGTH * SHARE_PERIOD
MAX_MESSAGE_HISTORY = 1000      # max messages to keep in memory

# Message Weight Units (MWU) -- share-cost economics
MWU_HEADER = 8                    # fixed cost per message header
MWU_PER_PAYLOAD_BYTE = 1          # 1 MWU per payload byte
MWU_PER_SIGNATURE_BYTE = 2        # signatures are expensive to verify
MWU_ANNOUNCEMENT = 171            # 57 bytes * 3 MWU/byte for key announcement

MAX_MWU_PER_SHARE = 1024          # hard cap per share
FREE_MWU_ALLOWANCE = 64           # small status messages are free (no sacrifice)
MWU_PER_SACRIFICE = 256           # MWU capacity bought per sacrifice unit
# Sacrifice shares -- miner mines shares for node operator & dev fund to pay for messaging
# Split follows --give-author parameter (not hardcoded):
#   node_operator_fraction = 1.0 - (give_author_percentage / 100)
#   donation_fraction      = give_author_percentage / 100
SACRIFICE_TAG_SIZE = 20           # signing_id embedded in sacrifice share ref_data

# Messaging eligibility -- require donation marker in recent shares
MIN_SHARES_FOR_MESSAGING = 10    # check this many recent shares from miner
REQUIRED_DONATION_SHARES = 10    # all must include donation script marker

# Message fragmentation
MAX_MESSAGE_FRAGMENTS = 8         # max fragments per split message
FRAGMENT_TIMEOUT = 300            # 5 minutes to receive all fragments
MAX_REASSEMBLED_SIZE = 1600       # max bytes after reassembly (8 * 200)
FRAGMENT_HEADER_SIZE = 6          # msg_id(4) + frag_index(1) + frag_total(1)

# MWU rate limiting
ROLLING_MWU_WINDOW = 3600         # 1 hour rate limit window (seconds)
MAX_MWU_PER_HOUR = 4096           # per signing_id

# Signing key derivation
SIGNING_KEY_DOMAIN = b'p2pool-msg-v1'  # Domain separator for HMAC derivation
SIGNING_KEY_ANNOUNCEMENT_SIZE = 57     # signing_id(20) + key_index(4) + pubkey(33)

# Message type names for display
MESSAGE_TYPE_NAMES = {
    MSG_NODE_STATUS: 'NODE_STATUS',
    MSG_MINER_MESSAGE: 'MINER_MESSAGE',
    MSG_POOL_ANNOUNCE: 'POOL_ANNOUNCE',
    MSG_VERSION_SIGNAL: 'VERSION_SIGNAL',
    MSG_MERGED_STATUS: 'MERGED_STATUS',
    MSG_EMERGENCY: 'EMERGENCY',
    MSG_TRANSITION_SIGNAL: 'TRANSITION_SIGNAL',
}


# ============================================================================
# Protocol Authority — Donation Script Trust Anchor
# ============================================================================
#
# V36 shares mine under COMBINED_DONATION_SCRIPT (P2SH wrapping 1-of-2 P2MS).
# The two keys in the redeem script are the protocol authority signers:
#   - forrestv (original p2pool author)
#   - frstrtr maintainer  (p2pool-merged-v36)
#
# Messages signed by either key carry FLAG_PROTOCOL_AUTHORITY.  These are
# the only messages that can issue TRANSITION_SIGNAL alerts that nodes will
# treat as authoritative upgrade/migration guidance.
#
# This trust model works because:
#   1. Every V36 share's coinbase pays to COMBINED_DONATION_SCRIPT.
#   2. The redeem script is hardcoded — changing it changes gentx_before_refhash
#      and invalidates all V36 shares.  So the pubkeys cannot be substituted.
#   3. A message signed by one of these keys + embedded in a valid share =
#      PoW-protected + authority-signed.  Double trust anchor.
#
# The compressed pubkeys are extracted directly from
# COMBINED_DONATION_REDEEM_SCRIPT in data.py:
#   OP_1 PUSH33 <forrestv_compressed> PUSH33 <maintainer_compressed> OP_2 OP_CHECKMULTISIG
# ============================================================================

# Compressed public keys from COMBINED_DONATION_REDEEM_SCRIPT
# forrestv's key (original p2pool author)
DONATION_PUBKEY_FORRESTV = '03ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1'.decode('hex')
# frstrtr maintainer key
DONATION_PUBKEY_MAINTAINER = '02fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a'.decode('hex')
# Set of both for fast lookup
DONATION_AUTHORITY_PUBKEYS = frozenset([DONATION_PUBKEY_FORRESTV, DONATION_PUBKEY_MAINTAINER])


# ============================================================================
# Crypto helpers -- isolated for easy replacement/testing
# ============================================================================

def _derive_pubkey(privkey_bytes):
    """
    Derive secp256k1 public key from private key bytes.
    Returns (uncompressed_pubkey, compressed_pubkey).
    """
    try:
        import coincurve
        pk = coincurve.PrivateKey(privkey_bytes)
        compressed = pk.public_key.format(compressed=True)
        uncompressed = pk.public_key.format(compressed=False)
        return uncompressed, compressed
    except ImportError:
        pass

    try:
        import ecdsa
        sk = ecdsa.SigningKey.from_string(privkey_bytes, curve=ecdsa.SECP256k1)
        vk = sk.get_verifying_key()
        uncompressed = b'\x04' + vk.to_string()
        # Compress: prefix 02 if y is even, 03 if odd
        x = vk.to_string()[:32]
        y = vk.to_string()[32:]
        prefix = b'\x02' if (ord(y[-1:]) % 2 == 0) else b'\x03'
        compressed = prefix + x
        return uncompressed, compressed
    except ImportError:
        pass

    raise ImportError('No ECDSA library available (need coincurve or ecdsa)')


def _ecdsa_sign(privkey_bytes, message_hash):
    """Sign a 32-byte hash with secp256k1 ECDSA. Returns DER-encoded signature."""
    try:
        import coincurve
        pk = coincurve.PrivateKey(privkey_bytes)
        return pk.sign(message_hash, hasher=None)
    except ImportError:
        pass

    try:
        import ecdsa
        sk = ecdsa.SigningKey.from_string(privkey_bytes, curve=ecdsa.SECP256k1)
        return sk.sign_digest(message_hash, sigencode=ecdsa.util.sigencode_der)
    except ImportError:
        pass

    return b''


def _ecdsa_verify(pubkey_compressed, message_hash, signature):
    """Verify ECDSA signature against compressed public key."""
    try:
        import coincurve
        pk = coincurve.PublicKey(pubkey_compressed)
        return pk.verify(signature, message_hash, hasher=None)
    except ImportError:
        pass

    try:
        import ecdsa
    except ImportError:
        ecdsa = None

    if ecdsa is not None:
        try:
            if pubkey_compressed[0:1] in (b'\x02', b'\x03'):
                vk = ecdsa.VerifyingKey.from_string(
                    pubkey_compressed, curve=ecdsa.SECP256k1)
            else:
                vk = ecdsa.VerifyingKey.from_string(
                    pubkey_compressed[1:], curve=ecdsa.SECP256k1)
            return vk.verify_digest(signature, message_hash,
                                    sigdecode=ecdsa.util.sigdecode_der)
        except ecdsa.BadSignatureError:
            pass
        except Exception:
            pass

    return False


def _hash160(data):
    """RIPEMD160(SHA256(data)) -- standard Bitcoin address hash."""
    sha = hashlib.sha256(data).digest()
    try:
        ripemd = hashlib.new('ripemd160')
        ripemd.update(sha)
        return ripemd.digest()
    except (ValueError, AttributeError):
        # Fallback for platforms without ripemd160
        try:
            from p2pool.bitcoin.data import hash160
            return hash160(data)
        except ImportError:
            raise NotImplementedError('No RIPEMD-160 available')


# ============================================================================
# Message Encryption Layer
# ============================================================================
#
# V36 system messages are SIGNED (ECDSA) and ENCRYPTED before embedding in
# shares.  This prevents passive observers from identifying transition
# messages in raw share data, and provides an additional authenticity layer:
# successful decryption + signature verification = double proof of authority.
#
# Encryption scheme (sign-then-encrypt):
#
#   SENDER (authority, has privkey d, pubkey Q):
#     1. plaintext = message payload (JSON)
#     2. signature = ECDSA_sign(d, SHA256(plaintext))
#     3. inner = pack(plaintext, signature)
#     4. nonce = random 16 bytes
#     5. enc_key = HMAC-SHA256(Q, nonce)              ← key derivation
#     6. stream = SHA256(enc_key||0) || SHA256(enc_key||1) || ...
#     7. ciphertext = inner XOR stream
#     8. mac = HMAC-SHA256(enc_key, ciphertext)       ← integrity
#     9. envelope = [version(1)] [nonce(16)] [mac(32)] [ciphertext(N)]
#
#   RECEIVER (any node, knows Q_forrestv and Q_maintainer):
#     For each Q in DONATION_AUTHORITY_PUBKEYS:
#       1. enc_key = HMAC-SHA256(Q, nonce)
#       2. mac_check = HMAC-SHA256(enc_key, ciphertext)
#       3. If mac_check != mac: try next Q
#       4. stream = SHA256(enc_key||0) || SHA256(enc_key||1) || ...
#       5. inner = ciphertext XOR stream
#       6. Unpack plaintext + signature from inner
#       7. Verify: ECDSA_verify(Q, SHA256(plaintext), signature)
#       8. If valid → authenticated message from this authority key
#
# Why this works for broadcast:
#   - The encryption key is derived from a KNOWN pubkey + random nonce
#   - Any p2pool node with the pubkey constants can derive the key
#   - Non-p2pool observers cannot (they don't know the key derivation formula)
#   - The MAC ensures ciphertext integrity (tampered data fails MAC check)
#   - The signature ensures authenticity (only privkey holder could sign)
#   - Together: encrypted + integrity-protected + authenticated
#
# V37+ will extend this with ECIES for private miner-to-miner messages
# where only the intended recipient (with their privkey) can decrypt.
# ============================================================================

ENCRYPTED_ENVELOPE_VERSION = 0x01   # V36 authenticated encryption
ENCRYPTION_NONCE_SIZE = 16
ENCRYPTION_MAC_SIZE = 32
ENCRYPTION_HEADER_SIZE = 1 + ENCRYPTION_NONCE_SIZE + ENCRYPTION_MAC_SIZE  # 49 bytes


def _derive_encryption_key(authority_pubkey, nonce):
    """
    Derive symmetric encryption key from authority pubkey + random nonce.

    The pubkey acts as a "group key" — any node with the same pubkey constant
    can derive the same encryption key given the nonce.

    Returns 32-byte key.
    """
    return hmac.new(authority_pubkey, nonce, hashlib.sha256).digest()


def _generate_stream(enc_key, length):
    """
    Generate a deterministic byte stream of `length` bytes from enc_key.

    Uses counter-mode SHA256: stream = SHA256(key||0) || SHA256(key||1) || ...
    """
    stream = b''
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(enc_key + struct.pack('<I', counter)).digest()
        stream += block
        counter += 1
    return stream[:length]


def _xor_bytes(data, stream):
    """XOR data with stream of equal or greater length."""
    return b''.join(chr(ord(a) ^ ord(b)) for a, b in zip(data, stream))


def encrypt_message_data(inner_data, authority_pubkey):
    """
    Encrypt packed message data for embedding in a share.

    Args:
        inner_data: packed bytes (messages with signatures)
        authority_pubkey: 33-byte compressed pubkey used for key derivation

    Returns:
        encrypted envelope bytes:
        [version:1] [nonce:16] [mac:32] [ciphertext:N]
    """
    import os as _os

    if not inner_data:
        return b''

    if authority_pubkey not in DONATION_AUTHORITY_PUBKEYS:
        raise ValueError('encrypt_message_data: pubkey not in DONATION_AUTHORITY_PUBKEYS')

    nonce = _os.urandom(ENCRYPTION_NONCE_SIZE)
    enc_key = _derive_encryption_key(authority_pubkey, nonce)

    # Encrypt
    stream = _generate_stream(enc_key, len(inner_data))
    ciphertext = _xor_bytes(inner_data, stream)

    # MAC over ciphertext (encrypt-then-MAC)
    mac = hmac.new(enc_key, ciphertext, hashlib.sha256).digest()

    return (chr(ENCRYPTED_ENVELOPE_VERSION) + nonce + mac + ciphertext)


def decrypt_message_data(encrypted_envelope):
    """
    Try to decrypt an encrypted message envelope using known authority pubkeys.

    Tries each DONATION_AUTHORITY_PUBKEY until MAC verification succeeds.

    Args:
        encrypted_envelope: bytes from share's message_data field

    Returns:
        (decrypted_inner_data, authority_pubkey) on success
        (None, None) if decryption fails for all authority keys

    This provides authentication: if MAC succeeds with a specific pubkey,
    the message was encrypted by the holder of that pubkey's private key
    (because only they would use that pubkey for key derivation).
    """
    if not encrypted_envelope or len(encrypted_envelope) < ENCRYPTION_HEADER_SIZE + 1:
        return None, None

    version = ord(encrypted_envelope[0])
    if version != ENCRYPTED_ENVELOPE_VERSION:
        return None, None

    nonce = encrypted_envelope[1:1 + ENCRYPTION_NONCE_SIZE]
    mac_received = encrypted_envelope[1 + ENCRYPTION_NONCE_SIZE:
                                      1 + ENCRYPTION_NONCE_SIZE + ENCRYPTION_MAC_SIZE]
    ciphertext = encrypted_envelope[1 + ENCRYPTION_NONCE_SIZE + ENCRYPTION_MAC_SIZE:]

    if not ciphertext:
        return None, None

    for pubkey in DONATION_AUTHORITY_PUBKEYS:
        enc_key = _derive_encryption_key(pubkey, nonce)

        # Verify MAC first (fast reject for wrong key)
        mac_computed = hmac.new(enc_key, ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(mac_computed, mac_received):
            continue  # Wrong key — try next

        # MAC matches — decrypt
        stream = _generate_stream(enc_key, len(ciphertext))
        inner_data = _xor_bytes(ciphertext, stream)

        return inner_data, pubkey

    return None, None  # No authority key matched


# ============================================================================
# Derived Signing Key
# ============================================================================

class DerivedSigningKey(object):
    """
    Signing key derived from miner's master private key via HMAC.

    The master private key (payout address key) is NEVER exposed.
    Instead, a one-way derived signing key is used for message signing.

    Derivation:
      signing_privkey = HMAC-SHA256(master_privkey, "p2pool-msg-v1" || key_index_le32)
      signing_pubkey  = secp256k1_point(signing_privkey)
      signing_id      = HASH160(signing_pubkey_compressed)

    Key rotation:
      Increment key_index to generate a new signing key.
      Old messages signed with the previous key become unverifiable.
      The new signing_id is announced in the miner's next share.
    """

    __slots__ = ['key_index', '_signing_privkey', '_signing_pubkey',
                 '_signing_pubkey_compressed', 'signing_id']

    def __init__(self, master_privkey_bytes, key_index=0):
        """
        Derive a signing key from the master private key.

        Args:
            master_privkey_bytes: 32-byte master private key (payout address key)
            key_index: uint32 rotation index (0 = first key, 1 = rotated, etc.)
        """
        if len(master_privkey_bytes) != 32:
            raise ValueError('Master private key must be 32 bytes, got %d' %
                             len(master_privkey_bytes))

        self.key_index = key_index

        # Derive signing private key via HMAC-SHA256
        # domain = "p2pool-msg-v1" || key_index as little-endian uint32
        domain = SIGNING_KEY_DOMAIN + struct.pack('<I', key_index)
        self._signing_privkey = hmac.new(
            master_privkey_bytes, domain, hashlib.sha256
        ).digest()

        # Derive public key and signing_id
        self._signing_pubkey, self._signing_pubkey_compressed = \
            _derive_pubkey(self._signing_privkey)

        # signing_id = HASH160(compressed_pubkey)
        self.signing_id = _hash160(self._signing_pubkey_compressed)

    def sign(self, message_hash):
        """
        Sign a 32-byte message hash with the derived signing key.
        Returns DER-encoded ECDSA signature bytes.
        """
        return _ecdsa_sign(self._signing_privkey, message_hash)

    def get_announcement(self):
        """
        Get the signing key announcement dict to embed in a share.

        This is what other nodes use to verify our signatures:
        - signing_id (20 bytes): HASH160 identifier
        - key_index (4 bytes): rotation counter
        - signing_pubkey (33 bytes): compressed public key for verification

        Total: 57 bytes in share ref_data
        """
        return {
            'signing_id': self.signing_id,
            'key_index': self.key_index,
            'signing_pubkey': self._signing_pubkey_compressed,
        }

    def pack_announcement(self):
        """
        Pack signing key announcement for embedding in share ref_data.
        Format: [signing_id:20] [key_index:4] [signing_pubkey:33] = 57 bytes
        """
        return (
            self.signing_id +
            struct.pack('<I', self.key_index) +
            self._signing_pubkey_compressed
        )

    @staticmethod
    def unpack_announcement(data, offset=0):
        """
        Unpack signing key announcement from share ref_data.
        Returns (signing_id, key_index, signing_pubkey, bytes_consumed).
        Returns (None, 0, None, 0) on failure.
        """
        if len(data) - offset < SIGNING_KEY_ANNOUNCEMENT_SIZE:
            return None, 0, None, 0

        signing_id = data[offset:offset + 20]
        key_index = struct.unpack_from('<I', data, offset + 20)[0]
        signing_pubkey = data[offset + 24:offset + 57]

        # Verify signing_id matches the pubkey
        expected_id = _hash160(signing_pubkey)
        if expected_id != signing_id:
            return None, 0, None, SIGNING_KEY_ANNOUNCEMENT_SIZE

        return signing_id, key_index, signing_pubkey, SIGNING_KEY_ANNOUNCEMENT_SIZE


# ============================================================================
# Signing Key Registry
# ============================================================================

class SigningKeyRegistry(object):
    """
    Registry of known signing keys, learned from verified shares.

    Each miner's share carries their (signing_id, key_index, signing_pubkey).
    When a miner rotates their key (increments key_index), the old signing_id
    is marked as revoked. Messages signed with revoked keys are rejected.

    Trust model:
    - A signing key is trusted if it was announced in a verified share
    - If a miner announces a higher key_index, all lower key_indexes are revoked
    - Share PoW prevents announcement spam (must mine a valid share to announce)
    """

    def __init__(self):
        # {miner_address: {signing_id_hex: {key_index, signing_pubkey, first_seen,
        #                                    share_hash, revoked}}}
        self.keys = {}
        # {signing_id_hex: miner_address} -- reverse lookup
        self.id_to_address = {}
        # {miner_address: current_key_index} -- highest known key_index per miner
        self.current_key_index = {}

    def register_key(self, miner_address, signing_id, key_index, signing_pubkey,
                     share_hash=None, timestamp=None):
        """
        Register a signing key announcement from a verified share.

        If key_index is higher than the previously known index for this miner,
        all older keys are revoked (key rotation).

        Returns True if this is a new or updated key.
        """
        signing_id_hex = signing_id.encode('hex') if isinstance(
            signing_id, bytes) else signing_id

        if miner_address not in self.keys:
            self.keys[miner_address] = {}
            self.current_key_index[miner_address] = -1

        # Check if this is a key rotation (higher key_index)
        if key_index > self.current_key_index.get(miner_address, -1):
            # Revoke all older keys for this miner
            for old_id, old_info in self.keys[miner_address].items():
                if old_info['key_index'] < key_index:
                    old_info['revoked'] = True

            self.current_key_index[miner_address] = key_index

        # Register the key (or update if already known)
        is_new = signing_id_hex not in self.keys[miner_address]
        self.keys[miner_address][signing_id_hex] = {
            'key_index': key_index,
            'signing_pubkey': signing_pubkey,
            'first_seen': timestamp or time.time(),
            'share_hash': share_hash,
            'revoked': key_index < self.current_key_index.get(miner_address, 0),
        }

        self.id_to_address[signing_id_hex] = miner_address
        return is_new

    def is_key_valid(self, signing_id):
        """Check if a signing_id is known and not revoked."""
        signing_id_hex = signing_id.encode('hex') if isinstance(
            signing_id, bytes) else signing_id

        miner_address = self.id_to_address.get(signing_id_hex)
        if miner_address is None:
            return False

        key_info = self.keys.get(miner_address, {}).get(signing_id_hex)
        if key_info is None:
            return False

        return not key_info.get('revoked', False)

    def get_pubkey_for_id(self, signing_id):
        """Get the compressed public key for a signing_id, or None if unknown/revoked."""
        signing_id_hex = signing_id.encode('hex') if isinstance(
            signing_id, bytes) else signing_id

        miner_address = self.id_to_address.get(signing_id_hex)
        if miner_address is None:
            return None

        key_info = self.keys.get(miner_address, {}).get(signing_id_hex)
        if key_info is None or key_info.get('revoked', False):
            return None

        return key_info['signing_pubkey']

    def get_miner_for_id(self, signing_id):
        """Get the miner address associated with a signing_id."""
        signing_id_hex = signing_id.encode('hex') if isinstance(
            signing_id, bytes) else signing_id
        return self.id_to_address.get(signing_id_hex)

    def get_miner_current_key(self, miner_address):
        """Get the current (non-revoked) signing key info for a miner."""
        if miner_address not in self.keys:
            return None

        current_idx = self.current_key_index.get(miner_address, -1)
        for signing_id_hex, key_info in self.keys[miner_address].items():
            if key_info['key_index'] == current_idx and \
                    not key_info.get('revoked', False):
                return {
                    'signing_id': signing_id_hex,
                    'key_index': key_info['key_index'],
                    'signing_pubkey': key_info['signing_pubkey'],
                }
        return None

    def to_json(self):
        """Serialize registry for API/debugging."""
        result = {}
        for miner_addr, keys in self.keys.items():
            result[miner_addr] = {
                'current_key_index': self.current_key_index.get(miner_addr, -1),
                'keys': {}
            }
            for signing_id_hex, key_info in keys.items():
                result[miner_addr]['keys'][signing_id_hex] = {
                    'key_index': key_info['key_index'],
                    'revoked': key_info.get('revoked', False),
                    'first_seen': key_info.get('first_seen', 0),
                }
        return result


# ============================================================================
# Share Message
# ============================================================================

class ShareMessage(object):
    """A single message embedded in a p2pool share's ref_data."""

    __slots__ = ['msg_type', 'flags', '_wire_flags', 'timestamp', 'payload',
                 'signature', 'signing_id', 'sender_address', 'share_hash',
                 'verified']

    def __init__(self, msg_type, payload, flags=FLAG_BROADCAST | FLAG_PERSISTENT,
                 timestamp=None, signature=b'', signing_id=None,
                 sender_address=None, share_hash=None):
        self.msg_type = msg_type
        self.flags = flags
        self._wire_flags = flags  # For message_hash(); overwritten by unpack()
        self.timestamp = timestamp or int(time.time())
        self.payload = payload if isinstance(payload, bytes) else payload.encode('utf-8')
        self.signature = signature
        self.signing_id = signing_id    # 20-byte HASH160 of signing pubkey
        self.sender_address = sender_address
        self.share_hash = share_hash
        self.verified = False

    @property
    def type_name(self):
        return MESSAGE_TYPE_NAMES.get(self.msg_type, 'UNKNOWN_0x%02x' % self.msg_type)

    @property
    def has_signature(self):
        return bool(self.flags & FLAG_HAS_SIGNATURE)

    @property
    def is_broadcast(self):
        return bool(self.flags & FLAG_BROADCAST)

    @property
    def is_persistent(self):
        return bool(self.flags & FLAG_PERSISTENT)

    @property
    def is_protocol_authority(self):
        return bool(self.flags & FLAG_PROTOCOL_AUTHORITY)

    @property
    def age(self):
        return time.time() - self.timestamp

    def message_hash(self):
        """
        Double-SHA256 of message content.
        Used for signing, verification, and deduplication.

        Uses the original wire flags (including FLAG_PROTOCOL_AUTHORITY if
        present) so the hash matches what the signer computed.  The public
        self.flags has the authority bit stripped for security (must be
        earned via verify), but the hash must be computed over the same
        flag byte that was signed.
        """
        flags = getattr(self, '_wire_flags', self.flags)
        data = struct.pack('<BBI', self.msg_type, flags, self.timestamp) + \
            self.payload
        return hashlib.sha256(hashlib.sha256(data).digest()).digest()

    def sign(self, derived_key):
        """
        Sign this message with a DerivedSigningKey.
        Sets the signature, signing_id, and FLAG_HAS_SIGNATURE flag.
        """
        self.flags |= FLAG_HAS_SIGNATURE
        self._wire_flags = self.flags  # Keep in sync for message_hash()
        self.signing_id = derived_key.signing_id
        self.signature = derived_key.sign(self.message_hash())

    def verify(self, key_registry):
        """
        Verify this message's signature against the signing key registry.

        Returns True if:
        1. Message has FLAG_HAS_SIGNATURE and non-empty signature
        2. signing_id is known in the registry (announced in a verified share)
        3. signing_id is not revoked (key hasn't been rotated to a higher index)
        4. ECDSA signature is valid against the registered public key

        If the signing pubkey is one of the DONATION_AUTHORITY_PUBKEYS,
        FLAG_PROTOCOL_AUTHORITY is set on the message.
        """
        if not self.has_signature or not self.signing_id or not self.signature:
            self.verified = False
            return False

        # Look up the public key for this signing_id
        pubkey = key_registry.get_pubkey_for_id(self.signing_id)
        if pubkey is None:
            self.verified = False
            return False

        # Verify ECDSA signature
        msg_hash = self.message_hash()
        self.verified = _ecdsa_verify(pubkey, msg_hash, self.signature)

        # Also populate sender_address from registry
        if self.verified:
            self.sender_address = key_registry.get_miner_for_id(self.signing_id)
            # Check if this is a protocol authority key
            if pubkey in DONATION_AUTHORITY_PUBKEYS:
                self.flags |= FLAG_PROTOCOL_AUTHORITY

        return self.verified

    def verify_authority_direct(self, compressed_pubkey):
        """
        Verify this message was signed directly by a specific pubkey,
        bypassing the signing key registry.

        This is used for TRANSITION_SIGNAL messages that are signed directly
        by one of the COMBINED_DONATION_SCRIPT keys (forrestv or maintainer)
        rather than through the derived-key registry path.

        Returns True if signature is valid AND pubkey is a donation authority.
        """
        if not self.signature or not compressed_pubkey:
            self.verified = False
            return False

        if compressed_pubkey not in DONATION_AUTHORITY_PUBKEYS:
            self.verified = False
            return False

        msg_hash = self.message_hash()
        self.verified = _ecdsa_verify(compressed_pubkey, msg_hash, self.signature)

        if self.verified:
            self.flags |= FLAG_PROTOCOL_AUTHORITY | FLAG_HAS_SIGNATURE

        return self.verified

    def pack(self):
        """
        Serialize message to bytes for embedding in share ref_data.

        Wire format:
          [type:1] [flags:1] [timestamp:4] [payload_len:2] [payload:N]
          [signing_id:20] [sig_len:1] [signature:M]

        Min size: 8 + 0 + 20 + 1 + 0 = 29 bytes (empty payload, no signature)
        Max size: 8 + 220 + 20 + 1 + 73 = 322 bytes
        """
        if len(self.payload) > MAX_MESSAGE_PAYLOAD:
            raise ValueError('Message payload too large: %d > %d' % (
                len(self.payload), MAX_MESSAGE_PAYLOAD))

        sig = self.signature or b''
        if len(sig) > 73:  # Max DER-encoded ECDSA signature
            raise ValueError('Signature too large: %d' % len(sig))

        sid = self.signing_id or (b'\x00' * 20)

        return (
            struct.pack('<BBIH', self.msg_type, self.flags, self.timestamp,
                        len(self.payload)) +
            self.payload +
            sid +                           # 20 bytes signing_id
            struct.pack('<B', len(sig)) +
            sig
        )

    @classmethod
    def unpack(cls, data, offset=0):
        """
        Deserialize message from bytes.
        Returns (message, new_offset).
        """
        if len(data) - offset < 8:
            raise ValueError('Message data too short: %d bytes at offset %d' % (
                len(data) - offset, offset))

        msg_type, flags, timestamp, payload_len = struct.unpack_from(
            '<BBIH', data, offset)
        offset += 8

        if payload_len > MAX_MESSAGE_PAYLOAD:
            raise ValueError('Payload length %d exceeds maximum %d' % (
                payload_len, MAX_MESSAGE_PAYLOAD))

        if len(data) - offset < payload_len:
            raise ValueError('Not enough data for payload: need %d, have %d' % (
                payload_len, len(data) - offset))

        payload = data[offset:offset + payload_len]
        offset += payload_len

        # Read 20-byte signing_id
        if len(data) - offset < 20:
            raise ValueError('Not enough data for signing_id')
        signing_id = data[offset:offset + 20]
        offset += 20

        # Check if signing_id is all zeros (unsigned message)
        if signing_id == b'\x00' * 20:
            signing_id = None

        # Read signature
        if len(data) - offset < 1:
            raise ValueError('Not enough data for signature length')
        sig_len = struct.unpack_from('<B', data, offset)[0]
        offset += 1

        if len(data) - offset < sig_len:
            raise ValueError('Not enough data for signature: need %d, have %d' % (
                sig_len, len(data) - offset))
        signature = data[offset:offset + sig_len] if sig_len > 0 else b''
        offset += sig_len

        msg = cls(
            msg_type=msg_type,
            payload=payload,
            flags=flags & ~FLAG_PROTOCOL_AUTHORITY,  # Strip authority; must be earned via verify
            timestamp=timestamp,
            signature=signature,
            signing_id=signing_id,
        )
        # Preserve original wire flags for message_hash() so signature
        # verification uses the same flags value the signer used.
        msg._wire_flags = flags

        return msg, offset

    def to_dict(self):
        """Convert to JSON-serializable dict for API/display."""
        result = {
            'type': self.type_name,
            'type_id': self.msg_type,
            'timestamp': self.timestamp,
            'age': int(self.age),
            'flags': {
                'signed': self.has_signature,
                'broadcast': self.is_broadcast,
                'persistent': self.is_persistent,
            },
            'verified': self.verified,
        }

        if self.signing_id:
            result['signing_id'] = self.signing_id.encode('hex')

        result['protocol_authority'] = self.is_protocol_authority

        # Decode payload based on message type
        if self.msg_type in (MSG_MINER_MESSAGE, MSG_POOL_ANNOUNCE, MSG_EMERGENCY):
            try:
                result['text'] = self.payload.decode('utf-8')
            except UnicodeDecodeError:
                result['text'] = self.payload.encode('hex')
        elif self.msg_type in (MSG_NODE_STATUS, MSG_MERGED_STATUS,
                               MSG_VERSION_SIGNAL, MSG_TRANSITION_SIGNAL):
            try:
                result['data'] = json.loads(self.payload)
            except (ValueError, TypeError):
                result['raw'] = self.payload.encode('hex')
        else:
            result['raw'] = self.payload.encode('hex')

        if self.sender_address:
            result['sender'] = self.sender_address
        if self.share_hash is not None:
            result['share_hash'] = '%064x' % self.share_hash if isinstance(
                self.share_hash, (int, long)) else str(self.share_hash)

        return result

    def __repr__(self):
        return '<ShareMessage %s sender=%s verified=%s age=%ds %d bytes>' % (
            self.type_name, self.sender_address or '?',
            self.verified, int(self.age), len(self.payload))


# ============================================================================
# Pack/unpack message lists for share embedding
# ============================================================================

def pack_share_messages(messages, signing_key_announcement=None):
    """
    Pack messages into encrypted wire-format bytes for share ref_data.

    The packed messages are signed, then encrypted using the authority pubkey
    that verified the signatures.  The resulting message_data is opaque to
    anyone who doesn't know the DONATION_AUTHORITY_PUBKEYS constants.

    Envelope format (after encryption):
      [version:1] [nonce:16] [mac:32] [ciphertext:N]

    Inner format (before encryption):
      [inner_version:1] [flags:1] [msg_count:1] [announcement_len:1]
      [announcement:N] [messages...]

    SECURITY GATE: Every message MUST carry a valid signature from one of
    the COMBINED_DONATION_SCRIPT authority keys.  Messages that are unsigned
    or signed by a non-authority key are rejected with ValueError.

    Returns encrypted bytes to embed in share ref_type.message_data,
    or empty bytes if nothing to pack.
    """
    if not messages and not signing_key_announcement:
        return b''

    # --- Authority gate: every message must be signed by a donation key ---
    authority_pubkey_used = None
    if messages:
        for msg in messages:
            if not msg.signature:
                raise ValueError(
                    'Message type 0x%02x has no signature -- '
                    'all share-embedded messages must be signed by a '
                    'COMBINED_DONATION_SCRIPT authority key' % msg.msg_type)
            # Always verify against donation authority pubkeys,
            # regardless of what flags say (flags can be spoofed locally).
            # Strip authority flag first, then re-earn it via verification.
            msg.flags &= ~FLAG_PROTOCOL_AUTHORITY
            authority_ok = False
            for pubkey in DONATION_AUTHORITY_PUBKEYS:
                if msg.verify_authority_direct(pubkey):
                    authority_ok = True
                    authority_pubkey_used = pubkey
                    break
            if not authority_ok:
                raise ValueError(
                    'Message type 0x%02x signature does not match any '
                    'COMBINED_DONATION_SCRIPT authority key -- '
                    'refusing to pack' % msg.msg_type)

    if messages and len(messages) > MAX_MESSAGES_PER_SHARE:
        messages = messages[:MAX_MESSAGES_PER_SHARE]

    # Pack inner (plaintext) envelope
    inner_version = 1   # Inner protocol version
    inner_flags = 0
    if signing_key_announcement:
        inner_flags |= 0x01  # Has signing key announcement

    announcement_data = b''
    if signing_key_announcement:
        announcement_data = signing_key_announcement

    msg_count = len(messages) if messages else 0

    inner = struct.pack('<BBBB', inner_version, inner_flags, msg_count,
                        len(announcement_data))
    inner += announcement_data

    if messages:
        for msg in messages:
            inner += msg.pack()

    if len(inner) > MAX_TOTAL_MESSAGE_BYTES:
        raise ValueError('Total message data %d exceeds limit %d' % (
            len(inner), MAX_TOTAL_MESSAGE_BYTES))

    # Encrypt with the authority pubkey that verified the signatures
    if authority_pubkey_used is None:
        # No messages — use first authority key for empty envelope
        authority_pubkey_used = DONATION_PUBKEY_FORRESTV

    return encrypt_message_data(inner, authority_pubkey_used)


def unpack_share_messages(data):
    """
    Decrypt and unpack messages from share ref_data.

    First decrypts the outer encrypted envelope using known DONATION_AUTHORITY_PUBKEYS.
    If decryption succeeds with a specific pubkey, that pubkey is returned as the
    authority that encrypted (and thus authored) the messages — providing an
    additional authenticity layer beyond the ECDSA signatures inside.

    Returns (messages_list, signing_key_info_dict_or_None).

    signing_key_info includes 'authority_pubkey' — the pubkey whose key derivation
    successfully decrypted the envelope, proving it was encrypted by that key holder.
    """
    if not data or len(data) < ENCRYPTION_HEADER_SIZE + 4:
        return [], None

    # Attempt decryption with known authority pubkeys
    inner_data, authority_pubkey = decrypt_message_data(data)
    if inner_data is None:
        # Decryption failed — message was not encrypted by any known authority key
        return [], None

    # Record which authority pubkey successfully decrypted
    signing_key_info = {
        'authority_pubkey': authority_pubkey,
        'encrypted': True,
    }

    # Parse inner (plaintext) envelope
    if len(inner_data) < 4:
        return [], signing_key_info

    inner_version, inner_flags, msg_count, announcement_len = struct.unpack_from(
        '<BBBB', inner_data, 0)
    offset = 4

    if inner_version != 1:
        return [], signing_key_info  # Unknown inner version -- skip gracefully

    # Parse signing key announcement if present
    if inner_flags & 0x01 and announcement_len > 0:
        if len(inner_data) - offset >= announcement_len:
            ann_data = inner_data[offset:offset + announcement_len]
            signing_id, key_index, signing_pubkey, consumed = \
                DerivedSigningKey.unpack_announcement(ann_data)
            if signing_id is not None:
                signing_key_info['signing_id'] = signing_id
                signing_key_info['key_index'] = key_index
                signing_key_info['signing_pubkey'] = signing_pubkey
            offset += announcement_len
        else:
            offset += announcement_len  # Skip malformed announcement

    # Parse messages
    messages = []
    if msg_count > MAX_MESSAGES_PER_SHARE:
        msg_count = MAX_MESSAGES_PER_SHARE

    for i in range(msg_count):
        try:
            msg, new_offset = ShareMessage.unpack(inner_data, offset)
            messages.append(msg)
            offset = new_offset
        except (ValueError, struct.error):
            break  # Malformed message -- keep what we have

    return messages, signing_key_info


# ============================================================================
# Message hash for ref_hash integration
# ============================================================================

def compute_message_data_hash(packed_message_data):
    """
    Compute hash of packed message data for inclusion in ref_hash.

    This is what makes messages PoW-protected:
    ref_hash = merkle(pack(identifier, share_info, message_data_hash))

    If no messages, returns zero hash (32 zero bytes).
    """
    if not packed_message_data:
        return b'\x00' * 32

    return hashlib.sha256(hashlib.sha256(packed_message_data).digest()).digest()


# ============================================================================
# Message Store
# ============================================================================

# ============================================================================
# BanList — node-local content filtering
# ============================================================================

class BanList(object):
    """
    Node-local ban list for filtering messages displayed to this node's users.

    Bans are LOCAL ONLY — they do NOT affect share validation or propagation.
    A banned message is still relayed to peers; it is simply hidden from the
    local API, dashboard, and BBS display.

    Ban types:
      - signing_id:  Ban all messages from a specific signing key
      - address:     Ban all messages from a miner address
      - keyword:     Ban messages containing a keyword (case-insensitive)
      - msg_type:    Ban entire message types (e.g. suppress all chat)

    Persistence:
      Saved to data/<net>/banned_senders.json on change.
      Loaded on startup.
    """

    def __init__(self, persist_path=None):
        self.banned_signing_ids = set()     # hex-encoded signing_id strings
        self.banned_addresses = set()       # miner address strings
        self.banned_keywords = set()        # lowercase keyword strings
        self.banned_types = set()           # msg_type ints (e.g. 0x02)
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def _load(self):
        """Load ban list from disk."""
        if not self._persist_path:
            return
        try:
            with open(self._persist_path, 'r') as f:
                data = json.load(f)
            self.banned_signing_ids = set(data.get('signing_ids', []))
            self.banned_addresses = set(data.get('addresses', []))
            self.banned_keywords = set(data.get('keywords', []))
            self.banned_types = set(data.get('types', []))
        except (IOError, OSError, ValueError):
            pass  # No file or corrupt — start fresh

    def _save(self):
        """Persist ban list to disk."""
        if not self._persist_path:
            return
        try:
            data = {
                'signing_ids': sorted(self.banned_signing_ids),
                'addresses': sorted(self.banned_addresses),
                'keywords': sorted(self.banned_keywords),
                'types': sorted(self.banned_types),
            }
            tmp = self._persist_path + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(data, f, indent=2)
            try:
                os.rename(tmp, self._persist_path)
            except OSError:  # Windows can't overwrite with rename
                os.remove(self._persist_path)
                os.rename(tmp, self._persist_path)
        except (IOError, OSError):
            pass

    def ban_signing_id(self, signing_id_hex):
        """Ban a signing_id (hex string)."""
        self.banned_signing_ids.add(signing_id_hex)
        self._save()

    def ban_address(self, address):
        """Ban a miner address."""
        self.banned_addresses.add(address)
        self._save()

    def ban_keyword(self, keyword):
        """Ban a keyword (case-insensitive)."""
        self.banned_keywords.add(keyword.lower())
        self._save()

    def ban_type(self, msg_type):
        """Ban an entire message type."""
        self.banned_types.add(msg_type)
        self._save()

    def unban_signing_id(self, signing_id_hex):
        self.banned_signing_ids.discard(signing_id_hex)
        self._save()

    def unban_address(self, address):
        self.banned_addresses.discard(address)
        self._save()

    def unban_keyword(self, keyword):
        self.banned_keywords.discard(keyword.lower())
        self._save()

    def unban_type(self, msg_type):
        self.banned_types.discard(msg_type)
        self._save()

    def is_banned(self, msg):
        """
        Check if a ShareMessage should be hidden from this node's display.

        Protocol-authority messages (FLAG_PROTOCOL_AUTHORITY) are NEVER banned,
        regardless of ban list contents — they are system-critical.

        Returns True if the message should be hidden.
        """
        # Authority messages are always shown
        if msg.flags & FLAG_PROTOCOL_AUTHORITY:
            return False

        # Check type ban
        if msg.msg_type in self.banned_types:
            return True

        # Check address ban
        if msg.sender_address and msg.sender_address in self.banned_addresses:
            return True

        # Check signing_id ban
        if msg.signing_id:
            sid_hex = msg.signing_id.encode('hex') if isinstance(
                msg.signing_id, bytes) else msg.signing_id
            if sid_hex in self.banned_signing_ids:
                return True

        # Check keyword ban (in payload text)
        if self.banned_keywords:
            try:
                text = msg.payload.decode('utf-8').lower()
            except (UnicodeDecodeError, AttributeError):
                text = ''
            for kw in self.banned_keywords:
                if kw in text:
                    return True

        return False

    def to_json(self):
        """Serialize for API."""
        return {
            'signing_ids': sorted(self.banned_signing_ids),
            'addresses': sorted(self.banned_addresses),
            'keywords': sorted(self.banned_keywords),
            'types': sorted(self.banned_types),
            'type_names': [MESSAGE_TYPE_NAMES.get(t, '0x%02x' % t)
                           for t in sorted(self.banned_types)],
        }


# ============================================================================
# Message Store — sharechain-aware persistence
# ============================================================================

class ShareMessageStore(object):
    """
    In-memory store for share messages with deduplication, pruning,
    integrated signing key registry, and node-local ban filtering.

    Persistence model:
      - Regular messages live as long as their carrying share is in the
        active sharechain (CHAIN_LENGTH window).  When a share falls off
        the chain tail, its messages are pruned automatically.
      - Authority messages (FLAG_PROTOCOL_AUTHORITY) and messages from
        donation script signers persist beyond the sharechain window
        into a separate authority_messages list with configurable TTL.
      - On restart, messages are re-populated from shares still in the
        tracker — no separate disk store needed for regular messages.

    Node control:
      - BanList filters messages from API/display (not from relay).
      - Authority messages bypass the ban list entirely.
    """

    def __init__(self, max_messages=MAX_MESSAGE_HISTORY, max_age=MAX_MESSAGE_AGE,
                 ban_list=None):
        self.messages = []          # ordered newest first
        self.message_hashes = set() # for deduplication
        self.max_messages = max_messages
        self.max_age = max_age
        self.key_registry = SigningKeyRegistry()
        self.ban_list = ban_list or BanList()
        # share_hash -> [messages] index for sharechain-aware pruning
        self._share_messages = {}   # {share_hash_int: [ShareMessage, ...]}
        # Authority messages with extended retention
        self.authority_messages = []  # never pruned by sharechain, only by max_age

    def process_share(self, share_hash, sender_address, packed_message_data):
        """
        Process messages from a share. This is the main entry point called
        during share verification in data.py.

        1. Unpacks messages and signing key announcement from packed data
        2. Registers any signing key announcement in the key registry
        3. Verifies message signatures against the registry
        4. Stores valid messages with deduplication

        Args:
            share_hash: int -- hash of the share carrying these messages
            sender_address: str -- payout address of the miner who produced the share
            packed_message_data: bytes -- raw message_data from share ref_type

        Returns number of messages added.
        """
        messages, signing_key_info = unpack_share_messages(packed_message_data)

        # Register signing key if present
        if signing_key_info:
            self.key_registry.register_key(
                miner_address=sender_address,
                signing_id=signing_key_info['signing_id'],
                key_index=signing_key_info['key_index'],
                signing_pubkey=signing_key_info['signing_pubkey'],
                share_hash=share_hash,
            )

        # Process each message
        added = 0
        for msg in messages:
            msg.share_hash = share_hash
            msg.sender_address = sender_address

            # Verify signature if present
            if msg.has_signature:
                msg.verify(self.key_registry)

            if self._add_message(msg):
                added += 1

        return added

    @staticmethod
    def _is_transition_authority(msg):
        """True for authority-signed transition signals — never time-expired."""
        return msg.is_protocol_authority and msg.msg_type == MSG_TRANSITION_SIGNAL

    def _add_message(self, msg):
        """Add a message if not duplicate and not too old.

        Expiry policy:
          - Authority transition signals (MSG_TRANSITION_SIGNAL +
            FLAG_PROTOCOL_AUTHORITY): NO time-based expiry.  They
            persist for the entire transition period until superseded.
          - Other authority messages: normal max_age (sharechain window).
          - Regular messages: normal max_age.
        """
        msg_hash = msg.message_hash()
        msg_hash_hex = msg_hash.encode('hex')

        if msg_hash_hex in self.message_hashes:
            return False

        # Transition signals from authority never expire by age
        if not self._is_transition_authority(msg):
            if msg.age > self.max_age:
                return False

        self.messages.append(msg)
        self.message_hashes.add(msg_hash_hex)

        # Index by share_hash for sharechain-aware pruning
        if msg.share_hash is not None:
            if msg.share_hash not in self._share_messages:
                self._share_messages[msg.share_hash] = []
            self._share_messages[msg.share_hash].append(msg)

        # Authority messages get extended retention
        if msg.is_protocol_authority:
            self.authority_messages.append(msg)

        self.messages.sort(key=lambda m: m.timestamp, reverse=True)
        self._prune()
        return True

    def add_local_message(self, msg, sender_address=None):
        """
        Add a locally-generated message (not from a share).
        Used for node status messages that haven't been embedded in a share yet.
        """
        if sender_address:
            msg.sender_address = sender_address
        return self._add_message(msg)

    def prune_by_sharechain(self, active_share_hashes):
        """
        Remove messages whose carrying share has fallen off the sharechain.

        Called periodically or when chain tip advances.  Takes a set of
        share hashes currently in the active chain.

        Authority messages are preserved regardless of sharechain status.
        """
        if not active_share_hashes:
            return

        expired_shares = set(self._share_messages.keys()) - active_share_hashes
        for sh in expired_shares:
            msgs = self._share_messages.pop(sh, [])
            for m in msgs:
                # Keep authority messages in the extended store
                if m.is_protocol_authority:
                    continue
                if m in self.messages:
                    self.messages.remove(m)
                    self.message_hashes.discard(m.message_hash().encode('hex'))

    def _prune(self):
        """Remove old and excess messages.

        Expiry policy:
          - Authority transition signals: NEVER pruned by time.
            They persist until superseded or the node restarts.
          - Regular messages: pruned after max_age (sharechain window).
        """
        cutoff = time.time() - self.max_age

        # Prune regular messages by cutoff;
        # authority transition signals are exempt from time-based pruning
        expired = [m for m in self.messages
                   if not self._is_transition_authority(m)
                   and m.timestamp < cutoff]
        for m in expired:
            self.messages.remove(m)
            self.message_hashes.discard(m.message_hash().encode('hex'))

        # Also prune authority list (same policy)
        expired_auth = [m for m in self.authority_messages
                        if not self._is_transition_authority(m)
                        and m.timestamp < cutoff]
        for m in expired_auth:
            self.authority_messages.remove(m)
            if m in self.messages:
                self.messages.remove(m)
                self.message_hashes.discard(m.message_hash().encode('hex'))

        while len(self.messages) > self.max_messages:
            oldest = self.messages.pop()
            self.message_hashes.discard(oldest.message_hash().encode('hex'))

    def rebuild_from_tracker(self, tracker, best_share, chain_length):
        """
        Rebuild message store from shares currently in the tracker.

        Called on startup or after a reorg.  Walks the sharechain from
        best_share backward for chain_length shares and re-processes
        any message_data found.
        """
        count = 0
        try:
            for share in tracker.get_chain(best_share, chain_length):
                if not hasattr(share, '_message_data') or not share._message_data:
                    continue
                if not hasattr(share, '_parsed_messages') or not share._parsed_messages:
                    continue
                for msg in share._parsed_messages:
                    msg.share_hash = share.hash
                    msg.sender_address = getattr(share, 'address', None)
                    if self._add_message(msg):
                        count += 1
        except Exception:
            pass
        return count

    def load_blob_hex(self, hex_string):
        """
        Load a pre-built encrypted message blob from a hex string.

        This is used for:
          1. --transition-message CLI argument
          2. Bootstrap blob files in data/<net>/bootstrap_messages/

        The blob is decrypted using known authority pubkeys (same as
        share message_data).  Only authority-encrypted blobs are accepted.
        After decryption, each message's signature is verified against
        the authority pubkey that encrypted the envelope, restoring
        FLAG_PROTOCOL_AUTHORITY (which unpack() strips by default).

        Returns number of messages loaded (0 if decryption fails or no
        valid messages found).
        """
        try:
            raw = hex_string.strip().decode('hex')
        except (ValueError, TypeError):
            return 0

        messages, signing_key_info = unpack_share_messages(raw)
        if not messages:
            return 0

        # Get the authority pubkey that successfully decrypted this envelope
        authority_pubkey = signing_key_info.get('authority_pubkey') if signing_key_info else None

        added = 0
        for msg in messages:
            # Bootstrap messages have no carrying share
            msg.share_hash = None
            msg.sender_address = 'bootstrap'
            # Verify signature against the authority pubkey that encrypted
            # this envelope.  This restores FLAG_PROTOCOL_AUTHORITY which
            # unpack() strips (authority must be "earned" via verification).
            if authority_pubkey and msg.has_signature:
                msg.verify_authority_direct(authority_pubkey)
            if authority_pubkey and not msg.is_protocol_authority:
                import logging
                logging.getLogger('p2pool.share_messages').warning(
                    'Authority message ECDSA verification failed — '
                    'install ecdsa or coincurve: '
                    'pypy -m pip install ecdsa')
            if self._add_message(msg):
                added += 1
        return added

    def load_bootstrap_blobs(self, bootstrap_dir):
        """
        Scan a directory for .hex and .blob files and load each as a
        pre-built encrypted message blob.

        Expected location: data/<net>/bootstrap_messages/
        Files should contain a single hex-encoded encrypted envelope per
        file (as produced by scripts/create_transition_message.py).

        Returns total number of messages loaded across all files.
        """
        if not bootstrap_dir or not os.path.isdir(bootstrap_dir):
            return 0

        total = 0
        for fname in sorted(os.listdir(bootstrap_dir)):
            if not (fname.endswith('.hex') or fname.endswith('.blob')):
                continue
            fpath = os.path.join(bootstrap_dir, fname)
            try:
                with open(fpath, 'r') as f:
                    hex_data = f.read().strip()
                if not hex_data:
                    continue
                n = self.load_blob_hex(hex_data)
                if n > 0:
                    total += n
            except Exception as e:
                print('Messaging: ERROR reading blob %s: %s' % (fpath, e))
                continue
        return total

    def get_messages(self, msg_type=None, sender=None, since=None,
                     verified_only=False, limit=50, apply_bans=True,
                     authority_only=False):
        """Query messages with optional filters and ban-list enforcement.

        Args:
            authority_only: If True, only return messages with
                FLAG_PROTOCOL_AUTHORITY set. Used by default display
                when --enable-miner-messages is not set.
        """
        results = self.messages

        if authority_only:
            results = [m for m in results if m.is_protocol_authority]

        if msg_type is not None:
            results = [m for m in results if m.msg_type == msg_type]
        if sender is not None:
            results = [m for m in results if m.sender_address == sender]
        if since is not None:
            results = [m for m in results if m.timestamp >= since]
        if verified_only:
            results = [m for m in results if m.verified]

        # Apply node-local ban list
        if apply_bans and self.ban_list:
            results = [m for m in results if not self.ban_list.is_banned(m)]

        return results[:limit]

    def get_recent(self, limit=20):
        """Get most recent messages of all types."""
        return self.get_messages(limit=limit)

    def get_chat(self, limit=50):
        """Get miner-to-miner chat messages (signed and verified only)."""
        return self.get_messages(
            msg_type=MSG_MINER_MESSAGE, verified_only=True, limit=limit)

    def get_all_chat(self, limit=50):
        """Get all miner-to-miner chat messages (including unverified)."""
        return self.get_messages(msg_type=MSG_MINER_MESSAGE, limit=limit)

    def get_announcements(self, limit=10):
        """Get pool operator announcements."""
        return self.get_messages(msg_type=MSG_POOL_ANNOUNCE, limit=limit)

    def get_alerts(self, limit=5):
        """Get emergency alerts."""
        return self.get_messages(msg_type=MSG_EMERGENCY, limit=limit)

    def get_node_statuses(self, limit=20):
        """Get node status reports."""
        return self.get_messages(msg_type=MSG_NODE_STATUS, limit=limit)

    def to_json(self, **kwargs):
        """Get messages as JSON-serializable list."""
        messages = self.get_messages(**kwargs)
        return [m.to_dict() for m in messages]

    @property
    def stats(self):
        """Get store statistics."""
        type_counts = {}
        for m in self.messages:
            name = m.type_name
            type_counts[name] = type_counts.get(name, 0) + 1

        unique_senders = set(
            m.sender_address for m in self.messages if m.sender_address)

        return {
            'total_messages': len(self.messages),
            'authority_messages': len(self.authority_messages),
            'tracked_shares': len(self._share_messages),
            'unique_senders': len(unique_senders),
            'senders': list(unique_senders),
            'by_type': type_counts,
            'oldest_timestamp': self.messages[-1].timestamp if self.messages else None,
            'newest_timestamp': self.messages[0].timestamp if self.messages else None,
            'signed_count': sum(1 for m in self.messages if m.has_signature),
            'verified_count': sum(1 for m in self.messages if m.verified),
            'known_signing_keys': len(self.key_registry.id_to_address),
            'key_registry': self.key_registry.to_json(),
            'ban_list': self.ban_list.to_json() if self.ban_list else None,
        }


# ============================================================================
# Message Builders -- convenience functions
# ============================================================================

def build_node_status(version, uptime, hashrate, share_count, peers,
                      merged_chains=None, capabilities=None):
    """
    Build a NODE_STATUS message with node health information.

    Payload is compact JSON:
      {"v":"13.4","up":3600,"hr":1500000,"sc":8640,"p":3,"mc":["DOGE"],"cap":["v36","mm"]}
    """
    status = {
        'v': version,
        'up': int(uptime),
        'hr': int(hashrate),
        'sc': share_count,
        'p': peers,
    }
    if merged_chains:
        status['mc'] = merged_chains   # e.g., ['DOGE', 'BEL']
    if capabilities:
        status['cap'] = capabilities   # e.g., ['v36', 'mm', 'segwit']

    payload = json.dumps(status, separators=(',', ':'))
    return ShareMessage(
        msg_type=MSG_NODE_STATUS,
        payload=payload,
        flags=FLAG_BROADCAST,  # ephemeral, broadcast but not persistent
    )


def build_miner_message(text):
    """
    Build a MINER_MESSAGE for miner-to-miner chat.
    Must be signed with DerivedSigningKey before embedding in share.
    """
    if isinstance(text, unicode):
        text = text.encode('utf-8')
    if len(text) > MAX_MESSAGE_PAYLOAD:
        text = text[:MAX_MESSAGE_PAYLOAD]
    return ShareMessage(
        msg_type=MSG_MINER_MESSAGE,
        payload=text,
        flags=FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT,
    )


def build_pool_announcement(text):
    """Build a POOL_ANNOUNCE message from node operator."""
    if isinstance(text, unicode):
        text = text.encode('utf-8')
    if len(text) > MAX_MESSAGE_PAYLOAD:
        text = text[:MAX_MESSAGE_PAYLOAD]
    return ShareMessage(
        msg_type=MSG_POOL_ANNOUNCE,
        payload=text,
        flags=FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT,
    )


def build_merged_status(chain_name, symbol, height, block_value, blocks_found=0):
    """
    Build a MERGED_STATUS message with merged mining chain info.

    Payload is compact JSON:
      {"chain":"Dogecoin","sym":"DOGE","h":5000000,"bv":10000.0,"bf":3}
    """
    status = {
        'chain': chain_name,
        'sym': symbol,
        'h': height,
        'bv': block_value,
        'bf': blocks_found,
    }
    payload = json.dumps(status, separators=(',', ':'))
    return ShareMessage(
        msg_type=MSG_MERGED_STATUS,
        payload=payload,
        flags=FLAG_BROADCAST,
    )


def build_version_signal(version, features, extra=None):
    """
    Build a VERSION_SIGNAL message with extended version info.

    Payload is compact JSON:
      {"ver":36,"feat":["mm","segwit","mweb"],"proto":3600}
    """
    status = {
        'ver': version,
        'feat': features,
    }
    if extra:
        status.update(extra)
    payload = json.dumps(status, separators=(',', ':'))
    return ShareMessage(
        msg_type=MSG_VERSION_SIGNAL,
        payload=payload,
        flags=FLAG_BROADCAST,
    )


def build_emergency_alert(text):
    """
    Build an EMERGENCY alert message.
    Must be signed to be taken seriously by recipients.
    """
    if isinstance(text, unicode):
        text = text.encode('utf-8')
    if len(text) > MAX_MESSAGE_PAYLOAD:
        text = text[:MAX_MESSAGE_PAYLOAD]
    return ShareMessage(
        msg_type=MSG_EMERGENCY,
        payload=text,
        flags=FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT,
    )


def build_transition_signal(
    current_version,
    target_version,
    message,
    urgency='recommended',
    upgrade_url=None,
    activation_threshold=None,
    extra=None,
):
    """
    Build a TRANSITION_SIGNAL message for embedding in shares.

    This is the primary mechanism for protocol-level upgrade coordination.
    The message MUST be signed by one of the COMBINED_DONATION_SCRIPT keys
    (forrestv or maintainer) to carry FLAG_PROTOCOL_AUTHORITY.

    Payload is compact JSON:
      {
        "from": 36,
        "to": 37,
        "msg": "Upgrade to v37 for MWEB merged mining support",
        "urg": "recommended",    -- "info" | "recommended" | "required"
        "url": "https://github.com/frstrtr/p2pool-merged-v36/releases",
        "thr": 95                -- activation threshold %   (optional)
      }

    The message is embedded in the share's ref_type message_data field,
    propagated via normal share distribution, and PoW-protected.

    Args:
        current_version: Current share version (e.g. 36)
        target_version:  Target share version to upgrade to (e.g. 37)
        message:         Human-readable transition guidance (UTF-8)
        urgency:         One of 'info', 'recommended', 'required'
        upgrade_url:     URL for the upgrade release   (optional)
        activation_threshold: Activation threshold %   (optional)
        extra:           Additional key-value pairs     (optional)

    Returns:
        ShareMessage ready to be signed and embedded
    """
    assert urgency in ('info', 'recommended', 'required'), \
        'urgency must be info, recommended, or required'

    status = {
        'from': current_version,
        'to': target_version,
        'msg': message if isinstance(message, str) else message.encode('utf-8'),
        'urg': urgency,
    }
    if upgrade_url:
        status['url'] = upgrade_url
    if activation_threshold is not None:
        status['thr'] = activation_threshold
    if extra:
        status.update(extra)

    payload = json.dumps(status, separators=(',', ':'))
    if len(payload) > MAX_MESSAGE_PAYLOAD:
        raise ValueError(
            'transition signal payload too large: %d > %d' % (
                len(payload), MAX_MESSAGE_PAYLOAD,
            )
        )

    return ShareMessage(
        msg_type=MSG_TRANSITION_SIGNAL,
        payload=payload,
        flags=FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT | FLAG_PROTOCOL_AUTHORITY,
    )


def is_authority_pubkey(compressed_pubkey):
    """
    Check whether a compressed public key is one of the
    COMBINED_DONATION_SCRIPT authority keys.
    """
    return compressed_pubkey in DONATION_AUTHORITY_PUBKEYS
