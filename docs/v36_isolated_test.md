# V36 Isolated Testnet Setup — Progress Log

## Goal

Set up isolated private testnet for end-to-end V36 block finding:
- **Litecoin testnet** (public, works fine)
- **Dogecoin private testnet4alpha** (custom build, public testnet is bugged)
- Test full path: share → block target met → coinbase → payout → merged mining aux PoW

## Current Status: Preparing Infrastructure

### Phase 1: Stop Mainnet Services ✅

#### P2Pool Stopped on All Nodes

| Node | Method | Status |
|------|--------|--------|
| NODE_A_IP | `screen -S p2poolA -X quit` | ✅ Stopped |
| NODE_C_IP | `kill -SIGINT 53861` (bare PID, no screen) | ✅ Stopped |
| NODE_B_IP | `screen -S p2poolB -X quit` | ✅ Stopped |

**NodeC details:**
- Was running p2pool as bare process (PID 53861), not in screen
- Had a systemd `p2pool.service` but it was **disabled/inactive** (leftover Bitcoin Cash config)
- Also killed stuck debug script (PID 54268)
- Command was: `pypy run_p2pool.py --net litecoin --bitcoind-address LTC_DAEMON_IP --bitcoind-rpc-port 9332 --bitcoind-p2p-port 9333 --address YOUR_LTC_ADDRESS_C --give-author 2 -f 0 --disable-upnp --max-conns 20 --debug litecoinrpc YOUR_LTC_RPC_PASSWORD`
- No merged mining configured on node 30

### Phase 2: Sharechain Backups ✅

| Node | Backup Path | Size |
|------|-------------|------|
| 29 | `~/backups/sharechain-litecoin-20260213_2353` | 143M |
| 30 | `~/backups/sharechain-litecoin-20260213_2353` | 62M |
| 31 | `~/backups/sharechain-litecoin-20260213_2354` | 189M |

### Phase 3: Stop LTC + DOGE Daemons ✅

**Litecoin (LTC_DAEMON_IP):**
- Binary: `~/.local/bin/litecoind`
- CLI: `~/.local/bin/litecoin-cli`
- Systemd: `litecoind-mainnet.service` — **stopped and disabled**
- Blockchain: `/litecoin-blockchain/mainnet/` (228G)
- Last sync: blocks=3,055,635, verificationprogress=0.9999996

**Dogecoin (DOGE_DAEMON_IP):**
- Mainnet binary: `~/dogecoin-1.14.8/bin/dogecoind`
- CLI: `~/dogecoin-1.14.8/bin/dogecoin-cli`
- Systemd: `dogecoind-mainnet.service` — **stopped and disabled**
- Blockchain: `/dogecoin-blockchain/mainnet/` (132G) — symlinked from `~/.dogecoin/{blocks,chainstate}`
- Last sync: blocks=6,084,285, verificationprogress=0.9999989

**Note:** `~/.dogecoin/testnet4alpha/` exists (from earlier partial setup attempt)

### Phase 4: Blockchain Backup to Storage ✅ (rsync running)

**Storage server:** MINER_IP_4 (10G interface: STORAGE_SERVER)
**Storage path:** `/media/nvme2tb/` (331G available, 81% used)

**10G interfaces activated:**
- LTC node: `STORAGE_NET_LTC/24` on `ens224` ✅
- DOGE node: `STORAGE_NET_DOGE/24` on `ens224` ✅
- Storage: `STORAGE_SERVER` on `eno49` (already up) ✅

**Backups (rsync delta update from Jan 29 backups):**
```bash
# Litecoin (228G total, delta from Jan 29)
ssh YOUR_USER@LTC_DAEMON_IP "rsync -av --progress --delete \
    /litecoin-blockchain/mainnet/ YOUR_USER@STORAGE_SERVER:/media/nvme2tb/.litecoin-mainnet/ \
    --exclude='.lock' --exclude='*.pid' --exclude='debug.log'"

# Dogecoin (132G total, delta from Jan 29)
ssh YOUR_USER@DOGE_DAEMON_IP "rsync -av --progress --delete \
    /dogecoin-blockchain/mainnet/ YOUR_USER@STORAGE_SERVER:/media/nvme2tb/.dogecoin-mainnet/ \
    --exclude='.lock' --exclude='*.pid' --exclude='debug.log'"

# DOGE wallet+config (small files)
ssh YOUR_USER@DOGE_DAEMON_IP "rsync -av ~/.dogecoin/{wallet.dat,dogecoin.conf,peers.dat} \
    YOUR_USER@STORAGE_SERVER:/media/nvme2tb/.dogecoin-mainnet/"
```

**To re-enable mainnet services after testing:**
```bash
ssh -t YOUR_USER@LTC_DAEMON_IP "sudo systemctl enable litecoind-mainnet.service && sudo systemctl start litecoind-mainnet.service"
ssh -t YOUR_USER@DOGE_DAEMON_IP "sudo systemctl enable dogecoind-mainnet.service && sudo systemctl start dogecoind-mainnet.service"
```

### Phase 5: Dogecoin Testnet4alpha Node ✅ (Running)

**Custom build on DOGE_DAEMON_IP:**
- Binary: `~/dogecoin-auxpow-gbt/src/dogecoind` (v1.14.99.0, built Jan 27)
- CLI: `~/dogecoin-auxpow-gbt/src/dogecoin-cli`
- **No additional patches needed** — init.cpp/util.cpp already worked as-is
- Was previously running fine: mined to block 1158, blocks every ~minute

**Started Feb 14 with:**
```bash
~/dogecoin-auxpow-gbt/src/dogecoind -testnet4alpha -daemon -gen=1 \
    -rpcport=44555 -port=44557 -rpcbind=0.0.0.0 \
    -rpcallowip=INTERNAL_SUBNET -rpcuser=dogecoinrpc -rpcpassword=testpass
```

**Actual running ports (from debug.log):**
- RPC port: **44555** (not 44559 from the script — actual config differs)
- P2P port: **44557** (not 44558)
- Chain: `testnet4alpha`, blocks=1119, progress=1.0
- AuxPoW: `createauxblock` / `getauxblock` available (wallet disabled, no getnewaddress)

### Phase 5b: Litecoin Testnet Node ✅ (Running, Synced)

**On LTC_DAEMON_IP:**
```bash
litecoind -testnet -daemon
```
- Config restructured: `litecoin.conf` with `[main]` and `[test]` sections
- Backup at `litecoin.conf.mainnet.bak`
- RPC port: **19332**, P2P port: **19335**
- User: `litecoinrpc`, Pass: `YOUR_LTC_RPC_PASSWORD`
- Blocks: **4,555,242** (fully synced)
- Wallet loaded: `p2pool_testnet`

### Phase 6: Testnet Addresses & Settings ✅

**Shared keypair (same pubkey):**
- Pubkey: `0232a16014d52f97ae2a7a0641509cae3ac6ca41d2d2a5e1214412a89a29262f11`
- Hash160: `29c1bdba942bbe1ce70837049923253b7f291a70`

| Coin | Network | Address | Validated |
|------|---------|---------|-----------|
| LTC  | testnet | `YOUR_TLTC_ADDRESS` | ✅ bech32 |
| DOGE | testnet4alpha | `YOUR_TDOGE_ADDRESS` | ✅ isvalid=true |

### Phase 7: P2Pool Testnet Configuration ✅

**NodeC (NODE_C_IP) — jtoomim canonical p2pool:**
- Repo: `~/Github/p2pool` (origin: jtoomim/p2pool.git)
- Branch: **rawtx** (switched from master, stash@{0} has our v36 mods)
- Data folder: **deleted** (fresh start), backup at `~/backups/p2pool-canonical-data-20260214`
- `PERSIST = False` in `p2pool/networks/litecoin_testnet.py`

**P2Pool start command:**
```bash
cd ~/Github/p2pool && screen -dmS p2poolC ~/pypy2.7-v7.3.20-linux64/bin/pypy run_p2pool.py \
    --net litecoin_testnet \
    --bitcoind-address LTC_DAEMON_IP --bitcoind-rpcport 19332 \
    --bitcoind-rpcuser litecoinrpc --bitcoind-rpcpassword YOUR_LTC_RPC_PASSWORD \
    --bitcoind-p2p-port 19335 \
    -a YOUR_TLTC_ADDRESS \
    --merged_addr YOUR_TDOGE_ADDRESS%http://dogecoinrpc:YOUR_DOGE_RPC_PASSWORD@DOGE_DAEMON_IP:44555/
```

**RPC connectivity verified:**
- NodeC → LTC 26:19332 ✅ (curl test returned blockcount)
- DOGE 27:44555 `createauxblock`/`getauxblock` available ✅

---

## Network Architecture

```
        Litecoin Testnet (public)          Dogecoin Testnet4alpha (private)
        ┌────────────────────┐             ┌────────────────────────┐
        │ litecoind -testnet │             │ dogecoind -testnet4alpha│
        │ LTC_DAEMON_IP      │             │ DOGE_DAEMON_IP           │
        │ RPC: 19332         │             │ RPC: 44555              │
        │ P2P: 19335         │             │ P2P: 44557              │
        └────────┬───────────┘             └────────┬───────────────┘
                 │                                  │
        ┌────────┴──────────────────────────────────┴───┐
        │      P2Pool jtoomim canonical (rawtx branch)   │
        │      NodeC (NODE_C_IP)                   │
        │      LTC addr: YOUR_TLTC_ADDRESS_TRUNC...   │
        │      DOGE addr: YOUR_TDOGE_ADDR_TRUNC...   │
        │      Stratum: 19327                            │
        │      P2P: 19338                                │
        └────────────────────┬──────────────────────────┘
                             │
        ┌────────────────────┴──────────────────────────┐
        │           CPU miner (scrypt, testnet diff)     │
        │           stratum+tcp://NODE_C_IP:19327    │
        └───────────────────────────────────────────────┘
```

## Mainnet Restart Commands (for when we're done testing)

### P2Pool NodeA
```bash
screen -dmS p2poolA bash -c 'export PATH=$HOME/pypy2.7-v7.3.20-linux64/bin:$PATH && cd ~/p2pool-merged && pypy run_p2pool.py --net litecoin --coind-address LTC_DAEMON_IP --coind-rpc-port 9332 --coind-p2p-port 9333 --merged-coind-address 127.0.0.1 --merged-coind-rpc-port 44556 --merged-coind-p2p-port 22556 --merged-coind-p2p-address DOGE_DAEMON_IP --merged-coind-rpc-user dogecoinrpc --merged-coind-rpc-password YOUR_DOGE_RPC_PASSWORD --address YOUR_LTC_ADDRESS --give-author 2 -f 0 --disable-upnp --max-conns 20 --external-ip YOUR_PUBLIC_IP --no-console litecoinrpc YOUR_LTC_RPC_PASSWORD 2>&1 | tee -a ~/p2pool-merged/data/litecoin/log'
```

### P2Pool NodeC
```bash
# NodeC ran LTC-only (no merged mining), bare process:
cd ~/p2pool-merged && pypy run_p2pool.py --net litecoin --bitcoind-address LTC_DAEMON_IP --bitcoind-rpc-port 9332 --bitcoind-p2p-port 9333 --address YOUR_LTC_ADDRESS_C --give-author 2 -f 0 --disable-upnp --max-conns 20 --debug litecoinrpc YOUR_LTC_RPC_PASSWORD
```

### P2Pool NodeB
```bash
screen -dmS p2poolB bash -c 'export PATH=$HOME/pypy2.7-v7.3.20-linux64/bin:$PATH && cd ~/p2pool-merged && pypy run_p2pool.py --net litecoin --coind-address LTC_DAEMON_IP --coind-rpc-port 9332 --coind-p2p-port 9333 --merged-coind-address 127.0.0.1 --merged-coind-rpc-port 44556 --merged-coind-p2p-port 22556 --merged-coind-p2p-address DOGE_DAEMON_IP --merged-coind-rpc-user dogecoinrpc --merged-coind-rpc-password YOUR_DOGE_RPC_PASSWORD --address YOUR_LTC_ADDRESS_B --give-author 2 -f 0 --disable-upnp --max-conns 20 --external-ip YOUR_PUBLIC_IP --no-console litecoinrpc YOUR_LTC_RPC_PASSWORD 2>&1 | tee -a ~/p2pool-merged/data/litecoin/log'
```

### Daemon Restart
```bash
# Litecoin
ssh YOUR_USER@LTC_DAEMON_IP "sudo systemctl start litecoind-mainnet.service"

# Dogecoin
ssh YOUR_USER@DOGE_DAEMON_IP "sudo systemctl start dogecoind-mainnet.service"
```

## Versioning Context

**Current git state:** commit `043060f` tag `v35.03`
- Protocol.VERSION = 3503 (testing phase, compat with jtoomim 3502)
- V36 Share MINIMUM_PROTOCOL_VERSION = 3503
- Network configs at 3301 (ratchet handles upgrades)
- When V36 finalized: bump both to 3600

## Key Files
- `setup_dogecoin_testnet4alpha.sh` — Full Dogecoin testnet4alpha build script
- `dogecoin_testnet4alpha.patch` — Patch file for Dogecoin source
- `DOGECOIN_TESTNET_BUG.md` — Documents why public testnet is broken
- `start_p2pool_scrypt_testnet.sh` — Previous testnet start script
- `p2pool/networks/litecoin_testnet.py` — LTC testnet p2pool config
