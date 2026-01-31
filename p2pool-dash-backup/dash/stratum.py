import random
import sys
import time
import weakref

from twisted.internet import protocol, reactor
from twisted.python import log

import p2pool
from p2pool.dash import data as dash_data, getwork
from p2pool.util import expiring_dict, jsonrpc, pack
from p2pool.util import security_config


def clip(num, bot, top):
    return min(top, max(bot, num))


# ==============================================================================
# GLOBAL POOL STATISTICS AND CONNECTION MANAGEMENT
# ==============================================================================

class PoolStatistics(object):
    """
    Global pool statistics tracker for performance monitoring and load management.
    
    This class tracks:
    - Total connected workers
    - Per-worker hash rates and share counts
    - Global share submission rate (for load protection)
    - Connection history for session resumption
    
    PERFORMANCE SAFEGUARDS:
    - Enforces minimum difficulty floor to prevent server overload
    - Tracks global submission rate to detect/prevent DoS
    - Limits total concurrent connections
    """
    
    # Class-level singleton instance
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = PoolStatistics()
        return cls._instance
    
    def __init__(self):
        # Connection tracking (weak refs to auto-cleanup disconnected workers)
        self.connections = weakref.WeakValueDictionary()
        self.connection_count = 0
        
        # Per-worker statistics {worker_name: {shares, hash_rate, last_seen, ...}}
        self.worker_stats = {}
        
        # Global submission rate tracking (for DoS protection)
        self.global_submissions = []  # List of (timestamp, difficulty) tuples
        self.global_submission_window = 60  # Track last 60 seconds
        
        # Session storage for resumption {session_id: session_data}
        self.sessions = expiring_dict.ExpiringDict(3600)  # 1 hour session timeout
        
        # Pool-wide configuration limits (can be overridden by security_config)
        self.MAX_CONNECTIONS = 10000  # Maximum concurrent connections
        self.MIN_DIFFICULTY_FLOOR = 0.001  # Absolute minimum difficulty (pool protection)
        self.MAX_DIFFICULTY_CEILING = 1000000  # Maximum difficulty (miner protection - prevents never finding shares)
        self.MAX_SUBMISSIONS_PER_SECOND = 1000  # Global rate limit
        
        # Load settings from security_config (with fallback defaults)
        sec_config = security_config.security_config
        self.MAX_CONNECTIONS_PER_IP = sec_config.get('max_connections_per_ip', 50)
        self.BAN_DURATION = sec_config.get('ban_duration_seconds', 3600)
        self.MAX_VIOLATIONS_BEFORE_BAN = sec_config.get('max_violations_before_ban', 10)
        
        # Banning system for misbehaving miners
        self.banned_ips = {}  # {ip: ban_expire_time}
        self.banned_workers = {}  # {worker_name: ban_expire_time}
        self.ip_violations = {}  # {ip: violation_count}
        
        # Per-IP connection tracking
        self.ip_connections = {}  # {ip: count}
        
        # Performance metrics
        self.total_shares_accepted = 0
        self.total_shares_rejected = 0
        self.startup_time = time.time()
        
        # Threat detection thresholds (set by network config via StratumServerFactory)
        self.connection_worker_elevated = 4.0  # Default: >4 connections per worker = elevated
        self.connection_worker_warning = 6.0   # Default: >6 connections per worker = warning
    
    def register_connection(self, conn_id, connection, ip=None):
        """Register a new stratum connection"""
        self.connections[conn_id] = connection
        self.connection_count = len(self.connections)
        
        # Track per-IP connections
        if ip:
            self.ip_connections[ip] = self.ip_connections.get(ip, 0) + 1
        
        return self.connection_count < self.MAX_CONNECTIONS
    
    def unregister_connection(self, conn_id, ip=None):
        """Unregister a stratum connection"""
        if conn_id in self.connections:
            del self.connections[conn_id]
        self.connection_count = len(self.connections)
        
        # Update per-IP count
        if ip and ip in self.ip_connections:
            self.ip_connections[ip] = max(0, self.ip_connections[ip] - 1)
            if self.ip_connections[ip] == 0:
                del self.ip_connections[ip]
    
    def is_ip_banned(self, ip):
        """Check if an IP is banned"""
        if ip in self.banned_ips:
            if time.time() < self.banned_ips[ip]:
                return True
            else:
                del self.banned_ips[ip]  # Ban expired
        return False
    
    def is_worker_banned(self, worker_name):
        """Check if a worker is banned"""
        if worker_name in self.banned_workers:
            if time.time() < self.banned_workers[worker_name]:
                return True
            else:
                del self.banned_workers[worker_name]  # Ban expired
        return False
    
    def record_violation(self, ip, reason):
        """Record a violation for an IP, ban if threshold exceeded"""
        now = time.time()
        if ip not in self.ip_violations:
            self.ip_violations[ip] = 0
        
        # Increment violation count
        self.ip_violations[ip] += 1
        
        # Check if should ban
        if self.ip_violations[ip] >= self.MAX_VIOLATIONS_BEFORE_BAN:
            self.ban_ip(ip, reason)
            return True
        return False
    
    def ban_ip(self, ip, reason):
        """Ban an IP address"""
        # Check whitelist
        sec_config = security_config.security_config
        if sec_config.is_ip_whitelisted(ip):
            print 'IP %s is whitelisted, not banning' % ip
            return
        if ip == '127.0.0.1' or ip == '::1':
            return  # Never ban localhost
        self.banned_ips[ip] = time.time() + self.BAN_DURATION
        print 'BANNED IP %s for %d seconds. Reason: %s' % (ip, self.BAN_DURATION, reason)
    
    def ban_worker(self, worker_name, reason):
        """Ban a worker name"""
        # Check whitelist
        sec_config = security_config.security_config
        if sec_config.is_worker_whitelisted(worker_name):
            print 'Worker %s is whitelisted, not banning' % worker_name
            return
        self.banned_workers[worker_name] = time.time() + self.BAN_DURATION
        print 'BANNED WORKER %s for %d seconds. Reason: %s' % (worker_name, self.BAN_DURATION, reason)
    
    def check_ip_connection_limit(self, ip):
        """Check if IP has exceeded connection limit"""
        current = self.ip_connections.get(ip, 0)
        return current < self.MAX_CONNECTIONS_PER_IP
    
    def get_worker_connections(self, worker_name):
        """Get all active connections for a worker name (Option A: Aggregate Worker Stats)"""
        connections = []
        for conn_id, conn in self.connections.items():
            if hasattr(conn, 'username') and conn.username == worker_name:
                connections.append(conn)
        return connections
    
    def update_worker_last_share_time(self, worker_name, share_time=None):
        """Update last_share_time for ALL connections of a worker (Option C: Session Linkage)
        
        When one connection submits a share, all connections for that worker
        get their timeout timer reset. This prevents timeout vardiff adjustments
        on backup/redundant connections.
        """
        if share_time is None:
            share_time = time.time()
        
        for conn_id, conn in self.connections.items():
            if hasattr(conn, 'username') and conn.username == worker_name:
                conn.last_share_time = share_time
    
    def get_worker_aggregate_stats(self, worker_name):
        """Get aggregated stats across all connections for a worker (Option A)"""
        connections = self.get_worker_connections(worker_name)
        if not connections:
            return None
        
        aggregate = {
            'connection_count': len(connections),
            'total_shares_submitted': 0,
            'total_shares_accepted': 0,
            'total_shares_rejected': 0,
            'difficulties': [],
            'active_connections': 0,  # Connections that have submitted shares
            'backup_connections': 0,  # Connections with no shares (backup/redundant)
        }
        
        for conn in connections:
            aggregate['total_shares_submitted'] += conn.shares_submitted
            aggregate['total_shares_accepted'] += conn.shares_accepted
            aggregate['total_shares_rejected'] += conn.shares_rejected
            if conn.shares_submitted > 0:
                aggregate['active_connections'] += 1
            else:
                aggregate['backup_connections'] += 1
            if hasattr(conn, 'target') and conn.target:
                from p2pool.dash import data as dash_data
                aggregate['difficulties'].append(dash_data.target_to_difficulty(conn.target))
        
        return aggregate
    
    def get_ban_stats(self):
        """Get current ban statistics with detailed info for UI"""
        now = time.time()
        # Clean expired bans
        self.banned_ips = {k: v for k, v in self.banned_ips.items() if v > now}
        self.banned_workers = {k: v for k, v in self.banned_workers.items() if v > now}
        
        # Build detailed banned IPs list
        banned_ips_list = []
        for ip, expires_at in self.banned_ips.items():
            banned_at = expires_at - self.BAN_DURATION
            banned_ips_list.append({
                'ip': ip,
                'banned_at': banned_at,
                'expires_at': expires_at,
                'remaining_seconds': int(expires_at - now),
                'reason': 'Too many violations or connections'
            })
        
        # Build detailed banned workers list
        banned_workers_list = []
        for worker, expires_at in self.banned_workers.items():
            banned_at = expires_at - self.BAN_DURATION
            banned_workers_list.append({
                'worker': worker,
                'banned_at': banned_at,
                'expires_at': expires_at,
                'remaining_seconds': int(expires_at - now),
                'reason': 'Excessive share submission rate'
            })
        
        # Build violations list
        violations_list = []
        for ip, count in self.ip_violations.items():
            if count > 0:
                violations_list.append({
                    'ip': ip,
                    'violations': count
                })
        violations_list.sort(key=lambda x: x['violations'], reverse=True)
        
        return {
            'banned_ips_count': len(self.banned_ips),
            'banned_workers_count': len(self.banned_workers),
            'banned_ips': banned_ips_list,
            'banned_workers': banned_workers_list,
            'ip_violations': violations_list[:20],  # Top 20 violators
            'ip_connections': dict(self.ip_connections),
            'ban_duration': self.BAN_DURATION,
            'max_violations': self.MAX_VIOLATIONS_BEFORE_BAN,
        }

    def record_share(self, worker_name, difficulty, accepted=True):
        """Record a share submission for statistics"""
        now = time.time()
        
        # Update global submission tracking
        self.global_submissions.append((now, difficulty))
        # Prune old entries
        cutoff = now - self.global_submission_window
        self.global_submissions = [(t, d) for t, d in self.global_submissions if t > cutoff]
        
        # Update worker stats
        if worker_name not in self.worker_stats:
            self.worker_stats[worker_name] = {
                'shares': 0,
                'accepted': 0,
                'rejected': 0,
                'hash_rate': 0.0,
                'last_seen': now,
                'first_seen': now,
                'difficulties': [],
            }
        
        stats = self.worker_stats[worker_name]
        stats['shares'] += 1
        stats['last_seen'] = now
        
        if accepted:
            stats['accepted'] += 1
            self.total_shares_accepted += 1
        else:
            stats['rejected'] += 1
            self.total_shares_rejected += 1
        
        # Track recent difficulties for hash rate estimation
        stats['difficulties'].append((now, difficulty))
        # Keep last 100 entries
        if len(stats['difficulties']) > 100:
            stats['difficulties'] = stats['difficulties'][-100:]
        
        # Estimate hash rate from recent shares
        if len(stats['difficulties']) >= 2:
            oldest_t, oldest_d = stats['difficulties'][0]
            time_span = now - oldest_t
            if time_span > 0:
                total_work = sum(d for t, d in stats['difficulties'])
                # Hash rate = total_difficulty * 2^32 / time_span
                stats['hash_rate'] = (total_work * (2**32)) / time_span
    
    def get_global_submission_rate(self):
        """Get current global submission rate (shares/second)"""
        now = time.time()
        cutoff = now - self.global_submission_window
        recent = [(t, d) for t, d in self.global_submissions if t > cutoff]
        if len(recent) == 0:
            return 0.0
        return len(recent) / self.global_submission_window
    
    def is_submission_rate_safe(self):
        """Check if global submission rate is within safe limits"""
        return self.get_global_submission_rate() < self.MAX_SUBMISSIONS_PER_SECOND
    
    def get_safe_minimum_difficulty(self, requested_difficulty):
        """
        Calculate safe minimum difficulty considering pool load.
        
        PERFORMANCE SAFEGUARD: This prevents miners from setting too-low difficulty
        that would overwhelm the pool with share submissions.
        
        Args:
            requested_difficulty: The difficulty requested by the miner
            
        Returns:
            Safe difficulty (may be higher than requested if pool is under load)
        """
        # Absolute floor - never go below this
        safe_diff = max(requested_difficulty, self.MIN_DIFFICULTY_FLOOR)
        
        # If submission rate is high, enforce higher minimum
        submission_rate = self.get_global_submission_rate()
        if submission_rate > self.MAX_SUBMISSIONS_PER_SECOND * 0.5:
            # Pool is under load - increase minimum difficulty
            load_factor = submission_rate / (self.MAX_SUBMISSIONS_PER_SECOND * 0.5)
            safe_diff = max(safe_diff, self.MIN_DIFFICULTY_FLOOR * load_factor * 10)
            print 'POOL LOAD: High submission rate (%.1f/s), enforcing min diff %.4f' % (
                submission_rate, safe_diff)
        
        return safe_diff
    
    def get_safe_difficulty(self, requested_difficulty):
        """
        Calculate safe difficulty within pool-defined bounds.
        
        SAFEGUARDS:
        1. Enforces minimum (prevents pool overload from low-diff flooding)
        2. Enforces maximum (prevents miner from never finding shares and disconnecting)
        
        Args:
            requested_difficulty: The difficulty requested by the miner
            
        Returns:
            Safe difficulty clamped to [MIN_DIFFICULTY_FLOOR, MAX_DIFFICULTY_CEILING]
        """
        # Apply both floor and ceiling
        safe_diff = self.get_safe_minimum_difficulty(requested_difficulty)
        
        # Cap at maximum to prevent miners from setting impossibly high difficulty
        if safe_diff > self.MAX_DIFFICULTY_CEILING:
            print 'MINER PROTECTION: Requested diff %.1f exceeds max, capping to %.1f' % (
                safe_diff, self.MAX_DIFFICULTY_CEILING)
            safe_diff = self.MAX_DIFFICULTY_CEILING
        
        return safe_diff
    
    def store_session(self, session_id, session_data):
        """Store session data for potential resumption"""
        self.sessions[session_id] = session_data
    
    def get_session(self, session_id):
        """Retrieve stored session data"""
        return self.sessions.get(session_id)
    
    def get_worker_stats(self, worker_name=None):
        """Get statistics for a specific worker or all workers"""
        if worker_name:
            return self.worker_stats.get(worker_name)
        return self.worker_stats
    
    def get_ip_worker_stats(self):
        """Calculate per-IP worker diversity for threat detection"""
        ip_workers = {}  # {ip: set(worker_names)}
        
        for conn_id, conn in self.connections.items():
            if hasattr(conn, 'worker_ip') and hasattr(conn, 'username'):
                ip = conn.worker_ip
                worker = conn.username
                if ip not in ip_workers:
                    ip_workers[ip] = set()
                ip_workers[ip].add(worker)
        
        # Convert sets to counts for JSON serialization
        return {ip: len(workers) for ip, workers in ip_workers.items()}
    
    def get_unique_connected_addresses(self):
        """Get count of unique miner addresses currently connected (not necessarily mining)"""
        connected_addresses = set()
        for conn_id, conn in self.connections.items():
            if hasattr(conn, 'address') and conn.address:
                connected_addresses.add(conn.address)
        return len(connected_addresses)
    
    def get_pool_stats(self):
        """Get overall pool statistics"""
        now = time.time()
        # Calculate rate directly from recent submissions
        cutoff = now - self.global_submission_window
        recent = [(t, d) for t, d in self.global_submissions if t > cutoff]
        rate = len(recent) / float(self.global_submission_window) if recent else 0.0
        return {
            'connections': self.connection_count,
            'workers': len(self.worker_stats),
            'total_accepted': self.total_shares_accepted,
            'total_rejected': self.total_shares_rejected,
            'submission_rate': rate,
            'uptime': now - self.startup_time,
            'ip_connections': dict(self.ip_connections),
            'ip_workers': self.get_ip_worker_stats(),  # Add worker diversity per IP
            'threat_thresholds': {  # Include thresholds for web UI
                'connection_worker_elevated': self.connection_worker_elevated,
                'connection_worker_warning': self.connection_worker_warning,
            },
        }
    
    def get_security_stats(self):
        """Get security and DDoS detection metrics"""
        now = time.time()
        
        # Calculate submission rate burst (last 10 seconds vs last 60 seconds)
        recent_10s = [(t, d) for t, d in self.global_submissions if t > now - 10]
        recent_60s = [(t, d) for t, d in self.global_submissions if t > now - 60]
        
        rate_10s = len(recent_10s) / 10.0 if recent_10s else 0
        rate_60s = len(recent_60s) / 60.0 if recent_60s else 0
        
        # Burst ratio: sudden spike detection (>3x normal is suspicious)
        burst_ratio = rate_10s / rate_60s if rate_60s > 0 else 0
        
        # Connection to worker anomaly
        conn_worker_ratio = self.connection_count / float(len(self.worker_stats)) if self.worker_stats else 0
        
        # Reject rate (high reject = possible invalid share flood)
        total_shares = self.total_shares_accepted + self.total_shares_rejected
        reject_rate = self.total_shares_rejected / float(total_shares) if total_shares > 0 else 0
        
        # Workers with suspiciously high submission rates
        suspicious_workers = []
        for worker_name, stats in self.worker_stats.items():
            if len(stats.get('difficulties', [])) >= 2:
                diffs = stats['difficulties']
                worker_time_span = diffs[-1][0] - diffs[0][0]
                if worker_time_span > 0:
                    worker_rate = len(diffs) / worker_time_span
                    # More than 10 shares/sec from single worker is suspicious
                    if worker_rate > 10:
                        suspicious_workers.append({
                            'name': worker_name,
                            'rate': worker_rate,
                        })
        
        # Calculate threat level
        threat_level = 0  # 0=normal, 1=elevated, 2=warning, 3=critical
        threat_reasons = []
        
        if burst_ratio > 5:
            threat_level = max(threat_level, 2)
            threat_reasons.append('Submission burst detected (%.1fx normal)' % burst_ratio)
        elif burst_ratio > 3:
            threat_level = max(threat_level, 1)
            threat_reasons.append('Elevated submission burst (%.1fx normal)' % burst_ratio)
        
        if conn_worker_ratio > 5:
            threat_level = max(threat_level, 2)
            threat_reasons.append('High connection/worker ratio (%.1f)' % conn_worker_ratio)
        elif conn_worker_ratio > 3:
            threat_level = max(threat_level, 1)
            threat_reasons.append('Elevated connection/worker ratio (%.1f)' % conn_worker_ratio)
        
        if reject_rate > 0.5:
            threat_level = max(threat_level, 2)
            threat_reasons.append('High reject rate (%.1f%%)' % (reject_rate * 100))
        elif reject_rate > 0.2:
            threat_level = max(threat_level, 1)
            threat_reasons.append('Elevated reject rate (%.1f%%)' % (reject_rate * 100))
        
        if rate_10s > self.MAX_SUBMISSIONS_PER_SECOND * 0.8:
            threat_level = max(threat_level, 3)
            threat_reasons.append('Near rate limit (%.0f/s of %d max)' % (rate_10s, self.MAX_SUBMISSIONS_PER_SECOND))
        elif rate_10s > self.MAX_SUBMISSIONS_PER_SECOND * 0.5:
            threat_level = max(threat_level, 2)
            threat_reasons.append('High submission rate (%.0f/s)' % rate_10s)
        
        if len(suspicious_workers) > 0:
            threat_level = max(threat_level, 1)
            threat_reasons.append('%d worker(s) with high submission rate' % len(suspicious_workers))
        
        # Add ban count to threat assessment
        active_bans = len([v for v in self.banned_ips.values() if v > now])
        if active_bans > 0:
            threat_level = max(threat_level, 1)
            threat_reasons.append('%d IP(s) currently banned' % active_bans)
        
        return {
            'rate_10s': rate_10s,
            'rate_60s': rate_60s,
            'burst_ratio': burst_ratio,
            'conn_worker_ratio': conn_worker_ratio,
            'reject_rate': reject_rate,
            'suspicious_workers': suspicious_workers,
            'threat_level': threat_level,  # 0=normal, 1=elevated, 2=warning, 3=critical
            'threat_reasons': threat_reasons,
            'banned_ips_count': active_bans,
            'banned_workers_count': len([v for v in self.banned_workers.values() if v > now]),
            'limits': {
                'max_submissions_per_sec': self.MAX_SUBMISSIONS_PER_SECOND,
                'max_connections': self.MAX_CONNECTIONS,
                'min_difficulty': self.MIN_DIFFICULTY_FLOOR,
                'max_connections_per_ip': self.MAX_CONNECTIONS_PER_IP,
            }
        }

# Global pool statistics instance
pool_stats = PoolStatistics.get_instance()


class StratumRPCMiningProvider(object):
    def __init__(self, wb, other, transport):
        self.pool_version_mask = 0x1fffe000  # BIP320 standard mask for ASICBOOST
        self.wb = wb
        self.other = other
        self.transport = transport
        
        self.username = None
        self.worker_ip = transport.getPeer().host if transport else None  # Track worker IP
        self.handler_map = expiring_dict.ExpiringDict(300)
        
        # ==== Check if IP is banned ====
        if self.worker_ip and pool_stats.is_ip_banned(self.worker_ip):
            print 'Rejected connection from banned IP: %s' % self.worker_ip
            if transport:
                transport.loseConnection()
            return
        
        # ==== Check per-IP connection limit ====
        if self.worker_ip and not pool_stats.check_ip_connection_limit(self.worker_ip):
            print 'Rejected connection from %s: too many connections (%d)' % (
                self.worker_ip, pool_stats.ip_connections.get(self.worker_ip, 0))
            pool_stats.record_violation(self.worker_ip, 'connection_flood')
            if transport:
                transport.loseConnection()
            return
        
        # Extranonce support for ASICs
        self.extranonce_subscribe = False
        self.extranonce1 = ""
        self.last_extranonce_update = 0
        
        self.watch_id = self.wb.new_work_event.watch(self._send_work)
        
        self.recent_shares = []
        self.target = None
        self.share_rate = wb.share_rate  # From command-line or default (10 sec)
        self.fixed_target = False
        self.desired_pseudoshare_target = None
        
        # ==== NEW: Enhanced difficulty management ====
        # Suggested difficulty from miner (mining.suggest_difficulty)
        self.suggested_difficulty = None
        # Minimum difficulty floor from BIP310 minimum-difficulty extension
        self.minimum_difficulty = None
        # Dynamic share rate (can be overridden per-worker)
        self.worker_share_rate = None
        
        # ==== NEW: Session management ====
        self.session_id = '%016x' % random.randrange(2**64)
        self.connection_time = time.time()
        
        # ==== NEW: Connection tracking ====
        self.conn_id = id(self)
        pool_stats.register_connection(self.conn_id, self, self.worker_ip)
        
        # ==== NEW: Per-connection statistics ====
        self.shares_submitted = 0
        self.shares_accepted = 0
        self.shares_rejected = 0
        self.last_share_time = None
    
    def rpc_subscribe(self, miner_version=None, session_id=None, *args):
        """
        Handle mining.subscribe - the first message from a miner.
        
        Supports session resumption: if session_id is provided and valid,
        restore the previous session state.
        
        Args:
            miner_version: Miner software identification string
            session_id: Optional session ID for resumption
            *args: Additional arguments (ignored)
        
        Returns:
            [subscription_details, extranonce1, extranonce2_size]
        """
        if p2pool.DEBUG:
            print 'STRATUM: mining.subscribe from %s - miner: %s, session: %s' % (
                self.worker_ip, miner_version, session_id[:16] if session_id else 'new')
        
        # ==== NEW: Session resumption support ====
        if session_id:
            stored_session = pool_stats.get_session(session_id)
            if stored_session:
                # Restore session state
                self.session_id = session_id
                self.target = stored_session.get('target')
                self.suggested_difficulty = stored_session.get('suggested_difficulty')
                self.minimum_difficulty = stored_session.get('minimum_difficulty')
                self.worker_share_rate = stored_session.get('share_rate')
                if p2pool.DEBUG:
                    print 'STRATUM: Resumed session %s for %s' % (session_id[:16], self.worker_ip)
        
        reactor.callLater(0, self._send_work)
        
        return [
            [["mining.set_difficulty", "ae6812eb4cd7735a302a8a9dd95cf71f1"], ["mining.notify", "ae6812eb4cd7735a302a8a9dd95cf71f2"]], # subscription details
            self.extranonce1 if self.extranonce1 else "",  # extranonce1 (use stored if resuming)
            self.wb.COINBASE_NONCE_LENGTH,  # extranonce2_size
            self.session_id,  # Return session ID for potential future resumption
        ]
    
    def rpc_authorize(self, username, password):
        if not hasattr(self, 'authorized'):  # authorize can be called many times in one connection
            self.authorized = username
        self.username = username.strip()
        if p2pool.DEBUG:
            print 'STRATUM: mining.authorize from %s - worker: %s' % (self.worker_ip, self.username)
        
        # ==== ENHANCED: Parse username with extended format support ====
        # Username formats supported:
        #   address                      - Basic address
        #   address+difficulty           - Address with pseudoshare difficulty
        #   address/share_difficulty     - Address with share difficulty
        #   address+diff/sharediff       - Both difficulties
        #   address+diff+sN              - Difficulty + share rate N seconds
        #   address.worker               - Address with worker name
        #   address_worker               - Address with worker name (alt format)
        
        self.user = self.username
        self.address = self.username.split('+')[0].split('/')[0].split('.')[0].split('_')[0]
        self.desired_share_target = None
        self.desired_pseudoshare_target = None
        
        # Parse extended options from username
        parts = self.username.replace('/', '+').split('+')
        for part in parts[1:]:
            if part.startswith('s') and part[1:].isdigit():
                # Dynamic share rate: +s5 means 5 seconds per share
                requested_rate = float(part[1:])
                # Clamp to reasonable range (1-60 seconds)
                self.worker_share_rate = clip(requested_rate, 1.0, 60.0)
                print 'STRATUM: Worker %s requested share rate: %.1fs' % (self.username, self.worker_share_rate)
            elif part.replace('.', '').isdigit():
                # Difficulty specification
                try:
                    diff = float(part)
                    self.desired_pseudoshare_target = dash_data.difficulty_to_target(diff)
                except:
                    pass
        
        reactor.callLater(0, self._send_work)
        return True
    
    # ==== NEW: mining.suggest_difficulty implementation ====
    def rpc_suggest_difficulty(self, difficulty):
        """
        Handle mining.suggest_difficulty - allows miner to suggest initial difficulty.
        
        PERFORMANCE SAFEGUARD: The suggested difficulty is subject to:
        1. Pool-wide minimum difficulty floor (prevents server overload)
        2. Dynamic adjustment based on pool load
        3. The normal vardiff algorithm will still adjust from this starting point
        
        Args:
            difficulty: Suggested starting difficulty (float)
        
        Returns:
            True on acceptance, the actual difficulty may differ from suggested
        """
        try:
            requested_diff = float(difficulty)
        except (ValueError, TypeError):
            # Keep invalid requests as warnings (not DEBUG) - indicates miner bug
            print 'STRATUM: Invalid suggest_difficulty from %s: %s' % (self.worker_ip, difficulty)
            return False
        
        # PERFORMANCE SAFEGUARD: Apply pool-wide safety limits (floor AND ceiling)
        safe_diff = pool_stats.get_safe_difficulty(requested_diff)
        
        # Also respect any minimum-difficulty set by BIP310 extension
        if self.minimum_difficulty is not None:
            safe_diff = max(safe_diff, self.minimum_difficulty)
        
        self.suggested_difficulty = safe_diff
        self.target = dash_data.difficulty_to_target(safe_diff)
        
        # Log if we had to adjust the difficulty
        if p2pool.DEBUG:
            if safe_diff != requested_diff:
                print 'STRATUM: suggest_difficulty from %s: requested %.4f, using %.4f (pool safeguard)' % (
                    self.worker_ip, requested_diff, safe_diff)
            else:
                print 'STRATUM: suggest_difficulty from %s: accepted %.4f' % (self.worker_ip, safe_diff)
        
        # Send immediate difficulty update to miner
        self.other.svc_mining.rpc_set_difficulty(safe_diff).addErrback(lambda err: None)
        
        # ==== FIX: Send new work immediately with the suggested difficulty ====
        # mining.suggest_difficulty often arrives AFTER mining.authorize, so the
        # initial work sent during authorize uses wrong difficulty. Re-send work
        # now with the correct difficulty target.
        reactor.callLater(0.1, self._send_work)
        
        return True
    
    def rpc_configure(self, extensions, extensionParameters):
        """
        Handle mining.configure (BIP310) - negotiate protocol extensions.
        
        Supported extensions:
        - version-rolling (BIP320 ASICBoost)
        - minimum-difficulty (sets difficulty floor for this connection)
        - subscribe-extranonce (NiceHash-style extranonce updates)
        
        Args:
            extensions: List of extension codes to negotiate
            extensionParameters: Dict of parameters for each extension
        
        Returns:
            Dict of negotiated extension results
        """
        if p2pool.DEBUG:
            print 'STRATUM: mining.configure from %s - extensions: %s' % (self.worker_ip, extensions)
        
        result = {}
        
        if 'version-rolling' in extensions:
            # ASICBoost support (BIP320)
            miner_mask = extensionParameters.get('version-rolling.mask', '0')
            try:
                minbitcount = extensionParameters.get('version-rolling.min-bit-count', 2)
            except:
                log.err("A miner tried to connect with a malformed version-rolling.min-bit-count parameter. This is probably a bug in your mining software. Braiins OS is known to have this bug. You should complain to them.")
                minbitcount = 2
            # Return the negotiated mask (pool mask AND miner mask)
            negotiated_mask = self.pool_version_mask & int(miner_mask, 16)
            result["version-rolling"] = True
            result["version-rolling.mask"] = '{:08x}'.format(negotiated_mask)
            if p2pool.DEBUG:
                print 'STRATUM: ASICBoost enabled for %s - mask: %08x' % (self.worker_ip, negotiated_mask)
        
        # ==== NEW: minimum-difficulty BIP310 extension ====
        if 'minimum-difficulty' in extensions:
            requested_min = extensionParameters.get('minimum-difficulty.value', 1)
            try:
                requested_min = float(requested_min)
            except (ValueError, TypeError):
                requested_min = 1.0
            
            # PERFORMANCE SAFEGUARD: Apply pool-wide safety limits
            safe_min = pool_stats.get_safe_minimum_difficulty(requested_min)
            
            self.minimum_difficulty = safe_min
            result["minimum-difficulty"] = True
            
            # If this sets a floor higher than current target, update target
            if self.target is not None:
                current_diff = dash_data.target_to_difficulty(self.target)
                if current_diff < safe_min:
                    self.target = dash_data.difficulty_to_target(safe_min)
                    if p2pool.DEBUG:
                        print 'STRATUM: minimum-difficulty raised current diff from %.4f to %.4f for %s' % (
                            current_diff, safe_min, self.worker_ip)
            
            if p2pool.DEBUG:
                if safe_min != requested_min:
                    print 'STRATUM: minimum-difficulty from %s: requested %.4f, enforcing %.4f (pool safeguard)' % (
                        self.worker_ip, requested_min, safe_min)
                else:
                    print 'STRATUM: minimum-difficulty enabled for %s: %.4f' % (self.worker_ip, safe_min)
            
        if 'subscribe-extranonce' in extensions:
            # Enable extranonce subscription for this connection (required for ASICs)
            self.extranonce_subscribe = True
            result["subscribe-extranonce"] = True
            if p2pool.DEBUG:
                print 'STRATUM: Extranonce subscription enabled for %s' % self.worker_ip
        
        return result if result else None
    
    # ==== NEW: client.reconnect for load balancing ====
    def rpc_reconnect(self, hostname=None, port=None, wait_time=0):
        """
        Request client to reconnect (for load balancing).
        
        This is typically called BY THE POOL to ask a miner to reconnect,
        possibly to a different server.
        
        Args:
            hostname: New hostname to connect to (optional)
            port: New port to connect to (optional)
            wait_time: Seconds to wait before reconnecting
        
        Returns:
            True
        """
        # Store session before disconnect for potential resumption
        pool_stats.store_session(self.session_id, {
            'target': self.target,
            'suggested_difficulty': self.suggested_difficulty,
            'minimum_difficulty': self.minimum_difficulty,
            'share_rate': self.worker_share_rate,
            'username': self.username,
            'worker_ip': self.worker_ip,
        })
        print 'STRATUM: Stored session %s for reconnect' % self.session_id[:16]
        return True
    
    def _send_work(self):
        if p2pool.DEBUG:
            print 'STRATUM: _send_work called for %s (username=%s)' % (self.worker_ip, self.username)
        try:
            x, got_response = self.wb.get_work(*self.wb.preprocess_request('' if self.username is None else self.username))
            if p2pool.DEBUG:
                print 'STRATUM: _send_work got work for %s' % self.worker_ip
        except Exception as e:
            # Don't disconnect for temporary errors like "lost contact with dashd"
            # Just log and skip this work update - miner will keep working on old job
            error_msg = str(e)
            if 'lost contact' in error_msg or 'not connected' in error_msg:
                # Temporary error - don't spam logs, just skip
                if p2pool.DEBUG:
                    print 'STRATUM: _send_work skipped - %s' % error_msg
            else:
                print 'STRATUM: _send_work error for %s - %s' % (self.worker_ip, error_msg)
                log.err(None, 'Error getting work for stratum:')
            return
        
        if self.desired_pseudoshare_target:
            # Fixed target from username parsing (e.g., "wallet+1000")
            # Note: we do NOT cap this at P2Pool share floor - vardiff should be
            # allowed to go harder than the (potentially easy) bootstrap P2Pool chain
            self.fixed_target = True
            self.target = self.desired_pseudoshare_target
        else:
            self.fixed_target = False
            # Start at a reasonable default difficulty that will quickly adjust via vardiff
            # Don't cap at min_share_target - that would prevent vardiff from going harder
            if self.target is None:
                # ==== ENHANCED: Use suggested_difficulty if provided ====
                if self.suggested_difficulty is not None:
                    initial_diff = self.suggested_difficulty
                    print 'STRATUM: Worker starting at suggested difficulty %.4f' % initial_diff
                else:
                    # Check for network-specific default difficulty (e.g., regtest uses lower diff)
                    if hasattr(self.wb.net, 'STRATUM_DEFAULT_DIFFICULTY'):
                        initial_diff = self.wb.net.STRATUM_DEFAULT_DIFFICULTY
                        if p2pool.DEBUG:
                            print 'STRATUM: New worker starting at network default difficulty %.4f' % initial_diff
                    else:
                        # Default: start at difficulty 100
                        # This is a balance between:
                        # - Not too low (diff 1 causes share flood from ASICs)
                        # - Not too high (diff 10000 makes slow miners wait too long)
                        # At 1.7 TH/s ASIC: ~0.25 sec/share (will ramp up quickly)
                        # At 100 MH/s GPU: ~4 sec/share (reasonable)
                        initial_diff = 100
                        if p2pool.DEBUG:
                            print 'STRATUM: New worker starting at default difficulty %d' % initial_diff
                
                # PERFORMANCE SAFEGUARD: Apply pool-wide minimum
                initial_diff = pool_stats.get_safe_minimum_difficulty(initial_diff)
                
                diff1_target = 0xFFFF * 2**208  # Standard bdiff difficulty 1 target
                self.target = diff1_target // int(initial_diff)
                
                # Initialize last_share_time for timeout-based vardiff reduction
                # This allows difficulty to be lowered even if no shares have been submitted yet
                if self.last_share_time is None:
                    self.last_share_time = time.time()
        
        # ==== ENHANCED: Enforce minimum difficulty floor ====
        if self.minimum_difficulty is not None and self.target is not None:
            current_diff = dash_data.target_to_difficulty(self.target)
            if current_diff < self.minimum_difficulty:
                self.target = dash_data.difficulty_to_target(self.minimum_difficulty)
        
        # ==== NEW: Timeout-based difficulty reduction ====
        # If no shares received for too long, reduce difficulty
        # This handles the case where vardiff jumped too aggressively
        if not self.fixed_target and self.target is not None and self.last_share_time is not None:
            time_since_last_share = time.time() - self.last_share_time
            effective_share_rate = self.worker_share_rate if self.worker_share_rate else self.share_rate
            # If we've waited 3x the expected time without a share, reduce difficulty
            expected_time = effective_share_rate * 3  # 3x target time = too long
            if time_since_last_share > expected_time:
                current_diff = dash_data.target_to_difficulty(self.target)
                # Reduce by 50% each time we exceed the timeout
                new_diff = current_diff * 0.5
                # Respect minimum difficulty floor
                if self.minimum_difficulty is not None:
                    new_diff = max(new_diff, self.minimum_difficulty)
                # Respect pool-wide minimum
                new_diff = max(new_diff, pool_stats.get_safe_minimum_difficulty(new_diff))
                if new_diff < current_diff:
                    self.target = dash_data.difficulty_to_target(new_diff)
                    # Only log timeout for connections that have submitted shares
                    # This suppresses noise from idle backup/redundant ASIC connections
                    if self.shares_submitted > 0 and p2pool.DEBUG:
                        print 'Vardiff timeout %s: %.4f -> %.4f (no shares for %.1fs, target %.1fs)' % (
                            self.username or self.worker_ip, current_diff, new_diff, 
                            time_since_last_share, effective_share_rate)
                    # Reset the timer so we don't immediately reduce again
                    self.last_share_time = time.time()
        
        # For ASIC compatibility: periodically send extranonce updates
        # Even with empty extranonce, this helps ASICs reset their state
        if self.extranonce_subscribe:
            current_time = time.time()
            # Send extranonce update every 30 seconds or on first work
            if current_time - self.last_extranonce_update > 30:
                self._notify_extranonce_change()
                self.last_extranonce_update = current_time
        
        # Use short job IDs for ASIC compatibility (8 hex chars max)
        # ASICs like Antminer truncate long job IDs causing "job_id does not change" errors
        jobid = '%08x' % random.randrange(2**32)
        job_target = self.target  # Capture the target that will be sent with this job
        self.other.svc_mining.rpc_set_difficulty(dash_data.target_to_difficulty(job_target)).addErrback(lambda err: None)
        self.other.svc_mining.rpc_notify(
            jobid, # jobid
            getwork._swap4(pack.IntType(256).pack(x['previous_block'])).encode('hex'), # prevhash
            x['coinb1'].encode('hex'), # coinb1
            x['coinb2'].encode('hex'), # coinb2
            [pack.IntType(256).pack(s).encode('hex') for s in x['merkle_link']['branch']], # merkle_branch
            getwork._swap4(pack.IntType(32).pack(x['version'])).encode('hex'), # version
            getwork._swap4(pack.IntType(32).pack(x['bits'].bits)).encode('hex'), # nbits
            getwork._swap4(pack.IntType(32).pack(x['timestamp'])).encode('hex'), # ntime
            True, # clean_jobs
        ).addErrback(lambda err: None)
        self.handler_map[jobid] = x, got_response, job_target  # Store job_target with the job
    
    def rpc_submit(self, worker_name, job_id, extranonce2, ntime, nonce, version_bits=None, *args):
        # ASICBOOST: version_bits is the version mask that the miner used
        t0 = time.time()  # Benchmarking start
        worker_name = worker_name.strip()
        
        # ==== Check if worker is banned ====
        if pool_stats.is_worker_banned(worker_name):
            return False
        
        # ==== Check if IP is banned ====
        if self.worker_ip and pool_stats.is_ip_banned(self.worker_ip):
            self.transport.loseConnection()
            return False
        
        # Rate limiting: drop submissions if coming too fast (more than 100/sec)
        # This prevents server overload when difficulty is too low
        now = time.time()
        if not hasattr(self, '_last_submit_time'):
            self._last_submit_time = 0
            self._rapid_submit_count = 0
        
        time_since_last = now - self._last_submit_time
        if time_since_last < 0.01:  # More than 100 submissions/sec
            self._rapid_submit_count += 1
            if self._rapid_submit_count > 10:
                # Record violation for rate abuse
                if self.worker_ip:
                    pool_stats.record_violation(self.worker_ip, 'rate_abuse')
                # Drop submission silently to reduce load, but still return True
                # to avoid miner reconnecting
                return True
        else:
            self._rapid_submit_count = 0
        self._last_submit_time = now
        
        if job_id not in self.handler_map:
            print >>sys.stderr, 'Stale job submission from %s: job_id=%s not found' % (worker_name, job_id[:16])
            # Return False for stale jobs instead of raising exception
            # This is more compatible with various miner implementations
            return False
        
        x, got_response, job_target = self.handler_map[job_id]  # Retrieve job_target
        
        try:
            coinb_nonce = extranonce2.decode('hex')
        except Exception as e:
            print >>sys.stderr, 'Invalid extranonce2 from %s: %s' % (worker_name, str(e))
            return False
        
        if len(coinb_nonce) != self.wb.COINBASE_NONCE_LENGTH:
            print >>sys.stderr, 'Invalid extranonce2 length from %s: got %d, expected %d' % (worker_name, len(coinb_nonce), self.wb.COINBASE_NONCE_LENGTH)
            return False
        
        new_packed_gentx = x['coinb1'] + coinb_nonce + x['coinb2']
        
        job_version = x['version']
        nversion = job_version
        
        # Check if miner changed bits that they were not supposed to change
        if version_bits:
            if ((~self.pool_version_mask) & int(version_bits, 16)) != 0:
                # Protocol does not say error needs to be returned but ckpool returns
                # {"error": "Invalid version mask", "id": "id", "result":""}
                raise ValueError("Invalid version mask {0}".format(version_bits))
            nversion = (job_version & ~self.pool_version_mask) | (int(version_bits, 16) & self.pool_version_mask)
        
        header = dict(
            version=nversion,
            previous_block=x['previous_block'],
            merkle_root=dash_data.check_merkle_link(dash_data.hash256(new_packed_gentx), x['merkle_link']),
            timestamp=pack.IntType(32).unpack(getwork._swap4(ntime.decode('hex'))),
            bits=x['bits'],
            nonce=pack.IntType(32).unpack(getwork._swap4(nonce.decode('hex'))),
        )
        # Dash's got_response takes 4 args: (header, user, coinbase_nonce, submitted_target)
        # Use job_target (the target sent with THIS job) for proper validation and hashrate
        result = got_response(header, worker_name, coinb_nonce, job_target)
        
        # ==== ENHANCED: Update statistics ====
        self.shares_submitted += 1
        self.last_share_time = now
        current_diff = dash_data.target_to_difficulty(job_target)
        
        # ==== Option C: Session Linkage ====
        # Update last_share_time for ALL connections of this worker
        # This prevents timeout vardiff on backup/redundant connections
        pool_stats.update_worker_last_share_time(worker_name, now)
        
        if result:
            self.shares_accepted += 1
            pool_stats.record_share(worker_name, current_diff, accepted=True)
        else:
            self.shares_rejected += 1
            pool_stats.record_share(worker_name, current_diff, accepted=False)
        
        # Aggressive vardiff: adjust difficulty to target ~share_rate seconds per pseudoshare
        # For high-hashrate ASICs, we need to ramp up difficulty quickly to avoid flooding
        if not self.fixed_target:
            self.recent_shares.append(now)
            
            # ==== ENHANCED: Use worker-specific or default share rate ====
            effective_share_rate = self.worker_share_rate if self.worker_share_rate else self.share_rate
            
            # Get vardiff parameters from network config (with defaults for compatibility)
            net = self.wb.net
            shares_trigger = getattr(net, 'VARDIFF_SHARES_TRIGGER', 8)
            timeout_mult = getattr(net, 'VARDIFF_TIMEOUT_MULT', 5)
            quickup_shares = getattr(net, 'VARDIFF_QUICKUP_SHARES', 2)
            quickup_divisor = getattr(net, 'VARDIFF_QUICKUP_DIVISOR', 3)
            min_adjust = getattr(net, 'VARDIFF_MIN_ADJUST', 0.5)
            max_adjust = getattr(net, 'VARDIFF_MAX_ADJUST', 2.0)
            
            # ASIC-optimized vardiff: parameters from network config
            num_shares = len(self.recent_shares)
            time_elapsed = now - self.recent_shares[0] if num_shares > 0 else 0
            target_time = num_shares * effective_share_rate
            
            # Adjust based on configurable thresholds
            should_adjust = (num_shares >= shares_trigger or 
                            (num_shares >= 1 and time_elapsed > timeout_mult * target_time) or
                            (num_shares >= quickup_shares and time_elapsed < target_time / quickup_divisor))
            
            if should_adjust and num_shares > 0:
                # Calculate actual share rate vs target
                actual_rate = time_elapsed / num_shares if num_shares > 0 else effective_share_rate
                adjustment = actual_rate / effective_share_rate
                
                # Apply configurable adjustment limits
                adjustment = clip(adjustment, min_adjust, max_adjust)
                
                old_diff = dash_data.target_to_difficulty(self.target)
                self.target = int(self.target * adjustment + 0.5)
                
                # Clip target to valid range for stratum vardiff
                # SANE_TARGET_RANGE[0] = hardest (lowest target, e.g. diff 10000)
                # For easiest, we allow much lower than SANE_TARGET_RANGE[1] to support slow miners
                # Calculate max target for MIN_DIFFICULTY_FLOOR (0.001)
                max_stratum_target = dash_data.difficulty_to_target(pool_stats.MIN_DIFFICULTY_FLOOR)
                min_stratum_target = self.wb.net.SANE_TARGET_RANGE[0]  # Hardest allowed
                newtarget = clip(self.target, min_stratum_target, max_stratum_target)
                if newtarget != self.target:
                    self.target = newtarget
                
                # ==== ENHANCED: Enforce minimum difficulty floor ====
                if self.minimum_difficulty is not None:
                    new_diff = dash_data.target_to_difficulty(self.target)
                    if new_diff < self.minimum_difficulty:
                        self.target = dash_data.difficulty_to_target(self.minimum_difficulty)
                
                # ==== ENHANCED: Enforce pool-wide minimum ====
                new_diff = dash_data.target_to_difficulty(self.target)
                safe_min = pool_stats.get_safe_minimum_difficulty(new_diff)
                if new_diff < safe_min:
                    self.target = dash_data.difficulty_to_target(safe_min)
                    new_diff = safe_min
                
                if p2pool.DEBUG and abs(new_diff - old_diff) / max(old_diff, 0.001) > 0.1:  # Only log significant changes in DEBUG mode
                    print 'Vardiff %s: %.4f -> %.4f (%.1f shares in %.1fs, target %.1fs)' % (
                        worker_name, old_diff, new_diff, num_shares, time_elapsed, target_time)
                
                # Reset and send new work
                self.recent_shares = [now]
                self._send_work()
        
        # Benchmarking: print timing if BENCH enabled
        t1 = time.time()
        try:
            if p2pool.BENCH and (t1-t0) > 0.01:  # Only log if > 10ms
                print "%8.3f ms for stratum:rpc_submit(%s)" % ((t1-t0)*1000., worker_name)
        except:
            pass
        
        return result
    
    def rpc_set_extranonce(self, extranonce1, extranonce2_size):
        """
        Handle mining.set_extranonce from pool/proxy
        
        This is sent BY THE POOL to miners when extranonce changes.
        Miners that subscribed to 'subscribe-extranonce' expect this.
        
        Args:
            extranonce1: New extranonce1 value (hex string)
            extranonce2_size: Size of extranonce2 in bytes (integer)
        
        Returns:
            True on success
        """
        if not self.extranonce_subscribe:
            # Miner didn't subscribe to extranonce updates
            return False
        
        # Update the extranonce for this connection
        if extranonce1:
            self.extranonce1 = extranonce1
        else:
            self.extranonce1 = ""
        
        if extranonce2_size != self.wb.COINBASE_NONCE_LENGTH:
            print >>sys.stderr, 'WARNING: extranonce2_size mismatch: expected %d, got %d' % (
                self.wb.COINBASE_NONCE_LENGTH, extranonce2_size)
        
        print '>>>Set extranonce: %s (size=%d) for %s' % (
            extranonce1 if extranonce1 else "(empty)", 
            extranonce2_size, 
            self.worker_ip
        )
        
        return True
    
    def _notify_extranonce_change(self, new_extranonce1=None):
        """
        Notify miners that subscribed to extranonce updates
        Called when extranonce needs to change (e.g., reconnection, long mining session)
        """
        if not self.extranonce_subscribe:
            return
        
        # Use current or new extranonce1
        extranonce1 = new_extranonce1 if new_extranonce1 is not None else self.extranonce1
        extranonce2_size = self.wb.COINBASE_NONCE_LENGTH
        
        # Send mining.set_extranonce notification to miner
        self.other.svc_mining.rpc_set_extranonce(
            extranonce1,
            extranonce2_size
        ).addErrback(lambda err: None)
        
        print '>>>Notified extranonce change to %s: %s (size=%d)' % (
            self.worker_ip,
            extranonce1 if extranonce1 else "(empty)",
            extranonce2_size
        )
    
    def close(self):
        """
        Clean up when connection closes.
        
        - Unregister from work events
        - Store session for potential resumption
        - Update pool statistics
        """
        # Only unwatch if watch_id was set (connection may have been rejected early)
        if hasattr(self, 'watch_id') and self.watch_id is not None:
            self.wb.new_work_event.unwatch(self.watch_id)
        
        # Store session for potential resumption (only if session was established)
        if hasattr(self, 'session_id') and self.session_id:
            pool_stats.store_session(self.session_id, {
                'target': getattr(self, 'target', None),
                'suggested_difficulty': getattr(self, 'suggested_difficulty', None),
                'minimum_difficulty': getattr(self, 'minimum_difficulty', None),
                'share_rate': getattr(self, 'worker_share_rate', None),
                'username': getattr(self, 'username', None),
                'worker_ip': getattr(self, 'worker_ip', None),
            })
        
        # Unregister connection (with IP for per-IP tracking)
        pool_stats.unregister_connection(self.conn_id, self.worker_ip)
        
        # Log disconnect with statistics
        session_duration = time.time() - self.connection_time
        print 'STRATUM: Disconnect %s (%s) - session: %s, duration: %.0fs, shares: %d/%d' % (
            self.worker_ip,
            self.username if self.username else 'unknown',
            self.session_id[:16],
            session_duration,
            self.shares_accepted,
            self.shares_submitted,
        )
    
    # ==== NEW: Get worker statistics ====
    def get_stats(self):
        """Get statistics for this connection"""
        return {
            'worker_ip': self.worker_ip,
            'username': self.username,
            'session_id': self.session_id,
            'connection_time': self.connection_time,
            'shares_submitted': self.shares_submitted,
            'shares_accepted': self.shares_accepted,
            'shares_rejected': self.shares_rejected,
            'current_difficulty': dash_data.target_to_difficulty(self.target) if self.target else None,
            'minimum_difficulty': self.minimum_difficulty,
            'suggested_difficulty': self.suggested_difficulty,
            'share_rate': self.worker_share_rate if self.worker_share_rate else self.share_rate,
        }


class ExtranonceService(object):
    """Service for NiceHash-style mining.extranonce.subscribe"""
    def __init__(self, parent):
        self.parent = parent
    
    def rpc_subscribe(self):
        """
        NiceHash-style extranonce subscription
        Called via mining.extranonce.subscribe method
        
        Many ASICs use this NiceHash protocol.
        See: https://github.com/nicehash/Specifications/blob/master/NiceHash_extranonce_subscribe_extension.txt
        
        Returns:
            True on success
        """
        self.parent.extranonce_subscribe = True
        print '>>>ExtranOnce subscribed (NiceHash method) from %s' % (self.parent.worker_ip)
        return True


# ==============================================================================
# STRATUM PROTOCOL AND FACTORY
# ==============================================================================

class StratumProtocol(jsonrpc.LineBasedPeer):
    def connectionMade(self):
        self.svc_mining = StratumRPCMiningProvider(self.factory.wb, self.other, self.transport)
        # Add extranonce service for NiceHash compatibility
        self.svc_mining.svc_extranonce = ExtranonceService(self.svc_mining)
    
    def connectionLost(self, reason):
        if hasattr(self, 'svc_mining'):
            self.svc_mining.close()


class StratumServerFactory(protocol.ServerFactory):
    protocol = StratumProtocol
    
    def __init__(self, wb, net=None):
        self.wb = wb
        self.net = net
        # Store threat detection thresholds from network config
        if net:
            pool_stats.connection_worker_elevated = getattr(net, 'CONNECTION_WORKER_ELEVATED', 4.0)
            pool_stats.connection_worker_warning = getattr(net, 'CONNECTION_WORKER_WARNING', 6.0)
    
    def get_pool_stats(self):
        """Get global pool statistics"""
        return pool_stats.get_pool_stats()
    
    def get_worker_stats(self, worker_name=None):
        """Get per-worker statistics"""
        return pool_stats.get_worker_stats(worker_name)
