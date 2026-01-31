import random
import sys
import time
import weakref

from twisted.internet import protocol, reactor
from twisted.python import log

from p2pool.bitcoin import data as bitcoin_data, getwork
from p2pool.util import expiring_dict, jsonrpc, pack

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
    - Global share submission rate
    - Connection history for monitoring
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
        
        # Global submission rate tracking
        self.global_submissions = []  # List of (timestamp, difficulty) tuples
        self.global_submission_window = 60  # Track last 60 seconds
        
        # Per-IP connection tracking
        self.ip_connections = {}  # {ip: count}
        
        # Performance metrics
        self.total_shares_accepted = 0
        self.total_shares_rejected = 0
        self.startup_time = time.time()
    
    def register_connection(self, conn_id, connection, ip=None):
        """Register a new stratum connection"""
        self.connections[conn_id] = connection
        self.connection_count = len(self.connections)
        
        # Track per-IP connections
        if ip:
            self.ip_connections[ip] = self.ip_connections.get(ip, 0) + 1
        
        return True
    
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
    
    def get_worker_connections(self, worker_name):
        """Get all active connections for a worker name"""
        connections = []
        for conn_id, conn in self.connections.items():
            if hasattr(conn, 'username') and conn.username == worker_name:
                connections.append(conn)
        return connections
    
    def get_worker_aggregate_stats(self, worker_name):
        """Get aggregated stats across all connections for a worker"""
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
            aggregate['total_shares_submitted'] += getattr(conn, 'shares_submitted', 0)
            aggregate['total_shares_accepted'] += getattr(conn, 'shares_accepted', 0)
            aggregate['total_shares_rejected'] += getattr(conn, 'shares_rejected', 0)
            if getattr(conn, 'shares_submitted', 0) > 0:
                aggregate['active_connections'] += 1
            else:
                aggregate['backup_connections'] += 1
            if hasattr(conn, 'target') and conn.target:
                aggregate['difficulties'].append(bitcoin_data.target_to_difficulty(conn.target))
        
        return aggregate

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
    
    def get_worker_stats(self, worker_name=None):
        """Get statistics for a specific worker or all workers"""
        if worker_name:
            return self.worker_stats.get(worker_name)
        return self.worker_stats
    
    def get_unique_connected_addresses(self):
        """Get set of unique miner addresses currently connected"""
        connected_addresses = set()
        for conn_id, conn in self.connections.items():
            if hasattr(conn, 'address') and conn.address:
                connected_addresses.add(conn.address)
        return connected_addresses
    
    def get_connected_workers(self):
        """Get dict of connected workers with their info"""
        workers = {}
        for conn_id, conn in self.connections.items():
            if hasattr(conn, 'username') and conn.username:
                worker_name = conn.username
                if worker_name not in workers:
                    workers[worker_name] = {
                        'connections': 0,
                        'address': getattr(conn, 'address', None),
                        'difficulties': [],
                        'ips': set(),
                    }
                workers[worker_name]['connections'] += 1
                if hasattr(conn, 'target') and conn.target:
                    workers[worker_name]['difficulties'].append(
                        bitcoin_data.target_to_difficulty(conn.target))
                if hasattr(conn, 'worker_ip') and conn.worker_ip:
                    workers[worker_name]['ips'].add(conn.worker_ip)
        
        # Convert sets to lists for JSON serialization
        for w in workers:
            workers[w]['ips'] = list(workers[w]['ips'])
        
        return workers
    
    def get_pool_stats(self):
        """Get overall pool statistics"""
        now = time.time()
        # Calculate rate directly from recent submissions
        cutoff = now - self.global_submission_window
        recent = [(t, d) for t, d in self.global_submissions if t > cutoff]
        rate = len(recent) / float(self.global_submission_window) if recent else 0.0
        
        # Count unique workers currently connected
        connected_workers = self.get_connected_workers()
        
        return {
            'connections': self.connection_count,
            'workers': len(connected_workers),
            'unique_addresses': len(self.get_unique_connected_addresses()),
            'total_accepted': self.total_shares_accepted,
            'total_rejected': self.total_shares_rejected,
            'submission_rate': rate,
            'uptime': now - self.startup_time,
            'ip_connections': dict(self.ip_connections),
        }
    
    def get_security_stats(self):
        """Get security and DDoS detection metrics for the stratum monitor UI"""
        now = time.time()
        
        # Calculate submission rate burst (last 10 seconds vs last 60 seconds)
        recent_10s = [(t, d) for t, d in self.global_submissions if t > now - 10]
        recent_60s = [(t, d) for t, d in self.global_submissions if t > now - 60]
        
        rate_10s = len(recent_10s) / 10.0 if recent_10s else 0
        rate_60s = len(recent_60s) / 60.0 if recent_60s else 0
        
        # Burst ratio: sudden spike detection (>3x normal is suspicious)
        burst_ratio = rate_10s / rate_60s if rate_60s > 0 else 0
        
        # Connection to worker anomaly
        worker_count = len(self.worker_stats)
        conn_worker_ratio = self.connection_count / float(worker_count) if worker_count > 0 else 0
        
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
        
        # Rate limit thresholds (using reasonable defaults)
        MAX_SUBMISSIONS_PER_SECOND = 1000
        if rate_10s > MAX_SUBMISSIONS_PER_SECOND * 0.8:
            threat_level = max(threat_level, 3)
            threat_reasons.append('Near rate limit (%.0f/s of %d max)' % (rate_10s, MAX_SUBMISSIONS_PER_SECOND))
        elif rate_10s > MAX_SUBMISSIONS_PER_SECOND * 0.5:
            threat_level = max(threat_level, 2)
            threat_reasons.append('High submission rate (%.0f/s)' % rate_10s)
        
        if len(suspicious_workers) > 0:
            threat_level = max(threat_level, 1)
            threat_reasons.append('%d worker(s) with high submission rate' % len(suspicious_workers))
        
        return {
            'rate_10s': rate_10s,
            'rate_60s': rate_60s,
            'burst_ratio': burst_ratio,
            'conn_worker_ratio': conn_worker_ratio,
            'reject_rate': reject_rate,
            'suspicious_workers': suspicious_workers,
            'threat_level': threat_level,  # 0=normal, 1=elevated, 2=warning, 3=critical
            'threat_reasons': threat_reasons,
            'banned_ips_count': 0,  # Banning not implemented in this version
            'banned_workers_count': 0,
            'limits': {
                'max_submissions_per_sec': MAX_SUBMISSIONS_PER_SECOND,
                'max_connections': 10000,
                'min_difficulty': 0.001,
                'max_connections_per_ip': 50,
            }
        }
    
    def get_ban_stats(self):
        """Get current ban statistics - stub for compatibility"""
        # Banning system is not implemented in this version
        return {
            'banned_ips_count': 0,
            'banned_workers_count': 0,
            'banned_ips': [],
            'banned_workers': [],
            'ip_violations': [],
            'ip_connections': dict(self.ip_connections),
            'ban_duration': 3600,
            'max_violations': 10,
        }


# Global pool statistics instance
pool_stats = PoolStatistics.get_instance()


class StratumRPCMiningProvider(object):
    def __init__(self, wb, other, transport):
        self.pool_version_mask = 0x1fffe000
        self.wb = wb
        self.other = other
        self.transport = transport
        
        self.username = None
        self.address = None  # Payout address extracted from username
        self.worker_ip = transport.getPeer().host if transport else None
        self.handler_map = expiring_dict.ExpiringDict(300)
        
        self.watch_id = self.wb.new_work_event.watch(self._send_work)

        self.recent_shares = []
        self.target = None
        self.share_rate = wb.share_rate
        self.fixed_target = False
        self.desired_pseudoshare_target = None
        self.merged_addresses = {}
        
        # Connection tracking
        self.conn_id = id(self)
        self.connection_time = time.time()
        pool_stats.register_connection(self.conn_id, self, self.worker_ip)
        
        # Per-connection statistics
        self.shares_submitted = 0
        self.shares_accepted = 0
        self.shares_rejected = 0

    
    def rpc_subscribe(self, miner_version=None, session_id=None, *args):
        reactor.callLater(0, self._send_work)
        
        return [
            ["mining.notify", "ae6812eb4cd7735a302a8a9dd95cf71f"], # subscription details
            "", # extranonce1
            self.wb.COINBASE_NONCE_LENGTH, # extranonce2_size
        ]
    
    def rpc_authorize(self, username, password):
        if not hasattr(self, 'authorized'): # authorize can be called many times in one connection
            print '>>>Authorize: %s from %s' % (username, self.transport.getPeer().host)
            self.authorized = username
        self.username = username.strip()
        
        self.user, self.address, self.desired_share_target, self.desired_pseudoshare_target, self.merged_addresses = self.wb.get_user_details(username)
        reactor.callLater(0, self._send_work)
        return True

    def rpc_configure(self, extensions, extensionParameters):
        #extensions is a list of extension codes defined in BIP310
        #extensionParameters is a dict of parameters for each extension code
        if 'version-rolling' in extensions:
            #mask from miner is mandatory but we dont use it
            miner_mask = extensionParameters['version-rolling.mask']
            #min-bit-count from miner is mandatory but we dont use it
            try:
                minbitcount = extensionParameters['version-rolling.min-bit-count']
            except:
                log.err("A miner tried to connect with a malformed version-rolling.min-bit-count parameter. This is probably a bug in your mining software. Braiins OS is known to have this bug. You should complain to them.")
                minbitcount = 2 # probably not needed
            #according to the spec, pool should return largest mask possible (to support mining proxies)
            return {"version-rolling" : True, "version-rolling.mask" : '{:08x}'.format(self.pool_version_mask&(int(miner_mask,16)))}
            #pool can send mining.set_version_mask at any time if the pool mask changes

        if 'minimum-difficulty' in extensions:
            print 'Extension method minimum-difficulty not implemented'
        if 'subscribe-extranonce' in extensions:
            print 'Extension method subscribe-extranonce not implemented'

    def _send_work(self):
        try:
            x, got_response = self.wb.get_work(*self.wb.preprocess_request('' if self.username is None else self.username))
        except:
            log.err()
            self.transport.loseConnection()
            return
        if self.desired_pseudoshare_target:
            self.fixed_target = True
            self.target = self.desired_pseudoshare_target
            self.target = max(self.target, int(x['bits'].target))
        else:
            self.fixed_target = False
            if self.target is None:
                # Initial target: start at the share_target (floor)
                self.target = x['share_target']
            # Enforce floor: don't let target be easier than min_share_target
            # (larger target value = easier difficulty)
            # But preserve harder targets that vardiff has set
            if self.target > x['min_share_target']:
                self.target = x['min_share_target']
        jobid = str(random.randrange(2**128))
        self.other.svc_mining.rpc_set_difficulty(bitcoin_data.target_to_difficulty(self.target)*self.wb.net.DUMB_SCRYPT_DIFF).addErrback(lambda err: None)
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
        self.handler_map[jobid] = x, got_response
    
    def rpc_submit(self, worker_name, job_id, extranonce2, ntime, nonce, version_bits = None, *args):
        #asicboost: version_bits is the version mask that the miner used
        worker_name = worker_name.strip()
        if job_id not in self.handler_map:
            print >>sys.stderr, '''Couldn't link returned work's job id with its handler. This should only happen if this process was recently restarted!'''
            #self.other.svc_client.rpc_reconnect().addErrback(lambda err: None)
            return False
        x, got_response = self.handler_map[job_id]
        coinb_nonce = extranonce2.decode('hex')
        # Debug: Uncomment to trace stratum share submission (prints on every share)
        # print >>sys.stderr, '[STRATUM DEBUG] extranonce2 raw: %s (len=%d)' % (extranonce2, len(extranonce2))
        # print >>sys.stderr, '[STRATUM DEBUG] coinb_nonce len: %d, expected: %d' % (len(coinb_nonce), self.wb.COINBASE_NONCE_LENGTH)
        # Pad or truncate to match expected length
        if len(coinb_nonce) < self.wb.COINBASE_NONCE_LENGTH:
            # print >>sys.stderr, '[STRATUM DEBUG] Padding coinb_nonce from %d to %d bytes' % (len(coinb_nonce), self.wb.COINBASE_NONCE_LENGTH)
            coinb_nonce = coinb_nonce + '\x00' * (self.wb.COINBASE_NONCE_LENGTH - len(coinb_nonce))
        elif len(coinb_nonce) > self.wb.COINBASE_NONCE_LENGTH:
            # print >>sys.stderr, '[STRATUM DEBUG] Truncating coinb_nonce from %d to %d bytes' % (len(coinb_nonce), self.wb.COINBASE_NONCE_LENGTH)
            coinb_nonce = coinb_nonce[:self.wb.COINBASE_NONCE_LENGTH]
        assert len(coinb_nonce) == self.wb.COINBASE_NONCE_LENGTH
        new_packed_gentx = x['coinb1'] + coinb_nonce + x['coinb2']

        # Debug: Print stratum's calculation
        stratum_coinbase_hash = bitcoin_data.hash256(new_packed_gentx)
        stratum_merkle_root = bitcoin_data.check_merkle_link(stratum_coinbase_hash, x['merkle_link'])
        # print >>sys.stderr, '[STRATUM DEBUG] coinb1 length: %d' % len(x['coinb1'])
        # print >>sys.stderr, '[STRATUM DEBUG] coinb2 length: %d' % len(x['coinb2'])
        # print >>sys.stderr, '[STRATUM DEBUG] coinb_nonce hex: %s' % coinb_nonce.encode('hex')
        # print >>sys.stderr, '[STRATUM DEBUG] new_packed_gentx length: %d' % len(new_packed_gentx)
        # print >>sys.stderr, '[STRATUM DEBUG] coinbase hash: %064x' % stratum_coinbase_hash
        # print >>sys.stderr, '[STRATUM DEBUG] merkle_link branch length: %d' % len(x['merkle_link']['branch'])
        # print >>sys.stderr, '[STRATUM DEBUG] calculated merkle_root: %064x' % stratum_merkle_root

        job_version = x['version']
        nversion = job_version
        #check if miner changed bits that they were not supposed to change
        if version_bits:
            if ((~self.pool_version_mask) & int(version_bits,16)) != 0:
                #todo: how to raise error back to miner?
                #protocol does not say error needs to be returned but ckpool returns
                #{"error": "Invalid version mask", "id": "id", "result":""}
                raise ValueError("Invalid version mask {0}".format(version_bits))
            nversion = (job_version & ~self.pool_version_mask) | (int(version_bits,16) & self.pool_version_mask)
            #nversion = nversion & int(version_bits,16)

        # Since coinb1/coinb2 are already in stripped format (tx_id_type),
        # hash256(new_packed_gentx) equals get_txid() of the transaction.
        # The miner computes the same hash, so merkle roots will match.
        coinbase_hash = bitcoin_data.hash256(new_packed_gentx)
        # print >>sys.stderr, '[STRATUM DEBUG] coinbase_hash (stripped): %064x' % coinbase_hash
        
        header = dict(
            version=nversion,
            previous_block=x['previous_block'],
            merkle_root=bitcoin_data.check_merkle_link(coinbase_hash, x['merkle_link']),
            timestamp=pack.IntType(32).unpack(getwork._swap4(ntime.decode('hex'))),
            bits=x['bits'],
            nonce=pack.IntType(32).unpack(getwork._swap4(nonce.decode('hex'))),
        )
        result = got_response(header, worker_name, coinb_nonce, self.target)
        
        # Track share submission statistics
        self.shares_submitted += 1
        current_diff = bitcoin_data.target_to_difficulty(self.target) if self.target else 1
        if result:
            self.shares_accepted += 1
            pool_stats.record_share(worker_name, current_diff, accepted=True)
        else:
            self.shares_rejected += 1
            pool_stats.record_share(worker_name, current_diff, accepted=False)

        # adjust difficulty on this stratum to target ~share_rate sec/pseudoshare
        if not self.fixed_target:
            self.recent_shares.append(time.time())
            if len(self.recent_shares) > 12 or (time.time() - self.recent_shares[0]) > 10*len(self.recent_shares)*self.share_rate:
                old_time = self.recent_shares[0]
                del self.recent_shares[0]
                olddiff = bitcoin_data.target_to_difficulty(self.target)
                # Widen adjustment range from 0.5-2x to 0.1-10x for faster convergence
                # This helps high-hashrate miners reach appropriate difficulty quickly
                ratio = (time.time() - old_time)/(len(self.recent_shares)*self.share_rate)
                self.target = int(self.target * clip(ratio, 0.1, 10.) + 0.5)
                newtarget = clip(self.target, self.wb.net.SANE_TARGET_RANGE[0], self.wb.net.SANE_TARGET_RANGE[1])
                if newtarget != self.target:
                    print "Clipping target from %064x to %064x" % (self.target, newtarget)
                    self.target = newtarget
                # Enforce floor: target cannot be easier than min_share_target
                # (larger target = easier, so use min to keep harder targets)
                if self.target > x['min_share_target']:
                    self.target = x['min_share_target']
                self.recent_shares = [time.time()]
                self._send_work()

        return result

    
    def close(self):
        self.wb.new_work_event.unwatch(self.watch_id)
        
        # Unregister connection from pool stats
        pool_stats.unregister_connection(self.conn_id, self.worker_ip)

class StratumProtocol(jsonrpc.LineBasedPeer):
    def connectionMade(self):
        self.svc_mining = StratumRPCMiningProvider(self.factory.wb, self.other, self.transport)
    
    def connectionLost(self, reason):
        self.svc_mining.close()

class StratumServerFactory(protocol.ServerFactory):
    protocol = StratumProtocol
    
    def __init__(self, wb):
        self.wb = wb
