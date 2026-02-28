# Changelog

All notable changes to P2Pool Merged Mining V36 are documented in this file.

## [v36-0.09-alpha] - 2026-03-01

### Features
- **macOS (Intel) installation guide** — New comprehensive section in `INSTALL.md` covering end-to-end setup on macOS with Intel hardware. Includes Homebrew-based PyPy 2.7 installation, dependency compilation (scrypt, coincurve/libsecp256k1), MM-Adapter venv setup, LTC+DOGE merged mining launch, `launchd` background service configuration, and firewall notes. Tested and verified on macOS 26.3 (x86_64) with full merged mining operational.
- **README macOS callout** — Added macOS (Intel) to the platform support checklist and a direct link to the INSTALL.md macOS section.

### Documentation
- **Docs cleanup** — Replaced example-only placeholder values across all documentation, scripts, and test fixtures for consistency and clarity. Updated 38 files spanning `docs/`, `scripts/`, `tests/`, `mm-adapter/`, `README.md`, and `.gitignore`.
- **`.gitignore` update** — Added `mm-adapter/config.yaml` to prevent accidental commits of local configuration files.

---

## [v36-0.08-alpha] - 2026-02-28

### Features
- **Docker deployment** — Added root `Dockerfile` (multi-stage: Ubuntu 22.04 + PyPy 2.7 + all deps), `docker-compose.yml` (P2Pool + MM-Adapter with healthchecks), `.env.example`, `.dockerignore`, and `mm-adapter/config.docker.example.yaml`. Full merged mining stack starts with three commands:
  ```bash
  cp .env.example .env && vi .env
  cp mm-adapter/config.docker.example.yaml mm-adapter/config.docker.yaml
  docker compose up -d
  ```
- **Windows 10/11 deployment guide** — New `docs/WINDOWS_DEPLOYMENT.md` with three tested paths: WSL2 (recommended), Docker on WSL2, and Native Windows. End-to-end tested on Windows 11 + WSL2 Ubuntu 22.04 with LTC+DOGE merged mining.
- **README Docker quick start** — Added Docker quick start section with prerequisites, build time estimates (~3 min first build), and share sync notes.
- **WSL2 startup helper** — `scripts/start_wsl_pool.sh` launches MM-Adapter + P2Pool in one command.

### Bug Fixes
- **fix: `--help` crash** — `--merged_addr` argparse help string had a bare `%` in `payout%http://...` that caused `ValueError: unsupported format character` during `--help` rendering. Escaped as `%%`.
- **fix: mm-adapter Dockerfile port** — Changed `EXPOSE 44555` to `EXPOSE 44556` to match the actual default server port.
- **fix: `.gitignore` credential safety** — Added `.env`, `.env.*` (except `.env.example`), and `mm-adapter/config.docker.yaml` to `.gitignore` to prevent accidental credential commits.

### Testing
- **WSL2**: Clean Docker build from scratch (2m43s), `docker compose up -d` — both containers healthy, 67 GH/s pool, 85 peers, dashboard OK.
- **Node 30** (Ubuntu 24.04, bare metal): Fresh `git clone` + Docker install + `docker compose up -d` — both containers healthy in ~10s, share chain synced 15k/17k in 60s, dashboard at `:9327` returns 200.

---

## [v36-0.07-alpha] - 2026-02-28

### Features & Improvements
- **Windows 10/11 compatibility (Phase 1)** —
  - `memory.py`: Replaced WMI dependency with native ctypes (kernel32/psapi) for Windows process memory reporting; added macOS resource.getrusage() fallback; returns 0 on any failure.
  - `os.rename()` atomic replace: Now wrapped in try/except OSError with os.remove()+os.rename() fallback for Windows in share_messages.py, broadcaster.py, and merged_broadcaster.py (Windows does not support overwriting existing files with os.rename).
  - `scrypt.c`: Added SCRYPT_INLINE portability macro (__forceinline for MSVC, __inline for GCC/Clang, inline for others) replacing GCC-only __inline.
  - `setup.py`: Removed dead p2pool.dash references, updated web-static data_files, added os.rename Windows fallback, fixed print syntax for Python 2/3 compat.

- **Address format warnings always visible** — Dashboard and API now always display address format warnings, not just during V36 transition. Added explicit warning for V35 phase: only auto-converted DOGE addresses are used for merged mining rewards until V36 activates; explicit stratum multi-address format is ignored pre-V36.
- **Address warning section UI** — Dashboard "Address Format Guide" is always visible and expanded by default, with clear urgency and phase-specific warnings.
- **API address_warnings** — `version_signaling` API now returns all relevant address warnings for the current phase, including V35 limitation, multi-address format, auto-conversion, and invalid address redistribution.

### Bug Fixes
- **Signaling percentage bug** — Transition banner and stats now always show the correct V36 signaling percentage. Fixed bug where V35's dominant vote % was shown as V36's when successor override was active. Now uses `sampling_signaling` for both API and UI.
- **Remove redundant signaling % in banner** — Status banner no longer repeats the sampling percentage (already shown in progress bar and stats).
- **Remove embedded transition blob** — Transition message is now loaded only from the signed .hex file; embedded copy removed from code.
- **ecdsa verification required** — Transition message signature verification now always uses ecdsa 0.19.1 (CVE-safe); coincurve is optional and not present on nodes.

### Deployment
- Both node 29 and node 31 updated to commit a0b5652, running with ecdsa 0.19.1, no coincurve. Verified API and dashboard on both nodes.

---

## [v36-0.06-alpha] - 2026-02-28

### Features & Improvements
- **feat: Always show address format warnings** — Dashboard and API now always display address format warnings, not just during V36 transition. Added explicit warning for V35 phase: only auto-converted DOGE addresses are used for merged mining rewards until V36 activates; explicit stratum multi-address format is ignored pre-V36.
- **feat: Address warning section UI** — Dashboard "Address Format Guide" is always visible and expanded by default, with clear urgency and phase-specific warnings.
- **feat: API address_warnings** — `version_signaling` API now returns all relevant address warnings for the current phase, including V35 limitation, multi-address format, auto-conversion, and invalid address redistribution.

### Bug Fixes
- **fix: Signaling percentage bug** — Transition banner and stats now always show the correct V36 signaling percentage. Fixed bug where V35's dominant vote % was shown as V36's when successor override was active. Now uses `sampling_signaling` for both API and UI.
- **fix: Remove redundant signaling % in banner** — Status banner no longer repeats the sampling percentage (already shown in progress bar and stats).
- **fix: Remove embedded transition blob** — Transition message is now loaded only from the signed .hex file; embedded copy removed from code.
- **fix: ecdsa verification required** — Transition message signature verification now always uses ecdsa 0.19.1 (CVE-safe); coincurve is optional and not present on nodes.

### Deployment
- Both node 29 and node 31 updated to commit a0b5652, running with ecdsa 0.19.1, no coincurve. Verified API and dashboard on both nodes.

---

## [v36-0.05-alpha] - 2026-02-27

### Critical Fixes
- **fix: P2SH miner address displayed as P2PKH in logs and stats** — miners connecting with a P2SH address (e.g. `MLhSmVQ...`) were shown as a different P2PKH address (`LY2EoGp...`) in "New work for worker" log lines, `last_work_shares` stats keys, BENCH timing, and V35 `share_data['address']`. Root cause: `pubkey_hash_to_address()` was hardcoded to `ADDRESS_VERSION` (P2PKH version 48) instead of using `ADDRESS_P2SH_VERSION` (50) for P2SH addresses — same 20-byte hash, wrong version byte. Now uses `pubkey_type_to_version_witver()` to select the correct version. (`1c538aa`)
- **fix: P2SH address handling in merged chain conversion** — three additional locations in merged mining (operator fallback address, Dogecoin `createauxblock` payout address for both testnet and mainnet) were hardcoded to `ADDRESS_VERSION`, producing a P2PKH Dogecoin address (`Dxxx`) instead of a P2SH one (`9xxx`/`Axxx`) for P2SH miners. Added `_merged_addr_ver()` static helper that returns `ADDRESS_P2SH_VERSION` for P2SH pubkey types, `ADDRESS_VERSION` otherwise. Also removed a duplicate line that always overwrote P2SH→P2PKH in the merged payout lookup, silently breaking P2SH merged payouts. (`d6cdd40`)

---

## [v36-0.04-alpha] - 2026-02-27

### Features
- **feat: `--redistribute` system with 4 modes** — configurable policy for shares from unnamed/broken miners:
  - `pplns` (default) — proportional PPLNS weight distribution (original behavior)
  - `fee` — 100% to node operator
  - `boost` — inverse-weighted PPLNS favoring connected miners with zero shares in the window (helps tiny miners who are hashing but haven't found a share yet); falls back to `pplns` if no zero-share miners are connected
  - `donate` — 100% to donation script
  
  Event-driven cache invalidation for boost mode — zero CPU cost when no broken miners are present. (`de76224`, `7b9a3c7`, `7684fb4`)

### Dashboard UI
- **ui: Best Share card redesign** — hero percentage display with big bold integer + small decimal (`format_pct_fancy`), removed redundant difficulty numbers from record line, added network difficulty to subtitle (share_diff / net_diff for LTC · DOGE) (`499fd1b`, `763dfe9`, `0208810`)
- **ui: Share version counts in Shares card** — inline version format counts and desired version counts next to the big share number (e.g. `0  V35:8640 | want V35:7476 V36:1164`), color-coded green for target version, grey for old (`63d36ec`, `4d8fa44`, `e42b015`, `2db3a99`)
- **ui: Version Signaling block golden border + transition message** — golden (#f59e0b) pulsing glow border on version-signaling block, context-aware transition status message bar showing phase-specific text (building_chain, waiting, signaling, signaling_strong, activating, propagating) (`5526270`)
- **ui: Shares card transition glow** — amber pulsing border on Shares card when network is transitioning between share versions (`4d8fa44`)
- **fix: peer direction column wrapping** — `white-space: nowrap` on direction column prevents arrow + text wrapping to two lines (`6bfb2dc`)

### Performance
- **perf: load transition blobs once at startup** — blob directories and hardcoded blobs now load once instead of re-scanning, re-reading, re-decrypting, and re-verifying ECDSA every 5 minutes (`bee3b96`)

### Documentation
- **docs: FUTURE.md full refactor** — separated chain-agnostic sections from coin-specific parts, removed already-implemented features (belong in CHANGELOG), added C++ migration section for c2pool with architecture diagram and porting priority matrix, added share redistribution roadmap (graduated boost, hybrid mode, share-rate threshold, explicit opt-in, anti-gaming analysis) (`a0187d7`, `b7f4b05`)

---

## [v36-0.03-alpha] - 2026-02-26

### Bug Fixes
- **fix: DOGE donation display shows tiny value (0.11) instead of ≥1 DOGE** — `get_v36_merged_weights()` returns `total_weight` inclusive of donation, but the display code added `donation_weight` a second time, halving the apparent donation ratio. Fixed weight decomposition: `miner_weight = total_weight - donation_weight`. Also enforce DUST_THRESHOLD minimum (1 DOGE) in display to match actual coinbase builder (`ba457df`)
- **fix: miner page shows 0 blocks for comma-separated merged miners** — Stratum records merged miners as `LTC_ADDR,DOGE_ADDR` but `get_miner_payouts()` / `get_merged_miner_payouts()` only split on `.` `+` `_` `/`, never on comma. Added `.split(',')[0]` to all 6 address-matching locations in `web.py` and `work.py` (`3bee8d6`)
- **fix: block explorer link uses wrong hash on miners page** — `miners.html` used `pow_hash_hex` (scrypt PoW hash) for the chainz.cryptoid.info link, but the explorer expects the SHA256d block hash. Changed to `block.hash`; display text still shows truncated PoW hash with a tooltip showing both hashes (`4787873`)
- **fix: transition message not showing on nodes without ecdsa library** — ECDSA signature verification is required for authority messages; nodes missing `ecdsa`/`coincurve` now log a clear warning: `pypy -m pip install ecdsa`. The decryption-only fallback was removed as insecure (pubkeys are public constants, so anyone could forge an encrypted envelope). Install `ecdsa` to see transition messages (`a9135c0`)
- **fix: `git describe --tags` for lightweight tag version display** — Added `--tags` flag so lightweight tags (not just annotated) are recognized in version string (`8b678bd`)

### Improvements
- **feat: `--redistribute` flag for unnamed/broken miner shares** — Configurable redistribution policy for shares from miners with empty/invalid/broken stratum credentials. Four modes:
  - `pplns` (default) — proportional PPLNS weight distribution (original behavior)
  - `fee` — 100% to node operator
  - `boost` — give to active stratum miners with **zero** PPLNS shares (helps tiny miners who are hashing but haven't found a single share in the 8640-share window). Falls back to `pplns` if no zero-share miners connected.
  - `donate` — 100% to donation script
  
  Usage: `--redistribute boost`. Consensus-safe: only affects `pubkey_hash` stamped into shares on this node.

---

## [v36-0.02-alpha] - 2026-02-26

### Critical Fixes
- **fix: miner.html shows 0 blocks for inactive miners** - Restructured `loadMinerStats()` to always load payouts, graphs, and merged blocks regardless of miner active status; previously miners not connected to the viewing node saw an error page with no block history (`5e46adf`)
- **fix: miner.html auto-refresh JS errors** - Fixed 30-second auto-refresh referencing non-existent element IDs (`doa_rate`, `time_to_share`) causing `Cannot set properties of null` errors; updated to correct IDs (`doa_rate_inline`, `doa_rate_detail`, `efficiency_value`) (`5e46adf`)
- **fix: DOGE address missing from Active Miners table** - Auto-converted DOGE addresses now displayed for miners connecting with LTC-only address; exposed `merged_addresses` through stratum API → web API → frontend chain (`5e54852`)
- **fix: restore --coinbtext support in LTC coinbase** - Regression from jtoomim fork that broke parent chain coinbase text injection (`59ae3dd`)
- **fix: payout lookup comma split** - Split on comma for merged mining worker names in payout calculations (`93c3ed2`)
- **fix: comma-split bug in miner/miners pages** - Display both LTC & DOGE addresses correctly (`e18731a`)
- **fix: message TTL** - Tie to sharechain window, exempt transition signals; consistent 7x max_age in admission and pruning (`b8462a9`, `2b4b5f9`)

### Security
- **security: fix 6 MEDIUM audit findings** - M1 (localhost-only ban/unban), M4 (rate limiting), M5 (input validation), M8 (safe defaults), M14 (log sanitization), M16 (error handling) (`f2323e3`)
- **Security audit fixes** - H1 (localhost-only ban/unban), H2 (64KB POST limit), H4 (assert->raise), H8 (IPv6 crash) (`a95e418`)

### Dashboard UI
- **Best Share card compact layout** - LTC blue / DOGE gold inline display (`2b0b9e0`)
- **fix: double-v in version display** - Corrected `vv36` → `v36` (`ed23899`)
- **fix: username template format** - Changed to `<ltc_addr>,<doge_addr>.WORKER` matching log format (`259fe38`, `ed23899`)
- **fix: Workers/Miners decimal values** - Round to integers since graph data averages produce decimals (`7c9b013`)
- **Node Fee DOGE payout** - Always show DOGE payout in Node Fee card (`d9d1bd9`)
- **fix: NaN% DOA display** - Fix NaN% DOA and infinity Expected Share when no local miners connected (`9517513`)
- **Table initial display** - Show 10 initial entries in payouts, blocks, and peers tables (`e3e14a3`)
- **Explorer URLs reverted** - LTC back to chainz.cryptoid.info, DOGE back to dogechain.info (`6283786`)
- **Miners table enhancement** - Added currency symbols and merged payout column (`f43aee0`)
- **fix: GitHub links and version display** - Fixed links and version in web UI footers (`ef55b7f`)
- **Progress bar labels** - Embedded percentage labels inside all progress bars, fixed threshold marker overlap (`8fdd0f4`)

### V36 Transition System
- **Full-chain sharechain scan** - Accurate V36 vote counting across entire tracked chain (`7a5a308`)
- **Fix chain scan cap** - Cap at CHAIN_LENGTH, not full tracker history (`278e469`)
- **Full chain length for propagation** - Use full chain length (8640) for propagation target, not 90% (`5ccc4c6`)
- **Fix transition display** - Overall V36 stats, propagation tracking, clear stage messages (`edfcbb5`)
- **Fix transition blob loading** - Fix transition message blob loading and classic stat page display (`6564720`)
- **Authority announcements** - Add authority announcements to dashboard + blob builder + legacy dashboard (`d4067b9`, `457dbe1`)
- **Transition guide** - Comprehensive V36 transition guide with dashboard legend (`bd3fa8e`)

### MM Adapter Overhaul
- **Unified adapter** - Removed legacy `adapter_v2.py`, `adapter_legacy_DEPRECATED.py`, `config_v2.yaml`; single `adapter.py` with multiaddress mode (`2b50d7a`)
- **Log file support** - Added `--log-file` CLI flag and `logging.file` config option for file-based logging (`2b50d7a`)
- **Log spam suppression** - Demoted routine RPC/template/aiohttp.access logs to DEBUG; only new blocks, submissions, errors at INFO (`5f36ed0`)
- **Default coinbase text** - Changed `P2POOL_TAG` and adapter `DEFAULT_COINBASE_TEXT` to `"technocore"` (`2b50d7a`)

### Diagnostics & Logging
- **Merged mining diagnostic logging** - Added `[MERGED-DIAG]` prefixed logs for twin block debugging: parent block detection, merged work state, submission flow (`a9d7998`)
- **Startup checklist** - 7-point `MERGED MINING STARTUP CHECKLIST` printed on launch with parent/merged addresses, P2P broadcaster, fees, stratum format, coinbase text (`5eab5a2`, `6840b14`)
- **CHECK 3: actual DOGE address** - Shows converted Dogecoin address (not parent chain address) using dogecoin network module (`6840b14`)
- **CHECK 6: worker separator clarity** - Uses `<ltc_addr>,<doge_addr>` placeholders to avoid confusion with `_` worker separator (`6840b14`)
- **CHECK 7: coinbase text display** - Shows parent chain `--coinbtext` and merged chain fallback tag on startup (`6840b14`)
- **Log blob read errors** - Add `/msg/diag` endpoint for diagnostics (`7ebc7d1`)
- **Periodically reload blob dirs** - 5-minute debounce for blob directory reload (`6f30bbf`)
- **Rate-limit MWEB-SKIP logs** - Reduce log spam from MWEB skip messages (`a6c8353`)
- **Rate-limit merged address validation** - Log once per address instead of every request (`2b2f860`)
- **Source IP logging** - Add source IP to empty/invalid miner logs (`a7ba671`)

### Backend
- **Multiaddress merged mining support** - Mine with separate LTC and DOGE addresses
- **Share messaging protocol** - P2P share messaging implementation
- **Live share message ingestion** - Wire live share message ingestion + blob upload API (`e0295c7`)
- **--merged-operator-address** - Wire operator address for PPLNS fee (`a7ba671`)
- **DOGE best share tracking** - Track DOGE best share with round reset on DOGE block find (`7f9b0cc`)
- **Embedded transition blob** - Reliable loading on all nodes without external file (`1719af6`)
- **V36 bootstrap nodes** - Added 102.160.209.121 and 5.188.104.245 to BOOTSTRAP_ADDRS (`abc56d2`)

### Documentation
- **Worker name separators** - Clarified both `.` and `_` are valid worker separators in README and startup logs (`27f6b4a`)
- **Coinbase text documentation** - Clarified `--coinbtext` (parent chain scriptSig) vs `coinbase_text` (child chain OP_RETURN) (`2b50d7a`)

### Compatibility
- **PyPy 2.7 fix** - Replaced em-dash (U+2014) with ASCII `--` in startup checklist to avoid `UnicodeDecodeError` under PyPy 2.7 (`9640efd`)

---

## [v36-0.01-alpha] - 2026-02-22

- Initial V36 sharechain protocol with merged mining
