"""
Network Broadcaster - Independent peer discovery and parallel block broadcasting

This module maintains an independent peer database and broadcasts found blocks
to multiple network nodes simultaneously for faster propagation.

Adapted for Litecoin (parent chain) with support for any Bitcoin-derived network.
For merged mining child chains (Dogecoin), see merged_broadcaster.py

Key features:
- Bootstrap from local node, then maintain independent peer list
- Discover new peers via P2P 'addr' messages
- Quality-based peer scoring and automatic rotation
- Protected local node connection (never dropped)
- Persistent peer database
- TRUE PARALLEL block broadcast to all peers simultaneously
"""

from __future__ import division, print_function

import json
import os
import sys
import time

from twisted.internet import defer, reactor, protocol
from twisted.python import log, failure

from . import data as bitcoin_data, p2p as bitcoin_p2p
from p2pool.util import deferral, variable


def _with_timeout(df, timeout):
    """Wrap a deferred with a timeout.
    
    Returns a new deferred that either:
    - Succeeds with the original deferred's result if it fires within timeout
    - Fails with TimeoutError if the timeout expires first
    """
    result_df = defer.Deferred()
    timed_out = [False]  # mutable to allow modification in nested function
    
    def on_timeout():
        timed_out[0] = True
        if not result_df.called:
            result_df.errback(failure.Failure(defer.TimeoutError('Connection timeout')))
    
    timeout_call = reactor.callLater(timeout, on_timeout)
    
    def on_success(result):
        if not timed_out[0] and not result_df.called:
            timeout_call.cancel()
            result_df.callback(result)
    
    def on_failure(fail):
        if not timed_out[0] and not result_df.called:
            timeout_call.cancel()
            result_df.errback(fail)
    
    df.addCallbacks(on_success, on_failure)
    return result_df


def _safe_addr_str(addr):
    """Safely format address tuple for printing"""
    try:
        if isinstance(addr, tuple) and len(addr) == 2:
            host, port = addr
            # Ensure host is ASCII-safe string
            if hasattr(host, 'encode'):
                try:
                    host = host.encode('ascii', 'replace') if isinstance(host, unicode) else host
                except NameError:
                    pass  # Python 3
            return '%s:%d' % (host, port)
        return str(addr)
    except Exception:
        return repr(addr)


class NetworkBroadcaster(object):
    """Manages independent P2P connections to network nodes for block broadcasting
    
    This broadcaster maintains its own peer list independent of the local node,
    bootstrapping from the node's peers initially and then discovering new peers
    via P2P addr messages.
    
    Key Design Principles:
    1. LOCAL NODE CONNECTION IS SACRED - Never disconnect the local node
    2. TRUE PARALLEL broadcast - All peers receive blocks simultaneously
    3. Quality-based scoring - Better peers get higher priority
    4. Persistent database - Peers survive restarts
    """
    
    def __init__(self, net, coind, local_factory, local_addr, datadir_path, chain_name='bitcoin'):
        """Initialize broadcaster
        
        Args:
            net: Network configuration object (e.g., litecoin mainnet)
            coind: JSON-RPC proxy to local node
            local_factory: Existing P2P factory for local node (PROTECTED)
            local_addr: (host, port) tuple for local node
            datadir_path: Directory to store peer database
            chain_name: Name for logging/database files (e.g., 'litecoin')
        """
        print('Broadcaster[%s]: Initializing NetworkBroadcaster...' % chain_name)
        
        self.net = net
        self.coind = coind
        self.local_factory = local_factory
        self.local_addr = local_addr
        self.datadir_path = datadir_path
        self.chain_name = chain_name
        
        # Peer database: (host, port) -> peer info dict
        self.peer_db = {}
        
        # Active connections: (host, port) -> connection info dict
        self.connections = {}
        
        # Track node's peer connections (to avoid duplication)
        self.coind_peers = set()  # Set of (host, port) tuples node is connected to
        
        # Connection tracking for retry logic
        self.connection_attempts = {}  # (host, port) -> attempt count
        self.connection_failures = {}  # (host, port) -> (last_failure_time, backoff_seconds)
        self.last_coind_refresh = 0    # Timestamp of last node peer refresh
        
        # Rate-limited connection management (to prevent CPU saturation)
        self.pending_connections = set()  # Peers we're currently trying to connect to
        self.max_concurrent_connections = 3  # Max simultaneous connection attempts
        self.max_connections_per_cycle = 5  # Max new connections to start per refresh cycle
        self.base_backoff = 30  # Initial backoff time in seconds
        self.max_backoff = 3600  # Maximum backoff time (1 hour)
        
        # Discovery control - stop when at capacity
        self.discovery_enabled = True  # Enable/disable peer discovery
        
        # Configuration
        self.max_peers = 20  # Total connections including local node
        self.min_peers = 5   # Minimum required for health
        self.max_connection_attempts = 10  # Max retries per peer before giving up
        self.connection_timeout = 300  # 5 minutes backoff after max failures
        self.coind_refresh_interval = 1800  # 30 minutes between node refreshes
        self.bootstrapped = False
        
        # Valid P2P ports for this network
        # Litecoin: 9333 (mainnet), 19335 (testnet4), 19333 (regtest)
        # Bitcoin: 8333 (mainnet), 18333 (testnet), 18444 (regtest)
        self.valid_ports = [
            net.P2P_PORT,  # Primary port from network config
        ]
        # Add common ports for the network type
        if hasattr(net, 'TESTNET') and net.TESTNET:
            self.valid_ports.extend([19335, 19333, 18333, 18444])
        else:
            self.valid_ports.extend([9333, 8333])  # Mainnet ports
        self.valid_ports = list(set(self.valid_ports))  # Dedupe
        
        # Shutdown flag
        self.stopping = False
        
        # Statistics
        self.stats = {
            'blocks_sent': 0,
            'total_broadcasts': 0,
            'successful_broadcasts': 0,
            'failed_broadcasts': 0,
            'peer_stats': {},  # (host, port) -> detailed stats
            'connection_stats': {
                'total_attempts': 0,
                'successful_connections': 0,
                'failed_connections': 0,
                'timeouts': 0,
                'refused': 0,
                'coind_refreshes': 0
            }
        }
        
        print('Broadcaster[%s]: Configuration:' % chain_name)
        print('  Max peers: %d' % self.max_peers)
        print('  Min peers: %d' % self.min_peers)
        print('  Valid P2P ports: %s' % self.valid_ports)
        print('  Local node: %s (PROTECTED)' % _safe_addr_str(local_addr))
        print('  Data directory: %s' % datadir_path)
        print('Broadcaster[%s]: Initialization complete' % chain_name)
    
    @defer.inlineCallbacks
    def start(self):
        """Start the broadcaster (bootstrap and begin peer management)"""
        print('Broadcaster[%s]: Starting broadcaster...' % self.chain_name)
        
        # Load persistent peer database
        self._load_peer_database()
        
        # Bootstrap from node if needed
        if not self.bootstrapped or len(self.peer_db) < self.min_peers:
            yield self.bootstrap_from_coind()
        else:
            print('Broadcaster[%s]: Using cached peer database (%d peers)' % (
                self.chain_name, len(self.peer_db)))
        
        # Start adaptive peer refresh (smart polling)
        self.refresh_loop = deferral.RobustLoopingCall(self._adaptive_refresh)
        self.refresh_loop.start(5)  # Check every 5 seconds
        print('Broadcaster[%s]: Adaptive peer refresh started' % self.chain_name)
        
        # Start periodic database save
        self.save_loop = deferral.RobustLoopingCall(self._save_peer_database)
        self.save_loop.start(300)  # Every 5 minutes
        print('Broadcaster[%s]: Database save loop started' % self.chain_name)
        
        print('Broadcaster[%s]: Start complete' % self.chain_name)
        defer.returnValue(True)
    
    def stop(self):
        """Stop the broadcaster and clean up"""
        print('Broadcaster[%s]: Stopping...' % self.chain_name)
        self.stopping = True
        
        if hasattr(self, 'refresh_loop'):
            self.refresh_loop.stop()
        if hasattr(self, 'save_loop'):
            self.save_loop.stop()
        
        # Save peer database
        self._save_peer_database()
        
        # Disconnect non-protected peers
        for addr in list(self.connections.keys()):
            if not self.connections[addr].get('protected'):
                self._disconnect_peer(addr)
        
        print('Broadcaster[%s]: Stopped' % self.chain_name)
    
    @defer.inlineCallbacks
    def bootstrap_from_coind(self):
        """One-time bootstrap: get initial peer list from local node"""
        print('')
        print('=' * 70)
        print('Broadcaster[%s]: BOOTSTRAP PHASE - Fetching peers from node' % self.chain_name)
        print('=' * 70)
        
        if self.bootstrapped:
            print('Broadcaster[%s]: Already bootstrapped, skipping' % self.chain_name)
            defer.returnValue(len(self.peer_db))
        
        # CRITICAL: Add local node with maximum priority
        print('Broadcaster[%s]: Registering local node as PROTECTED peer' % self.chain_name)
        self.peer_db[self.local_addr] = {
            'addr': self.local_addr,
            'score': 999999,  # Maximum score - never drop!
            'first_seen': time.time(),
            'last_seen': time.time(),
            'source': 'local_coind',
            'protected': True,  # CRITICAL FLAG
            'successful_broadcasts': 0,
            'failed_broadcasts': 0,
        }
        
        # Register the existing local node connection
        self.connections[self.local_addr] = {
            'factory': self.local_factory,
            'connector': None,  # Already connected
            'connected_at': time.time(),
            'protected': True  # CRITICAL FLAG
        }
        print('Broadcaster[%s]: Local node at %s marked as PROTECTED' % (
            self.chain_name, _safe_addr_str(self.local_addr)))
        
        # Get additional peers from node via RPC
        try:
            print('Broadcaster[%s]: Querying node.rpc_getpeerinfo()...' % self.chain_name)
            peer_info = yield self.coind.rpc_getpeerinfo()
            print('Broadcaster[%s]: Received %d peers from node' % (self.chain_name, len(peer_info)))
            
            added_count = 0
            for peer in peer_info:
                addr_str = peer.get('addr', '')
                if not addr_str:
                    continue
                
                # Parse address (handle IPv6)
                if addr_str.startswith('['):
                    # IPv6: [::1]:9333
                    if ']:' in addr_str:
                        host, port = addr_str.rsplit(':', 1)
                        host = host[1:-1]  # Remove brackets
                        port = int(port)
                    else:
                        continue
                elif ':' in addr_str:
                    host, port = addr_str.rsplit(':', 1)
                    port = int(port)
                else:
                    host = addr_str
                    port = self.net.P2P_PORT
                
                addr = (host, port)
                
                # Skip if this is local node (already added)
                if addr == self.local_addr:
                    continue
                
                # Filter out ephemeral ports
                if port not in self.valid_ports:
                    continue
                
                # Calculate initial score based on node metrics
                # NOTE: coind peers get LOWER priority because the coin daemon
                # will broadcast to these peers itself. P2P discovered peers
                # provide additional coverage that the daemon won't reach.
                score = 30  # Low base score - daemon handles these
                
                # Prefer outbound connections
                if not peer.get('inbound', True):
                    score += 100
                
                # Prefer low latency
                ping_ms = peer.get('pingtime', 1.0) * 1000
                if ping_ms < 50:
                    score += 50
                elif ping_ms < 100:
                    score += 30
                elif ping_ms < 200:
                    score += 10
                
                # Prefer long uptime
                conn_time = peer.get('conntime', 0)
                if conn_time > 3600:
                    score += 20
                
                # Add to database
                self.peer_db[addr] = {
                    'addr': addr,
                    'score': score,
                    'first_seen': time.time(),
                    'last_seen': time.time(),
                    'source': 'coind',
                    'protected': False,
                    'successful_broadcasts': 0,
                    'failed_broadcasts': 0,
                    'ping_ms': ping_ms,
                    'outbound': not peer.get('inbound', True)
                }
                added_count += 1
            
            print('Broadcaster[%s]: Added %d new peers from node' % (self.chain_name, added_count))
            
        except Exception as e:
            print('Broadcaster[%s]: ERROR fetching peers from node: %s' % (self.chain_name, e), file=sys.stderr)
            log.err(e, 'Broadcaster bootstrap error:')
        
        self.bootstrapped = True
        print('Broadcaster[%s]: Bootstrap complete - %d total peers in database' % (
            self.chain_name, len(self.peer_db)))
        print('=' * 70)
        print('')
        
        # Start connecting to top peers
        yield self.refresh_connections()
        defer.returnValue(len(self.peer_db))
    
    @defer.inlineCallbacks
    def _refresh_peers_from_coind(self):
        """Refresh peer list from node (emergency or scheduled refresh)"""
        try:
            print('Broadcaster[%s]: Querying node for fresh peers...' % self.chain_name)
            peer_info = yield self.coind.rpc_getpeerinfo()
            
            # Clear and rebuild coind_peers set
            self.coind_peers.clear()
            
            added_count = 0
            updated_count = 0
            
            for peer in peer_info:
                addr_str = peer.get('addr', '')
                if not addr_str:
                    continue
                
                # Parse address
                if addr_str.startswith('['):
                    if ']:' in addr_str:
                        host, port = addr_str.rsplit(':', 1)
                        host = host[1:-1]
                        port = int(port)
                    else:
                        continue
                elif ':' in addr_str:
                    host, port = addr_str.rsplit(':', 1)
                    port = int(port)
                else:
                    host = addr_str
                    port = self.net.P2P_PORT
                
                addr = (host, port)
                
                # Skip local node
                if addr == self.local_addr:
                    continue
                
                # Track that node is connected to this peer
                self.coind_peers.add(addr)
                
                # Filter out ephemeral ports
                if port not in self.valid_ports:
                    continue
                
                # Calculate score - LOW for coind peers (daemon propagates to these)
                # P2P discovered peers get priority for unique coverage
                score = 30  # Low base - daemon handles these
                if not peer.get('inbound', True):
                    score += 30  # Smaller bonus for outbound
                
                ping_ms = peer.get('pingtime', 1.0) * 1000
                if ping_ms < 50:
                    score += 20
                elif ping_ms < 100:
                    score += 10
                elif ping_ms < 200:
                    score += 5
                
                conn_time = peer.get('conntime', 0)
                if conn_time > 3600:
                    score += 10
                
                # Add or update
                if addr not in self.peer_db:
                    self.peer_db[addr] = {
                        'addr': addr,
                        'score': score,
                        'first_seen': time.time(),
                        'last_seen': time.time(),
                        'source': 'coind_refresh',
                        'protected': False,
                        'successful_broadcasts': 0,
                        'failed_broadcasts': 0,
                        'ping_ms': ping_ms,
                        'outbound': not peer.get('inbound', True)
                    }
                    added_count += 1
                    print('Broadcaster[%s]: NEW peer: %s' % (self.chain_name, _safe_addr_str(addr)))
                    if addr in self.connection_failures:
                        del self.connection_failures[addr]
                else:
                    # Update existing peer
                    self.peer_db[addr]['last_seen'] = time.time()
                    self.peer_db[addr]['ping_ms'] = ping_ms
                    self.peer_db[addr]['score'] = max(self.peer_db[addr]['score'], score)
                    updated_count += 1
            
            self.last_coind_refresh = time.time()
            self.stats['connection_stats']['coind_refreshes'] += 1
            
            print('Broadcaster[%s]: Refresh complete - %d new, %d updated, %d total' % (
                self.chain_name, added_count, updated_count, len(self.peer_db)))
            
            defer.returnValue(added_count + updated_count)
            
        except Exception as e:
            print('Broadcaster[%s]: ERROR refreshing from node: %s' % (self.chain_name, e), file=sys.stderr)
            log.err(e, 'Broadcaster refresh error:')
            defer.returnValue(0)
    
    def handle_addr_message(self, addrs):
        """Handle 'addr' message from connected peers - discover new peers!
        
        Args:
            addrs: List of address dicts with 'host', 'port', 'timestamp'
        """
        if not addrs:
            return
        
        new_count = 0
        
        for addr_info in addrs:
            host = addr_info.get('host') or addr_info.get('address', {}).get('address')
            port = addr_info.get('port') or addr_info.get('address', {}).get('port', self.net.P2P_PORT)
            
            if not host:
                continue
            
            # Filter out non-standard ports
            if port not in self.valid_ports:
                continue
            
            addr = (host, port)
            timestamp = addr_info.get('timestamp', time.time())
            
            # Add to database if new
            if addr not in self.peer_db:
                self.peer_db[addr] = {
                    'addr': addr,
                    # P2P peers get HIGH priority - they provide unique coverage
                    # that the coin daemon won't reach (daemon uses its own peers)
                    'score': 150,  # Higher score - unique propagation paths
                    'first_seen': time.time(),
                    'last_seen': timestamp,
                    'source': 'p2p',
                    'protected': False,
                    'successful_broadcasts': 0,
                    'failed_broadcasts': 0,
                }
                new_count += 1
            else:
                # Update last_seen
                self.peer_db[addr]['last_seen'] = timestamp
        
        if new_count > 0:
            print('Broadcaster[%s]: P2P discovery - %d new peers (total: %d)' % (
                self.chain_name, new_count, len(self.peer_db)))
    
    @defer.inlineCallbacks
    def _adaptive_refresh(self):
        """Adaptive refresh - only act when needed"""
        if self.stopping:
            return
        
        current_time = time.time()
        active_peers = len([c for c in self.connections.values() if c.get('factory') and c['factory'].conn.value])
        
        # Emergency refresh if too few active peers
        if active_peers < self.min_peers:
            time_since_refresh = current_time - self.last_coind_refresh
            if time_since_refresh > 60:  # At least 1 min between emergency refreshes
                print('Broadcaster[%s]: Emergency refresh - only %d active peers' % (
                    self.chain_name, active_peers))
                yield self._refresh_peers_from_coind()
                yield self.refresh_connections()
        
        # Scheduled refresh
        elif current_time - self.last_coind_refresh > self.coind_refresh_interval:
            yield self._refresh_peers_from_coind()
            yield self.refresh_connections()
    
    def _get_backoff_time(self, addr):
        """Get exponential backoff time for a peer"""
        if addr not in self.connection_failures:
            return 0
        last_failure, backoff = self.connection_failures[addr]
        return last_failure + backoff
    
    def _record_connection_failure(self, addr):
        """Record a connection failure with exponential backoff"""
        if addr in self.connection_failures:
            last_failure, old_backoff = self.connection_failures[addr]
            # Exponential backoff: double the delay each time, up to max
            new_backoff = min(old_backoff * 2, self.max_backoff)
        else:
            new_backoff = self.base_backoff
        
        self.connection_failures[addr] = (time.time(), new_backoff)
        attempts = self.connection_attempts.get(addr, 0) + 1
        self.connection_attempts[addr] = attempts
        
        # Remove from pending
        self.pending_connections.discard(addr)
    
    def _record_connection_success(self, addr):
        """Record a successful connection - reset backoff"""
        if addr in self.connection_failures:
            del self.connection_failures[addr]
        if addr in self.connection_attempts:
            del self.connection_attempts[addr]
        self.pending_connections.discard(addr)
    
    def _handle_connection_error(self, addr, failure):
        """Handle connection failure - record backoff"""
        self._record_connection_failure(addr)
    
    def refresh_connections(self):
        """Maintain connections to the best peers from our database
        
        Rate-limited and non-blocking connection management:
        - Limits concurrent pending connections
        - Uses exponential backoff for failed peers
        - Only attempts a few connections per cycle
        - Stops discovery when at max_peers capacity
        """
        if self.stopping:
            return
        
        current_time = time.time()
        
        # Verify local node connection and update its last_seen
        if self.local_addr not in self.connections:
            print('Broadcaster[%s]: WARNING - Local node not in connections!' % self.chain_name, file=sys.stderr)
            self.connections[self.local_addr] = {
                'factory': self.local_factory,
                'connector': None,
                'connected_at': time.time(),
                'protected': True
            }
        
        # Update last_seen for protected local node (it's always "active")
        if self.local_addr in self.peer_db:
            self.peer_db[self.local_addr]['last_seen'] = current_time
        
        current_connections = len(self.connections)
        
        # Check if we're at capacity - disable discovery if so
        if current_connections >= self.max_peers:
            if self.discovery_enabled:
                print('Broadcaster[%s]: At capacity (%d peers) - disabling discovery' % (
                    self.chain_name, current_connections))
                self.discovery_enabled = False
            return  # Nothing to do - we're at capacity
        
        # Re-enable discovery if we dropped below capacity
        if not self.discovery_enabled and current_connections < self.max_peers:
            print('Broadcaster[%s]: Below capacity (%d/%d) - enabling discovery' % (
                self.chain_name, current_connections, self.max_peers))
            self.discovery_enabled = True
        
        # Check how many connections we're already attempting
        pending_count = len(self.pending_connections)
        if pending_count >= self.max_concurrent_connections:
            return  # Don't start more connections
        
        # How many more connections can we attempt this cycle?
        available_slots = min(
            self.max_concurrent_connections - pending_count,
            self.max_connections_per_cycle,
            self.max_peers - len(self.connections)
        )
        
        if available_slots <= 0:
            return
        
        # Get sorted peers by score (exclude protected and already connected)
        # Use dynamic scoring that considers success rate, recency, and source
        scored_peers = []
        
        for addr, info in self.peer_db.items():
            host, port = addr
            # Skip protected peers (local coind)
            if info.get('protected'):
                continue
            # Skip already connected
            if addr in self.connections:
                continue
            # Skip already pending
            if addr in self.pending_connections:
                continue
            # Skip peers that coind is already connected to (avoid duplication)
            if addr in self.coind_peers:
                continue
            # Check exponential backoff
            if self._get_backoff_time(addr) > current_time:
                continue
            # Check max attempt count (give up after too many failures)
            if self.connection_attempts.get(addr, 0) >= self.max_connection_attempts:
                continue
            
            # Calculate dynamic score
            score = self._calculate_peer_score(info, current_time)
            scored_peers.append((score, addr, info))
        
        # Sort by score (highest first)
        scored_peers.sort(reverse=True)
        
        # Attempt connections to top peers (non-blocking)
        attempts_started = 0
        for score, addr, info in scored_peers[:available_slots]:
            # Mark as pending before starting
            self.pending_connections.add(addr)
            
            # Start connection attempt (don't yield - let it run in background)
            d = self._connect_to_peer(addr)
            d.addErrback(lambda f, a=addr: self._handle_connection_error(a, f))
            
            attempts_started += 1
            if attempts_started >= available_slots:
                break
    
    @defer.inlineCallbacks
    def _connect_to_peer(self, addr):
        """Connect to a peer"""
        host, port = addr
        
        print('Broadcaster[%s]: Connecting to %s...' % (self.chain_name, _safe_addr_str(addr)))
        
        factory = bitcoin_p2p.ClientFactory(self.net)
        connector = reactor.connectTCP(host, port, factory, timeout=10)
        
        self.stats['connection_stats']['total_attempts'] += 1
        
        try:
            # Wait for handshake with timeout
            protocol = yield _with_timeout(factory.getProtocol(), 15)
            
            self.connections[addr] = {
                'factory': factory,
                'connector': connector,
                'connected_at': time.time(),
                'protected': False
            }
            
            # Record successful connection (resets backoff)
            self._record_connection_success(addr)
            
            # Update peer database score
            if addr in self.peer_db:
                self.peer_db[addr]['last_seen'] = time.time()
                self.peer_db[addr]['score'] += 10  # Bonus for successful connection
            
            self.stats['connection_stats']['successful_connections'] += 1
            print('Broadcaster[%s]: Connected to %s' % (self.chain_name, _safe_addr_str(addr)))
            
            # Hook P2P messages for discovery and monitoring
            self._hook_protocol_messages(addr, protocol)
            
            # Request peer addresses for P2P discovery (only if discovery is enabled)
            if self.discovery_enabled:
                try:
                    if hasattr(protocol, 'send_getaddr') and callable(protocol.send_getaddr):
                        protocol.send_getaddr()
                        print('Broadcaster[%s]:   -> Sent getaddr request to %s' % (self.chain_name, _safe_addr_str(addr)))
                except Exception as e:
                    print('Broadcaster[%s]: Error sending getaddr to %s: %s' % (
                        self.chain_name, _safe_addr_str(addr), e), file=sys.stderr)
            
            defer.returnValue(True)
            
        except Exception as e:
            self.stats['connection_stats']['failed_connections'] += 1
            print('Broadcaster[%s]: Failed to connect to %s: %s' % (
                self.chain_name, _safe_addr_str(addr), e), file=sys.stderr)
            
            try:
                connector.disconnect()
            except:
                pass
            
            raise
    
    def _hook_protocol_messages(self, addr, protocol):
        """Hook P2P message handlers for peer discovery and monitoring"""
        # Hook addr message handler for P2P discovery
        original_handle_addr = getattr(protocol, 'handle_addr', None)
        if original_handle_addr:
            broadcaster = self  # Capture reference for closure
            
            def handle_addr_wrapper(addrs):
                # Convert to our format and pass to handler
                addr_list = []
                for addr_data in addrs:
                    addr_list.append({
                        'host': addr_data['address'].get('address', ''),
                        'port': addr_data['address'].get('port', broadcaster.net.P2P_PORT),
                        'timestamp': addr_data.get('timestamp', time.time())
                    })
                broadcaster.handle_addr_message(addr_list)
                return original_handle_addr(addrs)
            
            protocol.handle_addr = handle_addr_wrapper
        
        # Hook inv message handler to track block/tx announcements
        original_handle_inv = getattr(protocol, 'handle_inv', None)
        if original_handle_inv:
            broadcaster = self
            
            def handle_inv_wrapper(invs):
                for inv in invs:
                    inv_type = inv.get('type')
                    if inv_type == 'block':
                        broadcaster.handle_block_message(addr, inv.get('hash', 0))
                    elif inv_type == 'tx':
                        broadcaster.handle_tx_message(addr)
                return original_handle_inv(invs)
            
            protocol.handle_inv = handle_inv_wrapper
    
    def _disconnect_peer(self, addr):
        """Disconnect from a peer (NEVER disconnect protected peers!)"""
        if addr not in self.connections:
            return
        
        conn = self.connections[addr]
        
        # CRITICAL: Never disconnect protected peers!
        if conn.get('protected'):
            print('Broadcaster[%s]: REFUSED to disconnect PROTECTED peer %s' % (
                self.chain_name, _safe_addr_str(addr)), file=sys.stderr)
            return
        
        try:
            if conn.get('connector'):
                conn['connector'].disconnect()
        except Exception as e:
            print('Broadcaster[%s]: Error disconnecting %s: %s' % (
                self.chain_name, _safe_addr_str(addr), e), file=sys.stderr)
        
        del self.connections[addr]
        print('Broadcaster[%s]: Disconnected from %s' % (self.chain_name, _safe_addr_str(addr)))
    
    @defer.inlineCallbacks
    def broadcast_block(self, block):
        """Send block to ALL connected peers in TRUE PARALLEL
        
        Args:
            block: Block dict to broadcast
            
        Returns:
            Deferred that fires with number of successful sends
        """
        print('')
        print('=' * 70)
        print('Broadcaster[%s]: PARALLEL BLOCK BROADCAST INITIATED' % self.chain_name)
        print('=' * 70)
        
        if not self.bootstrapped:
            print('Broadcaster[%s]: Not bootstrapped yet, bootstrapping now...' % self.chain_name)
            yield self.bootstrap_from_coind()
        
        if len(self.connections) < self.min_peers:
            print('Broadcaster[%s]: Insufficient peers (%d < %d), refreshing...' % (
                self.chain_name, len(self.connections), self.min_peers))
            yield self.refresh_connections()
        
        block_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(block['header']))
        
        print('Broadcaster[%s]: Block details:' % self.chain_name)
        print('  Block hash: %064x' % block_hash)
        print('  Target peers: %d' % len(self.connections))
        print('  Transactions: %d' % len(block.get('txs', [])))
        
        # Send to ALL peers in parallel
        deferreds = []
        peer_addrs = []
        
        start_time = time.time()
        
        for addr, conn in self.connections.items():
            d = self._send_block_to_peer(addr, conn, block)
            deferreds.append(d)
            peer_addrs.append(addr)
        
        if not deferreds:
            print('Broadcaster[%s]: ERROR - No peers available for broadcast!' % self.chain_name, file=sys.stderr)
            defer.returnValue(0)
        
        print('Broadcaster[%s]: Broadcasting to %d peers in PARALLEL...' % (self.chain_name, len(deferreds)))
        
        # Wait for all sends to complete
        results = yield defer.DeferredList(deferreds, consumeErrors=True)
        
        broadcast_time = time.time() - start_time
        
        # Update statistics
        for (success, result), addr in zip(results, peer_addrs):
            if addr in self.peer_db:
                if success and result:
                    self.peer_db[addr]['successful_broadcasts'] += 1
                    self.peer_db[addr]['last_seen'] = time.time()
                    self.peer_db[addr]['score'] += 10  # Bonus for successful broadcast
                else:
                    self.peer_db[addr]['failed_broadcasts'] += 1
                    self.peer_db[addr]['score'] = max(0, self.peer_db[addr]['score'] - 5)
        
        successes = sum(1 for success, result in results if success and result)
        failures = len(results) - successes
        
        # Update global stats
        self.stats['blocks_sent'] += 1
        self.stats['total_broadcasts'] += len(results)
        self.stats['successful_broadcasts'] += successes
        self.stats['failed_broadcasts'] += failures
        
        # Check local node result
        local_success = None
        if self.local_addr in peer_addrs:
            idx = peer_addrs.index(self.local_addr)
            local_success = results[idx][0] and results[idx][1]
        
        # Log results
        print('')
        print('Broadcaster[%s]: BROADCAST COMPLETE' % self.chain_name)
        print('  Time: %.3f seconds' % broadcast_time)
        print('  Success: %d/%d peers (%.1f%%)' % (successes, len(results), 
            (successes * 100.0) / len(results) if results else 0))
        print('  Failed: %d peers' % failures)
        print('  Local node: %s' % (
            'SUCCESS' if local_success else 
            'FAILED' if local_success is False else 
            'NOT FOUND'))
        print('=' * 70)
        print('')
        
        defer.returnValue(successes)
    
    @defer.inlineCallbacks
    def _send_block_to_peer(self, addr, conn, block):
        """Send block to a single peer
        
        Args:
            addr: (host, port) tuple
            conn: Connection dict
            block: Block to send
            
        Returns:
            Deferred that fires with True on success, False on failure
        """
        try:
            factory = conn['factory']
            
            # Check if connected
            if factory.conn.value is None:
                print('Broadcaster[%s]: Peer %s not connected, skipping' % (
                    self.chain_name, _safe_addr_str(addr)))
                defer.returnValue(False)
            
            # Send block via P2P
            factory.conn.value.send_block(block=block)
            
            defer.returnValue(True)
            
        except Exception as e:
            print('Broadcaster[%s]: Error sending block to %s: %s' % (
                self.chain_name, _safe_addr_str(addr), e), file=sys.stderr)
            defer.returnValue(False)
    
    def _get_peer_db_path(self):
        """Get path to peer database file"""
        return os.path.join(self.datadir_path, 'broadcast_peers_%s.json' % self.chain_name)
    
    def _cleanup_invalid_ports(self):
        """Remove peers with invalid/ephemeral ports from database"""
        invalid_addrs = []
        
        for addr in list(self.peer_db.keys()):
            if addr[1] not in self.valid_ports:
                invalid_addrs.append(addr)
        
        if invalid_addrs:
            print('Broadcaster[%s]: Cleaning up %d peers with invalid ports' % (
                self.chain_name, len(invalid_addrs)))
            for addr in invalid_addrs:
                del self.peer_db[addr]
                if addr in self.connection_attempts:
                    del self.connection_attempts[addr]
                if addr in self.connection_failures:
                    del self.connection_failures[addr]
    
    def _load_peer_database(self):
        """Load peer database from disk"""
        db_path = self._get_peer_db_path()
        
        if not os.path.exists(db_path):
            print('Broadcaster[%s]: No cached peer database found' % self.chain_name)
            return
        
        try:
            print('Broadcaster[%s]: Loading peer database from %s' % (self.chain_name, db_path))
            with open(db_path, 'rb') as f:
                data = json.loads(f.read())
            
            # Load peers
            for addr_str, peer_info in data.get('peers', {}).items():
                # Parse address
                if ':' in addr_str:
                    parts = addr_str.rsplit(':', 1)
                    host = parts[0]
                    # Handle Python 2/3 unicode
                    try:
                        if isinstance(host, unicode):
                            host = host.encode('ascii', 'replace')
                    except NameError:
                        pass
                    addr = (host, int(parts[1]))
                else:
                    continue
                
                self.peer_db[addr] = peer_info
                self.peer_db[addr]['addr'] = addr
            
            self.bootstrapped = data.get('bootstrapped', False)
            
            print('Broadcaster[%s]: Loaded %d peers from database' % (
                self.chain_name, len(self.peer_db)))
            
            # Clean up invalid ports
            self._cleanup_invalid_ports()
            
        except Exception as e:
            print('Broadcaster[%s]: Error loading peer database: %s' % (
                self.chain_name, e), file=sys.stderr)
            log.err(e, 'Broadcaster database load error:')
    
    def _save_peer_database(self):
        """Save peer database to disk"""
        if self.stopping:
            return
        
        db_path = self._get_peer_db_path()
        
        try:
            # Convert to JSON-serializable format
            peers_json = {}
            for addr, peer_info in self.peer_db.items():
                addr_str = _safe_addr_str(addr)
                # Create a copy to avoid modifying original
                peer_copy = dict(peer_info)
                # Remove non-serializable addr tuple
                if 'addr' in peer_copy:
                    del peer_copy['addr']
                peers_json[addr_str] = peer_copy
            
            data = {
                'bootstrapped': self.bootstrapped,
                'peers': peers_json,
                'saved_at': time.time()
            }
            
            # Write atomically
            tmp_path = db_path + '.tmp'
            with open(tmp_path, 'wb') as f:
                f.write(json.dumps(data, indent=2))
            
            os.rename(tmp_path, db_path)
            
        except Exception as e:
            print('Broadcaster[%s]: Error saving peer database: %s' % (
                self.chain_name, e), file=sys.stderr)
            log.err(e, 'Broadcaster database save error:')
    
    def handle_ping_message(self, peer_addr):
        """Handle ping message from a peer - track activity
        
        Called from P2P protocol handler when peer sends ping.
        Updates last_seen timestamp for peer scoring.
        """
        if peer_addr in self.peer_db:
            self.peer_db[peer_addr]['last_seen'] = time.time()
            if 'pings_received' not in self.peer_db[peer_addr]:
                self.peer_db[peer_addr]['pings_received'] = 0
            self.peer_db[peer_addr]['pings_received'] += 1
    
    def handle_block_message(self, peer_addr, block_hash):
        """Handle block announcement/relay from a peer
        
        Called when we receive a block from a peer (via inv or direct).
        Tracks block relay for peer quality scoring.
        """
        if peer_addr in self.peer_db:
            self.peer_db[peer_addr]['last_seen'] = time.time()
            if 'blocks_relayed' not in self.peer_db[peer_addr]:
                self.peer_db[peer_addr]['blocks_relayed'] = 0
            self.peer_db[peer_addr]['blocks_relayed'] += 1
            # Boost score for active block relayers
            self.peer_db[peer_addr]['score'] = min(
                self.peer_db[peer_addr]['score'] + 5, 
                999998  # Below protected threshold
            )
    
    def handle_tx_message(self, peer_addr):
        """Handle transaction announcement from a peer
        
        Called when we receive tx inventory from a peer.
        Tracks tx relay activity for peer quality scoring.
        """
        if peer_addr in self.peer_db:
            self.peer_db[peer_addr]['last_seen'] = time.time()
            if 'txs_relayed' not in self.peer_db[peer_addr]:
                self.peer_db[peer_addr]['txs_relayed'] = 0
            self.peer_db[peer_addr]['txs_relayed'] += 1
    
    def _calculate_peer_score(self, peer_info, current_time):
        """Calculate dynamic quality score for a peer
        
        Scoring factors:
        - Base score from initial discovery
        - Success rate bonus (most important for broadcast reliability)
        - Recency bonus/penalty (prefer active peers)
        - Source bonus: P2P peers get priority (daemon handles its own peers)
        - Block relay bonus (peers that relay blocks are well-connected)
        
        Args:
            peer_info: Peer info dict from peer_db
            current_time: Current timestamp
            
        Returns:
            float: Quality score (higher is better)
        """
        score = peer_info.get('score', 50)
        
        # Success rate bonus (most important for broadcast reliability)
        total = peer_info.get('successful_broadcasts', 0) + peer_info.get('failed_broadcasts', 0)
        if total > 0:
            success_rate = peer_info['successful_broadcasts'] / float(total)
            score += success_rate * 100  # Up to +100 for 100% success
        
        # Recency bonus/penalty
        age_hours = (current_time - peer_info.get('last_seen', current_time)) / 3600.0
        if age_hours > 24:
            score -= 50  # Very stale - haven't heard from in a day
        elif age_hours > 6:
            score -= 20  # Somewhat stale
        elif age_hours < 1:
            score += 50  # Very fresh - recently active
        
        # Source bonus: PRIORITIZE P2P discovered peers
        # The coin daemon will broadcast to its own peers, so we want
        # to broadcast to DIFFERENT peers for maximum network coverage
        source = peer_info.get('source', 'unknown')
        if source == 'p2p':
            score += 50  # P2P peers provide unique coverage
        elif source in ('coind', 'coind_refresh'):
            score -= 20  # Daemon already handles these
        
        # Block relay bonus (well-connected peers relay blocks quickly)
        blocks_relayed = peer_info.get('blocks_relayed', 0)
        if blocks_relayed > 10:
            score += 30
        elif blocks_relayed > 5:
            score += 20
        elif blocks_relayed > 0:
            score += 10
        
        return max(0, score)
    
    def get_health_status(self):
        """Get health status for monitoring/alerting
        
        Returns dict with:
        - healthy: bool, True if broadcaster is working properly
        - active_connections: int, number of live connections
        - issues: list of strings describing any problems
        """
        issues = []
        
        active_count = len(self.connections)
        protected_count = len([c for c in self.connections.values() if c.get('protected')])
        
        if active_count < self.min_peers:
            issues.append('Low peer count: %d/%d (minimum: %d)' % (
                active_count, self.max_peers, self.min_peers))
        
        if protected_count == 0:
            issues.append('CRITICAL: Local node connection lost!')
        
        if not self.bootstrapped:
            issues.append('Not yet bootstrapped from local node')
        
        # Check for recent activity
        if self.stats['total_broadcasts'] > 0:
            success_rate = self.stats['successful_broadcasts'] / self.stats['total_broadcasts']
            if success_rate < 0.5:
                issues.append('Low broadcast success rate: %.1f%%' % (success_rate * 100))
        
        return {
            'healthy': len(issues) == 0 or (len(issues) == 1 and 'Low peer count' in issues[0]),
            'active_connections': active_count,
            'protected_connections': protected_count,
            'bootstrapped': self.bootstrapped,
            'issues': issues
        }
    
    def get_network_status(self):
        """Get comprehensive network status for web dashboard
        
        Returns detailed information suitable for display in web UI,
        including peer list, connection quality, and broadcast stats.
        """
        current_time = time.time()
        
        # Build detailed peer list
        peers_list = []
        for addr, info in self.peer_db.items():
            connected = addr in self.connections
            conn_info = self.connections.get(addr, {})
            
            peer_detail = {
                'address': _safe_addr_str(addr),
                'connected': connected,
                'protected': info.get('protected', False),
                'score': info.get('score', 0),
                'source': info.get('source', 'unknown'),
                'first_seen': info.get('first_seen', 0),
                'last_seen': info.get('last_seen', 0),
                'age_seconds': int(current_time - info.get('first_seen', current_time)),
                'successful_broadcasts': info.get('successful_broadcasts', 0),
                'failed_broadcasts': info.get('failed_broadcasts', 0),
                'blocks_relayed': info.get('blocks_relayed', 0),
                'txs_relayed': info.get('txs_relayed', 0),
                'pings_received': info.get('pings_received', 0),
            }
            
            if connected:
                peer_detail['connected_since'] = conn_info.get('connected_at', 0)
                peer_detail['connection_age'] = int(current_time - conn_info.get('connected_at', current_time))
            
            peers_list.append(peer_detail)
        
        # Sort by: protected first, then connected, then by score
        peers_list.sort(key=lambda x: (x['protected'], x['connected'], x['score']), reverse=True)
        
        # Limit to top 20 peers for dashboard display
        peers_list = peers_list[:20]
        
        # Calculate success rate
        if self.stats['total_broadcasts'] > 0:
            success_rate = self.stats['successful_broadcasts'] / self.stats['total_broadcasts'] * 100
        else:
            success_rate = 0
        
        health = self.get_health_status()
        
        return {
            'enabled': True,
            'chain': self.chain_name,
            'health': health,
            'configuration': {
                'max_peers': self.max_peers,
                'min_peers': self.min_peers,
                'valid_ports': self.valid_ports,
            },
            'connections': {
                'total': len(self.connections),
                'protected': len([c for c in self.connections.values() if c.get('protected')]),
                'regular': len([c for c in self.connections.values() if not c.get('protected')]),
            },
            'peer_database': {
                'total_peers': len(self.peer_db),
                'bootstrapped': self.bootstrapped,
            },
            'broadcast_stats': {
                'blocks_sent': self.stats['blocks_sent'],
                'total_broadcasts': self.stats['total_broadcasts'],
                'successful_broadcasts': self.stats['successful_broadcasts'],
                'failed_broadcasts': self.stats['failed_broadcasts'],
                'success_rate_percent': success_rate,
            },
            'connection_stats': self.stats['connection_stats'],
            'peers': peers_list,
        }
    
    def get_stats(self):
        """Get broadcaster statistics for API/monitoring"""
        return {
            'chain': self.chain_name,
            'bootstrapped': self.bootstrapped,
            'total_peers': len(self.peer_db),
            'active_connections': len(self.connections),
            'protected_connections': len([c for c in self.connections.values() if c.get('protected')]),
            'blocks_sent': self.stats['blocks_sent'],
            'total_broadcasts': self.stats['total_broadcasts'],
            'successful_broadcasts': self.stats['successful_broadcasts'],
            'failed_broadcasts': self.stats['failed_broadcasts'],
            'success_rate': (self.stats['successful_broadcasts'] / self.stats['total_broadcasts'] * 100
                           if self.stats['total_broadcasts'] > 0 else 0),
            'connection_stats': self.stats['connection_stats'],
            'top_peers': sorted(
                [{'addr': _safe_addr_str(addr), 'score': info['score'], 
                  'broadcasts': info['successful_broadcasts']}
                 for addr, info in self.peer_db.items() if not info.get('protected')],
                key=lambda x: x['score'], reverse=True
            )[:10]
        }
