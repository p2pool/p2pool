# P2Pool Share Messaging — Wire Protocol Specification

## Version

Protocol Version: 1  
Share Version: 36 (V36 `ref_type` extension)

## Terminology

| Term | Definition |
|------|-----------|
| **Master PK** | Miner's payout address private key (never transmitted) |
| **Signing Key** | HMAC-derived key used to sign messages |
| **signing_id** | HASH160(compressed signing pubkey) — 20-byte identifier |
| **key_index** | uint32 rotation counter for signing key derivation |
| **ref_type** | Share structure hashed into ref_hash (PoW-protected, not in coinbase) |
| **message_data** | VarStr field in ref_type carrying the message envelope |

## Share ref_type Extension

### Current V36 ref_type (before messaging)

```
ref_type = ComposedType([
    ('identifier',  FixedStrType(8)),
    ('share_info',  share_info_type),
])
```

### Extended V36 ref_type (with messaging)

```
ref_type = ComposedType([
    ('identifier',    FixedStrType(8)),
    ('share_info',    share_info_type),
    ('message_data',  PossiblyNoneType(b'', VarStrType())),   # NEW
])
```

The `message_data` field:
- Default value: `b''` (empty bytes) — no messages
- Wrapped in `PossiblyNoneType` for backward compatibility
- Included in `ref_hash` computation → PoW-protected
- NOT included in coinbase/gentx → never written to blockchain

**Note**: `message_data` is also added to the share contents type (not just
ref_type) so it is persisted and transmitted alongside the share. Both
additions are V36-specific — `MergedMiningShare.get_dynamic_types()` adds
them only when `cls.VERSION >= 36`. Older share versions are unaffected.

## Encrypted Envelope Format

All `message_data` in V36 shares is encrypted using the authority pubkey
encryption scheme defined in `share_messages.py`. The encryption uses
`HMAC-SHA256` key derivation + XOR stream cipher + `HMAC-SHA256` MAC.

### Outer Encrypted Envelope

```
Offset  Size  Field               Description
------  ----  ------------------  ------------------------------------------
0       1     version             Encryption version (0x01)
1       16    nonce               Random 16-byte nonce
17      32    mac                 HMAC-SHA256(enc_key, ciphertext)
49      N     ciphertext          Encrypted inner envelope
```

### Encryption/Decryption

```
Key derivation:
  enc_key = HMAC-SHA256(key=authority_pubkey, msg=nonce)    # 32 bytes

Encrypt:
  stream = SHA256(enc_key||0) || SHA256(enc_key||1) || ...  # counter-mode
  ciphertext = XOR(inner_data, stream)
  mac = HMAC-SHA256(enc_key, ciphertext)

Decrypt (receiver):
  For each pubkey in DONATION_AUTHORITY_PUBKEYS:
    enc_key = HMAC-SHA256(pubkey, nonce)
    mac_check = HMAC-SHA256(enc_key, ciphertext)
    if mac_check == mac:
      stream = SHA256(enc_key||0) || SHA256(enc_key||1) || ...
      inner_data = XOR(ciphertext, stream)
      → decrypted by this authority key
```

### Authority Pubkeys

The encryption/decryption keys are derived from the hardcoded
`COMBINED_DONATION_SCRIPT` pubkeys:

| Key Holder | Compressed Pubkey |
|---|---|
| forrestv | `03ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1` |
| maintainer | `02fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a` |

## Inner Message Envelope Format

After decryption, the inner `message_data` bytes contain:

```
Offset  Size  Field               Description
------  ----  ------------------  ------------------------------------------
0       1     version             Protocol version (currently 1)
1       1     envelope_flags      Bit flags for envelope
2       1     msg_count           Number of messages (0-3)
3       1     announcement_len    Length of signing key announcement (0 or 57)
4       N     announcement        Signing key announcement (if announcement_len > 0)
4+N     ...   messages[]          Packed messages (msg_count entries)
```

### Envelope Flags

```
Bit 0 (0x01): Has signing key announcement
Bits 1-7:     Reserved (must be 0)
```

### Total Size Budget

```
Envelope header:                     4 bytes
Signing key announcement (optional): 57 bytes
Per message overhead (minimum):      29 bytes (header + signing_id + sig_len)
Per message payload:                 0-220 bytes
Per message signature:               0-73 bytes (DER ECDSA)

Maximum total:                       512 bytes
```

## Signing Key Announcement Format

Carried in the envelope when a miner announces or rotates their signing key.

```
Offset  Size  Field            Description
------  ----  ---------------  ------------------------------------------
0       20    signing_id       HASH160(compressed signing pubkey)
20      4     key_index        Little-endian uint32 rotation counter
24      33    signing_pubkey   Compressed secp256k1 public key (02/03 prefix)
                               
Total:  57 bytes
```

### Verification

Recipients verify the announcement by checking:
```
HASH160(signing_pubkey) == signing_id
```

If this check fails, the announcement is silently discarded.

### Key Index Semantics

- `key_index = 0`: First signing key (initial announcement)
- `key_index = N`: N-th rotation
- When a node sees `key_index > previous_key_index` for a miner:
  - All signing keys with lower key_index are marked **REVOKED**
  - Messages signed with revoked keys fail verification
- A miner should include the announcement in every share (not just on rotation)
  to ensure new nodes learn the current signing key

## Message Wire Format

Each message in the `messages[]` array:

```
Offset  Size  Field            Description
------  ----  ---------------  ------------------------------------------
0       1     msg_type         Message type (see table below)
1       1     msg_flags        Per-message flags
2       4     timestamp        Unix timestamp (little-endian uint32)
6       2     payload_len      Payload length (little-endian uint16)
8       N     payload          Message payload (0-220 bytes)
8+N     20    signing_id       HASH160 of signer's pubkey (or 20 zero bytes)
28+N    1     sig_len          Signature length (0-73)
29+N    M     signature        DER-encoded ECDSA signature (if sig_len > 0)
```

### Message Types

```
Value  Name              Signed?     Persistent?  Description
-----  ----------------  ----------  -----------  ---------------------------
0x01   NODE_STATUS       Optional    No           Node health report
0x02   MINER_MESSAGE     Required    Yes          Miner-to-miner text
0x03   POOL_ANNOUNCE     Required    Yes          Operator announcement
0x04   VERSION_SIGNAL    Optional    No           Extended version info
0x05   MERGED_STATUS     Optional    No           Merged chain status
0x10   EMERGENCY         Required    Yes          Security alert
0x20   TRANSITION_SIGNAL Required    Yes          Protocol transition alert

0x00, 0x06-0x0F, 0x11-0x1F, 0x21-0xFF: Reserved for future use
```

### Message Flags

```
Bit 0 (0x01): FLAG_HAS_SIGNATURE      — Message is signed
Bit 1 (0x02): FLAG_BROADCAST          — Relay to peers
Bit 2 (0x04): FLAG_PERSISTENT         — Store in history
Bit 3 (0x08): FLAG_PROTOCOL_AUTHORITY — Signed by donation authority key
Bits 4-7:     Reserved (must be 0)
```

**FLAG_PROTOCOL_AUTHORITY (0x08)**: This flag is NEVER trusted from the wire.
It is stripped during unpacking and re-earned only by passing
`verify_authority_direct()` against one of the `DONATION_AUTHORITY_PUBKEYS`.
This prevents spoofing — a malicious sender cannot simply set the flag.

Common flag combinations:

| Flags | Meaning |
|-------|---------|
| `0x07` | Signed + Broadcast + Persistent (typical chat message) |
| `0x0F` | Authority-signed + Broadcast + Persistent (transition signal) |
| `0x02` | Unsigned + Broadcast (anonymous status report) |

### Unsigned Messages

For unsigned messages (e.g., NODE_STATUS without FLAG_HAS_SIGNATURE):
- `signing_id` is set to 20 zero bytes (`\x00` × 20)
- `sig_len` is 0
- `signature` is empty

The message is still PoW-protected (embedded in ref_hash via the share)
but is not cryptographically attributed to a specific signing key.
The sender is identified only by the share's payout address.

## Signature Scheme

### What is Signed

```
message_hash = SHA256d(msg_type || msg_flags || timestamp || payload)
             = SHA256(SHA256(pack('<BBI', type, flags, timestamp) + payload))
```

The signature does NOT cover signing_id — this prevents circular dependency
(signing_id is used to look up the verification key, not as signed data).

### Signing

```
signature = ECDSA_sign_secp256k1(signing_privkey, message_hash)
```

Output: DER-encoded signature (typically 70-73 bytes).

### Verification

```
1. Extract signing_id from message
2. Look up signing_pubkey in SigningKeyRegistry
3. Check key is not revoked (key_index >= miner's current_key_index)
4. Compute message_hash from message fields
5. ECDSA_verify_secp256k1(signing_pubkey, message_hash, signature)
```

### Signing Key Derivation (Detailed)

```
Input:
  master_privkey:  32 bytes (payout address private key)
  key_index:       uint32

Process:
  domain = b"p2pool-msg-v1" || pack('<I', key_index)   # 17 bytes
  signing_privkey = HMAC-SHA256(key=master_privkey, msg=domain)  # 32 bytes
  signing_pubkey  = secp256k1_point(signing_privkey)             # 33 bytes compressed
  signing_id      = RIPEMD160(SHA256(signing_pubkey))            # 20 bytes

Output:
  signing_privkey:  32 bytes (for signing)
  signing_pubkey:   33 bytes (announced in shares)
  signing_id:       20 bytes (message attribution)
```

## Payload Formats

### NODE_STATUS (0x01)

Compact JSON payload:

```json
{
  "v": "13.4-604-g02a27df",
  "up": 86400,
  "hr": 1500000,
  "sc": 8640,
  "p": 3,
  "mc": ["DOGE"],
  "cap": ["v36", "mm", "msg"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| v | string | Software version |
| up | int | Uptime in seconds |
| hr | int | Local hashrate (H/s) |
| sc | int | Share chain height |
| p | int | Connected peers |
| mc | string[] | Merged chains (optional) |
| cap | string[] | Capabilities (optional) |

### MINER_MESSAGE (0x02)

UTF-8 encoded text, max 220 bytes.

```
Hello from YOUR_LTC_ADDRESS! First PoW-authenticated message.
```

### POOL_ANNOUNCE (0x03)

UTF-8 encoded text, max 220 bytes.

```
Maintenance window: 2026-02-15 00:00-04:00 UTC. Expect brief downtime.
```

### VERSION_SIGNAL (0x04)

Compact JSON payload:

```json
{
  "ver": 36,
  "feat": ["mm", "segwit", "mweb", "msg"],
  "proto": 3600
}
```

### MERGED_STATUS (0x05)

Compact JSON payload:

```json
{
  "chain": "Dogecoin",
  "sym": "DOGE",
  "h": 5234567,
  "bv": 10000.0,
  "bf": 3
}
```

| Field | Type | Description |
|-------|------|-------------|
| chain | string | Chain name |
| sym | string | Ticker symbol |
| h | int | Block height |
| bv | float | Block value |
| bf | int | Blocks found (local) |

### EMERGENCY (0x10)

UTF-8 encoded text, max 220 bytes.

```
CRITICAL: v36 activation bug found. Upgrade to commit abc1234 immediately.
```

### TRANSITION_SIGNAL (0x20)

Compact JSON payload, authority-signed. Created offline using
`create_transition_message.py` by a COMBINED_DONATION_SCRIPT key holder.

```json
{
  "from": "36",
  "to": "37",
  "msg": "Upgrade to V37 for MWEB merged mining support",
  "urg": "recommended",
  "url": "https://github.com/frstrtr/p2pool-merged-v36/releases",
  "thr": 95
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| from | string | Yes | Current share version |
| to | string | Yes | Target share version |
| msg | string | Yes | Human-readable upgrade guidance |
| urg | string | No | Urgency: `info`, `recommended`, `required` |
| url | string | No | Upgrade download URL |
| thr | int | No | Activation threshold percentage |

**Workflow**:
1. Authority key holder runs `create_transition_message.py create` → hex string
2. Hex string distributed to operators (GitHub release, website, etc.)
3. Operators paste into `--transition-message <hex>` (no private key needed)
4. Node validates + embeds in every mined V36 share
5. Other nodes display as warning via `get_warnings()` transition scanner

## Wire Obfuscation Layer

All `message_data` bytes in shares are obfuscated before packing into
`ref_type`. This prevents passive TCP traffic analysis by anyone not running
a p2pool node. It is NOT cryptographic security — any p2pool node can
deobfuscate.

### Obfuscation Key Derivation

```
obfuscation_key = SHA256("p2pool-msg-obfuscate" || net.IDENTIFIER)   # 32 bytes
```

`net.IDENTIFIER` is the 8-byte network identifier already used by p2pool.
The obfuscation key is deterministic and the same for all nodes on the
same network.

### Obfuscation Process

```
Encrypt (before packing into ref_type):
  nonce      = share_hash[:12]                        # 12 bytes from the share hash
  keystream  = SHA256(obfuscation_key || nonce)       # truncate/extend as needed
  ciphertext = XOR(message_data, keystream)

Decrypt (after unpacking from ref_type):
  nonce      = share_hash[:12]
  keystream  = SHA256(obfuscation_key || nonce)
  plaintext  = XOR(ciphertext, keystream)
```

For messages longer than 32 bytes, extend the keystream by hashing
successive counter values: `SHA256(obfuscation_key || nonce || counter)`.

### Rationale

- Prevents ISP/network-level inspection of p2pool message content
- Zero performance overhead (single SHA256 per share)
- Does not require key exchange or per-peer state
- Any p2pool node can still read all messages (this is by design)

## Private Message Encryption (ECDH)

For private miner-to-miner messages (`MINER_MESSAGE` with `FLAG_PRIVATE`),
end-to-end encryption ensures only the intended recipient can read the
content.

### Message Flag Extension

```
Bit 3 (0x08): FLAG_PRIVATE — Payload is ECDH-encrypted for a specific recipient
```

### Private Message Wire Format

```
Offset  Size  Field            Description
------  ----  ---------------  ------------------------------------------
0       20    recipient_id     signing_id of intended recipient
20      N     ciphertext       AES-256-GCM encrypted payload

The ciphertext replaces the normal plaintext payload.
```

### ECDH Key Agreement

```
Both parties have signing keys (secp256k1):
  Sender:    (sender_privkey, sender_pubkey)     — from DerivedSigningKey
  Recipient: (recipient_privkey, recipient_pubkey) — from DerivedSigningKey

Shared secret:
  shared_point = ECDH(sender_privkey, recipient_pubkey)
               = ECDH(recipient_privkey, sender_pubkey)       # same result
  shared_secret = SHA256(shared_point.x || shared_point.y)    # 32 bytes

Encryption key derivation:
  encryption_key = HMAC-SHA256(shared_secret, "p2pool-msg-encrypt")   # 32 bytes
  nonce          = timestamp[4 bytes] || counter[4 bytes] || zero[4 bytes]  # 12 bytes

Encrypt:
  ciphertext, tag = AES-256-GCM(encryption_key, nonce, plaintext)

Decrypt (recipient):
  plaintext = AES-256-GCM_decrypt(encryption_key, nonce, ciphertext, tag)
```

### Private Message Behavior

- All nodes relay private messages in shares (they're PoW-protected)
- Non-recipient nodes see only: recipient_id + opaque ciphertext
- Only the recipient can decrypt using ECDH shared secret
- Sender identity is still visible (signing_id and signature are unencrypted)
- To hide sender identity: use unsigned private messages (signing_id = zeros)
  but this removes authentication

### Forward Secrecy Limitation

ECDH with static signing keys does NOT provide forward secrecy.
If a signing key is compromised, past messages can be decrypted.
Mitigation: Frequent key rotation (incrementing key_index).

## Deduplication

Messages are deduplicated by their `message_hash` (double-SHA256 of content).
If two shares carry the same message (same type, flags, timestamp, and payload),
only the first received copy is stored.

## Message Expiry

Messages older than 24 hours (86400 seconds) are pruned from the in-memory
store. The store also enforces a maximum of 1000 messages.

## Implementation Files

| File | Purpose |
|------|---------|
| `p2pool/share_messages.py` | Core module: messages, signing, encryption, registry, store |
| `p2pool/data.py` | V36 ref_type extension, strict message validation in check() |
| `p2pool/work.py` | Transition message loading + embedding in shares |
| `p2pool/main.py` | `--transition-message` CLI argument |
| `create_transition_message.py` | Standalone Python 3 authority message creator |
| `SHARE_MESSAGING_PROTOCOL.md` | This document — wire format specification |
| `SHARE_MESSAGING_DESIGN.md` | Architecture and design rationale |
| `SHARE_MESSAGING_INTEGRATION.md` | Code integration plan and status |
| `SHARE_MESSAGING_API.md` | HTTP API reference |
| `SHARE_MESSAGING_QUICKSTART.md` | Operator/miner quick start guide |
| `SHARE_MESSAGING_SECURITY.md` | Security model and threat analysis |

## Backward Compatibility

### Old Nodes (V35 and below)

Old nodes do not understand `message_data` in `ref_type`. The field uses
`PossiblyNoneType` with default `b''`, so:

- When parsing V36 shares from V36 nodes: old nodes ignore the field
- When V36 nodes parse shares without messages: `message_data = b''`
- ref_hash computation with `b''` matches the "no messages" case

### Version 1 Protocol

The envelope `version` byte enables future protocol upgrades:
- Version 1 nodes ignore envelopes with `version > 1`
- Future versions can add new fields after existing ones
- Message types 0x06-0x0F, 0x11-0x1F, and 0x21-0xFF are reserved

## Example: Complete Share with Transition Signal

```
Share V36:
  min_header: { version, previous_block, ... }
  share_info: { share_data, segwit_data, merged_addresses, ... }
  ref_merkle_link: { branch, index }
  last_txout_nonce: 42
  hash_link: { state, length, extra_data }
  merkle_link: { branch, index }
  message_data: <encrypted envelope>               # V36+: stored in share contents

ref_type (hashed into ref_hash, NOT in coinbase):
  identifier: "\xfe\x4f\xe0\x14\x79\x25\x4f\x80"
  share_info: <same as above>
  message_data: <encrypted envelope>               # Included in ref_hash → PoW-protected

ENCRYPTED ENVELOPE (message_data bytes):
  version: 0x01 (encryption version)
  nonce: <16 random bytes>
  mac: <32 bytes HMAC-SHA256>
  ciphertext: <N bytes>

  After decryption with authority pubkey:

  INNER ENVELOPE:
    inner_version: 1
    inner_flags: 0x00 (no announcement)
    msg_count: 1
    announcement_len: 0
    message[0]:
      type: 0x20 (TRANSITION_SIGNAL)
      flags: 0x0F (signed + broadcast + persistent + authority)
      timestamp: 1707580800
      payload_len: 120
      payload: {"from":"36","to":"37","msg":"Upgrade to V37","urg":"recommended","url":"..."}
      signing_id: <20 zero bytes> (authority messages use empty signing_id)
      sig_len: 71
      signature: <71 bytes DER ECDSA>

  Total inner: 4 + 8 + 120 + 20 + 1 + 71 = 224 bytes
  Total encrypted: 1 + 16 + 32 + 224 = 273 bytes

ref_hash = merkle(SHA256d(ref_type.pack(identifier, share_info, message_data)))
  └── Includes encrypted envelope → PoW protects transition signal
  └── Any p2pool node can decrypt (knows authority pubkeys) and verify signature
  └── Non-p2pool observers see only opaque ciphertext
```
