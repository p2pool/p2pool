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
# Dogecoin testnet4alpha: quickfix for unreliable official Dogecoin testnet.
# The official DOGE testnet suffers from block storms (extreme difficulty drops causing
# thousands of blocks per minute), making it unusable for merged mining development.
# testnet4alpha (Dogecoin PR #3967) adds fEnforceStrictMinDifficulty=true to prevent this.
# Key differences from regular testnet:
#   - P2P magic: d4a1f4a1 (vs fcc1b7dc for regular testnet)
#   - P2P port: 44557 (vs 44556)
#   - chain id in getblockchaininfo: 'testnet4alpha' (vs 'test')
# Detection: when --merged-coind-p2p-port is 44557, we use testnet4alpha network params.
# For mainnet: uses dogecoin_net (magic c0c0c0c0, port 22556) — no change needed.
try:
    from p2pool.bitcoin.networks import dogecoin_testnet4alpha as dogecoin_testnet4alpha_net
    print >>sys.stderr, '[IMPORT] Successfully imported dogecoin_testnet4alpha: %s' % dogecoin_testnet4alpha_net
except ImportError as e:
    print >>sys.stderr, '[IMPORT] Failed to import dogecoin_testnet4alpha: %s' % e
    dogecoin_testnet4alpha_net = None
try:
    from p2pool.bitcoin.networks import dogecoin as dogecoin_net
    print >>sys.stderr, '[IMPORT] Successfully imported dogecoin: %s' % dogecoin_net
except ImportError as e:
    print >>sys.stderr, '[IMPORT] Failed to import dogecoin: %s' % e
    dogecoin_net = None

print_throttle = 0.0

def is_pubkey_hash_address(address, net):
    """
    Check if an address can be converted to merged chain addresses.
    
    =================================================================================
    MERGED MINING ADDRESS CONVERSION - TECHNICAL EXPLANATION
    =================================================================================
    
    When P2Pool performs merged mining (e.g., Litecoin + Dogecoin), miner payouts need
    to be distributed on BOTH chains. However, miners only provide a Litecoin address.
    
    To create the Dogecoin payout address, we extract the 20-byte hash from the
    Litecoin address and re-encode it with the Dogecoin address version.
    
    CONVERTIBLE ADDRESS TYPES:
    --------------------------
    1. P2PKH (Pay-to-Public-Key-Hash) - Legacy addresses
       - Litecoin: starts with 'L' (mainnet) or 'm/n' (testnet)
       - Format: Base58Check(version || HASH160(pubkey))
       - The 20-byte HASH160(pubkey) is re-encoded as DOGE P2PKH
       - addr_type: 'p2pkh'
    
    2. P2WPKH (Pay-to-Witness-Public-Key-Hash) - Native SegWit v0
       - Litecoin: starts with 'ltc1q' followed by 39 more chars (43 total)
       - Format: Bech32(hrp, version=0, witness_program=HASH160(pubkey))
       - The 20-byte witness program IS the pubkey_hash → re-encoded as DOGE P2PKH
       - addr_type: 'p2pkh'
    
    3. P2SH (Pay-to-Script-Hash) - Legacy script addresses
       - Litecoin: starts with 'M' or '3' (mainnet) or '2' (testnet)
       - Format: Base58Check(p2sh_version || HASH160(script))
       - The 20-byte script_hash is re-encoded as DOGE P2SH
       - addr_type: 'p2sh'
       - CAVEAT: the redeem script must use opcodes supported by the merged chain.
         P2SH-P2WPKH (SegWit wrapped in P2SH) will be unspendable on chains
         without SegWit support (e.g., Dogecoin). For standard multisig P2SH,
         conversion works correctly since both chains support the same opcodes.
    
    NON-CONVERTIBLE ADDRESS TYPES:
    -------------------------------------------------------------------------
    4. P2WSH (Pay-to-Witness-Script-Hash) - Native SegWit script addresses
       - Litecoin: starts with 'ltc1q' followed by ~59 more chars (62 total)
       - Format: Bech32(hrp, version=0, witness_program=SHA256(script))
       - 32-byte SHA256 hash — CANNOT be re-encoded as 20-byte hash
    
    5. P2TR (Pay-to-Taproot) - Taproot addresses (witness v1)
       - Litecoin: starts with 'ltc1p...'
       - Format: Bech32m(hrp, version=1, tweaked_pubkey)
       - 32-byte tweaked public key — CANNOT be safely converted
    
    P2WPKH vs P2WSH DETECTION:
    --------------------------
    Both P2WPKH and P2WSH use witness version 0 and start with 'ltc1q'.
    The difference is the witness program length:
    - P2WPKH: 20 bytes (HASH160) -> 43 character address
    - P2WSH:  32 bytes (SHA256)  -> 62 character address
    
    We detect this by checking if the pubkey_hash value exceeds 2^160-1.
    A legitimate 20-byte hash will never exceed this, while a 32-byte hash
    almost certainly will (probability of false negative: 1 in 2^96).
    
    Returns: (is_convertible, hash_value, error_message, addr_type)
    - is_convertible: True if address can be converted to merged chain
    - hash_value: The 160-bit hash (int) if convertible, None otherwise
    - error_message: Human-readable error if not convertible, None otherwise
    - addr_type: 'p2pkh' or 'p2sh' — indicates which output script type to use
      (only present when is_convertible is True; callers should default to 'p2pkh')
    =================================================================================
    """
    try:
        pubkey_hash, version, witver = bitcoin_data.address_to_pubkey_hash(address, net)
        
        # Check for P2SH (script hash, not pubkey hash)
        # P2SH addresses CAN be converted to merged chain P2SH addresses.
        # The 20-byte script_hash is re-encoded with the merged chain's P2SH version.
        # Caveat: the redeem script must use opcodes supported by both chains.
        # P2SH-P2WPKH (SegWit wrapped in P2SH) may be unspendable on chains without
        # SegWit support (e.g., Dogecoin), but we trust the miner to know their setup.
        if version == net.ADDRESS_P2SH_VERSION:
            return (True, pubkey_hash, None, 'p2sh')
        
        # Check for P2WPKH vs P2WSH (both are witness v0, but different lengths)
        if witver == 0:
            # Witness v0: P2WPKH is 20 bytes (max value 2^160-1), P2WSH is 32 bytes (max value 2^256-1)
            # A 32-byte value will always be > 2^160-1 if any of the upper 12 bytes are non-zero
            # This is a probabilistic check - a P2WSH hash that happens to have all upper
            # 12 bytes as zero would pass, but this is astronomically unlikely (1 in 2^96)
            if pubkey_hash > (1 << 160) - 1:  # Larger than 20 bytes can represent
                return (False, None, 'P2WSH address (32-byte script hash) cannot be converted to merged chain')
            else:
                return (True, pubkey_hash, None, 'p2pkh')  # P2WPKH - convertible (same pubkey_hash)
        
        # Check for Taproot (witness v1) - not convertible (32-byte tweaked pubkey)
        if witver == 1:
            return (False, None, 'P2TR address (taproot) cannot be converted to merged chain')
        
        # Higher witness versions (future segwit) - not convertible for safety
        if witver > 1:
            return (False, None, 'Unknown witness version %d - cannot convert to merged chain' % witver)
        
        # P2PKH (legacy) - convertible
        if version == net.ADDRESS_VERSION:
            return (True, pubkey_hash, None, 'p2pkh')
        
        # Unknown address type
        return (False, None, 'Unknown address type (version=%s, witver=%s)' % (version, witver))
        
    except Exception as e:
        return (False, None, 'Failed to parse address: %s' % str(e))

class WorkerBridge(worker_interface.WorkerBridge):
    COINBASE_XNONCE1_LENGTH = 1
    COINBASE_NONCE_LENGTH = 8

    def __init__(self, node, my_pubkey_hash, donation_percentage, merged_urls, worker_fee, args, pubkeys, bitcoind, share_rate, my_pubkey_type=0):
        worker_interface.WorkerBridge.__init__(self)
        self.recent_shares_ts_work = []

        self.node = node

        self.bitcoind = bitcoind
        self.pubkeys = pubkeys
        self.args = args
        self.my_pubkey_hash = my_pubkey_hash
        self.my_pubkey_type = my_pubkey_type  # V36: 0=P2PKH, 1=P2WPKH/bech32, 2=P2SH
		
        self.donation_percentage = args.donation_percentage
        self.node_owner_fee = getattr(args, 'node_owner_fee', worker_fee)
        self.worker_fee = self.node_owner_fee
        self.merged_operator_address = getattr(args, 'merged_operator_address', None)

        # V36 transition messaging: pre-packed message_data for embedding in shares
        self.transition_message_data = self._prepare_transition_message(args)

        # AutoRatchet: automated V35->V36 share version management
        # Persists activation state to disk so restarts don't regress
        net_name = self.node.net.NAME
        if hasattr(args, 'datadir') and args.datadir:
            ratchet_datadir = os.path.join(args.datadir, net_name)
        else:
            ratchet_datadir = os.path.join(os.path.dirname(sys.argv[0]), 'data', net_name)
        self.auto_ratchet = p2pool_data.AutoRatchet(ratchet_datadir)
        print '[WorkerBridge] AutoRatchet initialized: %s' % self.auto_ratchet

        # Redistribute mode for unnamed/broken miner shares
        self._redistribute_mode = getattr(args, 'redistribute_mode', 'pplns')
        print '[WorkerBridge] Redistribute mode: %s (--redistribute)' % self._redistribute_mode

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
        
        # Track best difficulty per miner (all-time, session, and current round)
        # Format: {user: {'all_time': diff, 'session': diff, 'round': diff, ...}}
        self.miner_best_difficulty = {}
        self.session_start_time = time.time()
        
        # Node-wide best difficulty tracking (across all miners)
        self.node_best_difficulty = {
            'all_time': 0,           # Never resets (absolute record)
            'all_time_user': None,   # Who achieved it
            'all_time_ts': 0,        # When
            'session': 0,            # Resets on restart
            'session_user': None,
            'session_ts': 0,
            'round': 0,              # Resets when pool finds a block
            'round_user': None,
            'round_ts': 0,
            'round_start': time.time(),
        }
        # Merged chain (DOGE) best difficulty tracking
        self.merged_best_difficulty = {
            'all_time': 0,
            'all_time_user': None,
            'all_time_ts': 0,
            'round': 0,              # Resets when pool finds a DOGE block
            'round_user': None,
            'round_ts': 0,
            'round_start': time.time(),
        }

        self.removed_unstales_var = variable.Variable((0, 0, 0))
        self.removed_doa_unstales_var = variable.Variable(0)

        self.last_work_shares = variable.Variable( {} )

        self.my_share_hashes = set()
        self.my_doa_share_hashes = set()
        
        # Track recently found merged mined blocks
        self.recent_merged_blocks = []

        # --- Miner address caches ---
        # Avoids re-parsing the same address on every get_work() call.
        # Keyed by (user_string, merged_addr_key) — invalidated when miner reconnects with different address.
        self._miner_addr_cache = {}      # user -> (pubkey_hash, pubkey_type, is_convertible, addr_type, error_msg)
        self._miner_merged_cache = {}    # user -> list of {chain_id, script} entries (auto-generated)
        self._miner_merged_display_cache = {}  # user -> {chain_name: address_string} (auto-converted display addresses)
        self._merged_net_cache = {}      # chain_id -> net object (constant for entire run)
        self._merged_chain_name_cache = {} # chain_id -> name string (constant for entire run)

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
            
            # Merged daemon warnings (polled periodically via getnetworkinfo)
            merged_daemon_warnings = ''
            merged_daemon_warnings_last_poll = 0
            MERGED_WARNING_POLL_INTERVAL = 5 * 60  # 5 minutes
            
            # Lightweight pre-check: skip expensive GBT+coinbase rebuild when
            # the merged chain tip hasn't changed.  getbestblockhash returns a
            # single 64-char hex string and is orders of magnitude cheaper than
            # a full getblocktemplate call + PPLNS + coinbase + merkle rebuild.
            # We still do a full refresh every MERGED_FULL_REFRESH_INTERVAL
            # seconds so that mempool transactions stay reasonably up-to-date.
            # 5s balances CPU savings (~80% reduction) with transaction freshness
            # (DOGE has 1-min blocks, so ~12 refreshes per block is plenty).
            _cached_best_block_hash = None
            _last_full_refresh = 0
            MERGED_FULL_REFRESH_INTERVAL = 5  # seconds between full template refreshes
            
            while self.running:
                try:
                    # --- Lightweight tip check (skip heavy work if nothing changed) ---
                    now = time.time()
                    try:
                        _tip_hash = yield merged_proxy.rpc_getbestblockhash()
                    except Exception:
                        _tip_hash = None  # RPC failed; fall through to full refresh
                    
                    if (_tip_hash is not None
                            and _tip_hash == _cached_best_block_hash
                            and now - _last_full_refresh < MERGED_FULL_REFRESH_INTERVAL):
                        # Tip unchanged and we refreshed recently — skip heavy work
                        yield deferral.sleep(1)
                        continue
                    
                    # Tip changed or periodic refresh due — do full GBT cycle
                    _cached_best_block_hash = _tip_hash
                    
                    # Poll merged daemon warnings periodically
                    if time.time() - merged_daemon_warnings_last_poll > MERGED_WARNING_POLL_INTERVAL:
                        try:
                            merged_netinfo = yield merged_proxy.rpc_getnetworkinfo()
                            merged_daemon_warnings = merged_netinfo.get('warnings', '')
                            merged_daemon_warnings_last_poll = time.time()
                        except Exception:
                            pass  # Non-critical: daemon may not support getnetworkinfo
                    
                    # First, try getblocktemplate with auxpow capability (multiaddress support)
                    if auxpow_capable is None or auxpow_capable:
                        template = yield deferral.retry('Error while calling merged getblocktemplate on %s:' % (merged_url,), 30)(
                            merged_proxy.rpc_getblocktemplate
                        )({"capabilities": ["auxpow"]})
                        
                        # Check if auxpow is supported (modified Dogecoin with multiaddress)
                        if 'auxpow' in template:
                            if auxpow_capable is None:
                                print 'Detected auxpow-capable merged mining daemon at %s (multiaddress support enabled)' % (merged_url,)
                                print '[STARTUP-OK] Merged mining mode: MULTIADDRESS (getblocktemplate+auxpow)'
                                print '[STARTUP-OK] Chain ID: %s' % template['auxpow'].get('chainid', '?')
                                print '[STARTUP-OK] Template height: %s' % template.get('height', '?')
                            auxpow_capable = True
                            
                            chainid = template['auxpow']['chainid']
                            # CRITICAL: template['auxpow']['target'] is LE hex (Dogecoin internal format)
                            # but template['target'] is BE hex (standard getblocktemplate format).
                            # Use template['target'] so int(target_hex, 16) gives the correct value.
                            target_hex = template['target']
                            
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
                                        # Get local Dogecoin node's P2P address from args
                                        # --merged-coind-p2p-address overrides --merged-coind-address for P2P
                                        # This allows RPC to go to mm-adapter (e.g. 127.0.0.1) while P2P goes to the actual node (e.g. DOGE_DAEMON_IP)
                                        merged_p2p_port = getattr(self.args, 'merged_coind_p2p_port', None)
                                        merged_p2p_address = getattr(self.args, 'merged_coind_p2p_address', None) or getattr(self.args, 'merged_coind_address', None)
                                        
                                        if parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower():
                                            # Network selection for DOGE testnet broadcaster P2P:
                                            #   port 44557 → testnet4alpha (magic d4a1f4a1) — quickfix for block storm bug
                                            #   port 44556 → regular testnet (magic fcc1b7dc)
                                            # Wrong magic = daemon drops connection silently (handshake never completes)
                                            if merged_p2p_port == 44557 and dogecoin_testnet4alpha_net:
                                                chain_name = 'dogecoin_testnet4alpha'
                                                p2p_net = dogecoin_testnet4alpha_net
                                                p2p_port = 44557
                                                print 'MergedBroadcaster: Using dogecoin_testnet4alpha network (P2P magic d4a1f4a1, port 44557)'
                                            else:
                                                chain_name = 'dogecoin_testnet'
                                                p2p_net = dogecoin_testnet_net
                                                p2p_port = 44556 if dogecoin_testnet_net else None
                                        else:
                                            p2p_net = dogecoin_net
                                            p2p_port = 22556 if dogecoin_net else None
                                        
                                        if merged_p2p_port and merged_p2p_address:
                                            local_p2p_addr = (merged_p2p_address, merged_p2p_port)
                                            print 'MergedBroadcaster will connect to our Dogecoin node at %s:%d' % (merged_p2p_address, merged_p2p_port)
                                    
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
                                merged_donation_percentage = self.donation_percentage
                                
                                # Skip PPLNS when there are no previous shares (bootstrap phase)
                                # Allow previous_share_hash to be None - get_cumulative_weights handles it
                                try:
                                    if (previous_share is not None and 
                                        hasattr(previous_share, 'share_data')):
                                        # Get PPLNS weights from share chain — V36 shares ONLY.
                                        # Pre-V36 shares are excluded from merged mining distribution
                                        # because V35 nodes don't build merged blocks. Their weight
                                        # is naturally redistributed to V36 miners (smaller denominator).
                                        #
                                        # CRITICAL: Use the PARENT chain's block target for max_weight,
                                        # NOT the child chain's target. The PPLNS window must match the
                                        # parent chain's window exactly so merged payouts mirror parent
                                        # economics (including node owner fee via share address replacement).
                                        # Using the child target would create a different-sized window,
                                        # causing distribution misalignment between parent and child.
                                        parent_block_target = self.current_work.value['bits'].target
                                        best_share_hash = self.node.best_share_var.value
                                        weights, total_weight, donation_weight = self._get_cached_merged_weights(
                                            chainid, self.node.tracker, best_share_hash, parent_block_target)
                                    
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
                                    #
                                    # Keys from get_v36_merged_weights() come in two forms:
                                    #   1. 'MERGED:<hex_script>' — explicit merged chain script from V36 share's
                                    #      merged_addresses field. No conversion needed; use script directly.
                                    #   2. Parent chain address string (from share.address) — needs auto-conversion
                                    #      from LTC to DOGE format. Unconvertible (P2SH, P2WSH, P2TR) are skipped.
                                    shareholders = {}
                                    accepted_weights = {}
                                    skipped_addresses = []
                                    accepted_total_weight = 0
                                    for key, weight in weights.iteritems():
                                        try:
                                            if key.startswith('MERGED:'):
                                                # Explicit merged chain script from V36 share's merged_addresses.
                                                # Pass through as-is — build_merged_coinbase() handles MERGED: prefix
                                                # by decoding the hex script directly (no address round-trip needed).
                                                accepted_weights[key] = accepted_weights.get(key, 0) + weight
                                                accepted_total_weight += weight
                                                continue
                                            
                                            # Parent chain address — check if convertible to merged chain
                                            key_is_address = len(key) >= 25 and len(key) <= 100 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' for c in key)
                                            
                                            if key_is_address:
                                                # VERSION >= 34: key is already a parent chain address string
                                                # Need to convert to merged chain address
                                                parent_address = key
                                                parent_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                                
                                                # Validate that address can be converted to merged chain
                                                # P2PKH and P2WPKH: auto-convert to merged P2PKH
                                                # P2SH: auto-convert to merged P2SH
                                                # P2WSH, P2TR: cannot be converted
                                                addr_result = is_pubkey_hash_address(parent_address, parent_net)
                                                is_convertible = addr_result[0]
                                                pubkey_hash = addr_result[1]
                                                error_msg = addr_result[2]
                                                addr_type = addr_result[3] if len(addr_result) > 3 else 'p2pkh'
                                                
                                                if not is_convertible:
                                                    # Cannot convert this address - skip it with warning
                                                    skipped_addresses.append((parent_address[:20] + '...', error_msg))
                                                    continue
                                                
                                                # Node operator override: if --merged-operator-address is set,
                                                # use it for the operator's own share of merged chain payout
                                                # instead of auto-converting from parent chain address.
                                                if parent_address == self.args.address and self.merged_operator_address:
                                                    override_addr = self._get_validated_merged_operator_address(merged_addr_net, chainid)
                                                    if override_addr is not None:
                                                        merged_address = override_addr
                                                    else:
                                                        # Validation failed — fall through to normal auto-conversion
                                                        if addr_type == 'p2sh':
                                                            merged_address = bitcoin_data.pubkey_hash_to_address(pubkey_hash, merged_addr_net.ADDRESS_P2SH_VERSION, -1, merged_addr_net)
                                                        else:
                                                            merged_address = bitcoin_data.pubkey_hash_to_address(pubkey_hash, merged_addr_net.ADDRESS_VERSION, -1, merged_addr_net)
                                                # Standard auto-conversion from parent chain address
                                                elif addr_type == 'p2sh':
                                                    merged_address = bitcoin_data.pubkey_hash_to_address(pubkey_hash, merged_addr_net.ADDRESS_P2SH_VERSION, -1, merged_addr_net)
                                                else:
                                                    merged_address = bitcoin_data.pubkey_hash_to_address(pubkey_hash, merged_addr_net.ADDRESS_VERSION, -1, merged_addr_net)
                                            else:
                                                # Older VERSION: key is P2PKH script
                                                merged_address = bitcoin_data.script2_to_address(key, merged_addr_net.ADDRESS_VERSION, -1, merged_addr_net)
                                            
                                            accepted_weights[merged_address] = accepted_weights.get(merged_address, 0) + weight
                                            accepted_total_weight += weight
                                        except Exception as e:
                                            pass  # Suppressed: print >>sys.stderr, '[MERGED] Warning: Could not convert key to address: %s' % e

                                    # Redistribute unconvertible-address rewards to convertible/provided addresses.
                                    # We do this by normalizing fractions over accepted_total_weight (not total_weight).
                                    # This ensures skipped weight is proportionally redistributed instead of leaking
                                    # into donation via rounding remainder.
                                    if accepted_total_weight > 0:
                                        for merged_address, accepted_weight in accepted_weights.iteritems():
                                            shareholders[merged_address] = float(accepted_weight) / float(accepted_total_weight)
                                    
                                    if skipped_addresses:
                                        # Summary only - suppress verbose per-address output
                                        pass  # Suppressed verbose output: print >>sys.stderr, '[MERGED] WARNING: %d miner address(es) skipped' % len(skipped_addresses)

                                    # In PPLNS mode, merged-chain payouts must mirror sharechain economics.
                                    # Derive donation ratio from global sharechain weights instead of local
                                    # node flags. Node operator economics come from the -f probabilistic
                                    # address replacement in share_data, not from a per-block fee.
                                    if total_weight > 0 and shareholders:
                                        merged_donation_percentage = 100.0 * float(donation_weight) / float(total_weight)
                                    
                                    pass  # Suppressed: print >>sys.stderr, '[MERGED] Using PPLNS distribution with %d shareholders from share chain' % len(shareholders)
                                except (KeyError, AttributeError, TypeError) as e:
                                    # Fall back to single address mode if PPLNS calculation fails
                                    # This is expected during bootstrap when share chain is empty or incomplete
                                    previous_share = None  # Force fallback path
                                
                                if previous_share is None or not shareholders:
                                    # Fallback: No shares yet, PPLNS failed, or no V36 shares in window.
                                    # Use single address mode — this V36 node operator gets 100%.
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
                                        # Convert pubkey_hash to merged chain address (respect P2SH)
                                        _m_ver = self._merged_addr_ver(self.my_pubkey_type, merged_addr_net)
                                        mining_address = bitcoin_data.pubkey_hash_to_address(
                                            self.my_pubkey_hash, _m_ver,
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
                                
                                # Build coinbase with P2Pool donation (no per-block node owner fee)
                                # Node operator economics come entirely from the -f probabilistic
                                # address replacement in share_data, which flows through PPLNS weights.
                                # Pass parent_net for automatic address conversion (LTC -> DOGE)
                                # Pass coinbase_text from adapter template (if provided)
                                # Pass v36_active for donation script selection (pre-V36 vs post-V36)
                                parent_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                coinbase_text = template.get('auxpow', {}).get('coinbase_text')  # From MM adapter
                                v36_active, _ = self.is_v36_active()
                                pass  # Suppressed: print >>sys.stderr, '[MERGED] Calling build_merged_coinbase with net=%s (ADDRESS_VERSION=%d), parent_net=%s' % (merged_addr_net.SYMBOL, merged_addr_net.ADDRESS_VERSION, parent_net.SYMBOL)
                                doge_coinbase_tx = merged_mining.build_merged_coinbase(
                                    template, shareholders, merged_addr_net, merged_donation_percentage,
                                    parent_net=parent_net, coinbase_text=coinbase_text,
                                    v36_active=v36_active)
                                
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
                            # target_hex comes from template['target'] (BE hex), so int() works directly.
                            parsed_target = int(target_hex, 16)
                            pass  # Suppressed: print '[DEBUG] Dogecoin target from template: %064x' % parsed_target
                            
                            # Determine network name from chainid
                            merged_net_name = 'Dogecoin'
                            merged_net_symbol = 'DOGE'
                            if chainid == 98:  # Dogecoin
                                parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
                                if parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower():
                                    merged_net_name = 'Dogecoin Testnet'
                                    merged_net_symbol = 'tDOGE'
                            
                            old_work = self.merged_work.value.get(chainid, {})
                            old_prev = old_work.get('previousblockhash', '')
                            new_prev = template.get('previousblockhash', '')
                            
                            new_merged_entry = dict(
                                template=template,
                                hash=doge_block_hash,  # CRITICAL: This hash gets embedded in Litecoin coinbase
                                previousblockhash=new_prev,  # Track for change detection
                                target=parsed_target,
                                merged_proxy=merged_proxy,
                                multiaddress=True,
                                doge_header=doge_header,  # Save for later when building final block
                                doge_coinbase=doge_coinbase_tx,
                                doge_tx_hashes=all_doge_tx_hashes,
                                merged_net_name=merged_net_name,  # Store network name for block found message
                                merged_net_symbol=merged_net_symbol,  # Store network symbol for block found message
                                shareholders=shareholders,  # PPLNS distribution for miner payout calculation
                                    donation_percentage=merged_donation_percentage,
                                finder_fee_percentage=0.5,
                                daemon_warnings=merged_daemon_warnings,
                                last_update=time.time(),
                            )
                            
                            if new_prev != old_prev:
                                # New DOGE block found (previousblockhash changed).
                                # Fire merged_work.changed → new_work_event for all miners.
                                self.merged_work.set(math.merge_dicts(self.merged_work.value, {chainid: new_merged_entry}))
                                _last_full_refresh = time.time()
                                print '[MERGED-REFRESH] NEW BLOCK height=%d prev=%s hash=%064x' % (template.get('height', 0), new_prev[:16], doge_block_hash)
                            else:
                                # Same DOGE block, template refreshed (timestamp/txns).
                                # Update ALL fields in-place so get_work() uses fresh
                                # template, but do NOT fire merged_work.changed (avoids
                                # spurious new_work_event that triggers N get_work() calls).
                                if chainid in self.merged_work.value:
                                    for key, val in new_merged_entry.items():
                                        self.merged_work.value[chainid][key] = val
                                _last_full_refresh = time.time()
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
                        print '[STARTUP-OK] Merged mining mode: SINGLE ADDRESS (createauxblock/getauxblock)'
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
                            _m_ver = self._merged_addr_ver(self.my_pubkey_type, dogecoin_testnet_net)
                            effective_payout_address = bitcoin_data.pubkey_hash_to_address(
                                self.my_pubkey_hash, _m_ver,
                                -1, dogecoin_testnet_net)
                        elif dogecoin_net:
                            _m_ver = self._merged_addr_ver(self.my_pubkey_type, dogecoin_net)
                            effective_payout_address = bitcoin_data.pubkey_hash_to_address(
                                self.my_pubkey_hash, _m_ver,
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
                    
                    # Check if merged chain tip changed (new block to mine)
                    new_hash = int(auxblock['hash'], 16)
                    old_work = self.merged_work.value.get(auxblock['chainid'], {})
                    new_prev = auxblock.get('previousblockhash', '')
                    old_prev = old_work.get('previousblockhash', '')
                    
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
                                # Get local Dogecoin node's P2P address from args
                                merged_p2p_port = getattr(self.args, 'merged_coind_p2p_port', None)
                                merged_p2p_address = getattr(self.args, 'merged_coind_p2p_address', None) or getattr(self.args, 'merged_coind_address', None)
                                
                                if parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower():
                                    # Network selection for DOGE testnet broadcaster P2P:
                                    #   port 44557 → testnet4alpha (magic d4a1f4a1) — quickfix for block storm bug
                                    #   port 44556 → regular testnet (magic fcc1b7dc)
                                    # Wrong magic = daemon drops connection silently (handshake never completes)
                                    if merged_p2p_port == 44557 and dogecoin_testnet4alpha_net:
                                        chain_name = 'dogecoin_testnet4alpha'
                                        p2p_net = dogecoin_testnet4alpha_net
                                        p2p_port = 44557
                                        print 'MergedBroadcaster: Using dogecoin_testnet4alpha network (P2P magic d4a1f4a1, port 44557)'
                                    else:
                                        chain_name = 'dogecoin_testnet'
                                        p2p_net = dogecoin_testnet_net
                                        p2p_port = 44556 if dogecoin_testnet_net else None
                                else:
                                    p2p_net = dogecoin_net
                                    p2p_port = 22556 if dogecoin_net else None
                                
                                if merged_p2p_port and merged_p2p_address:
                                    local_p2p_addr = (merged_p2p_address, merged_p2p_port)
                            
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
                    
                    new_merged_entry = dict(
                        hash=new_hash,
                        previousblockhash=new_prev,  # Track for change detection
                        # createauxblock returns target in LE hex; use IntType(256) LE unpack
                        # to get the correct integer (same result as int(BE_hex, 16))
                        target='p2pool' if auxblock['target'] == 'p2pool' else pack.IntType(256).unpack(auxblock['target'].decode('hex')),
                        merged_proxy=merged_proxy,
                        multiaddress=False,
                        use_submitauxblock=use_submitauxblock,
                        coinbasevalue=auxblock.get('coinbasevalue', 0),  # Block reward + fees
                        height=auxblock.get('height', 0),
                        finder_fee_percentage=0.5,
                        daemon_warnings=merged_daemon_warnings,
                        last_update=time.time(),
                    )
                    
                    if new_prev != old_prev:
                        # New DOGE block found (previousblockhash changed).
                        # Fire merged_work.changed → new_work_event → _send_work().
                        self.merged_work.set(math.merge_dicts(self.merged_work.value, {auxblock['chainid']: new_merged_entry}))
                        _last_full_refresh = time.time()
                        print '[MERGED-REFRESH-SINGLE] NEW BLOCK hash=%s prev=%s height=%s' % (auxblock['hash'][:16], new_prev[:16] if new_prev else '?', auxblock.get('height', '?'))
                    else:
                        # Same DOGE block, template refreshed (timestamp/txns).
                        # Update ALL fields in-place so get_work() uses fresh hash,
                        # but do NOT fire merged_work.changed (avoids spurious
                        # new_work_event that triggers N get_work() rebuilds).
                        if auxblock['chainid'] in self.merged_work.value:
                            for key, val in new_merged_entry.items():
                                self.merged_work.value[auxblock['chainid']][key] = val
                        _last_full_refresh = time.time()
                
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

    def is_v36_active(self):
        """
        Check if V36 share version is active (95%+ signaling).
        
        Returns (v36_active, v36_signaling):
            v36_active: True if >= 95% of shares signal V36
            v36_signaling: Float 0.0-1.0 representing V36 signaling ratio
        """
        v36_active = False
        v36_signaling = 0.0
        
        if self.node.best_share_var.value is None:
            return v36_active, v36_signaling
            
        try:
            previous_share = self.node.tracker.items[self.node.best_share_var.value]
            chain_height = self.node.tracker.get_height(previous_share.hash)
            
            if chain_height >= self.node.net.CHAIN_LENGTH:
                counts = p2pool_data.get_desired_version_counts(
                    self.node.tracker,
                    self.node.tracker.get_nth_parent_hash(previous_share.hash, self.node.net.CHAIN_LENGTH*9//10),
                    self.node.net.CHAIN_LENGTH//10
                )
                total_weight = sum(counts.itervalues())
                if total_weight > 0:
                    v36_signaling = counts.get(36, 0) / total_weight
                    v36_active = v36_signaling >= 0.95
        except Exception as e:
            if p2pool.DEBUG:
                print >>sys.stderr, '[V36] Error checking V36 status: %s' % e
        
        return v36_active, v36_signaling

    @staticmethod
    def _prepare_transition_message(args):
        """
        Prepare pre-packed message_data for embedding transition signals in V36 shares.
        
        Called once at startup from --transition-message CLI arg.
        Returns packed bytes ready for generate_transaction(), or None if not configured.
        
        The operator provides a hex string (or file containing one) that was
        pre-built and encrypted offline by the authority key holder using
        create_transition_message.py.  This method simply decodes and validates
        that the blob decrypts correctly against a known authority pubkey.
        
        No private key is needed on the operator node.
        """
        transition_msg = getattr(args, 'transition_message', None)
        
        if not transition_msg:
            return None
        
        import os
        
        # Accept either a file path or an inline hex string
        raw_hex = transition_msg.strip()
        if os.path.isfile(raw_hex):
            with open(raw_hex) as f:
                raw_hex = f.read().strip()
        
        # Decode hex → bytes
        try:
            message_data = raw_hex.decode('hex')
        except (ValueError, TypeError):
            print >> sys.stderr, '[TRANSITION] ERROR: --transition-message must be a hex string or path to a file containing one'
            print >> sys.stderr, '[TRANSITION] Get the hex string from the authority key holder (scripts/create_transition_message.py)'
            return None
        
        if len(message_data) < 50:  # minimum: header(49) + at least 1 byte
            print >> sys.stderr, '[TRANSITION] ERROR: message_data too short (%d bytes)' % len(message_data)
            return None
        
        # Validate: must decrypt against a known authority pubkey
        from p2pool.share_messages import unpack_share_messages, DONATION_AUTHORITY_PUBKEYS
        try:
            messages, signing_key_info = unpack_share_messages(message_data)
        except Exception as e:
            print >> sys.stderr, '[TRANSITION] ERROR: failed to unpack message_data -- %s' % e
            return None
        
        if signing_key_info is None or not messages:
            print >> sys.stderr, '[TRANSITION] ERROR: message_data failed decryption -- not a valid authority-encrypted message'
            print >> sys.stderr, '[TRANSITION] Make sure you got the correct hex string from the authority key holder'
            return None
        
        authority_pubkey = signing_key_info.get('authority_pubkey', b'')
        if authority_pubkey not in DONATION_AUTHORITY_PUBKEYS:
            print >> sys.stderr, '[TRANSITION] ERROR: message decrypted but not from a known authority key'
            return None
        
        # Verify signatures
        for msg in messages:
            if not msg.signature or not msg.verify_authority_direct(authority_pubkey):
                print >> sys.stderr, '[TRANSITION] ERROR: message (type 0x%02x) has invalid signature' % msg.msg_type
                return None
        
        # Show what we're embedding
        import json as _json
        for msg in messages:
            try:
                data = _json.loads(msg.payload)
                print '[TRANSITION] Validated transition signal: v%s->v%s urg=%s (%d bytes)' % (
                    data.get('from', '?'), data.get('to', '?'),
                    data.get('urg', '?'), len(message_data))
                print '[TRANSITION] Message: %s' % data.get('msg', '')
            except (ValueError, KeyError):
                print '[TRANSITION] Validated message type 0x%02x (%d bytes)' % (
                    msg.msg_type, len(message_data))
        
        print '[TRANSITION] Authority key: %s...' % authority_pubkey.encode('hex')[:16]
        print '[TRANSITION] Will embed in all mined V36 shares'
        
        return message_data

    def _get_validated_merged_operator_address(self, merged_addr_net, chainid):
        """Validate --merged-operator-address against the merged chain network.

        Returns the address string if valid, None if invalid. Caches result
        so validation and logging happen only once per (address, chainid).
        """
        cache_key = (self.merged_operator_address, chainid)
        if not hasattr(self, '_merged_op_addr_cache'):
            self._merged_op_addr_cache = {}
        cached = self._merged_op_addr_cache.get(cache_key)
        if cached is not None:
            return cached if cached != '' else None

        try:
            pubkey_hash, version, witver = bitcoin_data.address_to_pubkey_hash(
                self.merged_operator_address, merged_addr_net)
            self._merged_op_addr_cache[cache_key] = self.merged_operator_address
            print >>sys.stderr, '[MERGED] Node operator override: using --merged-operator-address %s for chain_id %d fee payout (instead of auto-converted parent address)' % (
                self.merged_operator_address, chainid)
            return self.merged_operator_address
        except Exception as e:
            print >>sys.stderr, '[MERGED] WARNING: --merged-operator-address %s is not valid for chain_id %d: %s. Falling back to auto-conversion from parent address.' % (
                self.merged_operator_address, chainid, e)
            self._merged_op_addr_cache[cache_key] = ''  # Cache the negative result
            return None

    def _get_pplns_entries(self):
        """Get cached PPLNS weight entries.

        Event-driven invalidation: cache stays valid while the share chain
        head (best_share_var) is unchanged.  When a new share arrives, the
        cache is invalidated but recomputation is rate-limited to at most
        once every 10 seconds to avoid thrashing during rapid share bursts.

        Returns list of (address, weight, pubkey_hash, pubkey_type) or None.
        """
        now = time.time()
        current_best = self.node.best_share_var.value

        if hasattr(self, '_pplns_cache'):
            # Same share chain head — cache is perfectly valid
            if getattr(self, '_pplns_cache_best', None) == current_best:
                return self._pplns_cache
            # Share chain changed, but rate-limit recomputation (10s min)
            if (now - getattr(self, '_pplns_cache_time', 0)) < 10:
                return self._pplns_cache

        self._pplns_cache = None
        self._pplns_cache_time = now
        self._pplns_cache_best = current_best
        try:
            if current_best is not None:
                tracker = self.node.tracker
                block_target = self.current_work.value['bits'].target
                weights, total_weight, donation_weight = tracker.get_cumulative_weights(
                    current_best,
                    min(tracker.get_height(current_best), self.node.net.REAL_CHAIN_LENGTH),
                    65535 * self.node.net.SPREAD * bitcoin_data.target_to_average_attempts(block_target),
                )
                if weights:
                    entries = []
                    for addr, w in weights.iteritems():
                        try:
                            ph, ver, witver = bitcoin_data.address_to_pubkey_hash(addr, self.node.net.PARENT)
                            pt = p2pool_data.get_pubkey_type(ver, witver, self.node.net.PARENT)
                            entries.append((addr, w, ph, pt))
                        except Exception:
                            pass
                    if entries:
                        self._pplns_cache = entries
        except Exception:
            pass
        return self._pplns_cache

    def _get_connected_zero_pplns_miners(self):
        """Get miners connected via stratum that have ZERO weight in PPLNS.

        These are tiny miners actively hashing but haven't found a single share
        in the 8640-share window.  They need the most help.

        Event-driven invalidation:
          - Connection count changed  → a miner joined/left, recompute
          - PPLNS entries changed     → a miner may have graduated, recompute
          - Otherwise                 → cache stays valid indefinitely
        Rate-limited to at most once per 10 seconds.

        Returns list of (pubkey_hash, pubkey_type) or empty list.
        """
        now = time.time()

        from p2pool.bitcoin.stratum import pool_stats
        current_conn_count = pool_stats.connection_count

        if hasattr(self, '_zero_pplns_cache'):
            same_conns = (getattr(self, '_zero_pplns_conn_count', -1) == current_conn_count)
            same_pplns = (getattr(self, '_zero_pplns_pplns_best', None) == self.node.best_share_var.value)
            if same_conns and same_pplns:
                # Nothing changed — cache is perfectly valid
                return self._zero_pplns_cache
            if (now - getattr(self, '_zero_pplns_cache_time', 0)) < 10:
                # Rate limit: something changed but we just recomputed
                return self._zero_pplns_cache

        self._zero_pplns_cache = []
        self._zero_pplns_cache_time = now
        self._zero_pplns_conn_count = current_conn_count
        self._zero_pplns_pplns_best = self.node.best_share_var.value

        try:
            connected = pool_stats.get_connected_workers()
            if not connected:
                return self._zero_pplns_cache

            # Get addresses currently in PPLNS
            pplns_entries = self._get_pplns_entries()
            pplns_addresses = set()
            if pplns_entries:
                for addr, w, ph, pt in pplns_entries:
                    pplns_addresses.add(addr)

            # Find connected miners NOT in PPLNS
            zero_miners = []
            seen = set()
            for worker_name, info in connected.items():
                # Extract base address (strip worker name)
                addr = info.get('address')
                if not addr or addr in seen:
                    continue
                seen.add(addr)
                # Parse actual address (strip worker suffix, comma-separated merged addr)
                base_addr = addr.split(',')[0].split('.')[0].split('_')[0]
                if not base_addr or base_addr in pplns_addresses:
                    continue
                # Resolve to pubkey_hash
                try:
                    ph, ver, witver = bitcoin_data.address_to_pubkey_hash(base_addr, self.node.net.PARENT)
                    pt = p2pool_data.get_pubkey_type(ver, witver, self.node.net.PARENT)
                    zero_miners.append((ph, pt))
                except Exception:
                    pass  # skip invalid addresses

            self._zero_pplns_cache = zero_miners
        except Exception:
            pass

        return self._zero_pplns_cache

    @staticmethod
    def _merged_addr_ver(pubkey_type, merged_net):
        """Pick ADDRESS_VERSION or ADDRESS_P2SH_VERSION for pubkey_hash→merged-chain address.

        bech32 (P2WPKH) falls back to P2PKH on merged chains that lack segwit (e.g. Dogecoin).
        """
        if pubkey_type == p2pool_data.PUBKEY_TYPE_P2SH:
            return merged_net.ADDRESS_P2SH_VERSION
        return merged_net.ADDRESS_VERSION

    def _redistribute_share(self):
        """Pick a (pubkey_hash, pubkey_type) for shares from unnamed/broken miners.

        Controlled by --redistribute CLI flag:
          pplns  : distribute by PPLNS weight proportionally (default)
          fee    : 100% to node operator
          boost  : give to active stratum miners with ZERO PPLNS shares,
                   falls back to PPLNS if no zero-share miners connected
          donate : 100% to donation script (P2SH combined or P2PK legacy)

        This only affects which pubkey_hash is stamped into the share
        for redistribution. It does NOT change consensus rules.

        Returns (pubkey_hash, pubkey_type).
        """
        mode = getattr(self.args, 'redistribute_mode', 'pplns')

        # ---- MODE: fee ----
        if mode == 'fee':
            return self.my_pubkey_hash, self.my_pubkey_type

        # ---- MODE: donate ----
        if mode == 'donate':
            from p2pool.data import (COMBINED_DONATION_SCRIPT, DONATION_SCRIPT,
                                     combined_donation_script_to_address,
                                     donation_script_to_address,
                                     COMBINED_DONATION_PUBKEY_HASH)
            v36_active, _ = self.is_v36_active()
            if v36_active:
                # Use the combined donation pubkey_hash (P2SH)
                return COMBINED_DONATION_PUBKEY_HASH, p2pool_data.PUBKEY_TYPE_P2SH
            else:
                # Pre-V36: use original donation P2PK — map to P2PKH hash
                # DONATION_SCRIPT is a P2PK output, extract the pubkey hash
                import hashlib
                pubkey = DONATION_SCRIPT[1:-1]  # strip OP_PUSHDATA + OP_CHECKSIG
                h = hashlib.new('ripemd160', hashlib.sha256(pubkey).digest()).digest()
                return int(h.encode('hex'), 16), p2pool_data.PUBKEY_TYPE_P2PKH

        # ---- MODE: boost ----
        if mode == 'boost':
            zero_miners = self._get_connected_zero_pplns_miners()
            if zero_miners:
                # Equal chance for each zero-share miner (they're all equally tiny)
                ph, pt = random.choice(zero_miners)
                return ph, pt
            # Fallback: no zero-share miners connected, use PPLNS
            # (fall through to pplns mode)

        # ---- MODE: pplns (default + fallback) ----
        entries = self._get_pplns_entries()
        if not entries:
            return self.my_pubkey_hash, self.my_pubkey_type
        total = sum(w for _, w, _, _ in entries)
        r = random.randint(0, total - 1)
        cumulative = 0
        for addr, w, ph, pt in entries:
            cumulative += w
            if r < cumulative:
                return ph, pt
        return entries[-1][2], entries[-1][3]

    def get_user_details(self, username, peer_addr=None):
        # Debug: Uncomment to trace user details lookup
        #print '[DEBUG] get_user_details called with username:', repr(username)
        contents = re.split('([+/])', username)
        assert len(contents) % 2 == 1

        user, contents2 = contents[0], contents[1:]
        
        # Parse merged mining addresses (format: ltc_addr,doge_addr or ltc_addr,doge_addr.worker)
        # Using , (comma) separator - URL-safe and not used in difficulty parsing
        # V36 shares store validated merged addresses in share_info['merged_addresses'].
        # Each entry is (chain_id, script) where script is the payment script for that chain.
        # Validation cascade:
        #   1. Parse address from stratum username
        #   2. Validate against merged chain network (checksum, version byte)
        #   3. Convert to payment script for storage
        #   4. If invalid: log warning, omit from merged_addresses (auto-conversion fallback)
        merged_addresses = {}
        worker = ''
        
        if ',' in user:
            # Split merged addresses
            # Format: ltc_addr,doge_addr[.worker] or ltc_addr,doge_addr[_worker]
            parts = user.split(',', 1)  # Only split on first comma
            user = parts[0]  # Primary address (Litecoin)
            if len(parts) > 1:
                merged_addr = parts[1]
                # Strip worker name: split on '.' first, then '_'
                # Both are valid worker separators and may co-exist
                if '.' in merged_addr:
                    merged_addr, worker = merged_addr.split('.', 1)
                if '_' in merged_addr:
                    # '_' separates addr from worker (e.g. "addr_worker")
                    merged_addr = merged_addr.split('_', 1)[0]
                    # Only set worker if not already parsed from '.'
                    if not worker:
                        worker = parts[1].split('_', 1)[1].split('.')[0] if '_' in parts[1] else ''
                
                # Validate the merged address against the CURRENT merged chain network only.
                # Reject addresses that don't match — don't try other networks.
                chain_net = self._get_merged_address_net(98)  # 98 = Dogecoin
                chain_name = self._get_merged_chain_name(98)
                validated = False
                if chain_net is not None:
                    try:
                        pubkey_hash, version, witver = bitcoin_data.address_to_pubkey_hash(merged_addr, chain_net)
                        # Convert to payment script for storage in share
                        script = bitcoin_data.pubkey_hash_to_script2(pubkey_hash, version, witver, chain_net)
                        merged_addresses['dogecoin'] = merged_addr
                        # Store validated script with chain_id for share storage
                        # chain_id 98 = Dogecoin (0x62)
                        merged_addresses['_validated'] = [{'chain_id': 98, 'script': script}]
                        validated = True
                        # Only log first validation per address to avoid log spam on every work unit
                        if not hasattr(self, '_merged_validated_addrs'):
                            self._merged_validated_addrs = set()
                        if merged_addr not in self._merged_validated_addrs:
                            self._merged_validated_addrs.add(merged_addr)
                            print >>sys.stderr, '[MERGED] Validated explicit DOGE address: %s (chain: %s, script: %s)' % (merged_addr, chain_name, script.encode('hex'))
                    except (ValueError, Exception) as e:
                        pass  # falls through to !validated branch below
                
                if not validated:
                    # Address failed validation on the current DOGE network.
                    # Do NOT store it — fallback to auto-conversion from parent address.
                    # If parent address is also invalid, merged reward goes to random PPLNS miner.
                    print >>sys.stderr, '[MERGED] WARNING: Invalid DOGE address "%s" from stratum (rejected by %s network). Merged reward will be distributed to a random PPLNS miner with a valid merged address, probabilistically according to work share.' % (merged_addr, chain_name)
                    # Still store unvalidated for current-work display, but NOT for share storage
                    merged_addresses['dogecoin'] = merged_addr
                    merged_addresses['_validated'] = None  # Signals: do not store in share
        
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

        # Initialize pubkey_hash and pubkey_type with operator defaults
        pubkey_hash = self.my_pubkey_hash
        pubkey_type = self.my_pubkey_type  # V36: 0=P2PKH, 1=P2WPKH, 2=P2SH
        
        if self.args.address == 'dynamic':
            i = self.pubkeys.weighted()
            pubkey_hash = self.pubkeys.keys[i]
            pubkey_type = p2pool_data.PUBKEY_TYPE_P2PKH  # dynamic addresses are P2PKH

            c = time.time()
            if (c - self.pubkeys.stamp) > self.args.timeaddresses:
                self.freshen_addresses(c)

        if random.uniform(0, 100) < self.node_owner_fee:
            pubkey_hash = self.my_pubkey_hash
            pubkey_type = self.my_pubkey_type
        # Resolve miner address to pubkey_hash for share creation.
        # V36 uses COMBINED_DONATION_SCRIPT (1-of-2 P2MS) in coinbase for donations.
        # No fake miner mechanism needed — donation is handled entirely in coinbase.
        else:
            try:
                if not user or not user.strip():
                    # Empty address: redistribute per --redistribute mode
                    pubkey_hash, pubkey_type = self._redistribute_share()
                    print >>sys.stderr, '[POOL] Empty miner address from %s - redistributed (%s mode)' % (peer_addr or 'unknown', getattr(self.args, 'redistribute_mode', 'pplns'))
                else:
                    # Cache miner address resolution — same address produces same result every time
                    cached_addr = self._miner_addr_cache.get(user)
                    if cached_addr is not None:
                        pubkey_hash, pubkey_type, is_convertible, addr_type, error_msg = cached_addr
                    else:
                        addr_result = is_pubkey_hash_address(user, self.node.net.PARENT)
                        is_convertible = addr_result[0]
                        validated_pubkey_hash = addr_result[1]
                        error_msg = addr_result[2]
                        addr_type = addr_result[3] if len(addr_result) > 3 else 'p2pkh'
                        if is_convertible:
                            pubkey_hash = validated_pubkey_hash
                            try:
                                _, _v, _wv = bitcoin_data.address_to_pubkey_hash(user, self.node.net.PARENT)
                                pubkey_type = p2pool_data.get_pubkey_type(_v, _wv, self.node.net.PARENT)
                            except:
                                pubkey_type = p2pool_data.PUBKEY_TYPE_P2PKH
                        else:
                            pubkey_hash = validated_pubkey_hash
                            pubkey_type = p2pool_data.PUBKEY_TYPE_P2PKH
                        self._miner_addr_cache[user] = (pubkey_hash, pubkey_type, is_convertible, addr_type, error_msg)
                    if is_convertible:
                        # Auto-generate merged chain address when miner provides
                        # no explicit merged address via stratum.
                        # Priority: explicit (already in _validated) > auto-convert > pool distribution
                        if not merged_addresses.get('_validated'):
                            # Cache auto-generated merged addresses per miner
                            if user in self._miner_merged_cache:
                                cached_merged = self._miner_merged_cache[user]
                                if cached_merged is not None:
                                    merged_addresses['_validated'] = cached_merged
                                    # Restore cached display addresses
                                    cached_display = self._miner_merged_display_cache.get(user, {})
                                    for chain_name, display_addr in cached_display.items():
                                        merged_addresses[chain_name] = display_addr
                                    merged_addresses['_auto_converted'] = True
                            else:
                                auto_entries = self._auto_generate_merged_addresses(pubkey_hash, addr_type)
                                if auto_entries:
                                    merged_addresses['_validated'] = auto_entries
                                    self._miner_merged_cache[user] = auto_entries
                                    # Compute and cache display addresses for auto-converted entries
                                    display_addrs = {}
                                    src_type_names = {
                                        p2pool_data.PUBKEY_TYPE_P2PKH: 'P2PKH',
                                        p2pool_data.PUBKEY_TYPE_P2WPKH: 'BECH32',
                                        p2pool_data.PUBKEY_TYPE_P2SH: 'P2SH',
                                    }
                                    src_label = src_type_names.get(pubkey_type, addr_type.upper())
                                    for ae in auto_entries:
                                        try:
                                            ae_net = self._get_merged_address_net(ae['chain_id'])
                                            ae_chain = self._get_merged_chain_name(ae['chain_id'])
                                            if addr_type == 'p2sh':
                                                ae_addr = bitcoin_data.pubkey_hash_to_address(pubkey_hash, ae_net.ADDRESS_P2SH_VERSION, -1, ae_net)
                                                dst_label = 'P2SH'
                                            else:
                                                ae_addr = bitcoin_data.pubkey_hash_to_address(pubkey_hash, ae_net.ADDRESS_VERSION, -1, ae_net)
                                                dst_label = 'P2PKH'
                                            display_addrs[ae_chain] = ae_addr
                                            merged_addresses[ae_chain] = ae_addr
                                            print >>sys.stderr, '[MERGED] Auto-converted %s address %s -> %s %s (chain: %s, script: %s)' % (
                                                src_label, user, ae_addr, dst_label,
                                                ae_chain, ae['script'].encode('hex'))
                                        except Exception:
                                            print >>sys.stderr, '[MERGED] Auto-converted %s address %s -> script %s (chain_id: %d)' % (
                                                src_label, user, ae['script'].encode('hex'), ae['chain_id'])
                                    self._miner_merged_display_cache[user] = display_addrs
                                    merged_addresses['_auto_converted'] = True
                                else:
                                    # Tier 3: unconvertible - merged rewards go to pool distribution
                                    self._miner_merged_cache[user] = None  # cache the negative result too
                                    print >>sys.stderr, '[MERGED] Address %s (%s) not convertible to merged chain - pool distribution' % (
                                        user[:30] + '...' if len(user) > 30 else user, addr_type)
                    else:
                        if cached_addr is None:  # Only warn once per miner address
                            print >>sys.stderr, '[WARN] Miner address %s is not convertible for merged mining: %s' % (user[:30] + '...' if len(user) > 30 else user, error_msg)
                        pubkey_hash, _v2, _wv2 = bitcoin_data.address_to_pubkey_hash(user, self.node.net.PARENT)
                        pubkey_type = p2pool_data.get_pubkey_type(_v2, _wv2, self.node.net.PARENT)
            except: # Invalid/unparseable address - probabilistic redistribution
                # Parent chain: redistribute per --redistribute mode
                # Merged chain: preserve valid explicit address if provided
                pubkey_hash, pubkey_type = self._redistribute_share()
                print >>sys.stderr, '[POOL] Invalid miner address %s from %s - redistributed (%s mode)' % (
                    user[:30] + ('...' if len(user) > 30 else '') if user else '(empty)', peer_addr or 'unknown', getattr(self.args, 'redistribute_mode', 'pplns'))
        
        # Append worker name to user for identification
        if worker:
            user = user + '.' + worker

        # Debug: Uncomment to trace user details processing
        #print '[DEBUG] get_user_details returning: user=%r, merged_addresses=%r' % (user, merged_addresses)
        return user, pubkey_hash, pubkey_type, desired_share_target, desired_pseudoshare_target, merged_addresses

    def preprocess_request(self, user, peer_addr=None):
        # Debug: Uncomment to trace preprocess flow
        #print '[DEBUG] preprocess_request called with user:', repr(user)
        # Removed peer connection check - allow solo mining
        if time.time() > self.current_work.value['last_update'] + 60:
            raise jsonrpc.Error_for_code(-12345)(u'lost contact with coind')
        username, pubkey_hash, pubkey_type, desired_share_target, desired_pseudoshare_target, merged_addresses = self.get_user_details(user, peer_addr=peer_addr)
        #print '[DEBUG] preprocess_request returning 6 values: username=%r' % (username,)
        return username, pubkey_hash, pubkey_type, desired_share_target, desired_pseudoshare_target, merged_addresses

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
        # Cache for 2 seconds — result is identical within a single work event burst
        # (all 25+ miners calling get_work() on the same event get the same datums).
        # Saves O(datums) × O(miners) iterations per event.
        now = time.time()
        cached = getattr(self, '_local_addr_rates_cache', None)
        if cached is not None:
            cached_result, cached_ts = cached
            if now - cached_ts < 2.0:
                return cached_result
        addr_hash_rates = {}
        datums, dt = self.local_addr_rate_monitor.get_datums_in_last()
        for datum in datums:
            addr_hash_rates[datum['pubkey_hash']] = addr_hash_rates.get(datum['pubkey_hash'], 0) + datum['work']/dt
        self._local_addr_rates_cache = (addr_hash_rates, now)
        return addr_hash_rates

    def update_best_difficulty(self, user, difficulty):
        """Track best difficulty for a miner and node-wide (parent + merged)"""
        now = time.time()
        if user not in self.miner_best_difficulty:
            self.miner_best_difficulty[user] = {
                'all_time': 0,
                'session': 0,
                'round': 0,
                'session_start': self.session_start_time
            }
        
        rec = self.miner_best_difficulty[user]
        if difficulty > rec['all_time']:
            rec['all_time'] = difficulty
        if difficulty > rec['session']:
            rec['session'] = difficulty
        if difficulty > rec['round']:
            rec['round'] = difficulty
        
        # Node-wide tracking (parent chain)
        nb = self.node_best_difficulty
        if difficulty > nb['all_time']:
            nb['all_time'] = difficulty
            nb['all_time_user'] = user
            nb['all_time_ts'] = now
        if difficulty > nb['session']:
            nb['session'] = difficulty
            nb['session_user'] = user
            nb['session_ts'] = now
        if difficulty > nb['round']:
            nb['round'] = difficulty
            nb['round_user'] = user
            nb['round_ts'] = now
        
        # Merged chain (DOGE) tracking — same PoW hash, different target
        mb = self.merged_best_difficulty
        if difficulty > mb['all_time']:
            mb['all_time'] = difficulty
            mb['all_time_user'] = user
            mb['all_time_ts'] = now
        if difficulty > mb['round']:
            mb['round'] = difficulty
            mb['round_user'] = user
            mb['round_ts'] = now

    def reset_round_best_difficulty(self):
        """Reset round-level best difficulty (called when pool finds a block)"""
        now = time.time()
        # Reset per-miner round stats
        for user in self.miner_best_difficulty:
            self.miner_best_difficulty[user]['round'] = 0
        # Reset node-wide round stats
        self.node_best_difficulty['round'] = 0
        self.node_best_difficulty['round_user'] = None
        self.node_best_difficulty['round_ts'] = 0
        self.node_best_difficulty['round_start'] = now
        print >>sys.stderr, 'Best difficulty round stats reset (new round started)'

    def reset_merged_round_best_difficulty(self):
        """Reset merged chain round-level best difficulty (called when pool finds a DOGE block)"""
        now = time.time()
        self.merged_best_difficulty['round'] = 0
        self.merged_best_difficulty['round_user'] = None
        self.merged_best_difficulty['round_ts'] = 0
        self.merged_best_difficulty['round_start'] = now
        print >>sys.stderr, 'Merged best difficulty round stats reset (DOGE block found)'

    def get_miner_best_difficulty(self, user):
        """Get best difficulty stats for a miner"""
        if user not in self.miner_best_difficulty:
            return {'all_time': 0, 'session': 0, 'round': 0, 'session_start': self.session_start_time}
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

    def _auto_generate_merged_addresses(self, pubkey_hash, addr_type):
        """Auto-generate merged chain addresses from parent chain address (FALLBACK only).
        
        Three-tier merged address priority:
          1. Explicit miner-supplied merged address (stratum comma-separated) — HIGHEST
          2. Auto-conversion from parent chain address (this method) — FALLBACK
          3. Pool distribution (no merged address possible) — LAST RESORT
        
        This method implements tier 2. It is ONLY called when the miner did NOT
        supply an explicit merged address via stratum.
        
        For P2PKH/bech32: pubkey_hash → P2PKH script on merged chain
        For P2SH: script_hash → P2SH script on merged chain
           Caveat: P2SH-P2WPKH redeem scripts are unspendable on chains without
           SegWit (e.g., Dogecoin). The miner is trusted to know their setup.
        
        Returns: list of {chain_id, script} entries, or None (tier 3 — pool distribution)
        """
        entries = []
        # Generate for all known merged chains (currently just Dogecoin, chain_id 98)
        for chain_id in [98]:  # Dogecoin
            try:
                merged_net = self._get_merged_address_net(chain_id)
                if merged_net is None:
                    continue
                from p2pool.bitcoin.data import pack
                if addr_type == 'p2sh':
                    p2sh_version = getattr(merged_net, 'ADDRESS_P2SH_VERSION', None)
                    if p2sh_version is None:
                        continue
                    # P2SH scriptPubKey: OP_HASH160 <20-byte-hash> OP_EQUAL
                    script = '\xa9\x14' + pack.IntType(160).pack(pubkey_hash) + '\x87'
                elif addr_type in ('p2pkh', 'bech32'):
                    # P2PKH scriptPubKey: OP_DUP OP_HASH160 <20-byte-hash> OP_EQUALVERIFY OP_CHECKSIG
                    script = '\x76\xa9\x14' + pack.IntType(160).pack(pubkey_hash) + '\x88\xac'
                else:
                    # Unconvertible address type — tier 3: pool distribution
                    continue
                entries.append({'chain_id': chain_id, 'script': script})
            except Exception as e:
                print >>sys.stderr, '[MERGED] Failed to auto-convert %s for chain %d: %s' % (addr_type, chain_id, e)
        return entries if entries else None

    def _get_merged_address_net(self, chainid):
        """Return the network object for the active merged chain (cached)."""
        cached = self._merged_net_cache.get(chainid)
        if cached is not None:
            return cached
        result = self._get_merged_address_net_impl(chainid)
        self._merged_net_cache[chainid] = result
        return result

    def _get_merged_address_net_impl(self, chainid):
        """Return the network object for the active merged chain.
        
        Uses the same detection logic as the MergedMiningBroadcaster:
          - testnet + port 44557 → dogecoin_testnet4alpha
          - testnet + other port → dogecoin_testnet
          - mainnet → dogecoin
        """
        if chainid == 98:  # Dogecoin
            parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
            is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
            if is_testnet:
                merged_p2p_port = getattr(self.args, 'merged_coind_p2p_port', None)
                if merged_p2p_port == 44557 and dogecoin_testnet4alpha_net is not None:
                    return dogecoin_testnet4alpha_net
                if dogecoin_testnet_net is not None:
                    return dogecoin_testnet_net
            else:
                if dogecoin_net is not None:
                    return dogecoin_net
        return self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net

    def _get_merged_chain_name(self, chainid):
        """Return a human-readable name for the active merged chain (cached)."""
        cached = self._merged_chain_name_cache.get(chainid)
        if cached is not None:
            return cached
        result = self._get_merged_chain_name_impl(chainid)
        self._merged_chain_name_cache[chainid] = result
        return result

    def _get_merged_chain_name_impl(self, chainid):
        """Return a human-readable name for the active merged chain."""
        if chainid == 98:  # Dogecoin
            parent_symbol = getattr(self.node.net.PARENT, 'SYMBOL', '') if hasattr(self.node.net, 'PARENT') else ''
            is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
            if is_testnet:
                merged_p2p_port = getattr(self.args, 'merged_coind_p2p_port', None)
                if merged_p2p_port == 44557 and dogecoin_testnet4alpha_net is not None:
                    return 'dogecoin_testnet4alpha'
                return 'dogecoin_testnet'
            return 'dogecoin'
        return 'merged_%d' % chainid

    def _derive_merged_finder_address(self, user, merged_addresses, chainid, merged_addr_net, parent_net):
        # 1) Prefer validated merged address/script supplied via stratum for this chain.
        if merged_addresses and merged_addresses.get('_validated'):
            for entry in merged_addresses['_validated']:
                if entry.get('chain_id') != chainid:
                    continue
                try:
                    return bitcoin_data.script2_to_address(
                        entry['script'], merged_addr_net.ADDRESS_VERSION, -1, merged_addr_net)
                except Exception:
                    continue

        # 2) Fallback to explicit merged address text if present and valid for merged chain.
        if merged_addresses:
            explicit_merged = merged_addresses.get('dogecoin')
            if explicit_merged:
                try:
                    bitcoin_data.address_to_script2(explicit_merged, merged_addr_net)
                    return explicit_merged
                except Exception:
                    pass

        # 3) Fallback to converting parent-chain user address to merged-chain encoding.
        base_user = user.split('.')[0].split('_')[0].split('+')[0].split('/')[0]
        addr_result = is_pubkey_hash_address(base_user, parent_net)
        is_convertible = addr_result[0]
        pubkey_hash = addr_result[1]
        addr_type = addr_result[3] if len(addr_result) > 3 else 'p2pkh'
        if is_convertible and pubkey_hash is not None:
            try:
                if addr_type == 'p2sh':
                    return bitcoin_data.pubkey_hash_to_address(
                        pubkey_hash, merged_addr_net.ADDRESS_P2SH_VERSION, -1, merged_addr_net)
                else:
                    return bitcoin_data.pubkey_hash_to_address(
                        pubkey_hash, merged_addr_net.ADDRESS_VERSION, -1, merged_addr_net)
            except Exception:
                return None
        return None

    # Cache for get_v36_merged_weights results — avoid recomputing on every get_work() call.
    # Only invalidated when best_share_hash or block_target changes.
    _merged_weights_cache = None  # (cache_key, {chainid: (weights, total_weight, donation_weight)})

    def _get_cached_merged_weights(self, chainid, tracker, best_share_hash, block_target):
        """Return cached (weights, total_weight, donation_weight) or compute and cache."""
        from p2pool.data import get_v36_merged_weights

        height = tracker.get_height(best_share_hash) if best_share_hash is not None else 0
        max_weight = 65535 * self.node.net.SPREAD * bitcoin_data.target_to_average_attempts(block_target)
        chain_length = min(height, self.node.net.REAL_CHAIN_LENGTH) if height > 0 else 0

        if chain_length <= 0 or best_share_hash is None:
            return {}, 0, 0

        cache_key = (best_share_hash, block_target)
        if self._merged_weights_cache is not None and self._merged_weights_cache[0] == cache_key:
            cached = self._merged_weights_cache[1]
            if chainid in cached:
                return cached[chainid]

        # Cache miss or new key — reset cache
        if self._merged_weights_cache is None or self._merged_weights_cache[0] != cache_key:
            self._merged_weights_cache = (cache_key, {})

        result = get_v36_merged_weights(tracker, best_share_hash, chain_length, max_weight, chain_id=chainid)
        self._merged_weights_cache[1][chainid] = result
        return result

    def _build_user_specific_merged_work(self, user, merged_addresses, share_pubkey_hash=None, share_pubkey_type=None):
        if not self.merged_work.value:
            return {}

        user_merged_work = {}
        parent_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
        v36_active, _ = self.is_v36_active()

        for chainid, aux_work in self.merged_work.value.iteritems():
            # createauxblock/getauxblock path has no prebuilt merged block template details.
            if not aux_work.get('multiaddress') or 'template' not in aux_work or 'shareholders' not in aux_work:
                user_merged_work[chainid] = aux_work
                continue

            try:
                merged_addr_net = self._get_merged_address_net(chainid)
                template = aux_work['template']
                use_canonical = False

                if v36_active:
                    # === CANONICAL PATH (V36+) ===
                    # Use deterministic canonical coinbase builder for consensus enforcement.
                    # Peers re-derive this exact coinbase in check() and verify it matches
                    # what's committed in mm_data → DOGE block hash → DOGE header → merkle root.
                    from p2pool.data import (build_canonical_merged_coinbase,
                                             get_canonical_merged_finder_script)

                    best_share_hash = self.node.best_share_var.value
                    block_target = self.current_work.value['bits'].target
                    tracker = self.node.tracker

                    weights, total_weight, donation_weight = self._get_cached_merged_weights(
                        chainid, tracker, best_share_hash, block_target)

                    if weights and total_weight > 0:
                        # Determine finder script from the share's pubkey_hash, NOT from
                        # the user address string. The share may store a different pubkey_hash
                        # (e.g., random PPLNS miner for invalid addresses). The verifier uses
                        # share.share_data['pubkey_hash'], so creation must match.
                        #
                        # For P2SH pubkey_type: set to None (Tier 2 would make wrong P2PKH;
                        # rely on merged_addresses Tier 1 instead).
                        if share_pubkey_type is not None and share_pubkey_type == getattr(p2pool_data, 'PUBKEY_TYPE_P2SH', 2):
                            canonical_pubkey_hash = None  # P2SH — rely on merged_addresses
                        else:
                            canonical_pubkey_hash = share_pubkey_hash  # P2PKH or bech32

                        # Get validated merged addresses for this chain
                        merged_addrs_list = None
                        if merged_addresses and merged_addresses.get('_validated'):
                            merged_addrs_list = merged_addresses['_validated']

                        finder_script = get_canonical_merged_finder_script(
                            canonical_pubkey_hash, merged_addrs_list, chainid, merged_addr_net)

                        coinbase_value = template['coinbasevalue']
                        block_height_merged = template['height']

                        doge_coinbase_tx = build_canonical_merged_coinbase(
                            weights, total_weight, donation_weight,
                            coinbase_value, block_height_merged,
                            finder_script, merged_addr_net, parent_net)
                        
                        use_canonical = True

                if not use_canonical:
                    # === LEGACY/FALLBACK PATH ===
                    # Pre-V36 or no V36 shares in window yet — use old float-based builder.
                    finder_address = self._derive_merged_finder_address(
                        user, merged_addresses, chainid, merged_addr_net, parent_net)
                    finder_fee_percentage = aux_work.get('finder_fee_percentage', 0.5)
                    coinbase_text = template.get('auxpow', {}).get('coinbase_text')
                    doge_coinbase_tx = merged_mining.build_merged_coinbase(
                        template,
                        aux_work['shareholders'],
                        merged_addr_net,
                        aux_work.get('donation_percentage', self.donation_percentage),
                        None,  # node_owner_address
                        0,     # node_owner_fee
                        parent_net,
                        coinbase_text,
                        v36_active=v36_active,
                        finder_address=finder_address,
                        finder_fee_percentage=finder_fee_percentage,
                    )

                # Compute DOGE block hash from per-user coinbase
                doge_tx_hashes = [int(tx['hash'], 16) for tx in template.get('transactions', [])]
                doge_coinbase_hash = bitcoin_data.hash256(bitcoin_data.tx_id_type.pack(doge_coinbase_tx))
                all_doge_tx_hashes = [doge_coinbase_hash] + doge_tx_hashes
                doge_merkle_root = bitcoin_data.merkle_hash(all_doge_tx_hashes)

                if 'doge_header' in aux_work:
                    doge_header = aux_work['doge_header'].copy()
                    doge_header['merkle_root'] = doge_merkle_root
                else:
                    doge_header = dict(
                        version=template['version'] | (1 << 8),
                        previous_block=int(template['previousblockhash'], 16) if template.get('previousblockhash') else 0,
                        merkle_root=doge_merkle_root,
                        timestamp=template['curtime'],
                        bits=bitcoin_data.FloatingIntegerType().unpack(template['bits'].decode('hex')[::-1]),
                        nonce=0,
                    )

                doge_block_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(doge_header))

                # Compute coinbase merkle link (proof: coinbase → merkle root)
                coinbase_merkle_link = bitcoin_data.calculate_merkle_link(all_doge_tx_hashes, 0)

                result = dict(
                    aux_work,
                    hash=doge_block_hash,
                    doge_header=doge_header,
                    doge_coinbase=doge_coinbase_tx,
                    doge_tx_hashes=all_doge_tx_hashes,
                    coinbase_merkle_link=coinbase_merkle_link,
                )

                # V36 canonical path: attach verification data for share_info
                if use_canonical:
                    result['merged_coinbase_info_entry'] = {
                        'chain_id': chainid,
                        'coinbase_value': coinbase_value,
                        'block_height': block_height_merged,
                        'block_header_bytes': bitcoin_data.block_header_type.pack(doge_header),
                        'coinbase_merkle_link': coinbase_merkle_link,
                    }

                user_merged_work[chainid] = result
            except Exception as e:
                print >>sys.stderr, '[MERGED-DIAG] WARNING: _build_user_specific_merged_work failed for chain %s: %s' % (chainid, e)
                import traceback
                traceback.print_exc()
                user_merged_work[chainid] = aux_work

        return user_merged_work

    def get_work(self, user, pubkey_hash, pubkey_type, desired_share_target, desired_pseudoshare_target, merged_addresses=None):
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

        # Build user-specific merged templates so finder fee can target the work recipient.
        effective_merged_work = self._build_user_specific_merged_work(user, merged_addresses, share_pubkey_hash=pubkey_hash, share_pubkey_type=pubkey_type)

        if effective_merged_work:
            tree, size = bitcoin_data.make_auxpow_tree(effective_merged_work)
            mm_hashes = [effective_merged_work.get(tree.get(i), dict(hash=0))['hash'] for i in xrange(size)]
            mm_data = '\xfa\xbemm' + bitcoin_data.aux_pow_coinbase_type.pack(dict(
                merkle_root=bitcoin_data.merkle_hash(mm_hashes),
                size=size,
                nonce=0,
            ))
            # Include chain_id in mm_later tuple for merged block recording
            mm_later = [(dict(aux_work, chainid=chain_id), mm_hashes.index(aux_work['hash']), mm_hashes) for chain_id, aux_work in effective_merged_work.iteritems()]
            
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
        #
        # RAWTX APPROACH (ported from jtoomim rawtx branch):
        # Transactions are kept as raw GBT dicts with 'data', 'fee', 'hash', 'txid', 'weight' keys.
        # No parsing/unpacking needed — all transactions including MWEB/HogEx are handled natively.
        # get_txid(), get_wtxid(), get_size(), get_stripped_size(), is_segwit_tx() all handle GBT dicts.
        
        # Check V36 signaling status using helper method
        v36_active, v36_signaling = self.is_v36_active()
        previous_share = self.node.tracker.items[self.node.best_share_var.value] if self.node.best_share_var.value is not None else None
        
        # All transactions from GBT are included (MWEB transactions are just raw hex like any other)
        transactions = self.current_work.value['transactions']
        
        tx_hashes = self.current_work.value['transaction_hashes']
        tx_map = dict(zip(tx_hashes, transactions))
        # AutoRatchet determines share version from network state + persisted state.
        # This replaces the manual share_type selection with a fully automated,
        # network-aware ratchet that persists across restarts.
        share_type, desired_ver = self.auto_ratchet.get_share_version(
            self.node.tracker,
            self.node.best_share_var.value,
            self.node.net,
        )
        
        # CRITICAL: If AutoRatchet selects MergedMiningShare (V36), force v36_active=True.
        # MergedMiningShare.gentx_before_refhash uses COMBINED_DONATION_SCRIPT, so
        # generate_transaction MUST also use COMBINED_DONATION_SCRIPT. Without this,
        # a fresh chain bootstrap with confirmed ratchet state would mismatch:
        # is_v36_active() needs CHAIN_LENGTH shares (empty=False) but share_type=V36.
        if share_type.VERSION >= 36:
            v36_active = True
        
        # Still run the original voting check for switchover logging and protocol version update.
        # The AutoRatchet already handles the actual share_type decision, but this keeps
        # the "Switchover imminent" progress messages and update_min_protocol_version calls.
        if previous_share is not None:
            previous_share_type = type(previous_share)
            if previous_share_type.SUCCESSOR is not None and self.node.tracker.get_height(previous_share.hash) >= self.node.net.CHAIN_LENGTH:
                successor_type = previous_share_type.SUCCESSOR
                counts = p2pool_data.get_desired_version_counts(self.node.tracker,
                    self.node.tracker.get_nth_parent_hash(previous_share.hash, self.node.net.CHAIN_LENGTH*9//10), self.node.net.CHAIN_LENGTH//10)
                upgraded = counts.get(successor_type.VERSION, 0)/sum(counts.itervalues())
                if upgraded > .65:
                    print 'Switchover imminent. Upgraded: %.3f%% Threshold: %.3f%%' % (upgraded*100, 95)
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
            # 
            # DONATION SYSTEM:
            # V36 uses COMBINED_DONATION_SCRIPT (1-of-2 P2MS) in coinbase.
            # Full donation percentage goes to coinbase — no fake miner mechanism.
            
            share_data_base = dict(
                previous_share_hash=self.node.best_share_var.value,
                coinbase=(script.create_push_script([
                    self.current_work.value['height'],
                    ] + ([mm_data] if mm_data else []) + self.args.coinb_texts
                ) + self.current_work.value['coinbaseflags'] + getattr(self.node.net, 'COINBASEEXT', b''))[:100],
                nonce=random.randrange(2**32),
                subsidy=self.current_work.value['subsidy'],
                donation=math.perfect_round(65535*self.donation_percentage/100),
                stale_info=(lambda (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain):
                    'orphan' if orphans > orphans_recorded_in_chain else
                    'doa' if doas > doas_recorded_in_chain else
                    None
                )(*self.get_stale_counts()),
                desired_version=desired_ver,  # From AutoRatchet: always 36 (signals V36 capability)
            )
            
            if share_type.VERSION >= 36:
                # V36: store pubkey_hash as IntType(160) + pubkey_type (1 byte)
                share_data_base['pubkey_hash'] = pubkey_hash
                share_data_base['pubkey_type'] = pubkey_type  # 0=P2PKH, 1=P2WPKH/bech32, 2=P2SH
            elif share_type.VERSION >= 34:
                # V34-V35: use 'address' as a string
                _v35_ver, _v35_wv = p2pool_data.pubkey_type_to_version_witver(pubkey_type, self.node.net.PARENT)
                share_data_base['address'] = bitcoin_data.pubkey_hash_to_address(pubkey_hash, _v35_ver, _v35_wv, self.node.net.PARENT)
            else:
                # Older share versions use 'pubkey_hash' as an integer  
                share_data_base['pubkey_hash'] = pubkey_hash
            
            # Build validated merged_addresses list for V36 share storage.
            # Only include addresses that passed validation in get_user_details().
            # If miner provided no merged address or it failed validation,
            # merged_addresses_for_share will be None (triggers auto-conversion).
            merged_addresses_for_share = None
            current_merged = getattr(self, '_current_merged_addresses', {})
            if current_merged and current_merged.get('_validated'):
                merged_addresses_for_share = current_merged['_validated']
            
            # V36+: Collect merged coinbase verification data from effective_merged_work.
            # Each chain with canonical coinbase enforcement contributes one entry.
            merged_coinbase_info_for_share = None
            if v36_active and effective_merged_work:
                mci_entries = []
                for chain_id, emw in effective_merged_work.iteritems():
                    entry = emw.get('merged_coinbase_info_entry')
                    if entry:
                        mci_entries.append(entry)
                if mci_entries:
                    merged_coinbase_info_for_share = mci_entries
            
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
                v36_active=v36_active,  # Pass V36 status for donation script switch
                merged_addresses=merged_addresses_for_share,  # Validated merged chain addresses
                message_data=self.transition_message_data if v36_active else None,
                merged_coinbase_info=merged_coinbase_info_for_share,  # Merged coinbase verification data
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
        
        # CRITICAL: When segwit is activated, Share.__init__ validates using segwit_data['txid_merkle_link']
        # (merkle tree of txids, NOT wtxids). The stratum merkle_link sent to miners MUST match this,
        # otherwise the reconstructed merkle_root in __init__ will differ from the miner's header
        # and ALL shares will fail with "share PoW invalid".
        # When segwit is NOT activated, use other_transaction_hashes directly (which are wtxids from GBT).
        merkle_link = bitcoin_data.calculate_merkle_link([None] + other_transaction_hashes, 0) if share_info.get('segwit_data', None) is None else share_info['segwit_data']['txid_merkle_link']


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
                _display_ver, _display_wv = p2pool_data.pubkey_type_to_version_witver(pubkey_type, self.node.net.PARENT)
                print 'New work for worker %s! Difficulty: %.06f Share difficulty: %.06f (%sH/s) Total block value: %.6f %s including %i transactions' % (
                    bitcoin_data.pubkey_hash_to_address(pubkey_hash, _display_ver, _display_wv, self.node.net.PARENT),
                    bitcoin_data.target_to_difficulty(target),
                    bitcoin_data.target_to_difficulty(share_info['bits'].target),
                    math.format(int(local_addr_rates.get(pubkey_hash, 0))),
                    self.current_work.value['subsidy']*1e-8, self.node.net.PARENT.SYMBOL,
                    len(self.current_work.value['transactions']),
                )
                print_throttle = time.time()

        #need this for stats
        _stats_ver, _stats_wv = p2pool_data.pubkey_type_to_version_witver(pubkey_type, self.node.net.PARENT)
        self.last_work_shares.value[bitcoin_data.pubkey_hash_to_address(pubkey_hash, _stats_ver, _stats_wv, self.node.net.PARENT)]=share_info['bits']

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
            
            if len(coinbase_nonce) != self.COINBASE_NONCE_LENGTH:
                raise ValueError('coinbase_nonce length mismatch: got %d, expected %d' % (len(coinbase_nonce), self.COINBASE_NONCE_LENGTH))
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
            new_hexed_gentx = bitcoin_data.tx_type.pack(new_gentx).encode('hex')

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
                ratio = float(header['bits'].target) / float(pow_hash) if pow_hash > 0 else 0.0
                print >>sys.stderr, 'New best hash! pow=%064x target=%064x (%.8f%% of target)' % (pow_hash, header['bits'].target, ratio * 100)
            if self._attempt_counter % 1000 == 0:
                print >>sys.stderr, 'Block mining: %d attempts, best=%.8f%% of target' % (self._attempt_counter, (float(header['bits'].target) / float(self._best_pow_hash) * 100) if self._best_pow_hash > 0 else 0.0)
            
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
                            witness_reserved_value_str = '[P2Pool]'*4
                            witness_reserved_value = pack.IntType(256).unpack(witness_reserved_value_str)
                            expected_commitment = bitcoin_data.get_witness_commitment_hash(calculated_wtxid_merkle_root, witness_reserved_value)
                            if committed_hash != expected_commitment:
                                print >>sys.stderr, 'Witness commitment mismatch! calculated=%064x committed=%064x' % (expected_commitment, committed_hash)
                    
                    # Submit block and add error callback to catch any failures
                    # Use broadcaster for parallel propagation if available
                    block_submission = helper.submit_block(
                        dict(header=header, txs=[new_hexed_gentx] + [tx["data"] for tx in other_transactions]),
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
                        # For scrypt coins, header_hash (from BLOCKHASH_FUNC) is the scrypt/PoW hash,
                        # but the tracker uses SHA256d for s.header_hash. We need the SHA256d hash
                        # so the immediate record can be matched with the tracker record later.
                        sha256d_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(header))
                        # Get block subsidy and miner's current payout for reward tracking
                        block_subsidy = self.current_work.value.get('subsidy', 0)
                        miner_payout = 0
                        try:
                            current_txouts = self.node.get_current_txouts()
                            # Strip merged DOGE address (comma) and worker suffix for txout lookup
                            base_user = user.split(',')[0].split('.')[0].split('_')[0]
                            miner_payout = current_txouts.get(base_user, 0)
                        except:
                            pass
                        block_info = {
                            'ts': time.time(),
                            'hash': '%064x' % sha256d_hash,
                            'pow_hash_hex': '%064x' % pow_hash,
                            'number': share_info.get('height', 0),
                            'miner': user,
                            'network_difficulty': bitcoin_data.target_to_difficulty(header['bits'].target),
                            'pow_hash': pow_hash,
                            'target': header['bits'].target,
                            'subsidy': block_subsidy,
                            'miner_payout': miner_payout,
                        }
                        self.block_found.happened(block_info)
                        # Reset round-level best difficulty stats
                        self.reset_round_best_difficulty()
            except:
                log.err(None, 'Error while processing potential block:')

            user, _, _, _, _, _ = self.get_user_details(user)
            if header['previous_block'] != ba['previous_block']:
                raise ValueError('header previous_block does not match work assignment')
            # Note: header['merkle_root'] is calculated in stratum.py with the correct coinbase_nonce
            # Don't recalculate it here because worker_interface.py prepends additional nonce data
            if header['bits'] != ba['bits']:
                raise ValueError('header bits does not match work assignment')

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

            # Merged mining diagnostic: always log when parent block found
            if pow_hash <= header['bits'].target:
                if mm_later:
                    print >>sys.stderr, '[MERGED-DIAG] Parent block found! mm_later has %d chain(s), pow_hash=%064x' % (len(mm_later), pow_hash)
                    for _aw, _idx, _hs in mm_later:
                        _meets = pow_hash <= _aw['target']
                        print >>sys.stderr, '[MERGED-DIAG]   chain=%s target=%064x meets=%s multiaddress=%s' % (
                            _aw.get('merged_net_symbol', '?'), _aw['target'], _meets, _aw.get('multiaddress', False))
                else:
                    print >>sys.stderr, '[MERGED-DIAG] WARNING: Parent block found but mm_later is EMPTY! No merged mining check will run.'
                    print >>sys.stderr, '[MERGED-DIAG]   merged_work.value has %d chain(s)' % len(self.merged_work.value)
                    if self.merged_work.value:
                        # mm_later was empty at get_work() time but merged work exists NOW.
                        # Cannot submit merged block (LTC coinbase lacks fabe6d6d commitment).
                        # But log what WOULD have been a twin so we can track missed opportunities.
                        for _cid, _mw in self.merged_work.value.iteritems():
                            if pow_hash <= _mw.get('target', 0):
                                print >>sys.stderr, '[MERGED-DIAG] MISSED TWIN! %s target=%064x WOULD have qualified but LTC coinbase has no merged commitment' % (
                                    _mw.get('merged_net_symbol', 'chain_%s' % _cid), _mw['target'])

            if mm_later and pow_hash <= mm_later[0][0]['target']:
                pass  # Target met — will be processed in loop below

            for aux_work, index, hashes in mm_later:
                try:
                    # Merged mining: Check if hash meets Auxiliary chain (Dogecoin) difficulty
                    # Three scenarios:
                    # 1. pow_hash < aux_work['target'] only: Valid DOGE block (partial win)
                    # 2. pow_hash < both targets: Valid LTC + DOGE blocks (full win)
                    # 3. pow_hash < header['bits'].target only: Valid LTC block only
                    
                    # Log when parent block found - check if merged block should also be submitted
                    if pow_hash <= header['bits'].target:
                        # Debug: Uncomment for merged check diagnostics
                        # print >>sys.stderr, '[MERGED CHECK] Parent block found! pow=%064x parent_target=%064x merged_target=%064x' % (pow_hash, header['bits'].target, aux_work['target'])
                        
                        # TWIN BLOCK DETECTION: Same POW hash accepted by BOTH chains!
                        if pow_hash <= aux_work['target']:
                            merged_net_name = aux_work.get('merged_net_name', 'Merged Chain')
                            merged_net_symbol = aux_work.get('merged_net_symbol', 'MERGED')
                            print '*** TWIN BLOCK! %s (%s) + %s (%s) | POW: %064x ***' % (
                                self.node.net.PARENT.NAME, self.node.net.PARENT.SYMBOL,
                                merged_net_name, merged_net_symbol, pow_hash)
                    
                    # Debug: Uncomment to trace merged block candidates
                    # if pow_hash <= aux_work['target']:
                    #     print >>sys.stderr, 'Dogecoin block candidate: pow_hash=%064x target=%064x ratio=%.2f%%' % (
                    #         pow_hash, aux_work['target'], float(pow_hash) / float(aux_work['target']) * 100)
                    
                    if pow_hash <= aux_work['target']:
                        # Hash meets Dogecoin difficulty - submit auxpow block
                        merged_net_sym = aux_work.get('merged_net_symbol', 'MERGED')
                        print >>sys.stderr, '[MERGED-SUBMIT] %s target met! pow=%064x target=%064x Building block...' % (
                            merged_net_sym, pow_hash, aux_work['target'])
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
                                
                                # Pack transactions individually then concatenate.
                                # Avoids StringIO unicode/bytes mixing in Python 2:
                                # StringIO.getvalue() calls ''.join(buflist) which fails when
                                # buffers contain mixed unicode (from JSON text) and bytes
                                # with non-ASCII values (e.g., coinbase previous_output 0xffffffff).
                                # Individual tx_type.pack() calls each use a fresh StringIO
                                # which avoids cross-transaction contamination.
                                txs_varint = pack.VarIntType().pack(len(merged_block['txs']))
                                txs_parts = [txs_varint]
                                for tx in merged_block['txs']:
                                    packed_tx = bitcoin_data.tx_type.pack(tx)
                                    # Defensive: ensure bytes (str), not unicode
                                    if isinstance(packed_tx, unicode):
                                        packed_tx = packed_tx.encode('latin-1')
                                    txs_parts.append(packed_tx)
                                txs_packed = ''.join(txs_parts)
                                
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
                                
                                # Submit via primary RPC first, then broadcast to peers
                                df = deferral.retry('Error submitting multiaddress merged block: (will retry)', 10, 10)(
                                    aux_work['merged_proxy'].rpc_submitblock
                                )(complete_block_hex)
                                
                                @df.addCallback
                                def _(result, aux_work=aux_work, complete_block_hex=complete_block_hex):
                                    # submitblock returns: None=accepted, 'duplicate'=already in chain (also success),
                                    # 'inconclusive'=may have been accepted, other string=rejection reason
                                    if result is None or result == True or result == 'duplicate' or result == 'duplicate-invalid' or result == 'inconclusive':
                                        if result == 'duplicate':
                                            print '  (Note: block already accepted via parallel submission)'
                                        
                                        # Fire broadcast to P2P peers AFTER successful primary RPC submission
                                        chainid = aux_work.get('chainid', 98)
                                        if chainid in self.node.merged_broadcasters:
                                            try:
                                                bc = self.node.merged_broadcasters[chainid]
                                                bc_d = bc.broadcast_block(complete_block_hex, aux_work['hash'])
                                                bc_d.addErrback(lambda f: None)  # Ignore broadcaster errors
                                            except Exception as e:
                                                print >>sys.stderr, 'Merged broadcaster error: %s' % e
                                        print
                                        merged_net_name = aux_work.get('merged_net_name', 'Unknown')
                                        merged_net_symbol = aux_work.get('merged_net_symbol', 'UNKNOWN')
                                        merged_template = aux_work.get('template', {})
                                        print '### MERGED BLOCK FOUND! %s (%s) height=%d hash=%064x miner=%s txs=%d size=%d ###' % (
                                            merged_net_name, merged_net_symbol,
                                            merged_template.get('height', aux_work.get('height', 0)),
                                            aux_work['hash'], user,
                                            len(merged_block['txs']), len(complete_block))
                                        print
                                        
                                        # Record merged block find
                                        total_reward = merged_template.get('coinbasevalue', aux_work.get('coinbasevalue', 0))
                                        
                                        # Calculate miner's estimated payout from PPLNS shareholders
                                        miner_payout = 0
                                        try:
                                            sh = aux_work.get('shareholders', {})
                                            don_pct = aux_work.get('donation_percentage', 1.0)
                                            node_owner_fee = aux_work.get('node_owner_fee', aux_work.get('worker_fee', 0))
                                            miners_reward = total_reward - int(total_reward * don_pct / 100) - (int(total_reward * node_owner_fee / 100) if node_owner_fee > 0 else 0)
                                            # Match miner address (strip worker suffix) to shareholder
                                            base_user = user.split('.')[0].split('_')[0].split('+')[0].split('/')[0]
                                            for addr, val in sh.iteritems():
                                                frac = val[0] if isinstance(val, tuple) else val
                                                # Check if shareholder address matches miner (parent or merged chain)
                                                # Shareholders may be in merged chain format, so also try parent address match
                                                addr_base = addr.split('.')[0].split('_')[0].split('+')[0].split('/')[0]
                                                if addr_base == base_user:
                                                    miner_payout = int(miners_reward * frac)
                                                    break
                                            # If no direct match found, the shareholder addresses are in merged chain format
                                            # Try converting the miner's parent address to merged chain format
                                            if miner_payout == 0 and sh:
                                                try:
                                                    parent_net = self.node.net.PARENT if hasattr(self.node.net, 'PARENT') else self.node.net
                                                    addr_result = is_pubkey_hash_address(base_user, parent_net)
                                                    is_conv = addr_result[0]
                                                    pkh = addr_result[1]
                                                    a_type = addr_result[3] if len(addr_result) > 3 else 'p2pkh'
                                                    if is_conv and pkh:
                                                        chainid_val = aux_work.get('chainid', 0)
                                                        p_sym = getattr(parent_net, 'SYMBOL', '')
                                                        is_tn = p_sym.lower().startswith('t') or 'test' in p_sym.lower()
                                                        if chainid_val == 98:
                                                            m_net = dogecoin_testnet_net if is_tn else dogecoin_net
                                                        else:
                                                            m_net = parent_net
                                                        if m_net:
                                                            if a_type == 'p2sh':
                                                                merged_addr = bitcoin_data.pubkey_hash_to_address(pkh, m_net.ADDRESS_P2SH_VERSION, -1, m_net)
                                                            else:
                                                                merged_addr = bitcoin_data.pubkey_hash_to_address(pkh, m_net.ADDRESS_VERSION, -1, m_net)
                                                            for addr, val in sh.iteritems():
                                                                if addr == merged_addr:
                                                                    frac = val[0] if isinstance(val, tuple) else val
                                                                    miner_payout = int(miners_reward * frac)
                                                                    break
                                                except Exception:
                                                    pass
                                        except Exception as e:
                                            print >>sys.stderr, '[MERGED] Error calculating miner payout: %s' % e
                                        
                                        block_record = dict(
                                            ts=time.time(),
                                            hash='%064x' % aux_work['hash'],
                                            pow_hash='%064x' % pow_hash,
                                            target='%064x' % aux_work['target'],
                                            network=merged_net_name,
                                            symbol=merged_net_symbol,
                                            miner=user,
                                            chainid=aux_work.get('chainid', 0),
                                            height=merged_template.get('height', aux_work.get('height', 0)),
                                            coinbasevalue=total_reward,
                                            miner_payout=miner_payout,
                                            txs=len(merged_block['txs']),
                                            size=len(complete_block),
                                            verified=None,  # None=pending, True=confirmed, False=orphaned
                                        )
                                        self.recent_merged_blocks.append(block_record)
                                        # Keep only last 100 merged blocks
                                        if len(self.recent_merged_blocks) > 100:
                                            self.recent_merged_blocks = self.recent_merged_blocks[-100:]
                                        # Reset merged round best difficulty
                                        self.reset_merged_round_best_difficulty()
                                        
                                        # Async verification after a delay
                                        if 'merged_proxy' in aux_work:
                                            def verify_block(block_rec, proxy, block_hash):
                                                verify_df = proxy.rpc_getblock('%064x' % block_hash)
                                                @verify_df.addCallback
                                                def on_verify(block_info):
                                                    block_rec['verified'] = True
                                                @verify_df.addErrback
                                                def on_verify_fail(err):
                                                    block_rec['verified'] = False
                                                    print >>sys.stderr, 'Merged block orphaned (not in chain): %064x' % block_hash
                                            reactor.callLater(5.0, verify_block, block_record, aux_work['merged_proxy'], aux_work['hash'])
                                    else:
                                        print >>sys.stderr, 'Multiaddress merged block rejected: %s' % (result,)
                                
                                @df.addErrback
                                def _(err):
                                    print >>sys.stderr, '[MERGED-SUBMIT] ERROR: rpc_submitblock failed: %s' % (err.getErrorMessage() if hasattr(err, 'getErrorMessage') else err,)
                                    log.err(err, 'Error submitting multiaddress merged block:')
                                    
                            except Exception as e:
                                print >>sys.stderr, '[MERGED-SUBMIT] CRITICAL ERROR building multiaddress merged block: %s' % (e,)
                                import traceback
                                traceback.print_exc()
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
                                                    addr_result = is_pubkey_hash_address(user, parent_net)
                                                    is_convertible = addr_result[0]
                                                    pubkey_hash = addr_result[1]
                                                    addr_type = addr_result[3] if len(addr_result) > 3 else 'p2pkh'
                                                    if is_convertible and pubkey_hash:
                                                        if addr_type == 'p2sh':
                                                            miner_merged_address = bitcoin_data.pubkey_hash_to_address(
                                                                pubkey_hash, merged_net.ADDRESS_P2SH_VERSION, -1, merged_net)
                                                        else:
                                                            miner_merged_address = bitcoin_data.pubkey_hash_to_address(
                                                                pubkey_hash, merged_net.ADDRESS_VERSION, -1, merged_net)
                                        except Exception as e:
                                            pass  # Keep original address on error
                                        
                                        # In single-address mode, miner gets full reward minus fees
                                        sa_coinbasevalue = aux_work.get('coinbasevalue', 0)
                                        sa_don_pct = getattr(self, 'donation_percentage', 1.0)
                                        sa_node_owner_fee = getattr(self, 'node_owner_fee', getattr(self, 'worker_fee', 0))
                                        sa_miner_payout = sa_coinbasevalue - int(sa_coinbasevalue * sa_don_pct / 100) - (int(sa_coinbasevalue * sa_node_owner_fee / 100) if sa_node_owner_fee > 0 else 0)
                                        
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
                                            height=aux_work.get('height', 0),
                                            coinbasevalue=sa_coinbasevalue,
                                            miner_payout=sa_miner_payout,
                                            is_testnet=is_testnet,
                                            verified=None,  # None=pending, True=confirmed, False=orphaned
                                        )
                                        self.recent_merged_blocks.append(block_record)
                                        # Keep only last 100 merged blocks
                                        if len(self.recent_merged_blocks) > 100:
                                            self.recent_merged_blocks = self.recent_merged_blocks[-100:]
                                        # Reset merged round best difficulty
                                        self.reset_merged_round_best_difficulty()
                                        
                                        # For testnet: async verification after a delay
                                        # Use aux_work['hash'] (Dogecoin block hash) NOT pow_hash (scrypt hash)
                                        if is_testnet and 'merged_proxy' in aux_work:
                                            def verify_block(block_rec, proxy, block_hash):
                                                verify_df = proxy.rpc_getblock('%064x' % block_hash)
                                                @verify_df.addCallback
                                                def on_verify(block_info):
                                                    # Block found in chain - mark as verified
                                                    block_rec['verified'] = True
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
                    print >>sys.stderr, '[MERGED-SUBMIT] CRITICAL ERROR in merged mining POW processing:'
                    import traceback
                    traceback.print_exc()
                    log.err(None, 'Error while processing merged mining POW:')

            # P2Pool share creation - re-enabled for PERSIST=False bootstrap
            # Note: Stratum miners change coinbase_nonce which modifies gentx.
            # Share.__init__ reconstructs gentx and this should now work correctly.
            # CRITICAL: Only attempt share creation if merkle_root matches current work template!
            # If work_merkle_root != header['merkle_root'], the submitted work is stale (from old template)
            if pow_hash <= share_info['bits'].target and header_hash not in received_header_hashes and work_merkle_root == header['merkle_root']:
                last_txout_nonce = pack.IntType(8*self.COINBASE_NONCE_LENGTH).unpack(coinbase_nonce)
                try:
                    share = get_share(header, last_txout_nonce)
                except Exception as e:
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
            _bench_ver, _bench_wv = p2pool_data.pubkey_type_to_version_witver(pubkey_type, self.node.net.PARENT)
            print "%8.3f ms for work.py:get_work(%s)" % ((t1-t0)*1000., bitcoin_data.pubkey_hash_to_address(pubkey_hash, _bench_ver, _bench_wv, self.node.net.PARENT))
        
        return ba, got_response
