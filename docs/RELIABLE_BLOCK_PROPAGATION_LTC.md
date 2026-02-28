# Reliable Block Propagation for Litecoin + Dogecoin Merged Mining

## Overview

This feature implements parallel block broadcasting using native blockchain P2P connections and node discovery mechanisms. When p2pool finds a block (either on the parent chain Litecoin or merged mining chain Dogecoin), the block is broadcast to multiple peers simultaneously for faster network propagation.

## Architecture

### Parent Chain (Litecoin) - `NetworkBroadcaster`

The `NetworkBroadcaster` class (`p2pool/bitcoin/broadcaster.py`) handles parallel block propagation for the Litecoin parent chain:

1. **Bootstrap from Local Node**: On startup, discovers peers from the local Litecoin node via `getpeerinfo` RPC
2. **Independent Peer Database**: Maintains its own scored peer database, persisted to disk
3. **Protected Local Connection**: Never disconnects from the local Litecoin node
4. **TRUE PARALLEL Broadcast**: Sends blocks to ALL connected peers simultaneously via P2P `send_block()`
5. **Quality-Based Scoring**: Tracks peer reliability and adjusts scores based on connection success/failure

### Merged Mining Chain (Dogecoin) - `MergedMiningBroadcaster`

The `MergedMiningBroadcaster` class (`p2pool/bitcoin/merged_broadcaster.py`) handles block propagation for Dogecoin:

1. **RPC-Based Submission**: Merged mining blocks require auxpow proof, submitted via `submitblock` RPC
2. **Parallel RPC Endpoints**: Can submit to multiple Dogecoin nodes for redundancy
3. **Optional P2P Discovery**: Can discover peers from Dogecoin node for potential P2P announcements
4. **Fire-and-Forget**: Broadcast doesn't block the critical submission path

## Integration Points

### Node Class (`p2pool/node.py`)

```python
class Node(object):
    def __init__(self, ...):
        # Block broadcaster for parallel propagation (set externally)
        self.broadcaster = None
        # Merged mining broadcasters: {chainid: MergedMiningBroadcaster}
        self.merged_broadcasters = {}
```

### Main Initialization (`p2pool/main.py`)

The parent chain broadcaster is initialized after the node starts:

```python
# Initialize block broadcaster for parallel propagation
if not args.disable_broadcaster:
    broadcaster = NetworkBroadcaster(
        net=net.PARENT,
        coind=bitcoind,
        local_factory=factory,
        local_addr=(args.bitcoind_address, args.bitcoind_p2p_port),
        datadir_path=datadir_path,
        chain_name=net.PARENT.SYMBOL.lower()
    )
    yield broadcaster.start()
    node.broadcaster = broadcaster
```

### Work Processing (`p2pool/work.py`)

Block submission is enhanced to use the broadcasters:

**Parent Chain:**
```python
block_submission = helper.submit_block(
    dict(header=header, txs=[new_gentx] + other_transactions),
    False,
    self.node,
    broadcaster=self.node.broadcaster  # Parallel broadcast
)
```

**Merged Mining Chain:**
```python
# Fire parallel broadcast via merged broadcaster (non-blocking)
chainid = aux_work.get('chainid', 98)
if chainid in self.node.merged_broadcasters:
    bc = self.node.merged_broadcasters[chainid]
    bc_d = bc.broadcast_block(complete_block_hex, aux_work['hash'])
    bc_d.addErrback(lambda f: None)  # Ignore broadcaster errors
```

## Command-Line Options

```
--disable-broadcaster    Don't use the P2P block broadcaster for parallel 
                         block propagation (useful if having connectivity issues)
```

## Data Files

The broadcasters persist their peer databases to disk:

- **Litecoin**: `{datadir}/broadcaster_peers_litecoin.json`
- **Dogecoin**: `{datadir}/broadcaster_peers_dogecoin.json` (or `*_testnet.json`)

## Peer Scoring

Peers are scored on a 0-1000 scale:
- Initial score: 100 (bootstrapped) or 50 (discovered)
- Success: +10 points (capped at 1000)
- Failure: -20 points
- Peers below 10 points are removed
- Higher scored peers are preferred for connections

## Benefits

1. **Faster Block Propagation**: Parallel broadcast reaches more nodes quickly
2. **Reduced Orphan Risk**: Quick propagation means less chance of another miner finding a competing block
3. **Network Resilience**: Multiple broadcast paths ensure block gets out even if some peers are slow
4. **Independent from Local Node**: Broadcaster maintains its own peer connections

## Merged Mining Specifics

For Dogecoin merged mining:
- Blocks are submitted via `submitblock` RPC (not P2P) because they contain auxpow proof
- The broadcaster primarily provides redundant RPC submission to multiple Dogecoin nodes
- P2P peer discovery can be used for monitoring or future P2P block announcement

## Troubleshooting

### Broadcaster Not Starting
Check the logs for initialization errors. Common issues:
- Unable to connect to local node's P2P port
- Firewall blocking outbound P2P connections

### High Failure Rate
If seeing many broadcast failures:
1. Check network connectivity
2. Verify P2P ports are correct (Litecoin: 9333, Dogecoin: 22556)
3. Consider using `--disable-broadcaster` if issues persist

### Memory Usage
The broadcaster maintains connections to multiple peers. If memory is a concern:
- Peer database is periodically pruned
- Low-scoring peers are automatically removed

## Future Improvements

1. **Web Stats Endpoint**: Add `/broadcaster_stats` API endpoint
2. **P2P Block Announcements for Merged Mining**: Send inv messages to Dogecoin peers
3. **Compact Block Relay**: Use BIP152 compact blocks for faster propagation
4. **Dynamic Peer Limits**: Auto-adjust based on available resources
