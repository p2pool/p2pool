from __future__ import division

import base64
import gc
import json
import os
import random
import sys
import time
import signal
import traceback
import urlparse

if '--iocp' in sys.argv:
    from twisted.internet import iocpreactor
    iocpreactor.install()
from twisted.internet import defer, reactor, protocol, tcp
from twisted.web import server
from twisted.python import log
from nattraverso import portmapper, ipdiscover

import bitcoin.p2p as bitcoin_p2p, bitcoin.data as bitcoin_data
from bitcoin import stratum, worker_interface, helper
from util import fixargparse, jsonrpc, variable, deferral, math, logging, switchprotocol
from util.telegram import TelegramNotifier
from . import networks, web, work
import p2pool, p2pool.data as p2pool_data, p2pool.node as p2pool_node

class keypool():
    keys = []
    keyweights = []
    stamp = time.time()
    payouttotal = 0.0

    def addkey(self, n):
        self.keys.append(n)
        self.keyweights.append(random.uniform(0,100.0))
    def delkey(self, n):
        try:
            i=self.keys.index(n)
            self.keys.pop(i)
            self.keyweights.pop(i)
        except:
            pass

    def weighted(self):
        choice=random.uniform(0,sum(self.keyweights))
        tot = 0.0
        ind = 0
        for i in (self.keyweights):
            tot += i
            if tot >= choice:
                return ind
            ind += 1
        return ind

    def popleft(self):
        if (len(self.keys) > 0):
            dummyval=self.keys.pop(0)
        if (len(self.keyweights) > 0):
            dummyval=self.keyweights.pop(0)

    def updatestamp(self, n):
        self.stamp = n

    def paytotal(self):
        self.payouttotal = 0.0
        for i in xrange(len(pubkeys.keys)):
            self.payouttotal += node.get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(pubkeys.keys[i]), 0)*1e-8
        return self.payouttotal

    def getpaytotal(self):
        return self.payouttotal


@defer.inlineCallbacks
def main(args, net, datadir_path, merged_urls, worker_endpoint, telegram_notifier=None):
    try:
        print 'p2pool (version %s)' % (p2pool.__version__,)
        print
        
        @defer.inlineCallbacks
        def connect_p2p():
            # connect to coind over dash-p2p
            print '''Testing coind P2P connection to '%s:%s'...''' % (args.coind_address, args.coind_p2p_port)
            factory = bitcoin_p2p.ClientFactory(net.PARENT)
            reactor.connectTCP(args.coind_address, args.coind_p2p_port, factory)
            def long():
                print '''    ...taking a while. Common reasons for this include all of coind's connection slots being used...'''
            long_dc = reactor.callLater(5, long)
            yield factory.getProtocol() # waits until handshake is successful
            if not long_dc.called: long_dc.cancel()
            print '    ...success!'
            print
            defer.returnValue(factory)
        
        if args.testnet: # establish p2p connection first if testnet so coind can work without connections
            factory = yield connect_p2p()
        
        # connect to coind over JSON-RPC and do initial getmemorypool
        url = '%s://%s:%i/' % ('https' if args.coind_rpc_ssl else 'http', args.coind_address, args.coind_rpc_port)
        print '''Testing coind RPC connection to '%s' with username '%s'...''' % (url, args.coind_rpc_username)
        coind = jsonrpc.HTTPProxy(url, dict(Authorization='Basic ' + base64.b64encode(args.coind_rpc_username + ':' + args.coind_rpc_password)), timeout=30)
        yield helper.check(coind, net)
        temp_work = yield helper.getwork(coind, net)
        
        coind_getnetworkinfo_var = variable.Variable(None)
        @defer.inlineCallbacks
        def poll_warnings():
            coind_getnetworkinfo_var.set((yield deferral.retry('Error while calling getnetworkinfo:')(coind.rpc_getnetworkinfo)()))
        yield poll_warnings()
        deferral.RobustLoopingCall(poll_warnings).start(20*60)
        
        print '    ...success!'
        print '    Current block hash: %x' % (temp_work['previous_block'],)
        print '    Current block height: %i' % (temp_work['height'] - 1,)
        print
        
        if not args.testnet:
            factory = yield connect_p2p()
        
        print 'Determining payout address...'
        pubkeys = keypool()
        if args.pubkey_hash is None and args.address != 'dynamic':
            address_path = os.path.join(datadir_path, 'cached_payout_address')
            
            if os.path.exists(address_path):
                with open(address_path, 'rb') as f:
                    address = f.read().strip('\r\n')
                print '    Loaded cached address: %s...' % (address,)
            else:
                address = None
            
            if address is not None:
                res = yield deferral.retry('Error validating cached address:', 5)(lambda: coind.rpc_validateaddress(address))()
                if not res['isvalid'] or not res['ismine']:
                    print '    Cached address is either invalid or not controlled by local coind!'
                    address = None
            
            if address is None:
                print '    Getting payout address from coind...'
                address = yield deferral.retry('Error getting payout address from coind:', 5)(lambda: coind.rpc_getaccountaddress('p2pool'))()
            
            with open(address_path, 'wb') as f:
                f.write(address)
            
            my_pubkey_hash = bitcoin_data.address_to_pubkey_hash(address, net.PARENT)
            print '    ...success! Payout address:', bitcoin_data.pubkey_hash_to_address(my_pubkey_hash, net.PARENT)
            print
            pubkeys.addkey(my_pubkey_hash)
        elif args.address != 'dynamic':
            my_pubkey_hash = args.pubkey_hash
            print '    ...success! Payout address:', bitcoin_data.pubkey_hash_to_address(my_pubkey_hash, net.PARENT)
            print
            pubkeys.addkey(my_pubkey_hash)
        else:
            print '    Entering dynamic address mode.'

            if args.numaddresses < 2:
                print ' ERROR: Can not use fewer than 2 addresses in dynamic mode. Resetting to 2.'
                args.numaddresses = 2
                keys = []
                keyweights = []
                stamp = time.time()
                payouttotal = 0.0

                def addkey(self, n):
                    self.keys.append(n)
                    self.keyweights.append(random.uniform(0,100.0))
                def delkey(self, n):
                    try:
                        i=self.keys.index(n)
                        self.keys.pop(i)
                        self.keyweights.pop(i)
                    except:
                        pass

                def weighted(self):
                    choice=random.uniform(0,sum(self.keyweights))
                    tot = 0.0
                    ind = 0
                    for i in (self.keyweights):
                        tot += i
                        if tot >= choice:
                            return ind
                        ind += 1
                    return ind

                def popleft(self):
                    if (len(self.keys) > 0):
                        dummyval=self.keys.pop(0)
                    if (len(self.keyweights) > 0):
                        dummyval=self.keyweights.pop(0)

                def updatestamp(self, n):
                    self.stamp = n

                def paytotal(self):
                    self.payouttotal = 0.0
                    for i in xrange(len(pubkeys.keys)):
                        self.payouttotal += node.get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(pubkeys.keys[i]), 0)*1e-8
                    return self.payouttotal

                def getpaytotal(self):
                    return self.payouttotal

            pubkeys = keypool()
            for i in xrange(args.numaddresses):
                address = yield deferral.retry('Error getting a dynamic address from coind:', 5)(lambda: coind.rpc_getnewaddress('p2pool'))()
                new_pubkey = bitcoin_data.address_to_pubkey_hash(address, net.PARENT)
                pubkeys.addkey(new_pubkey)

            pubkeys.updatestamp(time.time())

            my_pubkey_hash = pubkeys.keys[0]

            for i in xrange(len(pubkeys.keys)):
                print '    ...payout %d: %s' % (i, bitcoin_data.pubkey_hash_to_address(pubkeys.keys[i], net.PARENT),)
        
        print "Loading shares..."
        shares = {}
        known_verified = set()
        last_print_time = [time.time()]
        last_count = [0]
        def share_cb(share):
            share.time_seen = 0 # XXX
            shares[share.hash] = share
            count = len(shares)
            now = time.time()
            elapsed = now - last_print_time[0]
            # Print every 1000 shares, OR every 100 shares if >10000 loaded, OR every 5 seconds
            if (count % 1000 == 0 or 
                (count > 10000 and count % 100 == 0) or 
                (elapsed > 5.0)):
                if count > 0:
                    # If triggered by timeout and very few shares loaded, indicate slow processing
                    if elapsed > 5.0 and (count - last_count[0]) < 50:
                        print "    %i (validating complex shares...)" % (count,)
                    else:
                        print "    %i" % (count,)
                    last_print_time[0] = now
                    last_count[0] = count
        ss = p2pool_data.ShareStore(os.path.join(datadir_path, 'shares.'), net, share_cb, known_verified.add)
        print "    ...done loading %i shares (%i verified)!" % (len(shares), len(known_verified))
        print
        
        
        print 'Initializing work...'
        print '    Building share chain graph from %i shares...' % (len(shares),)
        
        node = p2pool_node.Node(factory, coind, shares.values(), known_verified, net)
        yield node.start()
        
        print '    ...share chain initialized!'
        print
        
        for share_hash in shares:
            if share_hash not in node.tracker.items:
                ss.forget_share(share_hash)
        for share_hash in known_verified:
            if share_hash not in node.tracker.verified.items:
                ss.forget_verified_share(share_hash)
        node.tracker.removed.watch(lambda share: ss.forget_share(share.hash))
        node.tracker.verified.removed.watch(lambda share: ss.forget_verified_share(share.hash))
        
        # Create archive directory for old shares
        archive_dir = os.path.join(datadir_path, 'share_archive')
        if not os.path.exists(archive_dir):
            os.makedirs(archive_dir)
        
        # Migration backup directory (one-time use)
        migration_backup_dir = os.path.join(datadir_path, 'pre_archival_backup')
        migration_flag = os.path.join(datadir_path, '.archival_migration_done')
        
        def create_migration_backup():
            """One-time backup before first archival operation"""
            import time
            import shutil
            import glob
            
            # Check if migration already done
            if os.path.exists(migration_flag):
                return True  # Already migrated
            
            try:
                print 'Creating one-time migration backup before archival...'
                
                # Create backup directory
                if not os.path.exists(migration_backup_dir):
                    os.makedirs(migration_backup_dir)
                
                # Find all pickle files
                pickle_pattern = os.path.join(datadir_path, net.NAME, 'shares.*')
                pickle_files = glob.glob(pickle_pattern)
                
                if not pickle_files:
                    print '  No pickle files to backup'
                    # Still mark as done
                    with open(migration_flag, 'w') as f:
                        f.write('Migration completed: %s\n' % time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
                        f.write('No pickle files found\n')
                    return True
                
                # Copy each pickle file
                backed_up = 0
                total_size = 0
                for pickle_file in pickle_files:
                    if os.path.exists(pickle_file):
                        backup_path = os.path.join(migration_backup_dir, os.path.basename(pickle_file))
                        shutil.copy2(pickle_file, backup_path)
                        backed_up += 1
                        total_size += os.path.getsize(pickle_file)
                
                # Create restoration script
                restore_script = os.path.join(migration_backup_dir, 'restore_backup.sh')
                with open(restore_script, 'w') as f:
                    f.write('#!/bin/bash\n')
                    f.write('# P2Pool Share Backup Restoration Script\n')
                    f.write('# Created: %s\n\n' % time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
                    f.write('set -e\n\n')
                    f.write('echo "WARNING: This will restore your shares to pre-archival state"\n')
                    f.write('echo "Press Ctrl+C to cancel, or Enter to continue..."\n')
                    f.write('read\n\n')
                    f.write('# Stop p2pool if running\n')
                    f.write('echo "Stopping p2pool..."\n')
                    f.write('pkill -f "python.*run_p2pool.py" || true\n')
                    f.write('sleep 2\n\n')
                    f.write('# Restore files\n')
                    f.write('echo "Restoring pickle files..."\n')
                    f.write('cp -v "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"/shares.* "%s/"\n\n' % os.path.join(datadir_path, net.NAME))
                    f.write('# Remove migration flag to allow re-migration\n')
                    f.write('rm -f "%s"\n\n' % migration_flag)
                    f.write('echo "Restoration complete! You can now restart p2pool."\n')
                os.chmod(restore_script, 0755)
                
                # Create manifest
                manifest_path = os.path.join(migration_backup_dir, 'BACKUP_INFO.txt')
                with open(manifest_path, 'w') as f:
                    f.write('P2Pool Pre-Archival Migration Backup\n')
                    f.write('====================================\n\n')
                    f.write('Created: %s\n' % time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
                    f.write('Files backed up: %d\n' % backed_up)
                    f.write('Total size: %.2f MB\n' % (total_size / 1048576.0))
                    f.write('Chain height: %d\n' % (node.tracker.get_height(node.best_share_var.value) if node.best_share_var.value else 0))
                    f.write('Shares in tracker: %d\n\n' % len(node.tracker.items))
                    f.write('Backup files:\n')
                    for pickle_file in sorted(pickle_files):
                        if os.path.exists(pickle_file):
                            f.write('  %s (%d bytes)\n' % (os.path.basename(pickle_file), os.path.getsize(pickle_file)))
                    f.write('\nTo restore this backup:\n')
                    f.write('  1. Stop p2pool\n')
                    f.write('  2. Run: %s\n' % restore_script)
                    f.write('  3. Restart p2pool\n\n')
                    f.write('Or manually:\n')
                    f.write('  cp %s/shares.* %s/\n' % (migration_backup_dir, os.path.join(datadir_path, net.NAME)))
                    f.write('  rm %s\n' % migration_flag)
                
                print '  Backup created: %s' % migration_backup_dir
                print '  Files: %d (%.2f MB)' % (backed_up, total_size / 1048576.0)
                print '  Restore script: %s' % restore_script
                
                # Mark migration as done
                with open(migration_flag, 'w') as f:
                    f.write('Archival migration completed: %s\n' % time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
                    f.write('Backup location: %s\n' % migration_backup_dir)
                    f.write('Files backed up: %d\n' % backed_up)
                    f.write('Total size: %.2f MB\n' % (total_size / 1048576.0))
                
                print '  Migration backup complete!'
                return True
            except Exception as e:
                print 'Warning: Failed to create migration backup: %s' % str(e)
                print '  Continuing anyway - archival will proceed without backup'
                return False
        
        def archive_old_shares(reason='periodic'):
            """Archive old shares to file and remove from storage"""
            import time
            
            current_height = node.tracker.get_height(node.best_share_var.value) if node.best_share_var.value else 0
            save_height = min(current_height, 2*net.CHAIN_LENGTH)
            
            # Build set of shares we want to keep
            shares_to_keep = set()
            for share in node.tracker.get_chain(node.best_share_var.value, save_height):
                shares_to_keep.add(share.hash)
            
            # Find old shares to archive - ss.known is dict of filename -> (share_hashes, verified_hashes)
            all_stored_hashes = set()
            for filename, (share_hashes, verified_hashes) in ss.known.iteritems():
                all_stored_hashes.update(share_hashes)
            
            shares_to_archive = all_stored_hashes - shares_to_keep
            
            if not shares_to_archive:
                return 0
            
            # Create archive file with timestamp
            archive_filename = os.path.join(archive_dir, 'shares_%d.txt' % int(time.time()))
            
            archived_count = 0
            try:
                with open(archive_filename, 'w') as archive_file:
                    archive_file.write('# P2Pool Share Archive - Created: %s\n' % time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
                    archive_file.write('# Reason: %s\n' % reason)
                    archive_file.write('# Chain height: %d, Shares in active chain: %d\n' % (current_height, len(shares_to_keep)))
                    archive_file.write('# Format: share_hash timestamp verified\n\n')
                    
                    for share_hash in shares_to_archive:
                        # Get share from tracker if available (has metadata)
                        if share_hash in node.tracker.items:
                            share = node.tracker.items[share_hash]
                            verified = 'verified' if share_hash in node.tracker.verified.items else 'unverified'
                            archive_file.write('%064x %d %s\n' % (share_hash, share.timestamp, verified))
                        else:
                            # Share not in tracker, just record the hash
                            archive_file.write('%064x - unknown\n' % share_hash)
                        archived_count += 1
                        
                        # Remove from active storage (disk)
                        # Note: Shares remain in tracker memory until clean_tracker() prunes them
                        ss.forget_share(share_hash)
                
                if archived_count > 0:
                    print 'Archived %d old shares to %s (%s)' % (archived_count, os.path.basename(archive_filename), reason)
            except Exception as e:
                print 'Warning: Failed to archive shares: %s' % str(e)
            
            return archived_count
        
        startup_archive_done = [False]  # Mutable flag to track if startup archival happened
        
        def rebuild_share_storage():
            """Force complete rebuild of share storage files (removes archived shares from disk)"""
            import glob
            
            current_height = node.tracker.get_height(node.best_share_var.value) if node.best_share_var.value else 0
            save_height = min(current_height, 2*net.CHAIN_LENGTH)
            
            # Get ALL shares from tracker that are within depth limit
            # This includes main chain + orphans/side chains
            shares_to_keep = []
            for share_hash, share in node.tracker.items.iteritems():
                # Check if share is within reasonable depth from best share
                try:
                    height = node.tracker.get_height(share_hash)
                    if height >= current_height - save_height:
                        shares_to_keep.append(share)
                except:
                    # If we can't get height, it's disconnected - skip it
                    pass
            
            # Delete all existing pickle files
            pickle_pattern = os.path.join(datadir_path, net.NAME, 'shares.*')
            pickle_files = glob.glob(pickle_pattern)
            for pickle_file in pickle_files:
                try:
                    os.remove(pickle_file)
                except Exception as e:
                    print 'Warning: Failed to remove %s: %s' % (pickle_file, e)
            
            # Clear ShareStore internal state
            ss.known.clear()
            ss.known_desired.clear()
            
            # Rebuild with all active shares (main chain + recent orphans)
            for share in shares_to_keep:
                ss.add_share(share)
                if share.hash in node.tracker.verified.items:
                    ss.add_verified_hash(share.hash)
            
            print 'Rebuilt storage with %d shares (from %d in tracker)' % (len(shares_to_keep), len(node.tracker.items))
        
        def persist_shares():
            """Save current shares to disk without archiving"""
            current_height = node.tracker.get_height(node.best_share_var.value) if node.best_share_var.value else 0
            save_height = min(current_height, 2*net.CHAIN_LENGTH)
            
            # Build set of shares we want to keep and save them
            shares_to_keep = set()
            for share in node.tracker.get_chain(node.best_share_var.value, save_height):
                shares_to_keep.add(share.hash)
                ss.add_share(share)
                if share.hash in node.tracker.verified.items:
                    ss.add_verified_hash(share.hash)
        
        def save_shares():
            """Save current shares and archive old ones (periodic)"""
            # First persist current shares
            persist_shares()
            
            # Then archive old shares (skip first call if startup archival just ran)
            if startup_archive_done[0]:
                startup_archive_done[0] = False  # Reset flag
                return  # Skip first periodic call to avoid double-archival
            archive_old_shares('periodic')
        
        # STARTUP OPTIMIZATION: Archive old shares immediately
        # This prevents keeping orphaned/old shares in memory that will be archived anyway
        print 'Checking for old shares to archive on startup...'
        current_height = node.tracker.get_height(node.best_share_var.value) if node.best_share_var.value else 0
        if current_height > 2*net.CHAIN_LENGTH:
            # ONE-TIME MIGRATION BACKUP: Create backup before first archival
            create_migration_backup()
            
            archived = archive_old_shares('startup cleanup')
            if archived > 0:
                print 'Startup optimization: archived %d old shares' % archived
                print 'Note: Shares removed from disk storage (pickle files will be cleaned by periodic saves)'
                print 'Note: Shares remain in memory until naturally pruned by clean_tracker()'
                
                startup_archive_done[0] = True  # Set flag to skip next periodic call
        else:
            print 'Chain height %d <= 2*CHAIN_LENGTH (%d), no archival needed yet' % (current_height, 2*net.CHAIN_LENGTH)
        
        # Start periodic save (every 60 seconds)
        deferral.RobustLoopingCall(save_shares).start(60)
        
        # Register graceful shutdown handler
        def shutdown_handler():
            """Archive shares on graceful shutdown"""
            print 'Graceful shutdown: archiving shares...'
            try:
                save_shares()  # Final save and archive
                print 'Shutdown archival complete'
            except Exception as e:
                print 'Warning: Shutdown archival failed: %s' % str(e)
        
        # Register with reactor stop event
        reactor.addSystemEventTrigger('before', 'shutdown', shutdown_handler)
        
        print '    ...success!'
        print
        
        
        print 'Joining p2pool network using port %i...' % (args.p2pool_port,)
        
        @defer.inlineCallbacks
        def parse(host):
            port = net.P2P_PORT
            if ':' in host:
                host, port_str = host.split(':')
                port = int(port_str)
            defer.returnValue(((yield reactor.resolve(host)), port))
        
        addrs = {}
        if os.path.exists(os.path.join(datadir_path, 'addrs')):
            try:
                with open(os.path.join(datadir_path, 'addrs'), 'rb') as f:
                    addrs.update(dict((tuple(k), v) for k, v in json.loads(f.read())))
            except:
                print >>sys.stderr, 'error parsing addrs'
        # Skip bootstrap in solo mode (PERSIST=False) - no sharechain to sync
        bootstrap_addrs = net.BOOTSTRAP_ADDRS if net.PERSIST else []
        for addr_df in map(parse, bootstrap_addrs):
            try:
                addr = yield addr_df
                if addr not in addrs:
                    addrs[addr] = (0, time.time(), time.time())
            except Exception as e:
                # DNS lookup failures for bootstrap nodes are expected - just log briefly
                if 'DNS' in str(type(e).__name__) or 'DNS' in str(e):
                    pass  # Silently skip DNS failures for bootstrap nodes
                else:
                    log.err()
        
        connect_addrs = set()
        for addr_df in map(parse, args.p2pool_nodes):
            try:
                connect_addrs.add((yield addr_df))
            except Exception as e:
                # DNS lookup failures should be logged but not as full tracebacks
                if 'DNS' in str(type(e).__name__) or 'DNS' in str(e):
                    print 'Warning: DNS lookup failed for p2pool node'
                else:
                    log.err()
        
        node.p2p_node = p2pool_node.P2PNode(node,
            port=args.p2pool_port,
            max_incoming_conns=args.p2pool_conns,
            addr_store=addrs,
            connect_addrs=connect_addrs,
            desired_outgoing_conns=args.p2pool_outgoing_conns,
            advertise_ip=args.advertise_ip,
            external_ip=args.p2pool_external_ip,
        )
        node.p2p_node.start()
        
        def save_addrs():
            with open(os.path.join(datadir_path, 'addrs'), 'wb') as f:
                f.write(json.dumps(node.p2p_node.addr_store.items()))
        deferral.RobustLoopingCall(save_addrs).start(60)
        
        print '    ...success!'
        print
        
        if args.upnp:
            @defer.inlineCallbacks
            def upnp_thread():
                while True:
                    try:
                        is_lan, lan_ip = yield ipdiscover.get_local_ip()
                        if is_lan:
                            pm = yield portmapper.get_port_mapper()
                            yield pm._upnp.add_port_mapping(lan_ip, args.p2pool_port, args.p2pool_port, 'p2pool', 'TCP')
                    except defer.TimeoutError:
                        pass
                    except:
                        if p2pool.DEBUG:
                            log.err(None, 'UPnP error:')
                    yield deferral.sleep(random.expovariate(1/120))
            upnp_thread()
        
        # start listening for workers with a JSON-RPC server
        
        print 'Listening for workers on %r port %i...' % (worker_endpoint[0], worker_endpoint[1])
        
        wb = work.WorkerBridge(node, my_pubkey_hash, args.donation_percentage, merged_urls, args.worker_fee, args, pubkeys, coind)
        web_root, record_block_found, get_last_block_info = web.get_web_root(wb, datadir_path, coind_getnetworkinfo_var, static_dir=args.web_static)
        caching_wb = worker_interface.CachingWorkerBridge(wb)
        worker_interface.WorkerInterface(caching_wb).attach_to(web_root, get_handler=lambda request: request.redirect('/static/'))
        web_serverfactory = server.Site(web_root)
        
        
        serverfactory = switchprotocol.FirstByteSwitchFactory({'{': stratum.StratumServerFactory(caching_wb, net)}, web_serverfactory)
        deferral.retry('Error binding to worker port:', traceback=False)(reactor.listenTCP)(worker_endpoint[1], serverfactory, interface=worker_endpoint[0])
        
        with open(os.path.join(os.path.join(datadir_path, 'ready_flag')), 'wb') as f:
            pass
        
        print '    ...success!'
        print
        
        # Hook block recording for accurate luck calculation and Telegram notifications
        # (telegram_notifier already initialized earlier for error reporting)
        @defer.inlineCallbacks
        def on_verified_share(share):
            """Record block finds with hashrate data and send Telegram notification."""
            if share.pow_hash <= share.header['bits'].target:
                # This is a block! Record it with current hashrate
                block_hash = '%064x' % share.header_hash
                try:
                    block_height = p2pool_data.parse_bip0034(share.share_data['coinbase'])[0]
                except Exception:
                    block_height = 0
                share_hash = '%064x' % share.hash
                miner_address = bitcoin_data.script2_to_address(share.new_script, net.PARENT)
                explorer_url = net.PARENT.BLOCK_EXPLORER_URL_PREFIX + block_hash
                
                # Get previous block info for luck calculation BEFORE recording this block
                prev_block = get_last_block_info()
                
                # Get pool hashrate and network difficulty
                pool_hashrate = None
                network_diff = None
                try:
                    height = node.tracker.get_height(node.best_share_var.value)
                    if height >= 2:
                        lookbehind = min(height, 3600 // net.SHARE_PERIOD)
                        if lookbehind >= 2:
                            raw_hashrate = p2pool_data.get_pool_attempts_per_second(
                                node.tracker, node.best_share_var.value, lookbehind)
                            stale_prop = p2pool_data.get_average_stale_prop(
                                node.tracker, node.best_share_var.value, lookbehind)
                            pool_hashrate = raw_hashrate / (1 - stale_prop) if stale_prop < 1 else raw_hashrate
                    # Get network difficulty
                    if node.coind_work.value and 'bits' in node.coind_work.value:
                        network_diff = bitcoin_data.target_to_difficulty(node.coind_work.value['bits'].target)
                except Exception:
                    pass
                
                # Record block for luck calculation
                record_block_found(block_hash, block_height, share_hash, miner_address, share.timestamp)
                
                # Calculate and log luck
                luck_str = ''
                if prev_block and pool_hashrate and network_diff:
                    try:
                        actual_time = share.timestamp - prev_block['ts']
                        if actual_time > 0:
                            # Use average of previous and current hashrate if available
                            prev_hashrate = prev_block.get('pool_hashrate')
                            if prev_hashrate:
                                avg_hashrate = (prev_hashrate + pool_hashrate) / 2
                            else:
                                avg_hashrate = pool_hashrate
                            
                            expected_time = (network_diff * 2**32) / avg_hashrate
                            luck = (expected_time / actual_time) * 100
                            
                            luck_str = ' Luck: %.1f%% (found in %s, expected %s)' % (
                                luck,
                                math.format_dt(actual_time),
                                math.format_dt(expected_time)
                            )
                    except Exception as e:
                        if p2pool.DEBUG:
                            print 'Error calculating luck: %s' % str(e)
                elif pool_hashrate and network_diff:
                    # First block or no previous block data - just show expected time
                    try:
                        expected_time = (network_diff * 2**32) / pool_hashrate
                        luck_str = ' (expected time to block: %s)' % math.format_dt(expected_time)
                    except Exception:
                        pass
                
                # Print luck info
                if luck_str:
                    print 'BLOCK LUCK:%s' % luck_str
                
                # Send Telegram notification (don't block on this)
                if telegram_notifier is not None and telegram_notifier.is_configured():
                    try:
                        yield telegram_notifier.announce_block_found(
                            net_name=net.NAME,
                            block_height=block_height,
                            block_hash=block_hash,
                            miner_address=miner_address,
                            explorer_url=explorer_url,
                            pool_hashrate=pool_hashrate
                        )
                    except Exception as e:
                        print 'Telegram notification error: %s' % str(e)
        
        node.tracker.verified.added.watch(on_verified_share)
        print 'Block recording for luck calculation enabled'
        
        # done!
        print 'Started successfully!'
        print 'Go to http://127.0.0.1:%i/ to view graphs and statistics!' % (worker_endpoint[1],)
        if args.donation_percentage > 1.1:
            print '''Donating %.1f%% of work towards P2Pool's development. Thanks for the tip!''' % (args.donation_percentage,)
        elif args.donation_percentage < .9:
            print '''Donating %.1f%% of work towards P2Pool's development. Please donate to encourage further development of P2Pool!''' % (args.donation_percentage,)
        else:
            print '''Donating %.1f%% of work towards P2Pool's development. Thank you!''' % (args.donation_percentage,)
            print 'You can increase this amount with --give-author argument! (or decrease it, if you must)'
        print
        
        
        if hasattr(signal, 'SIGALRM'):
            signal.signal(signal.SIGALRM, lambda signum, frame: reactor.callFromThread(
                sys.stderr.write, 'Watchdog timer went off at:\n' + ''.join(traceback.format_stack())
            ))
            signal.siginterrupt(signal.SIGALRM, False)
            deferral.RobustLoopingCall(signal.alarm, 30).start(1)
        
        # DEPRECATED: IRC announcements - use Telegram instead (telegram_config.json)
        # Kept for backwards compatibility but Freenode is largely defunct
        if args.irc_announce:
            print 'WARNING: IRC announcements are deprecated. Use Telegram instead (configure telegram_config.json)'
            from twisted.words.protocols import irc
            class IRCClient(irc.IRCClient):
                nickname = 'p2pool%02i' % (random.randrange(100),)
                channel = net.ANNOUNCE_CHANNEL
                def lineReceived(self, line):
                    if p2pool.DEBUG:
                        print repr(line)
                    irc.IRCClient.lineReceived(self, line)
                def signedOn(self):
                    self.in_channel = False
                    irc.IRCClient.signedOn(self)
                    self.factory.resetDelay()
                    self.join(self.channel)
                    @defer.inlineCallbacks
                    def new_share(share):
                        if not self.in_channel:
                            return
                        if share.pow_hash <= share.header['bits'].target and abs(share.timestamp - time.time()) < 10*60:
                            yield deferral.sleep(random.expovariate(1/60))
                            message = '\x02%s BLOCK FOUND by %s! %s%064x' % (net.NAME.upper(), bitcoin_data.script2_to_address(share.new_script, net.PARENT), net.PARENT.BLOCK_EXPLORER_URL_PREFIX, share.header_hash)
                            if all('%x' % (share.header_hash,) not in old_message for old_message in self.recent_messages):
                                self.say(self.channel, message)
                                self._remember_message(message)
                    self.watch_id = node.tracker.verified.added.watch(new_share)
                    self.recent_messages = []
                def joined(self, channel):
                    self.in_channel = True
                def left(self, channel):
                    self.in_channel = False
                def _remember_message(self, message):
                    self.recent_messages.append(message)
                    while len(self.recent_messages) > 100:
                        self.recent_messages.pop(0)
                def privmsg(self, user, channel, message):
                    if channel == self.channel:
                        self._remember_message(message)
                def connectionLost(self, reason):
                    node.tracker.verified.added.unwatch(self.watch_id)
                    print 'IRC connection lost:', reason.getErrorMessage()
            class IRCClientFactory(protocol.ReconnectingClientFactory):
                protocol = IRCClient
            reactor.connectTCP("irc.freenode.net", 6667, IRCClientFactory(), bindAddress=(worker_endpoint[0], 0))
        
        @defer.inlineCallbacks
        def status_thread():
            last_str = None
            last_time = 0
            while True:
                yield deferral.sleep(3)
                try:
                    height = node.tracker.get_height(node.best_share_var.value)
                    this_str = 'P2Pool: %i shares in chain (%i verified/%i total) Peers: %i (%i incoming)' % (
                        height,
                        len(node.tracker.verified.items),
                        len(node.tracker.items),
                        len(node.p2p_node.peers),
                        sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
                    ) + (' FDs: %i R/%i W' % (len(reactor.getReaders()), len(reactor.getWriters())) if p2pool.DEBUG else '')
                    
                    datums, dt = wb.local_rate_monitor.get_datums_in_last()
                    my_att_s = sum(datum['work']/dt for datum in datums)
                    my_shares_per_s = sum(datum['work']/dt/bitcoin_data.target_to_average_attempts(datum['share_target']) for datum in datums)
                    
                    # Get worker/miner info
                    miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
                    num_workers = len(miner_hash_rates)
                    
                    this_str += '\n Local: %sH/s in last %s Workers: %i Local dead on arrival: %s Expected time to share: %s' % (
                        math.format(int(my_att_s)),
                        math.format_dt(dt),
                        num_workers,
                        math.format_binomial_conf(sum(1 for datum in datums if datum['dead']), len(datums), 0.95),
                        math.format_dt(1/my_shares_per_s) if my_shares_per_s else '???',
                    )
                    
                    if height > 2:
                        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()
                        stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, min(60*60//net.SHARE_PERIOD, height))
                        real_att_s = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, min(height - 1, 60*60//net.SHARE_PERIOD)) / (1 - stale_prop)
                        
                        paystr = ''
                        paytot = 0.0
                        for i in xrange(len(pubkeys.keys)):
                            curtot = node.get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(pubkeys.keys[i]), 0)
                            paytot += curtot*1e-8
                            paystr += "(%.4f)" % (curtot*1e-8,)
                        paystr += "=%.4f" % (paytot,)
                        this_str += '\n Shares: %i (%i orphan, %i dead) Stale rate: %s Efficiency: %s Current payout: %s %s' % (
                            shares, stale_orphan_shares, stale_doa_shares,
                            math.format_binomial_conf(stale_orphan_shares + stale_doa_shares, shares, 0.95),
                            math.format_binomial_conf(stale_orphan_shares + stale_doa_shares, shares, 0.95, lambda x: (1 - x)/(1 - stale_prop)),
                            paystr, net.PARENT.SYMBOL,
                        )
                        this_str += '\n Pool: %sH/s Stale rate: %.1f%% Expected time to block: %s' % (
                            math.format(int(real_att_s)),
                            100*stale_prop,
                            math.format_dt(2**256 / node.coind_work.value['bits'].target / real_att_s),
                        )
                        
                        for warning in p2pool_data.get_warnings(node.tracker, node.best_share_var.value, net, coind_getnetworkinfo_var.value, node.coind_work.value):
                            print >>sys.stderr, '#'*40
                            print >>sys.stderr, '>>> Warning: ' + warning
                            print >>sys.stderr, '#'*40
                        
                        if gc.garbage:
                            print '%i pieces of uncollectable cyclic garbage! Types: %r' % (len(gc.garbage), map(type, gc.garbage))
                    
                    if this_str != last_str or time.time() > last_time + 15:
                        print this_str
                        last_str = this_str
                        last_time = time.time()
                except:
                    log.err()
        status_thread()
    except:
        reactor.stop()
        log.err(None, 'Fatal error:')

def run():
    if not hasattr(tcp.Client, 'abortConnection'):
        print "Twisted doesn't have abortConnection! Upgrade to a newer version of Twisted to avoid memory leaks!"
        print 'Pausing for 3 seconds...'
        time.sleep(3)
    
    # Include all networks (Dash, Litecoin testnet, Dogecoin testnet, etc.)
    realnets = dict((name, net) for name, net in networks.nets.iteritems())
    
    parser = fixargparse.FixedArgumentParser(description='p2pool (version %s)' % (p2pool.__version__,), fromfile_prefix_chars='@')
    parser.add_argument('--version', action='version', version=p2pool.__version__)
    parser.add_argument('--net',
        help='use specified network (default: dash)',
        action='store', choices=sorted(realnets), default='dash', dest='net_name')
    parser.add_argument('--testnet',
        help='''use the network's testnet''',
        action='store_const', const=True, default=False, dest='testnet')
    parser.add_argument('--debug',
        help='enable debugging mode',
        action='store_const', const=True, default=False, dest='debug')
    parser.add_argument('--bench',
        help='enable benchmarking mode (print performance timing info)',
        action='store_const', const=True, default=False, dest='bench')
    parser.add_argument('-a', '--address',
        help='generate payouts to this address (default: <address requested from coind>), or (dynamic)',
        type=str, action='store', default=None, dest='address')
    parser.add_argument('-i', '--numaddresses',
        help='number of dash auto-generated addresses to maintain for getwork dynamic address allocation',
        type=int, action='store', default=2, dest='numaddresses')
    parser.add_argument('-t', '--timeaddresses',
        help='seconds between acquisition of new address and removal of single old (default: 2 days or 172800s)',
        type=int, action='store', default=172800, dest='timeaddresses')
    parser.add_argument('--datadir',
        help='store data in this directory (default: <directory run_p2pool.py is in>/data)',
        type=str, action='store', default=None, dest='datadir')
    parser.add_argument('--logfile',
        help='''log to this file (default: data/<NET>/log)''',
        type=str, action='store', default=None, dest='logfile')
    parser.add_argument('--web-static',
        help='use an alternative web frontend in this directory (otherwise use the built-in frontend)',
        type=str, action='store', default=None, dest='web_static')
    parser.add_argument('--web-password', metavar='USERNAME:PASSWORD',
        help='enable HTTP Basic Authentication for web interface (format: username:password)',
        type=str, action='store', default=None, dest='web_password')
    parser.add_argument('--merged',
        help='call getauxblock on this url to get work for merged mining (example: http://ncuser:ncpass@127.0.0.1:10332/)',
        type=str, action='append', default=[], dest='merged_urls')
    parser.add_argument('--give-author', metavar='DONATION_PERCENTAGE',
        help='donate this percentage of work towards the development of p2pool (default: 1.0)',
        type=float, action='store', default=1.0, dest='donation_percentage')
    parser.add_argument('--iocp',
        help='use Windows IOCP API in order to avoid errors due to large number of sockets being open',
        action='store_true', default=False, dest='iocp')
    parser.add_argument('--irc-announce',
        help='[DEPRECATED] use Telegram instead (configure telegram_config.json)',
        action='store_true', default=False, dest='irc_announce')
    parser.add_argument('--no-bugreport',
        help='disable error reporting (errors sent to Telegram if configured with error_notifications=true)',
        action='store_true', default=False, dest='no_bugreport')
    
    p2pool_group = parser.add_argument_group('p2pool interface')
    p2pool_group.add_argument('--p2pool-port', metavar='PORT',
        help='use port PORT to listen for connections (forward this port from your router!) (default: %s)' % ', '.join('%s:%i' % (name, net.P2P_PORT) for name, net in sorted(realnets.items())),
        type=int, action='store', default=None, dest='p2pool_port')
    p2pool_group.add_argument('-n', '--p2pool-node', metavar='ADDR[:PORT]',
        help='connect to existing p2pool node at ADDR listening on port PORT (defaults to default p2pool P2P port) in addition to builtin addresses',
        type=str, action='append', default=[], dest='p2pool_nodes')
    parser.add_argument('--disable-upnp',
        help='''don't attempt to use UPnP to forward p2pool's P2P port from the Internet to this computer''',
        action='store_false', default=True, dest='upnp')
    p2pool_group.add_argument('--max-conns', metavar='CONNS',
        help='maximum incoming connections (default: 40)',
        type=int, action='store', default=40, dest='p2pool_conns')
    p2pool_group.add_argument('--outgoing-conns', metavar='CONNS',
        help='outgoing connections (default: 6)',
        type=int, action='store', default=6, dest='p2pool_outgoing_conns')
    p2pool_group.add_argument('--external-ip', metavar='ADDR[:PORT]',
        help='specify your own public IP address instead of asking peers to discover it, useful for running dual WAN or asymmetric routing',
        type=str, action='store', default=None, dest='p2pool_external_ip')
    parser.add_argument('--disable-advertise',
        help='''don't advertise local IP address as being available for incoming connections. useful for running a dark node, along with multiple -n ADDR's and --outgoing-conns 0''',
        action='store_false', default=True, dest='advertise_ip')
    
    worker_group = parser.add_argument_group('worker interface')
    worker_group.add_argument('-w', '--worker-port', metavar='PORT or ADDR:PORT',
        help='listen on PORT on interface with ADDR for RPC connections from miners (default: all interfaces, %s)' % ', '.join('%s:%i' % (name, net.WORKER_PORT) for name, net in sorted(realnets.items())),
        type=str, action='store', default=None, dest='worker_endpoint')
    worker_group.add_argument('-f', '--fee', metavar='FEE_PERCENTAGE',
        help='''charge workers mining to their own dash address (by setting their miner's username to a dash address) this percentage fee to mine on your p2pool instance. Amount displayed at http://127.0.0.1:WORKER_PORT/fee (default: 0)''',
        type=float, action='store', default=0, dest='worker_fee')
    worker_group.add_argument('-s', '--share-rate', metavar='SECONDS_PER_SHARE',
        help='Auto-adjust stratum mining difficulty on each connection to target this many seconds per pseudoshare (default: 10)',
        type=float, action='store', default=10., dest='share_rate')
    
    coind_group = parser.add_argument_group('coind interface')
    coind_group.add_argument('--coind-config-path', metavar='COIND_CONFIG_PATH',
        help='custom configuration file path (when coind -conf option used)',
        type=str, action='store', default=None, dest='coind_config_path')
    coind_group.add_argument('--coind-address', metavar='COIND_ADDRESS',
        help='connect to this address (default: 127.0.0.1)',
        type=str, action='store', default='127.0.0.1', dest='coind_address')
    coind_group.add_argument('--coind-rpc-port', metavar='COIND_RPC_PORT',
        help='''connect to JSON-RPC interface at this port (default: %s <read from dash.conf if password not provided>)''' % ', '.join('%s:%i' % (name, net.PARENT.RPC_PORT) for name, net in sorted(realnets.items())),
        type=int, action='store', default=None, dest='coind_rpc_port')
    coind_group.add_argument('--coind-rpc-ssl',
        help='connect to JSON-RPC interface using SSL',
        action='store_true', default=False, dest='coind_rpc_ssl')
    coind_group.add_argument('--coind-p2p-port', metavar='COIND_P2P_PORT',
        help='''connect to P2P interface at this port (default: %s <read from dash.conf if password not provided>)''' % ', '.join('%s:%i' % (name, net.PARENT.P2P_PORT) for name, net in sorted(realnets.items())),
        type=int, action='store', default=None, dest='coind_p2p_port')
    
    coind_group.add_argument(metavar='COIND_RPCUSERPASS',
        help='coind RPC interface username, then password, space-separated (only one being provided will cause the username to default to being empty, and none will cause P2Pool to read them from dash.conf)',
        type=str, action='store', default=[], nargs='*', dest='coind_rpc_userpass')
    
    args = parser.parse_args()
    
    if args.debug:
        p2pool.DEBUG = True
        defer.setDebugging(True)
    else:
        p2pool.DEBUG = False
    
    if args.bench:
        p2pool.BENCH = True
    else:
        p2pool.BENCH = False
    
    net_name = args.net_name + ('_testnet' if args.testnet else '')
    net = networks.nets[net_name]
    
    datadir_path = os.path.join((os.path.join(os.path.dirname(sys.argv[0]), 'data') if args.datadir is None else args.datadir), net_name)
    if not os.path.exists(datadir_path):
        os.makedirs(datadir_path)
    
    # Initialize security config and handle web password
    from p2pool.util import security_config
    sec_config = security_config.security_config
    sec_config.set_datadir(datadir_path)
    
    if args.web_password:
        if ':' not in args.web_password:
            parser.error('--web-password must be in format username:password')
        username, password = args.web_password.split(':', 1)
        sec_config.set_web_password(username, password)
        print 'Web interface password protection enabled for user: %s' % username
    
    if len(args.coind_rpc_userpass) > 2:
        parser.error('a maximum of two arguments are allowed')
    args.coind_rpc_username, args.coind_rpc_password = ([None, None] + args.coind_rpc_userpass)[-2:]
    
    if args.coind_rpc_password is None:
        conf_path = args.coind_config_path or net.PARENT.CONF_FILE_FUNC()
        if not os.path.exists(conf_path):
            parser.error('''dash configuration file not found. Manually enter your RPC password.\r\n'''
                '''If you actually haven't created a configuration file, you should create one at %s with the text:\r\n'''
                '''\r\n'''
                '''server=1\r\n'''
                '''rpcpassword=%x\r\n'''
                '''\r\n'''
                '''Keep that password secret! After creating the file, restart dash.''' % (conf_path, random.randrange(2**128)))
        conf = open(conf_path, 'rb').read()
        contents = {}
        for line in conf.splitlines(True):
            if '#' in line:
                line = line[:line.index('#')]
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            contents[k.strip()] = v.strip()
        for conf_name, var_name, var_type in [
            ('rpcuser', 'coind_rpc_username', str),
            ('rpcpassword', 'coind_rpc_password', str),
            ('rpcport', 'coind_rpc_port', int),
            ('port', 'coind_p2p_port', int),
        ]:
            if getattr(args, var_name) is None and conf_name in contents:
                setattr(args, var_name, var_type(contents[conf_name]))
        if 'rpcssl' in contents and contents['rpcssl'] != '0':
                args.coind_rpc_ssl = True
        if args.coind_rpc_password is None:
            parser.error('''dash configuration file didn't contain an rpcpassword= line! Add one!''')
    
    if args.coind_rpc_username is None:
        args.coind_rpc_username = ''
    
    if args.coind_rpc_port is None:
        args.coind_rpc_port = net.PARENT.RPC_PORT
    
    if args.coind_p2p_port is None:
        args.coind_p2p_port = net.PARENT.P2P_PORT
    
    if args.p2pool_port is None:
        args.p2pool_port = net.P2P_PORT
    
    if args.p2pool_outgoing_conns > 10:
        parser.error('''--outgoing-conns can't be more than 10''')
    
    if args.worker_endpoint is None:
        worker_endpoint = '', net.WORKER_PORT
    elif ':' not in args.worker_endpoint:
        worker_endpoint = '', int(args.worker_endpoint)
    else:
        addr, port = args.worker_endpoint.rsplit(':', 1)
        worker_endpoint = addr, int(port)
    
    if args.address is not None and args.address != 'dynamic':
        try:
            args.pubkey_hash = bitcoin_data.address_to_pubkey_hash(args.address, net.PARENT)
        except Exception as e:
            parser.error('error parsing address: ' + repr(e))
    else:
        args.pubkey_hash = None
    
    def separate_url(url):
        s = urlparse.urlsplit(url)
        if '@' not in s.netloc:
            parser.error('merged url netloc must contain an "@"')
        userpass, new_netloc = s.netloc.rsplit('@', 1)
        return urlparse.urlunsplit(s._replace(netloc=new_netloc)), userpass
    merged_urls = map(separate_url, args.merged_urls)
    
    if args.logfile is None:
        args.logfile = os.path.join(datadir_path, 'log')
    
    logfile = logging.LogFile(args.logfile)
    pipe = logging.TimestampingPipe(logging.TeePipe([logging.EncodeReplacerPipe(sys.stderr), logfile]))
    sys.stdout = logging.AbortPipe(pipe)
    sys.stderr = log.DefaultObserver.stderr = logging.AbortPipe(logging.PrefixPipe(pipe, '> '))
    if hasattr(signal, "SIGUSR1"):
        def sigusr1(signum, frame):
            print 'Caught SIGUSR1, closing %r...' % (args.logfile,)
            logfile.reopen()
            print '...and reopened %r after catching SIGUSR1.' % (args.logfile,)
        signal.signal(signal.SIGUSR1, sigusr1)
    deferral.RobustLoopingCall(logfile.reopen).start(5)
    
    class ErrorReporter(object):
        def __init__(self, telegram_notifier):
            self.last_sent = None
            self.telegram = telegram_notifier
        
        def emit(self, eventDict):
            if not eventDict["isError"]:
                return
            
            if self.last_sent is not None and time.time() < self.last_sent + 30:
                return  # Rate limit to once per 30 seconds
            self.last_sent = time.time()
            
            if 'failure' in eventDict:
                text = ((eventDict.get('why') or 'Unhandled Error')
                    + '\n' + eventDict['failure'].getTraceback())
            else:
                text = " ".join([str(m) for m in eventDict["message"]]) + "\n"
            
            # Add version and network info
            error_header = 'P2Pool %s (%s)\n\n' % (p2pool.__version__, net.NAME)
            error_text = error_header + text
            
            # Send to Telegram if configured (non-blocking)
            if self.telegram and self.telegram.is_configured():
                self.telegram.send_error_notification(error_text, error_type='Error')
    
    # Initialize Telegram notifier early for error reporting
    telegram_notifier = TelegramNotifier(datadir_path, net.NAME)
    
    if not args.no_bugreport:
        log.addObserver(ErrorReporter(telegram_notifier).emit)
    
    # Filter out benign OpenSSL import errors and DNS lookup failures from Twisted
    original_observer = log.theLogPublisher.observers[0] if log.theLogPublisher.observers else None
    def filter_openssl_errors(eventDict):
        # Check for OpenSSL ImportError or DNS failures in failure or isError events
        if eventDict.get('isError'):
            msg = eventDict.get('message', '')
            why = eventDict.get('why', '')
            failure = eventDict.get('failure')
            
            # Build text to check from all available sources
            check_text = str(msg) + str(why)
            if failure:
                check_text += failure.getTraceback()
            
            # Suppress OpenSSL import errors from twisted.web (HTTPS redirect issue)
            if 'No module named OpenSSL' in check_text:
                return  # Suppress this error
            
            # Suppress DNS lookup failures for bootstrap nodes (expected when nodes are down)
            if 'DNSLookupError' in check_text or 'DNS lookup failed' in check_text:
                return  # Suppress DNS failures
        
        if original_observer:
            original_observer(eventDict)
    
    if original_observer:
        log.removeObserver(original_observer)
        log.addObserver(filter_openssl_errors)
    
    reactor.callWhenRunning(main, args, net, datadir_path, merged_urls, worker_endpoint, telegram_notifier)
    reactor.run()
