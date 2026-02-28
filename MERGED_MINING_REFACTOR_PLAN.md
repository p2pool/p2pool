# Merged Mining Refactoring Plan

## Current Implementation (getauxblock)

### How it works:
1. **Get Work**: P2Pool calls `getauxblock()` on merged chain (Dogecoin)
2. **Response**: Returns `{hash, target, chainid}`
3. **Coinbase**: P2Pool builds Litecoin coinbase with auxpow tree containing merged chain hashes
4. **Mining**: Miners work on Litecoin blocks
5. **Submit**: When block meets Dogecoin target, P2Pool calls `getauxblock(hash, auxpow_hex)` to submit

### Limitations:
- **Single payout address**: Dogecoin Core builds the coinbase transaction internally
- **Pool operator controls**: The merged coin (Dogecoin) payout goes to a single address
- **No per-miner payouts**: Miners get Litecoin payouts, but pool operator gets ALL Dogecoin rewards

## New Implementation (getblocktemplate with auxpow)

### How it works:
1. **Get Template**: P2Pool calls `getblocktemplate({"capabilities": ["auxpow"]})` on Dogecoin
2. **Response**: Returns full block template including:
   - `auxpow.chainid`: Chain ID (98 for Dogecoin)
   - `auxpow.target`: Target difficulty
   - `transactions[]`: List of transactions to include
   - `coinbasevalue`: Total coinbase reward
   - `height`, `previousblockhash`, etc.
3. **Build Coinbase**: P2Pool builds **TWO** coinbase transactions:
   - **Litecoin coinbase**: Contains auxpow tree (as before)
   - **Dogecoin coinbase**: Contains **multiple outputs** - one per miner based on share contribution
4. **Build Block**: P2Pool constructs complete Dogecoin block:
   - Block header with auxpow flag set
   - Transactions from template
   - Custom coinbase with multiple outputs
5. **Mining**: Miners work on Litecoin blocks (no change)
6. **Submit**: When block meets Dogecoin target, P2Pool:
   - Constructs complete Dogecoin block
   - Attaches auxpow proof (merkle path from Litecoin coinbase)
   - Calls `submitblock(block_hex)` to submit complete block

### Benefits:
- **Per-miner payouts**: Each miner gets separate Litecoin AND Dogecoin addresses
- **Trustless**: No pool operator custody of merged coin rewards
- **Proportional**: Dogecoin rewards distributed based on share contribution
- **Fair**: Same payout model for both chains

## Code Changes Required

### 1. Update `set_merged_work()` (work.py:87-98)

**Current:**
```python
@defer.inlineCallbacks
def set_merged_work(merged_url, merged_userpass):
    merged_proxy = jsonrpc.HTTPProxy(merged_url, dict(Authorization='Basic ' + base64.b64encode(merged_userpass)))
    while self.running:
        auxblock = yield deferral.retry('Error while calling merged getauxblock on %s:' % (merged_url,), 30)(merged_proxy.rpc_getauxblock)()
        self.merged_work.set(math.merge_dicts(self.merged_work.value, {auxblock['chainid']: dict(
            hash=int(auxblock['hash'], 16),
            target='p2pool' if auxblock['target'] == 'p2pool' else pack.IntType(256).unpack(auxblock['target'].decode('hex')),
            merged_proxy=merged_proxy,
        )}))
        yield deferral.sleep(1)
```

**New:**
```python
@defer.inlineCallbacks
def set_merged_work(merged_url, merged_userpass):
    merged_proxy = jsonrpc.HTTPProxy(merged_url, dict(Authorization='Basic ' + base64.b64encode(merged_userpass)))
    while self.running:
        # Request block template with auxpow capability
        template = yield deferral.retry('Error while calling merged getblocktemplate on %s:' % (merged_url,), 30)(
            merged_proxy.rpc_getblocktemplate
        )({"capabilities": ["auxpow"]})
        
        # Check if auxpow is supported (indicates modified Dogecoin)
        if 'auxpow' in template:
            chainid = template['auxpow']['chainid']
            target_hex = template['auxpow']['target']
            
            self.merged_work.set(math.merge_dicts(self.merged_work.value, {chainid: dict(
                template=template,  # Store full template
                hash=0,  # Will be computed from block header
                target=pack.IntType(256).unpack(target_hex.decode('hex')),
                merged_proxy=merged_proxy,
                multiaddress=True,  # Flag to indicate multiaddress support
            )}))
        else:
            # Fallback to getauxblock for standard merged mining
            auxblock = yield deferral.retry('Error while calling merged getauxblock on %s:' % (merged_url,), 30)(
                merged_proxy.rpc_getauxblock
            )()
            self.merged_work.set(math.merge_dicts(self.merged_work.value, {auxblock['chainid']: dict(
                hash=int(auxblock['hash'], 16),
                target='p2pool' if auxblock['target'] == 'p2pool' else pack.IntType(256).unpack(auxblock['target'].decode('hex')),
                merged_proxy=merged_proxy,
                multiaddress=False,
            )}))
        
        yield deferral.sleep(1)
```

### 2. Update Block Submission (work.py:475-495)

**Current:**
```python
df = deferral.retry('Error submitting merged block: (will retry)', 10, 10)(aux_work['merged_proxy'].rpc_getauxblock)(
    pack.IntType(256, 'big').pack(aux_work['hash']).encode('hex'),
    dash_data.aux_pow_type.pack(dict(
        merkle_tx=dict(
            tx=new_gentx,
            block_hash=header_hash,
            merkle_link=merkle_link,
        ),
        merkle_link=dash_data.calculate_merkle_link(hashes, index),
        parent_block_header=header,
    )).encode('hex'),
)
```

**New:**
```python
if aux_work.get('multiaddress'):
    # Build complete Dogecoin block for multiaddress support
    template = aux_work['template']
    
    # Build Dogecoin coinbase with multiple outputs (one per shareholder)
    dogecoin_coinbase = build_merged_coinbase(
        template=template,
        shareholders=current_shareholders,  # From share chain
        total_reward=template['coinbasevalue'],
    )
    
    # Build complete block
    dogecoin_block = build_merged_block(
        template=template,
        coinbase_tx=dogecoin_coinbase,
        auxpow=dict(
            merkle_tx=dict(
                tx=new_gentx,  # Litecoin coinbase
                block_hash=header_hash,
                merkle_link=merkle_link,
            ),
            merkle_link=dash_data.calculate_merkle_link(hashes, index),
            parent_block_header=header,
        )
    )
    
    # Submit complete block
    df = deferral.retry('Error submitting merged block: (will retry)', 10, 10)(
        aux_work['merged_proxy'].rpc_submitblock
    )(dogecoin_block.encode('hex'))
else:
    # Standard getauxblock submission (backward compatible)
    df = deferral.retry('Error submitting merged block: (will retry)', 10, 10)(
        aux_work['merged_proxy'].rpc_getauxblock
    )(
        pack.IntType(256, 'big').pack(aux_work['hash']).encode('hex'),
        dash_data.aux_pow_type.pack(dict(
            merkle_tx=dict(
                tx=new_gentx,
                block_hash=header_hash,
                merkle_link=merkle_link,
            ),
            merkle_link=dash_data.calculate_merkle_link(hashes, index),
            parent_block_header=header,
        )).encode('hex'),
    )
```

### 3. Add Helper Functions

**New file: `p2pool/merged_mining.py`**
```python
"""Helper functions for merged mining with multiaddress support"""

import dash_data
from p2pool.util import pack

def build_merged_coinbase(template, shareholders, total_reward):
    """
    Build Dogecoin coinbase transaction with multiple outputs
    
    Args:
        template: Block template from getblocktemplate
        shareholders: Dict of {address: share_fraction} from share chain
        total_reward: Total coinbase value from template
    
    Returns:
        Packed coinbase transaction
    """
    # Calculate output amounts based on share contribution
    outputs = []
    for address, fraction in shareholders.iteritems():
        amount = int(total_reward * fraction)
        outputs.append({
            'value': amount,
            'script': address_to_script(address),  # Need to implement
        })
    
    # Build coinbase transaction
    coinbase = {
        'version': 1,
        'tx_ins': [{
            'previous_output': None,  # Coinbase
            'sequence': 0xffffffff,
            'script': pack_coinbase_script(template['height']),
        }],
        'tx_outs': outputs,
        'lock_time': 0,
    }
    
    return dash_data.tx_type.pack(coinbase)

def build_merged_block(template, coinbase_tx, auxpow):
    """
    Build complete Dogecoin block with auxpow
    
    Args:
        template: Block template from getblocktemplate
        coinbase_tx: Packed coinbase transaction
        auxpow: Auxpow proof dict
    
    Returns:
        Complete packed block with auxpow
    """
    # Build block header
    header = {
        'version': template['version'],
        'previous_block': int(template['previousblockhash'], 16),
        'merkle_root': 0,  # Will calculate below
        'timestamp': template['curtime'],
        'bits': pack.IntType(32).unpack(template['bits']),
        'nonce': 0,  # From Litecoin block
    }
    
    # Build transaction list (coinbase + template transactions)
    transactions = [coinbase_tx]
    for tx in template['transactions']:
        transactions.append(tx['data'].decode('hex'))
    
    # Calculate merkle root
    merkle_root = dash_data.merkle_hash(transactions)
    header['merkle_root'] = merkle_root
    
    # Pack block
    block = {
        'header': header,
        'txs': transactions,
        'auxpow': auxpow,
    }
    
    return dash_data.block_type.pack(block)

def address_to_script(address):
    """Convert Dogecoin address to output script"""
    # Need to implement address decoding
    # For testnet addresses starting with 'n', this is P2PKH
    pass

def pack_coinbase_script(height):
    """Pack coinbase input script with height"""
    # BIP 34: Coinbase must contain block height
    return pack.IntType(32).pack(height)
```

## Implementation Plan

### Phase 1: Detection and Compatibility (1 hour)
- [x] Stop stock Dogecoin daemon
- [x] Start modified Dogecoin with auxpow support
- [x] Test `getblocktemplate({"capabilities": ["auxpow"]})`
- [x] Verify auxpow object in response
- [ ] Update `set_merged_work()` to detect auxpow capability
- [ ] Add fallback to getauxblock for backward compatibility

### Phase 2: Coinbase Building (2-3 hours)
- [ ] Create `p2pool/merged_mining.py` helper module
- [ ] Implement `build_merged_coinbase()` with shareholder outputs
- [ ] Implement address decoding for Dogecoin testnet addresses
- [ ] Test coinbase construction in isolation

### Phase 3: Block Building (2-3 hours)
- [ ] Implement `build_merged_block()` with template integration
- [ ] Implement auxpow attachment to Dogecoin block
- [ ] Calculate proper merkle root with transactions
- [ ] Test block construction in isolation

### Phase 4: Submission (1-2 hours)
- [ ] Update submission logic in `work.py` to handle multiaddress
- [ ] Implement `submitblock()` call instead of `getauxblock()`
- [ ] Add error handling for submission failures
- [ ] Test submission with regtest

### Phase 5: Integration Testing (2-3 hours)
- [ ] Start P2Pool with modified Dogecoin
- [ ] Connect test miner with both addresses
- [ ] Verify share chain tracking
- [ ] Verify block submission to both chains
- [ ] Verify payouts to multiple addresses

### Phase 6: Production Testing (ongoing)
- [ ] Deploy to testnet
- [ ] Monitor for issues
- [ ] Verify actual payouts
- [ ] Performance testing

## Total Estimated Time: 10-15 hours

## Risks and Mitigations

### Risk 1: Block Validation Failures
**Risk**: Dogecoin daemon rejects submitted blocks
**Mitigation**: Extensive testing on regtest before testnet deployment

### Risk 2: Merkle Root Calculation
**Risk**: Incorrect merkle root causes block rejection
**Mitigation**: Use existing P2Pool merkle calculation, verify against template

### Risk 3: Address Encoding
**Risk**: Incorrect address encoding causes unspendable outputs
**Mitigation**: Test address decoding separately, use known good addresses

### Risk 4: Backward Compatibility
**Risk**: Breaking existing getauxblock merged mining
**Mitigation**: Detect capability and fallback to old method

### Risk 5: Share Chain Synchronization
**Risk**: Share chain state not available when building merged block
**Mitigation**: Cache recent shareholder state, use snapshot

## Success Criteria

1. **Functional**: P2Pool successfully mines blocks on both Litecoin and Dogecoin
2. **Multiaddress**: Dogecoin blocks contain multiple outputs matching share distribution
3. **Performance**: No significant performance degradation
4. **Stability**: Runs for 24+ hours without errors
5. **Payouts**: Miners receive correct proportional payouts on both chains

## Current Status

- [x] Modified Dogecoin daemon built and running
- [x] Auxpow capability verified working
- [x] getblocktemplate with auxpow tested successfully
- [ ] P2Pool code refactoring (Phase 1-6)

## Next Steps

1. Update startup script to use auxpow Dogecoin daemon
2. Begin Phase 1: Detection and Compatibility
3. Document API differences for future reference
4. Create test cases for each phase
