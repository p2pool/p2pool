"""
Merged Mining Network Broadcaster - Parallel block broadcasting for merged mining chains

This module handles broadcasting merged mining blocks (e.g., Dogecoin) to multiple
network nodes simultaneously. Unlike parent chain blocks, merged mining blocks 
require auxpow proof and are submitted via RPC, but we ALSO maintain P2P connections
for faster block propagation via inv/block messages.

Key features:
- Bootstrap peers from local merged mining node (dogecoind) via getpeerinfo
- Maintain P2P connections to child chain nodes for fast block propagation
- Discover additional peers via P2P 'addr' messages
- Parallel RPC submission + P2P broadcast when block found
- Persistent peer database
- Quality-based peer scoring
"""

from __future__ import division, print_function

import json
import os
import sys
import time

from twisted.internet import defer, reactor, protocol
from twisted.python import log, failure

from p2pool.bitcoin import data as bitcoin_data, p2p as bitcoin_p2p
from p2pool.util import deferral, variable, jsonrpc


def _with_timeout(df, timeout):
    """Wrap a deferred with a timeout"""
    result_df = defer.Deferred()
    timed_out = [False]
    
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
            try:
                if isinstance(host, unicode):
                    host = host.encode('ascii', 'replace')
            except NameError:
                pass
            # Truncate long IPv6 addresses
            if len(str(host)) > 20:
                host = str(host)[:17] + '...'
            return '%s:%d' % (host, port)
        return str(addr)
    except Exception:
        return repr(addr)


class MergedMiningBroadcaster(object):
    """Manages block broadcasting for merged mining chains (e.g., Dogecoin)
    
    P2P connections for faster block propagation:
    - Connect to our own synced Dogecoin node first (PROTECTED peer)
    - Discover additional peers via P2P 'addr' messages from our node
    - Bootstrap more peers from local node via getpeerinfo
    - When block found: RPC submit + P2P broadcast simultaneously
    
    This broadcaster follows the same pattern as Litecoin broadcaster:
    - Primary P2P connection to our own Dogecoin node
    - P2P announcement to all connected peers for faster propagation
    - RPC submission as backup
    """
    
    def __init__(self, merged_proxy, merged_url, datadir_path, chain_name='dogecoin',
                 additional_rpc_endpoints=None, p2p_net=None, p2p_port=None,
                 local_p2p_addr=None):
        """Initialize merged mining broadcaster
        
        Args:
            merged_proxy: Primary JSON-RPC proxy to merged mining node
            merged_url: URL of primary merged mining node
            datadir_path: Directory to store peer database
            chain_name: Name for logging (e.g., 'dogecoin')
            additional_rpc_endpoints: List of additional RPC proxies for redundancy
            p2p_net: Network object for P2P connections (required for P2P)
            p2p_port: P2P port for the chain (e.g., 22556 for Dogecoin mainnet)
            local_p2p_addr: (host, port) of our own synced Dogecoin node's P2P port
        """
        print('MergedBroadcaster[%s]: Initializing...' % chain_name)
        
        self.merged_proxy = merged_proxy
        self.merged_url = merged_url
        self.datadir_path = datadir_path
        self.chain_name = chain_name
        self.additional_rpc_endpoints = additional_rpc_endpoints or []
        self.p2p_net = p2p_net
        self.p2p_port = p2p_port or 22556  # Default to Dogecoin mainnet
        self.local_p2p_addr = local_p2p_addr  # Our own Dogecoin node's P2P address
        
        # Peer database for P2P discovery
        self.peer_db = {}
        
        # Active P2P connections
        self.connections = {}
        
        # Track coind's peer connections (to avoid duplication)
        self.coind_peers = set()  # Set of (host, port) tuples coind is connected to
        
        # Connection tracking with exponential backoff
        self.connection_attempts = {}  # addr -> attempt count
        self.connection_failures = {}  # addr -> (last_failure_time, backoff_seconds)
        self.pending_connections = set()  # Currently attempting to connect
        self.max_connection_attempts = 5
        self.base_backoff = 30  # Base backoff in seconds
        self.max_backoff = 3600  # Max backoff: 1 hour
        
        # Rate limiting for connection attempts
        self.max_concurrent_connections = 3  # Max pending connection attempts at once
        self.max_connections_per_cycle = 5  # Max new connections to attempt per maintenance cycle
        
        # Discovery control - stop when at capacity with good peers
        self.discovery_enabled = True  # Enable/disable peer discovery (getaddr requests)
        
        # Valid P2P ports for Dogecoin
        # Dogecoin: 22556 (mainnet), 44556 (testnet), 44557 (testnet4alpha)
        self.valid_ports = [22556, 44556, 44557, 18444]
        if self.p2p_port not in self.valid_ports:
            self.valid_ports.append(self.p2p_port)
        
        # Configuration
        self.max_peers = 20  # Target number of P2P connections for reliable block propagation
        self.min_peers = 4   # Minimum before we actively try to connect more
        self.bootstrapped = False
        self.stopping = False
        
        # Statistics
        self.stats = {
            'blocks_submitted': 0,
            'rpc_successes': 0,
            'rpc_failures': 0,
            'p2p_broadcasts': 0,
            'p2p_successes': 0,
            'p2p_failures': 0,
            'peers_discovered': 0,
            'last_block_time': None,
            'last_block_hash': None,
        }
        
        print('MergedBroadcaster[%s]: Configuration:' % chain_name)
        print('  Primary RPC: %s' % merged_url)
        print('  Additional RPC endpoints: %d' % len(self.additional_rpc_endpoints))
        print('  P2P enabled: %s' % ('Yes' if p2p_net else 'No'))
        if p2p_net:
            print('  P2P port: %s' % self.p2p_port)
            print('  Max P2P peers: %d' % self.max_peers)
        print('MergedBroadcaster[%s]: Initialization complete' % chain_name)
    
    @defer.inlineCallbacks
    def start(self):
        """Start the merged mining broadcaster"""
        print('MergedBroadcaster[%s]: Starting...' % self.chain_name)
        
        # Load peer database
        self._load_peer_database()
        
        if self.p2p_net:
            # Bootstrap peers from node
            yield self._bootstrap_peers()
            
            # Start initial peer connections in background (don't block startup)
            # This allows the broadcaster to register immediately while connections establish
            self._connect_to_peers()  # Don't yield - let it run in background
            
            # Start connection maintenance loop
            self.connection_loop = deferral.RobustLoopingCall(self._maintain_connections)
            self.connection_loop.start(30)  # Every 30 seconds
            
            # Start periodic peer refresh from node
            self.refresh_loop = deferral.RobustLoopingCall(self._refresh_peers)
            self.refresh_loop.start(300)  # Every 5 minutes
        
        # Start periodic database save
        self.save_loop = deferral.RobustLoopingCall(self._save_peer_database)
        self.save_loop.start(300)  # Every 5 minutes
        
        print('MergedBroadcaster[%s]: Started' % self.chain_name)
        if self.p2p_net:
            print('MergedBroadcaster[%s]: Active P2P connections: %d (more connecting in background)' % (
                self.chain_name, len(self.connections)))
        defer.returnValue(True)
    
    def stop(self):
        """Stop the broadcaster"""
        print('MergedBroadcaster[%s]: Stopping...' % self.chain_name)
        self.stopping = True
        
        if hasattr(self, 'connection_loop'):
            self.connection_loop.stop()
        if hasattr(self, 'refresh_loop'):
            self.refresh_loop.stop()
        if hasattr(self, 'save_loop'):
            self.save_loop.stop()
        
        self._save_peer_database()
        
        # Disconnect all P2P peers
        for addr in list(self.connections.keys()):
            self._disconnect_peer(addr)
        
        print('MergedBroadcaster[%s]: Stopped' % self.chain_name)
    
    @defer.inlineCallbacks
    def _bootstrap_peers(self):
        """Bootstrap peer list from merged mining node"""
        if not self.p2p_net:
            return
        
        print('=' * 70)
        print('MergedBroadcaster[%s]: BOOTSTRAP PHASE - Connecting to our Dogecoin node' % self.chain_name)
        print('=' * 70)
        
        # CRITICAL: Connect to our own Dogecoin node FIRST as PROTECTED peer
        if self.local_p2p_addr:
            print('MergedBroadcaster[%s]: Connecting to OUR OWN node at %s (PROTECTED)' % (
                self.chain_name, _safe_addr_str(self.local_p2p_addr)))
            
            # Register local node in peer database with maximum priority
            self.peer_db[self.local_p2p_addr] = {
                'addr': self.local_p2p_addr,
                'score': 999999,  # Maximum score - never drop!
                'first_seen': time.time(),
                'last_seen': time.time(),
                'source': 'local_coind',
                'protected': True,  # CRITICAL FLAG - never disconnect
            }
            
            # Connect to our local node
            try:
                yield self._connect_to_peer(self.local_p2p_addr, protected=True)
                print('MergedBroadcaster[%s]: Connected to OUR OWN node - will discover peers via addr messages!' % self.chain_name)
            except Exception as e:
                print('MergedBroadcaster[%s]: WARNING - Failed to connect to our own node: %s' % (
                    self.chain_name, e), file=sys.stderr)
        else:
            print('MergedBroadcaster[%s]: WARNING - No local P2P address configured!' % self.chain_name)
        
        # Get additional peers from node via RPC getpeerinfo
        try:
            print('MergedBroadcaster[%s]: Fetching peers from node via RPC...' % self.chain_name)
            peer_info = yield self.merged_proxy.rpc_getpeerinfo()
            
            added = 0
            for peer in peer_info:
                addr_str = peer.get('addr', '')
                if not addr_str:
                    continue
                
                # Parse address (handle IPv6)
                if addr_str.startswith('['):
                    if ']:' in addr_str:
                        host, port = addr_str.rsplit(':', 1)
                        host = host[1:-1]  # Remove brackets
                        port = int(port)
                    else:
                        continue
                elif ':' in addr_str:
                    # Could be IPv4:port or IPv6 without port
                    parts = addr_str.rsplit(':', 1)
                    if len(parts) == 2:
                        host = parts[0]
                        try:
                            port = int(parts[1])
                        except ValueError:
                            continue
                    else:
                        continue
                else:
                    host = addr_str
                    port = self.p2p_port
                
                addr = (host, port)
                
                # Skip our own local node (already added as protected)
                if addr == self.local_p2p_addr:
                    continue
                
                # Track that coind is connected to this peer
                self.coind_peers.add(addr)
                
                # Filter non-standard ports
                if port not in self.valid_ports:
                    continue
                
                if addr not in self.peer_db:
                    self.peer_db[addr] = {
                        'addr': addr,
                        # coind peers get LOW priority - daemon propagates to these
                        # P2P discovered peers provide unique coverage
                        'score': 30,  # Low score - daemon handles these
                        'first_seen': time.time(),
                        'last_seen': time.time(),
                        'source': 'coind',  # From daemon's peers
                        'successful_broadcasts': 0,
                        'failed_broadcasts': 0,
                        'blocks_relayed': 0,
                    }
                    added += 1
                else:
                    # Update existing peer
                    self.peer_db[addr]['last_seen'] = time.time()
            
            self.bootstrapped = True
            print('MergedBroadcaster[%s]: Bootstrapped %d additional peers (total: %d)' % (
                self.chain_name, added, len(self.peer_db)))
            
        except Exception as e:
            print('MergedBroadcaster[%s]: Bootstrap error: %s' % (self.chain_name, e), file=sys.stderr)
    
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
    
    def _connect_to_peers(self):
        """Connect to peers from the database with rate limiting and exponential backoff
        
        This method is designed to not saturate the event loop:
        - Limits concurrent pending connections
        - Uses exponential backoff for failed peers
        - Only attempts a few connections per cycle
        - Stops discovery when at max_peers capacity
        """
        if not self.p2p_net or self.stopping:
            return
        
        current_time = time.time()
        current_connections = len(self.connections)
        
        # Check if we're at capacity - disable discovery if so
        if current_connections >= self.max_peers:
            if self.discovery_enabled:
                print('MergedBroadcaster[%s]: At capacity (%d peers) - disabling discovery' % (
                    self.chain_name, current_connections))
                self.discovery_enabled = False
            return  # Nothing to do - we're at capacity
        
        # Re-enable discovery if we dropped below capacity
        if not self.discovery_enabled and current_connections < self.max_peers:
            print('MergedBroadcaster[%s]: Below capacity (%d/%d) - enabling discovery' % (
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
        
        # Use dynamic scoring to select peers
        # Exclude: protected, already connected, pending, in backoff, and coind peers
        scored_peers = []
        
        for addr, peer_info in self.peer_db.items():
            host, port = addr
            # Skip protected peers (local coind)
            if peer_info.get('protected'):
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
            score = self._calculate_peer_score(peer_info, current_time)
            scored_peers.append((score, addr, peer_info))
        
        # Sort by score (highest first)
        scored_peers.sort(reverse=True)
        
        # Attempt connections to top peers (non-blocking)
        attempts_started = 0
        for score, addr, peer_info in scored_peers[:available_slots]:
            # Mark as pending before starting
            self.pending_connections.add(addr)
            
            # Start connection attempt (don't yield - let it run in background)
            d = self._connect_to_peer(addr)
            d.addErrback(lambda f, a=addr: self._handle_connection_error(a, f))
            
            attempts_started += 1
            if attempts_started >= available_slots:
                break
    
    def _handle_connection_error(self, addr, failure):
        """Handle connection failure - record backoff"""
        self._record_connection_failure(addr)
    
    @defer.inlineCallbacks
    def _connect_to_peer(self, addr, protected=False):
        """Connect to a single peer
        
        Args:
            addr: (host, port) tuple
            protected: If True, this is our own node - never disconnect!
        """
        host, port = addr
        
        if protected:
            print('MergedBroadcaster[%s]: Connecting to PROTECTED peer %s...' % (
                self.chain_name, _safe_addr_str(addr)))
        else:
            print('MergedBroadcaster[%s]: Connecting to %s...' % (
                self.chain_name, _safe_addr_str(addr)))
        
        factory = bitcoin_p2p.ClientFactory(self.p2p_net)
        connector = reactor.connectTCP(host, port, factory, timeout=10)
        
        try:
            # Wait for handshake with timeout
            protocol = yield _with_timeout(factory.getProtocol(), 15)
            
            self.connections[addr] = {
                'factory': factory,
                'connector': connector,
                'protocol': protocol,
                'connected_at': time.time(),
                'protected': protected,  # Mark protected peers
            }
            
            # Record successful connection (resets backoff)
            self._record_connection_success(addr)
            
            # Remove from pending connections
            self.pending_connections.discard(addr)
            
            # Update peer database score
            if addr in self.peer_db:
                self.peer_db[addr]['last_seen'] = time.time()
                if not protected:
                    self.peer_db[addr]['score'] = min(200, self.peer_db[addr].get('score', 50) + 10)
            
            if protected:
                print('MergedBroadcaster[%s]: Connected to PROTECTED peer %s' % (
                    self.chain_name, _safe_addr_str(addr)))
            else:
                print('MergedBroadcaster[%s]: Connected to %s' % (
                    self.chain_name, _safe_addr_str(addr)))
            
            # Hook P2P messages for discovery
            self._hook_protocol_messages(addr, protocol)
            
            # Request peer addresses from this peer (only if discovery is enabled)
            if self.discovery_enabled:
                try:
                    if hasattr(protocol, 'send_getaddr') and callable(protocol.send_getaddr):
                        protocol.send_getaddr()
                        print('MergedBroadcaster[%s]:   -> Sent getaddr request to %s' % (
                            self.chain_name, _safe_addr_str(addr)))
                except Exception as e:
                    print('MergedBroadcaster[%s]: Error sending getaddr: %s' % (
                        self.chain_name, e), file=sys.stderr)
            
            defer.returnValue(True)
            
        except Exception as e:
            print('MergedBroadcaster[%s]: Failed to connect to %s: %s' % (
                self.chain_name, _safe_addr_str(addr), e), file=sys.stderr)
            
            try:
                connector.disconnect()
            except:
                pass
            
            raise
    
    def _hook_protocol_messages(self, addr, protocol):
        """Hook P2P message handlers for peer discovery"""
        # Hook addr message handler for P2P discovery
        original_handle_addr = getattr(protocol, 'handle_addr', None)
        if original_handle_addr:
            broadcaster = self  # Capture reference for closure
            
            def handle_addr_wrapper(addrs):
                # Process addresses for peer discovery
                for addr_data in addrs:
                    try:
                        host = addr_data['address'].get('address', '')
                        port = addr_data['address'].get('port', broadcaster.p2p_port)
                        
                        if not host or port not in broadcaster.valid_ports:
                            continue
                        
                        peer_addr = (host, port)
                        if peer_addr not in broadcaster.peer_db:
                            broadcaster.peer_db[peer_addr] = {
                                'addr': peer_addr,
                                # P2P peers get HIGH priority - unique coverage
                                # that daemon won't reach
                                'score': 150,  # Higher than coind peers
                                'first_seen': time.time(),
                                'last_seen': time.time(),
                                'source': 'p2p',
                                'successful_broadcasts': 0,
                                'failed_broadcasts': 0,
                                'blocks_relayed': 0,
                            }
                            broadcaster.stats['peers_discovered'] += 1
                    except Exception:
                        pass
                
                return original_handle_addr(addrs)
            
            protocol.handle_addr = handle_addr_wrapper
        
        # Hook inv message handler to track block relay
        original_handle_inv = getattr(protocol, 'handle_inv', None)
        if original_handle_inv:
            broadcaster = self
            
            def handle_inv_wrapper(invs):
                for inv in invs:
                    inv_type = inv.get('type')
                    if inv_type == 'block':
                        # Track block relay for peer scoring
                        if addr in broadcaster.peer_db:
                            broadcaster.peer_db[addr]['last_seen'] = time.time()
                            broadcaster.peer_db[addr]['blocks_relayed'] = \
                                broadcaster.peer_db[addr].get('blocks_relayed', 0) + 1
                            # Small score bonus for block relayers
                            broadcaster.peer_db[addr]['score'] = min(
                                broadcaster.peer_db[addr].get('score', 50) + 5,
                                999998  # Below protected threshold
                            )
                return original_handle_inv(invs)
            
            protocol.handle_inv = handle_inv_wrapper
    
    def _disconnect_peer(self, addr):
        """Disconnect from a peer (NEVER disconnect protected peers!)"""
        if addr not in self.connections:
            return
        
        conn = self.connections[addr]
        
        # CRITICAL: Never disconnect protected peers (our own node)!
        if conn.get('protected'):
            print('MergedBroadcaster[%s]: REFUSED to disconnect PROTECTED peer %s' % (
                self.chain_name, _safe_addr_str(addr)), file=sys.stderr)
            return
        
        try:
            if conn.get('connector'):
                conn['connector'].disconnect()
        except Exception as e:
            print('MergedBroadcaster[%s]: Error disconnecting %s: %s' % (
                self.chain_name, _safe_addr_str(addr), e), file=sys.stderr)
        
        if addr in self.connections:
            del self.connections[addr]
    
    def _calculate_peer_score(self, peer_info, current_time):
        """Calculate dynamic quality score for a peer
        
        Scoring factors:
        - Base score from initial discovery
        - Success rate bonus (for broadcast reliability)
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
        
        # Success rate bonus
        total = peer_info.get('successful_broadcasts', 0) + peer_info.get('failed_broadcasts', 0)
        if total > 0:
            success_rate = peer_info['successful_broadcasts'] / float(total)
            score += success_rate * 100  # Up to +100 for 100% success
        
        # Recency bonus/penalty
        age_hours = (current_time - peer_info.get('last_seen', current_time)) / 3600.0
        if age_hours > 24:
            score -= 50  # Very stale
        elif age_hours > 6:
            score -= 20  # Somewhat stale
        elif age_hours < 1:
            score += 50  # Very fresh
        
        # Source bonus: PRIORITIZE P2P discovered peers
        source = peer_info.get('source', 'unknown')
        if source == 'p2p':
            score += 50  # P2P peers provide unique coverage
        elif source in ('coind', 'refresh'):
            score -= 20  # Daemon already handles these
        
        # Block relay bonus
        blocks_relayed = peer_info.get('blocks_relayed', 0)
        if blocks_relayed > 10:
            score += 30
        elif blocks_relayed > 5:
            score += 20
        elif blocks_relayed > 0:
            score += 10
        
        return max(0, score)
    
    @defer.inlineCallbacks
    def _maintain_connections(self):
        """Maintain minimum number of P2P connections"""
        if self.stopping or not self.p2p_net:
            return
        
        current_time = time.time()
        
        # Update last_seen for protected local node (it's always "active")
        if self.local_p2p_addr and self.local_p2p_addr in self.peer_db:
            self.peer_db[self.local_p2p_addr]['last_seen'] = current_time
        
        # Clean up dead connections (but NEVER remove protected peers from db!)
        for addr in list(self.connections.keys()):
            conn = self.connections[addr]
            protocol = conn.get('protocol')
            is_protected = conn.get('protected', False)
            
            if protocol and hasattr(protocol, 'transport'):
                if not protocol.transport or not protocol.transport.connected:
                    if is_protected:
                        print('MergedBroadcaster[%s]: Lost connection to PROTECTED peer %s - will reconnect!' % (
                            self.chain_name, _safe_addr_str(addr)))
                    else:
                        print('MergedBroadcaster[%s]: Lost connection to %s' % (
                            self.chain_name, _safe_addr_str(addr)))
                    del self.connections[addr]
        
        # CRITICAL: Reconnect to our own node if disconnected
        if self.local_p2p_addr and self.local_p2p_addr not in self.connections:
            print('MergedBroadcaster[%s]: Reconnecting to our own node at %s...' % (
                self.chain_name, _safe_addr_str(self.local_p2p_addr)))
            try:
                yield self._connect_to_peer(self.local_p2p_addr, protected=True)
            except Exception as e:
                print('MergedBroadcaster[%s]: Failed to reconnect to our own node: %s' % (
                    self.chain_name, e), file=sys.stderr)
        
        # Connect more peers if needed
        if len(self.connections) < self.min_peers:
            yield self._connect_to_peers()
    
    @defer.inlineCallbacks
    def _refresh_peers(self):
        """Periodic peer refresh - update coind_peers tracking and add new peers"""
        if self.stopping or not self.p2p_net:
            return
        
        try:
            peer_info = yield self.merged_proxy.rpc_getpeerinfo()
            
            # Clear and rebuild coind_peers set
            self.coind_peers.clear()
            
            for peer in peer_info:
                addr_str = peer.get('addr', '')
                if not addr_str or ':' not in addr_str:
                    continue
                
                host, port = addr_str.rsplit(':', 1)
                try:
                    port = int(port)
                except ValueError:
                    continue
                
                addr = (host, port)
                
                # Track that coind is connected to this peer
                self.coind_peers.add(addr)
                
                if port not in self.valid_ports:
                    continue
                
                if addr in self.peer_db:
                    self.peer_db[addr]['last_seen'] = time.time()
                else:
                    self.peer_db[addr] = {
                        'addr': addr,
                        # Refresh peers from coind get LOW priority
                        # daemon handles these already
                        'score': 30,  # Low score - daemon propagates to these
                        'first_seen': time.time(),
                        'last_seen': time.time(),
                        'source': 'refresh',
                        'successful_broadcasts': 0,
                        'failed_broadcasts': 0,
                        'blocks_relayed': 0,
                    }
        except Exception as e:
            print('MergedBroadcaster[%s]: Refresh error: %s' % (self.chain_name, e), file=sys.stderr)
    
    @defer.inlineCallbacks
    def broadcast_block(self, block_hex, block_hash, auxpow_info=None):
        """Submit merged mining block via RPC + P2P broadcast in parallel
        
        Args:
            block_hex: Hex-encoded block data for RPC submission
            block_hash: Block hash (for logging and P2P inv)
            auxpow_info: Optional dict with auxpow details for logging
            
        Returns:
            Deferred that fires with (rpc_success, p2p_announcements)
        """
        print('')
        print('=' * 70)
        print('MergedBroadcaster[%s]: BLOCK BROADCAST INITIATED' % self.chain_name)
        print('=' * 70)
        
        # Convert hash to int if string
        if isinstance(block_hash, str):
            hash_int = int(block_hash, 16)
            hash_str = block_hash
        else:
            hash_int = block_hash
            hash_str = '%064x' % block_hash
        
        print('  Block hash: %s' % hash_str)
        print('  Block size: %d bytes' % (len(block_hex) // 2))
        print('  Active P2P connections: %d' % len(self.connections))
        
        start_time = time.time()
        
        # Phase 1: Submit via RPC to all endpoints in parallel
        rpc_deferreds = []
        
        # Primary endpoint
        rpc_deferreds.append(self._submit_via_rpc(self.merged_proxy, block_hex, 'primary'))
        
        # Additional endpoints
        for i, proxy in enumerate(self.additional_rpc_endpoints):
            rpc_deferreds.append(self._submit_via_rpc(proxy, block_hex, 'additional_%d' % i))
        
        print('MergedBroadcaster[%s]: Phase 1 - Submitting to %d RPC endpoint(s)...' % (
            self.chain_name, len(rpc_deferreds)))
        
        # Phase 2: Broadcast via P2P simultaneously (non-blocking)
        p2p_successes = 0
        p2p_failures = 0
        
        if self.p2p_net and self.connections:
            print('MergedBroadcaster[%s]: Phase 2 - Broadcasting to %d P2P peers...' % (
                self.chain_name, len(self.connections)))
            
            for addr, conn in list(self.connections.items()):
                try:
                    protocol = conn.get('protocol')
                    if protocol and hasattr(protocol, 'send_inv'):
                        # Send inv message with block hash
                        protocol.send_inv(invs=[dict(type='block', hash=hash_int)])
                        p2p_successes += 1
                        self.stats['p2p_successes'] += 1
                except Exception as e:
                    p2p_failures += 1
                    self.stats['p2p_failures'] += 1
                    print('MergedBroadcaster[%s]: P2P broadcast to %s failed: %s' % (
                        self.chain_name, _safe_addr_str(addr), e), file=sys.stderr)
            
            self.stats['p2p_broadcasts'] += 1
        
        # Wait for all RPC submissions
        rpc_results = yield defer.DeferredList(rpc_deferreds, consumeErrors=True)
        
        rpc_time = time.time() - start_time
        
        # Count RPC results
        rpc_successes = sum(1 for success, result in rpc_results if success and result)
        rpc_failures = len(rpc_results) - rpc_successes
        
        # Update stats
        self.stats['blocks_submitted'] += 1
        self.stats['rpc_successes'] += rpc_successes
        self.stats['rpc_failures'] += rpc_failures
        self.stats['last_block_time'] = time.time()
        self.stats['last_block_hash'] = hash_str
        
        # Log results
        primary_success = rpc_results[0][0] and rpc_results[0][1] if rpc_results else False
        
        print('')
        print('MergedBroadcaster[%s]: BROADCAST COMPLETE' % self.chain_name)
        print('  Time: %.3f seconds' % rpc_time)
        print('  RPC: %d/%d succeeded (%s primary)' % (
            rpc_successes, len(rpc_results), 'OK' if primary_success else 'FAILED'))
        print('  P2P: %d/%d peers reached' % (p2p_successes, p2p_successes + p2p_failures))
        print('=' * 70)
        print('')
        
        defer.returnValue((rpc_successes > 0, p2p_successes))
    
    @defer.inlineCallbacks
    def _submit_via_rpc(self, proxy, block_hex, endpoint_name):
        """Submit block via RPC to a single endpoint
        
        Args:
            proxy: JSON-RPC proxy
            block_hex: Hex-encoded block
            endpoint_name: Name for logging
            
        Returns:
            Deferred that fires with True on success, False on failure
        """
        try:
            result = yield proxy.rpc_submitblock(block_hex)
            
            # submitblock returns None on success, error string on failure
            if result is None:
                print('MergedBroadcaster[%s]: %s - SUCCESS' % (self.chain_name, endpoint_name))
                defer.returnValue(True)
            else:
                print('MergedBroadcaster[%s]: %s - REJECTED: %s' % (
                    self.chain_name, endpoint_name, result), file=sys.stderr)
                defer.returnValue(False)
                
        except Exception as e:
            print('MergedBroadcaster[%s]: %s - ERROR: %s' % (
                self.chain_name, endpoint_name, e), file=sys.stderr)
            defer.returnValue(False)
    
    def _get_peer_db_path(self):
        """Get path to peer database file"""
        if not self.datadir_path:
            return None
        return os.path.join(self.datadir_path, 'merged_broadcast_peers_%s.json' % self.chain_name)
    
    def _load_peer_database(self):
        """Load peer database from disk"""
        db_path = self._get_peer_db_path()
        if not db_path:
            return
        
        if not os.path.exists(db_path):
            return
        
        try:
            with open(db_path, 'rb') as f:
                data = json.loads(f.read())
            
            for addr_str, peer_info in data.get('peers', {}).items():
                if ':' in addr_str:
                    parts = addr_str.rsplit(':', 1)
                    addr = (parts[0], int(parts[1]))
                    self.peer_db[addr] = peer_info
                    self.peer_db[addr]['addr'] = addr
            
            self.bootstrapped = data.get('bootstrapped', False)
            print('MergedBroadcaster[%s]: Loaded %d peers' % (self.chain_name, len(self.peer_db)))
            
        except Exception as e:
            print('MergedBroadcaster[%s]: Load error: %s' % (self.chain_name, e), file=sys.stderr)
    
    def _save_peer_database(self):
        """Save peer database to disk"""
        db_path = self._get_peer_db_path()
        if self.stopping or not db_path:
            return
        
        try:
            peers_json = {}
            for addr, info in self.peer_db.items():
                addr_str = _safe_addr_str(addr)
                peer_copy = dict(info)
                if 'addr' in peer_copy:
                    del peer_copy['addr']
                peers_json[addr_str] = peer_copy
            
            data = {
                'bootstrapped': self.bootstrapped,
                'peers': peers_json,
                'saved_at': time.time()
            }
            
            tmp_path = db_path + '.tmp'
            with open(tmp_path, 'wb') as f:
                f.write(json.dumps(data, indent=2))
            os.rename(tmp_path, db_path)
            
        except Exception as e:
            print('MergedBroadcaster[%s]: Save error: %s' % (self.chain_name, e), file=sys.stderr)
    
    def get_health_status(self):
        """Get health status for dashboard"""
        issues = []
        
        if not self.bootstrapped:
            issues.append('Not yet bootstrapped')
        if len(self.connections) == 0:
            issues.append('No active P2P connections')
        
        healthy = len(issues) == 0 and len(self.connections) >= 1
        
        return {
            'healthy': healthy,
            'active_connections': len(self.connections),
            'protected_connections': len([c for c in self.connections.values() if c.get('protected')]),
            'bootstrapped': self.bootstrapped,
            'issues': issues,
        }
    
    def get_network_status(self):
        """Get comprehensive network status for web dashboard
        
        Returns detailed information suitable for display in web UI,
        including peer list, connection quality, and broadcast stats.
        Same format as Litecoin broadcaster for dashboard compatibility.
        """
        current_time = time.time()
        
        # Build detailed peer list - prioritize connected peers
        peers_list = []
        
        # First add all connected peers
        for addr, conn in self.connections.items():
            peer_info = self.peer_db.get(addr, {})
            peer_detail = {
                'address': _safe_addr_str(addr),
                'connected': True,
                'protected': conn.get('protected', False),
                'score': peer_info.get('score', 0),
                'source': peer_info.get('source', 'unknown'),
                'first_seen': peer_info.get('first_seen', 0),
                'last_seen': peer_info.get('last_seen', 0),
                'age_seconds': int(current_time - peer_info.get('first_seen', current_time)),
                'successful_broadcasts': peer_info.get('successful_broadcasts', 0),
                'failed_broadcasts': peer_info.get('failed_broadcasts', 0),
                'blocks_relayed': 0,  # Not tracked for merged mining
                'txs_relayed': 0,  # Not tracked for merged mining
                'pings_received': 0,
                'connected_since': conn.get('connected_at', 0),
                'connection_age': int(current_time - conn.get('connected_at', current_time)),
            }
            peers_list.append(peer_detail)
        
        # Then add top non-connected peers from database (limited to 20 total)
        if len(peers_list) < 20:
            non_connected = [(addr, info) for addr, info in self.peer_db.items() 
                            if addr not in self.connections]
            non_connected.sort(key=lambda x: x[1].get('score', 0), reverse=True)
            
            for addr, info in non_connected[:20 - len(peers_list)]:
                peer_detail = {
                    'address': _safe_addr_str(addr),
                    'connected': False,
                    'protected': info.get('protected', False),
                    'score': info.get('score', 0),
                    'source': info.get('source', 'unknown'),
                    'first_seen': info.get('first_seen', 0),
                    'last_seen': info.get('last_seen', 0),
                    'age_seconds': int(current_time - info.get('first_seen', current_time)),
                    'successful_broadcasts': info.get('successful_broadcasts', 0),
                    'failed_broadcasts': info.get('failed_broadcasts', 0),
                    'blocks_relayed': 0,
                    'txs_relayed': 0,
                    'pings_received': 0,
                }
                peers_list.append(peer_detail)
        
        # Sort by: protected first, then connected, then by score
        peers_list.sort(key=lambda x: (x['protected'], x['connected'], x['score']), reverse=True)
        
        # Calculate success rate
        total_broadcasts = self.stats['rpc_successes'] + self.stats['rpc_failures']
        if total_broadcasts > 0:
            success_rate = self.stats['rpc_successes'] / total_broadcasts * 100
        else:
            success_rate = 0
        
        health = self.get_health_status()
        
        return {
            'enabled': True,
            'chain': self.chain_name,
            'chain_name': self.chain_name.capitalize(),  # For dashboard display
            'health': health,
            'configuration': {
                'max_peers': self.max_peers,
                'min_peers': 1,
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
                'blocks_sent': self.stats['blocks_submitted'],
                'total_broadcasts': total_broadcasts,
                'successful_broadcasts': self.stats['rpc_successes'],
                'failed_broadcasts': self.stats['rpc_failures'],
                'success_rate_percent': success_rate,
                'p2p_broadcasts': self.stats['p2p_broadcasts'],
                'p2p_successes': self.stats['p2p_successes'],
                'p2p_failures': self.stats['p2p_failures'],
            },
            'connection_stats': {
                'peers_discovered': self.stats['peers_discovered'],
            },
            'peers': peers_list,
        }
    
    def get_stats(self):
        """Get broadcaster statistics"""
        return {
            'chain': self.chain_name,
            'chain_name': self.chain_name.capitalize(),  # For dashboard display
            'bootstrapped': self.bootstrapped,
            'total_peers': len(self.peer_db),
            'active_connections': len(self.connections),  # Now tracking actual P2P connections
            'rpc_endpoints': 1 + len(self.additional_rpc_endpoints),
            'blocks_submitted': self.stats['blocks_submitted'],
            'blocks_broadcast': self.stats['blocks_submitted'],  # Alias for dashboard
            'rpc_successes': self.stats['rpc_successes'],
            'rpc_failures': self.stats['rpc_failures'],
            'successful_broadcasts': self.stats['rpc_successes'],  # Alias for dashboard
            'failed_broadcasts': self.stats['rpc_failures'],  # Alias for dashboard
            'p2p_broadcasts': self.stats['p2p_broadcasts'],
            'p2p_successes': self.stats['p2p_successes'],
            'p2p_failures': self.stats['p2p_failures'],
            'peers_discovered': self.stats['peers_discovered'],
            'success_rate': (self.stats['rpc_successes'] / 
                           (self.stats['rpc_successes'] + self.stats['rpc_failures']) * 100
                           if (self.stats['rpc_successes'] + self.stats['rpc_failures']) > 0 else 0),
            'last_block_time': self.stats['last_block_time'],
            'last_block_hash': self.stats['last_block_hash'],
        }
    
    def get_peer_details(self):
        """Get detailed peer information for dashboard"""
        peers = []
        for addr, conn in self.connections.items():
            connected_at = conn.get('connected_at', 0)
            uptime = time.time() - connected_at if connected_at else 0
            
            peer_info = self.peer_db.get(addr, {})
            peers.append({
                'address': _safe_addr_str(addr),
                'source': peer_info.get('source', 'unknown'),
                'score': peer_info.get('score', 0),
                'connected': True,
                'uptime': int(uptime),
            })
        
        return peers
