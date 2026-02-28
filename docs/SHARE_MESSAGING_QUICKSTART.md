# P2Pool Share Messaging — Quick Start Guide

## What Is This?

P2Pool V36 includes a decentralized messaging system where miners can send
authenticated messages to each other through the sharechain. Messages are
protected by Proof-of-Work — you must mine valid shares to send messages,
making spam economically impossible.

Messages are **never written to the blockchain**. They travel with P2Pool
shares but are excluded from coinbase transactions, keeping Litecoin and
Dogecoin blocks clean.

---

## For Node Operators

### Prerequisites

- P2Pool V36 node running and synced
- At least one miner connected and producing shares
- (Optional) Signing key for authenticated messaging

### Step 1: Verify Messaging Support

> **Note**: The HTTP API endpoints (`/msg/*`) and BBS web interface are
> **planned (Phase 3+)** and not yet implemented. The steps below describe
> the target experience. What IS implemented today: transition signal
> embedding via `--transition-message` and share-level message validation.

Check that your node has messaging support:

```bash
curl http://localhost:9327/msg/stats
```

Expected response:

```json
{
  "total_messages": 0,
  "messaging_enabled": true,
  "signing_key_configured": false
}
```

If you see `"messaging_enabled": true`, your node can receive and display
messages from the network, even without a signing key.

### Step 2: View Messages

Messages appear automatically as other miners embed them in shares:

```bash
# All recent messages
curl http://localhost:9327/msg/recent

# Chat messages only
curl http://localhost:9327/msg/chat

# Emergency alerts
curl http://localhost:9327/msg/alerts

# Network node status reports
curl http://localhost:9327/msg/status
```

Or visit the BBS (Bulletin Board System) in your browser:

```
http://localhost:9327/static/bbs.html
```

### Step 3: Set Up Signing Key (for Sending Messages)

To **send** messages, you need a derived signing key. This is a one-way
derived key — your master private key (payout address) is never exposed
to the node.

#### 3a. Generate Signing Key (Offline)

Run this on your **secure machine** (NOT on the P2Pool node):

```bash
python derive_signing_key.py <your_payout_WIF> 0
```

Output:

```
Master address:  YOUR_LTC_ADDRESS
Key index:       0
Signing key WIF: YOUR_SIGNING_KEY_WIF
Signing ID:      a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2

Copy this to your p2pool node:
  --signing-key YOUR_SIGNING_KEY_WIF
  --signing-key-index 0

WARNING: Do NOT copy your master WIF to the node!
```

**CRITICAL**: The `<your_payout_WIF>` is your payout address private key.
Never store it on the P2Pool node. Only the derived signing key WIF is safe
to copy to the node.

#### 3b. Configure P2Pool with Signing Key

Add to your P2Pool startup command:

```bash
python run_p2pool.py --net litecoin \
  --signing-key YOUR_SIGNING_KEY_WIF \
  --signing-key-index 0 \
  <your_other_flags>
```

#### 3c. Verify Identity

After restart, check your signing identity:

```bash
curl http://localhost:9327/msg/identity
```

```json
{
  "signing_id": "a1b2c3d4e5f6...",
  "signing_pubkey": "02abcd1234...",
  "key_index": 0,
  "address": "YOUR_LTC_ADDRESS",
  "messaging_enabled": true
}
```

### Step 4: Send Messages

```bash
# Chat message (signed, visible to all miners)
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"chat","text":"Hello from my node!"}'

# Pool announcement
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"announce","text":"Maintenance in 1hr, expect brief downtime"}'
```

Messages are queued and embedded in your next mined share. You must be
actively mining shares to send messages.

### Step 5: Manage Bans (Optional)

If you see unwanted content, ban the sender locally:

```bash
# Ban by signing key
curl -X POST http://localhost:9327/msg/ban \
  -d '{"signing_id":"a1b2c3d4e5f6..."}'

# Ban by payout address
curl -X POST http://localhost:9327/msg/ban \
  -d '{"address":"LtcAd..."}'

# Ban by keyword
curl -X POST http://localhost:9327/msg/ban \
  -d '{"word":"spam"}'

# Remove a ban
curl -X DELETE http://localhost:9327/msg/ban \
  -d '{"signing_id":"a1b2c3d4e5f6..."}'
```

Bans are local to your node — other nodes are not affected.

---

## For Miners

### Sending Your First Message

1. Make sure you're mining on a V36 node with `--signing-key` configured
2. Your node must be actively producing shares
3. Send a message via the API:

```bash
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"chat","text":"First PoW-authenticated message!"}'
```

4. The message will be embedded in your next share and propagate to all
   P2Pool nodes within seconds

### Message Costs

Messages are not free — they incur costs through the Message Weight Unit
(MWU) system:

| Message Type | Typical Cost | Free? |
|---|---|---|
| Node status (unsigned) | 48 MWU | Yes (under 64 MWU free allowance) |
| Version signal (unsigned) | 38 MWU | Yes |
| Chat message (signed, short) | ~232 MWU | No — requires 1 sacrifice share |
| Chat message (signed, full) | ~372 MWU | No — requires 2 sacrifice shares |
| Emergency alert | ~780 MWU | No — requires 4 sacrifice shares |

Sacrifice shares are real shares you mine where the payout goes to the node
operator and donation fund instead of your own address. This is the cost of
messaging — you trade hashrate for communication.

### Key Rotation

If your signing key is compromised, rotate immediately:

```bash
# On your secure machine (offline):
python derive_signing_key.py <master_WIF> 1   # increment key_index

# Update your P2Pool node:
--signing-key <new_WIF> --signing-key-index 1
```

When the node restarts and mines a share with `key_index=1`, all previous
messages signed with `key_index=0` become unverifiable. The attacker's
copy of the old key is immediately useless.

---

## Message Types Explained

### Chat (MINER_MESSAGE)

Miner-to-miner text messages. Must be signed. Visible to all nodes.
Maximum 220 bytes UTF-8 text.

```bash
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"chat","text":"anyone seeing orphans?"}'
```

### Announcements (POOL_ANNOUNCE)

Operator announcements for maintenance, upgrades, etc. Must be signed.

```bash
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"announce","text":"Upgrading to v36.1 in 2hrs"}'
```

### Node Status (NODE_STATUS)

Automatic health reports generated every 5 minutes. Includes version,
uptime, hashrate, peer count, and merged mining status. Signing is
optional — these are primarily for network health monitoring.

### Emergency Alerts (EMERGENCY)

Critical security notices. Must be signed. Displayed as prominent banners
on all dashboards.

```bash
curl -X POST http://localhost:9327/msg/send \
  -d '{"type":"alert","text":"CRITICAL: vulnerability in v35, upgrade now"}'
```

### Transition Signals (TRANSITION_SIGNAL)

Protocol-level upgrade signals. Created **offline** by authority key holders
using the standalone Python 3 tool `create_transition_message.py`. The tool
produces a signed+encrypted hex string that node operators paste into
`--transition-message`. Regular miners cannot create these — only the
hardcoded `COMBINED_DONATION_SCRIPT` key holders (forrestv, frstrtr).

See [Authority Message Creation](#authority-message-creation) below.

---

## BBS Interface

The BBS (Bulletin Board System) is a retro-styled web interface for browsing
messages:

```
http://localhost:9327/static/bbs.html
```

Features:
- Tab filtering: Chat, Announcements, Alerts, Node Status, Keys
- Verification badges (✅ verified / ⚠️ unverified)
- Sender identification (shortened payout address)
- Relative timestamps
- Send form for chat messages and announcements
- Alert banner for emergency messages

---

## Authority Message Creation

Authority key holders (forrestv, frstrtr) use the standalone **Python 3**
tool `create_transition_message.py` to create signed+encrypted transition
signals offline. This tool is completely separate from the P2Pool node
(which runs on PyPy 2.7).

### Requirements

```bash
pip3 install ecdsa    # or: pip3 install coincurve (faster, C-based)
pip3 install mnemonic  # optional — for BIP39 seed phrase support
```

### Creating a Transition Message (Authority Only)

```bash
# With hex private key
python3 create_transition_message.py create \
  --privkey <64-hex-chars> \
  --from 36 --to 37 \
  --msg "Upgrade to V37 — fixes critical bug" \
  --urgency recommended \
  --url "https://github.com/frstrtr/p2pool-merged-v36/releases"

# With BIP39 seed phrase
python3 create_transition_message.py create \
  --seed-phrase "word1 word2 ... word24" \
  --from 36 --to 37 --msg "Upgrade available" --urgency info

# With encrypted keystore file
python3 create_transition_message.py create \
  --keystore authority_key.json \
  --from 36 --to 37 --msg "Required upgrade" --urgency required
```

The tool outputs a hex string that is distributed to node operators.

### Creating an Encrypted Keystore (Authority Only)

```bash
python3 create_transition_message.py create-keystore \
  --privkey <64-hex-chars> --keystore-out authority_key.json
```

The keystore encrypts the private key with PBKDF2 (100,000 iterations).
Password is prompted interactively.

### Verifying a Message (Anyone)

```bash
# Verify hex string
python3 create_transition_message.py verify --file 01a2b3c4d5e6f7...

# Verify hex file
python3 create_transition_message.py verify --file transition_message.hex
```

Shows authority key identity, message content, and signature validity.

### Using the Message (Node Operators)

Node operators receive the hex string from the authority and add it to
their P2Pool startup — **no private key needed**:

```bash
python run_p2pool.py --net litecoin \
  --transition-message 01a2b3c4d5e6f7890123456789abcdef...

# Or point to the hex file:
python run_p2pool.py --net litecoin \
  --transition-message /path/to/transition_message_v36_v37.hex
```

The node validates and embeds the message in every share it mines.

---

## Command-Line Flags Reference

| Flag | Description |
|------|-------------|
| `--signing-key <WIF>` | Derived signing key WIF (from offline tool) |
| `--signing-key-index <N>` | Key rotation index (must match offline derivation) |
| `--message <TEXT>` | Queue a miner message for next share |
| `--announce <TEXT>` | Queue a pool announcement for next share |
| `--transition-message <HEX/FILE>` | Authority-signed transition signal (hex string or file path) |
| `--ban-sender <ID>` | Ban a signing key (hex ID) |
| `--ban-address <ADDR>` | Ban all keys from a payout address |
| `--ban-word <WORD>` | Filter messages containing keyword |

---

## Troubleshooting

### "no signing key configured"

You need to generate a signing key offline and provide it via `--signing-key`.
See Step 3 above.

### Messages not appearing

- You must be mining valid shares — no shares = no messages
- Check that the node is synced: `curl http://localhost:9327/msg/stats`
- Messages expire after 24 hours — check `age` in responses
- Check your ban list: `curl http://localhost:9327/msg/bans`

### "queue full"

Maximum 3 messages can be queued at once. Wait for your next share to be
mined, then the queue drains automatically.

### Key rotation rejected

Make sure `--signing-key-index` matches the index used in the offline
derivation tool. The index must be strictly greater than your previous index.

### Messages show "unverified"

The sender's signing key hasn't been seen yet (they haven't mined a share
with a signing key announcement). Messages from unknown keys are displayed
with ⚠️ unverified — they're still PoW-authenticated (carried in a valid
share) but not cryptographically attributed to a specific identity.

---

## Security Summary

| Concern | Protection |
|---------|-----------|
| Message spam | Must mine valid shares (PoW cost) |
| Identity theft | ECDSA signatures with derived keys |
| Master key exposure | Derived keys are one-way (HMAC-SHA256) |
| Key compromise | Immediate rotation via key_index increment |
| Content filtering | Node-local ban lists |
| Blockchain pollution | Messages never enter coinbase transactions |
| Wire sniffing | XOR obfuscation with network-derived key |
| Authority spoofing | Hardcoded authority pubkeys + encryption envelope |

For the full security analysis, see [SHARE_MESSAGING_SECURITY.md](SHARE_MESSAGING_SECURITY.md).

---

## See Also

- [SHARE_MESSAGING_API.md](SHARE_MESSAGING_API.md) — Full API endpoint reference
- [SHARE_MESSAGING_DESIGN.md](SHARE_MESSAGING_DESIGN.md) — Architecture and rationale
- [SHARE_MESSAGING_PROTOCOL.md](SHARE_MESSAGING_PROTOCOL.md) — Wire format specification
- [SHARE_MESSAGING_INTEGRATION.md](SHARE_MESSAGING_INTEGRATION.md) — Code integration plan
- [SHARE_MESSAGING_SECURITY.md](SHARE_MESSAGING_SECURITY.md) — Threat model and security analysis
- [create_transition_message.py](../scripts/create_transition_message.py) — Standalone Python 3 authority message tool
