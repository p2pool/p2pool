#!/usr/bin/env python3
"""
P2Pool V36 Authority Message Creator
======================================

Standalone Python 3 utility for AUTHORITY KEY HOLDERS to create encrypted and
signed messages for the p2pool share messaging system.

Supports:
  - Transition signals (MSG_TRANSITION_SIGNAL 0x20) — protocol upgrade alerts
  - Announcements (MSG_POOL_ANNOUNCE 0x03) — general authority announcements
  - Emergency alerts (MSG_EMERGENCY 0x10) — critical alerts

Messages are:
  1. SIGNED with an ECDSA secp256k1 key (proving authorship)
  2. ENCRYPTED using the authority pubkey (preventing on-the-wire sniffing)

Only messages signed+encrypted by a COMBINED_DONATION_SCRIPT key holder
(forrestv or maintainer) are accepted by the p2pool network.

WORKFLOW:
  1. Authority key holder creates the message (this tool) → gets a HEX STRING
  2. Authority distributes the hex string (GitHub release, website, etc.)
  3. Node operators paste the hex string into --transition-message or POST /msg/load_blob
  4. No private key is needed on operator nodes!

USAGE (authority key holder):
  python3 create_transition_message.py create --privkey <64-hex-chars> \\
      --from 36 --to 37 --msg "Upgrade to V37" --urgency recommended \\
      --url "https://github.com/frstrtr/p2pool-merged-v36/releases"

USAGE (node operator — just paste the hex string):
  python run_p2pool.py [options] --transition-message 01a2b3c4d5e6f7...

AUTHORITY KEYS (from COMBINED_DONATION_REDEEM_SCRIPT):
  forrestv:   03ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1
  maintainer: 02fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a
"""

import argparse
import hashlib
import hmac as hmac_mod
import json
import os
import struct
import sys
import time
import getpass
import binascii

# Try to import ecdsa
try:
    import ecdsa
    HAS_ECDSA = True
except ImportError:
    HAS_ECDSA = False

# Try to import coincurve (faster, C-based)
try:
    import coincurve
    HAS_COINCURVE = True
except ImportError:
    HAS_COINCURVE = False

if not HAS_ECDSA and not HAS_COINCURVE:
    print("ERROR: Need either 'ecdsa' or 'coincurve' package.", file=sys.stderr)
    print("  pip3 install ecdsa", file=sys.stderr)
    sys.exit(1)

# Try to import mnemonic for BIP39 seed phrases
try:
    from mnemonic import Mnemonic
    HAS_MNEMONIC = True
except ImportError:
    HAS_MNEMONIC = False


# =============================================================================
# Constants — must match p2pool/share_messages.py exactly
# =============================================================================

# Authority pubkeys from COMBINED_DONATION_REDEEM_SCRIPT
DONATION_PUBKEY_FORRESTV = bytes.fromhex(
    '03ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1')
DONATION_PUBKEY_MAINTAINER = bytes.fromhex(
    '02fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a')
DONATION_AUTHORITY_PUBKEYS = frozenset([
    DONATION_PUBKEY_FORRESTV, DONATION_PUBKEY_MAINTAINER])

# Message type
MSG_POOL_ANNOUNCE = 0x03
MSG_EMERGENCY = 0x10
MSG_TRANSITION_SIGNAL = 0x20

# Message flags
FLAG_HAS_SIGNATURE = 0x01
FLAG_BROADCAST = 0x02
FLAG_PERSISTENT = 0x04
FLAG_PROTOCOL_AUTHORITY = 0x08

# Limits
MAX_MESSAGE_PAYLOAD = 220

# Encryption constants
ENCRYPTED_ENVELOPE_VERSION = 0x01
ENCRYPTION_NONCE_SIZE = 16
ENCRYPTION_MAC_SIZE = 32
ENCRYPTION_HEADER_SIZE = 1 + ENCRYPTION_NONCE_SIZE + ENCRYPTION_MAC_SIZE


# =============================================================================
# Crypto primitives
# =============================================================================

def derive_compressed_pubkey(privkey_bytes: bytes) -> bytes:
    """Derive 33-byte compressed secp256k1 public key from 32-byte private key."""
    if HAS_COINCURVE:
        pk = coincurve.PrivateKey(privkey_bytes)
        return pk.public_key.format(compressed=True)
    else:
        sk = ecdsa.SigningKey.from_string(privkey_bytes, curve=ecdsa.SECP256k1)
        vk = sk.get_verifying_key()
        x = vk.to_string()[:32]
        y = vk.to_string()[32:]
        prefix = b'\x02' if y[-1] % 2 == 0 else b'\x03'
        return prefix + x


def ecdsa_sign(privkey_bytes: bytes, message_hash: bytes) -> bytes:
    """Sign a 32-byte hash with secp256k1. Returns DER-encoded signature."""
    if HAS_COINCURVE:
        pk = coincurve.PrivateKey(privkey_bytes)
        return pk.sign(message_hash, hasher=None)
    else:
        sk = ecdsa.SigningKey.from_string(privkey_bytes, curve=ecdsa.SECP256k1)
        return sk.sign_digest(message_hash, sigencode=ecdsa.util.sigencode_der)


def ecdsa_verify(pubkey_compressed: bytes, message_hash: bytes,
                 signature: bytes) -> bool:
    """Verify ECDSA signature against compressed public key."""
    try:
        if HAS_COINCURVE:
            pk = coincurve.PublicKey(pubkey_compressed)
            return pk.verify(signature, message_hash, hasher=None)
        else:
            vk = ecdsa.VerifyingKey.from_string(
                pubkey_compressed, curve=ecdsa.SECP256k1)
            return vk.verify_digest(
                signature, message_hash, sigdecode=ecdsa.util.sigdecode_der)
    except Exception:
        return False


# =============================================================================
# Encryption — must match share_messages.py exactly
# =============================================================================

def _derive_encryption_key(authority_pubkey: bytes, nonce: bytes) -> bytes:
    """Derive symmetric key from authority pubkey + nonce."""
    return hmac_mod.new(authority_pubkey, nonce, hashlib.sha256).digest()


def _generate_stream(enc_key: bytes, length: int) -> bytes:
    """Counter-mode SHA256 stream: SHA256(key||0) || SHA256(key||1) || ..."""
    stream = b''
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(enc_key + struct.pack('<I', counter)).digest()
        stream += block
        counter += 1
    return stream[:length]


def _xor_bytes(data: bytes, stream: bytes) -> bytes:
    """XOR data with stream."""
    return bytes(a ^ b for a, b in zip(data, stream))


def encrypt_message_data(inner_data: bytes, authority_pubkey: bytes) -> bytes:
    """
    Encrypt inner message data using the authority pubkey for key derivation.
    Returns: [version:1][nonce:16][mac:32][ciphertext:N]
    """
    if authority_pubkey not in DONATION_AUTHORITY_PUBKEYS:
        raise ValueError('Pubkey not in DONATION_AUTHORITY_PUBKEYS')

    nonce = os.urandom(ENCRYPTION_NONCE_SIZE)
    enc_key = _derive_encryption_key(authority_pubkey, nonce)

    stream = _generate_stream(enc_key, len(inner_data))
    ciphertext = _xor_bytes(inner_data, stream)

    mac = hmac_mod.new(enc_key, ciphertext, hashlib.sha256).digest()

    return bytes([ENCRYPTED_ENVELOPE_VERSION]) + nonce + mac + ciphertext


def decrypt_message_data(encrypted_envelope: bytes):
    """
    Decrypt using known authority pubkeys. Returns (inner_data, pubkey) or
    (None, None).
    """
    if len(encrypted_envelope) < ENCRYPTION_HEADER_SIZE + 1:
        return None, None

    version = encrypted_envelope[0]
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
        mac_computed = hmac_mod.new(enc_key, ciphertext, hashlib.sha256).digest()
        if mac_computed != mac_received:
            continue
        stream = _generate_stream(enc_key, len(ciphertext))
        inner_data = _xor_bytes(ciphertext, stream)
        return inner_data, pubkey

    return None, None


# =============================================================================
# Message building — must match share_messages.py format exactly
# =============================================================================

def message_hash(msg_type: int, flags: int, timestamp: int,
                 payload: bytes) -> bytes:
    """Double-SHA256 of message content (matches ShareMessage.message_hash())."""
    data = struct.pack('<BBI', msg_type, flags, timestamp) + payload
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def pack_message(msg_type: int, flags: int, timestamp: int,
                 payload: bytes, signature: bytes,
                 signing_id: bytes = b'\x00' * 20) -> bytes:
    """
    Pack a single message (matches ShareMessage.pack() wire format).

    Wire format:
      [type:1][flags:1][timestamp:4][payload_len:2][payload:N]
      [signing_id:20][sig_len:1][signature:M]
    """
    sig = signature or b''
    return (
        struct.pack('<BBIH', msg_type, flags, timestamp, len(payload)) +
        payload +
        signing_id +
        struct.pack('<B', len(sig)) +
        sig
    )


def build_transition_signal(from_ver: str, to_ver: str, msg_text: str,
                            urgency: str = 'recommended',
                            url: str = None,
                            threshold: int = None) -> bytes:
    """
    Build a TRANSITION_SIGNAL JSON payload.
    Returns compact JSON bytes.
    """
    assert urgency in ('info', 'recommended', 'required'), \
        "urgency must be 'info', 'recommended', or 'required'"

    payload = {
        'from': from_ver,
        'to': to_ver,
        'msg': msg_text,
        'urg': urgency,
    }
    if url:
        payload['url'] = url
    if threshold is not None:
        payload['thr'] = threshold

    encoded = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_MESSAGE_PAYLOAD:
        raise ValueError(
            f'Payload too large: {len(encoded)} > {MAX_MESSAGE_PAYLOAD} bytes')
    return encoded


def build_announcement_payload(msg_text: str, urgency: str = 'info',
                                url: str = None) -> bytes:
    """
    Build a POOL_ANNOUNCE or EMERGENCY JSON payload.
    Returns compact JSON bytes.
    """
    assert urgency in ('info', 'recommended', 'required', 'alert'), \
        "urgency must be 'info', 'recommended', 'required', or 'alert'"

    payload = {
        'msg': msg_text,
        'urg': urgency,
    }
    if url:
        payload['url'] = url

    encoded = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_MESSAGE_PAYLOAD:
        raise ValueError(
            f'Payload too large: {len(encoded)} > {MAX_MESSAGE_PAYLOAD} bytes')
    return encoded


def create_signed_encrypted_message(privkey_bytes: bytes,
                                    from_ver: str, to_ver: str,
                                    msg_text: str, urgency: str,
                                    url: str = None,
                                    threshold: int = None) -> bytes:
    """
    Full pipeline: build → sign → pack → wrap inner → encrypt.

    Returns the final encrypted message_data bytes ready for embedding
    in a V36 share's ref_type.message_data field.
    """
    # 1. Derive pubkey and verify it's an authority key
    compressed_pubkey = derive_compressed_pubkey(privkey_bytes)
    if compressed_pubkey not in DONATION_AUTHORITY_PUBKEYS:
        raise ValueError(
            f'Private key does not correspond to a COMBINED_DONATION_SCRIPT '
            f'authority key.\n'
            f'  Derived: {compressed_pubkey.hex()}\n'
            f'  Expected one of:\n'
            f'    forrestv:   {DONATION_PUBKEY_FORRESTV.hex()}\n'
            f'    maintainer: {DONATION_PUBKEY_MAINTAINER.hex()}')

    # 2. Build payload
    payload = build_transition_signal(
        from_ver, to_ver, msg_text, urgency, url, threshold)

    # 3. Compute message hash and sign
    ts = int(time.time())
    flags = FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT | FLAG_PROTOCOL_AUTHORITY
    msg_hash = message_hash(MSG_TRANSITION_SIGNAL, flags, ts, payload)
    signature = ecdsa_sign(privkey_bytes, msg_hash)

    # 4. Verify our own signature (sanity check)
    if not ecdsa_verify(compressed_pubkey, msg_hash, signature):
        raise RuntimeError('Self-verification failed — this should never happen')

    # 5. Pack the message
    packed_msg = pack_message(
        MSG_TRANSITION_SIGNAL, flags, ts, payload, signature,
        signing_id=b'\x00' * 20  # authority messages use empty signing_id
    )

    # 6. Wrap in inner envelope (version=1, flags=0, 1 message, no announcement)
    inner = struct.pack('<BBBB', 1, 0, 1, 0) + packed_msg

    # 7. Encrypt with authority pubkey
    encrypted = encrypt_message_data(inner, compressed_pubkey)

    return encrypted, compressed_pubkey, ts, payload, signature


def create_announcement_blob(privkey_bytes: bytes, msg_text: str,
                             urgency: str = 'info', url: str = None,
                             is_emergency: bool = False):
    """
    Create a signed+encrypted authority announcement or alert blob.

    Returns (encrypted_bytes, pubkey, timestamp, payload, signature).
    """
    compressed_pubkey = derive_compressed_pubkey(privkey_bytes)
    if compressed_pubkey not in DONATION_AUTHORITY_PUBKEYS:
        raise ValueError(
            f'Private key does not correspond to a COMBINED_DONATION_SCRIPT '
            f'authority key.\n'
            f'  Derived: {compressed_pubkey.hex()}\n'
            f'  Expected one of:\n'
            f'    forrestv:   {DONATION_PUBKEY_FORRESTV.hex()}\n'
            f'    maintainer: {DONATION_PUBKEY_MAINTAINER.hex()}')

    msg_type = MSG_EMERGENCY if is_emergency else MSG_POOL_ANNOUNCE
    payload = build_announcement_payload(msg_text, urgency, url)

    ts = int(time.time())
    flags = FLAG_HAS_SIGNATURE | FLAG_BROADCAST | FLAG_PERSISTENT | FLAG_PROTOCOL_AUTHORITY
    msg_hash = message_hash(msg_type, flags, ts, payload)
    signature = ecdsa_sign(privkey_bytes, msg_hash)

    if not ecdsa_verify(compressed_pubkey, msg_hash, signature):
        raise RuntimeError('Self-verification failed')

    packed_msg = pack_message(
        msg_type, flags, ts, payload, signature,
        signing_id=b'\x00' * 20
    )

    inner = struct.pack('<BBBB', 1, 0, 1, 0) + packed_msg
    encrypted = encrypt_message_data(inner, compressed_pubkey)

    return encrypted, compressed_pubkey, ts, payload, signature


# =============================================================================
# Key loading methods
# =============================================================================

def load_privkey_hex(hex_string: str) -> bytes:
    """Load private key from hex string (64 chars = 32 bytes)."""
    hex_string = hex_string.strip()
    try:
        privkey = bytes.fromhex(hex_string)
    except ValueError:
        raise ValueError('Invalid hex string for private key')
    if len(privkey) != 32:
        raise ValueError(f'Private key must be 32 bytes, got {len(privkey)}')
    return privkey


def load_privkey_file(path: str) -> bytes:
    """Load hex-encoded private key from file."""
    with open(path, 'r') as f:
        return load_privkey_hex(f.read())


def load_privkey_from_seed(seed_phrase: str,
                           derivation_path: str = "m/44'/2'/0'/0/0",
                           passphrase: str = '') -> bytes:
    """
    Derive a private key from a BIP39 seed phrase.

    Default derivation path m/44'/2'/0'/0/0 is for Litecoin (coin_type=2).
    The authority keys may use a different path — adjust as needed.

    Requires the 'mnemonic' package: pip3 install mnemonic
    """
    if not HAS_MNEMONIC:
        raise ImportError(
            "BIP39 seed phrase support requires the 'mnemonic' package.\n"
            "  pip3 install mnemonic")

    mnemo = Mnemonic("english")
    if not mnemo.check(seed_phrase):
        raise ValueError('Invalid BIP39 mnemonic phrase')

    # Generate seed from mnemonic
    seed = Mnemonic.to_seed(seed_phrase, passphrase)

    # BIP32 key derivation
    privkey = _bip32_derive(seed, derivation_path)
    return privkey


def _bip32_derive(seed: bytes, path: str) -> bytes:
    """
    BIP32 hierarchical deterministic key derivation.
    Derives a child private key from seed following the path.
    """
    # Master key derivation (BIP32)
    I = hmac_mod.new(b'Bitcoin seed', seed, hashlib.sha512).digest()
    master_key = I[:32]
    master_chain = I[32:]

    # Parse path
    if path.startswith('m/'):
        path = path[2:]
    elif path.startswith('m'):
        path = path[1:]

    if not path:
        return master_key

    key = master_key
    chain = master_chain

    for component in path.split('/'):
        hardened = component.endswith("'") or component.endswith('h')
        index = int(component.rstrip("'h"))
        if hardened:
            index += 0x80000000

        if hardened:
            data = b'\x00' + key + struct.pack('>I', index)
        else:
            pubkey = derive_compressed_pubkey(key)
            data = pubkey + struct.pack('>I', index)

        I = hmac_mod.new(chain, data, hashlib.sha512).digest()
        child_key_int = (int.from_bytes(I[:32], 'big') +
                         int.from_bytes(key, 'big')) % \
            0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        key = child_key_int.to_bytes(32, 'big')
        chain = I[32:]

    return key


def load_privkey_from_keystore(keystore_path: str,
                               password: str = None) -> bytes:
    """
    Load private key from an encrypted JSON keystore file.

    Supports a simple JSON format:
    {
        "crypto": {
            "cipher": "aes-256-cbc",
            "ciphertext": "<hex>",
            "iv": "<hex>",
            "kdf": "pbkdf2",
            "kdfparams": {
                "iterations": 100000,
                "salt": "<hex>"
            }
        }
    }

    The decryption key is derived from the password via PBKDF2-HMAC-SHA256.
    """
    with open(keystore_path, 'r') as f:
        keystore = json.load(f)

    if password is None:
        password = getpass.getpass('Keystore password: ')

    crypto = keystore.get('crypto', keystore.get('Crypto', {}))
    kdfparams = crypto.get('kdfparams', {})
    iterations = kdfparams.get('iterations', 100000)
    salt = bytes.fromhex(kdfparams.get('salt', ''))

    # Derive decryption key via PBKDF2
    dk = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt, iterations, dklen=32)

    ciphertext = bytes.fromhex(crypto.get('ciphertext', ''))
    iv = bytes.fromhex(crypto.get('iv', ''))

    # Decrypt using XOR stream (same as our encryption layer)
    stream = _generate_stream(dk, len(ciphertext))
    privkey = _xor_bytes(ciphertext, stream)

    if len(privkey) != 32:
        raise ValueError(f'Decrypted key is {len(privkey)} bytes, expected 32')

    return privkey


# =============================================================================
# Keystore creation helper
# =============================================================================

def create_keystore(privkey_bytes: bytes, password: str,
                    output_path: str, iterations: int = 100000) -> None:
    """
    Create an encrypted keystore file from a private key.

    Usage:
        python3 create_transition_message.py create-keystore \\
            --privkey <hex> --keystore-out /path/to/keystore.json
    """
    salt = os.urandom(32)
    dk = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt, iterations, dklen=32)

    stream = _generate_stream(dk, len(privkey_bytes))
    ciphertext = _xor_bytes(privkey_bytes, stream)

    keystore = {
        'version': 1,
        'description': 'P2Pool V36 transition message signing key',
        'pubkey': derive_compressed_pubkey(privkey_bytes).hex(),
        'crypto': {
            'cipher': 'stream-sha256',
            'ciphertext': ciphertext.hex(),
            'kdf': 'pbkdf2',
            'kdfparams': {
                'iterations': iterations,
                'salt': salt.hex(),
                'hash': 'sha256',
            },
        },
    }

    with open(output_path, 'w') as f:
        json.dump(keystore, f, indent=2)

    print(f'Keystore written to: {output_path}')
    print(f'Public key: {keystore["pubkey"]}')


# =============================================================================
# Verification helper
# =============================================================================

def verify_message_file(input_path: str) -> None:
    """
    Read and verify an encrypted message_data from a hex string, hex file, or binary file.
    Decrypts + validates format + shows contents.
    """
    # Try reading as file first
    if os.path.isfile(input_path):
        with open(input_path, 'r') as f:
            content = f.read().strip()
        # Try parsing as hex string
        try:
            data = bytes.fromhex(content)
            print(f'Source: {input_path} (hex file)')
        except ValueError:
            # Fall back to binary read
            with open(input_path, 'rb') as f:
                data = f.read()
            print(f'Source: {input_path} (binary file)')
    else:
        # Treat as inline hex string
        try:
            data = bytes.fromhex(input_path.strip())
            print(f'Source: inline hex string')
        except ValueError:
            print(f'ERROR: Not a valid file or hex string: {input_path}')
            return

    print(f'Size: {len(data)} bytes')
    print(f'Envelope version: 0x{data[0]:02x}')

    inner, authority_pubkey = decrypt_message_data(data)
    if inner is None:
        print('DECRYPTION FAILED — not encrypted by any known authority key')
        return

    # Identify which authority key
    if authority_pubkey == DONATION_PUBKEY_FORRESTV:
        key_name = 'forrestv'
    elif authority_pubkey == DONATION_PUBKEY_MAINTAINER:
        key_name = 'maintainer'
    else:
        key_name = 'unknown'
    print(f'Encrypted by: {key_name} ({authority_pubkey.hex()})')

    # Parse inner envelope
    if len(inner) < 4:
        print('ERROR: Inner envelope too short')
        return

    inner_ver, inner_flags, msg_count, ann_len = struct.unpack_from(
        '<BBBB', inner, 0)
    print(f'Inner version: {inner_ver}, messages: {msg_count}')

    offset = 4 + ann_len

    for i in range(msg_count):
        if offset + 8 > len(inner):
            break

        msg_type, flags, timestamp, payload_len = struct.unpack_from(
            '<BBIH', inner, offset)
        offset += 8

        payload = inner[offset:offset + payload_len]
        offset += payload_len

        signing_id = inner[offset:offset + 20]
        offset += 20

        sig_len = inner[offset]
        offset += 1
        signature = inner[offset:offset + sig_len]
        offset += sig_len

        print(f'\n--- Message {i + 1} ---')
        _type_names = {
            MSG_POOL_ANNOUNCE: 'POOL_ANNOUNCE',
            MSG_EMERGENCY: 'EMERGENCY',
            MSG_TRANSITION_SIGNAL: 'TRANSITION_SIGNAL',
        }
        print(f'  Type: 0x{msg_type:02x}'
              f' ({_type_names.get(msg_type, "unknown")})')
        print(f'  Flags: 0x{flags:02x}')
        print(f'  Timestamp: {timestamp}'
              f' ({time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(timestamp))} UTC)')
        print(f'  Payload ({payload_len} bytes): {payload.decode("utf-8", errors="replace")}')
        print(f'  Signature: {signature.hex()[:40]}...' if len(signature) > 20
              else f'  Signature: {signature.hex()}')

        # Verify signature
        msg_h = message_hash(msg_type, flags, timestamp, payload)
        valid = ecdsa_verify(authority_pubkey, msg_h, signature)
        print(f'  Signature valid: {valid}')

        if msg_type in (MSG_TRANSITION_SIGNAL, MSG_POOL_ANNOUNCE, MSG_EMERGENCY):
            try:
                j = json.loads(payload)
                if msg_type == MSG_TRANSITION_SIGNAL:
                    print(f'  Transition: v{j.get("from")} → v{j.get("to")}')
                print(f'  Message: {j.get("msg")}')
                print(f'  Urgency: {j.get("urg")}')
                if 'url' in j:
                    print(f'  URL: {j["url"]}')
            except json.JSONDecodeError:
                pass

    print('\nVerification complete.')


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='P2Pool V36 Transition Message Creator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # AUTHORITY: Create transition message with hex private key
  %(prog)s create --privkey <64-hex> \\
      --from 36 --to 37 --msg "Upgrade to V37" --urgency recommended

  # AUTHORITY: Create announcement (shown on all dashboards)
  %(prog)s announce --privkey <64-hex> \\
      --msg "Maintenance window: Feb 28 00:00-02:00 UTC" --urgency info

  # AUTHORITY: Create emergency alert
  %(prog)s announce --privkey <64-hex> --emergency \\
      --msg "Critical bug — upgrade immediately" --urgency required \\
      --url "https://github.com/frstrtr/p2pool-merged-v36/releases"

  # AUTHORITY: Create message with key file
  %(prog)s create --privkey-file key.hex \\
      --from 36 --to 37 --msg "Upgrade required" --urgency required

  # AUTHORITY: Create message with BIP39 seed phrase
  %(prog)s create --seed-phrase "word1 word2 ... word24" \\
      --from 36 --to 37 --msg "Upgrade available" --urgency info

  # AUTHORITY: Create encrypted keystore from hex key
  %(prog)s create-keystore --privkey <64-hex> --keystore-out keystore.json

  # Verify an existing message hex string or file
  %(prog)s verify --file transition_message.hex

  # NODE OPERATOR: Just paste the hex string from the authority
  python run_p2pool.py [options] --transition-message 01a2b3c4d5e6f7...

AUTHORITY KEYS:
  forrestv:   03ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1
  maintainer: 02fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a
""")

    subparsers = parser.add_subparsers(dest='command', help='Command')

    # --- create command ---
    create_parser = subparsers.add_parser(
        'create', help='Create a signed+encrypted transition message')

    key_group = create_parser.add_mutually_exclusive_group(required=True)
    key_group.add_argument('--privkey', type=str,
                           help='Hex-encoded 32-byte private key')
    key_group.add_argument('--privkey-file', type=str,
                           help='Path to file containing hex private key')
    key_group.add_argument('--seed-phrase', type=str,
                           help='BIP39 mnemonic seed phrase (12 or 24 words)')
    key_group.add_argument('--keystore', type=str,
                           help='Path to encrypted keystore JSON file')

    create_parser.add_argument('--derivation-path', type=str,
                               default="m/44'/2'/0'/0/0",
                               help="BIP32 derivation path (default: m/44'/2'/0'/0/0)")
    create_parser.add_argument('--from', type=str, required=True, dest='from_ver',
                               help='Current share version (e.g. 36)')
    create_parser.add_argument('--to', type=str, required=True, dest='to_ver',
                               help='Target share version (e.g. 37)')
    create_parser.add_argument('--msg', type=str, required=True,
                               help='Human-readable transition message')
    create_parser.add_argument('--urgency', type=str, default='recommended',
                               choices=['info', 'recommended', 'required'],
                               help='Urgency level (default: recommended)')
    create_parser.add_argument('--url', type=str, default=None,
                               help='URL for upgrade release')
    create_parser.add_argument('--threshold', type=int, default=None,
                               help='Activation threshold percentage')
    create_parser.add_argument('--output', '-o', type=str, default=None,
                               help='Output file base name (default: transition_message_v<from>_v<to>)')

    # --- create-keystore command ---
    ks_parser = subparsers.add_parser(
        'create-keystore', help='Create an encrypted keystore from a private key')

    ks_key_group = ks_parser.add_mutually_exclusive_group(required=True)
    ks_key_group.add_argument('--privkey', type=str,
                              help='Hex-encoded 32-byte private key')
    ks_key_group.add_argument('--privkey-file', type=str,
                              help='Path to file containing hex private key')

    ks_parser.add_argument('--keystore-out', type=str, required=True,
                           help='Output keystore file path')
    ks_parser.add_argument('--iterations', type=int, default=100000,
                           help='PBKDF2 iterations (default: 100000)')

    # --- verify command ---
    verify_parser = subparsers.add_parser(
        'verify', help='Verify an existing encrypted message (hex string or file)')
    verify_parser.add_argument('--file', type=str, required=True,
                               help='Hex string, hex file path, or binary file path')

    # --- announce command ---
    announce_parser = subparsers.add_parser(
        'announce', help='Create a signed+encrypted authority announcement')

    ann_key_group = announce_parser.add_mutually_exclusive_group(required=True)
    ann_key_group.add_argument('--privkey', type=str,
                               help='Hex-encoded 32-byte private key')
    ann_key_group.add_argument('--privkey-file', type=str,
                               help='Path to file containing hex private key')
    ann_key_group.add_argument('--seed-phrase', type=str,
                               help='BIP39 mnemonic seed phrase')
    ann_key_group.add_argument('--keystore', type=str,
                               help='Path to encrypted keystore JSON file')

    announce_parser.add_argument('--derivation-path', type=str,
                                 default="m/44'/2'/0'/0/0",
                                 help="BIP32 derivation path")
    announce_parser.add_argument('--msg', type=str, required=True,
                                 help='Announcement text')
    announce_parser.add_argument('--urgency', type=str, default='info',
                                 choices=['info', 'recommended', 'required', 'alert'],
                                 help='Urgency level (default: info)')
    announce_parser.add_argument('--url', type=str, default=None,
                                 help='Optional URL')
    announce_parser.add_argument('--emergency', action='store_true',
                                 help='Create as MSG_EMERGENCY (0x10) instead of MSG_POOL_ANNOUNCE (0x03)')
    announce_parser.add_argument('--output', '-o', type=str, default=None,
                                 help='Output file base name')

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # ---- VERIFY ----
    if args.command == 'verify':
        verify_message_file(args.file)
        return

    # ---- CREATE-KEYSTORE ----
    if args.command == 'create-keystore':
        if args.privkey:
            privkey = load_privkey_hex(args.privkey)
        else:
            privkey = load_privkey_file(args.privkey_file)

        password = getpass.getpass('Set keystore password: ')
        password2 = getpass.getpass('Confirm password: ')
        if password != password2:
            print('ERROR: Passwords do not match', file=sys.stderr)
            sys.exit(1)

        create_keystore(privkey, password, args.keystore_out, args.iterations)
        return

    # ---- CREATE ----
    if args.command == 'create':
        # Load private key
        if args.privkey:
            privkey = load_privkey_hex(args.privkey)
        elif args.privkey_file:
            privkey = load_privkey_file(args.privkey_file)
        elif args.seed_phrase:
            privkey = load_privkey_from_seed(
                args.seed_phrase, args.derivation_path)
        elif args.keystore:
            privkey = load_privkey_from_keystore(args.keystore)
        else:
            print('ERROR: No key source specified', file=sys.stderr)
            sys.exit(1)

        # Derive pubkey and check authority
        pubkey = derive_compressed_pubkey(privkey)
        if pubkey == DONATION_PUBKEY_FORRESTV:
            key_name = 'forrestv'
        elif pubkey == DONATION_PUBKEY_MAINTAINER:
            key_name = 'maintainer'
        else:
            print('ERROR: Derived pubkey is NOT a COMBINED_DONATION_SCRIPT '
                  'authority key.', file=sys.stderr)
            print(f'  Derived: {pubkey.hex()}', file=sys.stderr)
            print(f'  Expected:', file=sys.stderr)
            print(f'    forrestv:   {DONATION_PUBKEY_FORRESTV.hex()}',
                  file=sys.stderr)
            print(f'    maintainer: {DONATION_PUBKEY_MAINTAINER.hex()}',
                  file=sys.stderr)
            sys.exit(1)

        print(f'Authority key: {key_name}')
        print(f'Pubkey: {pubkey.hex()}')
        print()

        # Create the message
        encrypted, _, ts, payload, signature = create_signed_encrypted_message(
            privkey,
            from_ver=args.from_ver,
            to_ver=args.to_ver,
            msg_text=args.msg,
            urgency=args.urgency,
            url=args.url,
            threshold=args.threshold,
        )

        # Determine output file names
        base_name = args.output or f'transition_message_v{args.from_ver}_v{args.to_ver}'
        hex_path = base_name + '.hex'

        # The hex string IS the primary output
        hex_string = encrypted.hex()

        # Write hex file (can also be passed as file path to --transition-message)
        with open(hex_path, 'w') as f:
            f.write(hex_string + '\n')

        # Self-verify
        inner, auth_key = decrypt_message_data(encrypted)
        if inner is None:
            print('ERROR: Self-verification FAILED — decryption failed!',
                  file=sys.stderr)
            sys.exit(1)

        print(f'Message created successfully!')
        print()
        print(f'  Transition: v{args.from_ver} -> v{args.to_ver}')
        print(f'  Message:    {args.msg}')
        print(f'  Urgency:    {args.urgency}')
        if args.url:
            print(f'  URL:        {args.url}')
        print(f'  Timestamp:  {time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))}')
        print(f'  Authority:  {key_name} ({pubkey.hex()[:16]}...)')
        print(f'  Size:       {len(encrypted)} bytes')
        print(f'  Verified:   OK')
        print()
        print(f'='*72)
        print(f'HEX STRING (give this to node operators):')
        print(f'='*72)
        print(hex_string)
        print(f'='*72)
        print()
        print(f'Saved to: {hex_path}')
        print()
        print(f'NODE OPERATORS: paste the hex string above into your p2pool startup:')
        print(f'  python run_p2pool.py [options] \\')
        print(f'    --transition-message {hex_string[:40]}...')
        print()
        print(f'Or point to the hex file:')
        print(f'  python run_p2pool.py [options] \\')
        print(f'    --transition-message {hex_path}')

        # Clear privkey from memory
        privkey = b'\x00' * 32
        del privkey

    # ---- ANNOUNCE ----
    if args.command == 'announce':
        # Load private key
        if args.privkey:
            privkey = load_privkey_hex(args.privkey)
        elif args.privkey_file:
            privkey = load_privkey_file(args.privkey_file)
        elif args.seed_phrase:
            privkey = load_privkey_from_seed(
                args.seed_phrase, args.derivation_path)
        elif args.keystore:
            privkey = load_privkey_from_keystore(args.keystore)
        else:
            print('ERROR: No key source specified', file=sys.stderr)
            sys.exit(1)

        pubkey = derive_compressed_pubkey(privkey)
        if pubkey == DONATION_PUBKEY_FORRESTV:
            key_name = 'forrestv'
        elif pubkey == DONATION_PUBKEY_MAINTAINER:
            key_name = 'maintainer'
        else:
            print('ERROR: Derived pubkey is NOT a COMBINED_DONATION_SCRIPT '
                  'authority key.', file=sys.stderr)
            sys.exit(1)

        msg_type_name = 'EMERGENCY' if args.emergency else 'ANNOUNCEMENT'
        print(f'Authority key: {key_name}')
        print(f'Message type:  {msg_type_name}')
        print()

        encrypted, _, ts, payload, signature = create_announcement_blob(
            privkey,
            msg_text=args.msg,
            urgency=args.urgency,
            url=args.url,
            is_emergency=args.emergency,
        )

        base_name = args.output or f'announcement_{int(ts)}'
        hex_path = base_name + '.hex'
        hex_string = encrypted.hex()

        with open(hex_path, 'w') as f:
            f.write(hex_string + '\n')

        print(f'{msg_type_name} created successfully!')
        print()
        print(f'  Message:    {args.msg}')
        print(f'  Urgency:    {args.urgency}')
        if args.url:
            print(f'  URL:        {args.url}')
        print(f'  Timestamp:  {time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))}')
        print(f'  Authority:  {key_name}')
        print(f'  Size:       {len(encrypted)} bytes')
        print()
        print(f'={""*71}')
        print(f'HEX STRING (load via /msg/load_blob or --transition-message):')
        print(f'={""*71}')
        print(hex_string)
        print(f'={""*71}')
        print()
        print(f'Saved to: {hex_path}')
        print()
        print(f'Load at runtime: curl -X POST http://localhost:9327/msg/load_blob \\')
        print(f'  -H "Content-Type: application/json" \\')
        print(f'  -d \'{{"blob_hex": "{hex_string[:40]}..."}}\'')

        privkey = b'\x00' * 32
        del privkey


if __name__ == '__main__':
    main()
