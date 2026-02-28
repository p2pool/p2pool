# P2Pool Share Messaging — API Reference

## Version

API Version: 1  
Base URL: `http://<node_host>:<worker_port>` (default port 9327 for Litecoin)

## Overview

The Share Messaging API provides HTTP endpoints for interacting with the
PoW-authenticated messaging system embedded in P2Pool V36 shares. All
messages are authenticated by share Proof-of-Work — only miners who produce
valid shares can send messages.

Messages propagate via the existing P2Pool share protocol. No additional
P2P connections or infrastructure are required.

> **Implementation Status**: The HTTP API endpoints below are **planned
> (Phase 3+)** and not yet implemented. Currently implemented: core
> messaging module (`share_messages.py`), share-embedded message validation
> (`data.py`), transition signal embedding (`work.py`, `main.py`), and
> the standalone authority message tool (`create_transition_message.py`).
> This document serves as the API specification for when the web layer
> is built.

---

## Endpoints Summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/msg/recent` | Recent messages (all types) |
| GET | `/msg/chat` | Miner chat messages only |
| GET | `/msg/announcements` | Pool operator announcements |
| GET | `/msg/alerts` | Emergency security alerts |
| GET | `/msg/status` | Node status reports |
| GET | `/msg/keys` | Signing key registry |
| GET | `/msg/identity` | This node's signing identity |
| GET | `/msg/stats` | Messaging system statistics |
| POST | `/msg/send` | Queue a message for next share |
| POST | `/msg/ban` | Ban a sender (local policy) |
| DELETE | `/msg/ban` | Remove a ban |
| GET | `/msg/bans` | List active bans |

---

## Message Types

| Type ID | Name | Constant | Signed | Persistent | Description |
|---------|------|----------|--------|------------|-------------|
| `0x01` | Node Status | `MSG_NODE_STATUS` | Optional | No | Node health telemetry |
| `0x02` | Miner Message | `MSG_MINER_MESSAGE` | Required | Yes | Miner-to-miner text |
| `0x03` | Pool Announce | `MSG_POOL_ANNOUNCE` | Required | Yes | Operator announcement |
| `0x04` | Version Signal | `MSG_VERSION_SIGNAL` | Optional | No | Extended version info |
| `0x05` | Merged Status | `MSG_MERGED_STATUS` | Optional | No | Merged chain status |
| `0x10` | Emergency | `MSG_EMERGENCY` | Required | Yes | Security alert |
| `0x20` | Transition Signal | `MSG_TRANSITION_SIGNAL` | Required | Yes | Protocol transition |

---

## Endpoint Details

### GET /msg/recent

Returns the most recent messages across all types.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Maximum messages to return (1-200) |
| `since` | int | 0 | Unix timestamp — only messages newer than this |

**Response**

```json
{
  "messages": [
    {
      "msg_type": 2,
      "type_name": "MINER_MESSAGE",
      "flags": 7,
      "timestamp": 1707580800,
      "payload": "Hello from miner A!",
      "signing_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "has_signature": true,
      "verified": true,
      "sender_address": "YOUR_LTC_ADDRESS",
      "share_hash": "0000000012345678...",
      "age": 120.5,
      "message_hash": "abc123..."
    }
  ],
  "stats": {
    "total_messages": 42,
    "total_by_type": {
      "NODE_STATUS": 20,
      "MINER_MESSAGE": 15,
      "POOL_ANNOUNCE": 5,
      "EMERGENCY": 2
    },
    "known_signers": 8,
    "oldest_message_age": 82400,
    "newest_message_age": 30
  }
}
```

**Message Object Fields**

| Field | Type | Description |
|-------|------|-------------|
| `msg_type` | int | Message type ID (see table above) |
| `type_name` | string | Human-readable type name |
| `flags` | int | Message flags bitmask |
| `timestamp` | int | Unix timestamp when message was created |
| `payload` | string | Message content (UTF-8 text or JSON string) |
| `signing_id` | string | Hex-encoded 20-byte signer identifier |
| `has_signature` | bool | Whether message carries ECDSA signature |
| `verified` | bool | Whether signature verified against known key |
| `sender_address` | string | Payout address of the share that carried this message |
| `share_hash` | string | Hash of the share that carried this message |
| `age` | float | Seconds since message timestamp |
| `message_hash` | string | Hex SHA256d hash for deduplication |

---

### GET /msg/chat

Returns only `MINER_MESSAGE` (0x02) type messages.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Maximum messages to return |

**Response**

```json
{
  "messages": [
    {
      "msg_type": 2,
      "type_name": "MINER_MESSAGE",
      "payload": "merged mining DOGE working great",
      "signing_id": "b2c3d4e5f6...",
      "verified": true,
      "sender_address": "LRF2Z...DDp",
      "age": 300.0
    }
  ]
}
```

---

### GET /msg/announcements

Returns only `POOL_ANNOUNCE` (0x03) type messages.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Maximum messages to return |

**Response**: Same structure as `/msg/chat`, filtered to type 0x03.

---

### GET /msg/alerts

Returns only `EMERGENCY` (0x10) type messages. These are critical security
alerts that node operators should always display prominently.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 10 | Maximum alerts to return |

**Response**

```json
{
  "alerts": [
    {
      "msg_type": 16,
      "type_name": "EMERGENCY",
      "payload": "CRITICAL: v35.02 bug found. Upgrade immediately.",
      "signing_id": "c3d4e5f6...",
      "verified": true,
      "has_signature": true,
      "age": 600.0
    }
  ]
}
```

**Display Guidance**: Emergency alerts should be displayed as a sticky red
banner on all dashboard pages. Verified alerts (signed by a known key)
should be given highest visual priority.

---

### GET /msg/status

Returns `NODE_STATUS` (0x01) messages from the network. These provide a
view of the health and capabilities of other nodes.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Maximum status messages to return |

**Response**

```json
{
  "statuses": [
    {
      "msg_type": 1,
      "type_name": "NODE_STATUS",
      "payload": "{\"v\":\"13.4-604-g02a27df\",\"up\":86400,\"hr\":1500000,\"sc\":8640,\"p\":3,\"mc\":[\"DOGE\"],\"cap\":[\"v36\",\"mm\",\"msg\"]}",
      "sender_address": "LtcAd...",
      "age": 120.0
    }
  ]
}
```

**Status Payload Fields** (JSON inside `payload`)

| Field | Type | Description |
|-------|------|-------------|
| `v` | string | Software version string |
| `up` | int | Uptime in seconds |
| `hr` | int | Local hashrate in H/s |
| `sc` | int | Share chain height |
| `p` | int | Connected peer count |
| `mc` | string[] | Merged mining chains (optional) |
| `cap` | string[] | Node capabilities (optional) |

---

### GET /msg/keys

Returns the signing key registry — all known signing keys that have been
announced via share messages.

**Response**

```json
{
  "keys": [
    {
      "signing_id": "a1b2c3d4e5f6...",
      "key_index": 0,
      "signing_pubkey": "02abcd1234...",
      "miner_address": "YOUR_LTC_ADDRESS",
      "first_seen": 1707580800,
      "last_seen": 1707667200,
      "share_count": 42,
      "messages_signed": 15,
      "revoked": false
    }
  ],
  "total_keys": 8,
  "active_keys": 6,
  "revoked_keys": 2
}
```

**Key Object Fields**

| Field | Type | Description |
|-------|------|-------------|
| `signing_id` | string | HASH160 of the compressed signing pubkey (hex) |
| `key_index` | int | Key rotation counter |
| `signing_pubkey` | string | Compressed secp256k1 public key (hex) |
| `miner_address` | string | Associated payout address |
| `first_seen` | int | Unix timestamp of first announcement |
| `last_seen` | int | Unix timestamp of most recent use |
| `share_count` | int | Shares carrying this key's announcement |
| `messages_signed` | int | Messages signed with this key |
| `revoked` | bool | Whether key has been superseded by higher key_index |

---

### GET /msg/identity

Returns this node's signing identity (public information only).

**Response (with signing key configured)**

```json
{
  "signing_id": "a1b2c3d4e5f6...",
  "signing_pubkey": "02abcd1234...",
  "key_index": 0,
  "address": "YOUR_LTC_ADDRESS",
  "messaging_enabled": true
}
```

**Response (no signing key)**

```json
{
  "messaging_enabled": false,
  "error": "no signing key configured — use --signing-key to enable messaging"
}
```

---

### GET /msg/stats

Returns messaging system statistics.

**Response**

```json
{
  "total_messages": 42,
  "total_by_type": {
    "NODE_STATUS": 20,
    "MINER_MESSAGE": 15,
    "POOL_ANNOUNCE": 5,
    "VERSION_SIGNAL": 0,
    "MERGED_STATUS": 0,
    "EMERGENCY": 2,
    "TRANSITION_SIGNAL": 0
  },
  "known_signers": 8,
  "active_signers": 6,
  "revoked_keys": 2,
  "oldest_message_age": 82400,
  "newest_message_age": 30,
  "messages_per_hour": 1.75,
  "store_capacity": 1000,
  "store_usage_pct": 4.2,
  "messaging_enabled": true,
  "signing_key_configured": true
}
```

---

### POST /msg/send

Queue a message for embedding in the next mined share.

**Requires**: `--signing-key` configured on the node.

**Request Body**

```json
{
  "type": "chat",
  "text": "Hello, miners!"
}
```

**Fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | One of: `chat`, `announce`, `alert`, `status` |
| `text` | string | Yes | Message text (max 220 bytes UTF-8) |
| `to` | string | No | Recipient signing_id for private messages (hex) |

**Type Mapping**

| `type` value | Message Type | Requires Signing |
|--------------|-------------|-----------------|
| `chat` | `MSG_MINER_MESSAGE` (0x02) | Yes |
| `announce` | `MSG_POOL_ANNOUNCE` (0x03) | Yes |
| `alert` | `MSG_EMERGENCY` (0x10) | Yes |
| `status` | `MSG_NODE_STATUS` (0x01) | No |

**Response (success)**

```json
{
  "status": "queued",
  "message_hash": "abc123...",
  "queue_position": 1,
  "estimated_share_time": 30
}
```

**Response (error)**

```json
{
  "status": "error",
  "error": "no signing key configured"
}
```

**Error Cases**

| Error | HTTP Status | Description |
|-------|-------------|-------------|
| `no signing key configured` | 400 | Node started without `--signing-key` |
| `text too long` | 400 | Payload exceeds 220 bytes |
| `invalid type` | 400 | Unknown message type string |
| `queue full` | 429 | Too many pending messages (max 3) |

---

### POST /msg/ban

Add a sender to the local ban list. Bans are node-local — they do not
propagate to other nodes.

**Request Body**

```json
{
  "signing_id": "a1b2c3d4e5f6..."
}
```

Or:

```json
{
  "address": "YOUR_LTC_ADDRESS"
}
```

Or:

```json
{
  "word": "spam"
}
```

**Fields** (exactly one required)

| Field | Type | Description |
|-------|------|-------------|
| `signing_id` | string | Ban a specific signing key (hex) |
| `address` | string | Ban all keys from a payout address |
| `word` | string | Ban messages containing this keyword |

**Response**

```json
{
  "status": "banned",
  "ban_type": "signing_id",
  "value": "a1b2c3d4e5f6..."
}
```

---

### DELETE /msg/ban

Remove a ban from the local ban list.

**Request Body**: Same format as POST `/msg/ban`.

**Response**

```json
{
  "status": "unbanned",
  "ban_type": "signing_id",
  "value": "a1b2c3d4e5f6..."
}
```

---

### GET /msg/bans

List all active bans.

**Response**

```json
{
  "bans": {
    "signing_ids": ["a1b2c3d4e5f6..."],
    "addresses": ["LtcAd..."],
    "words": ["spam"]
  },
  "total_bans": 3
}
```

---

## Message Flags

Flags are a bitmask in the `flags` field of each message:

| Bit | Value | Constant | Description |
|-----|-------|----------|-------------|
| 0 | `0x01` | `FLAG_HAS_SIGNATURE` | Message carries ECDSA signature |
| 1 | `0x02` | `FLAG_BROADCAST` | Relay to peers |
| 2 | `0x04` | `FLAG_PERSISTENT` | Store in message history |
| 3 | `0x08` | `FLAG_PROTOCOL_AUTHORITY` | Signed by donation authority key |

Common flag combinations:

| Flags | Meaning |
|-------|---------|
| `0x07` | Signed + Broadcast + Persistent (typical chat message) |
| `0x0F` | Authority-signed + Broadcast + Persistent (transition signal) |
| `0x02` | Unsigned + Broadcast (anonymous status report) |

---

## Authentication Model

### PoW Authentication

Every message is embedded in a valid P2Pool share. The share must satisfy
the share difficulty target — there is no free messaging. This makes
message spam economically expensive (costs real electricity and hashrate).

### Cryptographic Authentication

Messages can optionally carry ECDSA signatures from derived signing keys:

1. Miner derives a signing key offline from their payout address private key
2. The derived signing key WIF is provided to the node via `--signing-key`
3. Messages are signed with the derived key (ECDSA secp256k1)
4. The signing key announcement is included in shares for verification
5. Other nodes verify signatures against the announced public key

### Authority Authentication

Protocol-level messages (transition signals) require signing by one of the
`COMBINED_DONATION_SCRIPT` authority keys. These are hardcoded public keys
belonging to authorized maintainers:

- `forrestv` (original p2pool author): `03ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1`
- `frstrtr` (current maintainer): `02fe6578f8021a7d466787827b3f26437aef88279ef380af326f87ec362633293a`

Authority-signed messages have `FLAG_PROTOCOL_AUTHORITY` (0x08) set and
are encrypted with the authority key before embedding.

Authority messages are created **offline** using the standalone Python 3
tool `create_transition_message.py` (see below). The resulting hex string
is distributed to node operators who paste it into `--transition-message`.
No private key is needed on operator nodes.

---

## Rate Limits

| Parameter | Value | Scope |
|-----------|-------|-------|
| Max payload per message | 220 bytes | Per message |
| Max messages per share | 3 | Per share |
| Max total message bytes per share | 512 bytes | Per share |
| Max MWU per share | 1024 MWU | Per share |
| Free MWU allowance | 64 MWU | Per share |
| Max MWU per hour | 4096 MWU | Per signing_id |
| Message store capacity | 1000 messages | Per node |
| Message expiry | 24 hours (86400s) | Per node |
| Pending message queue | 3 messages | Per node |

---

## Encryption

### Wire Obfuscation (All Messages)

All `message_data` in shares is XOR-obfuscated with a key derived from
the network identifier. This prevents passive TCP traffic analysis but
is not cryptographic security — any P2Pool node can deobfuscate.

### Authority Encryption (Transition Signals)

Authority-signed messages use an additional encryption envelope:

```
Encrypted Envelope (49 + N bytes):
  version:    1 byte  (0x01)
  nonce:      16 bytes (random)
  mac:        32 bytes (HMAC-SHA256 over ciphertext)
  ciphertext: N bytes  (XOR stream cipher)
```

The authority pubkey is NOT in the envelope. On decryption, the node tries
each pubkey in `DONATION_AUTHORITY_PUBKEYS` — the one whose derived MAC
matches is identified as the encrypting authority. The encryption key is
derived via `HMAC-SHA256(authority_pubkey, nonce)`.

### Private Messaging (Future — Phase 7)

ECDH key agreement between sender and recipient signing keys will enable
end-to-end encrypted private messages. See SHARE_MESSAGING_DESIGN.md for
the ECDH specification.

---

## Error Handling

All error responses follow this format:

```json
{
  "status": "error",
  "error": "<human-readable error description>"
}
```

The API does not use HTTP error status codes for messaging errors — all
responses return HTTP 200 with the error in the JSON body. This simplifies
client-side handling since the messaging system is advisory (not critical).

---

## Client Examples

### curl — Send a Chat Message

```bash
curl -X POST http://localhost:9327/msg/send \
  -H 'Content-Type: application/json' \
  -d '{"type":"chat","text":"Hello from my node!"}'
```

### curl — Get Recent Messages

```bash
curl http://localhost:9327/msg/recent?limit=10
```

### curl — Ban a Spammer

```bash
curl -X POST http://localhost:9327/msg/ban \
  -H 'Content-Type: application/json' \
  -d '{"signing_id":"a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"}'
```

### JavaScript — Poll Messages (Dashboard)

```javascript
function pollMessages() {
    fetch('/msg/recent?limit=20')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            data.messages.forEach(function(msg) {
                console.log('[' + msg.type_name + '] ' +
                    msg.sender_address + ': ' + msg.payload);
            });
        });
}

// Poll every 30 seconds
setInterval(pollMessages, 30000);

// Check alerts more frequently
setInterval(function() {
    fetch('/msg/alerts')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.alerts && data.alerts.length > 0) {
                alert('EMERGENCY: ' + data.alerts[0].payload);
            }
        });
}, 10000);
```

### Python — Send Message via API

```python
import requests, json

def send_chat(node_url, text):
    resp = requests.post(node_url + '/msg/send',
        json={'type': 'chat', 'text': text})
    result = resp.json()
    if result.get('status') == 'queued':
        print('Message queued at position %d' % result['queue_position'])
    else:
        print('Error: %s' % result.get('error', 'unknown'))

send_chat('http://localhost:9327', 'Hello miners!')
```

---

## Versioning

The messaging API version is tied to the protocol envelope version (currently 1).
Future versions will maintain backward compatibility:

- New fields may be added to response objects
- New message types may be added (unknown types are displayed as raw hex)
- New query parameters may be added with sensible defaults
- Existing fields and endpoints will not be removed or renamed

---

---

## Authority Message Creation Tool

The standalone Python 3 script `create_transition_message.py` is used by
authority key holders to create signed and encrypted transition messages
offline. The tool produces a hex string that node operators paste into
`--transition-message` — **no private key is needed on operator nodes**.

### Requirements

- **Python 3.6+** (standalone — does NOT require PyPy 2.7)
- One of: `ecdsa` or `coincurve` packages
- Optional: `mnemonic` package (for BIP39 seed phrase support)

```bash
pip3 install ecdsa            # or: pip3 install coincurve
pip3 install mnemonic          # optional — for seed phrase key loading
```

### Workflow

```
Authority key holder                    Node operators
─────────────────────                   ──────────────
1. create_transition_message.py         3. Receive hex string
   create --privkey <key> ...              (GitHub release, website, etc.)
        │
        ▼                               4. --transition-message <hex>
2. Gets HEX STRING output                  No private key needed!
   (signed + encrypted)
```

### Commands

#### `create` — Create a Transition Signal

```bash
python3 create_transition_message.py create \
  --privkey <64-hex-chars> \
  --from 36 --to 37 \
  --msg "Upgrade to V37" \
  --urgency recommended \
  --url "https://github.com/frstrtr/p2pool-merged-v36/releases"
```

**Key input methods** (mutually exclusive):

| Flag | Description |
|------|-------------|
| `--privkey <hex>` | Hex-encoded 32-byte private key (64 chars) |
| `--privkey-file <path>` | Path to file containing hex private key |
| `--seed-phrase "word1 word2 ..."` | BIP39 mnemonic (12 or 24 words) |
| `--keystore <path>` | Encrypted JSON keystore file |

**Message parameters**:

| Flag | Required | Description |
|------|----------|-------------|
| `--from <ver>` | Yes | Current share version (e.g., `36`) |
| `--to <ver>` | Yes | Target share version (e.g., `37`) |
| `--msg <text>` | Yes | Human-readable message (max 220 bytes) |
| `--urgency <level>` | No | `info`, `recommended` (default), or `required` |
| `--url <url>` | No | URL for upgrade release page |
| `--threshold <pct>` | No | Activation threshold percentage |
| `--output <base>` | No | Output file base name |
| `--derivation-path <path>` | No | BIP32 path (default: `m/44'/2'/0'/0/0`) |

**Output**: Hex string printed to stdout + saved to `<base>.hex` file.

```
========================================================================
HEX STRING (give this to node operators):
========================================================================
01a2b3c4d5e6f7890123456789abcdef...
========================================================================

NODE OPERATORS: paste the hex string above into your p2pool startup:
  python run_p2pool.py [options] \
    --transition-message 01a2b3c4d5e6f7...
```

#### `verify` — Verify an Existing Message

```bash
# Verify a hex string
python3 create_transition_message.py verify --file 01a2b3c4d5e6f7...

# Verify a hex file
python3 create_transition_message.py verify --file transition_message.hex
```

Outputs:
- Envelope version and size
- Authority key identification (forrestv or maintainer)
- Message content (type, flags, timestamp, payload)
- Signature verification result
- Transition details (from/to version, urgency, URL)

#### `create-keystore` — Create Encrypted Key Storage

```bash
python3 create_transition_message.py create-keystore \
  --privkey <64-hex> \
  --keystore-out keystore.json
```

Creates a PBKDF2-encrypted JSON keystore file for safer key storage.
Password is prompted interactively (with confirmation).

Keystore format:
```json
{
  "version": 1,
  "description": "P2Pool V36 transition message signing key",
  "pubkey": "02fe6578...",
  "crypto": {
    "cipher": "stream-sha256",
    "ciphertext": "<hex>",
    "kdf": "pbkdf2",
    "kdfparams": {
      "iterations": 100000,
      "salt": "<hex>",
      "hash": "sha256"
    }
  }
}
```

### Node Operator Usage

Operators do NOT need the authority private key. They receive the hex string
from the authority and embed it:

```bash
# Inline hex string
python run_p2pool.py --net litecoin \
  --transition-message 01a2b3c4d5e6f7890123456789abcdef...

# Or point to hex file
python run_p2pool.py --net litecoin \
  --transition-message /path/to/transition_message_v36_v37.hex
```

The node validates the hex string at startup:
1. Decrypts against known authority pubkeys
2. Verifies HMAC-SHA256 MAC
3. Verifies ECDSA signature on each inner message
4. Embeds the validated `message_data` in every share the node mines

If validation fails, the node prints an error and starts without the message.

### Security Properties

- The authority private key never leaves the key holder's machine
- Messages are encrypted — ISPs/observers cannot read the content
- Messages are signed — nodes reject forged transition signals
- The encryption envelope uses a random 16-byte nonce (unique per message)
- Self-verification is performed before outputting the hex string
- The private key is zeroed from memory after use

---

## See Also

- [SHARE_MESSAGING_DESIGN.md](SHARE_MESSAGING_DESIGN.md) — Architecture and design rationale
- [SHARE_MESSAGING_PROTOCOL.md](SHARE_MESSAGING_PROTOCOL.md) — Wire format specification
- [SHARE_MESSAGING_INTEGRATION.md](SHARE_MESSAGING_INTEGRATION.md) — Code integration plan
- [SHARE_MESSAGING_QUICKSTART.md](SHARE_MESSAGING_QUICKSTART.md) — Operator/miner quick start guide
- [SHARE_MESSAGING_SECURITY.md](SHARE_MESSAGING_SECURITY.md) — Security model and threat analysis
- [create_transition_message.py](../scripts/create_transition_message.py) — Standalone Python 3 authority message tool
