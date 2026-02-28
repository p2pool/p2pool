# Multiaddress Merged Mining Guide

## Overview

P2Pool now supports multiaddress merged mining with Dogecoin (or other auxpow-capable chains). This allows miners to receive payouts directly on both Litecoin AND Dogecoin without requiring the pool operator to distribute merged mining rewards.

## Prerequisites

- P2Pool server running with auxpow-capable Dogecoin daemon
- Mining software that supports Litecoin (scrypt algorithm)
- Litecoin testnet address
- Dogecoin testnet address

## Username Format

### Standard Format (Litecoin only)
```
litecoin_address
```
Example: `mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h`

### Multiaddress Format (Litecoin + Dogecoin)
```
litecoin_address,dogecoin_address
```
**Note**: We use `,` (comma) as the separator. This avoids conflicts with HTTP Basic Auth (`:`) and difficulty syntax (`+`).

Example: `mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB`

### With Worker Name
```
litecoin_address+dogecoin_address.worker_name
```
Example: `mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB.worker1`

Alternative format:
```
litecoin_address+dogecoin_address_worker_name
```
Example: `mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB_worker1`

## Miner Configuration Examples

### cpuminer / minerd

**Standard (Litecoin only):**
```bash
minerd -a scrypt -o stratum+tcp://192.168.80.182:9327 \
  -u mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h -p x
```

**Multiaddress (Litecoin + Dogecoin):**
```bash
minerd -a scrypt -o stratum+tcp://192.168.80.182:9327 \
  -u mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB -p x
```

**With worker name:**
```bash
minerd -a scrypt -o stratum+tcp://192.168.80.182:9327 \
  -u mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB.rig1 -p x
```

### cgminer / bfgminer

**Configuration file:**
```json
{
  "pools": [
    {
      "url": "stratum+tcp://192.168.80.182:9327",
      "user": "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB",
      "pass": "x"
    }
  ],
  "algorithm": "scrypt"
}
```

**Command line:**
```bash
cgminer --scrypt -o stratum+tcp://192.168.80.182:9327 \
  -u mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB -p x
```

## Difficulty Adjustment

You can still specify target difficulty after the addresses:

**With pseudoshare difficulty (+):**
```
litecoin_addr,dogecoin_addr+0.001
```

**With share difficulty (/):**
```
litecoin_addr,dogecoin_addr/32
```

**Both:**
```
litecoin_addr,dogecoin_addr+0.001/32
```

Example:
```bash
minerd -a scrypt -o stratum+tcp://192.168.80.182:9327 \
  -u mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB+0.001 -p x
```

## Address Requirements

### Litecoin Testnet
- **Legacy (P2PKH)**: Starts with `m` or `n`
- **P2SH**: Starts with `2` or `Q`
- **Bech32**: Starts with `tltc1` (native SegWit)

Example addresses:
- Legacy: `mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h`
- P2SH: `QcVudrUyKGwqjk4KWadnXfbHgnMVHB1Lif`
- Bech32: `tltc1qpkcpgwl24flh35mknlsf374x8ypqv7de6esjh4` (not currently supported)

### Dogecoin Testnet
- **P2PKH**: Starts with `n`

Example address:
- `nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB`

## Payout Behavior

### With Dogecoin Address
- **Litecoin rewards**: Paid to your Litecoin address via P2Pool share chain
- **Dogecoin rewards**: Paid directly to your Dogecoin address in merged mined blocks

### Without Dogecoin Address (Standard Mode)
- **Litecoin rewards**: Paid to your Litecoin address via P2Pool share chain
- **Dogecoin rewards**: Not distributed to miners (reverts to pool operator address)

## Verification

### Check Your Mining Status
Visit the P2Pool web interface:
```
http://192.168.80.182:9327/
```

### Check Console Output
When you submit shares, you should see:
```
Using miner dogecoin address: nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB
```

### Monitor Payouts
- **Litecoin**: Check shares on P2Pool web interface
- **Dogecoin**: Check your Dogecoin address on testnet block explorer

## Troubleshooting

### "Invalid address" Error
- Ensure addresses are for the correct network (testnet vs mainnet)
- Check address format (no extra spaces or characters)
- Verify comma separator between addresses

### Dogecoin Rewards Not Received
- Check if pool detected auxpow: Look for "Detected auxpow-capable merged mining daemon" in logs
- Verify your dogecoin address is valid for testnet (starts with 'n')
- Ensure block was actually solved (merged mining blocks are rare)

### Worker Name Not Showing
- Use dot notation: `ltc_addr,doge_addr.worker1`
- Or underscore: `ltc_addr,doge_addr_worker1`
- Check web interface for worker stats

## Testing on Testnet

### Get Testnet Coins

**Litecoin Testnet:**
- Faucet: https://testnet-faucet.com/ltc-testnet/
- Generate address: `litecoin-cli -testnet getnewaddress`

**Dogecoin Testnet:**
- Faucet: https://testnet-faucet.com/doge-testnet/
- Generate address: `dogecoin-cli -testnet getnewaddress`

### Quick Test Command
```bash
# Test with cpuminer (single thread, low intensity)
minerd -a scrypt -o stratum+tcp://192.168.80.182:9327 \
  -u mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB.test \
  -p x -t 1
```

## Production Deployment

### Mainnet Addresses

**Litecoin Mainnet:**
- Legacy: Starts with `L`
- P2SH: Starts with `M` or `3`
- Bech32: Starts with `ltc1`

**Dogecoin Mainnet:**
- P2PKH: Starts with `D`

### Example Mainnet Configuration
```bash
minerd -a scrypt -o stratum+tcp://pool.example.com:9327 \
  -u LYourLitecoinAddressHere,DYourDogecoinAddressHere.worker1 -p x
```

## Advanced Features

### Multiple Workers
Each worker can have different Dogecoin addresses:
```
Worker 1: ltc_addr1,doge_addr1.rig1
Worker 2: ltc_addr1,doge_addr2.rig2
Worker 3: ltc_addr2,doge_addr3.rig3
```

### Share Chain Distribution
In the future, P2Pool will support distributing Dogecoin rewards proportionally across multiple miners based on their share contributions, similar to how Litecoin rewards work.

Current behavior: Each miner gets their proportional Dogecoin payout based on their shares.

## Security Notes

1. **Validate Addresses**: Always double-check addresses before mining
2. **Test First**: Test on testnet before using mainnet addresses
3. **Backup Wallets**: Keep wallet backups of both chains
4. **Monitor Regularly**: Check both Litecoin and Dogecoin balances

## FAQ

**Q: Do I need to provide a Dogecoin address?**
A: No, it's optional. If you don't provide one, you'll only receive Litecoin rewards.

**Q: Can I use the same address for both chains?**
A: No, Litecoin and Dogecoin use different address formats. You need separate addresses.

**Q: How often will I receive Dogecoin payouts?**
A: Only when your pool solves a merged mined block that meets Dogecoin's difficulty target. This is less frequent than Litecoin payouts.

**Q: Does multiaddress mining affect my Litecoin earnings?**
A: No, Litecoin earnings work exactly the same as standard P2Pool mining.

**Q: Can I change my Dogecoin address without changing Litecoin address?**
A: Yes, just update the username in your miner configuration.

**Q: What happens if my Dogecoin address is invalid?**
A: The merged block submission will fail. Use valid addresses only.

## Support

For issues or questions:
1. Check P2Pool logs: `data/litecoin_testnet/debug.log`
2. Monitor console output for error messages
3. Verify both daemons are synced and running
4. Check GitHub issues: https://github.com/frstrtr/p2pool-dash

---

## ✅ Successfully Tested

**December 23, 2025** - Multiaddress merged mining successfully tested on Litecoin+Dogecoin testnet:

- **5 Dogecoin testnet blocks accepted** via AuxPOW merged mining
- Miner: cpuminer-multi (scrypt, ~25 kH/s)
- P2Pool running on Ubuntu 24.04 with PyPy 7.3.20
- Parent chain: Litecoin testnet (port 19332)
- Merged chain: Dogecoin testnet (port 44555)

Example successful submission:
```
Submitting Dogecoin auxpow block...
rpc_submitblock returned: None
Multiaddress merged block accepted!
```

---

**Last Updated**: December 23, 2025
**P2Pool Version**: v1.1.1+ with multiaddress merged mining support
**Networks Supported**: Litecoin + Dogecoin (mainnet and testnet)
**Status**: ✅ Tested and Working
