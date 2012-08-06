from __future__ import division

import base64
import random
import sys
import time

from twisted.internet import defer
from twisted.python import log

import bitcoin.getwork as bitcoin_getwork, bitcoin.data as bitcoin_data
from bitcoin import worker_interface
from util import jsonrpc, variable, deferral, math, pack
import p2pool, p2pool.data as p2pool_data

class WorkerBridge(worker_interface.WorkerBridge):
    def __init__(self, my_pubkey_hash, net, donation_percentage, bitcoind_work, best_block_header, merged_urls, best_share_var, tracker, my_share_hashes, my_doa_share_hashes, worker_fee, p2p_node, submit_block, set_best_share, broadcast_share, block_height_var):
        worker_interface.WorkerBridge.__init__(self)
        self.recent_shares_ts_work = []
        
        self.my_pubkey_hash = my_pubkey_hash
        self.net = net
        self.donation_percentage = donation_percentage
        self.bitcoind_work = bitcoind_work
        self.best_block_header = best_block_header
        self.best_share_var = best_share_var
        self.tracker = tracker
        self.my_share_hashes = my_share_hashes
        self.my_doa_share_hashes = my_doa_share_hashes
        self.worker_fee = worker_fee
        self.p2p_node = p2p_node
        self.submit_block = submit_block
        self.set_best_share = set_best_share
        self.broadcast_share = broadcast_share
        self.block_height_var = block_height_var
        
        self.pseudoshare_received = variable.Event()
        self.share_received = variable.Event()
        self.local_rate_monitor = math.RateMonitor(10*60)
        
        self.removed_unstales_var = variable.Variable((0, 0, 0))
        self.removed_doa_unstales_var = variable.Variable(0)
        
        @tracker.verified.removed.watch
        def _(share):
            if share.hash in self.my_share_hashes and tracker.is_child_of(share.hash, self.best_share_var.value):
                assert share.share_data['stale_info'] in [None, 'orphan', 'doa'] # we made these shares in this instance
                self.removed_unstales_var.set((
                    self.removed_unstales_var.value[0] + 1,
                    self.removed_unstales_var.value[1] + (1 if share.share_data['stale_info'] == 'orphan' else 0),
                    self.removed_unstales_var.value[2] + (1 if share.share_data['stale_info'] == 'doa' else 0),
                ))
            if share.hash in self.my_doa_share_hashes and self.tracker.is_child_of(share.hash, self.best_share_var.value):
                self.removed_doa_unstales_var.set(self.removed_doa_unstales_var.value + 1)
        
        # MERGED WORK
        
        self.merged_work = variable.Variable({})
        
        @defer.inlineCallbacks
        def set_merged_work(merged_url, merged_userpass):
            merged_proxy = jsonrpc.Proxy(merged_url, dict(Authorization='Basic ' + base64.b64encode(merged_userpass)))
            while True:
                auxblock = yield deferral.retry('Error while calling merged getauxblock:', 30)(merged_proxy.rpc_getauxblock)()
                self.merged_work.set(dict(self.merged_work.value, **{auxblock['chainid']: dict(
                    hash=int(auxblock['hash'], 16),
                    target='p2pool' if auxblock['target'] == 'p2pool' else pack.IntType(256).unpack(auxblock['target'].decode('hex')),
                    merged_proxy=merged_proxy,
                )}))
                yield deferral.sleep(1)
        for merged_url, merged_userpass in merged_urls:
            set_merged_work(merged_url, merged_userpass)
        
        @self.merged_work.changed.watch
        def _(new_merged_work):
            print 'Got new merged mining work!'
        
        # COMBINE WORK
        
        self.current_work = variable.Variable(None)
        def compute_work():
            t = dict(self.bitcoind_work.value)
            
            bb = self.best_block_header.value
            if bb is not None and bb['previous_block'] == t['previous_block'] and net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(bb)) <= t['bits'].target:
                print 'Skipping from block %x to block %x!' % (bb['previous_block'],
                    bitcoin_data.hash256(bitcoin_data.block_header_type.pack(bb)))
                t = dict(
                    previous_block=bitcoin_data.hash256(bitcoin_data.block_header_type.pack(bb)),
                    bits=bb['bits'], # not always true
                    coinbaseflags='',
                    time=bb['timestamp'] + 600, # better way?
                    transactions=[],
                    merkle_link=bitcoin_data.calculate_merkle_link([None], 0),
                    subsidy=net.PARENT.SUBSIDY_FUNC(self.block_height_var.value),
                    clock_offset=self.bitcoind_work.value['clock_offset'],
                    last_update=self.bitcoind_work.value['last_update'],
                )
            
            self.current_work.set(t)
        self.bitcoind_work.changed.watch(lambda _: compute_work())
        self.best_block_header.changed.watch(lambda _: compute_work())
        compute_work()
        
        self.new_work_event = variable.Event()
        @self.current_work.transitioned.watch
        def _(before, after):
            # trigger LP if previous_block/bits changed or transactions changed from nothing
            if any(before[x] != after[x] for x in ['previous_block', 'bits']) or (not before['transactions'] and after['transactions']):
                self.new_work_event.happened()
        self.merged_work.changed.watch(lambda _: self.new_work_event.happened())
        self.best_share_var.changed.watch(lambda _: self.new_work_event.happened())
    
    def get_stale_counts(self):
        '''Returns (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain)'''
        my_shares = len(self.my_share_hashes)
        my_doa_shares = len(self.my_doa_share_hashes)
        delta = self.tracker.verified.get_delta_to_last(self.best_share_var.value)
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
        if self.best_share_var.value is None and self.net.PERSIST:
            raise jsonrpc.Error(-12345, u'p2pool is downloading shares')
        if time.time() > self.current_work.value['last_update'] + 60:
            raise jsonrpc.Error(-12345, u'lost contact with bitcoind')
        
        if self.merged_work.value:
            tree, size = bitcoin_data.make_auxpow_tree(self.merged_work.value)
            mm_hashes = [self.merged_work.value.get(tree.get(i), dict(hash=0))['hash'] for i in xrange(size)]
            mm_data = '\xfa\xbemm' + bitcoin_data.aux_pow_coinbase_type.pack(dict(
                merkle_root=bitcoin_data.merkle_hash(mm_hashes),
                size=size,
                nonce=0,
            ))
            mm_later = [(aux_work, mm_hashes.index(aux_work['hash']), mm_hashes) for chain_id, aux_work in self.merged_work.value.iteritems()]
        else:
            mm_data = ''
            mm_later = []
        
        if True:
            share_info, generate_tx = p2pool_data.Share.generate_transaction(
                tracker=self.tracker,
                share_data=dict(
                    previous_share_hash=self.best_share_var.value,
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
        
        mm_later = [(dict(aux_work, target=aux_work['target'] if aux_work['target'] != 'p2pool' else share_info['bits'].target), index, hashes) for aux_work, index, hashes in mm_later]
        
        if desired_pseudoshare_target is None:
            target = 2**256-1
            if len(self.recent_shares_ts_work) == 50:
                hash_rate = sum(work for ts, work in self.recent_shares_ts_work[1:])//(self.recent_shares_ts_work[-1][0] - self.recent_shares_ts_work[0][0])
                if hash_rate:
                    target = min(target, int(2**256/hash_rate))
        else:
            target = desired_pseudoshare_target
        target = max(target, share_info['bits'].target)
        for aux_work, index, hashes in mm_later:
            target = max(target, aux_work['target'])
        target = math.clip(target, self.net.PARENT.SANE_TARGET_RANGE)
        
        transactions = [generate_tx] + list(self.current_work.value['transactions'])
        packed_generate_tx = bitcoin_data.tx_type.pack(generate_tx)
        merkle_root = bitcoin_data.check_merkle_link(bitcoin_data.hash256(packed_generate_tx), self.current_work.value['merkle_link'])
        
        getwork_time = time.time()
        lp_count = self.new_work_event.times
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
            version=1,
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
            
            on_time = self.new_work_event.times == lp_count
            
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
                        def _(result, aux_work=aux_work):
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
                self.set_best_share()
                
                try:
                    if pow_hash <= header['bits'].target or p2pool.DEBUG:
                        self.broadcast_share(share.hash)
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
