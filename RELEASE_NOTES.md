# v36-0.09-alpha Release Notes

**Release date:** 2026-03-01

## Highlights

### macOS (Intel) Support

P2Pool Merged Mining V36 now has full macOS (Intel) installation support. The new section in `INSTALL.md` provides a complete walkthrough:

- **Homebrew-based setup** — PyPy 2.7, autoconf/automake/libtool, and all Python dependencies installed via Homebrew and pip
- **Dependency compilation** — Step-by-step build of `scrypt` and `coincurve` (libsecp256k1) from source for PyPy on macOS
- **MM-Adapter** — Python 3 venv setup for the merged mining adapter bridge
- **Full merged mining** — LTC + DOGE merged mining launch commands with all required flags
- **Background service** — `launchd` plist template for running P2Pool as a macOS background service
- **Firewall notes** — Port configuration guidance for macOS firewall

Tested and verified on macOS 26.3 (x86_64, Intel Mac Pro) with full merged mining operational against LAN Litecoin and Dogecoin Core daemons.

### Documentation Improvements

- Replaced example-only placeholder values across all documentation, scripts, and test fixtures for consistency and clarity
- Updated `.gitignore` to cover local MM-Adapter configuration files
- 38 files updated across `docs/`, `scripts/`, `tests/`, `mm-adapter/`, `README.md`

## Platform Support

| Platform | Status |
|----------|--------|
| Ubuntu/Debian (bare metal) | ✅ Tested |
| Docker (Linux) | ✅ Tested |
| Windows 10/11 (WSL2) | ✅ Tested |
| **macOS (Intel)** | ✅ **NEW — Tested** |

## Upgrade Notes

No breaking changes. Drop-in replacement for v36-0.08-alpha.

## Full Changelog

See [CHANGELOG.md](CHANGELOG.md) for the complete change history.
