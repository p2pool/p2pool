from __future__ import division

import ConfigParser
import StringIO
import base64
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
from twisted.internet import defer, reactor, protocol, task
from twisted.web import server
from twisted.python import log
from nattraverso import portmapper, ipdiscover

import bitcoin.p2p as bitcoin_p2p, bitcoin.getwork as bitcoin_getwork, bitcoin.data as bitcoin_data
from bitcoin import worker_interface, height_tracker
from util import expiring_dict, fixargparse, jsonrpc, variable, deferral, math, logging, pack
from . import p2p, networks, web
import p2pool, p2pool.data as p2pool_data

@deferral.retry('Error getting work from bitcoind:', 3)
@defer.inlineCallbacks
def getwork(bitcoind):
    try:
        work = yield bitcoind.rpc_getmemorypool()
    except jsonrpc.Error, e:
        if e.code == -32601: # Method not found
            print >>sys.stderr, 'Error: Bitcoin version too old! Upgrade to v0.5 or newer!'
            raise deferral.RetrySilentlyException()
        raise
    packed_transactions = [x.decode('hex') for x in work['transactions']]
    defer.returnValue(dict(
        version=work['version'],
        previous_block_hash=int(work['previousblockhash'], 16),
        transactions=map(bitcoin_data.tx_type.unpack, packed_transactions),
        merkle_link=bitcoin_data.calculate_merkle_link([None] + map(bitcoin_data.hash256, packed_transactions), 0),
        subsidy=work['coinbasevalue'],
        time=work['time'],
        bits=bitcoin_data.FloatingIntegerType().unpack(work['bits'].decode('hex')[::-1]) if isinstance(work['bits'], (str, unicode)) else bitcoin_data.FloatingInteger(work['bits']),
        coinbaseflags=work['coinbaseflags'].decode('hex') if 'coinbaseflags' in work else ''.join(x.decode('hex') for x in work['coinbaseaux'].itervalues()) if 'coinbaseaux' in work else '',
    ))

class WorkerBridge(worker_interface.WorkerBridge):
    def __init__(self, lp_signal, my_pubkey_hash, net, donation_percentage, current_work, tracker, my_share_hashes, my_doa_share_hashes, worker_fee, p2p_node, submit_block, compute_work, shared_share_hashes):
        worker_interface.WorkerBridge.__init__(self)
        self.new_work_event = lp_signal
        self.recent_shares_ts_work = []
        
        self.my_pubkey_hash = my_pubkey_hash
        self.net = net
        self.donation_percentage = donation_percentage
        self.current_work = current_work
        self.tracker = tracker
        self.my_share_hashes = my_share_hashes
        self.my_doa_share_hashes = my_doa_share_hashes
        self.worker_fee = worker_fee
        self.p2p_node = p2p_node
        self.submit_block = submit_block
        self.compute_work = compute_work
        self.shared_share_hashes = shared_share_hashes
        
        self.pseudoshare_received = variable.Event()
        self.share_received = variable.Event()
        self.local_rate_monitor = math.RateMonitor(10*60)
        
        self.removed_unstales_var = variable.Variable((0, 0, 0))
        self.removed_doa_unstales_var = variable.Variable(0)
        
        @tracker.verified.removed.watch
        def _(share):
            if share.hash in self.my_share_hashes and tracker.is_child_of(share.hash, self.current_work.value['best_share_hash']):
                assert share.share_data['stale_info'] in [None, 'orphan', 'doa'] # we made these shares in this instance
                self.removed_unstales_var.set((
                    self.removed_unstales_var.value[0] + 1,
                    self.removed_unstales_var.value[1] + (1 if share.share_data['stale_info'] == 'orphan' else 0),
                    self.removed_unstales_var.value[2] + (1 if share.share_data['stale_info'] == 'doa' else 0),
                ))
            if share.hash in self.my_doa_share_hashes and self.tracker.is_child_of(share.hash, self.current_work.value['best_share_hash']):
                self.removed_doa_unstales_var.set(self.removed_doa_unstales_var.value + 1)
    
    def get_stale_counts(self):
        '''Returns (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain)'''
        my_shares = len(self.my_share_hashes)
        my_doa_shares = len(self.my_doa_share_hashes)
        delta = self.tracker.verified.get_delta_to_last(self.current_work.value['best_share_hash'])
        my_shares_in_chain = delta.my_count + self.removed_unstales_var.value[0]
        my_doa_shares_in_chain = delta.my_doa_count + self.removed_doa_unstales_var.value
        orphans_recorded_in_chain = delta.my_orphan_announce_count + self.removed_unstales_var.value[1]
        doas_recorded_in_chain = delta.my_dead_announce_count + self.removed_unstales_var.value[2]
        
        my_shares_not_in_chain = my_shares - my_shares_in_chain
        my_doa_shares_not_in_chain = my_doa_shares - my_doa_shares_in_chain
        
        return (my_shares_not_in_chain - my_doa_shares_not_in_chain, my_doa_shares_not_in_chain), my_shares, (orphans_recorded_in_chain, doas_recorded_in_chain)
    
    def get_user_details(self, request):
        user = request.getUser() if request.getUser() is not None else ''
        
        desired_pseudoshare_target = None
        if '+' in user:
            user, desired_pseudoshare_difficulty_str = user.rsplit('+', 1)
            try:
                desired_pseudoshare_target = bitcoin_data.difficulty_to_target(float(desired_pseudoshare_difficulty_str))
            except:
                pass
        
        desired_share_target = 2**256 - 1
        if '/' in user:
            user, min_diff_str = user.rsplit('/', 1)
            try:
                desired_share_target = bitcoin_data.difficulty_to_target(float(min_diff_str))
            except:
                pass
        
        if random.uniform(0, 100) < self.worker_fee:
            pubkey_hash = self.my_pubkey_hash
        else:
            try:
                pubkey_hash = bitcoin_data.address_to_pubkey_hash(user, self.net.PARENT)
            except: # XXX blah
                pubkey_hash = self.my_pubkey_hash
        
        return user, pubkey_hash, desired_share_target, desired_pseudoshare_target
    
    def preprocess_request(self, request):
        user, pubkey_hash, desired_share_target, desired_pseudoshare_target = self.get_user_details(request)
        return pubkey_hash, desired_share_target, desired_pseudoshare_target
    
    def get_work(self, pubkey_hash, desired_share_target, desired_pseudoshare_target):
        if len(self.p2p_node.peers) == 0 and self.net.PERSIST:
            raise jsonrpc.Error(-12345, u'p2pool is not connected to any peers')
        if self.current_work.value['best_share_hash'] is None and self.net.PERSIST:
            raise jsonrpc.Error(-12345, u'p2pool is downloading shares')
        if time.time() > self.current_work.value['last_update'] + 60:
            raise jsonrpc.Error(-12345, u'lost contact with bitcoind')
        
        if self.current_work.value['mm_chains']:
            tree, size = bitcoin_data.make_auxpow_tree(self.current_work.value['mm_chains'])
            mm_hashes = [self.current_work.value['mm_chains'].get(tree.get(i), dict(hash=0))['hash'] for i in xrange(size)]
            mm_data = '\xfa\xbemm' + bitcoin_data.aux_pow_coinbase_type.pack(dict(
                merkle_root=bitcoin_data.merkle_hash(mm_hashes),
                size=size,
                nonce=0,
            ))
            mm_later = [(aux_work, mm_hashes.index(aux_work['hash']), mm_hashes) for chain_id, aux_work in self.current_work.value['mm_chains'].iteritems()]
        else:
            mm_data = ''
            mm_later = []
        
        if True:
            share_info, generate_tx = p2pool_data.Share.generate_transaction(
                tracker=self.tracker,
                share_data=dict(
                    previous_share_hash=self.current_work.value['best_share_hash'],
                    coinbase=(mm_data + self.current_work.value['coinbaseflags'])[:100],
                    nonce=random.randrange(2**32),
                    pubkey_hash=pubkey_hash,
                    subsidy=self.current_work.value['subsidy'],
                    donation=math.perfect_round(65535*self.donation_percentage/100),
                    stale_info=(lambda (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain):
                        'orphan' if orphans > orphans_recorded_in_chain else
                        'doa' if doas > doas_recorded_in_chain else
                        None
                    )(*self.get_stale_counts()),
                    desired_version=3,
                ),
                block_target=self.current_work.value['bits'].target,
                desired_timestamp=int(time.time() - self.current_work.value['clock_offset']),
                desired_target=desired_share_target,
                ref_merkle_link=dict(branch=[], index=0),
                net=self.net,
            )
        
        if desired_pseudoshare_target is None:
            target = 2**256-1
            if len(self.recent_shares_ts_work) == 50:
                hash_rate = sum(work for ts, work in self.recent_shares_ts_work[1:])//(self.recent_shares_ts_work[-1][0] - self.recent_shares_ts_work[0][0])
                if hash_rate:
                    target = min(target, int(2**256/hash_rate))
        else:
            target = desired_pseudoshare_target
        target = max(target, share_info['bits'].target)
        for aux_work in self.current_work.value['mm_chains'].itervalues():
            target = max(target, aux_work['target'])
        target = math.clip(target, self.net.PARENT.SANE_TARGET_RANGE)
        
        transactions = [generate_tx] + list(self.current_work.value['transactions'])
        packed_generate_tx = bitcoin_data.tx_type.pack(generate_tx)
        merkle_root = bitcoin_data.check_merkle_link(bitcoin_data.hash256(packed_generate_tx), self.current_work.value['merkle_link'])
        
        getwork_time = time.time()
        merkle_link = self.current_work.value['merkle_link']
        
        print 'New work for worker! Difficulty: %.06f Share difficulty: %.06f Total block value: %.6f %s including %i transactions' % (
            bitcoin_data.target_to_difficulty(target),
            bitcoin_data.target_to_difficulty(share_info['bits'].target),
            self.current_work.value['subsidy']*1e-8, self.net.PARENT.SYMBOL,
            len(self.current_work.value['transactions']),
        )
        
        bits = self.current_work.value['bits']
        previous_block = self.current_work.value['previous_block']
        ba = bitcoin_getwork.BlockAttempt(
            version=self.current_work.value['version'],
            previous_block=self.current_work.value['previous_block'],
            merkle_root=merkle_root,
            timestamp=self.current_work.value['time'],
            bits=self.current_work.value['bits'],
            share_target=target,
        )
        
        received_header_hashes = set()
        
        def got_response(header, request):
            header_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(header))
            pow_hash = self.net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(header))
            try:
                if pow_hash <= header['bits'].target or p2pool.DEBUG:
                    self.submit_block(dict(header=header, txs=transactions), ignore_failure=False)
                    if pow_hash <= header['bits'].target:
                        print
                        print 'GOT BLOCK FROM MINER! Passing to bitcoind! %s%064x' % (self.net.PARENT.BLOCK_EXPLORER_URL_PREFIX, header_hash)
                        print
            except:
                log.err(None, 'Error while processing potential block:')
            
            user, _, _, _ = self.get_user_details(request)
            assert header['merkle_root'] == merkle_root
            assert header['previous_block'] == previous_block
            assert header['bits'] == bits
            
            on_time = self.current_work.value['best_share_hash'] == share_info['share_data']['previous_share_hash']
            
            for aux_work, index, hashes in mm_later:
                try:
                    if pow_hash <= aux_work['target'] or p2pool.DEBUG:
                        df = deferral.retry('Error submitting merged block: (will retry)', 10, 10)(aux_work['merged_proxy'].rpc_getauxblock)(
                            pack.IntType(256, 'big').pack(aux_work['hash']).encode('hex'),
                            bitcoin_data.aux_pow_type.pack(dict(
                                merkle_tx=dict(
                                    tx=transactions[0],
                                    block_hash=header_hash,
                                    merkle_link=merkle_link,
                                ),
                                merkle_link=bitcoin_data.calculate_merkle_link(hashes, index),
                                parent_block_header=header,
                            )).encode('hex'),
                        )
                        @df.addCallback
                        def _(result):
                            if result != (pow_hash <= aux_work['target']):
                                print >>sys.stderr, 'Merged block submittal result: %s Expected: %s' % (result, pow_hash <= aux_work['target'])
                            else:
                                print 'Merged block submittal result: %s' % (result,)
                        @df.addErrback
                        def _(err):
                            log.err(err, 'Error submitting merged block:')
                except:
                    log.err(None, 'Error while processing merged mining POW:')
            
            if pow_hash <= share_info['bits'].target and header_hash not in received_header_hashes:
                min_header = dict(header);del min_header['merkle_root']
                hash_link = p2pool_data.prefix_to_hash_link(packed_generate_tx[:-32-4], p2pool_data.Share.gentx_before_refhash)
                share = p2pool_data.Share(self.net, None, dict(
                    min_header=min_header, share_info=share_info, hash_link=hash_link,
                    ref_merkle_link=dict(branch=[], index=0),
                ), merkle_link=merkle_link, other_txs=transactions[1:] if pow_hash <= header['bits'].target else None)
                
                print 'GOT SHARE! %s %s prev %s age %.2fs%s' % (
                    request.getUser(),
                    p2pool_data.format_hash(share.hash),
                    p2pool_data.format_hash(share.previous_hash),
                    time.time() - getwork_time,
                    ' DEAD ON ARRIVAL' if not on_time else '',
                )
                self.my_share_hashes.add(share.hash)
                if not on_time:
                    self.my_doa_share_hashes.add(share.hash)
                
                self.tracker.add(share)
                if not p2pool.DEBUG:
                    self.tracker.verified.add(share)
                self.compute_work()
                
                try:
                    if pow_hash <= header['bits'].target or p2pool.DEBUG:
                        for peer in self.p2p_node.peers.itervalues():
                            peer.sendShares([share])
                        self.shared_share_hashes.add(share.hash)
                except:
                    log.err(None, 'Error forwarding block solution:')
                
                self.share_received.happened(bitcoin_data.target_to_average_attempts(share.target), not on_time)
            
            if pow_hash > target:
                print 'Worker %s submitted share with hash > target:' % (request.getUser(),)
                print '    Hash:   %56x' % (pow_hash,)
                print '    Target: %56x' % (target,)
            elif header_hash in received_header_hashes:
                print >>sys.stderr, 'Worker %s @ %s submitted share more than once!' % (request.getUser(), request.getClientIP())
            else:
                received_header_hashes.add(header_hash)
                
                self.pseudoshare_received.happened(bitcoin_data.target_to_average_attempts(target), not on_time, user)
                self.recent_shares_ts_work.append((time.time(), bitcoin_data.target_to_average_attempts(target)))
                while len(self.recent_shares_ts_work) > 50:
                    self.recent_shares_ts_work.pop(0)
                self.local_rate_monitor.add_datum(dict(work=bitcoin_data.target_to_average_attempts(target), dead=not on_time, user=user))
            
            return on_time
        
        return ba, got_response

@defer.inlineCallbacks
def main(args, net, datadir_path, merged_urls, worker_endpoint):
    try:
        print 'p2pool (version %s)' % (p2pool.__version__,)
        print
        
        # connect to bitcoind over JSON-RPC and do initial getmemorypool
        url = 'http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port)
        print '''Testing bitcoind RPC connection to '%s' with username '%s'...''' % (url, args.bitcoind_rpc_username)
        bitcoind = jsonrpc.Proxy(url, dict(Authorization='Basic ' + base64.b64encode(args.bitcoind_rpc_username + ':' + args.bitcoind_rpc_password)), timeout=30)
        @deferral.retry('Error while checking Bitcoin connection:', 1)
        @defer.inlineCallbacks
        def check():
            if not (yield net.PARENT.RPC_CHECK)(bitcoind):
                print >>sys.stderr, "    Check failed! Make sure that you're connected to the right bitcoind with --bitcoind-rpc-port!"
                raise deferral.RetrySilentlyException()
            temp_work = yield getwork(bitcoind)
            if not net.VERSION_CHECK((yield bitcoind.rpc_getinfo())['version'], temp_work):
                print >>sys.stderr, '    Bitcoin version too old! BIP16 support required! Upgrade to 0.6.0rc4 or greater!'
                raise deferral.RetrySilentlyException()
            defer.returnValue(temp_work)
        temp_work = yield check()
        
        block_height_var = variable.Variable(None)
        @defer.inlineCallbacks
        def poll_height():
            block_height_var.set((yield deferral.retry('Error while calling getblockcount:')(bitcoind.rpc_getblockcount)()))
        yield poll_height()
        task.LoopingCall(poll_height).start(60*60)
        
        print '    ...success!'
        print '    Current block hash: %x' % (temp_work['previous_block_hash'],)
        print '    Current block height: %i' % (block_height_var.value,)
        print
        
        # connect to bitcoind over bitcoin-p2p
        print '''Testing bitcoind P2P connection to '%s:%s'...''' % (args.bitcoind_address, args.bitcoind_p2p_port)
        factory = bitcoin_p2p.ClientFactory(net.PARENT)
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        yield factory.getProtocol() # waits until handshake is successful
        print '    ...success!'
        print
        
        print 'Determining payout address...'
        if args.pubkey_hash is None:
            address_path = os.path.join(datadir_path, 'cached_payout_address')
            
            if os.path.exists(address_path):
                with open(address_path, 'rb') as f:
                    address = f.read().strip('\r\n')
                print '    Loaded cached address: %s...' % (address,)
            else:
                address = None
            
            if address is not None:
                res = yield deferral.retry('Error validating cached address:', 5)(lambda: bitcoind.rpc_validateaddress(address))()
                if not res['isvalid'] or not res['ismine']:
                    print '    Cached address is either invalid or not controlled by local bitcoind!'
                    address = None
            
            if address is None:
                print '    Getting payout address from bitcoind...'
                address = yield deferral.retry('Error getting payout address from bitcoind:', 5)(lambda: bitcoind.rpc_getaccountaddress('p2pool'))()
            
            with open(address_path, 'wb') as f:
                f.write(address)
            
            my_pubkey_hash = bitcoin_data.address_to_pubkey_hash(address, net.PARENT)
        else:
            my_pubkey_hash = args.pubkey_hash
        print '    ...success! Payout address:', bitcoin_data.pubkey_hash_to_address(my_pubkey_hash, net.PARENT)
        print
        
        my_share_hashes = set()
        my_doa_share_hashes = set()
        
        tracker = p2pool_data.OkayTracker(net, my_share_hashes, my_doa_share_hashes)
        shared_share_hashes = set()
        ss = p2pool_data.ShareStore(os.path.join(datadir_path, 'shares.'), net)
        known_verified = set()
        print "Loading shares..."
        for i, (mode, contents) in enumerate(ss.get_shares()):
            if mode == 'share':
                if contents.hash in tracker.shares:
                    continue
                shared_share_hashes.add(contents.hash)
                contents.time_seen = 0
                tracker.add(contents)
                if len(tracker.shares) % 1000 == 0 and tracker.shares:
                    print "    %i" % (len(tracker.shares),)
            elif mode == 'verified_hash':
                known_verified.add(contents)
            else:
                raise AssertionError()
        print "    ...inserting %i verified shares..." % (len(known_verified),)
        for h in known_verified:
            if h not in tracker.shares:
                ss.forget_verified_share(h)
                continue
            tracker.verified.add(tracker.shares[h])
        print "    ...done loading %i shares!" % (len(tracker.shares),)
        print
        tracker.removed.watch(lambda share: ss.forget_share(share.hash))
        tracker.verified.removed.watch(lambda share: ss.forget_verified_share(share.hash))
        tracker.removed.watch(lambda share: shared_share_hashes.discard(share.hash))
        
        print 'Initializing work...'
        
        
        # BITCOIND WORK
        
        bitcoind_work = variable.Variable(None)
        
        @defer.inlineCallbacks
        def poll_bitcoind():
            work = yield getwork(bitcoind)
            bitcoind_work.set(dict(
                version=work['version'],
                previous_block=work['previous_block_hash'],
                bits=work['bits'],
                coinbaseflags=work['coinbaseflags'],
                time=work['time'],
                transactions=work['transactions'],
                merkle_link=work['merkle_link'],
                subsidy=work['subsidy'],
                clock_offset=time.time() - work['time'],
                last_update=time.time(),
            ))
        yield poll_bitcoind()
        
        @defer.inlineCallbacks
        def work_poller():
            while True:
                flag = factory.new_block.get_deferred()
                try:
                    yield poll_bitcoind()
                except:
                    log.err()
                yield defer.DeferredList([flag, deferral.sleep(15)], fireOnOneCallback=True)
        work_poller()
        
        # PEER WORK
        
        best_block_header = variable.Variable(None)
        def handle_header(new_header):
            # check that header matches current target
            if not (net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(new_header)) <= bitcoind_work.value['bits'].target):
                return
            bitcoind_best_block = bitcoind_work.value['previous_block']
            if (best_block_header.value is None
                or (
                    new_header['previous_block'] == bitcoind_best_block and
                    bitcoin_data.hash256(bitcoin_data.block_header_type.pack(best_block_header.value)) == bitcoind_best_block
                ) # new is child of current and previous is current
                or (
                    bitcoin_data.hash256(bitcoin_data.block_header_type.pack(new_header)) == bitcoind_best_block and
                    best_block_header.value['previous_block'] != bitcoind_best_block
                )): # new is current and previous is not a child of current
                best_block_header.set(new_header)
        @defer.inlineCallbacks
        def poll_header():
            handle_header((yield factory.conn.value.get_block_header(bitcoind_work.value['previous_block'])))
        bitcoind_work.changed.watch(lambda _: poll_header())
        yield poll_header()
        
        # MERGED WORK
        
        merged_work = variable.Variable({})
        
        @defer.inlineCallbacks
        def set_merged_work(merged_url, merged_userpass):
            merged_proxy = jsonrpc.Proxy(merged_url, dict(Authorization='Basic ' + base64.b64encode(merged_userpass)))
            while True:
                auxblock = yield deferral.retry('Error while calling merged getauxblock:', 1)(merged_proxy.rpc_getauxblock)()
                merged_work.set(dict(merged_work.value, **{auxblock['chainid']: dict(
                    hash=int(auxblock['hash'], 16),
                    target=pack.IntType(256).unpack(auxblock['target'].decode('hex')),
                    merged_proxy=merged_proxy,
                )}))
                yield deferral.sleep(1)
        for merged_url, merged_userpass in merged_urls:
            set_merged_work(merged_url, merged_userpass)
        
        @merged_work.changed.watch
        def _(new_merged_work):
            print 'Got new merged mining work!'
        
        # COMBINE WORK
        
        current_work = variable.Variable(None)
        
        get_height_rel_highest = yield height_tracker.get_height_rel_highest_func(bitcoind, factory, lambda: bitcoind_work.value['previous_block'], net)
        requested = expiring_dict.ExpiringDict(300)
        peer_heads = expiring_dict.ExpiringDict(300) # hash -> peers that know of it
        def compute_work():
            best, desired = tracker.think(get_height_rel_highest, bitcoind_work.value['previous_block'], bitcoind_work.value['bits'])
            
            t = dict(bitcoind_work.value)
            
            if (best_block_header.value is not None and
            best_block_header.value['previous_block'] == t['previous_block'] and
            net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(best_block_header.value)) <= t['bits'].target):
                print 'Skipping from block %x to block %x!' % (best_block_header.value['previous_block'],
                    bitcoin_data.hash256(bitcoin_data.block_header_type.pack(best_block_header.value)))
                t = dict(
                    version=best_block_header.value['version'],
                    previous_block=bitcoin_data.hash256(bitcoin_data.block_header_type.pack(best_block_header.value)),
                    bits=best_block_header.value['bits'], # not always true
                    coinbaseflags='',
                    time=best_block_header.value['timestamp'] + 600, # better way?
                    transactions=[],
                    merkle_link=bitcoin_data.calculate_merkle_link([None], 0),
                    subsidy=net.PARENT.SUBSIDY_FUNC(block_height_var.value),
                    clock_offset=current_work.value['clock_offset'],
                    last_update=current_work.value['last_update'],
                )
            
            t['best_share_hash'] = best
            t['mm_chains'] = merged_work.value
            current_work.set(t)
            
            t = time.time()
            for peer2, share_hash in desired:
                if share_hash not in tracker.tails: # was received in the time tracker.think was running
                    continue
                last_request_time, count = requested.get(share_hash, (None, 0))
                if last_request_time is not None and last_request_time - 5 < t < last_request_time + 10 * 1.5**count:
                    continue
                potential_peers = set()
                for head in tracker.tails[share_hash]:
                    potential_peers.update(peer_heads.get(head, set()))
                potential_peers = [peer for peer in potential_peers if peer.connected2]
                if count == 0 and peer2 is not None and peer2.connected2:
                    peer = peer2
                else:
                    peer = random.choice(potential_peers) if potential_peers and random.random() > .2 else peer2
                    if peer is None:
                        continue
                
                print 'Requesting parent share %s from %s' % (p2pool_data.format_hash(share_hash), '%s:%i' % peer.addr)
                peer.send_getshares(
                    hashes=[share_hash],
                    parents=2000,
                    stops=list(set(tracker.heads) | set(
                        tracker.get_nth_parent_hash(head, min(max(0, tracker.get_height_and_last(head)[0] - 1), 10)) for head in tracker.heads
                    ))[:100],
                )
                requested[share_hash] = t, count + 1
        bitcoind_work.changed.watch(lambda _: compute_work())
        merged_work.changed.watch(lambda _: compute_work())
        best_block_header.changed.watch(lambda _: compute_work())
        compute_work()
        
        # LONG POLLING
        
        lp_signal = variable.Event()
        
        @current_work.transitioned.watch
        def _(before, after):
            # trigger LP if version/previous_block/bits changed or transactions changed from nothing
            if any(before[x] != after[x] for x in ['version', 'previous_block', 'bits', 'best_share_hash', 'mm_chains']) or (not before['transactions'] and after['transactions']):
                lp_signal.happened()
        
        
        print '    ...success!'
        print
        
        # setup p2p logic and join p2pool network
        
        class Node(p2p.Node):
            def handle_shares(self, shares, peer):
                if len(shares) > 5:
                    print 'Processing %i shares from %s...' % (len(shares), '%s:%i' % peer.addr if peer is not None else None)
                
                new_count = 0
                for share in shares:
                    if share.hash in tracker.shares:
                        #print 'Got duplicate share, ignoring. Hash: %s' % (p2pool_data.format_hash(share.hash),)
                        continue
                    
                    new_count += 1
                    
                    #print 'Received share %s from %r' % (p2pool_data.format_hash(share.hash), share.peer.addr if share.peer is not None else None)
                    
                    tracker.add(share)
                
                if shares and peer is not None:
                    peer_heads.setdefault(shares[0].hash, set()).add(peer)
                
                if new_count:
                    compute_work()
                
                if len(shares) > 5:
                    print '... done processing %i shares. New: %i Have: %i/~%i' % (len(shares), new_count, len(tracker.shares), 2*net.CHAIN_LENGTH)
            
            def handle_share_hashes(self, hashes, peer):
                t = time.time()
                get_hashes = []
                for share_hash in hashes:
                    if share_hash in tracker.shares:
                        continue
                    last_request_time, count = requested.get(share_hash, (None, 0))
                    if last_request_time is not None and last_request_time - 5 < t < last_request_time + 10 * 1.5**count:
                        continue
                    print 'Got share hash, requesting! Hash: %s' % (p2pool_data.format_hash(share_hash),)
                    get_hashes.append(share_hash)
                    requested[share_hash] = t, count + 1
                
                if hashes and peer is not None:
                    peer_heads.setdefault(hashes[0], set()).add(peer)
                if get_hashes:
                    peer.send_getshares(hashes=get_hashes, parents=0, stops=[])
            
            def handle_get_shares(self, hashes, parents, stops, peer):
                parents = min(parents, 1000//len(hashes))
                stops = set(stops)
                shares = []
                for share_hash in hashes:
                    for share in tracker.get_chain(share_hash, min(parents + 1, tracker.get_height(share_hash))):
                        if share.hash in stops:
                            break
                        shares.append(share)
                print 'Sending %i shares to %s:%i' % (len(shares), peer.addr[0], peer.addr[1])
                return shares
            
            def handle_bestblock(self, header, peer):
                if net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(header)) > header['bits'].target:
                    raise p2p.PeerMisbehavingError('received block header fails PoW test')
                handle_header(header)
        
        @deferral.retry('Error submitting primary block: (will retry)', 10, 10)
        def submit_block_p2p(block):
            if factory.conn.value is None:
                print >>sys.stderr, 'No bitcoind connection when block submittal attempted! %s%32x' % (net.PARENT.BLOCK_EXPLORER_URL_PREFIX, bitcoin_data.hash256(bitcoin_data.block_header_type.pack(block['header'])))
                raise deferral.RetrySilentlyException()
            factory.conn.value.send_block(block=block)
        
        @deferral.retry('Error submitting block: (will retry)', 10, 10)
        @defer.inlineCallbacks
        def submit_block_rpc(block, ignore_failure):
            success = yield bitcoind.rpc_getmemorypool(bitcoin_data.block_type.pack(block).encode('hex'))
            success_expected = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(block['header'])) <= block['header']['bits'].target
            if (not success and success_expected and not ignore_failure) or (success and not success_expected):
                print >>sys.stderr, 'Block submittal result: %s Expected: %s' % (success, success_expected)
        
        def submit_block(block, ignore_failure):
            submit_block_p2p(block)
            submit_block_rpc(block, ignore_failure)
        
        @tracker.verified.added.watch
        def _(share):
            if share.pow_hash <= share.header['bits'].target:
                submit_block(share.as_block(tracker), ignore_failure=True)
                print
                print 'GOT BLOCK FROM PEER! Passing to bitcoind! %s bitcoin: %s%064x' % (p2pool_data.format_hash(share.hash), net.PARENT.BLOCK_EXPLORER_URL_PREFIX, share.header_hash)
                print
                def spread():
                    if (get_height_rel_highest(share.header['previous_block']) > -5 or
                        current_work.value['previous_block'] in [share.header['previous_block'], share.header_hash]):
                        broadcast_share(share.hash)
                spread()
                reactor.callLater(5, spread) # so get_height_rel_highest can update
        
        print 'Joining p2pool network using port %i...' % (args.p2pool_port,)
        
        @defer.inlineCallbacks
        def parse(x):
            if ':' in x:
                ip, port = x.split(':')
                defer.returnValue(((yield reactor.resolve(ip)), int(port)))
            else:
                defer.returnValue(((yield reactor.resolve(x)), net.P2P_PORT))
        
        addrs = {}
        if os.path.exists(os.path.join(datadir_path, 'addrs')):
            try:
                with open(os.path.join(datadir_path, 'addrs'), 'rb') as f:
                    addrs.update(dict((tuple(k), v) for k, v in json.loads(f.read())))
            except:
                print >>sys.stderr, 'error parsing addrs'
        elif os.path.exists(os.path.join(datadir_path, 'addrs.txt')):
            try:
                addrs.update(dict(eval(x) for x in open(os.path.join(datadir_path, 'addrs.txt'))))
            except:
                print >>sys.stderr, "error reading addrs.txt"
        for addr_df in map(parse, net.BOOTSTRAP_ADDRS):
            try:
                addr = yield addr_df
                if addr not in addrs:
                    addrs[addr] = (0, time.time(), time.time())
            except:
                log.err()
        
        connect_addrs = set()
        for addr_df in map(parse, args.p2pool_nodes):
            try:
                connect_addrs.add((yield addr_df))
            except:
                log.err()
        
        p2p_node = Node(
            best_share_hash_func=lambda: current_work.value['best_share_hash'],
            port=args.p2pool_port,
            net=net,
            addr_store=addrs,
            connect_addrs=connect_addrs,
            max_incoming_conns=args.p2pool_conns,
        )
        p2p_node.start()
        
        def save_addrs():
            with open(os.path.join(datadir_path, 'addrs'), 'wb') as f:
                f.write(json.dumps(p2p_node.addr_store.items()))
        task.LoopingCall(save_addrs).start(60)
        
        @best_block_header.changed.watch
        def _(header):
            for peer in p2p_node.peers.itervalues():
                peer.send_bestblock(header=header)
        
        def broadcast_share(share_hash):
            shares = []
            for share in tracker.get_chain(share_hash, min(5, tracker.get_height(share_hash))):
                if share.hash in shared_share_hashes:
                    break
                shared_share_hashes.add(share.hash)
                shares.append(share)
            
            for peer in p2p_node.peers.itervalues():
                peer.sendShares([share for share in shares if share.peer is not peer])
        
        # send share when the chain changes to their chain
        current_work.changed.watch(lambda new_work: broadcast_share(new_work['best_share_hash']))
        
        def save_shares():
            for share in tracker.get_chain(current_work.value['best_share_hash'], min(tracker.get_height(current_work.value['best_share_hash']), 2*net.CHAIN_LENGTH)):
                ss.add_share(share)
                if share.hash in tracker.verified.shares:
                    ss.add_verified_hash(share.hash)
        task.LoopingCall(save_shares).start(60)
        
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
        
        get_current_txouts = lambda: p2pool_data.get_expected_payouts(tracker, current_work.value['best_share_hash'], current_work.value['bits'].target, current_work.value['subsidy'], net)
        
        wb = WorkerBridge(lp_signal, my_pubkey_hash, net, args.donation_percentage, current_work, tracker, my_share_hashes, my_doa_share_hashes, args.worker_fee, p2p_node, submit_block, compute_work, shared_share_hashes)
        web_root = web.get_web_root(tracker, current_work, get_current_txouts, datadir_path, net, wb.get_stale_counts, my_pubkey_hash, wb.local_rate_monitor, args.worker_fee, p2p_node, wb.my_share_hashes, wb.pseudoshare_received, wb.share_received)
        worker_interface.WorkerInterface(wb).attach_to(web_root, get_handler=lambda request: request.redirect('/static/'))
        
        deferral.retry('Error binding to worker port:', traceback=False)(reactor.listenTCP)(worker_endpoint[1], server.Site(web_root), interface=worker_endpoint[0])
        
        with open(os.path.join(os.path.join(datadir_path, 'ready_flag')), 'wb') as f:
            pass
        
        print '    ...success!'
        print
        
        
        # done!
        print 'Started successfully!'
        print 'Go to http://127.0.0.1:%i/ to view graphs and statistics!' % (worker_endpoint[1],)
        if args.donation_percentage > 0.51:
            print '''Donating %.1f%% of work towards P2Pool's development. Thanks for the tip!''' % (args.donation_percentage,)
        elif args.donation_percentage < 0.49:
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
            task.LoopingCall(signal.alarm, 30).start(1)
        
        if args.irc_announce:
            from twisted.words.protocols import irc
            class IRCClient(irc.IRCClient):
                nickname = 'p2pool%02i' % (random.randrange(100),)
                channel = net.ANNOUNCE_CHANNEL
                def lineReceived(self, line):
                    if p2pool.DEBUG:
                        print repr(line)
                    irc.IRCClient.lineReceived(self, line)
                def signedOn(self):
                    irc.IRCClient.signedOn(self)
                    self.factory.resetDelay()
                    self.join(self.channel)
                    @defer.inlineCallbacks
                    def new_share(share):
                        if share.pow_hash <= share.header['bits'].target and abs(share.timestamp - time.time()) < 10*60:
                            yield deferral.sleep(random.expovariate(1/60))
                            message = '\x02%s BLOCK FOUND by %s! %s%064x' % (net.NAME.upper(), bitcoin_data.script2_to_address(share.new_script, net.PARENT), net.PARENT.BLOCK_EXPLORER_URL_PREFIX, share.header_hash)
                            if message not in self.recent_messages:
                                self.say(self.channel, message)
                                self._remember_message(message)
                    self.watch_id = tracker.verified.added.watch(new_share)
                    self.recent_messages = []
                def _remember_message(self, message):
                    self.recent_messages.append(message)
                    while len(self.recent_messages) > 100:
                        self.recent_messages.pop(0)
                def privmsg(self, user, channel, message):
                    if channel == self.channel:
                        self._remember_message(message)
                def connectionLost(self, reason):
                    tracker.verified.added.unwatch(self.watch_id)
                    print 'IRC connection lost:', reason.getErrorMessage()
            class IRCClientFactory(protocol.ReconnectingClientFactory):
                protocol = IRCClient
            reactor.connectTCP("irc.freenode.net", 6667, IRCClientFactory())
        
        @defer.inlineCallbacks
        def status_thread():
            last_str = None
            last_time = 0
            while True:
                yield deferral.sleep(3)
                try:
                    if time.time() > current_work.value['last_update'] + 60:
                        print >>sys.stderr, '''---> LOST CONTACT WITH BITCOIND for %s! Check that it isn't frozen or dead! <---''' % (math.format_dt(time.time() - current_work.value['last_update']),)
                    
                    height = tracker.get_height(current_work.value['best_share_hash'])
                    this_str = 'P2Pool: %i shares in chain (%i verified/%i total) Peers: %i (%i incoming)' % (
                        height,
                        len(tracker.verified.shares),
                        len(tracker.shares),
                        len(p2p_node.peers),
                        sum(1 for peer in p2p_node.peers.itervalues() if peer.incoming),
                    ) + (' FDs: %i R/%i W' % (len(reactor.getReaders()), len(reactor.getWriters())) if p2pool.DEBUG else '')
                    
                    datums, dt = wb.local_rate_monitor.get_datums_in_last()
                    my_att_s = sum(datum['work']/dt for datum in datums)
                    this_str += '\n Local: %sH/s in last %s Local dead on arrival: %s Expected time to share: %s' % (
                        math.format(int(my_att_s)),
                        math.format_dt(dt),
                        math.format_binomial_conf(sum(1 for datum in datums if datum['dead']), len(datums), 0.95),
                        math.format_dt(2**256 / tracker.shares[current_work.value['best_share_hash']].max_target / my_att_s) if my_att_s and current_work.value['best_share_hash'] else '???',
                    )
                    
                    if height > 2:
                        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()
                        stale_prop = p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], min(60*60//net.SHARE_PERIOD, height))
                        real_att_s = p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], min(height - 1, 60*60//net.SHARE_PERIOD)) / (1 - stale_prop)
                        
                        this_str += '\n Shares: %i (%i orphan, %i dead) Stale rate: %s Efficiency: %s Current payout: %.4f %s' % (
                            shares, stale_orphan_shares, stale_doa_shares,
                            math.format_binomial_conf(stale_orphan_shares + stale_doa_shares, shares, 0.95),
                            math.format_binomial_conf(stale_orphan_shares + stale_doa_shares, shares, 0.95, lambda x: (1 - x)/(1 - stale_prop)),
                            get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(my_pubkey_hash), 0)*1e-8, net.PARENT.SYMBOL,
                        )
                        this_str += '\n Pool: %sH/s Stale rate: %.1f%% Expected time to block: %s' % (
                            math.format(int(real_att_s)),
                            100*stale_prop,
                            math.format_dt(2**256 / current_work.value['bits'].target / real_att_s),
                        )
                        
                        for warning in p2pool_data.get_warnings(tracker, current_work, net):
                            print >>sys.stderr, '#'*40
                            print >>sys.stderr, '>>> Warning: ' + warning
                            print >>sys.stderr, '#'*40
                    
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
    realnets=dict((name, net) for name, net in networks.nets.iteritems() if '_testnet' not in name)
    
    parser = fixargparse.FixedArgumentParser(description='p2pool (version %s)' % (p2pool.__version__,), fromfile_prefix_chars='@')
    parser.add_argument('--version', action='version', version=p2pool.__version__)
    parser.add_argument('--net',
        help='use specified network (default: bitcoin)',
        action='store', choices=sorted(realnets), default='bitcoin', dest='net_name')
    parser.add_argument('--testnet',
        help='''use the network's testnet''',
        action='store_const', const=True, default=False, dest='testnet')
    parser.add_argument('--debug',
        help='enable debugging mode',
        action='store_const', const=True, default=False, dest='debug')
    parser.add_argument('-a', '--address',
        help='generate payouts to this address (default: <address requested from bitcoind>)',
        type=str, action='store', default=None, dest='address')
    parser.add_argument('--datadir',
        help='store data in this directory (default: <directory run_p2pool.py is in>/data)',
        type=str, action='store', default=None, dest='datadir')
    parser.add_argument('--logfile',
        help='''log to this file (default: data/<NET>/log)''',
        type=str, action='store', default=None, dest='logfile')
    parser.add_argument('--merged',
        help='call getauxblock on this url to get work for merged mining (example: http://ncuser:ncpass@127.0.0.1:10332/)',
        type=str, action='append', default=[], dest='merged_urls')
    parser.add_argument('--give-author', metavar='DONATION_PERCENTAGE',
        help='donate this percentage of work towards the development of p2pool (default: 0.5)',
        type=float, action='store', default=0.5, dest='donation_percentage')
    parser.add_argument('--iocp',
        help='use Windows IOCP API in order to avoid errors due to large number of sockets being open',
        action='store_true', default=False, dest='iocp')
    parser.add_argument('--irc-announce',
        help='announce any blocks found on irc://irc.freenode.net/#p2pool',
        action='store_true', default=False, dest='irc_announce')
    parser.add_argument('--no-bugreport',
        help='disable submitting caught exceptions to the author',
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
    
    worker_group = parser.add_argument_group('worker interface')
    worker_group.add_argument('-w', '--worker-port', metavar='PORT or ADDR:PORT',
        help='listen on PORT on interface with ADDR for RPC connections from miners (default: all interfaces, %s)' % ', '.join('%s:%i' % (name, net.WORKER_PORT) for name, net in sorted(realnets.items())),
        type=str, action='store', default=None, dest='worker_endpoint')
    worker_group.add_argument('-f', '--fee', metavar='FEE_PERCENTAGE',
        help='''charge workers mining to their own bitcoin address (by setting their miner's username to a bitcoin address) this percentage fee to mine on your p2pool instance. Amount displayed at http://127.0.0.1:WORKER_PORT/fee (default: 0)''',
        type=float, action='store', default=0, dest='worker_fee')
    
    bitcoind_group = parser.add_argument_group('bitcoind interface')
    bitcoind_group.add_argument('--bitcoind-address', metavar='BITCOIND_ADDRESS',
        help='connect to this address (default: 127.0.0.1)',
        type=str, action='store', default='127.0.0.1', dest='bitcoind_address')
    bitcoind_group.add_argument('--bitcoind-rpc-port', metavar='BITCOIND_RPC_PORT',
        help='''connect to JSON-RPC interface at this port (default: %s <read from bitcoin.conf if password not provided>)''' % ', '.join('%s:%i' % (name, net.PARENT.RPC_PORT) for name, net in sorted(realnets.items())),
        type=int, action='store', default=None, dest='bitcoind_rpc_port')
    bitcoind_group.add_argument('--bitcoind-p2p-port', metavar='BITCOIND_P2P_PORT',
        help='''connect to P2P interface at this port (default: %s <read from bitcoin.conf if password not provided>)''' % ', '.join('%s:%i' % (name, net.PARENT.P2P_PORT) for name, net in sorted(realnets.items())),
        type=int, action='store', default=None, dest='bitcoind_p2p_port')
    
    bitcoind_group.add_argument(metavar='BITCOIND_RPCUSERPASS',
        help='bitcoind RPC interface username, then password, space-separated (only one being provided will cause the username to default to being empty, and none will cause P2Pool to read them from bitcoin.conf)',
        type=str, action='store', default=[], nargs='*', dest='bitcoind_rpc_userpass')
    
    args = parser.parse_args()
    
    if args.debug:
        p2pool.DEBUG = True
    
    net_name = args.net_name + ('_testnet' if args.testnet else '')
    net = networks.nets[net_name]
    
    datadir_path = os.path.join((os.path.join(os.path.dirname(sys.argv[0]), 'data') if args.datadir is None else args.datadir), net_name)
    if not os.path.exists(datadir_path):
        os.makedirs(datadir_path)
    
    if len(args.bitcoind_rpc_userpass) > 2:
        parser.error('a maximum of two arguments are allowed')
    args.bitcoind_rpc_username, args.bitcoind_rpc_password = ([None, None] + args.bitcoind_rpc_userpass)[-2:]
    
    if args.bitcoind_rpc_password is None:
        if not hasattr(net.PARENT, 'CONF_FILE_FUNC'):
            parser.error('This network has no configuration file function. Manually enter your RPC password.')
        conf_path = net.PARENT.CONF_FILE_FUNC()
        if not os.path.exists(conf_path):
            parser.error('''Bitcoin configuration file not found. Manually enter your RPC password.\r\n'''
                '''If you actually haven't created a configuration file, you should create one at %s with the text:\r\n'''
                '''\r\n'''
                '''server=1\r\n'''
                '''rpcpassword=%x''' % (conf_path, random.randrange(2**128)))
        with open(conf_path, 'rb') as f:
            cp = ConfigParser.RawConfigParser()
            cp.readfp(StringIO.StringIO('[x]\r\n' + f.read()))
            for conf_name, var_name, var_type in [
                ('rpcuser', 'bitcoind_rpc_username', str),
                ('rpcpassword', 'bitcoind_rpc_password', str),
                ('rpcport', 'bitcoind_rpc_port', int),
                ('port', 'bitcoind_p2p_port', int),
            ]:
                if getattr(args, var_name) is None and cp.has_option('x', conf_name):
                    setattr(args, var_name, var_type(cp.get('x', conf_name)))
        if args.bitcoind_rpc_password is None:
            parser.error('''Bitcoin configuration file didn't contain an rpcpassword= line! Add one!''')
    
    if args.bitcoind_rpc_username is None:
        args.bitcoind_rpc_username = ''
    
    if args.bitcoind_rpc_port is None:
        args.bitcoind_rpc_port = net.PARENT.RPC_PORT
    
    if args.bitcoind_p2p_port is None:
        args.bitcoind_p2p_port = net.PARENT.P2P_PORT
    
    if args.p2pool_port is None:
        args.p2pool_port = net.P2P_PORT
    
    if args.worker_endpoint is None:
        worker_endpoint = '', net.WORKER_PORT
    elif ':' not in args.worker_endpoint:
        worker_endpoint = '', int(args.worker_endpoint)
    else:
        addr, port = args.worker_endpoint.rsplit(':', 1)
        worker_endpoint = addr, int(port)
    
    if args.address is not None:
        try:
            args.pubkey_hash = bitcoin_data.address_to_pubkey_hash(args.address, net.PARENT)
        except Exception, e:
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
    task.LoopingCall(logfile.reopen).start(5)
    
    class ErrorReporter(object):
        def __init__(self):
            self.last_sent = None
        
        def emit(self, eventDict):
            if not eventDict["isError"]:
                return
            
            if self.last_sent is not None and time.time() < self.last_sent + 5:
                return
            self.last_sent = time.time()
            
            if 'failure' in eventDict:
                text = ((eventDict.get('why') or 'Unhandled Error')
                    + '\n' + eventDict['failure'].getTraceback())
            else:
                text = " ".join([str(m) for m in eventDict["message"]]) + "\n"
            
            from twisted.web import client
            client.getPage(
                url='http://u.forre.st/p2pool_error.cgi',
                method='POST',
                postdata=p2pool.__version__ + ' ' + net.NAME + '\n' + text,
                timeout=15,
            ).addBoth(lambda x: None)
    if not args.no_bugreport:
        log.addObserver(ErrorReporter().emit)
    
    reactor.callWhenRunning(main, args, net, datadir_path, merged_urls, worker_endpoint)
    reactor.run()
