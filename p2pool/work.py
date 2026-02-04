from __future__ import division
from collections import deque

import base64
import os
import random
import re
import sys
import time

from twisted.internet import defer, reactor
from twisted.python import log

from bitcoin import getwork, data as bitcoin_data, helper, script, worker_interface
from bitcoin.merged_broadcaster import MergedMiningBroadcaster
from util import forest, jsonrpc, variable, deferral, math, pack
import p2pool, p2pool.data as p2pool_data
from p2pool import merged_mining

# Import merged chain networks for address conversion
# These are used when converting pubkey_hash from share chain to merged chain addresses
try:
    from p2pool.bitcoin.networks import dogecoin_testnet as dogecoin_testnet_net
    print >>sys.stderr, '[IMPORT] Successfully imported dogecoin_testnet: %s' % dogecoin_testnet_net
except ImportError as e:
    print >>sys.stderr, '[IMPORT] Failed to import dogecoin_testnet: %s' % e
    dogecoin_testnet_net = None
try:
    from p2pool.bitcoin.networks import dogecoin as dogecoin_net
    print >>sys.stderr, '[IMPORT] Successfully imported dogecoin: %s' % dogecoin_net
except ImportError as e:
    print >>sys.stderr, '[IMPORT] Failed to import dogecoin: %s' % e
    dogecoin_net = None

print_throttle = 0.0

def is_pubkey_hash_address(address, net):
    """
    Check if an address contains a pubkey hash that can be converted to merged chain addresses.
    
    =================================================================================
    MERGED MINING ADDRESS CONVERSION - TECHNICAL EXPLANATION
    =================================================================================
    
    When P2Pool performs merged mining (e.g., Litecoin + Dogecoin), miner payouts need
    to be distributed on BOTH chains. However, miners only provide a Litecoin address.
    
    To create the Dogecoin payout address, we extract the pubkey_hash from the Litecoin
    address and re-encode it with the Dogecoin address version. This ONLY works for
    addresses that contain a raw pubkey_hash:
    
    CONVERTIBLE ADDRESS TYPES:
    --------------------------
    1. P2PKH (Pay-to-Public-Key-Hash) - Legacy addresses
       - Litecoin: starts with 'L' (mainnet) or 'm/n' (testnet)
       - Format: Base58Check(version || HASH160(pubkey))
       - The 20-byte HASH160(pubkey) can be extracted and re-encoded for Dogecoin
       - Example: LTC 'LbxJe7Nf59gv2vK7Mw8kEa6aWFDHjwsf2E' -> DOGE 'DCo7...'
    
    2. P2WPKH (Pay-to-Witness-Public-Key-Hash) - Native SegWit v0
       - Litecoin: starts with 'ltc1q' followed by 39 more chars (43 total)
       - Format: Bech32(hrp, version=0, witness_program=HASH160(pubkey))
       - The 20-byte witness program IS the pubkey_hash
       - Example: LTC 'ltc1qna9n6gs...' (43 chars) -> DOGE 'D...'
    
    NON-CONVERTIBLE ADDRESS TYPES (contain script hashes, NOT pubkey hashes):
    -------------------------------------------------------------------------
    3. P2SH (Pay-to-Script-Hash) - Legacy script addresses
       - Litecoin: starts with 'M' or '3' (mainnet) or '2' (testnet)
       - Format: Base58Check(p2sh_version || HASH160(script))
       - The hash is of a SCRIPT, not a public key - CANNOT be safely converted!
       - Used for: multisig, SegWit-wrapped addresses, complex scripts
    
    4. P2WSH (Pay-to-Witness-Script-Hash) - Native SegWit script addresses
       - Litecoin: starts with 'ltc1q' followed by ~59 more chars (62 total)
       - Format: Bech32(hrp, version=0, witness_program=SHA256(script))
       - The 32-byte witness program is a SHA256 hash of a script
       - WARNING: These look similar to P2WPKH but are LONGER (62 vs 43 chars)
       - CANNOT be converted - the script exists only on the parent chain!
    
    5. P2TR (Pay-to-Taproot) - Taproot addresses (witness v1)
       - Litecoin: starts with 'ltc1p...'
       - Format: Bech32m(hrp, version=1, tweaked_pubkey)
       - Contains a 32-byte tweaked public key, not a simple hash
       - CANNOT be safely converted
    
    WHY P2SH/P2WSH CANNOT BE CONVERTED:
    -----------------------------------
    These addresses are hashes of SCRIPTS (smart contracts), not public keys.
    The underlying script (e.g., "2-of-3 multisig with keys A, B, C") only exists
    on the parent chain. Creating a Dogecoin address from the script hash would
    result in an address that NO ONE can spend from, because the script doesn't
    exist on Dogecoin.
    
    P2WPKH vs P2WSH DETECTION:
    --------------------------
    Both P2WPKH and P2WSH use witness version 0 and start with 'ltc1q'.
    The difference is the witness program length:
    - P2WPKH: 20 bytes (HASH160) -> 43 character address
    - P2WSH:  32 bytes (SHA256)  -> 62 character address
    
    We detect this by checking if the pubkey_hash value exceeds 2^160-1.
    A legitimate 20-byte hash will never exceed this, while a 32-byte hash
    almost certainly will (probability of false negative: 1 in 2^96).
    
    REDISTRIBUTION OF UNCONVERTIBLE SHARES:
    ---------------------------------------
    When an address cannot be converted, that miner's share of the merged
    mining reward is redistributed proportionally to all convertible addresses,
    EXCLUDING the primary donation (author fee). This ensures:
    1. 100% of the merged block reward is distributed
    2. Miners with convertible addresses get slightly more DOGE
    3. The author donation doesn't unfairly benefit from unconvertible addresses
    
    Returns: (is_convertible, pubkey_hash, error_message)
    - is_convertible: True if address can be converted to merged chain
    - pubkey_hash: The 160-bit hash (int) if convertible, None otherwise
    - error_message: Human-readable error if not convertible, None otherwise
    =================================================================================
    """
    try:
        pubkey_hash, version, witver = bitcoin_data.address_to_pubkey_hash(address, net)
        
        # Check for P2SH (script hash, not pubkey hash)
        if version == net.ADDRESS_P2SH_VERSION:
            return (False, None, 'P2SH address (script hash) cannot be converted to merged chain')
        
        # Check for P2WPKH vs P2WSH (both are witness v0, but different lengths)
        if witver == 0:
            # Witness v0: P2WPKH is 20 bytes (max value 2^160-1), P2WSH is 32 bytes (max value 2^256-1)
            # A 32-byte value will always be > 2^160-1 if any of the upper 12 bytes are non-zero
            # This is a probabilistic check - a P2WSH hash that happens to have all upper
            # 12 bytes as zero would pass, but this is astronomically unlikely (1 in 2^96)
            if pubkey_hash > (1 << 160) - 1:  # Larger than 20 bytes can represent
                return (False, None, 'P2WSH address (32-byte script hash) cannot be converted to merged chain')
            else:
                return (True, pubkey_hash, None)  # P2WPKH - convertible
        
        # Check for Taproot (witness v1) - not convertible (32-byte tweaked pubkey)
        if witver == 1:
            return (False, None, 'P2TR address (taproot) cannot be converted to merged chain')
        
        # Higher witness versions (future segwit) - not convertible for safety
        if witver > 1:
            return (False, None, 'Unknown witness version %d - cannot convert to merged chain' % witver)
        
        # P2PKH (legacy) - convertible
        if version == net.ADDRESS_VERSION:
            return (True, pubkey_hash, None)
        
        # Unknown address type
        return (False, None, 'Unknown address type (version=%s, witver=%s)' % (version, witver))
        
    except Exception as e:
        return (False, None, 'Failed to parse address: %s' % str(e))

class WorkerBridge(worker_interface.WorkerBridge):
    COINBASE_NONCE_LENGTH = 8

    def __init__(self, node, my_pubkey_hash, donation_percentage, merged_urls, worker_fee, args, pubkeys, bitcoind, share_rate):
        worker_interface.WorkerBridge.__init__(self)
        self.recent_shares_ts_work = []

        self.node = node

        self.bitcoind = bitcoind
        self.pubkeys = pubkeys
        self.args = args
        self.my_pubkey_hash = my_pubkey_hash
		
        self.donation_percentage = args.donation_percentage
        self.worker_fee = args.worker_fee
        self.merged_operator_address = getattr(args, 'merged_operator_address', None)


        self.net = self.node.net.PARENT
        self.running = True
        self.pseudoshare_received = variable.Event()
        self.share_received = variable.Event()
        self.block_found = variable.Event()  # Fired when a parent network block is found
        # Activity window must account for extreme variance in low-difficulty mining
        # At minimum difficulty (0.001), miners can have very long gaps between shares
        # due to Poisson distribution variance (95% CI = ~30x expected time)
        # Formula: 100 * STRATUM_SHARE_RATE gives safe margin for variance
        # For mainnet: 100 * 10 sec = 1000 seconds (~16.7 minutes)
        # This keeps count stable while still being responsive to real disconnects
        stratum_share_rate = getattr(self.node.net, 'STRATUM_SHARE_RATE', 10)  # Default 10 seconds if not defined
        activity_window = 100 * stratum_share_rate
        self.local_rate_monitor = math.RateMonitor(activity_window)
        self.local_addr_rate_monitor = math.RateMonitor(activity_window)
        
        # Track best difficulty per miner (all-time and session)
        # Format: {user: {'all_time': diff, 'session': diff, 'session_start': timestamp}}
        self.miner_best_difficulty = {}
        self.session_start_time = time.time()

        self.removed_unstales_var = variable.Variable((0, 0, 0))
        self.removed_doa_unstales_var = variable.Variable(0)

        self.last_work_shares = variable.Variable( {} )

        self.my_share_hashes = set()
        self.my_doa_share_hashes = set()
        
        # Track recently found merged mined blocks
        self.recent_merged_blocks = []

        self.address_throttle = 0
        self.address = None  # Dynamic address, set later if --dynamic-address used
        self.share_rate = args.share_rate  # Stratum vardiff target (seconds per pseudoshare)

        self.tracker_view = forest.TrackerView(self.node.tracker, forest.get_attributedelta_type(dict(forest.AttributeDelta.attrs,
            my_count=lambda share: 1 if share.hash in self.my_share_hashes else 0,
            my_doa_count=lambda share: 1 if share.hash in self.my_doa_share_hashes else 0,
            my_orphan_announce_count=lambda share: 1 if share.hash in self.my_share_hashes and share.share_data['stale_info'] == 'orphan' else 0,
            my_dead_announce_count=lambda share: 1 if share.hash in self.my_share_hashes and share.share_data['stale_info'] == 'doa' else 0,
        )))

        @self.node.tracker.verified.removed.watch
        def _(share):
            if share.hash in self.my_share_hashes and self.node.tracker.is_child_of(share.hash, self.node.best_share_var.value):
                assert share.share_data['stale_info'] in [None, 'orphan', 'doa'] # we made these shares in this instance
                self.removed_unstales_var.set((
                    self.removed_unstales_var.value[0] + 1,
                    self.removed_unstales_var.value[1] + (1 if share.share_data['stale_info'] == 'orphan' else 0),
                    self.removed_unstales_var.value[2] + (1 if share.share_data['stale_info'] == 'doa' else 0),
                ))
            if share.hash in self.my_doa_share_hashes and self.node.tracker.is_child_of(share.hash, self.node.best_share_var.value):
                self.removed_doa_unstales_var.set(self.removed_doa_unstales_var.value + 1)

        # MERGED WORK

        self.merged_work = variable.Variable({})

        @defer.inlineCallbacks
        def set_merged_work(merged_url, merged_userpass, merged_payout_address=None):
            merged_proxy = jsonrpc.HTTPProxy(merged_url, dict(Authorization='Basic ' + base64.b64encode(merged_userpass)))
            
            # Initialize merged broadcaster for this chain (once per URL)
            # We'll determine the chainid from the first successful response
            merged_broadcaster = None
            broadcaster_initialized = False
            
            # Try to detect auxpow capability on first call
            auxpow_capable = None
            
            while self.running:
                try:
                    # First, try getblocktemplate with auxpow capability (multiaddress support)
                    if auxpow_capable is None or auxpow_capable:
                        template = yield deferral.retry('Error while calling merged getblocktemplate on %s:' % (merged_url,), 30)(
                            merged_proxy.rpc_getblocktemplate
                        )({"capabilities": ["auxpow"]})
                        
                        # Check if auxpow is supported (modified Dogecoin with multiaddress)
                        if 'auxpow' in template:
                            if auxpow_capable is None:
                                print 'Detected auxpow-capable merged mining daemon at %s (multiaddress support enabled)' % (merged_url,)
                            auxpow_capable = True
                            
                            chainid = template['auxpow']['chainid']
                            target_hex = template['auxpow']['target']
                            
                            # Initialize merged broadcaster for this chain (once)
                            if not broadcaster_initialized and chainid not in self.node.merged_broadcasters:
                                try:
                                    # Determine chain name and network for logging/P2P
                                    chain_name = 'dogecoin' if chainid == 98 else 'merged_%d' % chainid
                                    parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                                    
                                    # Select correct P2P network for the merged chain
                                    p2p_net = None
                                    p2p_port = None
                                    local_p2p_addr = None
                                    
                                    if chainid == 98:  # Dogecoin
                                        if parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower():
                                            chain_name = 'dogecoin_testnet'
                                            p2p_net = dogecoin_testnet_net
                                            p2p_port = 44556 if dogecoin_testnet_net else None
                                        else:
                                            p2p_net = dogecoin_net
                                            p2p_port = 22556 if dogecoin_net else None
                                        
                                        # Get local Dogecoin node's P2P address from args
                                        merged_p2p_port = getattr(self.args, 'merged_coind_p2p_port', None)
                                        merged_address = getattr(self.args, 'merged_coind_address', None)
                                        if merged_p2p_port and merged_address:
                                            local_p2p_addr = (merged_address, merged_p2p_port)
                                            print 'MergedBroadcaster will connect to our Dogecoin node at %s:%d' % (merged_address, merged_p2p_port)
                                    
                                    # Compute datadir_path for peer database storage
                                    # Use same logic as main.py: default to data/<net_name> or args.datadir/<net_name>
                                    net_name = self.node.net.NAME
                                    if hasattr(self.args, 'datadir') and self.args.datadir:
                                        datadir_path = os.path.join(self.args.datadir, net_name)
                                    else:
                                        datadir_path = os.path.join(os.path.dirname(sys.argv[0]), 'data', net_name)
                                    
                                    merged_broadcaster = MergedMiningBroadcaster(
                                        merged_proxy=merged_proxy,
                                        merged_url=merged_url,
                                        datadir_path=datadir_path,
                                        chain_name=chain_name,
                                        p2p_net=p2p_net,
                                        p2p_port=p2p_port,
                                        local_p2p_addr=local_p2p_addr,
                                    )
                                    yield merged_broadcaster.start()
                                    self.node.merged_broadcasters[chainid] = merged_broadcaster
                                    print 'Merged broadcaster started for chainid %d (%s) P2P=%s local=%s' % (
                                        chainid, chain_name, 
                                        'enabled' if p2p_net else 'disabled',
                                        '%s:%d' % local_p2p_addr if local_p2p_addr else 'none')
                                except Exception as e:
                                    print >>sys.stderr, 'Failed to start merged broadcaster: %s' % e
                                broadcaster_initialized = True
                            
                            # PHASE A: Build complete Dogecoin block to get its hash for merged mining commitment
                            # This is the key to resolving the "chicken-and-egg" problem:
                            # We build the Dogecoin block FIRST, before the Litecoin block
                            try:
                                from p2pool import merged_mining
                                
                                # Step 1-2: Build Dogecoin coinbase and transactions, calculate merkle root
                                doge_tx_hashes = [int(tx['hash'], 16) for tx in template.get('transactions', [])]
                                
                                # Build merged mining coinbase with P2Pool PPLNS shareholder distribution
                                # Use the share chain to calculate proper payouts (same as parent chain)
                                #
                                # ADDRESS CONVERSION STRATEGY:
                                # Miners' merged chain addresses are auto-converted from their pubkey_hash
                                # using the merged chain's address format (e.g., Litecoin → Dogecoin encoding).
                                # This works because:
                                # - Share chain stores pubkey_hash (160-bit, network-agnostic)
                                # - Same private key controls addresses on both chains
                                # - Auto-conversion: pubkey_hash → chain-specific address encoding
                                #
                                # DISCRETE PER-CHAIN ADDRESSES:
                                # To support truly independent addresses per chain would require:
                                # 1. Protocol change: Add 'merged_addresses' field to share_data_type
                                # 2. Network consensus: All nodes must understand new share format
                                # 3. Share type version bump: Backward compatibility migration
                                # 4. Storage overhead: Each share grows with per-chain address data
                                # Current approach (auto-conversion) avoids protocol changes and works
                                # for 99% of use cases where miners control same keys across chains.
                                previous_share = self.node.tracker.items.get(self.node.best_share_var.value) if self.node.best_share_var.value is not None else None
                                
                                # Initialize variables in case of exception
                                weights = {}
                                total_weight = 0
                                donation_weight = 0
                                shareholders = {}
                                
                                # Skip PPLNS when there are no previous shares (bootstrap phase)
                                # Allow previous_share_hash to be None - get_cumulative_weights handles it
                                try:
                                    if (previous_share is not None and 
                                        hasattr(previous_share, 'share_data')):
                                        # Get PPLNS weights from share chain
                                        # Use best_share_hash directly (not grandparent) - merged mining should
                                        # include all current shareholders, unlike generate_transaction which
                                        # excludes the finder of the new share being generated.
                                        target = int(target_hex, 16)
                                        best_share_hash = self.node.best_share_var.value
                                        share_height = self.node.tracker.get_height(best_share_hash)
                                        weights, total_weight, donation_weight = self.node.tracker.get_cumulative_weights(
                                            best_share_hash,  # Use best share, not grandparent
                                            max(0, min(share_height, self.node.net.REAL_CHAIN_LENGTH)),
                                            65535 * self.node.net.SPREAD * bitcoin_data.target_to_average_attempts(target),
                                        )
                                    
                                    # Determine the correct merged chain network for address conversion
                                    # We detect based on chainid: Dogecoin chainid = 98 (0x62)
                                    # This converts pubkey_hash from share chain to merged chain address format
                                    if chainid == 98:  # Dogecoin
                                        # Use Dogecoin testnet or mainnet based on parent chain
                                        # Check for 't' prefix in symbol (e.g., tLTC) or 'test' in name
                                        parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                                        is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
                                        if is_testnet:
                                            merged_addr_net = dogecoin_testnet_net
                                        else:
                                            merged_addr_net = dogecoin_net
                                        if merged_addr_net is None:
                                            print >>sys.stderr, '[MERGED] Warning: Dogecoin network module not available, using parent chain addresses'
                                            merged_addr_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                    else:
                                        # Unknown chain - fallback to parent network (may produce wrong addresses!)
                                        merged_addr_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                    
                                    # Convert weights (address/script -> weight) to shareholders (merged_address -> fraction)
                                    # In VERSION >= 34, the key is an address string (from share.address)
                                    # In older versions, the key is a P2PKH script that needs conversion
                                    shareholders = {}
                                    skipped_addresses = []
                                    for key, weight in weights.iteritems():
                                        try:
                                            # Check if key is already an address string (VERSION >= 34)
                                            # Address strings are alphanumeric and 25-35 chars for base58, or longer for bech32
                                            # Script bytes would have non-printable characters
                                            key_is_address = len(key) >= 25 and len(key) <= 100 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' for c in key)
                                            
                                            if key_is_address:
                                                # VERSION >= 34: key is already a parent chain address string
                                                # Need to convert to merged chain address
                                                parent_address = key
                                                parent_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                                
                                                # CRITICAL: Validate that address contains a pubkey hash (not script hash)
                                                # P2SH, P2WSH, P2TR addresses CANNOT be converted to merged chain!
                                                is_convertible, pubkey_hash, error_msg = is_pubkey_hash_address(parent_address, parent_net)
                                                
                                                if not is_convertible:
                                                    # Cannot convert this address - skip it with warning
                                                    skipped_addresses.append((parent_address[:20] + '...', error_msg))
                                                    continue
                                                
                                                # Re-encode as merged chain address
                                                merged_address = bitcoin_data.pubkey_hash_to_address(pubkey_hash, merged_addr_net.ADDRESS_VERSION, -1, merged_addr_net)
                                            else:
                                                # Older VERSION: key is P2PKH script
                                                merged_address = bitcoin_data.script2_to_address(key, merged_addr_net.ADDRESS_VERSION, -1, merged_addr_net)
                                            
                                            fraction = float(weight) / float(total_weight) if total_weight > 0 else 0
                                            shareholders[merged_address] = fraction
                                        except Exception as e:
                                            pass  # Suppressed: print >>sys.stderr, '[MERGED] Warning: Could not convert key to address: %s' % e
                                    
                                    if skipped_addresses:
                                        # Summary only - suppress verbose per-address output
                                        pass  # Suppressed verbose output: print >>sys.stderr, '[MERGED] WARNING: %d miner address(es) skipped' % len(skipped_addresses)
                                    
                                    pass  # Suppressed: print >>sys.stderr, '[MERGED] Using PPLNS distribution with %d shareholders from share chain' % len(shareholders)
                                except (KeyError, AttributeError, TypeError) as e:
                                    # Fall back to single address mode if PPLNS calculation fails
                                    # This is expected during bootstrap when share chain is empty or incomplete
                                    previous_share = None  # Force fallback path
                                
                                if previous_share is None:
                                    # Fallback: No shares yet or PPLNS failed, use single address mode
                                    # Need to convert to merged chain address format
                                    pass  # Suppressed: print >>sys.stderr, '[MERGED] Entering no-shares fallback path, chainid=%s' % chainid
                                    if chainid == 98:  # Dogecoin
                                        # Check for 't' prefix in symbol (e.g., tLTC) or 'test' in name
                                        parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                                        is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
                                        if is_testnet:
                                            merged_addr_net = dogecoin_testnet_net
                                            pass  # Suppressed: print >>sys.stderr, '[MERGED] FALLBACK: Set merged_addr_net = dogecoin_testnet_net: %s' % merged_addr_net
                                        else:
                                            merged_addr_net = dogecoin_net
                                            pass  # Suppressed: print >>sys.stderr, '[MERGED] FALLBACK: Set merged_addr_net = dogecoin_net: %s' % merged_addr_net
                                        if merged_addr_net is None:
                                            merged_addr_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                            pass  # Suppressed: print >>sys.stderr, '[MERGED] FALLBACK: merged_addr_net was None, using parent: %s' % merged_addr_net
                                        pass  # Suppressed: print >>sys.stderr, '[MERGED] FALLBACK: Final merged_addr_net: SYMBOL=%s, ADDRESS_VERSION=%d' % (merged_addr_net.SYMBOL, merged_addr_net.ADDRESS_VERSION)
                                    else:
                                        merged_addr_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                        print >>sys.stderr, '[MERGED] FALLBACK: Using parent chain (unknown chainid): %s' % merged_addr_net
                                    
                                    mining_address = getattr(self.args, 'address', None)
                                    if not mining_address and self.my_pubkey_hash:
                                        # Convert pubkey_hash to merged chain address
                                        mining_address = bitcoin_data.pubkey_hash_to_address(
                                            self.my_pubkey_hash, merged_addr_net.ADDRESS_VERSION,
                                            -1, merged_addr_net)
                                    shareholders = {mining_address: 1.0} if mining_address else {}
                                    pass  # Suppressed: print >>sys.stderr, '[MERGED] No share chain yet, using single address: %s' % mining_address
                                
                                # Setup merged chain network for address operations
                                # Must be done BEFORE node operator address handling
                                if chainid == 98:  # Dogecoin
                                    # Check for 't' prefix in symbol (e.g., tLTC) or 'test' in name
                                    parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                                    is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
                                    if is_testnet:
                                        merged_addr_net = dogecoin_testnet_net
                                    else:
                                        merged_addr_net = dogecoin_net
                                    if merged_addr_net is None:
                                        merged_addr_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                else:
                                    merged_addr_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                
                                # Determine node operator address for merged chain
                                # Priority: 1) --merged-operator-address, 2) convert parent pubkey_hash to merged chain
                                node_operator_address = None
                                if self.my_pubkey_hash and self.worker_fee > 0:
                                    if self.merged_operator_address:
                                        # Use explicitly provided merged chain address
                                        node_operator_address = self.merged_operator_address
                                        pass  # Suppressed: print >>sys.stderr, '[MERGED] Using provided node operator address: %s' % node_operator_address
                                    else:
                                        # Convert pubkey_hash to merged chain address format (NOT parent chain!)
                                        node_operator_address = bitcoin_data.pubkey_hash_to_address(
                                            self.my_pubkey_hash, merged_addr_net.ADDRESS_VERSION,
                                            -1, merged_addr_net)
                                        pass  # Suppressed: print >>sys.stderr, '[MERGED] Converted node operator address to merged chain: %s' % node_operator_address
                                
                                # Build coinbase with P2Pool donation and node fee
                                # Pass parent_net for automatic address conversion (LTC -> DOGE)
                                # Pass coinbase_text from adapter template (if provided)
                                parent_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                coinbase_text = template.get('auxpow', {}).get('coinbase_text')  # From MM adapter
                                pass  # Suppressed: print >>sys.stderr, '[MERGED] Calling build_merged_coinbase with net=%s (ADDRESS_VERSION=%d), parent_net=%s' % (merged_addr_net.SYMBOL, merged_addr_net.ADDRESS_VERSION, parent_net.SYMBOL)
                                doge_coinbase_tx = merged_mining.build_merged_coinbase(
                                    template, shareholders, merged_addr_net, self.donation_percentage,
                                    node_operator_address, self.worker_fee, parent_net, coinbase_text)
                                
                                doge_coinbase_hash = bitcoin_data.hash256(bitcoin_data.tx_type.pack(doge_coinbase_tx))
                                all_doge_tx_hashes = [doge_coinbase_hash] + doge_tx_hashes
                                
                                # Step 2: Calculate Dogecoin merkle root
                                doge_merkle_root = bitcoin_data.merkle_hash(all_doge_tx_hashes)
                                pass  # Suppressed: print '[DEBUG] Calculated Dogecoin merkle root: %064x' % doge_merkle_root
                                
                                # Step 3-4: Build Dogecoin header with real merkle root and hash it
                                doge_header = dict(
                                    version=template['version'] | (1 << 8),  # Set auxpow bit
                                    previous_block=int(template['previousblockhash'], 16) if template.get('previousblockhash') else 0,
                                    merkle_root=doge_merkle_root,  # REAL merkle root from actual transactions
                                    timestamp=template['curtime'],
                                    bits=bitcoin_data.FloatingIntegerType().unpack(template['bits'].decode('hex')[::-1]),
                                    nonce=0,  # Will be set to parent nonce later
                                )
                                doge_header_packed = bitcoin_data.block_header_type.pack(doge_header)
                                doge_block_hash = bitcoin_data.hash256(doge_header_packed)
                                pass  # Suppressed: print '[MERGED-DEBUG] New Dogecoin block hash calculated: %064x (prev=%s)' % (doge_block_hash, template.get('previousblockhash', 'None')[:16])
                            except Exception as e:
                                print >>sys.stderr, '[ERROR] Failed to build Dogecoin block (v2-FIXED): %s' % e
                                import traceback
                                traceback.print_exc()
                                doge_block_hash = 0
                            
                            # PHASE B: Store for embedding in Litecoin coinbase
                            # This hash will be embedded in the Litecoin coinbase via mm_data
                            # NOW with actual block hash for merged mining commitment
                            parsed_target = pack.IntType(256).unpack(target_hex.decode('hex'))
                            pass  # Suppressed: print '[DEBUG] Dogecoin target from template: %064x' % parsed_target
                            
                            # Determine network name from chainid
                            merged_net_name = 'Dogecoin'
                            merged_net_symbol = 'DOGE'
                            if chainid == 98:  # Dogecoin
                                parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                                if parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower():
                                    merged_net_name = 'Dogecoin Testnet'
                                    merged_net_symbol = 'tDOGE'
                            
                            self.merged_work.set(math.merge_dicts(self.merged_work.value, {chainid: dict(
                                template=template,
                                hash=doge_block_hash,  # CRITICAL: This hash gets embedded in Litecoin coinbase
                                target=parsed_target,
                                merged_proxy=merged_proxy,
                                multiaddress=True,
                                doge_header=doge_header,  # Save for later when building final block
                                doge_coinbase=doge_coinbase_tx,
                                doge_tx_hashes=all_doge_tx_hashes,
                                merged_net_name=merged_net_name,  # Store network name for block found message
                                merged_net_symbol=merged_net_symbol,  # Store network symbol for block found message
                            )}))
                            pass  # Suppressed: print '[MERGED-REFRESH] Template height=%d prev=%s hash=%064x' % (template.get('height', 0), template.get('previousblockhash', 'None')[:16], doge_block_hash)
                        else:
                            # getblocktemplate succeeded but no auxpow - shouldn't happen
                            if auxpow_capable is None:
                                print 'Warning: getblocktemplate succeeded but no auxpow object at %s, falling back to createauxblock/getauxblock' % (merged_url,)
                            auxpow_capable = False
                            raise ValueError('No auxpow in template')
                            
                except Exception as e:
                    # Fall back to createauxblock (with address) or getauxblock (wallet-based)
                    if auxpow_capable is None:
                        print 'Auxpow not supported at %s, using createauxblock/getauxblock (single address mode)' % (merged_url,)
                    auxpow_capable = False
                    
                    # Try createauxblock first (requires payout address, no wallet needed)
                    # Then fall back to getauxblock (requires wallet with keypool)
                    auxblock = None
                    
                    # Auto-convert parent chain address to merged chain (Dogecoin) format if not provided
                    effective_payout_address = merged_payout_address
                    if not effective_payout_address and self.my_pubkey_hash:
                        # Dogecoin testnet uses address version 113 (0x71)
                        # Detect testnet from parent chain symbol
                        parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                        is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
                        
                        if is_testnet and dogecoin_testnet_net:
                            effective_payout_address = bitcoin_data.pubkey_hash_to_address(
                                self.my_pubkey_hash, dogecoin_testnet_net.ADDRESS_VERSION,
                                -1, dogecoin_testnet_net)
                        elif dogecoin_net:
                            effective_payout_address = bitcoin_data.pubkey_hash_to_address(
                                self.my_pubkey_hash, dogecoin_net.ADDRESS_VERSION,
                                -1, dogecoin_net)
                        
                        if effective_payout_address:
                            print 'Auto-converted parent address to merged chain: %s' % effective_payout_address
                    
                    if effective_payout_address:
                        try:
                            auxblock = yield deferral.retry('Error while calling merged createauxblock on %s:' % (merged_url,), 30)(
                                merged_proxy.rpc_createauxblock
                            )(effective_payout_address)
                            if auxpow_capable is None:
                                print 'Using createauxblock API at %s with address %s' % (merged_url, effective_payout_address)
                        except Exception as create_err:
                            print 'createauxblock failed at %s: %s, trying getauxblock' % (merged_url, create_err)
                    
                    # Track whether we used createauxblock (for submitauxblock) or getauxblock
                    use_submitauxblock = False
                    
                    if auxblock is None:
                        # Fall back to getauxblock (requires wallet)
                        auxblock = yield deferral.retry('Error while calling merged getauxblock on %s:' % (merged_url,), 30)(
                            merged_proxy.rpc_getauxblock
                        )()
                    else:
                        # We used createauxblock, so we need submitauxblock for submission
                        use_submitauxblock = True
                    
                    # Check if merged work hash changed (new block to mine)
                    new_hash = int(auxblock['hash'], 16)
                    old_work = self.merged_work.value.get(auxblock['chainid'], {})
                    old_hash = old_work.get('hash', 0)
                    
                    # Initialize merged broadcaster for fallback mode (once)
                    chainid = auxblock['chainid']
                    if not broadcaster_initialized and chainid not in self.node.merged_broadcasters:
                        try:
                            chain_name = 'dogecoin' if chainid == 98 else 'merged_%d' % chainid
                            parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                            
                            # Select correct P2P network for the merged chain
                            p2p_net = None
                            p2p_port = None
                            local_p2p_addr = None
                            
                            if chainid == 98:  # Dogecoin
                                if parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower():
                                    chain_name = 'dogecoin_testnet'
                                    p2p_net = dogecoin_testnet_net
                                    p2p_port = 44556 if dogecoin_testnet_net else None
                                else:
                                    p2p_net = dogecoin_net
                                    p2p_port = 22556 if dogecoin_net else None
                                
                                # Get local Dogecoin node's P2P address from args
                                merged_p2p_port = getattr(self.args, 'merged_coind_p2p_port', None)
                                merged_address = getattr(self.args, 'merged_coind_address', None)
                                if merged_p2p_port and merged_address:
                                    local_p2p_addr = (merged_address, merged_p2p_port)
                            
                            # Compute datadir_path for peer database storage
                            net_name = self.node.net.NAME
                            if hasattr(self.args, 'datadir') and self.args.datadir:
                                datadir_path = os.path.join(self.args.datadir, net_name)
                            else:
                                datadir_path = os.path.join(os.path.dirname(sys.argv[0]), 'data', net_name)
                            
                            merged_broadcaster = MergedMiningBroadcaster(
                                merged_proxy=merged_proxy,
                                merged_url=merged_url,
                                datadir_path=datadir_path,
                                chain_name=chain_name,
                                p2p_net=p2p_net,
                                p2p_port=p2p_port,
                                local_p2p_addr=local_p2p_addr,
                            )
                            yield merged_broadcaster.start()
                            self.node.merged_broadcasters[chainid] = merged_broadcaster
                            print 'Merged broadcaster started for chainid %d (%s) P2P=%s local=%s' % (
                                chainid, chain_name, 
                                'enabled' if p2p_net else 'disabled',
                                '%s:%d' % local_p2p_addr if local_p2p_addr else 'none')
                        except Exception as e:
                            print >>sys.stderr, 'Failed to start merged broadcaster: %s' % e
                        broadcaster_initialized = True
                    
                    self.merged_work.set(math.merge_dicts(self.merged_work.value, {auxblock['chainid']: dict(
                        hash=new_hash,
                        target='p2pool' if auxblock['target'] == 'p2pool' else pack.IntType(256).unpack(auxblock['target'].decode('hex')),
                        merged_proxy=merged_proxy,
                        multiaddress=False,
                        use_submitauxblock=use_submitauxblock,
                        coinbasevalue=auxblock.get('coinbasevalue', 0),  # Block reward + fees
                        height=auxblock.get('height', 0),
                    )}))
                    
                    # Log when hash changes (new block template)
                    if new_hash != old_hash:
                        print '[MERGED-REFRESH-SINGLE] NEW TEMPLATE hash=%s target=%s height=%s' % (auxblock['hash'][:16], auxblock['target'][:16], auxblock.get('height', '?'))
                
                yield deferral.sleep(1)
        
        for merged_url_tuple in merged_urls:
            # Handle both 2-tuple and 3-tuple formats
            if len(merged_url_tuple) == 3:
                merged_url, merged_userpass, merged_payout = merged_url_tuple
            else:
                merged_url, merged_userpass = merged_url_tuple
                merged_payout = None
            set_merged_work(merged_url, merged_userpass, merged_payout)

        @self.merged_work.changed.watch
        def _(new_merged_work):
            pass  # Suppress spam: Got new merged mining work!

        # COMBINE WORK

        self.current_work = variable.Variable(None)
        def compute_work():
            t = self.node.bitcoind_work.value
            bb = self.node.best_block_header.value
            if bb is not None and bb['previous_block'] == t['previous_block'] and self.node.net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(bb)) <= t['bits'].target:
                print 'Skipping from block %x to block %x! NewHeight=%s' % (bb['previous_block'],
                    self.node.net.PARENT.BLOCKHASH_FUNC(bitcoin_data.block_header_type.pack(bb)),t['height']+1,)
                '''
                # New block template from Dash daemon only
                t = dict(
                    version=bb['version'],
                    previous_block=self.node.net.PARENT.BLOCKHASH_FUNC(bitcoin_data.block_header_type.pack(bb)),
                    bits=bb['bits'], # not always true
                    coinbaseflags='',
                    height=t['height'] + 1,
                    time=bb['timestamp'] + 600, # better way?
                    transactions=[],
                    transaction_fees=[],
                    merkle_link=bitcoin_data.calculate_merkle_link([None], 0),
                    subsidy=self.node.bitcoind_work.value['subsidy'],
                    last_update=self.node.bitcoind_work.value['last_update'],
                    payment_amount=self.node.bitcoind_work.value['payment_amount'],
                    packed_payments=self.node.bitcoind_work.value['packed_payments'],
                )
                '''

            self.current_work.set(t)
        self.node.bitcoind_work.changed.watch(lambda _: compute_work())
        self.node.best_block_header.changed.watch(lambda _: compute_work())
        compute_work()

        self.new_work_event = variable.Event()
        @self.current_work.transitioned.watch
        def _(before, after):
            # trigger LP if version/previous_block/bits changed or transactions changed from nothing
            if any(before[x] != after[x] for x in ['version', 'previous_block', 'bits']) or (not before['transactions'] and after['transactions']):
                self.new_work_event.happened()
        self.merged_work.changed.watch(lambda _: self.new_work_event.happened())
        self.node.best_share_var.changed.watch(lambda _: self.new_work_event.happened())

    def stop(self):
        self.running = False

    def get_stale_counts(self):
        '''Returns (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain)'''
        my_shares = len(self.my_share_hashes)
        my_doa_shares = len(self.my_doa_share_hashes)
        delta = self.tracker_view.get_delta_to_last(self.node.best_share_var.value)
        my_shares_in_chain = delta.my_count + self.removed_unstales_var.value[0]
        my_doa_shares_in_chain = delta.my_doa_count + self.removed_doa_unstales_var.value
        orphans_recorded_in_chain = delta.my_orphan_announce_count + self.removed_unstales_var.value[1]
        doas_recorded_in_chain = delta.my_dead_announce_count + self.removed_unstales_var.value[2]

        my_shares_not_in_chain = my_shares - my_shares_in_chain
        my_doa_shares_not_in_chain = my_doa_shares - my_doa_shares_in_chain

        return (my_shares_not_in_chain - my_doa_shares_not_in_chain, my_doa_shares_not_in_chain), my_shares, (orphans_recorded_in_chain, doas_recorded_in_chain)

    @defer.inlineCallbacks
    def freshen_addresses(self, c):
        self.cur_address_throttle = time.time()
        if self.cur_address_throttle - self.address_throttle < 30:
            return
        self.address_throttle=time.time()
        print "ATTEMPTING TO FRESHEN ADDRESS."
        self.address = yield deferral.retry('Error getting a dynamic address from coind:', 5)(lambda: self.bitcoind.rpc_getnewaddress('p2pool'))()
        new_pubkey, _, _ = bitcoin_data.address_to_pubkey_hash(self.address, self.net)
        self.pubkeys.popleft()
        self.pubkeys.addkey(new_pubkey)
        print " Updated payout pool:"
        for i in xrange(len(self.pubkeys.keys)):
            print '    ...payout %d: %s(%f)' % (i, bitcoin_data.pubkey_hash_to_address(self.pubkeys.keys[i], self.net.ADDRESS_VERSION, -1, self.net),self.pubkeys.keyweights[i],)
        self.pubkeys.updatestamp(c)
        print " Next address rotation in : %fs" % (time.time()-c+self.args.timeaddresses)

    def get_user_details(self, username):
        # Debug: Uncomment to trace user details lookup
        #print '[DEBUG] get_user_details called with username:', repr(username)
        contents = re.split('([+/])', username)
        assert len(contents) % 2 == 1

        user, contents2 = contents[0], contents[1:]
        
        # Parse merged mining addresses (format: ltc_addr,doge_addr or ltc_addr,doge_addr.worker)
        # Using , (comma) separator - URL-safe and not used in difficulty parsing
        # NOTE: This parsing exists but merged addresses are NOT stored in share chain.
        # They're used for current work only. Historical shares use auto-conversion.
        # To make this persistent would require P2Pool protocol changes (new share format).
        merged_addresses = {}
        worker = ''
        
        if ',' in user:
            # Split merged addresses
            parts = user.split(',', 1)  # Only split on first comma
            user = parts[0]  # Primary address (Litecoin)
            if len(parts) > 1:
                merged_addr = parts[1]
                # Check if worker name is attached to merged address
                if '.' in merged_addr:
                    merged_addr, worker = merged_addr.split('.', 1)
                elif '_' in merged_addr:
                    merged_addr, worker = merged_addr.split('_', 1)
                merged_addresses['dogecoin'] = merged_addr
                # Debug: Uncomment to trace merged address usage
                #print '[DEBUG] Using miner dogecoin address:', merged_addr
        
        # Parse worker name from primary address if not already set
        if not worker:
            if '_' in user:
                worker = user.split('_')[1]
                user = user.split('_')[0]
            elif '.' in user:
                worker = user.split('.')[1]
                user = user.split('.')[0]

        desired_pseudoshare_target = None
        desired_share_target = None
        for symbol, parameter in zip(contents2[::2], contents2[1::2]):
            if symbol == '+':
                try:
                    desired_pseudoshare_target = bitcoin_data.difficulty_to_target(float(parameter))
                except:
                    if p2pool.DEBUG:
                        log.err()
            elif symbol == '/':
                try:
                    desired_share_target = bitcoin_data.difficulty_to_target(float(parameter))
                except:
                    if p2pool.DEBUG:
                        log.err()        

        # Initialize pubkey_hash with default
        pubkey_hash = self.my_pubkey_hash
        
        if self.args.address == 'dynamic':
            i = self.pubkeys.weighted()
            pubkey_hash = self.pubkeys.keys[i]

            c = time.time()
            if (c - self.pubkeys.stamp) > self.args.timeaddresses:
                self.freshen_addresses(c)

        if random.uniform(0, 100) < self.worker_fee:
            pubkey_hash = self.my_pubkey_hash
        # Secondary donation: Credit some shares to secondary donation address (like a fake miner)
        # This is compatible with old nodes - they see it as a regular miner payout
        # Split donation_percentage: half stays as primary donation, half goes to secondary via this mechanism
        # 
        # SECONDARY DONATION LOGIC:
        # - For --give-author 0: Use MARKER_CHANCE (0.012%) to ensure ~1 share per PPLNS window
        #   This gives ~72,000 litoshis (~0.00072 LTC) per block as blockchain marker
        #   Primary donation still gets only consensus dust
        # - For --give-author >0: Split 50/50 between primary and secondary
        #   Use max(MARKER_CHANCE, donation/2) to ensure marker always appears
        elif p2pool_data.SECONDARY_DONATION_ENABLED:
            MARKER_CHANCE = 0.012  # ~1 share per 8640 PPLNS window = marker in every block
            secondary_donation_chance = max(MARKER_CHANCE, self.donation_percentage / 2)
            if random.uniform(0, 100) < secondary_donation_chance:
                # Credit this share to secondary donation address (our project's donation)
                pubkey_hash = p2pool_data.script_to_pubkey_hash(p2pool_data.SECONDARY_DONATION_SCRIPT)
            else:
                try:
                    if not user or not user.strip():
                        # Credit to primary donation (original P2Pool developer donation)
                        pubkey_hash = p2pool_data.script_to_pubkey_hash(p2pool_data.DONATION_SCRIPT)
                    else:
                        is_convertible, validated_pubkey_hash, error_msg = is_pubkey_hash_address(user, self.node.net.PARENT)
                        if is_convertible:
                            pubkey_hash = validated_pubkey_hash
                        else:
                            print >>sys.stderr, '[WARN] Miner address %s is not convertible for merged mining: %s' % (user[:30] + '...' if len(user) > 30 else user, error_msg)
                            print >>sys.stderr, '[WARN] This miner will NOT receive merged mining rewards! Use P2PKH or P2WPKH address.'
                            pubkey_hash, _, _ = bitcoin_data.address_to_pubkey_hash(user, self.node.net.PARENT)
                except:
                    pubkey_hash = self.my_pubkey_hash
        else:
            # SECONDARY_DONATION_ENABLED=False
            # Standard behavior - no secondary donation
            try:
                # Skip validation if user is empty (can happen with pre-authorization work requests)
                # Use donation script pubkey_hash so rewards go to P2Pool development
                if not user or not user.strip():
                    # Extract pubkey_hash from DONATION_SCRIPT (P2PK script - need different handling)
                    # For empty user, fall back to my_pubkey_hash
                    pubkey_hash = self.my_pubkey_hash
                else:
                    # Validate that miner's address is convertible for merged mining
                    is_convertible, validated_pubkey_hash, error_msg = is_pubkey_hash_address(user, self.node.net.PARENT)
                    
                    if is_convertible:
                        pubkey_hash = validated_pubkey_hash
                    else:
                        # Address is not convertible (P2SH, P2WSH, P2TR)
                        # Log warning but still allow mining on parent chain
                        # Merged mining rewards will be skipped for this miner
                        print >>sys.stderr, '[WARN] Miner address %s is not convertible for merged mining: %s' % (user[:30] + '...' if len(user) > 30 else user, error_msg)
                        print >>sys.stderr, '[WARN] This miner will NOT receive merged mining rewards! Use P2PKH or P2WPKH address.'
                        # Fall back to parsing anyway for parent chain mining
                        pubkey_hash, _, _ = bitcoin_data.address_to_pubkey_hash(user, self.node.net.PARENT)
            except: # XXX blah
                pubkey_hash = self.my_pubkey_hash
        
        # Append worker name to user for identification
        if worker:
            user = user + '.' + worker

        # Debug: Uncomment to trace user details processing
        #print '[DEBUG] get_user_details returning: user=%r, merged_addresses=%r' % (user, merged_addresses)
        return user, pubkey_hash, desired_share_target, desired_pseudoshare_target, merged_addresses

    def preprocess_request(self, user):
        # Debug: Uncomment to trace preprocess flow
        #print '[DEBUG] preprocess_request called with user:', repr(user)
        # Removed peer connection check - allow solo mining
        if time.time() > self.current_work.value['last_update'] + 60:
            raise jsonrpc.Error_for_code(-12345)(u'lost contact with coind')
        username, pubkey_hash, desired_share_target, desired_pseudoshare_target, merged_addresses = self.get_user_details(user)
        #print '[DEBUG] preprocess_request returning 5 values: username=%r' % (username,)
        return username, pubkey_hash, desired_share_target, desired_pseudoshare_target, merged_addresses

    def _estimate_local_hash_rate(self):
        if len(self.recent_shares_ts_work) == 50:
            hash_rate = sum(work for ts, work in self.recent_shares_ts_work[1:])//(self.recent_shares_ts_work[-1][0] - self.recent_shares_ts_work[0][0])
            if hash_rate > 0:
                return hash_rate
        return None

    def get_local_rates(self):
        miner_hash_rates = {}
        miner_dead_hash_rates = {}
        datums, dt = self.local_rate_monitor.get_datums_in_last()
        for datum in datums:
            miner_hash_rates[datum['user']] = miner_hash_rates.get(datum['user'], 0) + datum['work']/dt
            if datum['dead']:
                miner_dead_hash_rates[datum['user']] = miner_dead_hash_rates.get(datum['user'], 0) + datum['work']/dt
        return miner_hash_rates, miner_dead_hash_rates

    def get_local_addr_rates(self):
        addr_hash_rates = {}
        datums, dt = self.local_addr_rate_monitor.get_datums_in_last()
        for datum in datums:
            addr_hash_rates[datum['pubkey_hash']] = addr_hash_rates.get(datum['pubkey_hash'], 0) + datum['work']/dt
        return addr_hash_rates

    def update_best_difficulty(self, user, difficulty):
        """Track best difficulty for a miner"""
        if user not in self.miner_best_difficulty:
            self.miner_best_difficulty[user] = {
                'all_time': 0,
                'session': 0,
                'session_start': self.session_start_time
            }
        
        if difficulty > self.miner_best_difficulty[user]['all_time']:
            self.miner_best_difficulty[user]['all_time'] = difficulty
        if difficulty > self.miner_best_difficulty[user]['session']:
            self.miner_best_difficulty[user]['session'] = difficulty

    def get_miner_best_difficulty(self, user):
        """Get best difficulty stats for a miner"""
        if user not in self.miner_best_difficulty:
            return {'all_time': 0, 'session': 0, 'session_start': self.session_start_time}
        return self.miner_best_difficulty[user]

    def get_miner_hashrate_periods(self, user):
        """Get hashrate for different time periods (1m, 10m, 1h)"""
        # Access raw datums with timestamps from the rate monitor
        self.local_rate_monitor._prune()
        now = time.time()
        
        periods = {
            '1m': {'work': 0, 'dead_work': 0, 'duration': 60},
            '10m': {'work': 0, 'dead_work': 0, 'duration': 600},
            '1h': {'work': 0, 'dead_work': 0, 'duration': 3600}
        }
        
        for ts, datum in self.local_rate_monitor.datums:
            if datum.get('user') != user:
                continue
            age = now - ts
            
            for period_name, period_data in periods.items():
                if age <= period_data['duration']:
                    period_data['work'] += datum['work']
                    if datum.get('dead', False):
                        period_data['dead_work'] += datum['work']
        
        result = {}
        for period_name, period_data in periods.items():
            duration = period_data['duration']
            result[period_name] = {
                'hashrate': period_data['work'] / duration if duration > 0 else 0,
                'dead_hashrate': period_data['dead_work'] / duration if duration > 0 else 0
            }
        
        return result

    def get_work(self, user, pubkey_hash, desired_share_target, desired_pseudoshare_target, merged_addresses=None):
        # Debug: Uncomment to trace get_work calls
        #print '[DEBUG] get_work called with user=%r, merged_addresses=%r' % (user, merged_addresses)
        global print_throttle
        t0 = time.time()  # Benchmarking start
        
        # Store merged addresses for later use in block submission
        if merged_addresses is None:
            merged_addresses = {}
        self._current_merged_addresses = merged_addresses
        
        # Removed peer connection check - allow solo mining
        # P2Pool can work standalone even with PERSIST=True

        if self.merged_work.value:
            tree, size = bitcoin_data.make_auxpow_tree(self.merged_work.value)
            mm_hashes = [self.merged_work.value.get(tree.get(i), dict(hash=0))['hash'] for i in xrange(size)]
            mm_data = '\xfa\xbemm' + bitcoin_data.aux_pow_coinbase_type.pack(dict(
                merkle_root=bitcoin_data.merkle_hash(mm_hashes),
                size=size,
                nonce=0,
            ))
            # Include chain_id in mm_later tuple for merged block recording
            mm_later = [(dict(aux_work, chainid=chain_id), mm_hashes.index(aux_work['hash']), mm_hashes) for chain_id, aux_work in self.merged_work.value.iteritems()]
            
            # Debug: Uncomment to trace merged mining data in coinbase (prints frequently)
            # print >>sys.stderr, '[DEBUG] Merged mining data being embedded in Litecoin coinbase:'
            # for chain_id, aux_work in self.merged_work.value.iteritems():
            #     print >>sys.stderr, '[DEBUG]   Chain ID 0x%08x: hash=%064x' % (chain_id, aux_work['hash'])
            # print >>sys.stderr, '[DEBUG]   Merkle root of mm_hashes: %064x' % bitcoin_data.merkle_hash(mm_hashes)
        else:
            mm_data = ''
            mm_later = []

        # CRITICAL: Use txid (stripped hash without SegWit witness) for merkle root calculation!
        # For SegWit transactions, the merkle root uses txid (not wtxid).
        # get_txid() uses tx_id_type which strips the witness data before hashing.
        tx_hashes = [bitcoin_data.get_txid(tx) for tx in self.current_work.value['transactions']]
        tx_map = dict(zip(tx_hashes, self.current_work.value['transactions']))

        previous_share = self.node.tracker.items[self.node.best_share_var.value] if self.node.best_share_var.value is not None else None
        if previous_share is None:
            share_type = p2pool_data.Share
        else:
            previous_share_type = type(previous_share)

            if previous_share_type.SUCCESSOR is None or self.node.tracker.get_height(previous_share.hash) < self.node.net.CHAIN_LENGTH:
                share_type = previous_share_type
            else:
                successor_type = previous_share_type.SUCCESSOR

                counts = p2pool_data.get_desired_version_counts(self.node.tracker,
                    self.node.tracker.get_nth_parent_hash(previous_share.hash, self.node.net.CHAIN_LENGTH*9//10), self.node.net.CHAIN_LENGTH//10)
                upgraded = counts.get(successor_type.VERSION, 0)/sum(counts.itervalues())
                if upgraded > .65:
                    print 'Switchover imminent. Upgraded: %.3f%% Threshold: %.3f%%' % (upgraded*100, 95)
                # Share -> NewShare only valid if 95% of hashes in [net.CHAIN_LENGTH*9//10, net.CHAIN_LENGTH] for new version
                if counts.get(successor_type.VERSION, 0) > sum(counts.itervalues())*95//100:
                    share_type = successor_type
                else:
                    share_type = previous_share_type
        local_addr_rates = self.get_local_addr_rates()

        if desired_share_target is None:
            desired_share_target = 2**256-1
            local_hash_rate = local_addr_rates.get(pubkey_hash, 0)
            if local_hash_rate > 0.0:
                desired_share_target = min(desired_share_target,
                    bitcoin_data.average_attempts_to_target(local_hash_rate * self.node.net.SHARE_PERIOD / 0.0167)) # limit to 1.67% of pool shares by modulating share difficulty



            lookbehind = 3600//self.node.net.SHARE_PERIOD
            block_subsidy = self.node.bitcoind_work.value['subsidy']
            if previous_share is not None and self.node.tracker.get_height(previous_share.hash) > lookbehind:
                expected_payout_per_block = local_addr_rates.get(pubkey_hash, 0)/p2pool_data.get_pool_attempts_per_second(self.node.tracker, self.node.best_share_var.value, lookbehind) \
                    * block_subsidy*(1-self.donation_percentage/100) # XXX doesn't use global stale rate to compute pool hash
                if expected_payout_per_block < self.node.net.PARENT.DUST_THRESHOLD:
                    desired_share_target = min(desired_share_target,
                        bitcoin_data.average_attempts_to_target((bitcoin_data.target_to_average_attempts(self.node.bitcoind_work.value['bits'].target)*self.node.net.SPREAD)*self.node.net.PARENT.DUST_THRESHOLD/block_subsidy)
                    )

        if True:
            # Build share_data differently based on share version
            # VERSION >= 34 uses 'address' (string), VERSION < 34 uses 'pubkey_hash' (int)
            # Calculate primary donation percentage
            # If SECONDARY_DONATION_ENABLED AND donation_percentage > 0: 
            #   Split donation - half goes to primary via donation field, half to secondary via fake miner
            # If donation_percentage = 0: No split (primary gets consensus dust only, secondary gets nothing)
            # If SECONDARY_DONATION_ENABLED = False: Full donation goes to primary
            primary_donation_pct = self.donation_percentage
            if p2pool_data.SECONDARY_DONATION_ENABLED and self.donation_percentage > 0:
                primary_donation_pct = self.donation_percentage / 2  # Half to primary, half to secondary via fake miner
            
            share_data_base = dict(
                previous_share_hash=self.node.best_share_var.value,
                coinbase=(script.create_push_script([
                    self.current_work.value['height'],
                    ] + ([mm_data] if mm_data else []) + [
                ]) + self.current_work.value['coinbaseflags'] + getattr(self.node.net, 'COINBASEEXT', b''))[:100],
                nonce=random.randrange(2**32),
                subsidy=self.current_work.value['subsidy'],
                donation=math.perfect_round(65535*primary_donation_pct/100),
                stale_info=(lambda (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain):
                    'orphan' if orphans > orphans_recorded_in_chain else
                    'doa' if doas > doas_recorded_in_chain else
                    None
                )(*self.get_stale_counts()),
                desired_version=(share_type.SUCCESSOR if share_type.SUCCESSOR is not None else share_type).VOTING_VERSION,
            )
            
            if share_type.VERSION >= 34:
                # Newer share versions use 'address' as a string
                share_data_base['address'] = bitcoin_data.pubkey_hash_to_address(pubkey_hash, self.node.net.PARENT.ADDRESS_VERSION, -1, self.node.net.PARENT)
            else:
                # Older share versions use 'pubkey_hash' as an integer  
                share_data_base['pubkey_hash'] = pubkey_hash
            
            share_info, gentx, other_transaction_hashes, get_share = share_type.generate_transaction(
                tracker=self.node.tracker,
                share_data=share_data_base,
                block_target=self.current_work.value['bits'].target,
                desired_timestamp=int(time.time() + 0.5),
                desired_target=desired_share_target,
                ref_merkle_link=dict(branch=[], index=0),
                desired_other_transaction_hashes_and_fees=zip(tx_hashes, self.current_work.value['transaction_fees']),
                net=self.node.net,
                known_txs=tx_map,
                base_subsidy=self.current_work.value['subsidy'],
            )

        packed_gentx = bitcoin_data.tx_type.pack(gentx)
        other_transactions = [tx_map[tx_hash] for tx_hash in other_transaction_hashes]

        mm_later = [(dict(aux_work, target=aux_work['target'] if aux_work['target'] != 'p2pool' else share_info['bits'].target), index, hashes) for aux_work, index, hashes in mm_later]

        if desired_pseudoshare_target is None:
            target = 2**256-1
            local_hash_rate = self._estimate_local_hash_rate()
            if local_hash_rate is not None:
                target = min(target,
                    bitcoin_data.average_attempts_to_target(local_hash_rate * 1)) # limit to 1 share response every second by modulating pseudoshare difficulty
        else:
            target = desired_pseudoshare_target
        for aux_work, index, hashes in mm_later:
            target = max(target, aux_work['target'])
        
        # Clip to SANE_TARGET_RANGE: [min_target (hardest), max_target (easiest)]
        # SANE_TARGET_RANGE[0] = lowest target = highest difficulty (e.g., 10000)
        # SANE_TARGET_RANGE[1] = highest target = lowest difficulty (e.g., 1)
        # We do NOT enforce P2Pool share floor here - that would prevent vardiff from
        # setting difficulty higher than the (potentially easy) P2Pool share chain.
        # Stratum separately checks if shares meet P2Pool criteria before crediting them.
        target = math.clip(target, self.node.net.PARENT.SANE_TARGET_RANGE)

        getwork_time = time.time()
        lp_count = self.new_work_event.times
        
        # CRITICAL: merkle_link must use other_transaction_hashes (the transactions actually in the share)
        # NOT tx_hashes (all available transactions). The share's coinbase + other_transaction_hashes
        # defines the block that will be submitted. The merkle_link must match this.
        # This is true for BOTH regular P2Pool AND merged mining.
        merkle_link = bitcoin_data.calculate_merkle_link([None] + other_transaction_hashes, 0)
        # if mm_later:
        #     print >>sys.stderr, '[DEBUG] Merged mining: merkle_link uses other_transaction_hashes (%d txs)' % len(other_transaction_hashes)


        if print_throttle is 0.0:
            print_throttle = time.time()
        else:
            current_time = time.time()
            if (current_time - print_throttle) > 5.0:
                # Debug: Uncomment to trace share target/difficulty calculations (confirmed working)
                # print >>sys.stderr, '[SHARE DEBUG] share_info[bits].target = %x' % share_info['bits'].target
                # print >>sys.stderr, '[SHARE DEBUG] share_info[bits].bits = %x' % share_info['bits'].bits
                # print >>sys.stderr, '[SHARE DEBUG] target (pseudoshare) = %x' % target
                # print >>sys.stderr, '[SHARE DEBUG] MAX_TARGET = %x' % self.node.net.MAX_TARGET
                # print >>sys.stderr, '[SHARE DEBUG] MIN_TARGET = %x' % self.node.net.MIN_TARGET
                # print >>sys.stderr, '[SHARE DEBUG] SANE_TARGET_RANGE = (%x, %x)' % self.node.net.PARENT.SANE_TARGET_RANGE
                print 'New work for worker %s! Difficulty: %.06f Share difficulty: %.06f (speed %.06f) Total block value: %.6f %s including %i transactions' % (
                    bitcoin_data.pubkey_hash_to_address(pubkey_hash, self.node.net.PARENT.ADDRESS_VERSION, -1, self.node.net.PARENT),
                    bitcoin_data.target_to_difficulty(target),
                    bitcoin_data.target_to_difficulty(share_info['bits'].target),
                    local_addr_rates.get(pubkey_hash, 0),
                    self.current_work.value['subsidy']*1e-8, self.node.net.PARENT.SYMBOL,
                    len(self.current_work.value['transactions']),
                )
                print_throttle = time.time()

        #need this for stats
        self.last_work_shares.value[bitcoin_data.pubkey_hash_to_address(pubkey_hash, self.node.net.PARENT.ADDRESS_VERSION, -1, self.node.net.PARENT)]=share_info['bits']

        coinbase_payload_data_size = 0
        if gentx['version'] == 3 and gentx['type'] == 5:
            coinbase_payload_data_size = len(pack.VarStrType().pack(gentx['extra_payload']))

        # For stratum coinb1/coinb2, use tx_id_type (stripped format without SegWit marker)
        # This is necessary because:
        # 1. Miner computes merkle_root by hashing coinb1+nonce+coinb2
        # 2. We use get_txid() (which uses tx_id_type) for merkle calculations
        # 3. Both must produce the same hash for shares to be valid
        packed_gentx_stripped = bitcoin_data.tx_id_type.pack(gentx)

        # Fixed based on jtoomim's p2pool implementation
        # share_target = vardiff pseudoshare difficulty (already floored at p2pool_share_floor above)
        # min_share_target = P2Pool share chain difficulty floor (respects SANE_TARGET_RANGE)
        ba = dict(
            version=self.current_work.value['version'],
            previous_block=self.current_work.value['previous_block'],
            merkle_link=merkle_link,
            coinb1=packed_gentx_stripped[:-coinbase_payload_data_size-self.COINBASE_NONCE_LENGTH-4],
            coinb2=packed_gentx_stripped[-coinbase_payload_data_size-4:],
            timestamp=self.current_work.value['time'],
            bits=self.current_work.value['bits'],
            min_share_target=min(share_info['bits'].target, self.node.net.PARENT.SANE_TARGET_RANGE[1]),  # P2Pool share difficulty floor
            share_target=target,  # Vardiff pseudoshare target (already floored)
        )

        received_header_hashes = set()

        def got_response(header, user, coinbase_nonce, submitted_target=None):
            # submitted_target: optional override for the target the miner was actually working at
            # This is needed for vardiff - stratum adjusts target after get_work() returns
            effective_target = submitted_target if submitted_target is not None else target
            
            assert len(coinbase_nonce) == self.COINBASE_NONCE_LENGTH
            # IMPORTANT: CachingWorkerBridge modifies x['coinb1'] by appending caching nonce bytes,
            # but ba['coinb1'] is the original. The lambda in CachingWorkerBridge prepends the
            # caching nonce to coinbase_nonce before calling us. So coinbase_nonce is FULL length.
            # We must reconstruct from packed_gentx_stripped using the FULL coinbase_nonce.
            coinbase_payload_data_size_local = 0
            if gentx['version'] == 3 and gentx['type'] == 5:
                coinbase_payload_data_size_local = len(pack.VarStrType().pack(gentx['extra_payload']))
            # Reconstruct using stripped format (tx_id_type) to match miner's merkle calculation
            # ALWAYS reconstruct - even if nonce is all zeros, because CachingWorkerBridge
            # modifies coinb1 and stratum uses the modified version.
            new_packed_gentx = packed_gentx_stripped[:-coinbase_payload_data_size_local-self.COINBASE_NONCE_LENGTH-4] + coinbase_nonce + packed_gentx_stripped[-coinbase_payload_data_size_local-4:]
            new_gentx = bitcoin_data.tx_id_type.unpack(new_packed_gentx)
            
            # Restore SegWit witness data if original gentx had it
            # This is required for block submission to work with SegWit-activated chains
            if 'marker' in gentx and gentx.get('flag'):
                new_gentx = dict(new_gentx)  # Make mutable copy
                new_gentx['marker'] = gentx['marker']
                new_gentx['flag'] = gentx['flag']
                new_gentx['witness'] = gentx['witness']
                print >>sys.stderr, '[SEGWIT] Restored witness data to new_gentx: marker=%s, flag=%s, witness_len=%d' % (
                    new_gentx.get('marker'), new_gentx.get('flag'), len(new_gentx.get('witness', [])))
            else:
                print >>sys.stderr, '[SEGWIT] Original gentx has no SegWit data: marker=%s, flag=%s' % (
                    gentx.get('marker'), gentx.get('flag'))

            # Debug: Print work.py's calculation for comparison with stratum
            # Show what we're actually using to construct new_packed_gentx
            coinb1_actual = packed_gentx_stripped[:-coinbase_payload_data_size_local-self.COINBASE_NONCE_LENGTH-4]
            coinb2_actual = packed_gentx_stripped[-coinbase_payload_data_size_local-4:]
            # Debug: Uncomment to trace coinbase construction (confirmed working)
            # print >>sys.stderr, '[WORK DEBUG] packed_gentx_stripped length: %d' % len(packed_gentx_stripped)
            # print >>sys.stderr, '[WORK DEBUG] coinbase_payload_data_size_local: %d' % coinbase_payload_data_size_local
            # print >>sys.stderr, '[WORK DEBUG] COINBASE_NONCE_LENGTH: %d' % self.COINBASE_NONCE_LENGTH
            # print >>sys.stderr, '[WORK DEBUG] coinb1_actual length: %d' % len(coinb1_actual)
            # print >>sys.stderr, '[WORK DEBUG] coinb2_actual length: %d' % len(coinb2_actual)
            # print >>sys.stderr, '[WORK DEBUG] coinbase_nonce hex: %s (len=%d)' % (coinbase_nonce.encode('hex'), len(coinbase_nonce))
            # Use txid (stripped hash without SegWit witness data) for merkle root
            # This ensures consistency with auxpow serialization which uses tx_id_type
            work_coinbase_txid = bitcoin_data.get_txid(new_gentx)
            work_coinbase_hash = work_coinbase_txid  # For backward compatibility in debug output
            work_merkle_root = bitcoin_data.check_merkle_link(work_coinbase_txid, ba['merkle_link'])
            # print >>sys.stderr, '[WORK DEBUG] new_packed_gentx length: %d' % len(new_packed_gentx)
            # print >>sys.stderr, '[WORK DEBUG] coinbase txid (stripped): %064x' % work_coinbase_txid
            # print >>sys.stderr, '[WORK DEBUG] coinbase hash: %064x' % work_coinbase_hash
            # print >>sys.stderr, '[WORK DEBUG] header[merkle_root]: %064x' % header['merkle_root']
            # print >>sys.stderr, '[WORK DEBUG] calculated merkle_root: %064x' % work_merkle_root
            # print >>sys.stderr, '[WORK DEBUG] MATCH: %s' % (work_merkle_root == header['merkle_root'])
            
            # CRITICAL FIX: Update header with recalculated merkle_root
            # The header from stratum has merkle_root based on the template coinbase,
            # but we've modified the coinbase with the miner's coinbase_nonce.
            # We MUST use the recalculated merkle_root for correct pow_hash!
            if work_merkle_root != header['merkle_root']:
                print >>sys.stderr, '[CRITICAL] Merkle root mismatch! Updating header with recalculated value.'
                print >>sys.stderr, '[CRITICAL]   Old: %064x' % header['merkle_root']
                print >>sys.stderr, '[CRITICAL]   New: %064x' % work_merkle_root
            header['merkle_root'] = work_merkle_root

            header_hash = self.node.net.PARENT.BLOCKHASH_FUNC(bitcoin_data.block_header_type.pack(header))
            pow_hash = self.node.net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(header))
            
            # Debug: Save the header we hashed for later comparison
            if not hasattr(self, '_last_hashed_header'):
                self._last_hashed_header = {}
            self._last_hashed_header_packed = bitcoin_data.block_header_type.pack(header)
            self._last_hashed_header_hex = self._last_hashed_header_packed.encode('hex')
            
            # Debug: Log every 1000th attempt to monitor progress
            if not hasattr(self, '_attempt_counter'):
                self._attempt_counter = 0
                self._best_pow_hash = 2**256-1
            self._attempt_counter += 1
            if pow_hash < self._best_pow_hash:
                self._best_pow_hash = pow_hash
                ratio = float(pow_hash) / float(header['bits'].target)
                print >>sys.stderr, 'New best hash! pow=%064x target=%064x (%.2f%% of target)' % (pow_hash, header['bits'].target, ratio * 100)
            if self._attempt_counter % 1000 == 0:
                print >>sys.stderr, 'Block mining: %d attempts, best=%.2f%% of target' % (self._attempt_counter, float(self._best_pow_hash) / float(header['bits'].target) * 100)
            
            try:
                if pow_hash <= header['bits'].target or p2pool.DEBUG:
                    if pow_hash <= header['bits'].target:
                        print
                        print '#' * 70
                        print '### PARENT NETWORK BLOCK FOUND! ###'
                        print '### Network: %s (%s) ###' % (self.node.net.PARENT.NAME, self.node.net.PARENT.SYMBOL)
                        print '#' * 70
                        print 'Time:        %s' % time.strftime('%Y-%m-%d %H:%M:%S')
                        print 'Miner:       %s' % user
                        print 'Block hash:  %064x' % header_hash
                        print 'POW hash:    %064x' % pow_hash
                        print 'Target:      %064x' % header['bits'].target
                        if 'height' in share_info:
                            print 'Height:      %d' % share_info['height']
                        print 'Txs:         %d' % (1 + len(other_transactions))
                        print 'Explorer:    %s%064x' % (self.node.net.PARENT.BLOCK_EXPLORER_URL_PREFIX, header_hash)
                        print '#' * 70
                        print
                    
                    # Debug: Check witness merkle root before block submission
                    if bitcoin_data.is_segwit_tx(new_gentx):
                        # Calculate witness merkle root from transactions being submitted
                        all_txs = [new_gentx] + other_transactions
                        wtxids = [0]  # coinbase wtxid is always 0
                        for tx in other_transactions:
                            txid = bitcoin_data.get_txid(tx)
                            wtxid = bitcoin_data.get_wtxid(tx, txid, None)
                            wtxids.append(wtxid)
                        calculated_wtxid_merkle_root = bitcoin_data.merkle_hash(wtxids)
                        
                        # Get the witness commitment from coinbase output[0]
                        # Format: OP_RETURN + aa21a9ed + 32-byte commitment
                        if new_gentx['tx_outs'] and len(new_gentx['tx_outs'][0]['script']) == 38:
                            committed_hash = pack.IntType(256).unpack(new_gentx['tx_outs'][0]['script'][6:])
                            # Witness commitment = hash256(witness_merkle_root || witness_reserved_value)
                            witness_reserved_value_str = '[P2Pool]'*4
                            witness_reserved_value = pack.IntType(256).unpack(witness_reserved_value_str)
                            expected_commitment = bitcoin_data.get_witness_commitment_hash(calculated_wtxid_merkle_root, witness_reserved_value)
                            print >>sys.stderr, '[WITNESS DEBUG] calculated wtxid_merkle_root: %064x' % calculated_wtxid_merkle_root
                            print >>sys.stderr, '[WITNESS DEBUG] committed hash in coinbase: %064x' % committed_hash
                            print >>sys.stderr, '[WITNESS DEBUG] expected commitment: %064x' % expected_commitment
                            print >>sys.stderr, '[WITNESS DEBUG] MATCH: %s' % (committed_hash == expected_commitment)
                            if 'segwit_data' in share_info:
                                print >>sys.stderr, '[WITNESS DEBUG] share_info wtxid_merkle_root: %064x' % share_info['segwit_data']['wtxid_merkle_root']
                    
                    # Submit block and add error callback to catch any failures
                    # Use broadcaster for parallel propagation if available
                    block_submission = helper.submit_block(
                        dict(header=header, txs=[new_gentx] + other_transactions),
                        False,
                        self.node,
                        broadcaster=self.node.broadcaster
                    )
                    @block_submission.addErrback
                    def block_submit_error(err):
                        print >>sys.stderr, '*** CRITICAL: Block submission failed! ***'
                        log.err(err, 'Block submission error:')
                    if pow_hash <= header['bits'].target:
                        # New block found - notify subscribers
                        self.node.factory.new_block.happened(header_hash)
                        # Fire block_found event with block info for immediate persistence
                        block_info = {
                            'ts': time.time(),
                            'hash': '%064x' % header_hash,
                            'number': share_info.get('height', 0),
                            'miner': user,
                            'network_difficulty': bitcoin_data.target_to_difficulty(header['bits'].target),
                            'pow_hash': pow_hash,
                            'target': header['bits'].target,
                        }
                        self.block_found.happened(block_info)
            except:
                log.err(None, 'Error while processing potential block:')

            user, _, _, _, _ = self.get_user_details(user)
            assert header['previous_block'] == ba['previous_block']
            # Note: header['merkle_root'] is calculated in stratum.py with the correct coinbase_nonce
            # Don't recalculate it here because worker_interface.py prepends additional nonce data
            assert header['bits'] == ba['bits']

            # DOA (Dead On Arrival) Share Prevention
            # =============================================
            # Shares are marked DOA if work has changed too many times since the share was issued.
            # Work events fire on: new blocks, new best shares, merged mining updates, etc.
            #
            # Problem: With fast miners or isolated testing, shares arrive after many work events:
            #   - Each new share triggers best_share_var.changed -> new_work_event.happened()
            #   - At 13 GH/s with diff 32, shares come every ~10 sec
            #   - But work events can fire much faster (every share found)
            #   - If tolerance is too low (e.g., 3), most shares become DOA
            #
            # DOA shares don't contribute to the share chain, so:
            #   - Chain height stays low (< TARGET_LOOKBEHIND = 200)
            #   - Vardiff can't adjust (stuck at MAX_TARGET floor)
            #   - More rapid shares -> more DOA -> vicious cycle
            #
            # Solution: Higher tolerance for isolated/testing nodes (PERSIST=False)
            work_event_diff = self.new_work_event.times - lp_count
            # PERSIST=False (isolated testing): 30 events tolerance - allows chain to grow
            # PERSIST=True (production): 3 events - tighter for network consistency
            max_work_events = 30 if not self.node.net.PERSIST else 3
            on_time = work_event_diff <= max_work_events

            # Debug: Uncomment to trace merged mining auxpow checking (prints on every share)
            # print >>sys.stderr, '[DEBUG] mm_later has %d items, pow_hash=%064x' % (len(mm_later), pow_hash)
            # for aux_work, index, hashes in mm_later:
            #     print >>sys.stderr, '[DEBUG] Checking aux_work target=%064x, meets=%s' % (aux_work['target'], pow_hash <= aux_work['target'])

            for aux_work, index, hashes in mm_later:
                try:
                    # Merged mining: Check if hash meets Auxiliary chain (Dogecoin) difficulty
                    # Three scenarios:
                    # 1. pow_hash < aux_work['target'] only: Valid DOGE block (partial win)
                    # 2. pow_hash < both targets: Valid LTC + DOGE blocks (full win)
                    # 3. pow_hash < header['bits'].target only: Valid LTC block only
                    
                    # Log when parent block found - check if merged block should also be submitted
                    if pow_hash <= header['bits'].target:
                        print >>sys.stderr, '[MERGED CHECK] Parent block found! Checking merged chain...'
                        print >>sys.stderr, '[MERGED CHECK] pow_hash=%064x' % pow_hash
                        print >>sys.stderr, '[MERGED CHECK] parent_target=%064x (met: %s)' % (header['bits'].target, pow_hash <= header['bits'].target)
                        print >>sys.stderr, '[MERGED CHECK] merged_target=%064x (met: %s)' % (aux_work['target'], pow_hash <= aux_work['target'])
                        
                        # TWIN BLOCK DETECTION: Same POW hash accepted by BOTH chains!
                        if pow_hash <= aux_work['target']:
                            merged_net_name = aux_work.get('merged_net_name', 'Merged Chain')
                            merged_net_symbol = aux_work.get('merged_net_symbol', 'MERGED')
                            print
                            print '*' * 70
                            print '*** TWIN BLOCK FOUND! ***'
                            print '*** Same POW hash accepted by BOTH chains! ***'
                            print '*' * 70
                            print 'Time:         %s' % time.strftime('%Y-%m-%d %H:%M:%S')
                            print 'Miner:        %s' % user
                            print 'POW Hash:     %064x' % pow_hash
                            print
                            print 'Parent Chain: %s (%s)' % (self.node.net.PARENT.NAME, self.node.net.PARENT.SYMBOL)
                            print '  Block hash: %064x' % header_hash
                            print '  Target:     %064x' % header['bits'].target
                            print
                            print 'Merged Chain: %s (%s)' % (merged_net_name, merged_net_symbol)
                            print '  Block hash: %064x' % aux_work['hash']
                            print '  Target:     %064x' % aux_work['target']
                            print '*' * 70
                            print 'This proves merged mining is working - one hash, two blockchains!'
                            print '*' * 70
                            print
                    
                    # Debug: Uncomment to trace merged block candidates
                    # if pow_hash <= aux_work['target']:
                    #     print >>sys.stderr, 'Dogecoin block candidate: pow_hash=%064x target=%064x ratio=%.2f%%' % (
                    #         pow_hash, aux_work['target'], float(pow_hash) / float(aux_work['target']) * 100)
                    
                    if pow_hash <= aux_work['target']:
                        # Hash meets Dogecoin difficulty - submit auxpow block
                        # Check if this is multiaddress merged mining (getblocktemplate with auxpow)
                        if aux_work.get('multiaddress'):
                            # Build complete Dogecoin block with auxpow proof
                            # The Litecoin block (parent) has already been mined with correct POW
                            # We just need to construct the Dogecoin block that references it
                            template = aux_work['template']
                            
                            # Get miner's merged addresses if provided  
                            merged_addrs = getattr(self, '_current_merged_addresses', {})
                            dogecoin_address = merged_addrs.get('dogecoin')
                            
                            # Debug: Uncomment to trace auxpow block building
                            # print >>sys.stderr, '[DEBUG] Building Dogecoin auxpow block'
                            # print >>sys.stderr, '[DEBUG] Litecoin pow_hash: %064x' % pow_hash
                            # print >>sys.stderr, '[DEBUG] Dogecoin target: %064x' % aux_work['target']
                            # print >>sys.stderr, '[DEBUG] Meets target: %s (%.2f%%)' % (
                            #     pow_hash <= aux_work['target'],
                            #     float(pow_hash) / float(aux_work['target']) * 100
                            # )
                            
                            # PHASE C: Build Dogecoin block for submission using pre-calculated data
                            # Use the header and transactions we built BEFORE mining (Phase A)
                            try:
                                # Retrieve pre-built Dogecoin header from Phase A
                                if 'doge_header' not in aux_work:
                                    raise ValueError('Missing pre-built Dogecoin header from Phase A')
                                
                                doge_header = aux_work['doge_header'].copy()
                                doge_coinbase = aux_work['doge_coinbase']
                                doge_tx_hashes = aux_work['doge_tx_hashes']
                                
                                # Debug: Uncomment to trace Dogecoin header verification
                                # print >>sys.stderr, '[DEBUG] Using pre-built Dogecoin header from Phase A'
                                # print >>sys.stderr, '[DEBUG] Dogecoin merkle root: %064x' % doge_header['merkle_root']
                                # print >>sys.stderr, '[DEBUG] Dogecoin nonce (should be 0): %d' % doge_header['nonce']
                                # print >>sys.stderr, '[DEBUG] Dogecoin block hash from aux_work: %064x' % aux_work['hash']
                                
                                # Verify: Calculate what the Dogecoin block hash should be
                                doge_header_packed_check = bitcoin_data.block_header_type.pack(doge_header)
                                doge_block_hash_check = bitcoin_data.hash256(doge_header_packed_check)
                                # print >>sys.stderr, '[DEBUG] Dogecoin block hash (recalculated): %064x' % doge_block_hash_check
                                # print >>sys.stderr, '[DEBUG] Do they match? %s' % (doge_block_hash_check == aux_work['hash'])
                                
                                # DON'T update nonce - in AuxPoW, child block nonce stays 0
                                # The actual mining work is done on the parent (Litecoin) block
                                # doge_header['nonce'] should already be 0 from Phase A
                                
                                # Debug: Uncomment to trace coinbase transaction handling
                                # print >>sys.stderr, '[DEBUG] new_gentx type: %s' % type(new_gentx)
                                # print >>sys.stderr, '[DEBUG] gentx type: %s' % type(gentx)
                                # Use the DIRECT concatenation for hash (new_packed_gentx from line 595)
                                # NOT pack(new_gentx) which may differ due to unpack/repack!
                                # print >>sys.stderr, '[DEBUG] Using direct concatenation (new_packed_gentx) for hash'
                                # print >>sys.stderr, '[DEBUG] new_packed_gentx length: %d bytes' % len(new_packed_gentx)
                                # print >>sys.stderr, '[DEBUG] packed_gentx length: %d bytes' % len(packed_gentx)
                                # print >>sys.stderr, '[DEBUG] new_packed_gentx == packed_gentx: %s' % (new_packed_gentx == packed_gentx)
                                
                                # Calculate Litecoin coinbase hash using txid (stripped, no witness)
                                # This matches auxpow serialization which uses tx_id_type
                                ltc_coinbase_hash = bitcoin_data.get_txid(new_gentx)
                                ltc_coinbase_hash_from_original = bitcoin_data.get_txid(gentx)
                                
                                # CRITICAL: Verify that tx_id_type.pack(new_gentx) produces correct hash
                                packed_coinbase_for_auxpow = bitcoin_data.tx_id_type.pack(new_gentx)
                                # Debug: Uncomment to trace coinbase hash calculation
                                # print >>sys.stderr, '[DEBUG] new_packed_gentx length: %d' % len(new_packed_gentx)
                                # print >>sys.stderr, '[DEBUG] packed_coinbase_for_auxpow length: %d' % len(packed_coinbase_for_auxpow)
                                # print >>sys.stderr, '[DEBUG] ltc_coinbase_hash (txid): %064x' % ltc_coinbase_hash
                                # print >>sys.stderr, '[DEBUG] Litecoin coinbase txid (from new_gentx): %064x' % ltc_coinbase_hash
                                # print >>sys.stderr, '[DEBUG] Litecoin coinbase txid (from gentx): %064x' % ltc_coinbase_hash_from_original
                                
                                # Build the ACTUAL Litecoin block's transaction list
                                # This is what gets submitted to the Litecoin network (see line 627)
                                # The merkle root should be calculated from THIS list, not from P2Pool share data
                                ltc_tx_list = [new_gentx] + other_transactions
                                # Use txid (stripped hash) for all transactions in merkle tree
                                ltc_tx_hashes = [ltc_coinbase_hash] + [bitcoin_data.get_txid(tx) for tx in other_transactions]
                                
                                # Calculate the REAL Litecoin block's merkle root
                                ltc_block_merkle_root = bitcoin_data.merkle_hash(ltc_tx_hashes)
                                
                                # Debug: Uncomment to trace merkle root calculation
                                # print >>sys.stderr, '[DEBUG] Litecoin block has %d transactions' % len(ltc_tx_list)
                                # print >>sys.stderr, '[DEBUG] Litecoin block merkle root (calculated): %064x' % ltc_block_merkle_root
                                # print >>sys.stderr, '[DEBUG] P2Pool share merkle root (from header): %064x' % header['merkle_root']
                                # print >>sys.stderr, '[DEBUG] Are they the same? %s' % (ltc_block_merkle_root == header['merkle_root'])
                                
                                # CRITICAL: Use ba['merkle_link'] which was saved when this job was created!
                                # The miner's header merkle_root was computed using ba['merkle_link']
                                # NOT the current merkle_link (which may have changed)
                                ltc_coinbase_merkle_branch = ba['merkle_link']
                                
                                # Debug: Uncomment to trace merkle link verification
                                # print >>sys.stderr, '[DEBUG] Using ba[merkle_link] from job (branch length: %d)' % len(ltc_coinbase_merkle_branch['branch'])
                                
                                # Verify: coinbase_hash + ba['merkle_link'] should equal header['merkle_root']
                                calculated_root = bitcoin_data.check_merkle_link(ltc_coinbase_hash, ltc_coinbase_merkle_branch)
                                # print >>sys.stderr, '[DEBUG] Calculated merkle root from ba[merkle_link]: %064x' % calculated_root
                                # print >>sys.stderr, '[DEBUG] Header merkle root: %064x' % header['merkle_root']
                                # print >>sys.stderr, '[DEBUG] Do they MATCH? %s' % (calculated_root == header['merkle_root'])
                                
                                # Use the header as-is - merkle_root should match ba['merkle_link']
                                litecoin_header_for_auxpow = header.copy()
                                
                                # print >>sys.stderr, '[DEBUG] Litecoin auxpow header merkle_root: %064x' % litecoin_header_for_auxpow['merkle_root']
                                # print >>sys.stderr, '[DEBUG] Merkle roots match coinbase branch? %s' % (header['merkle_root'] == calculated_root)
                                
                                # Calculate the auxiliary chain merkle link
                                # This is the merkle branch from the Dogecoin block hash to the aux merkle root
                                # The aux merkle root is embedded in the Litecoin coinbase
                                aux_merkle_link = bitcoin_data.calculate_merkle_link(hashes, index)
                                
                                # Debug: Uncomment to trace aux merkle link calculation
                                # print >>sys.stderr, '[DEBUG] Aux merkle link: index=%d, branch_length=%d' % (index, len(aux_merkle_link['branch']))
                                # print >>sys.stderr, '[DEBUG] Aux merkle hashes tree size: %d' % len(hashes)
                                # for i, h in enumerate(hashes):
                                #     print >>sys.stderr, '[DEBUG]   hashes[%d] = %064x' % (i, h)
                                
                                # Verify the aux merkle link leads to the correct root
                                aux_merkle_root_check = bitcoin_data.check_merkle_link(aux_work['hash'], aux_merkle_link)
                                # print >>sys.stderr, '[DEBUG] Aux merkle root (from link): %064x' % aux_merkle_root_check
                                # print >>sys.stderr, '[DEBUG] Aux merkle root (expected): %064x' % bitcoin_data.merkle_hash(hashes)
                                
                                # Reconstruct Dogecoin block using pre-built header and transactions
                                # The doge_coinbase and transactions were locked in during Phase A
                                # Parse template transactions into proper transaction objects
                                doge_tx_objects = []
                                for tx_dict in template.get('transactions', []):
                                    try:
                                        # Decode hex transaction data and unpack into transaction object
                                        tx_packed = tx_dict['data'].decode('hex')
                                        tx_obj = bitcoin_data.tx_type.unpack(tx_packed)
                                        doge_tx_objects.append(tx_obj)
                                    except Exception as tx_e:
                                        print >>sys.stderr, '[ERROR] Failed to parse Dogecoin transaction: %s' % tx_e
                                        raise
                                
                                doge_tx_list = [doge_coinbase] + doge_tx_objects
                                
                                merged_block = dict(
                                    header=doge_header,
                                    txs=doge_tx_list,
                                    auxpow=dict(
                                        merkle_tx=dict(
                                            tx=new_gentx,  # Litecoin coinbase transaction
                                            block_hash=header_hash,  # Litecoin block hash (NOT used by Dogecoin validation)
                                            merkle_link=ltc_coinbase_merkle_branch,  # Merkle branch from LTC coinbase to LTC merkle root
                                        ),
                                        merkle_link=aux_merkle_link,  # FIXED: Merkle branch from DOGE block hash to aux merkle root
                                        parent_block_header=litecoin_header_for_auxpow,  # Litecoin block header
                                    )
                                )
                                
                                auxpow = merged_block['auxpow']
                                
                                # Pack complete auxpow block for submission
                                # Dogecoin auxpow block format: header + auxpow + transactions
                                # The auxpow must be serialized immediately after the header (before txs)
                                # because CBlock serialization includes auxpow in the header section
                                header_packed = bitcoin_data.block_header_type.pack(merged_block['header'])
                                
                                # Debug: Uncomment to trace Dogecoin block header target verification
                                # doge_header_target = merged_block['header']['bits'].target
                                # doge_version = merged_block['header']['version']
                                # print >>sys.stderr, 'Dogecoin block version=0x%x (auxpow bit set: %s)' % (
                                #     doge_version, 
                                #     'YES' if (doge_version & 0x100) else 'NO'
                                # )
                                # print >>sys.stderr, 'Dogecoin block header bits.target=%064x' % doge_header_target
                                # print >>sys.stderr, 'aux_work target=%064x' % aux_work['target']
                                # print >>sys.stderr, 'Litecoin POW hash=%064x' % pow_hash
                                # # Use integer division to avoid float overflow
                                # ratio_pct = (pow_hash * 100) // doge_header_target if doge_header_target > 0 else 0
                                # print >>sys.stderr, 'Does LTC hash meet DOGE header target? %s (ratio=%d%%)' % (
                                #     pow_hash <= doge_header_target,
                                #     ratio_pct
                                # )
                                
                                # Debug: Show Litecoin header details
                                ltc_header_packed = bitcoin_data.block_header_type.pack(litecoin_header_for_auxpow)
                                ltc_header_hash_from_packed = self.node.net.PARENT.POW_FUNC(ltc_header_packed)
                                # Debug: Uncomment to trace Litecoin header in auxpow
                                # print >>sys.stderr, '[DEBUG] Litecoin header in auxpow:'
                                # print >>sys.stderr, '[DEBUG]   version: 0x%08x' % litecoin_header_for_auxpow['version']
                                # print >>sys.stderr, '[DEBUG]   previous_block: %064x' % litecoin_header_for_auxpow['previous_block']
                                # print >>sys.stderr, '[DEBUG]   merkle_root: %064x' % litecoin_header_for_auxpow['merkle_root']
                                # print >>sys.stderr, '[DEBUG]   timestamp: %d' % litecoin_header_for_auxpow['timestamp']
                                # print >>sys.stderr, '[DEBUG]   bits: 0x%08x' % litecoin_header_for_auxpow['bits'].bits
                                # print >>sys.stderr, '[DEBUG]   nonce: 0x%08x' % litecoin_header_for_auxpow['nonce']
                                # print >>sys.stderr, '[DEBUG]   POW hash (recalculated): %064x' % ltc_header_hash_from_packed
                                # print >>sys.stderr, '[DEBUG]   POW hash (original): %064x' % pow_hash
                                # print >>sys.stderr, '[DEBUG]   Do they match? %s' % (ltc_header_hash_from_packed == pow_hash)
                                
                                auxpow_packed = bitcoin_data.aux_pow_type.pack(auxpow)
                                
                                # Debug: Uncomment to trace coinbase hash in auxpow
                                # packed_coinbase_in_auxpow = bitcoin_data.tx_id_type.pack(new_gentx)
                                # coinbase_hash_from_auxpow = bitcoin_data.hash256(packed_coinbase_in_auxpow)
                                # print >>sys.stderr, '[DEBUG] Coinbase hash (from new_packed_gentx): %064x' % ltc_coinbase_hash
                                # print >>sys.stderr, '[DEBUG] Coinbase hash (from tx_id_type.pack): %064x' % coinbase_hash_from_auxpow
                                # print >>sys.stderr, '[DEBUG] Do auxpow coinbase hashes match? %s' % (ltc_coinbase_hash == coinbase_hash_from_auxpow)
                                # print >>sys.stderr, '[DEBUG] packed_coinbase_in_auxpow length: %d' % len(packed_coinbase_in_auxpow)
                                # print >>sys.stderr, '[DEBUG] new_packed_gentx length: %d' % len(new_packed_gentx)
                                # if packed_coinbase_in_auxpow != new_packed_gentx:
                                #     print >>sys.stderr, '[ERROR] Coinbase bytes MISMATCH in auxpow!'
                                #     print >>sys.stderr, '[DEBUG] tx_id_type.pack(new_gentx)[:100]: %s' % packed_coinbase_in_auxpow[:100].encode('hex')
                                #     print >>sys.stderr, '[DEBUG] new_packed_gentx[:100]: %s' % new_packed_gentx[:100].encode('hex')
                                
                                # Pack transactions
                                import StringIO
                                txs_stream = StringIO.StringIO()
                                pack.ListType(bitcoin_data.tx_type).write(txs_stream, merged_block['txs'])
                                txs_packed = txs_stream.getvalue()
                                
                                # Correct Dogecoin auxpow block format: header + auxpow + transactions
                                complete_block = header_packed + auxpow_packed + txs_packed
                                complete_block_hex = complete_block.encode('hex')
                                
                                # Debug: Uncomment to trace block submission details
                                # print >>sys.stderr, 'Submitting Dogecoin auxpow block:'
                                # print >>sys.stderr, '  Block hex length: %d bytes' % len(complete_block)
                                # print >>sys.stderr, '  Header (first 80 bytes): %s' % complete_block[:80].encode('hex')
                                # print >>sys.stderr, '  Bits field in header (bytes 72-76): %s' % complete_block[72:76].encode('hex')
                                # print >>sys.stderr, '  Parent header nonce in auxpow: 0x%08x' % header['nonce']
                                # import struct
                                # bits_packed = struct.unpack('<I', complete_block[72:76])[0]
                                # print >>sys.stderr, '  Bits as uint32 (little-endian): 0x%08x' % bits_packed
                                # print >>sys.stderr, '  [DEBUG] Full block hex (for manual decode):'
                                # print >>sys.stderr, '  %s' % complete_block_hex
                                # print >>sys.stderr, '  [DEBUG] Auxpow packed length: %d bytes' % len(auxpow_packed)
                                # print >>sys.stderr, '  [DEBUG] Auxpow hex: %s' % auxpow_packed.encode('hex')
                                
                                # Compare parent header in auxpow with what we hashed
                                parent_header_in_auxpow = bitcoin_data.block_header_type.pack(header).encode('hex')
                                if hasattr(self, '_last_hashed_header_hex'):
                                    if parent_header_in_auxpow == self._last_hashed_header_hex:
                                        pass  # Debug: Uncomment to verify - print >>sys.stderr, '  [OK] Parent header matches hashed header'
                                    else:
                                        print >>sys.stderr, '  [ERROR] Parent header MISMATCH!'
                                        print >>sys.stderr, '    Hashed:  %s' % self._last_hashed_header_hex
                                        print >>sys.stderr, '    In aux:  %s' % parent_header_in_auxpow
                                
                                # Submit via submitblock (modified Dogecoin with getblocktemplate auxpow support)
                                # Debug: Uncomment to trace submission
                                # print 'Submitting multiaddress merged block via submitblock...'
                                # print 'Block size: %d bytes (header + auxpow + %d txs)' % (len(complete_block), len(merged_block['txs']))
                                # print '[DEBUG] About to call rpc_submitblock with %d byte hex string' % (len(complete_block_hex),)
                                # print '[DEBUG] Block hex (first 200 chars): %s...' % (complete_block_hex[:200],)
                                
                                # Fire parallel broadcast via merged broadcaster (non-blocking)
                                chainid = aux_work.get('chainid', 98)
                                if chainid in self.node.merged_broadcasters:
                                    try:
                                        bc = self.node.merged_broadcasters[chainid]
                                        bc_d = bc.broadcast_block(complete_block_hex, aux_work['hash'])
                                        bc_d.addErrback(lambda f: None)  # Ignore broadcaster errors
                                    except Exception as e:
                                        print >>sys.stderr, 'Merged broadcaster error: %s' % e
                                
                                df = deferral.retry('Error submitting multiaddress merged block: (will retry)', 10, 10)(
                                    aux_work['merged_proxy'].rpc_submitblock
                                )(complete_block_hex)
                                
                                @df.addCallback
                                def _(result, aux_work=aux_work):
                                    # Debug: Uncomment to trace RPC result - print '[DEBUG] rpc_submitblock returned: %r (type: %s)' % (result, type(result))
                                    if result is None or result == True:
                                        print
                                        print '#' * 70
                                        print '### MERGED NETWORK BLOCK FOUND! ###'
                                        # Get merged network info from aux_work
                                        merged_net_name = aux_work.get('merged_net_name', 'Unknown')
                                        merged_net_symbol = aux_work.get('merged_net_symbol', 'UNKNOWN')
                                        print '### Network: %s (%s) ###' % (merged_net_name, merged_net_symbol)
                                        print '#' * 70
                                        print 'Time:        %s' % time.strftime('%Y-%m-%d %H:%M:%S')
                                        print 'Miner:       %s' % user
                                        print 'Block hash:  %064x' % aux_work['hash']
                                        print 'POW hash:    %064x' % pow_hash
                                        print 'Target:      %064x' % aux_work['target']
                                        print 'Txs:         %d' % len(merged_block['txs'])
                                        print 'Block size:  %d bytes' % len(complete_block)
                                        print '#' * 70
                                        print
                                        
                                        # Record merged block find
                                        block_record = dict(
                                            ts=time.time(),
                                            hash='%064x' % aux_work['hash'],
                                            pow_hash='%064x' % pow_hash,
                                            target='%064x' % aux_work['target'],
                                            network=merged_net_name,
                                            symbol=merged_net_symbol,
                                            miner=user,
                                            chainid=aux_work.get('chainid', 0),
                                            txs=len(merged_block['txs']),
                                            size=len(complete_block),
                                            verified=None,  # None=pending, True=confirmed, False=orphaned
                                        )
                                        self.recent_merged_blocks.append(block_record)
                                        # Keep only last 100 merged blocks
                                        if len(self.recent_merged_blocks) > 100:
                                            self.recent_merged_blocks = self.recent_merged_blocks[-100:]
                                        
                                        # Async verification after a delay
                                        if 'merged_proxy' in aux_work:
                                            def verify_block(block_rec, proxy, block_hash):
                                                verify_df = proxy.rpc_getblock('%064x' % block_hash)
                                                @verify_df.addCallback
                                                def on_verify(block_info):
                                                    block_rec['verified'] = True
                                                    print 'Merged block VERIFIED in chain: %064x' % block_hash
                                                @verify_df.addErrback
                                                def on_verify_fail(err):
                                                    block_rec['verified'] = False
                                                    print >>sys.stderr, 'Merged block orphaned (not in chain): %064x' % block_hash
                                            reactor.callLater(5.0, verify_block, block_record, aux_work['merged_proxy'], aux_work['hash'])
                                    else:
                                        print >>sys.stderr, 'Multiaddress merged block rejected: %s' % (result,)
                                
                                @df.addErrback
                                def _(err):
                                    # Debug: Uncomment to trace RPC errors - print >>sys.stderr, '[DEBUG] rpc_submitblock raised error: %s' % (err,)
                                    log.err(err, 'Error submitting multiaddress merged block:')
                                    
                            except Exception as e:
                                print >>sys.stderr, 'Error building multiaddress merged block: %s' % (e,)
                                log.err(None, 'Error building multiaddress merged block:')
                        else:
                            # Standard getauxblock submission (backward compatible)
                            # Choose submission method based on how we got the work
                            # If we used createauxblock, use submitauxblock; otherwise use getauxblock
                            auxpow_hex = bitcoin_data.aux_pow_type.pack(dict(
                                merkle_tx=dict(
                                    tx=new_gentx,
                                    block_hash=header_hash,
                                    merkle_link=merkle_link,
                                ),
                                merkle_link=bitcoin_data.calculate_merkle_link(hashes, index),
                                parent_block_header=header,
                            )).encode('hex')
                            hash_hex = pack.IntType(256, 'big').pack(aux_work['hash']).encode('hex')
                            
                            if aux_work.get('use_submitauxblock'):
                                df = deferral.retry('Error submitting merged block via submitauxblock: (will retry)', 10, 10)(aux_work['merged_proxy'].rpc_submitauxblock)(
                                    hash_hex,
                                    auxpow_hex,
                                )
                            else:
                                df = deferral.retry('Error submitting merged block: (will retry)', 10, 10)(aux_work['merged_proxy'].rpc_getauxblock)(
                                    hash_hex,
                                    auxpow_hex,
                                )
                            @df.addCallback
                            def _(result, aux_work=aux_work, pow_hash=pow_hash, user=user):
                                if result != (pow_hash <= aux_work['target']):
                                    print >>sys.stderr, 'Merged block submittal result: %s Expected: %s' % (result, pow_hash <= aux_work['target'])
                                else:
                                    print 'Merged block submittal result: %s' % (result,)
                                    # Record merged block find if successful
                                    if result == True:
                                        # Get network info - for single-address mode we may not have full info
                                        chainid = aux_work.get('chainid', 0)
                                        merged_net_name = aux_work.get('merged_net_name', 'Dogecoin' if chainid == 98 else 'Unknown')
                                        merged_net_symbol = aux_work.get('merged_net_symbol', 'DOGE' if chainid == 98 else 'UNKNOWN')
                                        
                                        # Detect testnet from parent chain symbol
                                        parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                                        is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
                                        
                                        # Convert miner address to merged chain format
                                        miner_merged_address = user  # Default to original
                                        try:
                                            if chainid == 98:  # Dogecoin
                                                merged_net = dogecoin_testnet_net if is_testnet else dogecoin_net
                                                if merged_net:
                                                    parent_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                                    is_convertible, pubkey_hash, _ = is_pubkey_hash_address(user, parent_net)
                                                    if is_convertible and pubkey_hash:
                                                        miner_merged_address = bitcoin_data.pubkey_hash_to_address(
                                                            pubkey_hash, merged_net.ADDRESS_VERSION, -1, merged_net)
                                        except Exception as e:
                                            pass  # Keep original address on error
                                        
                                        # Create block record
                                        block_record = dict(
                                            ts=time.time(),
                                            hash='%064x' % aux_work['hash'],
                                            pow_hash='%064x' % pow_hash,
                                            target='%064x' % aux_work['target'],
                                            network=merged_net_name,
                                            symbol=merged_net_symbol,
                                            miner=miner_merged_address,
                                            miner_parent=user,  # Also store original parent chain address
                                            chainid=chainid,
                                            is_testnet=is_testnet,
                                            verified=None,  # None=pending, True=confirmed, False=orphaned
                                        )
                                        self.recent_merged_blocks.append(block_record)
                                        # Keep only last 100 merged blocks
                                        if len(self.recent_merged_blocks) > 100:
                                            self.recent_merged_blocks = self.recent_merged_blocks[-100:]
                                        
                                        # For testnet: async verification after a delay
                                        # Use aux_work['hash'] (Dogecoin block hash) NOT pow_hash (scrypt hash)
                                        if is_testnet and 'merged_proxy' in aux_work:
                                            def verify_block(block_rec, proxy, block_hash):
                                                verify_df = proxy.rpc_getblock('%064x' % block_hash)
                                                @verify_df.addCallback
                                                def on_verify(block_info):
                                                    # Block found in chain - mark as verified
                                                    block_rec['verified'] = True
                                                    print 'Merged block VERIFIED in chain: %064x' % block_hash
                                                @verify_df.addErrback
                                                def on_verify_fail(err):
                                                    # Block not found - mark as orphaned
                                                    block_rec['verified'] = False
                                                    print >>sys.stderr, 'Merged block orphaned (not in chain): %064x' % block_hash
                                            # Use reactor.callLater to delay verification by 5 seconds
                                            # Pass aux_work['hash'] which is the Dogecoin block hash
                                            reactor.callLater(5.0, verify_block, block_record, aux_work['merged_proxy'], aux_work['hash'])
                            @df.addErrback
                            def _(err):
                                log.err(err, 'Error submitting merged block:')
                except:
                    log.err(None, 'Error while processing merged mining POW:')

            # P2Pool share creation - re-enabled for PERSIST=False bootstrap
            # Note: Stratum miners change coinbase_nonce which modifies gentx.
            # Share.__init__ reconstructs gentx and this should now work correctly.
            # CRITICAL: Only attempt share creation if merkle_root matches current work template!
            # If work_merkle_root != header['merkle_root'], the submitted work is stale (from old template)
            if pow_hash <= share_info['bits'].target and header_hash not in received_header_hashes and work_merkle_root == header['merkle_root']:
                # Debug: Uncomment to trace P2Pool share creation (prints on every share)
                # print >>sys.stderr, '[DEBUG] Attempting to create P2Pool share:'
                # print >>sys.stderr, '  pow_hash: %064x' % pow_hash
                # print >>sys.stderr, '  target:   %064x' % share_info['bits'].target
                # print >>sys.stderr, '  passes:   %s' % (pow_hash <= share_info['bits'].target)
                # print >>sys.stderr, '  header: %s' % header
                last_txout_nonce = pack.IntType(8*self.COINBASE_NONCE_LENGTH).unpack(coinbase_nonce)
                try:
                    share = get_share(header, last_txout_nonce)
                except Exception as e:
                    # print >>sys.stderr, '[DEBUG] get_share failed: %s' % e
                    # print >>sys.stderr, '[DEBUG] Recalculating pow_hash with header:'
                    # recalc_pow = self.node.net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(header))
                    # print >>sys.stderr, '  Recalc pow_hash: %064x' % recalc_pow
                    # print >>sys.stderr, '  Original pow_hash: %064x' % pow_hash
                    # print >>sys.stderr, '  Match: %s' % (recalc_pow == pow_hash)
                    raise

                print 'GOT SHARE! %s %s prev %s age %.2fs%s' % (
                    user,
                    p2pool_data.format_hash(share.hash),
                    p2pool_data.format_hash(share.previous_hash),
                    time.time() - getwork_time,
                    ' DEAD ON ARRIVAL' if not on_time else '',
                )
                self.my_share_hashes.add(share.hash)
                if not on_time:
                    self.my_doa_share_hashes.add(share.hash)

                self.node.tracker.add(share)
                self.node.set_best_share()
                
                # Broadcast share to P2P network
                try:
                    if (pow_hash <= header['bits'].target or p2pool.DEBUG) and self.node.p2p_node is not None:
                        self.node.p2p_node.broadcast_share(share.hash)
                except:
                    log.err(None, 'Error forwarding block solution:')

                self.share_received.happened(bitcoin_data.target_to_average_attempts(share.target), not on_time, share.hash)
                
                # Also trigger pseudoshare_received for graph recording
                # This ensures per-miner hashrate is tracked for shares too
                work_value = bitcoin_data.target_to_average_attempts(effective_target)
                self.pseudoshare_received.happened(work_value, not on_time, user)
                
                # Track best difficulty - calculate actual difficulty achieved by this share
                share_difficulty = bitcoin_data.target_to_difficulty(pow_hash)
                self.update_best_difficulty(user, share_difficulty)
                
                # Update local rate monitor for shares (they are also pseudoshares)
                # Use effective_target (vardiff target) for work calculation
                self.local_rate_monitor.add_datum(dict(work=bitcoin_data.target_to_average_attempts(effective_target), dead=not on_time, user=user, share_target=share_info['bits'].target))
                self.local_addr_rate_monitor.add_datum(dict(work=bitcoin_data.target_to_average_attempts(effective_target), pubkey_hash=pubkey_hash))
                received_header_hashes.add(header_hash)
            elif pow_hash <= share_info['bits'].target and work_merkle_root != header['merkle_root']:
                # Stale work - share meets P2Pool difficulty but merkle_root mismatch
                # This means the miner submitted work based on an old template
                # We still count it for hash rate but don't create a share
                print >>sys.stderr, 'Worker %s submitted P2Pool-quality share on stale work template' % (user,)
                self.local_rate_monitor.add_datum(dict(work=bitcoin_data.target_to_average_attempts(effective_target), dead=True, user=user, share_target=share_info['bits'].target))
                self.local_addr_rate_monitor.add_datum(dict(work=bitcoin_data.target_to_average_attempts(effective_target), pubkey_hash=pubkey_hash))
                received_header_hashes.add(header_hash)
            elif pow_hash > effective_target:
                print 'Worker %s submitted share with hash > target:' % (user,)
                print '    Hash:   %56x' % (pow_hash,)
                print '    Target: %56x' % (effective_target,)
            elif header_hash in received_header_hashes:
                print >>sys.stderr, 'Worker %s submitted share more than once!' % (user,)
            else:
                received_header_hashes.add(header_hash)

                work_value = bitcoin_data.target_to_average_attempts(effective_target)
                self.pseudoshare_received.happened(work_value, not on_time, user)
                self.recent_shares_ts_work.append((time.time(), work_value))
                while len(self.recent_shares_ts_work) > 50:
                    self.recent_shares_ts_work.pop(0)
                self.local_rate_monitor.add_datum(dict(work=work_value, dead=not on_time, user=user, share_target=share_info['bits'].target))
                self.local_addr_rate_monitor.add_datum(dict(work=work_value, pubkey_hash=pubkey_hash))
                
                # Track best difficulty for pseudoshares too
                share_difficulty = bitcoin_data.target_to_difficulty(pow_hash)
                self.update_best_difficulty(user, share_difficulty)

            return on_time

        t1 = time.time()
        if p2pool.BENCH:
            print "%8.3f ms for work.py:get_work(%s)" % ((t1-t0)*1000., bitcoin_data.pubkey_hash_to_address(pubkey_hash, self.node.net.PARENT.ADDRESS_VERSION, -1, self.node.net.PARENT))
        
        return ba, got_response
