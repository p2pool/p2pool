from __future__ import division

import cgi
import errno
import json
import os
import sys
import time

from twisted.internet import reactor, task
from twisted.python import log
from twisted.web import resource, static

from bitcoin import data as bitcoin_data
from . import data as p2pool_data, graphs
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

def get_web_root(tracker, current_work, current_work2, get_current_txouts, datadir_path, net, get_stale_counts, my_pubkey_hash, local_rate_monitor, worker_fee, p2p_node, my_share_hashes, recent_blocks, pseudoshare_received, share_received):
    start_time = time.time()
    
    web_root = resource.Resource()
    
    def get_rate():
        if tracker.get_height(current_work.value['best_share_hash']) < 720:
            return json.dumps(None)
        return json.dumps(p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], 720)
            / (1 - p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], 720)))
    
    def get_users():
        height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
        weights, total_weight, donation_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 720), 65535*2**256, False)
        res = {}
        for script in sorted(weights, key=lambda s: weights[s]):
            res[bitcoin_data.script2_to_human(script, net.PARENT)] = weights[script]/total_weight
        return json.dumps(res)
    
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
    
    def get_current_payouts():
        return json.dumps(dict((bitcoin_data.script2_to_human(script, net.PARENT), value/1e8) for script, value in get_current_txouts().iteritems()))
    
    def get_patron_sendmany(total=None, trunc='0.01'):
        if total is None:
            return 'need total argument. go to patron_sendmany/<TOTAL>'
        total = int(float(total)*1e8)
        trunc = int(float(trunc)*1e8)
        return json.dumps(dict(
            (bitcoin_data.script2_to_address(script, net.PARENT), value/1e8)
            for script, value in get_current_scaled_txouts(total, trunc).iteritems()
            if bitcoin_data.script2_to_address(script, net.PARENT) is not None
        ))
    
    def get_global_stats():
        # averaged over last hour
        lookbehind = 3600//net.SHARE_PERIOD
        if tracker.get_height(current_work.value['best_share_hash']) < lookbehind:
            return None
        
        nonstale_hash_rate = p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], lookbehind)
        stale_prop = p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], lookbehind)
        return json.dumps(dict(
            pool_nonstale_hash_rate=nonstale_hash_rate,
            pool_hash_rate=nonstale_hash_rate/(1 - stale_prop),
            pool_stale_prop=stale_prop,
        ))
    
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
        
        miner_hash_rates = {}
        miner_dead_hash_rates = {}
        datums, dt = local_rate_monitor.get_datums_in_last()
        for datum in datums:
            miner_hash_rates[datum['user']] = miner_hash_rates.get(datum['user'], 0) + datum['work']/dt
            if datum['dead']:
                miner_dead_hash_rates[datum['user']] = miner_dead_hash_rates.get(datum['user'], 0) + datum['work']/dt
        
        (stale_orphan_shares, stale_doa_shares), shares, _ = get_stale_counts()
        
        return json.dumps(dict(
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
        ))
    
    def get_peer_addresses():
        return ' '.join(peer.transport.getPeer().host + (':' + str(peer.transport.getPeer().port) if peer.transport.getPeer().port != net.P2P_PORT else '') for peer in p2p_node.peers.itervalues())
    
    def get_uptime():
        return json.dumps(time.time() - start_time)
    
    class WebInterface(resource.Resource):
        def __init__(self, func, mime_type, args=()):
            resource.Resource.__init__(self)
            self.func, self.mime_type, self.args = func, mime_type, args
        
        def getChild(self, child, request):
            return WebInterface(self.func, self.mime_type, self.args + (child,))
        
        def render_GET(self, request):
            request.setHeader('Content-Type', self.mime_type)
            request.setHeader('Access-Control-Allow-Origin', '*')
            return self.func(*self.args)
    
    web_root.putChild('rate', WebInterface(get_rate, 'application/json'))
    web_root.putChild('users', WebInterface(get_users, 'application/json'))
    web_root.putChild('fee', WebInterface(lambda: json.dumps(worker_fee), 'application/json'))
    web_root.putChild('current_payouts', WebInterface(get_current_payouts, 'application/json'))
    web_root.putChild('patron_sendmany', WebInterface(get_patron_sendmany, 'text/plain'))
    web_root.putChild('global_stats', WebInterface(get_global_stats, 'application/json'))
    web_root.putChild('local_stats', WebInterface(get_local_stats, 'application/json'))
    web_root.putChild('peer_addresses', WebInterface(get_peer_addresses, 'text/plain'))
    web_root.putChild('peer_versions', WebInterface(lambda: ''.join('%s:%i ' % peer.addr + peer.other_sub_version + '\n' for peer in p2p_node.peers.itervalues()), 'text/plain'))
    web_root.putChild('payout_addr', WebInterface(lambda: json.dumps(bitcoin_data.pubkey_hash_to_address(my_pubkey_hash, net.PARENT)), 'application/json'))
    web_root.putChild('recent_blocks', WebInterface(lambda: json.dumps(recent_blocks), 'application/json'))
    web_root.putChild('uptime', WebInterface(get_uptime, 'application/json'))
    
    try:
        from . import draw
        web_root.putChild('chain_img', WebInterface(lambda: draw.get(tracker, current_work.value['best_share_hash']), 'image/png'))
    except ImportError:
        print "Install Pygame and PIL to enable visualizations! Visualizations disabled."
    
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
        
        miner_hash_rates = {}
        miner_dead_hash_rates = {}
        datums, dt = local_rate_monitor.get_datums_in_last()
        for datum in datums:
            miner_hash_rates[datum['user']] = miner_hash_rates.get(datum['user'], 0) + datum['work']/dt
            if datum['dead']:
                miner_dead_hash_rates[datum['user']] = miner_dead_hash_rates.get(datum['user'], 0) + datum['work']/dt
        
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
    new_root.putChild('log', WebInterface(lambda: json.dumps(stat_log), 'application/json'))
    
    class ShareExplorer(resource.Resource):
        def __init__(self, share_hash):
            self.share_hash = share_hash
        def render_GET(self, request):
            request.setHeader('Content-Type', 'text/html')
            if self.share_hash not in tracker.shares:
                return 'share not known'
            share = tracker.shares[self.share_hash]
            
            format_bits = lambda bits: '%f (bits=%#8x) Work required: %sH</p>' % (bitcoin_data.target_to_difficulty(bits.target), bits.bits, math.format(bitcoin_data.target_to_average_attempts(bits.target)))
            
            request.write('<h1>%s <a href="%x">%s</a></h1>' % (share.__class__.__name__, share.hash, p2pool_data.format_hash(share.hash)))
            if share.previous_hash is not None:
                request.write('<p>Previous: <a href="%x">%s</a>' % (share.previous_hash, p2pool_data.format_hash(share.previous_hash)))
            if tracker.get_height(share.hash) >= 100:
                jump_hash = tracker.get_nth_parent_hash(share.hash, 100)
                if jump_hash is not None:
                    request.write(' (100 jump <a href="%x">%s</a>)' % (jump_hash, p2pool_data.format_hash(jump_hash)))
            request.write('</p>')
            request.write('<p>Next: %s</p>' % (', '.join('<a href="%x">%s</a>' % (next, p2pool_data.format_hash(next)) for next in sorted(tracker.reverse_shares.get(share.hash, set()), key=lambda sh: -len(tracker.reverse_shares.get(sh, set())))),))
            request.write('<p>Verified: %s</p>' % (share.hash in tracker.verified.shares,))
            request.write('<p>Time first seen: %s</p>' % (time.ctime(start_time if share.time_seen == 0 else share.time_seen),))
            request.write('<p>Peer first received from: %s</p>' % ('%s:%i' % share.peer.addr if share.peer is not None else 'self or cache',))
            
            request.write('<h2>Share data</h2>')
            request.write('<p>Timestamp: %s (%i)</p>' % (time.ctime(share.timestamp), share.timestamp))
            request.write('<p>Difficulty: %s</p>' % (format_bits(share.share_info['bits']),))
            request.write('<p>Minimum difficulty: %s</p>' % (format_bits(share.share_info.get('max_bits', share.share_info['bits'])),))
            request.write('<p>Payout script: %s</p>' % (bitcoin_data.script2_to_human(share.new_script, share.net.PARENT),))
            request.write('<p>Donation: %.2f%%</p>' % (share.share_data['donation']/65535*100,))
            request.write('<p>Stale info: %s</p>' % ({0: 'none', 253: 'had an orphan', 254: 'had a dead'}.get(share.share_data['stale_info'], 'unknown %i' % (share.share_data['stale_info'],)),))
            request.write('<p>Nonce: %s</p>' % (cgi.escape(repr(share.share_data['nonce'])),))
            
            request.write('<h2>Block header</h2>')
            request.write('<p>Hash: <a href="%s%064x">%064x</a></p>' % (net.PARENT.BLOCK_EXPLORER_URL_PREFIX, share.header_hash, share.header_hash))
            request.write('<p>Version: %i</p>' % (share.header['version'],))
            request.write('<p>Previous block: <a href="%s%064x">%064x</a></p>' % (net.PARENT.BLOCK_EXPLORER_URL_PREFIX, share.header['previous_block'], share.header['previous_block']))
            request.write('<p>Timestamp: %s (%i)</p>' % (time.ctime(share.header['timestamp']), share.header['timestamp']))
            request.write('<p>Difficulty: %f (bits=%#8x) Work: %sH</p>' % (bitcoin_data.target_to_difficulty(share.header['bits'].target), share.header['bits'].bits, math.format(bitcoin_data.target_to_average_attempts(share.header['bits'].target))))
            request.write('<p>Nonce: %i</p>' % (share.header['nonce'],))
            if share.other_txs is not None:
                tx_count = len(share.other_txs)
            elif len(share.merkle_link['branch']) == 0:
                tx_count = 1
            else:
                tx_count = 'between %i and %i' % (2**len(share.merkle_link['branch'])//2+1, 2**len(share.merkle_link['branch']))
            request.write('<p>Transactions: %s</p>' % (tx_count,))
            coinbase = share.share_data['coinbase'].ljust(2, '\x00')
            request.write('<p>Coinbase: %s %s</p>' % (cgi.escape(repr(coinbase)), coinbase.encode('hex')))
            request.write('<p>Generation value: %.8f %s</p>' % (share.share_data['subsidy']*1e-8, net.PARENT.SYMBOL))
            #request.write('<p>Generation txn: %32x</p>' % (share.gentx_hash,))
            
            return ''
    class Explorer(resource.Resource):
        def render_GET(self, request):
            if not request.path.endswith('/'):
                request.redirect(request.path + '/')
                return ''
            request.setHeader('Content-Type', 'text/html')
            request.write('<h1>P2Pool share explorer</h1>')
            
            request.write('<h2>Verified heads</h2>')
            request.write('<ul>')
            for h in tracker.verified.heads:
                request.write('<li><a href="%x">%s%s</a></li>' % (h, p2pool_data.format_hash(h), ' BEST' if h == current_work.value['best_share_hash'] else ''))
            request.write('</ul>')
            
            request.write('<h2>Verified tails</h2>')
            request.write('<ul>')
            for tail in tracker.verified.tails:
                for h in tracker.reverse_shares.get(tail, set()):
                    request.write('<li><a href="%x">%s%s</a></li>' % (h, p2pool_data.format_hash(h), ' BEST' if h == current_work.value['best_share_hash'] else ''))
            request.write('</ul>')
            
            request.write('<h2>Heads</h2>')
            request.write('<ul>')
            for h in tracker.heads:
                request.write('<li><a href="%x">%s%s</a></li>' % (h, p2pool_data.format_hash(h), ' BEST' if h == current_work.value['best_share_hash'] else ''))
            request.write('</ul>')
            
            request.write('<h2>Tails</h2>')
            request.write('<ul>')
            for tail in tracker.tails:
                for h in tracker.reverse_shares.get(tail, set()):
                    request.write('<li><a href="%x">%s%s</a></li>' % (h, p2pool_data.format_hash(h), ' BEST' if h == current_work.value['best_share_hash'] else ''))
            request.write('</ul>')
            
            return ''
        def getChild(self, child, request):
            if not child:
                return self
            return ShareExplorer(int(child, 16))
    new_root.putChild('explorer', Explorer())
    
    grapher = graphs.Grapher(os.path.join(datadir_path, 'rrd'))
    web_root.putChild('graphs', grapher.get_resource())
    def add_point():
        if tracker.get_height(current_work.value['best_share_hash']) < 720:
            return
        nonstalerate = p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], 720)
        poolrate = nonstalerate / (1 - p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], 720))
        grapher.add_poolrate_point(poolrate, poolrate - nonstalerate)
    task.LoopingCall(add_point).start(100)
    @pseudoshare_received.watch
    def _(work, dead, user, had_vip_pass):
        reactor.callLater(1, grapher.add_localrate_point, work, dead)
        if user is not None and had_vip_pass:
            reactor.callLater(1, grapher.add_localminer_point, user, work, dead)
    
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
    def combine_and_keep_largest(*dicts):
        res = {}
        for d in dicts:
            for k, v in d.iteritems():
                res[k] = res.get(k, 0) + v
        return dict((k, v) for k, v in sorted(res.iteritems(), key=lambda (k, v): v)[-30:] if v)
    hd = graph.HistoryDatabase.from_obj({
        'local_hash_rate': graph.DataStreamDescription(False, dataview_descriptions),
        'local_dead_hash_rate': graph.DataStreamDescription(False, dataview_descriptions),
        'local_share_hash_rate': graph.DataStreamDescription(False, dataview_descriptions),
        'local_dead_share_hash_rate': graph.DataStreamDescription(False, dataview_descriptions),
        'pool_rate': graph.DataStreamDescription(True, dataview_descriptions),
        'pool_stale_rate': graph.DataStreamDescription(True, dataview_descriptions),
        'current_payout': graph.DataStreamDescription(True, dataview_descriptions),
        'incoming_peers': graph.DataStreamDescription(True, dataview_descriptions),
        'outgoing_peers': graph.DataStreamDescription(True, dataview_descriptions),
        'miner_hash_rates': graph.DataStreamDescription(False, dataview_descriptions, {}, combine_and_keep_largest, math.mult_dict),
        'miner_dead_hash_rates': graph.DataStreamDescription(False, dataview_descriptions, {}, combine_and_keep_largest, math.mult_dict),
    }, hd_obj)
    task.LoopingCall(lambda: _atomic_write(hd_path, json.dumps(hd.to_obj()))).start(100)
    @pseudoshare_received.watch
    def _(work, dead, user, had_vip_pass):
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
        hd.datastreams['current_payout'].add_datum(t, get_current_txouts().get(bitcoin_data.pubkey_hash_to_script2(my_pubkey_hash), 0)*1e-8)
        hd.datastreams['incoming_peers'].add_datum(t, sum(1 for peer in p2p_node.peers.itervalues() if peer.incoming))
        hd.datastreams['outgoing_peers'].add_datum(t, sum(1 for peer in p2p_node.peers.itervalues() if not peer.incoming))
    task.LoopingCall(add_point).start(5)
    new_root.putChild('graph_data', WebInterface(lambda source, view: json.dumps(hd.datastreams[source].dataviews[view].get_data(time.time())), 'application/json'))
    
    web_root.putChild('static', static.File(os.path.join(os.path.dirname(sys.argv[0]), 'web-static')))
    
    return web_root
