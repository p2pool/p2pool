# Dogecoin Core Auxpow - Deployment Guide

## Build Environment Required

The testnet server (192.168.80.182) does not have build tools installed. To deploy the patched Dogecoin Core, you need:

### Option 1: Build on Local Machine

**Requirements:**
- Linux (Ubuntu 20.04+ or similar)
- Build tools: gcc, g++, make, autoconf, automake
- Libraries: boost, openssl, libevent, berkeley-db

**Steps:**
```bash
# 1. Clone the fork
git clone https://github.com/frstrtr/dogecoin-auxpow-gbt.git
cd dogecoin-auxpow-gbt
git checkout feature/getblocktemplate-auxpow

# 2. Install dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y build-essential libtool autotools-dev automake \
  pkg-config bsdmainutils python3 libssl-dev libevent-dev \
  libboost-system-dev libboost-filesystem-dev libboost-chrono-dev \
  libboost-test-dev libboost-thread-dev libdb-dev libdb++-dev

# 3. Build
./autogen.sh
./configure --without-gui --with-incompatible-bdb
make -j$(nproc)

# 4. Strip binaries (reduce size)
strip src/dogecoind src/dogecoin-cli

# 5. Create package
tar czf dogecoin-1.14.9-auxpow-linux64.tar.gz \
  src/dogecoind src/dogecoin-cli

# 6. Copy to testnet server
scp dogecoin-1.14.9-auxpow-linux64.tar.gz user0@192.168.80.182:/tmp/

# 7. Deploy on server
ssh user0@192.168.80.182 'bash -s' << 'DEPLOY'
cd /tmp
tar xzf dogecoin-1.14.9-auxpow-linux64.tar.gz
mkdir -p ~/bin-auxpow
cp src/dogecoind src/dogecoin-cli ~/bin-auxpow/
export PATH=~/bin-auxpow:$PATH

# Stop old version
~/bin/dogecoin-cli -testnet stop

# Start new version
~/bin-auxpow/dogecoind -testnet -daemon

sleep 5

# Test auxpow capability
~/bin-auxpow/dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}'
DEPLOY
```

### Option 2: Use GitHub Actions (CI/CD)

Add `.github/workflows/build.yml` to the Dogecoin fork:

```yaml
name: Build Dogecoin Auxpow

on:
  push:
    branches: [ feature/getblocktemplate-auxpow ]

jobs:
  build:
    runs-on: ubuntu-20.04
    steps:
      - uses: actions/checkout@v3
      
      - name: Install dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y build-essential libtool autotools-dev \
            automake pkg-config libssl-dev libevent-dev \
            libboost-system-dev libboost-filesystem-dev \
            libboost-chrono-dev libboost-test-dev libboost-thread-dev \
            libdb-dev libdb++-dev
      
      - name: Build
        run: |
          ./autogen.sh
          ./configure --without-gui --with-incompatible-bdb
          make -j$(nproc)
      
      - name: Package
        run: |
          strip src/dogecoind src/dogecoin-cli
          tar czf dogecoin-auxpow-linux64.tar.gz src/dogecoind src/dogecoin-cli
      
      - name: Upload artifact
        uses: actions/upload-artifact@v3
        with:
          name: dogecoin-auxpow-binaries
          path: dogecoin-auxpow-linux64.tar.gz
```

Then download the artifact from GitHub Actions and deploy manually.

### Option 3: Use Pre-built Docker Image

```bash
# Create Dockerfile in dogecoin-auxpow-gbt repo
cat > Dockerfile << 'DOCKER'
FROM ubuntu:20.04
RUN apt-get update && apt-get install -y \
  build-essential libtool autotools-dev automake pkg-config \
  libssl-dev libevent-dev libboost-all-dev libdb-dev libdb++-dev
WORKDIR /build
COPY . .
RUN ./autogen.sh && \
    ./configure --without-gui --with-incompatible-bdb && \
    make -j$(nproc)
RUN strip src/dogecoind src/dogecoin-cli
DOCKER

# Build and extract binaries
docker build -t dogecoin-auxpow .
docker create --name temp dogecoin-auxpow
docker cp temp:/build/src/dogecoind .
docker cp temp:/build/src/dogecoin-cli .
docker rm temp

# Copy to server
scp dogecoind dogecoin-cli user0@192.168.80.182:~/bin-auxpow/
```

## Testing Plan

Once binaries are deployed:

### 1. Verify Basic Functionality
```bash
# Check version
dogecoin-cli -testnet --version

# Check blockchain sync
dogecoin-cli -testnet getblockchaininfo

# Check help text
dogecoin-cli -testnet help getblocktemplate | grep -A5 auxpow
```

### 2. Test Auxpow Capability
```bash
# Standard getblocktemplate (backward compatibility)
dogecoin-cli -testnet getblocktemplate > /tmp/gbt-standard.json

# With auxpow capability
dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}' > /tmp/gbt-auxpow.json

# Compare
diff /tmp/gbt-standard.json /tmp/gbt-auxpow.json
```

### 3. Verify Response Fields
```bash
# Check for auxpow object
dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}' | jq '.auxpow'

# Verify chainid
dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}' | jq '.auxpow.chainid'

# Verify coinbasetxn is omitted
dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}' | jq 'has("coinbasetxn")'
```

### 4. Compare with createauxblock
```bash
# Create test address
TEST_ADDR=$(dogecoin-cli -testnet getnewaddress)

# Get createauxblock response
dogecoin-cli -testnet createauxblock $TEST_ADDR > /tmp/createauxblock.json

# Get getblocktemplate auxpow response
dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}' > /tmp/gbt-auxpow.json

# Compare chainid
echo "createauxblock chainid:"
jq -r '.chainid' /tmp/createauxblock.json
echo "getblocktemplate chainid:"
jq -r '.auxpow.chainid' /tmp/gbt-auxpow.json

# Compare height
echo "createauxblock height:"
jq -r '.height' /tmp/createauxblock.json
echo "getblocktemplate height:"
jq -r '.height' /tmp/gbt-auxpow.json
```

### 5. Performance Test
```bash
# Benchmark standard getblocktemplate
time for i in {1..100}; do
  dogecoin-cli -testnet getblocktemplate > /dev/null
done

# Benchmark auxpow getblocktemplate
time for i in {1..100}; do
  dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}' > /dev/null
done
```

## Expected Results

### Standard getblocktemplate Response
```json
{
  "version": 6422788,
  "previousblockhash": "...",
  "transactions": [...],
  "coinbaseaux": {...},
  "coinbasevalue": 10000000000,
  "coinbasetxn": {
    "data": "...",
    "txid": "...",
    "hash": "...",
    "depends": [],
    "fee": -10000000000,
    "sigops": 0,
    "weight": 600
  },
  "target": "...",
  "bits": "...",
  "height": 12345
}
```

### Auxpow getblocktemplate Response
```json
{
  "version": 6422788,
  "previousblockhash": "...",
  "transactions": [...],
  "coinbaseaux": {...},
  "coinbasevalue": 10000000000,
  "target": "...",
  "bits": "...",
  "height": 12345,
  "auxpow": {
    "chainid": 98,
    "target": "00000000ffff0000000000000000000000000000000000000000000000000000"
  }
}
```

**Key Differences:**
- ❌ No `coinbasetxn` field (P2Pool builds it)
- ✅ Has `auxpow` object with `chainid`
- ✅ Same `coinbasevalue` (reward amount)
- ✅ Same `transactions` array
- ✅ Same `coinbaseaux` (scriptSig data)

## Integration with P2Pool

Once testing is complete, integrate with P2Pool:

### Phase 1: Detection Layer
File: `p2pool/work.py`

```python
def supports_auxpow_getblocktemplate(rpc):
    """Check if Dogecoin supports getblocktemplate with auxpow"""
    try:
        # Try with auxpow capability
        result = rpc.getblocktemplate({'capabilities': ['auxpow']})
        # Check if auxpow object is present
        return 'auxpow' in result and 'chainid' in result.get('auxpow', {})
    except Exception as e:
        return False

def get_merged_mining_template(rpc, chain_name):
    """Get block template for merged mining"""
    if supports_auxpow_getblocktemplate(rpc):
        # Use trustless method
        template = rpc.getblocktemplate({'capabilities': ['auxpow']})
        return {
            'method': 'getblocktemplate',
            'chainid': template['auxpow']['chainid'],
            'height': template['height'],
            'bits': template['bits'],
            'previousblockhash': template['previousblockhash'],
            'coinbasevalue': template['coinbasevalue'],
            'transactions': template['transactions']
        }
    else:
        # Fall back to createauxblock (trusted)
        block = rpc.createauxblock(fallback_address)
        return {
            'method': 'createauxblock',
            'chainid': block['chainid'],
            'hash': block['hash'],
            'height': block['height']
        }
```

### Phase 2: Coinbase Builder
```python
def build_merged_coinbase(parent_coinbase, merged_templates):
    """
    Build coinbase for parent chain that includes P2Pool outputs
    and merged mining commitments
    """
    coinbase = parent_coinbase.copy()
    
    # Add merged mining commitments
    for chain_name, template in merged_templates.items():
        if template['method'] == 'getblocktemplate':
            # Build merkle root commitment
            commitment = build_auxpow_commitment(
                chainid=template['chainid'],
                block_hash=calculate_block_hash(template)
            )
            coinbase['scriptSig'] += commitment
    
    return coinbase
```

### Phase 3: Block Submission
```python
def submit_merged_block(parent_block, merged_templates):
    """Submit block to parent and child chains"""
    
    # Submit to parent chain (Litecoin)
    parent_hash = submit_to_litecoin(parent_block)
    
    # Extract auxpow proof from parent block
    auxpow = extract_auxpow_proof(parent_block, parent_hash)
    
    # Submit to child chains
    for chain_name, template in merged_templates.items():
        if template['method'] == 'getblocktemplate':
            # Build complete block with auxpow
            child_block = build_auxpow_block(
                template=template,
                auxpow=auxpow,
                coinbase=parent_block.coinbase
            )
            submit_block(template['rpc'], child_block)
```

## Troubleshooting

### Build Fails
- Check dependencies: `dpkg -l | grep -E 'boost|ssl|event|db'`
- Check autoconf: `autoconf --version`
- Try with system BDB: `./configure --without-gui` (remove --with-incompatible-bdb)

### Runtime Errors
- Check logs: `tail -f ~/.dogecoin/testnet3/debug.log`
- Check RPC: `dogecoin-cli -testnet getinfo`
- Check sync: `dogecoin-cli -testnet getblockchaininfo`

### Auxpow Not Working
- Verify commit: `cd ~/dogecoin-auxpow-gbt && git log --oneline -1`
- Check binary: `strings ~/bin-auxpow/dogecoind | grep auxpow`
- Test help: `dogecoin-cli -testnet help getblocktemplate | grep auxpow`

## Current Status

✅ **Completed:**
- Code implementation (436b09bb8)
- Fork created (frstrtr/dogecoin-auxpow-gbt)
- Tests written (3/5 pass)
- Documentation complete
- **Build successful locally** (v1.14.99.0-436b09bb8)
- Binaries created: dogecoind (6.1MB), dogecoin-cli (463KB)
- Packaged: /tmp/dogecoin-auxpow-testnet.tar.gz (3.3MB)

⏳ **Pending:**
- Deploy to compatible server (library dependencies)
- Test auxpow functionality
- Integrate with P2Pool

🔴 **Known Issue:**
- Library dependency mismatch on testnet server
- Requires: libboost_filesystem.so.1.83.0, libdb_cxx-5.3.so
- **Solution:** Use Docker build (see below) or deploy to Ubuntu 24.04 with matching libraries

## Build Complete ✅

```bash
Location: /tmp/dogecoin-auxpow-gbt/
Version:  v1.14.99.0-436b09bb8
Binary:   src/dogecoind (6.1MB stripped)
CLI:      src/dogecoin-cli (463KB stripped)
Package:  /tmp/dogecoin-auxpow-testnet.tar.gz (3.3MB)
```

**Test locally:**
```bash
cd /tmp/dogecoin-auxpow-gbt
./src/dogecoind -testnet -daemon
sleep 5
./src/dogecoin-cli -testnet getblocktemplate '{"capabilities":["auxpow"]}'
```

## Next Steps

1. **Set up build environment** (choose one):
   - Local Linux machine
   - GitHub Actions CI/CD
   - Docker container

2. **Build and package** binaries

3. **Deploy to testnet** server

4. **Run test suite** (see Testing Plan above)

5. **Integrate with P2Pool** (see Integration section above)

6. **Test live mining** on testnet

7. **Deploy to mainnet** after validation
