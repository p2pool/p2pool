# P2Pool Scrypt Testnet Addresses

## Litecoin Testnet Addresses

### Legacy Address (P2PKH)
```
mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h
```
- Compatible with all miners and wallets
- Faucet: https://testnet-faucet.com/ltc-testnet/

### P2SH-Segwit Address
```
QcVudrUyKGwqjk4KWadnXfbHgnMVHB1Lif
```
- Wrapped Segwit (starts with Q)
- Better compatibility with older wallets

### Bech32 (Native Segwit) - **RECOMMENDED**
```
tltc1qpkcpgwl24flh35mknlsf374x8ypqv7de6esjh4
```
- Native segwit format (starts with tltc1)
- Lowest transaction fees
- Best for MWEB support
- **Currently configured in start_p2pool_scrypt_testnet.sh**

## Dogecoin Testnet Address

### P2Pool Mining Address
```
nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB
```
- For Dogecoin merged mining payouts
- Faucet: https://testnet-faucet.com/doge-testnet/

### Additional Addresses
```
nfvmyQGupr3h1nALLmrXJwnJDqSuGbCAxW
nsNoCDxo4W55Z4b5UCcdmVnyju1WTnyzgK
```

## Getting Testnet Coins

### Litecoin Testnet Faucets
1. https://testnet-faucet.com/ltc-testnet/
2. https://testnet.litecointools.com/
3. https://ltc-testnet.com/faucet

### Dogecoin Testnet Faucets
1. https://testnet-faucet.com/doge-testnet/
2. https://shibe.technology/ (may support testnet)

## Wallet Commands

### Check Litecoin Balance
```bash
litecoin-cli -testnet getbalance
litecoin-cli -testnet listreceivedbyaddress 0 true
```

### Check Dogecoin Balance
```bash
/home/user0/bin/dogecoin-cli -testnet getbalance
/home/user0/bin/dogecoin-cli -testnet listreceivedbyaddress 0 true
```

### Generate New Addresses
```bash
# Litecoin - different types
litecoin-cli -testnet getnewaddress 'p2pool-mining' 'legacy'
litecoin-cli -testnet getnewaddress 'p2pool-mining' 'p2sh-segwit'
litecoin-cli -testnet getnewaddress 'p2pool-mining' 'bech32'

# Dogecoin
/home/user0/bin/dogecoin-cli -testnet getnewaddress 'p2pool-mining'
```

## Mining Configuration

The P2Pool instance is configured to use:
- **Primary chain**: Litecoin testnet (port 19332)
- **Merged mining**: Dogecoin testnet (port 44555)
- **Payout address**: tltc1qpkcpgwl24flh35mknlsf374x8ypqv7de6esjh4 (native segwit)
- **Worker port**: 9327
- **P2Pool port**: 9338

### Connect Miners
Point your Scrypt miner to:
```
stratum+tcp://192.168.80.182:9327
```

Username: Your Litecoin testnet address (for custom payouts)  
Password: x (or anything)

Example with cpuminer:
```bash
cpuminer -a scrypt -o stratum+tcp://192.168.80.182:9327 -u tltc1qpkcpgwl24flh35mknlsf374x8ypqv7de6esjh4 -p x
```

## Notes

- All addresses have 0 balance initially - request coins from faucets
- Native segwit (bech32) addresses are recommended for Litecoin
- Dogecoin will be merge-mined automatically alongside Litecoin
- Both blockchains are fully synced:
  - Litecoin testnet: block 4,476,250
  - Dogecoin testnet: block 21,431,556
