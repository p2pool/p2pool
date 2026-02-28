# P2Pool Share Messaging — Security Model & Threat Analysis

## Overview

The P2Pool share messaging system achieves decentralized, authenticated
communication without any external infrastructure. Security is anchored
to two independent trust roots:

1. **Proof-of-Work** — only miners who produce valid shares can send messages
2. **ECDSA Signatures** — derived signing keys authenticate message origin

This document analyzes the threat model, attack surfaces, and mitigations.

---

## Trust Model

### Trust Root: Proof-of-Work

Every message exists inside a valid P2Pool share. To embed a message, the
sender must:

1. Solve a share-difficulty proof-of-work puzzle
2. The share must chain correctly onto the sharechain
3. Other nodes independently verify the PoW before accepting

**Cost of sending one message**: The electricity and hardware cost of mining
one valid share. On the Litecoin P2Pool network with ~60 GH/s total hashrate,
a single share requires substantial computational work.

This is fundamentally different from any traditional messaging system —
there is no registration, no accounts, no API keys. The "account" is your
hashrate and the "fee" is real electricity.

### Trust Root: Cryptographic Signatures

Messages can be cryptographically signed with ECDSA (secp256k1) using
derived signing keys. The signing key derivation chain:

```
Master Private Key (payout address — never exposed)
    │
    └── HMAC-SHA256(master_pk, "p2pool-msg-v1" || key_index_le32)
              │
              └── Signing Private Key (derived — safe to give to node)
                    │
                    └── ECDSA signature on message_hash
```

**Properties**:
- **One-way**: Signing key cannot be reversed to obtain master key
- **Deterministic**: Same master key + key_index always produces same signing key
- **Rotatable**: Incrementing key_index produces a completely new signing key
- **Verifiable**: The signing public key is announced in shares

---

## Threat Analysis

### 1. Message Forgery — Impersonating Another Miner

**Attack**: Attacker creates a message that appears to come from another miner.

**Difficulty**: IMPOSSIBLE without the victim's signing key.

**Analysis**:
- Signed messages include an ECDSA signature verifiable against the announced
  signing public key
- Even if the attacker mines valid shares (satisfying PoW), the signature
  will not verify against the victim's signing_id
- Unsigned messages carry only the share's payout address as attribution,
  which is set by the miner's configuration — the attacker would need to
  mine shares with the victim's payout address, which means the mining
  rewards go to the victim (self-defeating attack)

**Mitigation**: ECDSA signatures + signing key announcements in PoW-protected shares.

---

### 2. Message Spam / Flooding

**Attack**: Attacker floods the network with excessive messages.

**Difficulty**: ECONOMICALLY PROHIBITIVE.

**Analysis**:
- Each message requires mining a valid share (PoW cost)
- Messages beyond the free allowance (64 MWU) require **sacrifice shares** —
  shares where the payout goes to node operators and the donation fund
- Rate limiting: max 4096 MWU per hour per signing_id
- Max 3 messages per share, max 512 bytes per share
- Sustained flooding at maximum rate costs the attacker their entire mining
  income (sacrifice shares pay others, not the attacker)

**Economic analysis** (Litecoin mainnet):
```
Share value:          ~0.001 LTC (varies with difficulty)
Messages per hour:    ~11 full signed messages
Sacrifice cost:       ~2 shares per message = ~0.002 LTC per message
Max hourly cost:      ~0.022 LTC to send 11 messages
```

This is expensive spam that pays real money to the network operators.

**Mitigations**:
1. PoW cost per share
2. Sacrifice share requirement for signed messages
3. Rolling MWU rate limiter per signing_id
4. Per-share message limits (3 messages, 512 bytes, 1024 MWU)
5. Node-local ban lists
6. Message store capacity limit (1000 messages, 24h expiry)

---

### 3. Signing Key Compromise

**Attack**: Attacker obtains a miner's signing private key (e.g., by
compromising the P2Pool node server).

**Difficulty**: Requires server compromise.

**Impact**: MODERATE — message impersonation only, funds are safe.

**Analysis**:
- The signing key is a **derived** key — it cannot be reversed to obtain
  the master private key (payout address WIF)
- The attacker can sign messages as the victim, but:
  - Cannot steal mining rewards (master key is not on the node)
  - Cannot modify the victim's payout address
  - Can only impersonate in message signing
- The attacker still needs to mine valid shares to embed the forged messages

**Mitigation**: Immediate key rotation via `key_index` increment.

```
Compromised:  key_index=0 → signing_key_A → attacker has this
Rotated:      key_index=1 → signing_key_B → announced in next share
Result:       signing_key_A is REVOKED, all old signatures become unverifiable
```

Key rotation is atomic — one share with the new key_index revokes all
previous keys for that miner address.

**Recovery procedure**:
1. Revoke: Generate new signing key with `key_index + 1` on secure machine
2. Restart: Update P2Pool with new `--signing-key` and `--signing-key-index`
3. Announce: Mine one share to propagate the new key announcement
4. Done: Old key is immediately revoked across the entire network

---

### 4. Master Key Exposure

**Attack**: Attacker obtains the miner's master private key (payout address).

**Difficulty**: Should never happen — master key should stay on air-gapped machine.

**Impact**: CRITICAL — but this is NOT a messaging system vulnerability.

**Analysis**:
- If the master key is stolen, the attacker can steal mining rewards
- This has nothing to do with the messaging system — it's a general
  cryptocurrency security issue
- The messaging system is explicitly designed to prevent this: the master
  key **never** touches the P2Pool node

**Defense-in-depth**:
- Offline key derivation tool runs on secure machine only
- Node only receives derived signing key WIF
- Documentation repeatedly warns: "Do NOT copy your master WIF to the node"
- Even if the node is compromised, only the signing key is exposed

---

### 5. Replay Attacks

**Attack**: Attacker replays a previously seen message in a new share.

**Difficulty**: Requires mining a valid share.

**Analysis**:
- Messages are deduplicated by `message_hash` (SHA256d of content)
- Identical messages (same type, flags, timestamp, payload) produce the
  same hash and are dropped by the `ShareMessageStore`
- The attacker must still mine a valid share to replay, which costs them

**Mitigation**: Deduplication by message_hash in ShareMessageStore.

---

### 6. Sharechain Fork / Message Divergence

**Attack**: Network split causes different nodes to see different messages.

**Difficulty**: Inherent risk of any decentralized system.

**Analysis**:
- Messages are embedded in shares, so they follow the sharechain
- If the sharechain forks, different branches may carry different messages
- When the fork resolves (longest chain wins), the "losing" messages are
  discarded along with their shares
- This is identical to how Bitcoin transactions work during blockchain forks

**Mitigation**: The sharechain consensus mechanism (longest chain) resolves
message divergence automatically. Messages are ephemeral (24h expiry) so
short forks have minimal impact.

---

### 7. Authority Key Compromise

**Attack**: Attacker obtains one of the COMBINED_DONATION_SCRIPT authority
private keys.

**Difficulty**: Requires compromising the key holders (forrestv or frstrtr).

**Impact**: MODERATE — can send fake transition signals.

**Analysis**:
- Authority keys are used for protocol-level messages (transition signals)
- Messages are created offline using `create_transition_message.py` (Python 3)
- The authority private key never touches a P2Pool node — only the hex output does
- A compromised authority key could send fake "upgrade to v37" signals
- These signals are displayed as warnings but do NOT trigger automatic
  upgrades — node operators must independently verify
- There are two authority keys — compromise of one still leaves the other
  as a trusted source

**Mitigation**:
1. Two independent authority keys (redundancy)
2. Transition signals are advisory, not automatic
3. Authority key holders should use encrypted keystores
   (`create_transition_message.py create-keystore`) rather than raw hex keys
4. Node operators should always verify upgrade instructions through
   out-of-band channels (GitHub, forums, etc.)
5. Authority keys can be rotated by publishing a new software release
   with updated `DONATION_AUTHORITY_PUBKEYS`
6. `create_transition_message.py` zeroes the private key from memory after use

---

### 8. Content Injection

**Attack**: Attacker embeds malicious content (XSS, SQL injection, etc.)
in message payloads.

**Difficulty**: Trivial if the attacker is mining shares.

**Impact**: Depends on how the UI renders messages.

**Analysis**:
- Message payloads are arbitrary bytes (max 220)
- If rendered as HTML without sanitization, XSS is possible
- If used in database queries without parameterization, SQL injection is possible

**Mitigations**:
1. **BBS UI**: All message content MUST be HTML-escaped before rendering
2. **API responses**: Payloads are returned as-is in JSON — clients must
   sanitize before display
3. **Node-local**: No database queries — messages are stored in memory only
4. **Content filtering**: Ban-by-keyword allows operators to filter patterns

**Implementation requirement**: The BBS HTML page must use `textContent`
(not `innerHTML`) when inserting message text into the DOM.

---

### 9. Wire Sniffing / Traffic Analysis

**Attack**: ISP or network observer reads message content from TCP traffic.

**Difficulty**: Easy for passive network observers.

**Mitigation**: Wire obfuscation (Phase 6).

**Analysis**:
- All `message_data` is XOR-obfuscated with a key derived from the
  P2Pool network identifier
- The obfuscation key is: `SHA256("p2pool-msg-obfuscate" || net.IDENTIFIER)`
- This prevents casual wire sniffing (ISPs, network monitors)
- This is NOT cryptographic security — any P2Pool node knows the key
- For true confidentiality, use private messaging (ECDH, Phase 7)

**Obfuscation limitations**:
- Any P2Pool node can deobfuscate all messages
- A determined attacker can run a P2Pool node to read all messages
- The obfuscation only prevents non-P2Pool observers

---

### 10. Sybil Attack on Message Reputation

**Attack**: Attacker creates many signing identities to dominate the
message feed with apparently different senders.

**Difficulty**: EXPENSIVE — each identity must mine valid shares.

**Analysis**:
- Creating a signing identity requires mining at least one share with a
  signing key announcement
- Each share requires solving a PoW puzzle
- The attacker needs multiple payout addresses (each gets a different
  signing identity)
- More identities = more hashrate split across addresses = slower share
  production per identity

**Mitigation**:
1. PoW cost per identity (must mine shares)
2. Messaging eligibility requires recent share history (min 10 shares)
3. Ban-by-address catches all keys from one payout address
4. Rate limiting per signing_id applies independently

---

### 11. Denial-of-Service on Message Store

**Attack**: Overwhelming the in-memory message store with valid messages.

**Difficulty**: MODERATE — requires sustained share production.

**Analysis**:
- Message store has hard limits: max 1000 messages, 24h expiry
- At typical share rates (~2 per minute network-wide), with max 3 messages
  per share, the theoretical maximum is 360 messages per hour
- Pruning removes oldest messages first
- The message store is in-memory only — no disk persistence to abuse

**Mitigation**: Fixed capacity (1000), automatic pruning, message expiry.

---

## Encryption Security Analysis

### Wire Obfuscation (Non-cryptographic)

| Property | Status |
|----------|--------|
| Prevents passive TCP sniffing | ✅ |
| Prevents active man-in-middle | ❌ |
| Prevents P2Pool node from reading | ❌ (by design) |
| Key derivation | Deterministic from network ID |
| Cipher | XOR with SHA256 keystream |

### Authority Encryption (Transition Signals)

Created by `create_transition_message.py` (standalone Python 3):

| Property | Status |
|----------|--------|
| Confidentiality | ✅ Only nodes with authority pubkey can decrypt |
| Integrity | ✅ HMAC-SHA256 MAC |
| Authentication | ✅ ECDSA signature inside encrypted envelope |
| Forward secrecy | ❌ Static authority keys |
| Replay protection | ✅ Random 16-byte nonce per message |
| Key separation | ✅ Authority key never on P2Pool node — only hex output |
| Key storage | ✅ Optional encrypted keystore (PBKDF2, 100K iterations) |
| Memory safety | ✅ Private key zeroed from memory after signing |
| Self-verification | ✅ Tool verifies its own output before printing |

### Private Messaging ECDH (Phase 7, Future)

| Property | Status |
|----------|--------|
| Confidentiality | ✅ AES-256-GCM with ECDH shared secret |
| Integrity | ✅ GCM authentication tag |
| Authentication | ✅ Sender signing_id visible (optional) |
| Forward secrecy | ❌ Static signing keys (mitigated by rotation) |
| Deniability | ⚠️ ECDH is symmetric — neither party can prove the other sent it |

---

## Cryptographic Primitives

| Primitive | Usage | Library |
|-----------|-------|---------|
| HMAC-SHA256 | Signing key derivation, encryption key derivation, MAC | hashlib |
| SHA256 (double) | message_hash, ref_hash, share_hash | hashlib |
| HASH160 (SHA256 + RIPEMD160) | signing_id derivation | hashlib |
| ECDSA secp256k1 | Message signing and verification | coincurve / ecdsa |
| XOR stream cipher | Wire obfuscation, authority encryption | custom |
| AES-256-GCM (future) | Private message encryption | TBD |

### Library Fallback Chain

The crypto implementation uses a fallback chain for PyPy 2.7 compatibility:

```
coincurve (C-based, fast) → ecdsa (pure Python, portable)
```

If neither library is available, signing and verification are disabled
(messages are treated as unsigned). This is a graceful degradation — the
messaging system continues to function for PoW-authenticated messages.

---

## Comparison with Alternative Approaches

| Feature | Coinbase OP_RETURN | Separate P2P Protocol | **ref_type Extension** |
|---------|---|---|---|
| PoW-protected | ✅ | ❌ Needs own anti-spam | **✅** |
| Blockchain-clean | ❌ Pollutes blockchain | ✅ | **✅** |
| Propagation | ✅ With blocks | ✅ Custom relay | **✅ Existing P2P** |
| Anti-spam cost | High (block reward) | Zero (free) | **Medium (share PoW)** |
| Implementation | Simple | Complex (new protocol) | **Medium (field extension)** |
| Backward compat | Easy | Hard (new message types) | **Easy (PossiblyNoneType)** |

---

## Security Invariants

These properties must always hold:

1. **No master key exposure**: The P2Pool node process never has access to
   the miner's payout address private key
2. **PoW gating**: Every message is embedded in a PoW-valid share — no
   free messaging capability exists
3. **Blockchain cleanliness**: `message_data` is in `ref_type` (hashed into
   `ref_hash`), NOT in the coinbase transaction — messages never appear on
   the Litecoin or Dogecoin blockchain
4. **Key revocation**: A signing key with `key_index=N` immediately revokes
   all keys with `key_index < N` for the same miner address
5. **Strict message validation**: Shares carrying `message_data` that fails
   decryption or signature verification are **REJECTED** via
   `PeerMisbehavingError` — the miner wastes their PoW and earns no reward.
   Shares with NO `message_data` (None or empty) are always valid
6. **Ban locality**: Ban lists are local to each node — no node can censor
   messages for other nodes by manipulating the sharechain
7. **Authority verification**: Transition signals require both encryption
   by a known authority pubkey AND valid ECDSA signature — forgery requires
   the authority's private key

---

## Audit Checklist

For security reviewers:

### Signing Key Derivation
- [ ] HMAC-SHA256 domain separation includes version string and key_index
- [ ] Derived key is valid secp256k1 scalar (non-zero, less than curve order)
- [ ] HASH160 of derived pubkey matches signing_id
- [ ] Different key_index values produce different signing keys
- [ ] Derivation is deterministic (same inputs → same outputs)

### Message Signing
- [ ] message_hash covers msg_type, flags, timestamp, and payload
- [ ] message_hash does NOT cover signing_id (avoids circular dependency)
- [ ] ECDSA verify matches sign for round-trip
- [ ] Invalid signatures are rejected (not silently accepted)
- [ ] Unsigned messages are clearly marked (signing_id = zero bytes)

### Share Integration
- [ ] `message_data` in ref_type with `PossiblyNoneType(b'', VarStrType())`
- [ ] Default `b''` produces identical ref_hash as pre-messaging shares
- [ ] message_data is NOT included in coinbase/gentx
- [ ] Tampered message_data produces different ref_hash (PoW fails)

### Store & Deduplication
- [ ] Messages deduplicated by message_hash (SHA256d of content)
- [ ] Store enforces MAX_MESSAGE_HISTORY (1000) and MAX_MESSAGE_AGE (86400s)
- [ ] Pruning removes oldest messages first

### Authority Messages
- [ ] Only DONATION_AUTHORITY_PUBKEYS can create authority-encrypted envelopes
- [ ] Decryption verifies HMAC-SHA256 MAC before processing
- [ ] Invalid MAC → entire message_data rejected
- [ ] Authority pubkeys are hardcoded (not configurable at runtime)

### Input Validation
- [ ] Payload size ≤ MAX_MESSAGE_PAYLOAD (220 bytes)
- [ ] Messages per share ≤ MAX_MESSAGES_PER_SHARE (3)
- [ ] Total message bytes ≤ MAX_TOTAL_MESSAGE_BYTES (512)
- [ ] msg_type is a known value (unknown types logged but not processed)
- [ ] Envelope version == 1 (unknown versions ignored)

### UI Safety
- [ ] BBS page HTML-escapes all message content
- [ ] No innerHTML used for user-generated content
- [ ] API JSON responses properly escaped
- [ ] Long payloads truncated in display

---

## Responsible Disclosure

If you discover a vulnerability in the P2Pool share messaging system:

1. **Do NOT** publish publicly before coordinating a fix
2. **Do NOT** exploit the vulnerability on mainnet
3. Contact maintainers through:
   - GitHub Issues (mark as security-sensitive)
   - Direct contact via the project README
4. Allow reasonable time for a patch before public disclosure

---

## See Also

- [SHARE_MESSAGING_DESIGN.md](SHARE_MESSAGING_DESIGN.md) — Architecture and crypto design
- [SHARE_MESSAGING_PROTOCOL.md](SHARE_MESSAGING_PROTOCOL.md) — Wire format specification
- [SHARE_MESSAGING_API.md](SHARE_MESSAGING_API.md) — HTTP API reference
- [SHARE_MESSAGING_QUICKSTART.md](SHARE_MESSAGING_QUICKSTART.md) — Operator/miner quick start
- [SHARE_MESSAGING_INTEGRATION.md](SHARE_MESSAGING_INTEGRATION.md) — Code integration plan
- [create_transition_message.py](../scripts/create_transition_message.py) — Standalone Python 3 authority message tool
