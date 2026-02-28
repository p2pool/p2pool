# P2Pool Share-Based Messaging System — Design Document

## Overview

A decentralized messaging system embedded in P2Pool share data, using share
Proof-of-Work as anti-spam and derived signing keys for authentication.

Messages are part of the share hash (PoW-protected) but NOT part of the
coinbase transaction — they never pollute the parent blockchain.

## Design Goals

1. **PoW-gated**: Only miners who produce valid shares can send messages
2. **Blockchain-clean**: Messages never appear in Litecoin/Dogecoin blocks
3. **Authenticated**: Messages signed with derived keys, verifiable by all nodes
4. **Key-safe**: Master private key (payout address) is NEVER exposed to the node
5. **Rotatable**: Signing keys can be rotated, revoking all previous signatures
6. **Encrypted**: Messages are not plaintext on the wire — even public BBS messages
7. **Private messaging**: P2P messages use ECDH encryption, only sender/recipient can read
8. **Bannable**: Nodes can locally ban senders by signing_id or miner address
9. **Backward-compatible**: Embeds in V36 without breaking existing share format
10. **Zero infrastructure**: No external servers, databases, or PKI — trust is anchored to share PoW

## Why NOT Coinbase OP_RETURN

| Approach | PoW-protected? | Blockchain-clean? | Propagated? |
|----------|:-:|:-:|:-:|
| Coinbase OP_RETURN | ✅ | ❌ pollutes blockchain if block found | ✅ |
| `share_data['coinbase']` suffix | ✅ | ❌ same problem — in coinbase | ✅ |
| Separate P2P message type | ❌ needs own anti-spam | ✅ | ✅ needs new protocol |
| **ref_type extension (chosen)** | **✅** | **✅** | **✅** via existing P2P |

The chosen approach adds a `message_data` field to V36's `ref_type`. This field:
- Is included in `ref_hash` → part of the share merkle tree → protected by PoW
- Is NOT included in the coinbase/gentx → never written to any blockchain
- Propagates with shares via existing p2pool P2P protocol — no new message types

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     P2Pool Share (V36)                        │
├──────────────────────────────────────────────────────────────┤
│ share_info (existing — in coinbase/gentx/blockchain)         │
│   ├── share_data (previous_hash, coinbase, nonce, address…)  │
│   ├── segwit_data                                            │
│   ├── merged_addresses (NEW in V36)                          │
│   └── far_share_hash, bits, timestamp, absheight, abswork    │
├──────────────────────────────────────────────────────────────┤
│ ref_type (PoW-protected via ref_hash, NOT in blockchain)     │
│   ├── identifier (8 bytes)                                   │
│   ├── share_info (same as above)                             │
│   └── message_data (NEW — VarStrType)  ◄── MESSAGES HERE     │
│         ├── signing_key_announcement (57 bytes, optional)     │
│         └── messages[] (up to 3 per share)                   │
├──────────────────────────────────────────────────────────────┤
│ ref_hash = merkle(hash256(ref_type.pack(...)))               │
│   └── Includes message_data → PoW protects messages          │
├──────────────────────────────────────────────────────────────┤
│ gentx/coinbase (existing — written to blockchain)            │
│   └── Does NOT include message_data → blockchain stays clean │
└──────────────────────────────────────────────────────────────┘
```

## Derived Signing Key Scheme

### The Problem

Miners need to sign messages, but exposing the payout address private key
would be catastrophic — an attacker could steal all mining rewards.

### The Solution: Offline Key Derivation

The miner derives a **one-way signing key** from their master private key
**OFFLINE** (on their own machine, never on the node). The derived signing
key is then provided to the node via config file or CLI flag.

**CRITICAL: The node never sees the master private key.**

The signing key can sign messages but cannot be reversed to obtain the
master key. If the signing key is compromised, the miner rotates to a
new key by incrementing `key_index` and re-running the offline derivation.

### Offline Derivation Tool

```bash
# Run on miner's secure machine — NOT on the p2pool node
$ python derive_signing_key.py <master_WIF> [key_index]

Master address: YOUR_LTC_ADDRESS
Key index: 0
Signing key WIF: YOUR_SIGNING_KEY_WIF
Signing ID: a1b2c3d4e5f6...

Put this in your p2pool config:
  --signing-key YOUR_SIGNING_KEY_WIF
  --signing-key-index 0

To rotate (if compromised):
  python derive_signing_key.py <master_WIF> 1
```

The node receives only the **derived signing key** (safe to expose) and the
**key_index** (public). The master WIF stays on the miner's air-gapped machine.

### Derivation

```
Master Private Key (payout address — NEVER EXPOSED)
    │
    └─── HMAC-SHA256(master_pk, "p2pool-msg-v1" || key_index_le32)
              │
              ├── signing_privkey (32 bytes)
              │     └── Used to ECDSA-sign messages
              │
              ├── signing_pubkey = secp256k1(signing_privkey) (33 bytes compressed)
              │     └── Announced in shares for verification
              │
              └── signing_id = HASH160(signing_pubkey) (20 bytes)
                    └── Short identifier for message attribution
```

### Key Rotation

```
key_index=0 ──► signing_key_A ──► signing_id_A  (announced in share)
                  │
                  ├── Signs messages M1, M2, M3
                  │
                  └── COMPROMISED! Attacker has signing_key_A
                        │
key_index=1 ──► signing_key_B ──► signing_id_B  (announced in NEW share)
                  │
                  ├── SigningKeyRegistry sees key_index=1 > 0
                  ├── REVOKES signing_id_A ──► M1, M2, M3 now UNVERIFIABLE
                  └── Signs new messages with signing_key_B
```

**Properties:**
- Master key stays secret — signing key is one-way derived
- Compromise of signing key only affects message auth, not mining rewards
- Key rotation is immediate — just mine one share with new key_index
- Old messages become unverifiable (revoked), preventing impersonation
- No PKI, no key exchange — trust anchored entirely to share PoW

### Security Analysis

| Attack | Mitigation |
|--------|-----------|
| Steal master private key | Signing key is derived via HMAC — can't reverse |
| Steal signing key | Rotate key_index — old key revoked, new key in next share |
| Forge messages from another miner | Need their signing_privkey — can't derive without master |
| Spam messages | Must mine valid shares (PoW cost) |
| Announce fake signing key | Must mine valid share — PoW prevents sybil |
| Replay old messages | Deduplicated by message_hash in ShareMessageStore |
| Impersonate after key rotation | Old signing_id is revoked — verification fails |

## Encryption Layers

Messages are NOT plaintext on the wire. Four layers of protection:

### Layer 1: Wire Obfuscation (all messages)

All message_data in shares is obfuscated with a symmetric key derived from
the p2pool network identifier. This prevents passive TCP traffic analysis
by anyone not running a p2pool node.

```
obfuscation_key = SHA256("p2pool-msg-obfuscate" || net.IDENTIFIER)
ciphertext = XOR(plaintext, keystream(obfuscation_key, nonce=share_hash))
```

This is NOT security — any p2pool node can deobfuscate. It's protection
against casual wire sniffing.

### Layer 2: Authority Encryption (transition signals) — IMPLEMENTED

Transition signal messages are encrypted using the authority pubkey as a
"group key".  Every p2pool node knows the authority pubkeys (hardcoded in
`DONATION_AUTHORITY_PUBKEYS`), so they can derive the decryption key.
Non-p2pool observers cannot.

```
Encrypt (authority, offline — create_transition_message.py):
  nonce      = random 16 bytes
  enc_key    = HMAC-SHA256(key=authority_pubkey, msg=nonce)
  stream     = SHA256(enc_key||0) || SHA256(enc_key||1) || ...
  ciphertext = XOR(inner_data, stream)
  mac        = HMAC-SHA256(enc_key, ciphertext)
  envelope   = [0x01] [nonce:16] [mac:32] [ciphertext:N]

Decrypt (any p2pool node):
  For each pubkey in DONATION_AUTHORITY_PUBKEYS:
    enc_key    = HMAC-SHA256(pubkey, nonce)
    mac_check  = HMAC-SHA256(enc_key, ciphertext)
    if mac_check == mac → decrypt + verify ECDSA signature inside
```

This layer provides:
- Confidentiality from passive observers (ISPs, network monitors)
- Integrity via HMAC-SHA256 MAC (tampered ciphertext fails check)
- Key attribution (MAC match identifies WHICH authority encrypted it)
- Double authentication (encryption key match + ECDSA signature inside)

### Layer 3: Authentication (signed messages)

ECDSA signatures via DerivedSigningKey, as described above. Proves sender
identity and message integrity.

### Layer 4: Private Encryption (P2P messages)

For private miner-to-miner messages, ECDH key agreement provides
end-to-end encryption:

```
shared_secret = ECDH(sender_signing_privkey, recipient_signing_pubkey)
encryption_key = HMAC-SHA256(shared_secret, "p2pool-msg-encrypt")
ciphertext = AES-256-GCM(encryption_key, nonce=timestamp||counter, plaintext)
```

Only sender and recipient can decrypt. All other nodes relay the opaque
ciphertext without being able to read it. The `to` field (recipient
signing_id) is visible so nodes can check if a message is addressed to them.

### Layer 5: (Future) ZK Anonymous Reputation — Phase 3+

Zero-Knowledge proofs could enable anonymous messaging with reputation:
- Prove "I control addresses with combined hashrate weight > X%" without
  revealing which addresses
- Enables anonymous governance proposals and emergency alerts from major miners
- Requires zkSNARK/Bulletproof library — too complex for Phase 1

#### ZK Analysis

| What to prove | Without ZK | With ZK | Worth it? |
|---|---|---|---|
| "I mined this share" | Share PoW proves it | Same | ❌ No benefit |
| "I own this address" | Derived signing key | ZK proof of key knowledge | ⚠️ Marginal |
| "I have >X% hashrate" | Check share count | ZK proof without revealing address | ✅ Compelling |
| "I'm a node operator" | No way currently | ZK proof of uptime | ⚠️ Hard to verify |

**Decision**: ZK is deferred to Phase 3+. The one compelling use case
(anonymous weighted voting) doesn't justify the implementation complexity
in PyPy 2.7 for initial release.

## Banning System

Each node maintains a **local** ban list. Bans are not propagated — each
node operator decides independently what content to filter.

### Ban Types

```
Ban by signing_id:     Blocks a specific signing key
Ban by miner_address:  Blocks all keys from a payout address
Ban by content:        Regex/keyword filter on message payload
```

### Behavior

- Banned messages are dropped silently on the receiving node
- Banned messages are still relayed in shares (the banning node can't
  remove them from shares — they're PoW-protected)
- Other nodes see the messages normally unless they also ban the sender
- Ban list persisted to `data/litecoin/banned_senders.json`

### Configuration

```
--ban-sender <signing_id_hex>     Ban a signing key
--ban-address <LTC_address>       Ban all keys from an address
--ban-word <keyword>              Filter messages containing keyword
```

Or via API:
```
POST /msg/ban {"signing_id": "a1b2c3..."}
POST /msg/ban {"address": "LtcAd..."}
DELETE /msg/ban {"signing_id": "a1b2c3..."}
```

## UI/UX Design

### Key Setup (One-Time, Offline)

```
Miner's secure machine:
  $ python derive_signing_key.py <master_WIF> 0
  → signing_key_WIF (safe to give to node)

P2Pool node config:
  --signing-key <signing_key_WIF>
  --signing-key-index 0
```

The node NEVER sees the master private key. The derived signing key
is safe to store in config files and expose to the node process.

### Sending Messages

```
# Via web API
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"chat","text":"hello miners!"}'

# Private message to a specific miner
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"chat","text":"secret msg","to":"<signing_id_hex>"}'

# Pool announcement
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"announce","text":"upgrading in 1hr"}'

# Emergency alert
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"alert","text":"critical bug, upgrade now"}'
```

Messages are queued and embedded in the next mined share.

### Viewing Messages — BBS (Bulletin Board System)

The node serves a BBS-style web page at `http://node:9327/static/bbs.html`:

```
┌─────────────────────────────────────────────────────────┐
│  P2Pool BBS — Share-Authenticated Messaging             │
├─────────────────────────────────────────────────────────┤
│  [Chat] [Announcements] [Alerts] [Node Status] [Keys]  │
├─────────────────────────────────────────────────────────┤
│  #42  LtcAd...azc  ✅verified  2m ago                   │
│  > hello from miner A!                                  │
│                                                         │
│  #41  LtcBd...xyz  ✅verified  5m ago                   │
│  > merged mining DOGE working great                     │
│                                                         │
│  #40  LiF7n...3s3  ⚠️unverified  8m ago                 │
│  > anyone seeing orphans?                               │
│                                                         │
│  #39  [SYSTEM]  NODE_STATUS  10m ago                    │
│  > v13.4 | up 2d | 1.5MH/s | 3 peers | DOGE merged    │
├─────────────────────────────────────────────────────────┤
│  Send: [____________________________] [Chat] [Announce] │
└─────────────────────────────────────────────────────────┘
```

### API Endpoints

```
GET  /msg/recent           Recent messages (all types)
GET  /msg/chat             Miner chat messages only
GET  /msg/announcements    Pool announcements only
GET  /msg/alerts           Emergency alerts only
GET  /msg/status           Node status messages
GET  /msg/keys             Signing key registry
GET  /msg/identity         This node's signing identity
GET  /msg/stats            Messaging system statistics
POST /msg/send             Queue a message for next share
POST /msg/ban              Ban a sender
POST /msg/rotate_key       Rotate signing key (increment key_index)
DELETE /msg/ban            Unban a sender
```

## Message Types

| Type | ID | Signed? | Persistent? | Purpose |
|------|----|---------|-------------|---------|
| NODE_STATUS | 0x01 | Optional | No | Node health: version, uptime, hashrate, peers |
| MINER_MESSAGE | 0x02 | **Required** | Yes | Miner-to-miner text chat |
| POOL_ANNOUNCE | 0x03 | **Required** | Yes | Node operator announcements |
| VERSION_SIGNAL | 0x04 | Optional | No | Extended version signaling with metadata |
| MERGED_STATUS | 0x05 | Optional | No | Merged mining chain status reports |
| EMERGENCY | 0x10 | **Required** | Yes | Security alerts, critical upgrade notices |
| TRANSITION_SIGNAL | 0x20 | **Required** | Yes | Protocol transition alerts (authority only) |

## Message Flags

```
Bit 0 (0x01): FLAG_HAS_SIGNATURE      — Message carries an ECDSA signature
Bit 1 (0x02): FLAG_BROADCAST          — Relay to peers (vs. local-only)
Bit 2 (0x04): FLAG_PERSISTENT         — Store in message history (vs. ephemeral)
Bit 3 (0x08): FLAG_PROTOCOL_AUTHORITY — Signed by a COMBINED_DONATION_SCRIPT key
Bits 4-7:     Reserved for future use
```

`FLAG_PROTOCOL_AUTHORITY` is **earned, not set** — it is stripped during
unpacking and only restored when `verify_authority_direct()` confirms the
signature matches a `DONATION_AUTHORITY_PUBKEYS` key.

## Limits

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max payload per message | 220 bytes | Fits a tweet-length message + JSON metadata |
| Max messages per share | 3 | Keeps share overhead small |
| Max total message bytes per share | 512 bytes | ~0.5 KB overhead on ~2 KB share |
| Signing key announcement | 57 bytes | signing_id(20) + key_index(4) + pubkey(33) |
| Message expiry | 24 hours | Prevents unbounded memory growth |
| Message store capacity | 1000 messages | ~24 hours at typical share rates |

## Use Cases

### 1. Miner Chat
Miners communicate in real-time via signed text messages. Only verified shares
can carry messages — this is the most expensive chat system in the world
(you literally need to perform PoW to send a message).

### 2. Pool Status Dashboard
Node operators broadcast health status: hashrate, peer count, merged chain
availability. Other nodes display this on their dashboards.

### 3. Emergency Alerts
Critical security notices propagate through the share chain. Since they're
signed and PoW-protected, they can't be spoofed.

### 4. Upgrade Coordination
Extended version signaling carries feature flags and capability lists,
enabling richer negotiation than the existing `desired_version` integer.

### 5. Merged Mining Discovery
Nodes announce which merged chains they support and their block heights,
enabling automatic peer discovery for new merged mining chains.

### 6. Protocol Transition Coordination (IMPLEMENTED)

Authority key holders (forrestv, frstrtr) broadcast signed+encrypted
transition signals via shares. These are created offline using
`create_transition_message.py` (Python 3) and distributed as hex strings
to node operators, who paste them into `--transition-message`.

```
Authority offline:    create_transition_message.py create --privkey ... → hex string
Operator startup:     --transition-message <hex>
Node validates:       decrypt + verify ECDSA → embed in every mined share
Other nodes:          get_warnings() scans shares → display upgrade notice
```

Urgency levels control the warning display:
- `info` → informational notice
- `recommended` → visible upgrade recommendation
- `required` → prominent URGENT UPGRADE REQUIRED banner

Transition signals are advisory — they never trigger automatic upgrades.
Node operators must independently verify through out-of-band channels.

No private key is needed on operator nodes — only the pre-built hex string.

## Message Weight Units (MWU) — Share-Cost Economics

### The Problem

Messages embedded in shares increase share size and consume P2P bandwidth.
Without economic constraints, a high-hashrate miner could flood the network
with maximum-size messages in every share, degrading propagation for everyone.

PoW alone is necessary but not sufficient — a miner already mining shares
pays zero marginal cost for stuffing message data into every share they
produce. We need an **additional** economic mechanism that makes messaging
have a measurable cost proportional to the burden it imposes on the network.

### Solution: Message Weight Units + Share Sacrifice + Donation Commitment

Inspired by Bitcoin's SegWit Weight Units, the MWU system creates a
well-defined cost model for messaging:

1. **Message Weight Units (MWU)** — each byte of message data has a weight
2. **Share Sacrifice** — to send messages, the miner must mine shares that
   pay out to the **node operator's address** and the **donation script**,
   not to the miner's own address. The miner literally donates their
   hashrate to others as payment for the messaging privilege.
3. **Donation Commitment** — the sacrificed shares' payouts go to node
   operators and dev fund, creating a direct economic incentive for
   operators to accept and relay message-carrying shares

### Weight Calculation

Every message has a weight in MWU (Message Weight Units):

```
Base Components:
  header_weight    = 8 MWU           (type + flags + timestamp + payload_len)
  signature_weight = sig_len * 2 MWU (signatures are expensive to verify)
  payload_weight   = payload_len * 1 MWU (raw payload bytes)
  announcement_weight = 57 * 3 MWU   (signing key announcements are heavy — 171 MWU)

Total MWU per message:
  msg_mwu = header_weight + payload_weight + signature_weight

Total MWU per share:
  share_mwu = sum(msg_mwu for each message) + announcement_weight (if present)

Limits:
  MAX_MWU_PER_SHARE    = 1024 MWU    (hard cap per share)
  FREE_MWU_ALLOWANCE   = 64 MWU      (small status messages are free)
  MWU_PER_SACRIFICE    = 256 MWU     (each sacrificed share buys this much capacity)
```

### Share Sacrifice Mechanism

When a miner wants to send a message that exceeds the free allowance, they
must **mine sacrifice shares** — valid PoW shares where the **payout address
is set to the node operator's address or the donation script**, not the
miner's own address. The miner is literally burning their own hashrate and
electricity to mine for someone else's profit.

```
┌────────────────────────────────────────────────────────────────────┐
│                    Share Sacrifice Model                           │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Normal share (miner's own):                                       │
│    payout address: miner's LTC address                             │
│    message budget: FREE_MWU_ALLOWANCE (64 MWU ≈ 64 bytes)         │
│                    enough for NODE_STATUS, VERSION_SIGNAL           │
│                                                                    │
│  Sacrifice share (mined for node operator):                         │
│    payout address: NODE OPERATOR'S address (not miner's!)           │
│    purpose:        pays the node operator for messaging service     │
│    message credit: earns MWU_PER_SACRIFICE (256 MWU) of budget     │
│    the miner gets: NOTHING from this share — pure cost              │
│                                                                    │
│  Sacrifice share (mined for donation script):                       │
│    payout address: p2pool donation/dev fund address                  │
│    purpose:        funds p2pool development                          │
│    message credit: earns MWU_PER_SACRIFICE (256 MWU) of budget     │
│    the miner gets: NOTHING from this share — pure cost              │
│                                                                    │
│  How it works:                                                      │
│    1. Miner wants to send a 372 MWU message (chat + signature)     │
│    2. Free budget: 64 MWU → need 308 MWU more                      │
│    3. Required: ceil(308/256) = 2 sacrifice shares                  │
│    4. Miner mines 1 share → node operator's address                 │
│    5. Miner mines 1 share → donation script address                 │
│    6. Miner now has 64 + 512 = 576 MWU budget                      │
│    7. Miner embeds the message in their NEXT own share              │
│    8. Node operator earned a full share payout (~1.56 tLTC)         │
│    9. Dev fund earned a full share payout (~1.56 tLTC)              │
│   10. Miner lost 2 shares worth of mining (~3.12 tLTC) to send msg │
│                                                                    │
│  The sacrifice is REAL — the miner mined those shares with their   │
│  own hashrate and electricity, but the payout goes to someone else.│
│  This is the most honest form of payment: verifiable PoW work      │
│  directed at the beneficiary's address.                             │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**Sacrifice share verification:**
Each sacrifice share is a normal, valid p2pool share. Nodes verify:
1. The share is PoW-valid (normal share validation)
2. The payout address matches the node operator or donation script
3. The share's `ref_data` contains a **sacrifice tag**: `[SACRIFICE_FOR:20]`
   containing the `signing_id` of the miner who is paying for message credit
4. The sacrifice share is recorded in the miner's MWU credit ledger

This means the sacrifice is attributable — the miner's signing_id is embedded
in the sacrifice share, proving "I mined this share to pay for messaging."

**Sacrifice ratio — follows `--give-author` split:**
The split between node operator and donation script is NOT hardcoded — it
follows the same ratio configured by the node operator's `--give-author`
parameter. This aligns messaging economics with the existing donation model:

```
Node operator runs:   --give-author 1.0  (default: 1% donation)
Sacrifice split:      99% node operator, 1% donation script

Node operator runs:   --give-author 5.0  (generous: 5% donation)
Sacrifice split:      95% node operator, 5% donation script

Node operator runs:   --give-author 50.0 (altruistic: 50% donation)
Sacrifice split:      50% node operator, 50% donation script

Required sacrifice shares = ceil((msg_mwu - FREE_MWU_ALLOWANCE) / MWU_PER_SACRIFICE)

For each sacrifice share:
  donation_fraction = give_author_percentage / 100
  The share's payout is split:
    (1 - donation_fraction) → node operator's payout address
    donation_fraction       → COMBINED_DONATION_SCRIPT (or DONATION_SCRIPT pre-V36)
```

The node operator controls their own reward ratio — they can set `--give-author`
higher to donate more to the dev fund, or keep it at the minimum (0%) to
capture all sacrifice share payouts themselves.

### Donation Script Marker — Every Share

**Every share** (not just sacrifice shares) already includes the donation
script as part of the coinbase/gentx payout outputs. This existing mechanism
ensures the donation address is present as a persistent marker across the
entire sharechain:

```
Existing P2Pool share structure (already implemented):
┌──────────────────────────────────────────────────────────────┐
│ Coinbase Transaction (gentx) — in every share               │
├──────────────────────────────────────────────────────────────┤
│ Output 0: Miner's payout address     (1 - donation%)        │
│ Output 1: ... other PPLNS payouts ...                        │
│ Output N: COMBINED_DONATION_SCRIPT   (donation %)            │
│           (V36+: 1-of-2 P2MS — either author can spend)    │
│           └── Serves as permanent sharechain marker          │
│           └── Proves this share belongs to the p2pool network│
│           └── For messaging: sacrifice shares increase this  │
└──────────────────────────────────────────────────────────────┘

share_data['donation'] field:
  - uint16 (0-65535) representing donation fraction of share value
  - Set from --give-author parameter (default: 0.0%)  
  - Normal shares: donation% of share value → DONATION_SCRIPT
  - Sacrifice shares: the payout ADDRESS is set to node operator,
    but donation% STILL goes to DONATION_SCRIPT — both parties benefit
```

This means the donation script appears in **every single share's coinbase**
as a recognizable marker, exactly like how mined block rewards always include
the donation output. For the messaging system, this marker serves as:

1. **Network identity** — the donation script proves the share was generated
   by authentic p2pool software (not a rogue fork stripping donations)
2. **Messaging eligibility** — nodes can verify that a miner consistently
   includes the donation marker before granting message credits
3. **Sacrifice attribution** — sacrifice shares directed to the donation
   script are identifiable by matching against the known donation addresses
   (`DONATION_SCRIPT`, `SECONDARY_DONATION_SCRIPT`, `COMBINED_DONATION_SCRIPT`)

### Messaging Eligibility — Donation Marker Requirement

To prevent abuse, a miner must have the donation script marker present in
their recent shares to be eligible for messaging. Nodes enforce:

```
Eligibility check (local policy, per node):
  1. Look at miner's last N shares (N = MIN_SHARES_FOR_MESSAGING, default 10)
  2. Count how many include COMBINED_DONATION_SCRIPT in their coinbase
  3. If count < REQUIRED_DONATION_SHARES (default: all of them), 
     → miner's messages are IGNORED (not invalid, just dropped locally)

This ensures:
  - Miners who strip the donation script can't use messaging
  - Nodes protect the donation ecosystem by requiring participation  
  - The check is local policy — each node decides independently
  - No consensus-level enforcement (shares remain valid either way)
```

### Message Splitting Across Shares

Large messages (or message bursts) that exceed a single share's MWU budget
are automatically split across multiple consecutive shares:

```
Original message: "Attention all miners: critical vulnerability found in
  v35.02, please upgrade to v35.03 immediately. Details at ..." (450 bytes)

  Total MWU = 8 + 450 + 144 = 602 MWU (exceeds MAX_MWU_PER_SHARE)

  Split into fragments:
  ┌─────────────────────────────────────────────────────────────┐
  │  Share N:   [FRAG 0/2] [msg_id:4] [frag:1] [total:1]      │
  │             payload: bytes 0-199 (200 bytes)                │
  │             mwu: 8 + 6 + 200 + 144 = 358 MWU               │
  │             sacrifice: 2 units → -20% payout                │
  ├─────────────────────────────────────────────────────────────┤
  │  Share N+1: [FRAG 1/2] [msg_id:4] [frag:1] [total:1]      │
  │             payload: bytes 200-399 (200 bytes)              │
  │             mwu: 8 + 6 + 200 + 0 = 214 MWU (sig on last)   │
  │             sacrifice: 1 unit → -10% payout                 │
  ├─────────────────────────────────────────────────────────────┤
  │  Share N+2: [FRAG 2/2] [msg_id:4] [frag:1] [total:1]      │
  │             payload: bytes 400-449 (50 bytes) + signature   │
  │             mwu: 8 + 6 + 50 + 144 = 208 MWU                │
  │             sacrifice: 1 unit → -10% payout                 │
  └─────────────────────────────────────────────────────────────┘
  
  Total cost: 4 sacrifice units → miner loses 40% payout across 3 shares
  Reassembly: receivers collect fragments by msg_id, verify signature on final fragment
  Timeout: incomplete fragments expire after 5 minutes (prevent memory DoS)
```

### Fragment Wire Format

```
Fragment header (6 bytes, prepended to payload):
  [msg_id:4]         Random uint32 identifying this message across fragments
  [frag_index:1]     Fragment index (0, 1, 2, ...)
  [frag_total:1]     Total fragment count (receivers know when complete)

Rules:
  - msg_id is random per message, consistent across all fragments
  - Signature is carried ONLY in the last fragment (frag_index == frag_total - 1)
  - Intermediate fragments have FLAG_HAS_SIGNATURE = 0
  - Receiver buffers fragments until all arrive, then verifies signature over
    the reassembled payload
  - If any fragment is missing after FRAGMENT_TIMEOUT (5 min), discard all
  - Max fragments per message: MAX_MESSAGE_FRAGMENTS = 8
  - Max reassembled message size: 8 * 200 = 1600 bytes
```

### Donation Script — Node Operator Incentive

The sacrifice shares ARE the payment. No complex PPLNS weight adjustment
needed — the miner literally mines shares to someone else's address:

```
Sacrifice Share Flow:
  ┌──────────┐     sacrifice shares       ┌──────────┐
  │  Miner   │ ──── (payout_addr = ────►  │  Node    │
  │ (sender) │      node_operator)        │ Operator │
  └──────────┘                            └──────────┘
       │              sacrifice shares       ┌──────────┐
       └──────────── (payout_addr = ────►    │ Dev Fund │
                      donation_script)       └──────────┘
       │
       │  After mining sacrifice shares:
       │  miner embeds message in own share
       ▼
  ┌──────────────────────────────────────────────────────────┐
  │              PPLNS Payout (normal, no tricks)            │
  │                                                          │
  │  Sacrifice share A → node operator gets full payout      │
  │  Sacrifice share B → donation script gets full payout    │
  │  Miner's share     → miner gets full payout (has message)│
  │                                                          │
  │  The sacrifice shares are indistinguishable from normal   │
  │  shares in PPLNS — they just have a different payout_addr │
  │  The miner spent their own hashrate to benefit others.    │
  └──────────────────────────────────────────────────────────┘
```

**Why this is elegant:**
- **No PPLNS modifications needed** — sacrifice shares are normal shares
  with the node operator's payout address. PPLNS doesn't need to know about
  messaging at all — it just pays whoever the share says to pay.
- **Verifiable on-chain** — the sacrifice shares are real PoW work, visible
  in the sharechain, paying real LTC to the node operator and dev fund.
- **Miners** pay a real cost (lost mining income) to send messages — prevents spam
- **Node operators** earn full share payouts from message senders — strong
  incentive to run a messaging-enabled node
- **Dev fund** receives full share payouts — funds continued development
- **No one can cheat** — you can't fake a sacrifice share, you must do the PoW

### Rate Limiting (MWU Budget Over Time)

Beyond per-share limits, each miner has a **rolling MWU budget** tracked
over a time window to prevent sustained flooding:

```
MWU Rate Limiting:
  ROLLING_WINDOW       = 3600 seconds (1 hour)
  MAX_MWU_PER_HOUR     = 4096 MWU per miner (per signing_id)
  COOLDOWN_MULTIPLIER  = 2x (if limit hit, next window budget halved)

Example:
  Miner sends 372 MWU message at T+0     → budget: 4096 - 372 = 3724 remaining
  Miner sends 372 MWU message at T+60    → budget: 3724 - 372 = 3352 remaining
  ...
  Miner sends 372 MWU at T+3000          → budget: 0 remaining
  Miner tries to send at T+3060          → REJECTED (over budget)
  At T+3600, window rolls over           → budget: 4096 again

Enforcement:
  - Each node tracks MWU usage per signing_id in its local SigningKeyRegistry
  - Shares with messages exceeding the sender's MWU budget are NOT invalid
    (can't reject PoW-valid shares) but the messages within are IGNORED
  - Nodes MAY choose different MAX_MWU_PER_HOUR thresholds locally
  - Default is generous enough for normal conversation (≈11 full chat messages/hour)
```

### Network Saturation Protection

The MWU system directly addresses P2P bandwidth concerns:

```
Worst Case Analysis (all limits maxed):
  MAX_MWU_PER_SHARE = 1024 MWU ≈ 1 KB of message data
  Typical share size (without messages) ≈ 2 KB
  Share with max messages ≈ 3 KB (50% overhead)

  At litecoin_testnet share rate of 1 share/30s:
    Baseline bandwidth: 2 KB * 2/min = 4 KB/min
    With max messages:  3 KB * 2/min = 6 KB/min
    Message overhead:   2 KB/min = ~267 bps (negligible on any connection)

  At mainnet share rate of ~1 share/30s with 100 miners:
    Best case (sparse messages): <0.1% bandwidth increase
    Worst case (every share stuffed): ~50% bandwidth increase
    Expected case (10% of shares carry messages): ~5% bandwidth increase

  The sacrifice penalty makes the worst case economically irrational —
  no miner would sacrifice 10-40% of every share's payout just to spam.
```

### Cost Table — What Does Messaging Cost?

| Message Type | Typical Size | MWU | Sacrifice Shares | Miner Cost | Node Op Earns |
|---|---|---|---|---|---|
| NODE_STATUS (unsigned) | 40 bytes | 48 | 0 (free) | Free | — |
| VERSION_SIGNAL (unsigned) | 30 bytes | 38 | 0 (free) | Free | — |
| MERGED_STATUS (unsigned) | 50 bytes | 58 | 0 (free) | Free | — |
| MINER_MESSAGE (signed, short) | 80 + 72 sig | 232 | 1 share | ~1.56 tLTC | ~0.78 tLTC |
| MINER_MESSAGE (signed, full) | 220 + 72 sig | 372 | 2 shares | ~3.12 tLTC | ~1.56 tLTC |
| POOL_ANNOUNCE (signed, full) | 220 + 72 sig | 372 | 2 shares | ~3.12 tLTC | ~1.56 tLTC |
| EMERGENCY (signed, split 3x) | 600 + 72 sig | 780 | 4 shares | ~6.24 tLTC | ~3.12 tLTC |

*Cost = sacrifice shares × share payout value (~1.56 tLTC on testnet).*
*Node operator receives 50% of sacrifice shares, dev fund receives 50%.*
*Miner's own message-carrying share still pays to miner at full value.*

### Implementation Constants

```python
# Message Weight Units
MWU_HEADER = 8                    # fixed cost per message header
MWU_PER_PAYLOAD_BYTE = 1          # 1 MWU per payload byte
MWU_PER_SIGNATURE_BYTE = 2        # signatures are expensive to verify
MWU_ANNOUNCEMENT = 171            # 57 bytes * 3 MWU/byte for key announcement

MAX_MWU_PER_SHARE = 1024          # hard cap per share
FREE_MWU_ALLOWANCE = 64           # small messages are free
MWU_PER_SACRIFICE = 256           # MWU capacity bought per sacrifice share

# Sacrifice shares — miner mines shares for others to pay for messaging
# Split is dynamic and follows node's --give-author setting:
#   SACRIFICE_NODE_FRACTION = 1.0 - (give_author_percentage / 100.0)
#   SACRIFICE_DONATION_FRACTION = give_author_percentage / 100.0
SACRIFICE_TAG_SIZE = 20           # signing_id embedded in sacrifice share ref_data

MAX_MESSAGE_FRAGMENTS = 8         # max fragments per split message
FRAGMENT_TIMEOUT = 300            # 5 minutes to receive all fragments
MAX_REASSEMBLED_SIZE = 1600       # max bytes after reassembly

ROLLING_MWU_WINDOW = 3600         # 1 hour rate limit window
MAX_MWU_PER_HOUR = 4096           # per signing_id
```

### Design Rationale

**Why mine sacrifice shares instead of a separate fee?**
P2Pool has no account model. There is no way to "pay a fee" outside of the
sharechain. But miners CAN mine valid shares with any payout address. By
mining shares that pay to the node operator and dev fund, the miner performs
verifiable PoW work that directly rewards the message relay infrastructure.
No PPLNS modifications needed — sacrifice shares are normal shares that
happen to pay someone else. The cost is real and measurable: the miner
spent hashrate and electricity mining for someone else's profit.

**Why a free allowance?**
Status messages (`NODE_STATUS`, `VERSION_SIGNAL`, `MERGED_STATUS`) are
operationally useful for the network. Making them free (up to 64 MWU)
ensures network health telemetry flows without penalizing anyone.

**Why pay node operators directly instead of burning?**
Pure burn creates no incentive for node operators to relay messages. By
mining shares that pay directly to the node operator's address, we create
a real market: senders pay with PoW, operators earn full share payouts.
The node operator sees sacrifice shares as free income — someone else did
the PoW work, but the payout goes to the operator. This is the strongest
possible incentive to run messaging-enabled nodes, similar to how Bitcoin
transaction fees incentivize miners to include transactions.

**Why fragment across shares instead of one big share?**
A single share with 1600 bytes of message data would be a propagation
outlier, potentially causing orphan issues. Splitting across shares keeps
each share close to normal size and distributes the bandwidth impact over
time (one fragment per share period).

**Why not just reject oversized shares?**
P2Pool shares are PoW-valid — rejecting otherwise-valid shares over
message content would be a consensus-layer decision that could fork the
sharechain. Instead, the MWU system uses economic penalties and local
policy (nodes can ignore messages over budget) without affecting share
validity.

## Implementation Files

| File | Purpose |
|------|---------|
| `p2pool/share_messages.py` | Core module: messages, signing, encryption, registry, store |
| `p2pool/data.py` | V36 ref_type extension, strict validation in check(), transition scanning in get_warnings() |
| `p2pool/work.py` | Transition message loading (_prepare_transition_message) + embedding |
| `p2pool/main.py` | `--transition-message` CLI argument |
| `create_transition_message.py` | Standalone Python 3 authority message tool (create/verify/keystore) |
| `SHARE_MESSAGING_DESIGN.md` | This document — architecture and rationale |
| `SHARE_MESSAGING_PROTOCOL.md` | Wire format specification |
| `SHARE_MESSAGING_INTEGRATION.md` | Integration plan and phase status |
| `SHARE_MESSAGING_API.md` | HTTP API reference |
| `SHARE_MESSAGING_QUICKSTART.md` | Operator/miner quick start guide |
| `SHARE_MESSAGING_SECURITY.md` | Security model and threat analysis |

## Integration Points (Summary)

1. **data.py**: Add `message_data` to V36 `ref_type`, process in share verification
2. **work.py**: Embed queued messages when generating new shares
3. **web.py**: API endpoints for viewing messages and queuing outbound messages
4. **p2p.py**: No changes needed — messages travel with shares automatically

See `SHARE_MESSAGING_INTEGRATION.md` for detailed integration plan.
