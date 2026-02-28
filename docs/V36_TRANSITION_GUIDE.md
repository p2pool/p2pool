# V35 → V36 Transition: Complete Technical Guide

> **"When 90% of shares are the new version, it switches."** — This is a dangerous
> oversimplification. The actual transition is a **multi-stage, multi-threshold,
> safety-gated process** designed to prevent network splits and ensure no miner
> loses rewards during the upgrade. This document explains every stage in detail.

> [!IMPORTANT]
> **Coin-Specific Parameters**: All concrete numbers in this document (share
> periods, chain lengths, time spans, confirmation durations) reflect the
> **Litecoin mainnet + Dogecoin merged mining** configuration as of February 2026.
> P2Pool is a **multi-coin pool framework** — each supported cryptocurrency
> (Bitcoin, Litecoin, Namecoin, Fastcoin, etc.) defines its own network
> parameters in `p2pool/networks/<coin>.py`. Different coins use different
> `SHARE_PERIOD`, `CHAIN_LENGTH`, `REAL_CHAIN_LENGTH`, and threshold values,
> which change all the derived time spans and window sizes. The **transition
> mechanism and stages** described here are universal across all coins; only the
> specific numbers vary. See [Chain Parameters](#chain-parameters-litecoin-mainnet)
> for the values used in this document, and consult the relevant network file
> for other coins.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Concepts](#key-concepts)
3. [Chain Parameters (Litecoin Mainnet)](#chain-parameters-litecoin-mainnet)
4. [Share VERSION vs desired_version](#share-version-vs-desired_version)
5. [Vote Weighting — Not All Shares Are Equal](#vote-weighting--not-all-shares-are-equal)
6. [The Five Transition Stages](#the-five-transition-stages)
   - [Stage 0: Building Chain](#stage-0-building-chain)
   - [Stage 1: Waiting](#stage-1-waiting)
   - [Stage 2: Propagating](#stage-2-propagating)
   - [Stage 3: Signaling (0–60%)](#stage-3-signaling-060)
   - [Stage 4: Strong Signaling (60–95%)](#stage-4-strong-signaling-6095)
   - [Stage 5: Activating (≥95%)](#stage-5-activating-95)
7. [The AutoRatchet State Machine](#the-autoratchet-state-machine)
   - [VOTING State](#voting-state)
   - [ACTIVATED State](#activated-state)
   - [CONFIRMED State](#confirmed-state)
   - [Deactivation Safety Net](#deactivation-safety-net)
   - [All Reversal Scenarios](#all-reversal-scenarios)
   - [Effective Ratchet State Override](#effective-ratchet-state-override)
8. [Confirmation: The Countdown](#confirmation-the-countdown)
9. [Protocol Version Ratchet](#protocol-version-ratchet)
10. [What Changes When V36 Activates](#what-changes-when-v36-activates)
11. [Dashboard Display Legend](#dashboard-display-legend)
    - [Status Badge](#status-badge)
    - [Chain Maturity Bar](#chain-maturity-bar)
    - [Propagation Bar](#propagation-bar)
    - [Signaling Bar (Sampling Window)](#signaling-bar-sampling-window)
    - [Confirmation Bar (V36 Chain Fill)](#confirmation-bar-v36-chain-fill)
    - [Countdown Bar](#countdown-bar)
    - [Version Tags](#version-tags)
    - [Ratchet Banner](#ratchet-banner)
    - [Transition Message](#transition-message)
12. [Classic Stat Page Legend](#classic-stat-page-legend)
13. [FAQ](#faq)

---

## Overview

The V35 → V36 transition is **not** a simple majority vote. It is a carefully
designed multi-stage process with:

- **Two distinct thresholds**: 60% (consensus minimum) and 95% (activation trigger)
- **Two different vote counts**: difficulty-weighted votes (consensus) and unweighted share counts (display)
- **Three AutoRatchet states**: VOTING → ACTIVATED → CONFIRMED
- **Built-in safety**: automatic deactivation if support drops below 50%
- **A 72-hour confirmation period** after activation before the transition is permanent
- **A one-way protocol ratchet** that eventually excludes nodes running old software

The entire process is **automatic** — no manual configuration changes are needed
on any node. Upgraded nodes vote, the network counts votes, and the transition
happens when the thresholds are met.

---

## Key Concepts

| Term | Meaning |
|------|---------|
| **Share** | A proof-of-work unit on the P2Pool sharechain; equivalent to a "mini-block" |
| **Share VERSION** | The binary format of the share (V35 or V36). Determines what fields exist |
| **desired_version** | A vote embedded in every share. "I want the network to run version X" |
| **Sampling Window** | The last 864 shares of the chain — where activation votes are counted |
| **Propagation Target** | Position 8640 in the chain (full chain length) — votes must age to the end of the chain to enter the sampling window |
| **CHAIN_LENGTH** | 8640 shares — the full active sharechain window |
| **AutoRatchet** | The state machine that decides when to switch from producing V35 to V36 shares |
| **Weighted vote** | Each share's vote is multiplied by its difficulty (harder shares get more votes) |

---

## Chain Parameters (Litecoin Mainnet)

> [!NOTE]
> These values are from `p2pool/networks/litecoin.py` and apply to the **Litecoin
> mainnet** sharechain (with Dogecoin as the merged-mined auxiliary chain). Other
> coins have different parameters — for example, Bitcoin uses `SHARE_PERIOD = 30`,
> Fastcoin uses `SHARE_PERIOD = 6`, and testnet configurations use much smaller
> chain lengths for faster iteration. Always check the relevant file under
> `p2pool/networks/` for the coin you are running.

```
SHARE_PERIOD       = 15 seconds    (target time between shares)
CHAIN_LENGTH       = 8640 shares   (24×60×60 ÷ 10 = 8640)
REAL_CHAIN_LENGTH  = 8640 shares   (used for PPLNS weight calculations)

Full chain time span:  8640 × 15s = 129,600s = 36 hours
```

### Derived Windows

These windows are computed from the base parameters above. On a different coin
with different `SHARE_PERIOD` and `CHAIN_LENGTH`, all of these values change
proportionally.

| Window | Formula | Shares (LTC) | Time Span (LTC) |
|--------|---------|--------|-----------|
| **Sampling Window** | CHAIN_LENGTH ÷ 10 | 864 | ~3.6 hours |
| **Propagation Target** | CHAIN_LENGTH | 8640 | ~36 hours |
| **Confirmation Window** | REAL_CHAIN_LENGTH × 2 | 17,280 | ~72 hours |

**Important**: `CHAIN_LENGTH = 24×60×60 ÷ 10 = 8640` was inherited from the
original Bitcoin P2Pool where shares were every 10 seconds. On Litecoin the
`SHARE_PERIOD` is 15s, so the chain actually spans **36 hours**, not 24.

### How the Sampling Window Works

The sharechain is a linked list from the tip (newest) to the genesis (oldest):

```
Position:   0 .......................... 7776 .. 8640
            ↑                            ↑        ↑
           TIP                     Sampling    Chain end
                                   window
            ←——— 7776 shares ———→←— 864 —→
            Recent activity          SAMPLING
            (not counted for         WINDOW
             activation)             (votes counted
                                      here)
```

Shares enter at offset 0 (the tip) and age toward position 8640. Only when
a share reaches position 7776–8640 (the **sampling window**) are its votes
counted for the 60%/95% thresholds.

This design ensures that a sudden burst of shares cannot instantly trigger
activation — votes must persist across **~32–36 hours** of aging before they
enter the sampling window.

The propagation progress on the dashboard tracks how deep the oldest V36 vote
is relative to the full chain length (8640), giving a clear picture of how
far along the aging process is.

---

## Share VERSION vs desired_version

Every share has two version-related fields:

### VERSION (share format)

- A **class constant** — determined by which share class was used to build it
- `PaddingBugfixShare.VERSION = 35` — V35 format (current)
- `MergedMiningShare.VERSION = 36` — V36 format (new, with merged mining)
- Determines binary serialization, available fields, and protocol features
- **Cannot be changed** after a share is created

### desired_version (vote)

- A **per-share field** embedded in `share_data`
- Expresses what version the share's creator **wants** the network to run
- V36 nodes set `desired_version = 36` on **every share they produce**, even
  if the share itself is V35 format
- This is the "ballot" — the share says "I'm V35, but I vote for V36"

**During the transition**, the sharechain contains V35-format shares that
carry `desired_version = 36`. These are V35 shares with upgrade votes.
The actual format switch (V35 → V36) happens only after the AutoRatchet
transitions to ACTIVATED.

---

## Vote Weighting — Not All Shares Are Equal

The consensus-level vote count uses **difficulty-weighted** voting:

```python
def get_desired_version_counts(tracker, best_share_hash, dist):
    res = {}
    for share in tracker.get_chain(best_share_hash, dist):
        weight = target_to_average_attempts(share.target)  # = 2^256 / (target+1)
        res[share.desired_version] = res.get(share.desired_version, 0) + weight
    return res
```

- A share at difficulty 64 gets **4×** the vote weight of a share at difficulty 16
- This prevents share flooding attacks (creating many easy shares to stuff the ballot)
- A miner with 50% of the hashrate produces ~50% of the weighted votes, regardless of
  how many shares they submit

**The dashboard shows two different counts:**

| Metric | Weighting | Where Used |
|--------|-----------|------------|
| **Sampling window signaling** | Difficulty-weighted | 60% and 95% threshold checks (consensus) |
| **Overall chain percentage** | Unweighted (share count) | Display only — "X out of Y shares" |

The weighted percentage (consensus) and unweighted percentage (display) may differ
slightly, especially when miners have different share difficulties.

---

## The Five Transition Stages

### Stage 0: Building Chain

**When**: The node has fewer than `CHAIN_LENGTH` (8640) shares in its local chain.

This happens when a node first starts and is still syncing the sharechain from
peers. No upgrade checks can run because the sampling window isn't fully formed.

- **Status badge**: `BUILDING CHAIN` (amber)
- **Progress bar**: Chain Maturity bar showing sync progress
- **Message**: "Building chain: X/8640 shares (need Y more before upgrade checks activate)"

### Stage 1: Waiting

**When**: Chain is mature (≥8640 shares) but zero V36 votes exist anywhere.

No miners have upgraded yet, or all upgraded shares have aged out.

- **Status badge**: `WAITING` (grey)
- **Message**: "Waiting for miners to upgrade. No V36 votes in chain yet."

### Stage 2: Propagating

**When**: V36 votes exist in the chain, but the deepest (oldest) V36 vote hasn't
reached position 8640 yet — it hasn't fully aged through the chain.

This is the "patience" stage. V36 nodes are producing shares and voting, but those
votes need to age ~36 hours before they reach the end of the chain wavelength and
enter the sampling window (positions 7776–8640).

- **Status badge**: `PROPAGATING` (blue)
- **Progress bar**: Propagation bar showing how deep the oldest V36 vote is
- **Message**: "V36 votes propagating: N votes (X% of chain), deepest at position D/8640. Reach sampling window in ~Xh Xm"
- **ETA**: Estimated from shares remaining × `SHARE_PERIOD`

### Stage 3: Signaling (0–60%)

**When**: V36 votes have entered the sampling window but represent < 60% of
weighted votes.

Miners are upgrading, but not enough to meet the minimum consensus threshold.

- **Status badge**: `SIGNALING` (blue)
- **Progress bar**: Signaling bar with threshold markers at 60% and 95%
- **Message**: "V36 signaling: X% in sampling window (Y% overall in chain)"

### Stage 4: Strong Signaling (60–95%)

**When**: V36 votes represent ≥60% but <95% of weighted votes in the sampling window.

**The 60% threshold is critical**: it is the **consensus-level minimum** for
share format switching. Once 60% is reached:

- V36-format shares become **valid** on the chain (peers will accept them)
- But the AutoRatchet does **not** switch to producing V36 shares yet
- This range provides a safety buffer — the network won't switch until
  an overwhelming supermajority (95%) is reached

```python
# In share.check() — consensus validation:
if counts.get(self.VERSION, 0) < sum(counts.itervalues()) * 60 // 100:
    raise PeerMisbehavingError('switch without enough hash power upgraded')
```

- **Status badge**: `SIGNALING STRONG` (amber/warning)
- **Progress bar**: Signaling bar, 60% threshold now behind the bar fill
- **Message**: "Strong V36 signaling: X% in sampling window (need 95% to activate)"

### Stage 5: Activating (≥95%)

**When**: V36 votes represent ≥95% of weighted votes in the sampling window.

The AutoRatchet will transition from VOTING → ACTIVATED on its next check.
All upgraded nodes will begin producing V36-format shares.

- **Status badge**: `ACTIVATING` (green)
- **Progress bar**: Signaling bar is full, past the 95% marker
- **Message**: "V36 activation threshold reached! X% in sampling window — switchover imminent"

---

## The AutoRatchet State Machine

The AutoRatchet is the core mechanism that controls when each node switchesPEREYBERE
from producing V35 shares to V36 shares. It runs independently on each node
but converges to the same decision across the network because all nodes see
the same sharechain.

```
                    ┌────────────────────────────────┐
                    │           VOTING               │
                    │  (produces V35, votes V36)     │
                    └───────────┬────────────────────┘
                                │
                    ≥95% weighted votes for V36
                    in a full sampling window
                                │
                                ▼
                    ┌────────────────────────────────┐
                    │          ACTIVATED             │
                    │  (produces V36 shares)         │◄── reverts if <50% votes
                    │  72-hour confirmation countdown│
                    └───────────┬────────────────────┘
                                │
                    17,280 shares elapsed AND
                    ≥95% V36-format shares in chain
                                │
                                ▼
                    ┌────────────────────────────────┐
                    │          CONFIRMED             │
                    │  (permanent, survives restart) │
                    │  V36 is the new baseline       │
                    └────────────────────────────────┘
```

### VOTING State

- **Produces**: V35-format shares (`PaddingBugfixShare`)
- **Votes**: `desired_version = 36` (signals upgrade intent)
- **Transition to ACTIVATED**: Requires **all** of:
  1. Full window of data (≥ `REAL_CHAIN_LENGTH` shares available)
  2. ≥95% of difficulty-weighted votes in the window are for V36
- **Initial state** for all nodes, and the fallback if activation fails

### ACTIVATED State

- **Produces**: V36-format shares (`MergedMiningShare`)
- **Votes**: `desired_version = 36`
- **Features**: Merged mining, share messaging, compact addresses now active
- **Persisted**: Saved to `v36_ratchet.json` — survives restarts
- **Countdown begins**: Tracking shares elapsed since activation
- **Can revert**: If weighted V36 votes drop below 50% (see below)

### CONFIRMED State

- **Produces**: V36-format shares
- **Permanent**: Saved to disk, survives restarts, cannot be reverted by vote
- **Still consensus-aware**: If V36 votes somehow drop below 50%, the node
  will produce V35 shares (following consensus) while keeping its CONFIRMED
  state. This handles edge cases like connecting to a mostly-V35 network
  after a partition.
- **The transition display is hidden** once CONFIRMED — the transition is complete.

### Deactivation Safety Net

The AutoRatchet includes critical safety mechanisms to prevent network splits.
The fundamental principle is: **consensus always wins**. No matter what state
the ratchet is in, if the majority of the network runs V35, the node follows
the majority.

#### Threshold Hysteresis

| Threshold | Value | Direction |
|-----------|-------|----------|
| Activation | **95%** | VOTING → ACTIVATED (requires supermajority) |
| Deactivation | **50%** | ACTIVATED → VOTING (simple majority lost) |
| Gap | **45 percentage points** | Prevents oscillation |

The large gap between activation (95%) and deactivation (50%) is deliberate.
Without it, if the V36 percentage hovered around 90%, the ratchet could
rapidly cycle: activate → deactivate → activate → deactivate every few
minutes. The 50% floor means the network must *genuinely* lose majority
support before reversal occurs.

### All Reversal Scenarios

The ratchet handles six distinct scenarios where a node might need to produce
V35 shares instead of V36:

#### Scenario 1: ACTIVATED → VOTING (Hard Revert)

**Trigger**: V36 vote percentage drops below 50% with a full window of data.

```
[AutoRatchet] ACTIVATED -> VOTING (42% votes < 50% threshold)
```

- **State changes**: ACTIVATED → VOTING (persisted to `v36_ratchet.json`)
- **Activation data cleared**: `_activated_at` and `_activated_height` set to `None`
- **Share output**: Switches to `PaddingBugfixShare` (V35)
- **Vote**: Still `desired_version = 36` (continues advocating for V36)
- **Confirmation countdown**: Lost — if re-activated later, the countdown
  restarts from zero

This is the most drastic reversal. It occurs when a significant portion of
the network's hashrate stops running V36 software — for example, if a large
mining pool reverts to V35 due to bugs or compatibility issues.

#### Scenario 2: CONFIRMED but Following V35 Network (Soft Override)

**Trigger**: CONFIRMED node connects to a network where <50% vote V36.

```
[AutoRatchet] WARNING: CONFIRMED but network is 73% V35 - following network consensus
```

- **State does NOT change**: Stays CONFIRMED in `v36_ratchet.json`
- **Share output**: `PaddingBugfixShare` (V35) — follows consensus
- **Vote**: Still `desired_version = 36`
- **On restart with empty chain**: Will bootstrap as V36 (CONFIRMED persists)
- **When V36 majority returns**: Automatically resumes V36 share production

This is a **soft override** — the return value switches to V35 without
mutating the persisted state. This handles the scenario where a CONFIRMED
node connects to a predominantly V35 network (e.g., after a network partition
heals, or if the node operator connects to a different P2Pool network).

The node doesn't "forget" it was confirmed. If the network later regains
V36 majority, the node seamlessly returns to producing V36 shares without
needing to go through the full activation → confirmation cycle again.

#### Scenario 3: ACTIVATED with Empty Chain on Restart

**Trigger**: Node restarts with ACTIVATED state but no share chain
(cleared share store, new data directory, fresh sync).

- **Share output**: `PaddingBugfixShare` (V35) — not safe to assume V36
- **State**: Stays ACTIVATED (not reverted)
- **Rationale**: Without a chain to check votes against, the node can't
  verify that V36 still has majority support. Producing V36 shares blindly
  could create invalid shares if the network has reverted.

**Compare with CONFIRMED + empty chain**: A CONFIRMED node WILL produce V36
shares on an empty chain, because confirmation is a permanent commitment.

#### Scenario 4: Stale Activation Height After Restart

**Trigger**: Node restarts and rebuilds a shorter chain than the one that
was running when it activated. The persisted `_activated_height` is now
higher than the current chain height.

```
[AutoRatchet] Adjusting stale activated_height 15000 -> 8200 (chain rebuilt after restart)
```

- **Effect**: `_activated_height` is reset to the current chain height
- **Confirmation countdown**: Restarts from zero (from the new height)
- **Share output**: Stays V36 (node is still ACTIVATED)
- **Persisted**: The corrected height is saved to `v36_ratchet.json`

Without this correction, `shares_since = height - _activated_height` would
be negative or zero, potentially triggering immediate false confirmation or
preventing confirmation from ever completing.

#### Scenario 5: `desired_version` Never Stops Voting V36

In **all** reversal scenarios — whether the node reverts to VOTING, follows
a V35 network while CONFIRMED, or restarts with an empty chain — the node
**always** sets `desired_version = 36` on every share it produces.

This is by design: even when temporarily producing V35-format shares, the
node advocates for V36. This ensures that the V36 vote count recovers as
quickly as possible once conditions improve.

#### Summary Table

| # | Scenario | State Change? | Output | Persisted? |
|---|----------|---------------|--------|------------|
| 1 | ACTIVATED, votes drop <50% | **Yes**: ACTIVATED→VOTING | V35 | Yes (state + cleared activation data) |
| 2 | CONFIRMED, votes drop <50% | **No**: stays CONFIRMED | V35 (soft override) | No (return-value only) |
| 3 | ACTIVATED, empty chain on restart | **No**: stays ACTIVATED | V35 (safety fallback) | No |
| 4 | ACTIVATED, stale height | Height reset only | V36 (stays ACTIVATED) | Yes (corrected height) |
| 5 | Any state | N/A | V35 or V36 per above | N/A |

> [!IMPORTANT]
> The common thread across all scenarios: **the node never produces V36 shares
> unless it can verify V36 majority support on the live chain**, except for the
> CONFIRMED state which represents a permanent network commitment.

### Effective Ratchet State Override

The dashboard and API expose an **effective ratchet state** that may differ
from the persisted state. This handles a subtle edge case:

**Scenario**: A node has `confirmed` persisted in `v36_ratchet.json`, but
connects to a network where <50% of shares are V36 format (not just votes —
actual V36-format shares in the chain).

**What happens**:
1. The persisted `state` stays `confirmed` (never mutated)
2. The web.py display logic computes `effective_ratchet_state = 'voting'`
3. The transition display widget **reappears** (normally hidden when confirmed)
4. The API reports both:
   - `auto_ratchet.state`: `"voting"` (effective — what the UI shows)
   - `auto_ratchet.persisted_state`: `"confirmed"` (raw — what's on disk)

The same override applies in the `get_warnings()` function: transition-related
warnings are shown when the effective state is `voting`, even if the persisted
state is `confirmed`. This ensures operators see relevant warnings when their
node is operating in V35 compatibility mode.

**Why this matters**: Without this override, a CONFIRMED node joining a V35
network would show "transition complete" in the UI while actually producing
V35 shares — confusing operators into thinking V36 is active when it isn't.

---

## Confirmation: The Countdown

After activation, the transition enters a 72-hour confirmation period:

```
Confirmation Window = 2 × REAL_CHAIN_LENGTH = 2 × 8640 = 17,280 shares
At 15 seconds per share: 17,280 × 15 = 259,200 seconds ≈ 72 hours (3 days)
```

### Confirmation Requirements

The countdown completes (ACTIVATED → CONFIRMED) when **both**:

1. **17,280 shares** have been added to the chain since activation
2. **≥95% of shares** in the chain are actual V36-format shares (not just votes)

Requirement #2 is important: during the transition, the chain contains a mix
of V35 and V36 shares. As old V35 shares age out and new V36 shares enter,
the V36 percentage climbs toward 100%. Only when the chain is overwhelmingly
V36 does confirmation complete.

### Why 72 Hours?

The confirmation window (2× chain length) ensures:
- The entire chain has been "flushed" with V36 shares at least twice
- Any temporary hashrate fluctuations are smoothed out
- All miners have had ample time to upgrade or reconnect
- No "accidental" activation from a temporary hashrate spike

---

## Protocol Version Ratchet

Independently from the AutoRatchet, there is a **protocol version ratchet**
that excludes old nodes from the network:

| Share Class | MINIMUM_PROTOCOL_VERSION |
|-------------|--------------------------|
| BaseShare (V17) | 1400 |
| PaddingBugfixShare (V35) | 3500 |
| MergedMiningShare (V36) | **3503** |

When ≥95% of the weighted votes in the sampling window are for V36, the
network's runtime `MINIMUM_PROTOCOL_VERSION` increases from 3301 to **3503**.

Nodes running protocol versions below 3503 will be **disconnected by peers**.
This is a one-way ratchet — the minimum version only increases, never decreases.

This ensures that once V36 is dominant, old nodes still running V35-only
software will be pushed off the network, preventing them from producing
incompatible shares.

---

## What Changes When V36 Activates

V36 (`MergedMiningShare`) introduces these new capabilities:

| Feature | Description |
|---------|-------------|
| **Merged Mining** | Shares include `merged_addresses`, `merged_coinbase_info`, `merged_payout_hash` fields for mining auxiliary chains (e.g., Dogecoin) alongside Litecoin |
| **Share Messaging** | `message_data` field allows embedding signed messages in shares (transition announcements, operator communications) |
| **Compact Addresses** | `pubkey_hash` (160-bit) + `pubkey_type` enum replaces variable-length address strings. Supports P2PKH, P2WPKH, and P2SH |
| **Combined Donation** | Switches from P2PK (67 bytes) to P2SH 1-of-2 multisig donation script — more compact and flexible |
| **VarInt Encoding** | `subsidy` and `abswork` use VarInt instead of fixed-size integers — saves 3–15 bytes per share |
| **VarStr Hash Link** | `extra_data` in hash links uses VarStr instead of fixed padding |
| **Merged Mining PPLNS** | `get_v36_merged_weights()` excludes pre-V36 shares from merged mining reward distribution — only V36-signaling miners receive merged mining payouts |

---

## Dashboard Display Legend

The modern dashboard (`/static/dashboard.html`) provides a comprehensive
visual display of the transition state. Here is a complete guide to every
element.

### Status Badge

Located in the top-right corner of the transition section. Shows the current
transition stage as a colored pill:

| Badge Text | Color | Meaning |
|-----------|-------|---------|
| **BUILDING CHAIN** | Amber (#FFC107) | Node is syncing, chain not yet mature |
| **WAITING** | Grey (#8888a0) | No V36 votes detected anywhere |
| **PROPAGATING** | Blue (#2196F3) | V36 votes exist but haven't reached sampling window |
| **SIGNALING** | Blue (#008de4) | V36 votes in sampling window, below 60% |
| **SIGNALING STRONG** | Amber (#FFC107) | V36 votes at 60–95% (above consensus minimum) |
| **ACTIVATING** | Green (#28a745) | V36 votes ≥95%, activation imminent |
| **NO TRANSITION** | Purple (#6f42c1) | No active transition (V36 already confirmed or not applicable) |

### Chain Maturity Bar

**Shown when**: Node's chain height < `CHAIN_LENGTH` (8640).

```
┌────────────────────────────────────────────────────┐
│ Chain Maturity:                              42.5% │
│ ██████████████████████░░░░░░░░░░░░░░░░░░░░░  42.5% │
│ 3672 / 8640 (42.5%) — need 4968 more shares        │
└────────────────────────────────────────────────────┘
```

- **Gradient**: Amber → Orange (#FFC107 → #FF9800)
- **Width**: `chain_height / chain_length × 100%`
- **Embedded label**: Shows percentage inside the filled portion
- **Detail text**: Shows exact counts and shares remaining

### Propagation Bar

**Shown when**: Status is `propagating` (V36 votes exist but haven't reached
the sampling window).

```
┌────────────────────────────────────────────────────┐
│ Vote Propagation:                            18.1% │
│ █████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   18.1% │
│ V36 votes: 1566/8640 (18.1% of full chain).        │
│ Deepest at position 5443/8640 — reach sampling     │
│ window in ~9h 44m                                  │
└────────────────────────────────────────────────────┘
```

- **Gradient**: Blue → Light Blue (#2196F3 → #03A9F4)
- **Width**: `deepest_v36_position / chain_length × 100%`
- **Embedded label**: Shows `"X% V36"`
- **Detail text**: Shows vote count, chain percentage, deepest position, and ETA
- **ETA**: Calculated as `shares_to_window × SHARE_PERIOD`, displayed as hours/minutes

### Signaling Bar (Sampling Window)

**Shown when**: The node is in the voting phase (not yet activated). This is the
primary transition indicator.

```
┌────────────────────────────────────────────────────┐
│ Sampling Window Signaling:                    72.3%│
│                            │60%           │95%     │
│ ████████████████████████████░░░░░░░░░░░░░░░░  72.3%│
│ 72.3% of sampling window (864 shares) voting for   │
│ V36 — need 95% to activate                         │
└────────────────────────────────────────────────────┘
```

- **Gradient**: Blue → Green (#008de4 → #28a745)
- **Threshold markers**: Two dashed vertical lines at **60%** and **95%**
  - 60%: Consensus minimum — V36 shares become valid on the chain
  - 95%: Activation threshold — AutoRatchet triggers
- **Width**: `max(overall_v36_vote_pct, sampling_signaling)` (shows whichever is higher)
- **Embedded label format**:
  - If overall chain % differs from sampling window %: `"18.1% chain / 0.0% window"`
  - If they're similar: `"72.3%"`
  - When bar is very narrow (< 15%), label appears outside the bar to remain readable
- **Detail text**: Shows both full-chain percentage and sampling window percentage

#### Reading the Dual Label

The signaling bar may show two percentages, like `"18.1% chain / 0.0% window"`:

- **Chain %**: Proportion of V36 votes across the entire active chain (8640 shares).
  This reflects current adoption but is NOT used for activation.
- **Window %**: Proportion of V36 weighted votes in the sampling window (last 864 shares
  at the tail of the chain). This IS the number that matters for the 60% and 95%
  thresholds.

The chain % will always be higher than the window % during propagation, because
recent V36 shares near the tip haven't aged into the sampling window yet.

### Confirmation Bar (V36 Chain Fill)

**Shown when**: AutoRatchet is ACTIVATED and the chain contains a mix of V35 and V36 shares.

```
┌────────────────────────────────────────────────────┐
│ V36 Chain Fill:                              63.2% │
│                  │50%                  │95%        │
│ ████████████████████████████░░░░░░░░░░░░░░░  63.2% │
│ 63.2% V36 format in chain (5460/8640 shares).      │
│ Confirmation: 4200/17280 shares elapsed.           │
│                                                    │
│ V36 shares are replacing older V35 shares in the   │
│ chain. Once 100% V36, the confirmation countdown   │
│ begins.                                            │
└────────────────────────────────────────────────────┘
```

- **Gradient**: Blue → Cyan when <95% (#2196F3 → #00BCD4), Green when ≥95% (#4CAF50 → #00E676)
- **Threshold markers**: 50% (default) and 95% (green)
- **Width**: Percentage of shares in the chain that are V36 format
- **Embedded label**: `"63.2% V36"`
- **Explanation**: As time passes, older V35 shares age out of the chain and are replaced
  by new V36 shares. This bar tracks how "pure" the chain has become.

### Countdown Bar

**Shown when**: AutoRatchet is ACTIVATED and the chain is 100% V36 format.

```
┌────────────────────────────────────────────────────┐
│ Confirmation Countdown:                      58.3% │
│ ████████████████████████████░░░░░░░░░░░░░░░  58.3% │
│ 10080/17280 shares elapsed — ~30h remaining        │
│                                                    │
│ All shares are V36 format. Counting 2× chain       │
│ length (17280 shares) of sustained ≥95% V36 —      │
│ ensures the upgrade is irreversible before         │
│ locking in.                                        │
└────────────────────────────────────────────────────┘
```

- **Gradient**: Green (#4CAF50 → #00E676)
- **Width**: `shares_since_activation / confirmation_window × 100%`
- **Embedded label**: Percentage complete
- **ETA**: `remaining_shares × 10 seconds` (approximate)
- **When it fills to 100%**: AutoRatchet transitions to CONFIRMED and the entire
  transition display disappears

### Version Tags

Below the progress bars, version information is displayed as colored pill-shaped tags:

```
┌────────────────────────────────────────────────────┐
│ [V35 desired: 7074/8640 (81.9%)]                   │
│ [V36 desired: 1566/8640 (18.1%) — target] ← purple │
│ [Sampling window (864): V35 100.0%, V36 0.0%] grey │
│ [V36 adoption: 1566/8640 votes (18.1%), 0 V36      │
│  format shares]                            ← green │
└────────────────────────────────────────────────────┘
```

1. **Desired version tags**: One per version found in the full chain.
   The target version (V36) gets a purple highlight.
   - Tag shows: version, count, total shares, percentage
   - This is **unweighted** (simple share count, not difficulty-weighted)

2. **Sampling window tag** (grey, smaller text): Shows the **weighted** vote
   breakdown in the 864-share sampling window that matters for consensus.

3. **Overall adoption badge** (green border): Summary showing total V36 votes,
   percentage of chain, and count of actual V36-format shares.

### Ratchet Banner

A colored warning/info bar showing the AutoRatchet's current state:

| State | Color | Icon | Example Text |
|-------|-------|------|-------------|
| **VOTING** | Amber background, ⏳ icon | `VOTING` badge | "V35 → V36 Transition: VOTING — producing V35 shares, voting for V36. X% V36 in sampling window." |
| **ACTIVATED** | Blue background, 🔄 icon | `ACTIVATED` badge | "V36 Transition: ACTIVATED — Now producing V36 shares. 63% V36 format in chain. Confirmation: 4200/17280 shares elapsed." |
| **CONFIRMED** | Green `CONFIRMED` badge | *(banner hidden)* | The banner disappears — transition is complete |

### Transition Message

If a signed transition message has been broadcast via the share messaging system,
it appears as a highlighted box:

```
┌─ 📢 V35 → V36 Transition Signal ──── [RECOMMENDED] ─┐
│                                                     │
│ Upgrade to V36 for merged mining support. Download  │
│ the latest release.                                 │
│                                                     │
│ 🔗 https://github.com/frstrtr/p2pool-merged-v36     │
└─────────────────────────────────────────────────────┘
```

| Urgency | Border/Badge Color | Meaning |
|---------|-------------------|---------|
| **INFO** | Blue (#2196F3) | Informational — no immediate action needed |
| **RECOMMENDED** | Orange (#FF9800) | Upgrade recommended soon |
| **REQUIRED** | Red (#F44336) | Upgrade required urgently |

---

## Classic Stat Page Legend

The classic stat page (`/static/index.html`) shows a simpler version of
the transition display:

### Differences from the Dashboard

| Feature | Dashboard | Classic Page |
|---------|-----------|-------------|
| Theme | Dark background | Light background (#f0e6ff purple section) |
| Threshold markers | ✅ Dashed lines at 60%, 95% | ❌ Not shown |
| Confirmation bar | ✅ Separate chain fill bar | ❌ Not present |
| Countdown bar | ✅ Separate countdown bar | ❌ Not present |
| Ratchet banner | ✅ Colored state banner | ❌ Not present |
| Version display | Colored pill badges | Pipe-delimited text |
| Signaling bar gradient | Blue → Green | Purple → Green |

### Classic Page Elements

1. **Header**: `🔄 V35 → V36 Transition` with status badge (same colors as dashboard)
2. **Chain Maturity Bar**: Amber gradient, same as dashboard (shown when chain < 8640)
3. **Propagation Bar**: Blue gradient, shows vote depth and ETA
4. **Signaling Bar**: Purple → Green gradient, shows sampling window percentage
   - Same dual label logic: `"18.1% chain / 0.0% window"` when values differ
   - Label moves outside the bar when percentage is very low (< 15%)
5. **Status message**: Server-generated text describing current stage
6. **Version info**: Current share type and chain version breakdown as text
7. **Transition message**: Blue-highlighted box with message text and URL link

---

## FAQ

### "When 90% of shares are the new version, it switches" — is this correct?

**No.** This oversimplification is wrong in several ways:

1. **The activation threshold is 95%, not 90%** — and it uses *difficulty-weighted*
   votes, not simple share counts
2. **It doesn't "switch" instantly** — activation triggers a 72-hour confirmation
   period during which the switch can still be reverted
3. **There are TWO thresholds** — 60% (consensus minimum for V36 share validity)
   and 95% (AutoRatchet activation trigger)
4. **Votes are weighted by difficulty** — a high-difficulty share counts more than
   a low-difficulty share
5. **Only the sampling window matters** — not the whole chain. The sampling window
   is the last 864 of 8640 shares, representing ~3.6 hours
6. **There's a deactivation threshold at 50%** — if support drops, the network
   rolls back automatically

### Why is my V36 percentage so low if I have lots of hashrate?

Several factors:

1. **36-hour chain**: The chain spans 36 hours (8640 × 15s). If you started 20 hours
   ago, 44% of the chain still predates your participation.
2. **Difficulty weighting**: Your shares may have lower difficulty than others,
   giving them less vote weight in the consensus count.
3. **Sampling window lag**: The sampling window (positions 7776–8640) only shows
   shares that are 32–36 hours old. Your recent shares haven't reached it yet.
4. **The display shows unweighted counts**: The dashboard version tags show simple
   share counts, but the actual activation check uses difficulty-weighted votes.

### Can the transition be reversed after activation?

**Yes, during the 72-hour confirmation period.** If weighted V36 votes drop below
50%, the AutoRatchet performs a **hard revert** from ACTIVATED to VOTING — clearing
all activation data and restarting the process. Nodes resume producing V35 shares
immediately. The confirmation countdown is lost and must restart from zero if the
network re-activates later.

**No, after confirmation — but with a safety net.** Once CONFIRMED, the state is
persisted to disk and survives restarts. The ratchet will NOT revert to VOTING.
However, even confirmed nodes will **follow V35 consensus** if the network
genuinely reverts — they produce V35 shares while keeping their CONFIRMED state
internally. This means:

- They won't fork the network by producing V36 shares nobody accepts
- If V36 majority returns, they instantly resume V36 without re-activating
- The dashboard shows the transition widget again (via the effective state
  override) so operators can see the situation

See [All Reversal Scenarios](#all-reversal-scenarios) for the complete list of
six rollback cases and their behaviors.

### What happens if my CONFIRMED node joins a V35 network?

The node detects that <50% of shares are V36 format and enters a **soft override**
mode: it produces V35 shares to follow consensus, but keeps its CONFIRMED state
on disk. The dashboard's effective ratchet state shows `voting` instead of
`confirmed`, and the transition widget reappears so you can see what's happening.

This can occur when:
- You connect to a different P2Pool network segment
- A network partition heals and your side had fewer miners
- The majority of miners rolled back their software

The node continues voting `desired_version = 36` on every share, helping the
network return to V36 majority. No manual intervention is needed.

### What happens to miners who don't upgrade?

1. **During signaling**: Nothing — V35 miners continue mining normally
2. **After activation**: V35-only nodes continue working but won't produce V36
   shares. They remain connected to the network.
3. **After the protocol version ratchet (≥95% V36)**: The network's
   `MINIMUM_PROTOCOL_VERSION` bumps to 3503. Old nodes running protocol < 3503
   will be **disconnected by peers** and can no longer participate.

### How long does the entire transition take?

Minimum timeline assuming instant 100% adoption **(Litecoin mainnet values)**:

| Phase | Duration (LTC) | Cumulative |
|-------|----------|------------|
| Propagation (votes age into sampling window) | ~32 hours | 32 hours |
| Activation (once 95% in sampling window) | Immediate | 32 hours |
| Chain fill (V35 shares age out) | ~36 hours | 68 hours |
| Confirmation countdown (17,280 shares) | ~72 hours | ~140 hours |
| **Total** | | **~6 days** |

In practice, with gradual adoption, the signaling phase alone may take days to
weeks. The full transition from first V36 vote to CONFIRMED can take **1–3 weeks**
depending on how quickly miners upgrade.

> [!NOTE]
> On testnet (`CHAIN_LENGTH = 400`, `SHARE_PERIOD = 4s`), the same process
> completes in **under 2 hours** — propagation ~24 min, chain fill ~27 min,
> confirmation ~53 min. On Bitcoin (`SHARE_PERIOD = 30s`, `CHAIN_LENGTH = 8640`),
> the chain spans 72 hours and the full transition takes ~12 days minimum.

### What are `full_chain_versions` vs `versions` in the API?

The `/version_signaling` API endpoint returns both:

- **`full_chain_versions`**: desired_version counts across the entire active
  chain (up to 8640 shares). Unweighted. Used for version tags and overall
  adoption display.
- **`versions`**: Difficulty-weighted desired_version percentages in the
  **sampling window only** (864 shares). This is what determines the 60% and
  95% thresholds for consensus.

### What is the difference between `sampling_signaling` and `overall_v36_vote_pct`?

- **`sampling_signaling`**: Weighted V36 percentage in the sampling window (864
  shares at tail of chain). This is the number that triggers activation.
- **`overall_v36_vote_pct`**: Unweighted V36 share count percentage across the
  full active chain (8640 shares). This is a general adoption indicator.

During propagation, `overall_v36_vote_pct` will be much higher than
`sampling_signaling` because recent V36 votes near the tip haven't aged into the
sampling window yet.

---

---

## Appendix: Network Parameter Reference

For quick reference, here are `SHARE_PERIOD` and `CHAIN_LENGTH` values for
selected coins. The transition mechanism is identical across all of them —
only the timing changes.

| Network | SHARE_PERIOD | CHAIN_LENGTH | Chain Span | Confirmation Window |
|---------|-------------|-------------|-----------|--------------------|
| **Litecoin mainnet** | 15s | 8640 | 36 hours | 72 hours (17,280 shares) |
| Litecoin testnet | 4s | 400 | 27 min | 53 min (800 shares) |
| Bitcoin mainnet | 30s | 8640 | 72 hours | 144 hours (17,280 shares) |
| Bitcoin testnet | 30s | 360 | 3 hours | 6 hours (720 shares) |
| Bitcoin regtest | 30s | 360 | 3 hours | 6 hours (720 shares) |
| Fastcoin | 6s | 8640 | 14.4 hours | 28.8 hours (17,280 shares) |
| Bitcoin Cash | 60s | 4320 | 72 hours | 144 hours (8,640 shares) |
| Bitcoin SV | 30s | 2880 | 24 hours | 48 hours (5,760 shares) |
| Terracoin | 45s | 2880 | 36 hours | 72 hours (5,760 shares) |

> [!TIP]
> To check the parameters for your coin: `cat p2pool/networks/<coin>.py | grep -E 'SHARE_PERIOD|CHAIN_LENGTH'`

---

*Last updated: 2026-02-25. Covers p2pool-merged-v36 transition mechanism as
implemented in `p2pool/data.py` (AutoRatchet, version validation) and
`p2pool/web.py` (display logic). All specific numeric values are for
Litecoin mainnet + Dogecoin merged mining unless otherwise noted.*
