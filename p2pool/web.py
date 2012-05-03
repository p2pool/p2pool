from __future__ import division

import errno
import json
import os
import sys
import time

from twisted.internet import task
from twisted.python import log
from twisted.web import resource, static

from bitcoin import data as bitcoin_data
from . import data as p2pool_data
from util import graph, math

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
    except os.error: # windows can't overwrite
        os.remove(filename)
        os.rename(filename + '.new', filename)

def get_web_root(tracker, current_work, current_work2, get_current_txouts, datadir_path, net, get_stale_counts, my_pubkey_hash, local_rate_monitor, worker_fee, p2p_node, my_share_hashes, pseudoshare_received, share_received):
    start_time = time.time()
    
    web_root = resource.Resource()
    
    def get_users():
        height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
        weights, total_weight, donation_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 720), 65535*2**256)
        res = {}
        for script in sorted(weights, key=lambda s: weights[s]):
            res[bitcoin_data.script2_to_address(script, net.PARENT)] = weights[script]/total_weight
        return res
    
    def get_current_scaled_txouts(scale, trunc=0):
        txouts = get_current_txouts()
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
        return dict(
            (bitcoin_data.script2_to_address(script, net.PARENT), value/1e8)
            for script, value in get_current_scaled_txouts(total, trunc).iteritems()
            if bitcoin_data.script2_to_address(script, net.PARENT) is not None
        )
    
    def get_local_rates():
        miner_hash_rates = {}
        miner_dead_hash_rates = {}
        datums, dt = local_rate_monitor.get_datums_in_last()
        for datum in datums:
            miner_hash_rates[datum['user']] = miner_hash_rates.get(datum['user'], 0) + datum['work']/dt
            if datum['dead']:
                miner_dead_hash_rates[datum['user']] = miner_dead_hash_rates.get(datum['user'], 0) + datum['work']/dt
        return miner_hash_rates, miner_dead_hash_rates
    
    def get_global_stats():
        # averaged over last hour
        lookbehind = 3600//net.SHARE_PERIOD
        if tracker.get_height(current_work.value['best_share_hash']) < lookbehind:
            return None
        
        nonstale_hash_rate = p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], lookbehind)
        stale_prop = p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], lookbehind)
        return dict(
            pool_nonstale_hash_rate=nonstale_hash_rate,
            pool_hash_rate=nonstale_hash_rate/(1 - stale_prop),
            pool_stale_prop=stale_prop,
            min_difficulty=bitcoin_data.target_to_difficulty(tracker.shares[current_work.value['best_share_hash']].max_target),
        )
    
    def get_local_stats():
        lookbehind = 3600//net.SHARE_PERIOD
        if tracker.get_height(current_work.value['best_share_hash']) < lookbehind:
            return None
        
        global_stale_prop = p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], lookbehind)
        
        my_unstale_count = sum(1 for share in tracker.get_chain(current_work.value['best_share_hash'], lookbehind) if share.hash in my_share_hashes)
        my_orphan_count = sum(1 for share in tracker.get_chain(current_work.value['best_share_hash'], lookbehind) if share.hash in my_share_hashes and share.share_data['stale_info'] == 253)
        my_doa_count = sum(1 for share in tracker.get_chain(current_work.value['best_share_hash'], lookbehind) if share.hash in my_share_hashes and share.share_data['stale_info'] == 254)
        my_share_count = my_unstale_count + my_orphan_count + my_doa_count
        my_stale_count = my_orphan_count + my_doa_count
        
        my_stale_prop = my_stale_count/my_share_count if my_share_count != 0 else None
        
        my_work = sum(bitcoin_data.target_to_average_attempts(share.target)
            for share in tracker.get_chain(current_work.value['best_share_hash'], lookbehind - 1)
            if share.hash in my_share_hashes)
        actual_time = (tracker.shares[current_work.value['best_share_hash']].timestamp -
            tracker.shares[tracker.get_nth_parent_hash(current_work.value['best_share_hash'], lookbehind - 1)].timestamp)
        share_att_s = my_work / actual_time
        
        miner_hash_rates, miner_dead_hash_rates = get_local_rates()
        (stale_orphan_shares, stale_doa_shares), shares, _ = get_stale_counts()
        
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
            efficiency_if_miner_perfect=(1 - stale_orphan_shares/shares)/(1 - global_stale_prop) if shares else None, # ignores dead shares because those are miner's fault and indicated by pseudoshare rejection
            efficiency=(1 - (stale_orphan_shares+stale_doa_shares)/shares)/(1 - global_stale_prop) if shares else None,
            peers=dict(
                incoming=sum(1 for peer in p2p_node.peers.itervalues() if peer.incoming),
                outgoing=sum(1 for peer in p2p_node.peers.itervalues() if not peer.incoming),
            ),
            shares=dict(
                total=shares,
                orphan=stale_orphan_shares,
                dead=stale_doa_shares,
            ),
            uptime=time.time() - start_time,
            block_value=current_work2.value['subsidy']*1e-8,
            warnings=p2pool_data.get_warnings(tracker, current_work, net),
        )
    
    class WebInterface(resource.Resource):
        def __init__(self, func, mime_type='application/json', args=()):
            resource.Resource.__init__(self)
            self.func, self.mime_type, self.args = func, mime_type, args
        
        def getChild(self, child, request):
            return WebInterface(self.func, self.mime_type, self.args + (child,))
        
        def render_GET(self, request):
            request.setHeader('Content-Type', self.mime_type)
            request.setHeader('Access-Control-Allow-Origin', '*')
            res = self.func(*self.args)
            return json.dumps(res) if self.mime_type == 'application/json' else res
    
    web_root.putChild('rate', WebInterface(lambda: p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], 720)/(1-p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], 720))))
    web_root.putChild('difficulty', WebInterface(lambda: bitcoin_data.target_to_difficulty(tracker.shares[current_work.value['best_share_hash']].max_target)))
    web_root.putChild('users', WebInterface(get_users))
    web_root.putChild('fee', WebInterface(lambda: worker_fee))
    web_root.putChild('current_payouts', WebInterface(lambda: dict((bitcoin_data.script2_to_address(script, net.PARENT), value/1e8) for script, value in get_current_txouts().iteritems())))
    web_root.putChild('patron_sendmany', WebInterface(get_patron_sendmany, 'text/plain'))
    web_root.putChild('global_stats', WebInterface(get_global_stats))
    web_root.putChild('local_stats', WebInterface(get_local_stats))
    web_root.putChild('peer_addresses', WebInterface(lambda: ' '.join(peer.transport.getPeer().host + (':' + str(peer.transport.getPeer().port) if peer.transport.getPeer().port != net.P2P_PORT else '') for peer in p2p_node.peers.itervalues()), 'text/plain'))
    web_root.putChild('peer_versions', WebInterface(lambda: ''.join('%s:%i ' % peer.addr + peer.other_sub_version + '\n' for peer in p2p_node.peers.itervalues()), 'text/plain'))
    web_root.putChild('payout_addr', WebInterface(lambda: bitcoin_data.pubkey_hash_to_address(my_pubkey_hash, net.PARENT)))
    web_root.putChild('recent_blocks', WebInterface(lambda: [dict(ts=s.timestamp, hash='%064x' % s.header_hash) for s in tracker.get_chain(current_work.value['best_share_hash'], 24*60*60//net.SHARE_PERIOD) if s.pow_hash <= s.header['bits'].target]))
    web_root.putChild('uptime', WebInterface(lambda: time.time() - start_time))
    
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
        
        lookbehind = 3600//net.SHARE_PERIOD
        if tracker.get_height(current_work.value['best_share_hash']) < lookbehind:
            return None
        
        global_stale_prop = p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], lookbehind)
        (stale_orphan_shares, stale_doa_shares), shares, _ = get_stale_counts()
        miner_hash_rates, miner_dead_hash_rates = get_local_rates()
        
        stat_log.append(dict(
            time=time.time(),
            pool_hash_rate=p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], lookbehind)/(1-global_stale_prop),
            pool_stale_prop=global_stale_prop,
            local_hash_rates=miner_hash_rates,
            local_dead_hash_rates=miner_dead_hash_rates,
            shares=shares,
            stale_shares=stale_orphan_shares + stale_doa_shares,
            stale_shares_breakdown=dict(orphan=stale_orphan_shares, doa=stale_doa_shares),
            current_payout=get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(my_pubkey_hash), 0)*1e-8,
            peers=dict(
                incoming=sum(1 for peer in p2p_node.peers.itervalues() if peer.incoming),
                outgoing=sum(1 for peer in p2p_node.peers.itervalues() if not peer.incoming),
            ),
            attempts_to_share=bitcoin_data.target_to_average_attempts(tracker.shares[current_work.value['best_share_hash']].max_target),
            attempts_to_block=bitcoin_data.target_to_average_attempts(current_work.value['bits'].target),
            block_value=current_work2.value['subsidy']*1e-8,
        ))
        
        with open(os.path.join(datadir_path, 'stats'), 'wb') as f:
            f.write(json.dumps(stat_log))
    task.LoopingCall(update_stat_log).start(5*60)
    new_root.putChild('log', WebInterface(lambda: stat_log))
    
    def get_share(share_hash_str):
        if int(share_hash_str, 16) not in tracker.shares:
            return None
        share = tracker.shares[int(share_hash_str, 16)]
        
        return dict(
            parent='%064x' % share.previous_hash,
            children=['%064x' % x for x in sorted(tracker.reverse_shares.get(share.hash, set()), key=lambda sh: -len(tracker.reverse_shares.get(sh, set())))], # sorted from most children to least children
            local=dict(
                verified=share.hash in tracker.verified.shares,
                time_first_seen=start_time if share.time_seen == 0 else share.time_seen,
                peer_first_received_from=share.peer.addr if share.peer is not None else None,
            ),
            share_data=dict(
                timestamp=share.timestamp,
                target=share.target,
                max_target=share.max_target,
                payout_address=bitcoin_data.script2_to_address(share.new_script, net.PARENT),
                donation=share.share_data['donation']/65535,
                stale_info=share.share_data['stale_info'],
                nonce=share.share_data['nonce'],
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
                ),
                txn_count_range=[len(share.other_txs), len(share.other_txs)] if share.other_txs is not None else 1 if len(share.merkle_link['branch']) == 0 else [2**len(share.merkle_link['branch'])//2+1, 2**len(share.merkle_link['branch'])],
            ),
        )
    new_root.putChild('share', WebInterface(lambda share_hash_str: get_share(share_hash_str)))
    new_root.putChild('heads', WebInterface(lambda: ['%064x' % x for x in tracker.heads]))
    new_root.putChild('verified_heads', WebInterface(lambda: ['%064x' % x for x in tracker.verified.heads]))
    new_root.putChild('tails', WebInterface(lambda: ['%064x' % x for t in tracker.tails for x in tracker.reverse_shares.get(t, set())]))
    new_root.putChild('verified_tails', WebInterface(lambda: ['%064x' % x for t in tracker.verified.tails for x in tracker.verified.reverse_shares.get(t, set())]))
    new_root.putChild('best_share_hash', WebInterface(lambda: '%064x' % current_work.value['best_share_hash']))
    
    class Explorer(resource.Resource):
        def render_GET(self, request):
            return 'moved to /static/'
        def getChild(self, child, request):
            return self
    new_root.putChild('explorer', Explorer())
    
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
        'local_share_hash_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False),
        'local_dead_share_hash_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False),
        'pool_rate': graph.DataStreamDescription(dataview_descriptions),
        'pool_stale_rate': graph.DataStreamDescription(dataview_descriptions),
        'current_payout': graph.DataStreamDescription(dataview_descriptions),
        'current_payouts': graph.DataStreamDescription(dataview_descriptions, multivalues=True),
        'incoming_peers': graph.DataStreamDescription(dataview_descriptions),
        'outgoing_peers': graph.DataStreamDescription(dataview_descriptions),
        'miner_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'miner_dead_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'desired_versions': graph.DataStreamDescription(dataview_descriptions, multivalues=True),
    }, hd_obj)
    task.LoopingCall(lambda: _atomic_write(hd_path, json.dumps(hd.to_obj()))).start(100)
    @pseudoshare_received.watch
    def _(work, dead, user):
        t = time.time()
        hd.datastreams['local_hash_rate'].add_datum(t, work)
        if dead:
            hd.datastreams['local_dead_hash_rate'].add_datum(t, work)
        if user is not None:
            hd.datastreams['miner_hash_rates'].add_datum(t, {user: work})
            if dead:
                hd.datastreams['miner_dead_hash_rates'].add_datum(t, {user: work})
    @share_received.watch
    def _(work, dead):
        t = time.time()
        hd.datastreams['local_share_hash_rate'].add_datum(t, work)
        if dead:
            hd.datastreams['local_dead_share_hash_rate'].add_datum(t, work)
    def add_point():
        if tracker.get_height(current_work.value['best_share_hash']) < 720:
            return
        nonstalerate = p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], 720)
        poolrate = nonstalerate / (1 - p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], 720))
        t = time.time()
        hd.datastreams['pool_rate'].add_datum(t, poolrate)
        hd.datastreams['pool_stale_rate'].add_datum(t, poolrate - nonstalerate)
        current_txouts = get_current_txouts()
        hd.datastreams['current_payout'].add_datum(t, current_txouts.get(bitcoin_data.pubkey_hash_to_script2(my_pubkey_hash), 0)*1e-8)
        miner_hash_rates, miner_dead_hash_rates = get_local_rates()
        current_txouts_by_address = dict((bitcoin_data.script2_to_address(script, net.PARENT), amount) for script, amount in current_txouts.iteritems())
        hd.datastreams['current_payouts'].add_datum(t, dict((user, current_txouts_by_address[user]*1e-8) for user in miner_hash_rates if user in current_txouts_by_address))
        hd.datastreams['incoming_peers'].add_datum(t, sum(1 for peer in p2p_node.peers.itervalues() if peer.incoming))
        hd.datastreams['outgoing_peers'].add_datum(t, sum(1 for peer in p2p_node.peers.itervalues() if not peer.incoming))
        
        vs = p2pool_data.get_desired_version_counts(tracker, current_work.value['best_share_hash'], 720)
        vs_total = sum(vs.itervalues())
        hd.datastreams['desired_versions'].add_datum(t, dict((str(k), v/vs_total) for k, v in vs.iteritems()))
    task.LoopingCall(add_point).start(5)
    new_root.putChild('graph_data', WebInterface(lambda source, view: hd.datastreams[source].dataviews[view].get_data(time.time())))
    
    web_root.putChild('static', static.File(os.path.join(os.path.dirname(sys.argv[0]), 'web-static')))
    
    return web_root
