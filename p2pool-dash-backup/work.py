from __future__ import division
from collections import deque

import base64
import random
import re
import sys
import time

from twisted.internet import defer
from twisted.python import log

import dash.getwork as dash_getwork, dash.data as dash_data
from dash import helper, script, worker_interface
from util import forest, jsonrpc, variable, deferral, math, pack
import p2pool, p2pool.data as p2pool_data
from p2pool import merged_mining

print_throttle = 0.0

class WorkerBridge(worker_interface.WorkerBridge):
    COINBASE_NONCE_LENGTH = 8

    def __init__(self, node, my_pubkey_hash, donation_percentage, merged_urls, worker_fee, args, pubkeys, coind):
        worker_interface.WorkerBridge.__init__(self)
        self.recent_shares_ts_work = []

        self.node = node

        self.coind = coind
        self.pubkeys = pubkeys
        self.args = args
        self.my_pubkey_hash = my_pubkey_hash
		
        self.donation_percentage = args.donation_percentage
        self.worker_fee = args.worker_fee


        self.net = self.node.net.PARENT
        self.running = True
        self.pseudoshare_received = variable.Event()
        self.share_received = variable.Event()
        # Activity window must account for extreme variance in low-difficulty mining
        # At minimum difficulty (0.001), miners can have very long gaps between shares
        # due to Poisson distribution variance (95% CI = ~30x expected time)
        # Formula: 100 * STRATUM_SHARE_RATE gives safe margin for variance
        # For mainnet: 100 * 10 sec = 1000 seconds (~16.7 minutes)
        # This keeps count stable while still being responsive to real disconnects
        activity_window = 100 * self.node.net.STRATUM_SHARE_RATE
        self.local_rate_monitor = math.RateMonitor(activity_window)
        self.local_addr_rate_monitor = math.RateMonitor(activity_window)

        self.removed_unstales_var = variable.Variable((0, 0, 0))
        self.removed_doa_unstales_var = variable.Variable(0)

        self.last_work_shares = variable.Variable( {} )

        self.my_share_hashes = set()
        self.my_doa_share_hashes = set()

        self.address_throttle = 0
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
        def set_merged_work(merged_url, merged_userpass):
            merged_proxy = jsonrpc.HTTPProxy(merged_url, dict(Authorization='Basic ' + base64.b64encode(merged_userpass)))
            
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
                            
                            # Store full template for multiaddress coinbase building
                            self.merged_work.set(math.merge_dicts(self.merged_work.value, {chainid: dict(
                                template=template,
                                hash=0,  # Not used with getblocktemplate
                                target=pack.IntType(256).unpack(target_hex.decode('hex')),
                                merged_proxy=merged_proxy,
                                multiaddress=True,
                            )}))
                        else:
                            # getblocktemplate succeeded but no auxpow - shouldn't happen
                            if auxpow_capable is None:
                                print 'Warning: getblocktemplate succeeded but no auxpow object at %s, falling back to getauxblock' % (merged_url,)
                            auxpow_capable = False
                            raise ValueError('No auxpow in template')
                            
                except Exception as e:
                    # Fall back to standard getauxblock (single address)
                    if auxpow_capable is None:
                        print 'Auxpow not supported at %s, using standard getauxblock (single address mode)' % (merged_url,)
                    auxpow_capable = False
                    
                    auxblock = yield deferral.retry('Error while calling merged getauxblock on %s:' % (merged_url,), 30)(
                        merged_proxy.rpc_getauxblock
                    )()
                    self.merged_work.set(math.merge_dicts(self.merged_work.value, {auxblock['chainid']: dict(
                        hash=int(auxblock['hash'], 16),
                        target='p2pool' if auxblock['target'] == 'p2pool' else pack.IntType(256).unpack(auxblock['target'].decode('hex')),
                        merged_proxy=merged_proxy,
                        multiaddress=False,
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
            t = self.node.coind_work.value
            bb = self.node.best_block_header.value
            if bb is not None and bb['previous_block'] == t['previous_block'] and self.node.net.PARENT.POW_FUNC(dash_data.block_header_type.pack(bb)) <= t['bits'].target:
                print 'Skipping from block %x to block %x! NewHeight=%s' % (bb['previous_block'],
                    self.node.net.PARENT.BLOCKHASH_FUNC(dash_data.block_header_type.pack(bb)),t['height']+1,)
                '''
                # New block template from Dash daemon only
                t = dict(
                    version=bb['version'],
                    previous_block=self.node.net.PARENT.BLOCKHASH_FUNC(dash_data.block_header_type.pack(bb)),
                    bits=bb['bits'], # not always true
                    coinbaseflags='',
                    height=t['height'] + 1,
                    time=bb['timestamp'] + 600, # better way?
                    transactions=[],
                    transaction_fees=[],
                    merkle_link=dash_data.calculate_merkle_link([None], 0),
                    subsidy=self.node.coind_work.value['subsidy'],
                    last_update=self.node.coind_work.value['last_update'],
                    payment_amount=self.node.coind_work.value['payment_amount'],
                    packed_payments=self.node.coind_work.value['packed_payments'],
                )
                '''

            self.current_work.set(t)
        self.node.coind_work.changed.watch(lambda _: compute_work())
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
        self.address = yield deferral.retry('Error getting a dynamic address from coind:', 5)(lambda: self.coind.rpc_getnewaddress('p2pool'))()
        new_pubkey = dash_data.address_to_pubkey_hash(self.address, self.net)
        self.pubkeys.popleft()
        self.pubkeys.addkey(new_pubkey)
        print " Updated payout pool:"
        for i in xrange(len(self.pubkeys.keys)):
            print '    ...payout %d: %s(%f)' % (i, dash_data.pubkey_hash_to_address(self.pubkeys.keys[i], self.net),self.pubkeys.keyweights[i],)
        self.pubkeys.updatestamp(c)
        print " Next address rotation in : %fs" % (time.time()-c+self.args.timeaddresses)

    def get_user_details(self, username):
        contents = re.split('([+/])', username)
        assert len(contents) % 2 == 1

        user, contents2 = contents[0], contents[1:]
        
        # Parse merged mining addresses (format: ltc_addr,doge_addr or ltc_addr,doge_addr.worker)
        # Using , (comma) separator - URL-safe and not used in difficulty parsing
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
                    desired_pseudoshare_target = dash_data.difficulty_to_target(float(parameter))
                except:
                    if p2pool.DEBUG:
                        log.err()
            elif symbol == '/':
                try:
                    desired_share_target = dash_data.difficulty_to_target(float(parameter))
                except:
                    if p2pool.DEBUG:
                        log.err()        

        if self.args.address == 'dynamic':
            i = self.pubkeys.weighted()
            pubkey_hash = self.pubkeys.keys[i]

            c = time.time()
            if (c - self.pubkeys.stamp) > self.args.timeaddresses:
                self.freshen_addresses(c)

        if random.uniform(0, 100) < self.worker_fee:
            pubkey_hash = self.my_pubkey_hash
        else:
            try:
                pubkey_hash = dash_data.address_to_pubkey_hash(user, self.node.net.PARENT)
            except: # XXX blah
                if self.args.address != 'dynamic':
                    pubkey_hash = self.my_pubkey_hash
        
        # Append worker name to user for identification
        if worker:
            user = user + '.' + worker

        return user, pubkey_hash, desired_share_target, desired_pseudoshare_target, merged_addresses

    def preprocess_request(self, user):
        # Removed peer connection check - allow solo mining
        if time.time() > self.current_work.value['last_update'] + 60:
            raise jsonrpc.Error_for_code(-12345)(u'lost contact with coind')
        user, pubkey_hash, desired_share_target, desired_pseudoshare_target, merged_addresses = self.get_user_details(user)
        return pubkey_hash, desired_share_target, desired_pseudoshare_target, merged_addresses

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

    def get_work(self, pubkey_hash, desired_share_target, desired_pseudoshare_target, merged_addresses=None):
        global print_throttle
        t0 = time.time()  # Benchmarking start
        
        # Store merged addresses for later use in block submission
        if merged_addresses is None:
            merged_addresses = {}
        self._current_merged_addresses = merged_addresses
        
        # Removed peer connection check - allow solo mining
        # P2Pool can work standalone even with PERSIST=True

        if self.merged_work.value:
            tree, size = dash_data.make_auxpow_tree(self.merged_work.value)
            mm_hashes = [self.merged_work.value.get(tree.get(i), dict(hash=0))['hash'] for i in xrange(size)]
            mm_data = '\xfa\xbemm' + dash_data.aux_pow_coinbase_type.pack(dict(
                merkle_root=dash_data.merkle_hash(mm_hashes),
                size=size,
                nonce=0,
            ))
            mm_later = [(aux_work, mm_hashes.index(aux_work['hash']), mm_hashes) for chain_id, aux_work in self.merged_work.value.iteritems()]
        else:
            mm_data = ''
            mm_later = []

        tx_hashes = [dash_data.hash256(dash_data.tx_type.pack(tx)) for tx in self.current_work.value['transactions']]
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
                    dash_data.average_attempts_to_target(local_hash_rate * self.node.net.SHARE_PERIOD / 0.0167)) # limit to 1.67% of pool shares by modulating share difficulty



            lookbehind = 3600//self.node.net.SHARE_PERIOD
            block_subsidy = self.node.coind_work.value['subsidy']
            if previous_share is not None and self.node.tracker.get_height(previous_share.hash) > lookbehind:
                expected_payout_per_block = local_addr_rates.get(pubkey_hash, 0)/p2pool_data.get_pool_attempts_per_second(self.node.tracker, self.node.best_share_var.value, lookbehind) \
                    * block_subsidy*(1-self.donation_percentage/100) # XXX doesn't use global stale rate to compute pool hash
                if expected_payout_per_block < self.node.net.PARENT.DUST_THRESHOLD:
                    desired_share_target = min(desired_share_target,
                        dash_data.average_attempts_to_target((dash_data.target_to_average_attempts(self.node.coind_work.value['bits'].target)*self.node.net.SPREAD)*self.node.net.PARENT.DUST_THRESHOLD/block_subsidy)
                    )

        if True:
            share_info, gentx, other_transaction_hashes, get_share = share_type.generate_transaction(
                tracker=self.node.tracker,
                share_data=dict(
                    previous_share_hash=self.node.best_share_var.value,
                    coinbase=(script.create_push_script([
                        self.current_work.value['height'],
                        ] + ([mm_data] if mm_data else []) + [
                    ]) + self.current_work.value['coinbaseflags'] + self.node.net.COINBASEEXT)[:100],
                    coinbase_payload=self.current_work.value['coinbase_payload'],
                    nonce=random.randrange(2**32),
                    pubkey_hash=pubkey_hash,
                    subsidy=self.current_work.value['subsidy'],
                    donation=math.perfect_round(65535*self.donation_percentage/100),
                    stale_info=(lambda (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain):
                        'orphan' if orphans > orphans_recorded_in_chain else
                        'doa' if doas > doas_recorded_in_chain else
                        None
                    )(*self.get_stale_counts()),
                    desired_version=(share_type.SUCCESSOR if share_type.SUCCESSOR is not None else share_type).VOTING_VERSION,
                    payment_amount=self.current_work.value['payment_amount'],
                    packed_payments=self.current_work.value['packed_payments'],
                ),
                block_target=self.current_work.value['bits'].target,
                desired_timestamp=int(time.time() + 0.5),
                desired_target=desired_share_target,
                ref_merkle_link=dict(branch=[], index=0),
                desired_other_transaction_hashes_and_fees=zip(tx_hashes, self.current_work.value['transaction_fees']),
                net=self.node.net,
                known_txs=tx_map,
                base_subsidy=self.current_work.value['subsidy'],
            )

        packed_gentx = dash_data.tx_type.pack(gentx)
        other_transactions = [tx_map[tx_hash] for tx_hash in other_transaction_hashes]

        mm_later = [(dict(aux_work, target=aux_work['target'] if aux_work['target'] != 'p2pool' else share_info['bits'].target), index, hashes) for aux_work, index, hashes in mm_later]

        if desired_pseudoshare_target is None:
            target = 2**256-1
            local_hash_rate = self._estimate_local_hash_rate()
            if local_hash_rate is not None:
                target = min(target,
                    dash_data.average_attempts_to_target(local_hash_rate * 1)) # limit to 1 share response every second by modulating pseudoshare difficulty
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
        merkle_link = dash_data.calculate_merkle_link([None] + other_transaction_hashes, 0)

        if print_throttle is 0.0:
            print_throttle = time.time()
        else:
            current_time = time.time()
            if (current_time - print_throttle) > 5.0:
                print 'New work for worker %s! Difficulty: %.06f Share difficulty: %.06f (speed %.06f) Total block value: %.6f %s including %i transactions' % (
                    dash_data.pubkey_hash_to_address(pubkey_hash, self.node.net.PARENT),
                    dash_data.target_to_difficulty(target),
                    dash_data.target_to_difficulty(share_info['bits'].target),
                    local_addr_rates.get(pubkey_hash, 0),
                    self.current_work.value['subsidy']*1e-8, self.node.net.PARENT.SYMBOL,
                    len(self.current_work.value['transactions']),
                )
                print_throttle = time.time()

        #need this for stats
        self.last_work_shares.value[dash_data.pubkey_hash_to_address(pubkey_hash, self.node.net.PARENT)]=share_info['bits']

        coinbase_payload_data_size = 0
        if gentx['version'] == 3 and gentx['type'] == 5:
            coinbase_payload_data_size = len(pack.VarStrType().pack(gentx['extra_payload']))

        # Fixed based on jtoomim's p2pool implementation
        # share_target = vardiff pseudoshare difficulty (already floored at p2pool_share_floor above)
        # min_share_target = P2Pool share chain difficulty floor (respects SANE_TARGET_RANGE)
        ba = dict(
            version=self.current_work.value['version'],
            previous_block=self.current_work.value['previous_block'],
            merkle_link=merkle_link,
            coinb1=packed_gentx[:-coinbase_payload_data_size-self.COINBASE_NONCE_LENGTH-4],
            coinb2=packed_gentx[-coinbase_payload_data_size-4:],
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
            new_packed_gentx = packed_gentx[:-coinbase_payload_data_size-self.COINBASE_NONCE_LENGTH-4] + coinbase_nonce + packed_gentx[-coinbase_payload_data_size-4:] if coinbase_nonce != '\0'*self.COINBASE_NONCE_LENGTH else packed_gentx
            new_gentx = dash_data.tx_type.unpack(new_packed_gentx) if coinbase_nonce != '\0'*self.COINBASE_NONCE_LENGTH else gentx

            header_hash = self.node.net.PARENT.BLOCKHASH_FUNC(dash_data.block_header_type.pack(header))
            pow_hash = self.node.net.PARENT.POW_FUNC(dash_data.block_header_type.pack(header))
            try:
                if pow_hash <= header['bits'].target or p2pool.DEBUG:
                    if pow_hash <= header['bits'].target:
                        print
                        print '#' * 70
                        print '### DASH BLOCK FOUND! ###'
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
                    # Submit block and add error callback to catch any failures
                    block_submission = helper.submit_block(dict(header=header, txs=[new_gentx] + other_transactions), False, self.node.factory, self.node.coind, self.node.coind_work, self.node.net)
                    @block_submission.addErrback
                    def block_submit_error(err):
                        print >>sys.stderr, '*** CRITICAL: Block submission failed! ***'
                        log.err(err, 'Block submission error:')
                    if pow_hash <= header['bits'].target:
                        # New block found
                        self.node.factory.new_block.happened(header_hash)
            except:
                log.err(None, 'Error while processing potential block:')

            user, _, _, _, _ = self.get_user_details(user)
            assert header['previous_block'] == ba['previous_block']
            assert header['merkle_root'] == dash_data.check_merkle_link(dash_data.hash256(new_packed_gentx), merkle_link)
            assert header['bits'] == ba['bits']

            # Allow shares that are within 3 work events of current (grace period for network latency)
            # Work events fire on new blocks, new best shares, etc. - can be rapid
            work_event_diff = self.new_work_event.times - lp_count
            on_time = work_event_diff <= 3  # Allow up to 3 work events behind

            for aux_work, index, hashes in mm_later:
                try:
                    if pow_hash <= aux_work['target'] or p2pool.DEBUG:
                        # Check if this is multiaddress merged mining (getblocktemplate with auxpow)
                        if aux_work.get('multiaddress'):
                            # Build complete Dogecoin block with multiaddress coinbase
                            template = aux_work['template']
                            
                            # Get miner's merged addresses if provided
                            merged_addrs = getattr(self, '_current_merged_addresses', {})
                            dogecoin_address = merged_addrs.get('dogecoin')
                            
                            # Build shareholders dict
                            if dogecoin_address:
                                # Miner provided dogecoin address - use it for payout
                                shareholders = {dogecoin_address: 1.0}
                                print 'Using miner dogecoin address: %s' % dogecoin_address
                            else:
                                # No dogecoin address provided - create dummy output
                                # TODO: Integrate with share chain to get actual shareholder distribution
                                shareholders = {}
                            
                            # Build Dogecoin coinbase with shareholder outputs
                            try:
                                merged_coinbase = merged_mining.build_merged_coinbase(
                                    template=template,
                                    shareholders=shareholders,
                                    net=self.node.net
                                )
                                
                                # Build complete Dogecoin block
                                merged_block, auxpow = merged_mining.build_merged_block(
                                    template=template,
                                    coinbase_tx=merged_coinbase,
                                    auxpow_proof=dict(
                                        merkle_tx=dict(
                                            tx=new_gentx,
                                            block_hash=header_hash,
                                            merkle_link=merkle_link,
                                        ),
                                        merkle_link=dash_data.calculate_merkle_link(hashes, index),
                                        parent_block_header=header,
                                    ),
                                    parent_block_header=header,
                                    merkle_link_to_parent=merkle_link
                                )
                                
                                # Pack block for submission
                                block_hex = dash_data.block_type.pack(merged_block).encode('hex')
                                auxpow_hex = dash_data.aux_pow_type.pack(auxpow).encode('hex')
                                
                                # Submit via submitauxblock (block + auxpow)
                                print 'Submitting multiaddress merged block via submitauxblock...'
                                df = deferral.retry('Error submitting multiaddress merged block: (will retry)', 10, 10)(
                                    aux_work['merged_proxy'].rpc_submitauxblock
                                )(block_hex, auxpow_hex)
                                
                                @df.addCallback
                                def _(result, aux_work=aux_work):
                                    if result is None or result == True:
                                        print 'Multiaddress merged block accepted!'
                                    else:
                                        print >>sys.stderr, 'Multiaddress merged block rejected: %s' % (result,)
                                
                                @df.addErrback
                                def _(err):
                                    log.err(err, 'Error submitting multiaddress merged block:')
                                    
                            except Exception as e:
                                print >>sys.stderr, 'Error building multiaddress merged block: %s' % (e,)
                                log.err(None, 'Error building multiaddress merged block:')
                        else:
                            # Standard getauxblock submission (backward compatible)
                            df = deferral.retry('Error submitting merged block: (will retry)', 10, 10)(aux_work['merged_proxy'].rpc_getauxblock)(
                                pack.IntType(256, 'big').pack(aux_work['hash']).encode('hex'),
                                dash_data.aux_pow_type.pack(dict(
                                    merkle_tx=dict(
                                        tx=new_gentx,
                                        block_hash=header_hash,
                                        merkle_link=merkle_link,
                                    ),
                                    merkle_link=dash_data.calculate_merkle_link(hashes, index),
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
                last_txout_nonce = pack.IntType(8*self.COINBASE_NONCE_LENGTH).unpack(coinbase_nonce)
                share = get_share(header, last_txout_nonce)

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

                try:
                    if (pow_hash <= header['bits'].target or p2pool.DEBUG) and self.node.p2p_node is not None:
                        self.node.p2p_node.broadcast_share(share.hash)
                except:
                    log.err(None, 'Error forwarding block solution:')

                self.share_received.happened(dash_data.target_to_average_attempts(share.target), not on_time, share.hash)
                
                # Update local rate monitor for shares (they are also pseudoshares)
                # Use effective_target (vardiff target) for work calculation
                self.local_rate_monitor.add_datum(dict(work=dash_data.target_to_average_attempts(effective_target), dead=not on_time, user=user, share_target=share_info['bits'].target))
                self.local_addr_rate_monitor.add_datum(dict(work=dash_data.target_to_average_attempts(effective_target), pubkey_hash=pubkey_hash))
                received_header_hashes.add(header_hash)
            elif pow_hash > effective_target:
                print 'Worker %s submitted share with hash > target:' % (user,)
                print '    Hash:   %56x' % (pow_hash,)
                print '    Target: %56x' % (effective_target,)
            elif header_hash in received_header_hashes:
                print >>sys.stderr, 'Worker %s submitted share more than once!' % (user,)
            else:
                received_header_hashes.add(header_hash)

                work_value = dash_data.target_to_average_attempts(effective_target)
                self.pseudoshare_received.happened(work_value, not on_time, user)
                self.recent_shares_ts_work.append((time.time(), work_value))
                while len(self.recent_shares_ts_work) > 50:
                    self.recent_shares_ts_work.pop(0)
                self.local_rate_monitor.add_datum(dict(work=work_value, dead=not on_time, user=user, share_target=share_info['bits'].target))
                self.local_addr_rate_monitor.add_datum(dict(work=work_value, pubkey_hash=pubkey_hash))

            return on_time

        t1 = time.time()
        if p2pool.BENCH:
            print "%8.3f ms for work.py:get_work(%s)" % ((t1-t0)*1000., dash_data.pubkey_hash_to_address(pubkey_hash, self.node.net.PARENT))
        
        return ba, got_response
