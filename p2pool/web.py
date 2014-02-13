from __future__ import division

import errno
import json
import os
import sys
import time
import traceback

from twisted.internet import defer, reactor
from twisted.python import log
from twisted.web import resource, static

import p2pool
from bitcoin import data as bitcoin_data
from . import data as p2pool_data, p2p
from util import deferral, deferred_resource, graph, math, memory, pack, variable

def _atomic_read(filename):
    try:
        with open(filename, 'rb') as f:
            return f.read()
    except IOError, e:
        if e.errno != errno.ENOENT:
            raise
    try:
        with open(filename + '.new', 'rb') as f:
            return f.read()
    except IOError, e:
        if e.errno != errno.ENOENT:
            raise
    return None

def _atomic_write(filename, data):
    with open(filename + '.new', 'wb') as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except:
            pass
    try:
        os.rename(filename + '.new', filename)
    except: # XXX windows can't overwrite
        os.remove(filename)
        os.rename(filename + '.new', filename)

def get_web_root(wb, datadir_path, bitcoind_getinfo_var, stop_event=variable.Event()):
    node = wb.node
    start_time = time.time()
    
    web_root = resource.Resource()
    
    def get_users():
        height, last = node.tracker.get_height_and_last(node.best_share_var.value)
        weights, total_weight, donation_weight = node.tracker.get_cumulative_weights(node.best_share_var.value, min(height, 720), 65535*2**256)
        res = {}
        for script in sorted(weights, key=lambda s: weights[s]):
            res[bitcoin_data.script2_to_address(script, node.net.PARENT)] = weights[script]/total_weight
        return res
    
    def get_current_scaled_txouts(scale, trunc=0):
        txouts = node.get_current_txouts()
        total = sum(txouts.itervalues())
        results = dict((script, value*scale//total) for script, value in txouts.iteritems())
        if trunc > 0:
            total_random = 0
            random_set = set()
            for s in sorted(results, key=results.__getitem__):
                if results[s] >= trunc:
                    break
                total_random += results[s]
                random_set.add(s)
            if total_random:
                winner = math.weighted_choice((script, results[script]) for script in random_set)
                for script in random_set:
                    del results[script]
                results[winner] = total_random
        if sum(results.itervalues()) < int(scale):
            results[math.weighted_choice(results.iteritems())] += int(scale) - sum(results.itervalues())
        return results
    
    def get_patron_sendmany(total=None, trunc='0.01'):
        if total is None:
            return 'need total argument. go to patron_sendmany/<TOTAL>'
        total = int(float(total)*1e8)
        trunc = int(float(trunc)*1e8)
        return json.dumps(dict(
            (bitcoin_data.script2_to_address(script, node.net.PARENT), value/1e8)
            for script, value in get_current_scaled_txouts(total, trunc).iteritems()
            if bitcoin_data.script2_to_address(script, node.net.PARENT) is not None
        ))
    
    def get_global_stats():
        # averaged over last hour
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.tracker.get_height(node.best_share_var.value), 3600//node.net.SHARE_PERIOD)
        
        nonstale_hash_rate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
        stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        diff = bitcoin_data.target_to_difficulty(wb.current_work.value['bits'].target)

        return dict(
            pool_nonstale_hash_rate=nonstale_hash_rate,
            pool_hash_rate=nonstale_hash_rate/(1 - stale_prop),
            pool_stale_prop=stale_prop,
            min_difficulty=bitcoin_data.target_to_difficulty(node.tracker.items[node.best_share_var.value].max_target),
            network_block_difficulty=diff,
            network_hashrate=(diff * 2**32 // node.net.PARENT.BLOCK_PERIOD),
        )
    
    def get_local_stats():
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.tracker.get_height(node.best_share_var.value), 3600//node.net.SHARE_PERIOD)
        
        global_stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        
        my_unstale_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes)
        my_orphan_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes and share.share_data['stale_info'] == 'orphan')
        my_doa_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes and share.share_data['stale_info'] == 'doa')
        my_share_count = my_unstale_count + my_orphan_count + my_doa_count
        my_stale_count = my_orphan_count + my_doa_count
        
        my_stale_prop = my_stale_count/my_share_count if my_share_count != 0 else None
        
        my_work = sum(bitcoin_data.target_to_average_attempts(share.target)
            for share in node.tracker.get_chain(node.best_share_var.value, lookbehind - 1)
            if share.hash in wb.my_share_hashes)
        actual_time = (node.tracker.items[node.best_share_var.value].timestamp -
            node.tracker.items[node.tracker.get_nth_parent_hash(node.best_share_var.value, lookbehind - 1)].timestamp)
        share_att_s = my_work / actual_time
        
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()

        miner_last_difficulties = {}
        for addr in wb.last_work_shares.value:
            miner_last_difficulties[addr] = bitcoin_data.target_to_difficulty(wb.last_work_shares.value[addr].target)
        
        return dict(
            my_hash_rates_in_last_hour=dict(
                note="DEPRECATED",
                nonstale=share_att_s,
                rewarded=share_att_s/(1 - global_stale_prop),
                actual=share_att_s/(1 - my_stale_prop) if my_stale_prop is not None else 0, # 0 because we don't have any shares anyway
            ),
            my_share_counts_in_last_hour=dict(
                shares=my_share_count,
                unstale_shares=my_unstale_count,
                stale_shares=my_stale_count,
                orphan_stale_shares=my_orphan_count,
                doa_stale_shares=my_doa_count,
            ),
            my_stale_proportions_in_last_hour=dict(
                stale=my_stale_prop,
                orphan_stale=my_orphan_count/my_share_count if my_share_count != 0 else None,
                dead_stale=my_doa_count/my_share_count if my_share_count != 0 else None,
            ),
            miner_hash_rates=miner_hash_rates,
            miner_dead_hash_rates=miner_dead_hash_rates,
            miner_last_difficulties=miner_last_difficulties,
            efficiency_if_miner_perfect=(1 - stale_orphan_shares/shares)/(1 - global_stale_prop) if shares else None, # ignores dead shares because those are miner's fault and indicated by pseudoshare rejection
            efficiency=(1 - (stale_orphan_shares+stale_doa_shares)/shares)/(1 - global_stale_prop) if shares else None,
            peers=dict(
                incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
                outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
            ),
            shares=dict(
                total=shares,
                orphan=stale_orphan_shares,
                dead=stale_doa_shares,
            ),
            uptime=time.time() - start_time,
            attempts_to_share=bitcoin_data.target_to_average_attempts(node.tracker.items[node.best_share_var.value].max_target),
            attempts_to_block=bitcoin_data.target_to_average_attempts(node.bitcoind_work.value['bits'].target),
            block_value=node.bitcoind_work.value['subsidy']*1e-8,
            warnings=p2pool_data.get_warnings(node.tracker, node.best_share_var.value, node.net, bitcoind_getinfo_var.value, node.bitcoind_work.value),
            donation_proportion=wb.donation_percentage/100,
            version=p2pool.__version__,
            protocol_version=p2p.Protocol.VERSION,
            fee=wb.worker_fee,
        )
    
    class WebInterface(deferred_resource.DeferredResource):
        def __init__(self, func, mime_type='application/json', args=()):
            deferred_resource.DeferredResource.__init__(self)
            self.func, self.mime_type, self.args = func, mime_type, args
        
        def getChild(self, child, request):
            return WebInterface(self.func, self.mime_type, self.args + (child,))
        
        @defer.inlineCallbacks
        def render_GET(self, request):
            request.setHeader('Content-Type', self.mime_type)
            request.setHeader('Access-Control-Allow-Origin', '*')
            res = yield self.func(*self.args)
            defer.returnValue(json.dumps(res) if self.mime_type == 'application/json' else res)
    
    def decent_height():
        return min(node.tracker.get_height(node.best_share_var.value), 720)
    web_root.putChild('rate', WebInterface(lambda: p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, decent_height())/(1-p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, decent_height()))))
    web_root.putChild('difficulty', WebInterface(lambda: bitcoin_data.target_to_difficulty(node.tracker.items[node.best_share_var.value].max_target)))
    web_root.putChild('users', WebInterface(get_users))
    web_root.putChild('user_stales', WebInterface(lambda: dict((bitcoin_data.pubkey_hash_to_address(ph, node.net.PARENT), prop) for ph, prop in
        p2pool_data.get_user_stale_props(node.tracker, node.best_share_var.value, node.tracker.get_height(node.best_share_var.value)).iteritems())))
    web_root.putChild('fee', WebInterface(lambda: wb.worker_fee))
    web_root.putChild('current_payouts', WebInterface(lambda: dict((bitcoin_data.script2_to_address(script, node.net.PARENT), value/1e8) for script, value in node.get_current_txouts().iteritems())))
    web_root.putChild('patron_sendmany', WebInterface(get_patron_sendmany, 'text/plain'))
    web_root.putChild('global_stats', WebInterface(get_global_stats))
    web_root.putChild('local_stats', WebInterface(get_local_stats))
    web_root.putChild('peer_addresses', WebInterface(lambda: ' '.join('%s%s' % (peer.transport.getPeer().host, ':'+str(peer.transport.getPeer().port) if peer.transport.getPeer().port != node.net.P2P_PORT else '') for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('peer_txpool_sizes', WebInterface(lambda: dict(('%s:%i' % (peer.transport.getPeer().host, peer.transport.getPeer().port), peer.remembered_txs_size) for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('pings', WebInterface(defer.inlineCallbacks(lambda: defer.returnValue(
        dict([(a, (yield b)) for a, b in
            [(
                '%s:%i' % (peer.transport.getPeer().host, peer.transport.getPeer().port),
                defer.inlineCallbacks(lambda peer=peer: defer.returnValue(
                    min([(yield peer.do_ping().addCallback(lambda x: x/0.001).addErrback(lambda fail: None)) for i in xrange(3)])
                ))()
            ) for peer in list(node.p2p_node.peers.itervalues())]
        ])
    ))))
    web_root.putChild('peer_versions', WebInterface(lambda: dict(('%s:%i' % peer.addr, peer.other_sub_version) for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('payout_addr', WebInterface(lambda: bitcoin_data.pubkey_hash_to_address(wb.my_pubkey_hash, node.net.PARENT)))
    web_root.putChild('recent_blocks', WebInterface(lambda: [dict(
        ts=s.timestamp,
        hash='%064x' % s.header_hash,
        number=pack.IntType(24).unpack(s.share_data['coinbase'][1:4]) if len(s.share_data['coinbase']) >= 4 else None,
        share='%064x' % s.hash,
    ) for s in node.tracker.get_chain(node.best_share_var.value, min(node.tracker.get_height(node.best_share_var.value), 24*60*60//node.net.SHARE_PERIOD)) if s.pow_hash <= s.header['bits'].target]))
    web_root.putChild('uptime', WebInterface(lambda: time.time() - start_time))
    web_root.putChild('stale_rates', WebInterface(lambda: p2pool_data.get_stale_counts(node.tracker, node.best_share_var.value, decent_height(), rates=True)))
    
    new_root = resource.Resource()
    web_root.putChild('web', new_root)
    
    stat_log = []
    if os.path.exists(os.path.join(datadir_path, 'stats')):
        try:
            with open(os.path.join(datadir_path, 'stats'), 'rb') as f:
                stat_log = json.loads(f.read())
        except:
            log.err(None, 'Error loading stats:')
    def update_stat_log():
        while stat_log and stat_log[0]['time'] < time.time() - 24*60*60:
            stat_log.pop(0)
        
        lookbehind = 3600//node.net.SHARE_PERIOD
        if node.tracker.get_height(node.best_share_var.value) < lookbehind:
            return None
        
        global_stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        
        stat_log.append(dict(
            time=time.time(),
            pool_hash_rate=p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)/(1-global_stale_prop),
            pool_stale_prop=global_stale_prop,
            local_hash_rates=miner_hash_rates,
            local_dead_hash_rates=miner_dead_hash_rates,
            shares=shares,
            stale_shares=stale_orphan_shares + stale_doa_shares,
            stale_shares_breakdown=dict(orphan=stale_orphan_shares, doa=stale_doa_shares),
            current_payout=node.get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(wb.my_pubkey_hash), 0)*1e-8,
            peers=dict(
                incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
                outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
            ),
            attempts_to_share=bitcoin_data.target_to_average_attempts(node.tracker.items[node.best_share_var.value].max_target),
            attempts_to_block=bitcoin_data.target_to_average_attempts(node.bitcoind_work.value['bits'].target),
            block_value=node.bitcoind_work.value['subsidy']*1e-8,
        ))
        
        with open(os.path.join(datadir_path, 'stats'), 'wb') as f:
            f.write(json.dumps(stat_log))
    x = deferral.RobustLoopingCall(update_stat_log)
    x.start(5*60)
    stop_event.watch(x.stop)
    new_root.putChild('log', WebInterface(lambda: stat_log))
    
    def get_share(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return None
        share = node.tracker.items[int(share_hash_str, 16)]
        
        return dict(
            parent='%064x' % share.previous_hash,
            children=['%064x' % x for x in sorted(node.tracker.reverse.get(share.hash, set()), key=lambda sh: -len(node.tracker.reverse.get(sh, set())))], # sorted from most children to least children
            type_name=type(share).__name__,
            local=dict(
                verified=share.hash in node.tracker.verified.items,
                time_first_seen=start_time if share.time_seen == 0 else share.time_seen,
                peer_first_received_from=share.peer_addr,
            ),
            share_data=dict(
                timestamp=share.timestamp,
                target=share.target,
                max_target=share.max_target,
                payout_address=bitcoin_data.script2_to_address(share.new_script, node.net.PARENT),
                donation=share.share_data['donation']/65535,
                stale_info=share.share_data['stale_info'],
                nonce=share.share_data['nonce'],
                desired_version=share.share_data['desired_version'],
                absheight=share.absheight,
                abswork=share.abswork,
            ),
            block=dict(
                hash='%064x' % share.header_hash,
                header=dict(
                    version=share.header['version'],
                    previous_block='%064x' % share.header['previous_block'],
                    merkle_root='%064x' % share.header['merkle_root'],
                    timestamp=share.header['timestamp'],
                    target=share.header['bits'].target,
                    nonce=share.header['nonce'],
                ),
                gentx=dict(
                    hash='%064x' % share.gentx_hash,
                    coinbase=share.share_data['coinbase'].ljust(2, '\x00').encode('hex'),
                    value=share.share_data['subsidy']*1e-8,
                    last_txout_nonce='%016x' % share.contents['last_txout_nonce'],
                ),
                other_transaction_hashes=['%064x' % x for x in share.get_other_tx_hashes(node.tracker)],
            ),
        )
    new_root.putChild('share', WebInterface(lambda share_hash_str: get_share(share_hash_str)))
    new_root.putChild('heads', WebInterface(lambda: ['%064x' % x for x in node.tracker.heads]))
    new_root.putChild('verified_heads', WebInterface(lambda: ['%064x' % x for x in node.tracker.verified.heads]))
    new_root.putChild('tails', WebInterface(lambda: ['%064x' % x for t in node.tracker.tails for x in node.tracker.reverse.get(t, set())]))
    new_root.putChild('verified_tails', WebInterface(lambda: ['%064x' % x for t in node.tracker.verified.tails for x in node.tracker.verified.reverse.get(t, set())]))
    new_root.putChild('best_share_hash', WebInterface(lambda: '%064x' % node.best_share_var.value))
    new_root.putChild('my_share_hashes', WebInterface(lambda: ['%064x' % my_share_hash for my_share_hash in wb.my_share_hashes]))
    def get_share_data(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return ''
        share = node.tracker.items[int(share_hash_str, 16)]
        return p2pool_data.share_type.pack(share.as_share1a())
    new_root.putChild('share_data', WebInterface(lambda share_hash_str: get_share_data(share_hash_str), 'application/octet-stream'))
    new_root.putChild('currency_info', WebInterface(lambda: dict(
        symbol=node.net.PARENT.SYMBOL,
        block_explorer_url_prefix=node.net.PARENT.BLOCK_EXPLORER_URL_PREFIX,
        address_explorer_url_prefix=node.net.PARENT.ADDRESS_EXPLORER_URL_PREFIX,
        tx_explorer_url_prefix=node.net.PARENT.TX_EXPLORER_URL_PREFIX,
    )))
    new_root.putChild('version', WebInterface(lambda: p2pool.__version__))
    
    hd_path = os.path.join(datadir_path, 'graph_db')
    hd_data = _atomic_read(hd_path)
    hd_obj = {}
    if hd_data is not None:
        try:
            hd_obj = json.loads(hd_data)
        except Exception:
            log.err(None, 'Error reading graph database:')
    dataview_descriptions = {
        'last_hour': graph.DataViewDescription(150, 60*60),
        'last_day': graph.DataViewDescription(300, 60*60*24),
        'last_week': graph.DataViewDescription(300, 60*60*24*7),
        'last_month': graph.DataViewDescription(300, 60*60*24*30),
        'last_year': graph.DataViewDescription(300, 60*60*24*365.25),
    }
    hd = graph.HistoryDatabase.from_obj({
        'local_hash_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False),
        'local_dead_hash_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False),
        'local_share_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False,
            multivalues=True, multivalue_undefined_means_0=True,
            default_func=graph.make_multivalue_migrator(dict(good='local_share_hash_rate', dead='local_dead_share_hash_rate', orphan='local_orphan_share_hash_rate'),
                post_func=lambda bins: [dict((k, (v[0] - (sum(bin.get(rem_k, (0, 0))[0] for rem_k in ['dead', 'orphan']) if k == 'good' else 0), v[1])) for k, v in bin.iteritems()) for bin in bins])),
        'pool_rates': graph.DataStreamDescription(dataview_descriptions, multivalues=True,
            multivalue_undefined_means_0=True),
        'current_payout': graph.DataStreamDescription(dataview_descriptions),
        'current_payouts': graph.DataStreamDescription(dataview_descriptions, multivalues=True),
        'peers': graph.DataStreamDescription(dataview_descriptions, multivalues=True, default_func=graph.make_multivalue_migrator(dict(incoming='incoming_peers', outgoing='outgoing_peers'))),
        'miner_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'miner_dead_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'desired_version_rates': graph.DataStreamDescription(dataview_descriptions, multivalues=True,
            multivalue_undefined_means_0=True),
        'traffic_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'getwork_latency': graph.DataStreamDescription(dataview_descriptions),
        'memory_usage': graph.DataStreamDescription(dataview_descriptions),
    }, hd_obj)
    x = deferral.RobustLoopingCall(lambda: _atomic_write(hd_path, json.dumps(hd.to_obj())))
    x.start(100)
    stop_event.watch(x.stop)
    @wb.pseudoshare_received.watch
    def _(work, dead, user):
        t = time.time()
        hd.datastreams['local_hash_rate'].add_datum(t, work)
        if dead:
            hd.datastreams['local_dead_hash_rate'].add_datum(t, work)
        if user is not None:
            hd.datastreams['miner_hash_rates'].add_datum(t, {user: work})
            if dead:
                hd.datastreams['miner_dead_hash_rates'].add_datum(t, {user: work})
    @wb.share_received.watch
    def _(work, dead, share_hash):
        t = time.time()
        if not dead:
            hd.datastreams['local_share_hash_rates'].add_datum(t, dict(good=work))
        else:
            hd.datastreams['local_share_hash_rates'].add_datum(t, dict(dead=work))
        def later():
            res = node.tracker.is_child_of(share_hash, node.best_share_var.value)
            if res is None: res = False # share isn't connected to sharechain? assume orphaned
            if res and dead: # share was DOA, but is now in sharechain
                # move from dead to good
                hd.datastreams['local_share_hash_rates'].add_datum(t, dict(dead=-work, good=work))
            elif not res and not dead: # share wasn't DOA, and isn't in sharechain
                # move from good to orphan
                hd.datastreams['local_share_hash_rates'].add_datum(t, dict(good=-work, orphan=work))
        reactor.callLater(200, later)
    @node.p2p_node.traffic_happened.watch
    def _(name, bytes):
        hd.datastreams['traffic_rate'].add_datum(time.time(), {name: bytes})
    def add_point():
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.net.CHAIN_LENGTH, 60*60//node.net.SHARE_PERIOD, node.tracker.get_height(node.best_share_var.value))
        t = time.time()
        
        pool_rates = p2pool_data.get_stale_counts(node.tracker, node.best_share_var.value, lookbehind, rates=True)
        pool_total = sum(pool_rates.itervalues())
        hd.datastreams['pool_rates'].add_datum(t, pool_rates)
        
        current_txouts = node.get_current_txouts()
        hd.datastreams['current_payout'].add_datum(t, current_txouts.get(bitcoin_data.pubkey_hash_to_script2(wb.my_pubkey_hash), 0)*1e-8)
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        current_txouts_by_address = dict((bitcoin_data.script2_to_address(script, node.net.PARENT), amount) for script, amount in current_txouts.iteritems())
        hd.datastreams['current_payouts'].add_datum(t, dict((user, current_txouts_by_address[user]*1e-8) for user in miner_hash_rates if user in current_txouts_by_address))
        
        hd.datastreams['peers'].add_datum(t, dict(
            incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
            outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
        ))
        
        vs = p2pool_data.get_desired_version_counts(node.tracker, node.best_share_var.value, lookbehind)
        vs_total = sum(vs.itervalues())
        hd.datastreams['desired_version_rates'].add_datum(t, dict((str(k), v/vs_total*pool_total) for k, v in vs.iteritems()))
        try:
            hd.datastreams['memory_usage'].add_datum(t, memory.resident())
        except:
            if p2pool.DEBUG:
                traceback.print_exc()
    x = deferral.RobustLoopingCall(add_point)
    x.start(5)
    stop_event.watch(x.stop)
    @node.bitcoind_work.changed.watch
    def _(new_work):
        hd.datastreams['getwork_latency'].add_datum(time.time(), new_work['latency'])
    new_root.putChild('graph_data', WebInterface(lambda source, view: hd.datastreams[source].dataviews[view].get_data(time.time())))
    
    web_root.putChild('static', static.File(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'web-static')))
    
    return web_root
