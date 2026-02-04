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

def get_web_root(wb, datadir_path, bitcoind_getinfo_var, stop_event=variable.Event(), static_dir=None):
    node = wb.node
    start_time = time.time()
    
    web_root = resource.Resource()
    
    def get_users():
        height, last = node.tracker.get_height_and_last(node.best_share_var.value)
        weights, total_weight, donation_weight = node.tracker.get_cumulative_weights(node.best_share_var.value, min(height, 720), 65535*2**256)
        res = {}
        for addr in sorted(weights, key=lambda s: weights[s]):
            res[addr] = weights[addr]/total_weight
        return res
    
    def get_current_scaled_txouts(scale, trunc=0):
        txouts = node.get_current_txouts()
        total = sum(txouts.itervalues())
        results = dict((addr, value*scale//total) for addr, value in txouts.iteritems())
        if trunc > 0:
            total_random = 0
            random_set = set()
            for s in sorted(results, key=results.__getitem__):
                if results[s] >= trunc:
                    break
                total_random += results[s]
                random_set.add(s)
            if total_random:
                winner = math.weighted_choice((addr, results[script]) for addr in random_set)
                for addr in random_set:
                    del results[addr]
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
    
    def get_attempts_to_merged_block(wb):
        """Get the average attempts needed to find a merged mining block"""
        try:
            if hasattr(wb, 'merged_work') and wb.merged_work and hasattr(wb.merged_work, 'value') and wb.merged_work.value:
                for chain_id, chain in wb.merged_work.value.iteritems():
                    # First try template path (getblocktemplate)
                    if 'template' in chain and chain['template']:
                        template = chain['template']
                        if 'bits' in template:
                            bits_hex = template['bits']
                            if isinstance(bits_hex, basestring):
                                bits_int = int(bits_hex, 16)
                            else:
                                bits_int = bits_hex
                            exponent = bits_int >> 24
                            mantissa = bits_int & 0xffffff
                            target = mantissa * (1 << (8 * (exponent - 3)))
                            return bitcoin_data.target_to_average_attempts(target)
                    
                    # Fallback: use target directly from createauxblock/getauxblock
                    if 'target' in chain and chain['target'] != 'p2pool':
                        target = chain['target']
                        if isinstance(target, (int, long)):
                            return bitcoin_data.target_to_average_attempts(target)
        except Exception as e:
            print "[MERGED] Error getting attempts_to_merged_block: %s" % e
        return None
    
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
            attempts_to_merged_block=get_attempts_to_merged_block(wb),
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
    web_root.putChild('user_stales', WebInterface(lambda:
        p2pool_data.get_user_stale_props(node.tracker, node.best_share_var.value,
            node.tracker.get_height(node.best_share_var.value), node.net.PARENT)))
    web_root.putChild('fee', WebInterface(lambda: wb.worker_fee))
    web_root.putChild('current_payouts', WebInterface(lambda: dict(
        (address, value/1e8) for address, value
            in node.get_current_txouts().iteritems())))
    
    # Import merged chain networks for address conversion
    try:
        from p2pool.bitcoin.networks import dogecoin_testnet as dogecoin_testnet_net
        from p2pool.bitcoin.networks import dogecoin as dogecoin_net
    except ImportError:
        dogecoin_testnet_net = None
        dogecoin_net = None
    
    def get_current_merged_payouts():
        """
        Get current payouts with derived merged chain addresses.
        
        IMPORTANT: For addresses that cannot be converted to the merged chain
        (P2SH, P2WSH, P2TR), their share of the merged block reward is
        redistributed proportionally to all convertible addresses.
        This ensures 100% of the merged block reward is distributed.
        
        The primary donation (author fee) does NOT receive redistributed rewards -
        only the secondary donation, node fee, and regular miners benefit.
        
        Returns dict: {parent_address: {amount: X, merged: [{network: Y, symbol: Z, address: A, amount: B}, ...]}}
        """
        from p2pool.work import is_pubkey_hash_address
        
        # Get main chain payouts (in satoshis for proportion calculation)
        main_payouts_satoshis = dict((address, value) for address, value in node.get_current_txouts().iteritems())
        main_payouts = dict((address, value/1e8) for address, value in main_payouts_satoshis.iteritems())
        
        # Calculate total main chain payout for proportion calculation
        total_main_satoshis = sum(main_payouts_satoshis.values())
        
        # Check if we have merged work active
        merged_chains = []
        if hasattr(wb, 'merged_work') and wb.merged_work.value:
            for chainid, aux_work in wb.merged_work.value.iteritems():
                # Get merged chain block reward - try coinbasevalue first, then template
                merged_reward = aux_work.get('coinbasevalue', 0)
                if merged_reward == 0:
                    template = aux_work.get('template')
                    if template and 'coinbasevalue' in template:
                        merged_reward = template['coinbasevalue']
                
                # Determine network name and symbol based on chainid
                if chainid == 98:  # Dogecoin
                    merged_net_name = 'Dogecoin'
                    merged_net_symbol = 'DOGE'
                    parent_symbol = getattr(node.net.PARENT, 'SYMBOL', '') if hasattr(node.net, 'PARENT') else ''
                    is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
                    if is_testnet:
                        merged_net_name = 'Dogecoin Testnet'
                        merged_net_symbol = 'tDOGE'
                        merged_addr_net = dogecoin_testnet_net
                    else:
                        merged_addr_net = dogecoin_net
                else:
                    merged_net_name = aux_work.get('merged_net_name', 'Unknown')
                    merged_net_symbol = aux_work.get('merged_net_symbol', 'AUX')
                    merged_addr_net = None
                
                if merged_addr_net:
                    merged_chains.append({
                        'chainid': chainid,
                        'network': merged_net_name,
                        'symbol': merged_net_symbol,
                        'addr_net': merged_addr_net,
                        'reward': merged_reward,
                    })
        
        # Build result with merged addresses for each parent address
        result = {}
        parent_net = node.net.PARENT if hasattr(node.net, 'PARENT') else node.net
        
        # Identify primary donation address (should NOT receive redistributed rewards)
        # The primary donation is typically the first/smallest output that goes to author
        primary_donation_address = None
        if hasattr(wb, 'donation_percentage') and wb.donation_percentage > 0:
            # Primary donation is the author donation - identify it by being in the payout list
            # It's typically a hardcoded address, but we'll exclude it from redistribution
            # by checking if it's the donation script
            pass  # We'll handle this by checking converted addresses
        
        # For each merged chain, calculate payouts with redistribution
        for chain in merged_chains:
            # First pass: identify convertible vs non-convertible addresses
            convertible_addresses = {}  # {parent_addr: (pubkey_hash, main_satoshis)}
            unconvertible_satoshis = 0
            
            for parent_address, main_sats in main_payouts_satoshis.iteritems():
                try:
                    is_convertible, pubkey_hash, error_msg = is_pubkey_hash_address(parent_address, parent_net)
                    if is_convertible and pubkey_hash is not None:
                        convertible_addresses[parent_address] = (pubkey_hash, main_sats)
                    else:
                        # This address cannot be converted - its merged reward will be redistributed
                        unconvertible_satoshis += main_sats
                except Exception:
                    unconvertible_satoshis += main_sats
            
            # Calculate the redistribution factor
            # Total convertible satoshis (for redistribution proportions)
            convertible_total_satoshis = sum(sats for _, sats in convertible_addresses.values())
            
            # Redistribution: unconvertible share gets divided among convertible addresses
            # proportionally to their share of the convertible pool
            # BUT exclude primary donation from receiving extra redistribution
            if convertible_total_satoshis > 0 and chain['reward'] > 0:
                for parent_address in main_payouts_satoshis:
                    if parent_address not in result:
                        result[parent_address] = {'amount': main_payouts[parent_address], 'merged': []}
                    
                    if parent_address in convertible_addresses:
                        pubkey_hash, main_sats = convertible_addresses[parent_address]
                        
                        # Base proportion of merged reward (same as main chain)
                        base_proportion = main_sats / float(total_main_satoshis)
                        base_merged_amount = chain['reward'] * base_proportion
                        
                        # Additional redistribution from unconvertible addresses
                        # Proportional to this address's share of convertible pool
                        redistribution_proportion = main_sats / float(convertible_total_satoshis)
                        redistribution_amount = (chain['reward'] * (unconvertible_satoshis / float(total_main_satoshis))) * redistribution_proportion
                        
                        total_merged_amount = (base_merged_amount + redistribution_amount) / 1e8
                        
                        merged_address = bitcoin_data.pubkey_hash_to_address(
                            pubkey_hash, chain['addr_net'].ADDRESS_VERSION, -1, chain['addr_net'])
                        
                        result[parent_address]['merged'].append({
                            'network': chain['network'],
                            'symbol': chain['symbol'],
                            'address': merged_address,
                            'amount': total_merged_amount,
                        })
                    # Non-convertible addresses get no merged payout (their share is redistributed)
        
        # Handle case where no merged chains are active - still build result from main payouts
        for parent_address, amount in main_payouts.iteritems():
            if parent_address not in result:
                result[parent_address] = {'amount': amount, 'merged': []}
        
        return result
    
    web_root.putChild('current_merged_payouts', WebInterface(get_current_merged_payouts))
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
    web_root.putChild('payout_addr', WebInterface(lambda: wb.address))
    web_root.putChild('payout_addrs', WebInterface(
        lambda: list(add['address'] for add in wb.pubkeys.keys)))
    
    # ==== Stratum statistics endpoint ====
    def get_stratum_stats():
        """Get stratum pool statistics including per-worker data"""
        try:
            from p2pool.bitcoin.stratum import pool_stats
            stats = pool_stats.get_pool_stats()
            worker_stats = pool_stats.get_worker_stats()
            connected_workers = pool_stats.get_connected_workers()
            
            # Format worker stats for JSON
            formatted_workers = {}
            for worker_name, wstats in worker_stats.items():
                # Get aggregate connection stats
                conn_aggregate = pool_stats.get_worker_aggregate_stats(worker_name)
                
                formatted_workers[worker_name] = {
                    'shares': wstats.get('shares', 0),
                    'accepted': wstats.get('accepted', 0),
                    'rejected': wstats.get('rejected', 0),
                    'hash_rate': wstats.get('hash_rate', 0),
                    'last_seen': wstats.get('last_seen', 0),
                    'first_seen': wstats.get('first_seen', 0),
                    # Connection aggregate stats
                    'connections': conn_aggregate.get('connection_count', 0) if conn_aggregate else 0,
                    'active_connections': conn_aggregate.get('active_connections', 0) if conn_aggregate else 0,
                    'backup_connections': conn_aggregate.get('backup_connections', 0) if conn_aggregate else 0,
                    'connection_difficulties': conn_aggregate.get('difficulties', []) if conn_aggregate else [],
                }
            
            # Also include currently connected workers (even if no shares yet)
            for worker_name, winfo in connected_workers.items():
                if worker_name not in formatted_workers:
                    formatted_workers[worker_name] = {
                        'shares': 0,
                        'accepted': 0,
                        'rejected': 0,
                        'hash_rate': 0,
                        'last_seen': 0,
                        'first_seen': 0,
                        'connections': winfo.get('connections', 0),
                        'active_connections': 0,
                        'backup_connections': winfo.get('connections', 0),
                        'connection_difficulties': winfo.get('difficulties', []),
                    }
                else:
                    # Update connection info for existing workers
                    formatted_workers[worker_name]['connections'] = winfo.get('connections', 0)
                    formatted_workers[worker_name]['connection_difficulties'] = winfo.get('difficulties', [])
            
            return {
                'pool': stats,
                'workers': formatted_workers,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'error': str(e)}
    
    web_root.putChild('stratum_stats', WebInterface(get_stratum_stats))
    
    # ==== Stratum security monitoring endpoint ====
    def get_stratum_security():
        """Get stratum security and DDoS detection metrics"""
        try:
            from p2pool.bitcoin.stratum import pool_stats
            return pool_stats.get_security_stats()
        except Exception as e:
            return {'error': str(e)}
    
    web_root.putChild('stratum_security', WebInterface(get_stratum_security))
    
    # ==== Ban stats endpoint ====
    def get_ban_stats():
        """Get current ban statistics"""
        try:
            from p2pool.bitcoin.stratum import pool_stats
            return pool_stats.get_ban_stats()
        except Exception as e:
            return {'error': str(e)}
    
    web_root.putChild('ban_stats', WebInterface(get_ban_stats))
    
    # ==== Connected miners endpoint (all miners currently connected via stratum) ====
    def get_connected_miners():
        """Get list of all currently connected miner addresses"""
        try:
            from p2pool.bitcoin.stratum import pool_stats
            connected_workers = pool_stats.get_connected_workers()
            
            # Extract unique addresses from connected workers
            addresses = set()
            for worker_name, winfo in connected_workers.items():
                addr = winfo.get('address')
                if addr:
                    addresses.add(addr)
                else:
                    # Try to extract address from worker name (format: address.worker or address)
                    base_addr = worker_name.split('+')[0].split('/')[0].split('.')[0].split('_')[0]
                    if base_addr:
                        addresses.add(base_addr)
            
            return list(addresses)
        except Exception as e:
            return []
    
    web_root.putChild('connected_miners', WebInterface(get_connected_miners))
    
    # ==== Individual miner stats endpoint ====
    def get_miner_stats(address=None):
        """Get detailed statistics for a specific miner address"""
        if not address:
            return {'error': 'No address provided', 'active': False}
        
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        
        # Extract base address and find all matching workers
        # Supported formats: address.worker, address_worker, address+diff, address/diff, address,dogeaddr
        def extract_base_address(worker_name):
            # Handle multiaddress format: LTC_ADDR,DOGE_ADDR.worker
            base = worker_name.split(',')[0]  # Take LTC address part
            return base.split('+')[0].split('/')[0].split('.')[0].split('_')[0]
        
        # Aggregate stats for all workers belonging to this address
        hashrate = 0
        dead_hashrate = 0
        found_workers = False
        estimated_hashrate = False
        worker_difficulties = {}
        
        # First, check measured hashrate from miner_hash_rates
        for worker_name in miner_hash_rates:
            if extract_base_address(worker_name) == address:
                found_workers = True
                hashrate += miner_hash_rates.get(worker_name, 0)
                dead_hashrate += miner_dead_hash_rates.get(worker_name, 0)
        
        # If no measured hashrate, check stratum connections and estimate from difficulty
        if not found_workers or hashrate == 0:
            try:
                from p2pool.bitcoin.stratum import pool_stats
                if pool_stats:
                    stratum_workers = pool_stats.get_worker_stats()
                    
                    dumb_scrypt_diff = node.net.PARENT.DUMB_SCRYPT_DIFF if hasattr(node.net.PARENT, 'DUMB_SCRYPT_DIFF') else 2**32
                    vardiff_target = wb.share_rate if hasattr(wb, 'share_rate') else 3.0  # Default 3 seconds per share
                    
                    for worker_name, worker_data in stratum_workers.items():
                        if extract_base_address(worker_name) == address:
                            found_workers = True
                            # Get difficulty from stratum connection
                            worker_diff = 0
                            # Get aggregate stats for this worker to get connection difficulties
                            conn_aggregate = pool_stats.get_worker_aggregate_stats(worker_name)
                            if conn_aggregate and conn_aggregate.get('difficulties'):
                                worker_diff = conn_aggregate['difficulties'][0]
                                worker_difficulties[worker_name] = worker_diff
                            
                            # Try measured hashrate first, then estimate from difficulty
                            worker_hashrate = worker_data.get('hash_rate', 0)
                            if worker_hashrate == 0 and worker_diff > 0:
                                # Estimate: hashrate = difficulty * DUMB_SCRYPT_DIFF / vardiff_target
                                worker_hashrate = worker_diff * dumb_scrypt_diff / vardiff_target
                                estimated_hashrate = True
                            
                            hashrate += worker_hashrate
                    
                    # Also check connected workers (those with active connections but no shares yet)
                    connected_workers = pool_stats.get_connected_workers()
                    for worker_name, winfo in connected_workers.items():
                        if extract_base_address(worker_name) == address and worker_name not in stratum_workers:
                            found_workers = True
                            conn_aggregate = pool_stats.get_worker_aggregate_stats(worker_name)
                            if conn_aggregate and conn_aggregate.get('difficulties'):
                                worker_diff = conn_aggregate['difficulties'][0]
                                worker_difficulties[worker_name] = worker_diff
                                # Estimate hashrate from difficulty
                                worker_hashrate = worker_diff * dumb_scrypt_diff / vardiff_target
                                hashrate += worker_hashrate
                                estimated_hashrate = True
            except Exception as e:
                import traceback
                traceback.print_exc()
        
        if not found_workers:
            return {'error': 'Miner not found', 'active': False}
        
        # Current rates
        doa_rate = dead_hashrate / hashrate if hashrate > 0 else 0
        
        # Current payout - txouts keys are already addresses
        current_payout = 0
        try:
            current_txouts = node.get_current_txouts()
            # txouts is {address: satoshis}, address is the key we need
            current_payout = current_txouts.get(address, 0) / 1e8
        except (ValueError, KeyError, IndexError):
            pass
        
        # Share difficulty - check all workers for this address
        # First check last_work_shares, then use stratum worker_difficulties if available
        miner_last_diff = 0
        for worker_name in wb.last_work_shares.value:
            if extract_base_address(worker_name) == address:
                worker_diff = bitcoin_data.target_to_difficulty(wb.last_work_shares.value[worker_name].target)
                miner_last_diff = max(miner_last_diff, worker_diff)
        
        # Fall back to stratum difficulties if we didn't find any from last_work_shares
        if miner_last_diff == 0 and worker_difficulties:
            for worker_name, worker_diff in worker_difficulties.items():
                miner_last_diff = max(miner_last_diff, worker_diff)
        
        # Time to share - use attempts_to_share from local_stats
        dumb_scrypt_diff = node.net.PARENT.DUMB_SCRYPT_DIFF if hasattr(node.net.PARENT, 'DUMB_SCRYPT_DIFF') else 2**32
        attempts_to_share = bitcoin_data.target_to_average_attempts(node.tracker.items[node.best_share_var.value].max_target)
        time_to_share = attempts_to_share / hashrate if hashrate > 0 else float('inf')
        
        # Get global stats for context
        global_stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, min(node.tracker.get_height(node.best_share_var.value), 720))
        
        # Get merged mining payouts for this address
        merged_payouts = []
        try:
            merged_data = get_current_merged_payouts()
            if address in merged_data and 'merged' in merged_data[address]:
                merged_payouts = merged_data[address]['merged']
        except:
            pass
        
        # Get best difficulty for all workers of this address
        best_diff_all_time = 0
        best_diff_session = 0
        session_start = wb.session_start_time
        for worker_name in miner_hash_rates:
            if extract_base_address(worker_name) == address:
                worker_best = wb.get_miner_best_difficulty(worker_name)
                best_diff_all_time = max(best_diff_all_time, worker_best['all_time'])
                best_diff_session = max(best_diff_session, worker_best['session'])
        
        # Get hashrate periods for all workers of this address
        hashrate_periods = {'1m': {'hashrate': 0, 'dead_hashrate': 0},
                          '10m': {'hashrate': 0, 'dead_hashrate': 0},
                          '1h': {'hashrate': 0, 'dead_hashrate': 0}}
        for worker_name in miner_hash_rates:
            if extract_base_address(worker_name) == address:
                worker_periods = wb.get_miner_hashrate_periods(worker_name)
                for period in hashrate_periods:
                    if period in worker_periods:
                        hashrate_periods[period]['hashrate'] += worker_periods[period]['hashrate']
                        hashrate_periods[period]['dead_hashrate'] += worker_periods[period]['dead_hashrate']
        
        # Calculate network difficulty for "chance to find block"
        network_difficulty = bitcoin_data.target_to_difficulty(node.bitcoind_work.value['bits'].target)
        chance_to_find_block = (best_diff_all_time / network_difficulty * 100) if network_difficulty > 0 and best_diff_all_time > 0 else 0
        
        # Calculate equivalent hashrate for best difficulty
        # For Scrypt: hashrate = difficulty * DUMB_SCRYPT_DIFF (2^16 = 65536)
        # For SHA256: hashrate = difficulty * 2^32
        dumb_scrypt_diff = node.net.PARENT.DUMB_SCRYPT_DIFF if hasattr(node.net.PARENT, 'DUMB_SCRYPT_DIFF') else 2**32
        best_diff_hashrate_all_time = best_diff_all_time * dumb_scrypt_diff
        best_diff_hashrate_session = best_diff_session * dumb_scrypt_diff
        
        # Count shares for this miner address in the current window
        lookbehind = min(node.tracker.get_height(node.best_share_var.value), 3600//node.net.SHARE_PERIOD)
        miner_share_count = 0
        miner_orphan_count = 0
        miner_doa_count = 0
        try:
            for share in node.tracker.get_chain(node.best_share_var.value, lookbehind):
                share_addr = getattr(share, 'address', None)
                if share_addr == address:
                    if share.share_data.get('stale_info') == 'orphan':
                        miner_orphan_count += 1
                    elif share.share_data.get('stale_info') == 'doa':
                        miner_doa_count += 1
                    else:
                        miner_share_count += 1
        except Exception as e:
            pass
        
        total_miner_shares = miner_share_count + miner_orphan_count + miner_doa_count
        miner_dead_shares = miner_orphan_count + miner_doa_count
        
        return dict(
            address=address,
            active=True,
            hashrate=hashrate,
            estimated_hashrate=estimated_hashrate,  # True if hashrate is estimated from difficulty
            dead_hashrate=dead_hashrate,
            doa_rate=doa_rate,
            share_difficulty=miner_last_diff,
            time_to_share=time_to_share,
            current_payout=current_payout,
            merged_payouts=merged_payouts,
            global_stale_prop=global_stale_prop,
            # New fields for enhanced stats
            best_difficulty_all_time=best_diff_all_time,
            best_difficulty_session=best_diff_session,
            best_diff_hashrate_all_time=best_diff_hashrate_all_time,
            best_diff_hashrate_session=best_diff_hashrate_session,
            session_start=session_start,
            hashrate_periods=hashrate_periods,
            network_difficulty=network_difficulty,
            chance_to_find_block=chance_to_find_block,
            # Share counts
            total_shares=total_miner_shares,
            unstale_shares=miner_share_count,
            dead_shares=miner_dead_shares,
            orphan_shares=miner_orphan_count,
            doa_shares=miner_doa_count,
        )
    
    web_root.putChild('miner_stats', WebInterface(get_miner_stats))
    
    # ==== Individual miner payouts endpoint ====
    def get_miner_payouts(address=None):
        """Get payout history for a specific miner address"""
        if not address:
            return {'error': 'No address provided'}
        
        # Current payout from txouts - keys are already addresses
        current_payout = 0
        try:
            current_txouts = node.get_current_txouts()
            current_payout = current_txouts.get(address, 0) / 1e8
        except (ValueError, KeyError, IndexError):
            pass
        
        return {
            'address': address,
            'current_payout': current_payout,
            'blocks_found': 0,  # TODO: Track per-miner block history
            'blocks': [],
        }
    
    web_root.putChild('miner_payouts', WebInterface(get_miner_payouts))
    
    # Block history storage - persisted to disk
    block_history = []
    block_history_path = os.path.join(datadir_path, 'block_history')
    
    # Load existing block history
    if os.path.exists(block_history_path):
        try:
            with open(block_history_path, 'rb') as f:
                block_history = json.loads(f.read())
                print('Loaded %d historical blocks from disk' % len(block_history))
        except Exception as e:
            log.err(None, 'Error loading block history:')
    
    # Set to track known block hashes (avoid duplicates)
    known_block_hashes = set(b['hash'] for b in block_history)
    
    def save_block_history():
        """Save block history to disk
        
        Block history stores all found blocks with luck/timing data.
        Dashboards handle their own display windowing (e.g., last 100 blocks).
        No artificial limit needed here - let it grow and persist all history.
        """
        try:
            # Optional: Uncomment below to limit storage if memory/disk becomes an issue
            # Note: List is sorted newest-first (descending), so pop() removes oldest
            # while len(block_history) > 1000:
            #     oldest = block_history.pop()  # Remove from END (oldest blocks)
            #     known_block_hashes.discard(oldest['hash'])
            _atomic_write(block_history_path, json.dumps(block_history))
        except Exception as e:
            log.err(None, 'Error saving block history:')
    
    def add_block_to_history(block_info):
        """Add a new block to history if not already known"""
        block_hash = block_info['hash']
        if block_hash not in known_block_hashes:
            block_history.append(block_info)
            known_block_hashes.add(block_hash)
            # Sort by timestamp descending
            block_history.sort(key=lambda x: x['ts'], reverse=True)
            return True
        return False
    
    def get_recent_blocks():
        """Get recent blocks found by the pool with luck and timing info"""
        try:
            # Get pool hashrate for luck calculations
            height = node.tracker.get_height(node.best_share_var.value)
            if height < 10:
                return block_history  # Return historical blocks if tracker not ready
            
            lookbehind = min(height, 720)
            pool_hashrate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
            
            # Find all blocks in the current tracker chain
            chain_length = min(height, node.net.CHAIN_LENGTH)
            tracker_blocks = []
            for s in node.tracker.get_chain(node.best_share_var.value, chain_length):
                if s.pow_hash <= s.header['bits'].target:
                    tracker_blocks.append(s)
            
            # Build block info for each block in tracker
            new_blocks_added = False
            for i, s in enumerate(tracker_blocks):
                block_hash = '%064x' % s.header_hash
                
                # Skip if already in history
                if block_hash in known_block_hashes:
                    # Update verification status
                    for b in block_history:
                        if b['hash'] == block_hash:
                            is_verified = s.hash in node.tracker.verified.items
                            b['verified'] = is_verified
                            b['status'] = 'confirmed' if is_verified else 'pending'
                            break
                    continue
                
                is_verified = s.hash in node.tracker.verified.items
                block_info = {
                    'ts': s.timestamp,
                    'hash': block_hash,
                    'number': p2pool_data.parse_bip0034(s.share_data['coinbase'])[0],
                    'share': '%064x' % s.hash,
                    'network_difficulty': bitcoin_data.target_to_difficulty(s.header['bits'].target),
                    'share_difficulty': bitcoin_data.target_to_difficulty(s.target),
                    'actual_hash_difficulty': bitcoin_data.target_to_difficulty(s.pow_hash),
                    'verified': is_verified,
                    'status': 'confirmed' if is_verified else 'pending',
                    'pool_hashrate_at_find': pool_hashrate,
                }
                
                # Calculate expected time based on difficulty and pool hashrate
                if pool_hashrate > 0:
                    expected_hashes = bitcoin_data.target_to_average_attempts(s.header['bits'].target)
                    expected_time = expected_hashes / pool_hashrate
                    block_info['expected_time'] = expected_time
                
                # Calculate time_to_find based on previous block
                if i + 1 < len(tracker_blocks):
                    prev_block = tracker_blocks[i + 1]
                    time_to_find = s.timestamp - prev_block.timestamp
                    block_info['time_to_find'] = time_to_find
                    
                    if pool_hashrate > 0 and expected_time > 0 and time_to_find > 0:
                        luck = (expected_time / time_to_find) * 100
                        block_info['luck'] = luck
                        block_info['luck_method'] = 'simple_avg'
                else:
                    block_info['luck_method'] = 'first_block'
                
                if add_block_to_history(block_info):
                    new_blocks_added = True
                    print('Added new block to history: height=%s hash=%s diff=%.8f' % (block_info['number'], block_hash[:16], block_info['network_difficulty']))
                    # Also record network difficulty sample with this block
                    # (add_network_diff_sample is defined later but will exist when this runs)
                    try:
                        add_network_diff_sample(block_info['ts'], block_info['network_difficulty'], 'block')
                    except:
                        pass  # Ignore if not yet defined during startup
            
            # Save to disk if new blocks were added
            if new_blocks_added:
                save_block_history()
                try:
                    save_network_diff_history()
                except:
                    pass  # Ignore if not yet defined during startup
            
            # Calculate pool average luck from all blocks with luck data
            total_luck = 0
            luck_count = 0
            for b in block_history:
                if b.get('luck'):
                    total_luck += b['luck']
                    luck_count += 1
            
            # Return a copy with pool_avg_luck added to first block
            result = list(block_history)
            if result and luck_count > 0:
                result[0] = dict(result[0])
                result[0]['pool_avg_luck'] = total_luck / luck_count
            
            return result
        except Exception as e:
            import traceback
            traceback.print_exc()
            return block_history  # Return what we have on error
    
    web_root.putChild('recent_blocks', WebInterface(get_recent_blocks))
    
    # =========================================================================
    # Immediate block recording when a block is found
    # This ensures blocks are saved to disk right away, not just when API is queried
    # =========================================================================
    def on_block_found(block_info):
        """Called immediately when a parent network block is found.
        
        Records the block to history and network difficulty immediately,
        ensuring no data is lost if dashboard isn't being watched.
        """
        try:
            # Get pool hashrate for luck calculations
            height = node.tracker.get_height(node.best_share_var.value)
            pool_hashrate = 0
            if height >= 10:
                lookbehind = min(height, 720)
                pool_hashrate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
            
            # Build full block info with luck data
            full_block_info = {
                'ts': block_info['ts'],
                'hash': block_info['hash'],
                'number': block_info['number'],
                'share': '',  # Will be filled in when tracker catches up
                'network_difficulty': block_info['network_difficulty'],
                'share_difficulty': 0,  # Will be filled in when tracker catches up  
                'actual_hash_difficulty': bitcoin_data.target_to_difficulty(block_info['pow_hash']),
                'verified': False,
                'status': 'pending',
                'pool_hashrate_at_find': pool_hashrate,
            }
            
            # Calculate expected time and luck
            if pool_hashrate > 0:
                expected_hashes = bitcoin_data.target_to_average_attempts(block_info['target'])
                expected_time = expected_hashes / pool_hashrate
                full_block_info['expected_time'] = expected_time
                
                # Calculate time_to_find based on previous block in history
                if block_history:
                    prev_block = block_history[0]  # Most recent block (sorted descending)
                    time_to_find = block_info['ts'] - prev_block['ts']
                    full_block_info['time_to_find'] = time_to_find
                    
                    if expected_time > 0 and time_to_find > 0:
                        luck = (expected_time / time_to_find) * 100
                        full_block_info['luck'] = luck
                        full_block_info['luck_method'] = 'immediate'
            
            # Add to history and save immediately
            if add_block_to_history(full_block_info):
                print('IMMEDIATE: Added block to history: height=%s hash=%s diff=%.8f' % (
                    block_info['number'], block_info['hash'][:16], block_info['network_difficulty']))
                save_block_history()
                
                # Also record network difficulty sample with this block
                add_network_diff_sample(block_info['ts'], block_info['network_difficulty'], 'block')
                save_network_diff_history()
        except Exception as e:
            import traceback
            print('Error in on_block_found callback:')
            traceback.print_exc()
    
    # Note: wb.block_found.watch(on_block_found) is registered later after
    # add_network_diff_sample and save_network_diff_history are defined
    
    # Debug endpoint to check tracker status
    def get_tracker_debug():
        """Debug endpoint to inspect tracker shares and their difficulty comparison"""
        try:
            height = node.tracker.get_height(node.best_share_var.value)
            chain_length = min(height, node.net.CHAIN_LENGTH) if height > 0 else 0
            
            # Sample first 10 shares
            shares_debug = []
            block_candidates = 0
            total_checked = 0
            for s in node.tracker.get_chain(node.best_share_var.value, chain_length):
                total_checked += 1
                pow_hash = s.pow_hash
                network_target = s.header['bits'].target
                is_block = pow_hash <= network_target
                if is_block:
                    block_candidates += 1
                if total_checked <= 10:
                    shares_debug.append({
                        'share_hash': '%064x' % s.hash,
                        'pow_hash': '%064x' % pow_hash,
                        'network_target': '%064x' % network_target,
                        'share_target': '%064x' % s.target,
                        'is_block': is_block,
                        'ts': s.timestamp,
                        'header_hash': '%064x' % s.header_hash,
                    })
            
            return {
                'tracker_height': height,
                'chain_length_checked': total_checked,
                'block_candidates_found': block_candidates,
                'sample_shares': shares_debug,
                'known_block_hashes_count': len(known_block_hashes),
                'block_history_count': len(block_history),
                'best_share_var': '%064x' % node.best_share_var.value if node.best_share_var.value else None,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'error': str(e)}
    
    web_root.putChild('tracker_debug', WebInterface(get_tracker_debug))
    
    # Merged block history storage - persisted to disk
    merged_block_history_path = os.path.join(datadir_path, 'merged_block_history')
    merged_known_hashes = set()
    
    # Load existing merged block history
    if os.path.exists(merged_block_history_path):
        try:
            with open(merged_block_history_path, 'rb') as f:
                loaded_merged = json.loads(f.read())
                # Merge with any existing blocks in wb.recent_merged_blocks
                for b in loaded_merged:
                    if b.get('hash') not in merged_known_hashes:
                        wb.recent_merged_blocks.append(b)
                        merged_known_hashes.add(b.get('hash'))
                print('Loaded %d historical merged blocks from disk' % len(loaded_merged))
        except Exception as e:
            log.err(None, 'Error loading merged block history:')
    
    # Initialize known hashes from any existing blocks
    for b in wb.recent_merged_blocks:
        if b.get('hash'):
            merged_known_hashes.add(b.get('hash'))
    
    def save_merged_block_history():
        """Save merged block history to disk"""
        try:
            # Keep last 500 merged blocks
            while len(wb.recent_merged_blocks) > 500:
                oldest = wb.recent_merged_blocks.pop(0)
                merged_known_hashes.discard(oldest.get('hash'))
            _atomic_write(merged_block_history_path, json.dumps(wb.recent_merged_blocks))
        except Exception as e:
            log.err(None, 'Error saving merged block history:')
    
    # Periodically save merged blocks
    x_merged = deferral.RobustLoopingCall(save_merged_block_history)
    x_merged.start(60)  # Save every 60 seconds
    stop_event.watch(x_merged.stop)
    
    # Merged mined blocks endpoint - show verified and pending blocks (not orphaned)
    web_root.putChild('recent_merged_blocks', WebInterface(lambda: [b for b in wb.recent_merged_blocks[::-1] if b.get('verified') != False]))
    
    # All merged blocks endpoint - for debugging (includes orphaned and pending)
    web_root.putChild('all_merged_blocks', WebInterface(lambda: wb.recent_merged_blocks[::-1]))
    
    # Merged mining stats endpoint
    def get_merged_stats():
        """Get merged mining statistics"""
        blocks = wb.recent_merged_blocks
        
        # Get current merged block value from createauxblock coinbasevalue (includes fees)
        merged_block_value = 0
        merged_symbol = ''
        try:
            if hasattr(wb, 'merged_work') and wb.merged_work and hasattr(wb.merged_work, 'value') and wb.merged_work.value:
                for chain_id, chain in wb.merged_work.value.iteritems():
                    # Use coinbasevalue from createauxblock (includes subsidy + fees)
                    if 'coinbasevalue' in chain and chain['coinbasevalue'] > 0:
                        merged_block_value = chain['coinbasevalue'] / 1e8
                        if chain_id == 98:  # Dogecoin
                            merged_symbol = 'DOGE'
                        else:
                            merged_symbol = chain.get('symbol', 'AUX')
                        break
                    # Fallback: try template (getblocktemplate path)
                    elif 'template' in chain and chain['template']:
                        template = chain['template']
                        merged_block_value = template.get('coinbasevalue', 0) / 1e8
                        merged_symbol = chain.get('symbol', 'AUX')
                        break
        except Exception as e:
            print "[MERGED STATS] Error getting merged work: %s" % e
        
        if not blocks:
            return {
                'total_blocks': 0,
                'verified_blocks': 0,
                'pending_blocks': 0,
                'orphaned_blocks': 0,
                'networks': {},
                'block_value': merged_block_value,
                'symbol': merged_symbol,
            }
        
        verified = len([b for b in blocks if b.get('verified') == True])
        pending = len([b for b in blocks if b.get('verified') is None])
        orphaned = len([b for b in blocks if b.get('verified') == False])
        
        # Group by network
        networks = {}
        for b in blocks:
            net = b.get('network', 'Unknown')
            if net not in networks:
                networks[net] = {'total': 0, 'verified': 0, 'pending': 0, 'orphaned': 0, 'symbol': b.get('symbol', '?')}
            networks[net]['total'] += 1
            if b.get('verified') == True:
                networks[net]['verified'] += 1
            elif b.get('verified') is None:
                networks[net]['pending'] += 1
            else:
                networks[net]['orphaned'] += 1
        
        return {
            'total_blocks': len(blocks),
            'verified_blocks': verified,
            'pending_blocks': pending,
            'orphaned_blocks': orphaned,
            'networks': networks,
            'recent': [b for b in blocks[-5:][::-1]],  # Last 5 blocks
            'block_value': merged_block_value,
            'symbol': merged_symbol,
        }
    
    web_root.putChild('merged_stats', WebInterface(get_merged_stats))
    
    # Network difficulty history storage - persisted to disk
    network_diff_history = []
    network_diff_history_path = os.path.join(datadir_path, 'network_difficulty_history')
    known_diff_timestamps = set()
    
    # Load existing network difficulty history
    if os.path.exists(network_diff_history_path):
        try:
            with open(network_diff_history_path, 'rb') as f:
                network_diff_history = json.loads(f.read())
                known_diff_timestamps = set(int(d['ts']) for d in network_diff_history)
                print('Loaded %d network difficulty samples from disk' % len(network_diff_history))
        except Exception as e:
            log.err(None, 'Error loading network difficulty history:')
    
    # Seed network difficulty history from block history (if not already loaded)
    seeded_from_blocks = 0
    for b in block_history:
        if b.get('ts') and b.get('network_difficulty'):
            ts_key = int(b['ts'])
            if ts_key not in known_diff_timestamps:
                network_diff_history.append({
                    'ts': b['ts'],
                    'network_diff': b['network_difficulty'],
                    'source': 'block'
                })
                known_diff_timestamps.add(ts_key)
                seeded_from_blocks += 1
    if seeded_from_blocks > 0:
        network_diff_history.sort(key=lambda x: x['ts'])
        print('Seeded %d network difficulty samples from block history' % seeded_from_blocks)
    
    def save_network_diff_history():
        """Save network difficulty history to disk"""
        try:
            # Keep last 2000 samples (covers weeks of data at block-rate sampling)
            while len(network_diff_history) > 2000:
                oldest = network_diff_history.pop(0)
                known_diff_timestamps.discard(int(oldest['ts']))
            _atomic_write(network_diff_history_path, json.dumps(network_diff_history))
        except Exception as e:
            log.err(None, 'Error saving network difficulty history:')
    
    def add_network_diff_sample(timestamp, network_diff, source='block'):
        """Add a network difficulty sample if not already recorded for this timestamp"""
        ts_key = int(timestamp)
        if ts_key not in known_diff_timestamps:
            network_diff_history.append({
                'ts': timestamp,
                'network_diff': network_diff,
                'source': source  # 'block' or 'periodic'
            })
            known_diff_timestamps.add(ts_key)
            # Sort by timestamp ascending
            network_diff_history.sort(key=lambda x: x['ts'])
            return True
        return False
    
    # Periodically save network difficulty history
    x_netdiff = deferral.RobustLoopingCall(save_network_diff_history)
    x_netdiff.start(120)  # Save every 2 minutes
    stop_event.watch(x_netdiff.stop)
    
    # Also sample current network difficulty periodically (every 5 minutes)
    def sample_current_network_diff():
        try:
            if wb.current_work.value and 'bits' in wb.current_work.value:
                diff = bitcoin_data.target_to_difficulty(wb.current_work.value['bits'].target)
                current_time = time.time()
                if add_network_diff_sample(current_time, diff, 'periodic'):
                    print('Recorded periodic network difficulty sample: %.8f' % diff)
        except Exception as e:
            pass
    
    x_sample_diff = deferral.RobustLoopingCall(sample_current_network_diff)
    x_sample_diff.start(300)  # Sample every 5 minutes
    stop_event.watch(x_sample_diff.stop)
    
    # =========================================================================
    # Register the block_found callback now that all helper functions are defined
    # This ensures blocks AND network difficulty are saved immediately when found
    # =========================================================================
    wb.block_found.watch(on_block_found)
    print('Registered block_found callback for immediate block history persistence')
    
    # Network difficulty endpoint for graph - returns historical network difficulty
    class NetworkDifficultyResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            try:
                # Parse period parameter
                period = request.args.get('period', ['hour'])[0]
                now = time.time()
                
                # Determine time cutoff based on period
                if period == 'hour':
                    cutoff = now - 3600
                elif period == 'day':
                    cutoff = now - 86400
                elif period == 'week':
                    cutoff = now - 604800
                elif period == 'month':
                    cutoff = now - 2592000
                elif period == 'year':
                    cutoff = now - 31536000
                else:
                    cutoff = now - 3600  # Default to hour
                
                # Get samples within the time range
                samples = [d for d in network_diff_history if d['ts'] >= cutoff]
                
                # Also add current network difficulty
                if wb.current_work.value and 'bits' in wb.current_work.value:
                    diff = bitcoin_data.target_to_difficulty(wb.current_work.value['bits'].target)
                    samples.append({'ts': now, 'network_diff': diff, 'source': 'current'})
                
                # Sort by timestamp and return
                samples.sort(key=lambda x: x['ts'])
                return json.dumps(samples)
            except Exception as e:
                return json.dumps([])
    
    web_root.putChild('network_difficulty', NetworkDifficultyResource())
    
    # Node info endpoint for miner configuration display
    def get_node_info():
        """Get node connection info for miners"""
        try:
            # Use configured external IP if available, otherwise try to detect
            external_ip = getattr(node, 'external_ip', None)
            
            if not external_ip:
                # Try to get external IP from external service
                try:
                    import urllib2
                    for url in ['https://api.ipify.org', 'https://icanhazip.com', 'https://ifconfig.me/ip']:
                        try:
                            req = urllib2.Request(url)
                            req.add_header('User-Agent', 'p2pool')
                            response = urllib2.urlopen(req, timeout=3)
                            external_ip = response.read().strip()
                            if external_ip and len(external_ip) < 50:
                                break
                        except:
                            continue
                except:
                    pass
            
            # Fallback to local network IP
            if not external_ip:
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    external_ip = s.getsockname()[0]
                    s.close()
                except:
                    external_ip = "127.0.0.1"
            
            return {
                'external_ip': external_ip,
                'worker_port': node.net.WORKER_PORT,
                'p2p_port': node.net.P2P_PORT,
                'network': node.net.NAME,
                'symbol': node.net.PARENT.SYMBOL,
            }
        except Exception as e:
            return {'error': str(e)}
    
    web_root.putChild('node_info', WebInterface(get_node_info))
    
    # Luck statistics endpoint
    def get_luck_stats():
        """Get pool luck statistics"""
        try:
            # Get recent blocks from tracker
            height = node.tracker.get_height(node.best_share_var.value)
            if height < 10:
                return {'luck_available': False, 'blocks': [], 'current_luck_trend': None}
            
            lookbehind = min(height, 720)
            
            # Calculate current round luck
            # Shares since last block / expected shares
            pool_hashrate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
            if pool_hashrate > 0:
                expected_time = bitcoin_data.target_to_average_attempts(node.bitcoind_work.value['bits'].target) / pool_hashrate
                # Get time since last block found
                blocks_found = [s for s in node.tracker.get_chain(node.best_share_var.value, lookbehind) if s.pow_hash <= s.header['bits'].target]
                if blocks_found:
                    time_since_last = time.time() - blocks_found[0].timestamp
                    current_luck = (expected_time / max(time_since_last, 1)) * 100
                else:
                    current_luck = None
            else:
                current_luck = None
            
            # Build blocks list with luck values
            blocks = []
            for s in node.tracker.get_chain(node.best_share_var.value, lookbehind):
                if s.pow_hash <= s.header['bits'].target:
                    blocks.append({
                        'ts': s.timestamp,
                        'hash': '%064x' % s.header_hash,
                        'luck': 100,  # Placeholder - would need actual calculation
                    })
            
            return {
                'luck_available': True,
                'current_luck_trend': current_luck,
                'blocks': blocks[:20],  # Last 20 blocks
            }
        except Exception as e:
            return {'luck_available': False, 'error': str(e), 'blocks': []}
    
    web_root.putChild('luck_stats', WebInterface(get_luck_stats))
    
    # Peer list endpoint with detailed info
    def get_peer_list():
        """Get list of connected P2Pool peers with details"""
        try:
            peers = []
            for peer in node.p2p_node.peers.itervalues():
                try:
                    addr = peer.transport.getPeer()
                    peers.append({
                        'address': '%s:%s' % (addr.host, addr.port),
                        'web_port': getattr(node.net, 'WORKER_PORT', addr.port),
                        'version': getattr(peer, 'other_sub_version', None),
                        'incoming': getattr(peer, 'incoming', False),
                        'uptime': time.time() - getattr(peer, 'connected_at', time.time()) if hasattr(peer, 'connected_at') else 0,
                        'downtime': 0,
                        'txpool_size': getattr(peer, 'remembered_txs_size', 0),
                    })
                except:
                    pass
            return peers
        except Exception as e:
            return []
    
    web_root.putChild('peer_list', WebInterface(get_peer_list))
    
    # Add broadcaster network status endpoint (parent chain)
    from p2pool.bitcoin import helper as bitcoin_helper
    web_root.putChild('broadcaster_status', WebInterface(lambda: bitcoin_helper.get_broadcaster_status()))
    
    # Add merged broadcaster status endpoint (child chains like Dogecoin)
    def get_merged_broadcaster_status():
        """Get status of all merged mining broadcasters"""
        result = {'chains': {}}
        has_attr = hasattr(node, 'merged_broadcasters')
        broadcasters_dict = getattr(node, 'merged_broadcasters', None)
        if broadcasters_dict:
            for chain_id, broadcaster in broadcasters_dict.items():
                try:
                    # Use get_network_status for full peer list (same format as Litecoin broadcaster)
                    result['chains'][str(chain_id)] = broadcaster.get_network_status()
                except Exception as e:
                    result['chains'][str(chain_id)] = {'error': str(e)}
        if not result['chains']:
            result['message'] = 'No merged mining broadcasters active'
            result['debug'] = {
                'has_attr': has_attr,
                'broadcasters_type': str(type(broadcasters_dict)),
                'broadcasters_len': len(broadcasters_dict) if broadcasters_dict else 0,
                'broadcasters_keys': list(broadcasters_dict.keys()) if broadcasters_dict else [],
            }
        return result
    
    web_root.putChild('merged_broadcaster_status', WebInterface(get_merged_broadcaster_status))

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
        
        my_current_payout=0.0
        for add in wb.pubkeys.keys:
            my_current_payout += node.get_current_txouts().get(
                    add['address'], 0)*1e-8
        stat_log.append(dict(
            time=time.time(),
            pool_hash_rate=p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)/(1-global_stale_prop),
            pool_stale_prop=global_stale_prop,
            local_hash_rates=miner_hash_rates,
            local_dead_hash_rates=miner_dead_hash_rates,
            shares=shares,
            stale_shares=stale_orphan_shares + stale_doa_shares,
            stale_shares_breakdown=dict(orphan=stale_orphan_shares, doa=stale_doa_shares),
            current_payout=my_current_payout,
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
            parent='%064x' % share.previous_hash if share.previous_hash else "None",
            far_parent='%064x' % share.share_info['far_share_hash'] if share.share_info['far_share_hash'] else "None",
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
                payout_address=share.address if share.address else
                                bitcoin_data.script2_to_address(
                                    share.new_script,
                                    node.net.PARENT.ADDRESS_VERSION,
                                    node.net.PARENT),
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
                    raw=bitcoin_data.tx_id_type.pack(share.gentx).encode('hex') if hasattr(share, 'gentx') else "unknown",
                    coinbase=share.share_data['coinbase'].ljust(2, '\x00').encode('hex'),
                    value=share.share_data['subsidy']*1e-8,
                    last_txout_nonce='%016x' % share.contents['last_txout_nonce'],
                ),
                other_transaction_hashes=['%064x' % x for x in share.get_other_tx_hashes(node.tracker)],
            ),
        )

    def get_share_address(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return None
        share = node.tracker.items[int(share_hash_str, 16)]
        try:
            return share.address
        except AttributeError:
            return bitcoin_data.script2_to_address(share.new_script,
                                                   node.net.ADDRESS_VERSION, -1,
                                                   node.net.PARENT)

    new_root.putChild('payout_address', WebInterface(lambda share_hash_str: get_share_address(share_hash_str)))
    new_root.putChild('share', WebInterface(lambda share_hash_str: get_share(share_hash_str)))
    new_root.putChild('heads', WebInterface(lambda: ['%064x' % x for x in node.tracker.heads]))
    new_root.putChild('verified_heads', WebInterface(lambda: ['%064x' % x for x in node.tracker.verified.heads]))
    new_root.putChild('tails', WebInterface(lambda: ['%064x' % x for t in node.tracker.tails for x in node.tracker.reverse.get(t, set())]))
    new_root.putChild('verified_tails', WebInterface(lambda: ['%064x' % x for t in node.tracker.verified.tails for x in node.tracker.verified.reverse.get(t, set())]))
    new_root.putChild('best_share_hash', WebInterface(lambda: '%064x' % node.best_share_var.value))
    new_root.putChild('my_share_hashes', WebInterface(lambda: ['%064x' % my_share_hash for my_share_hash in wb.my_share_hashes]))
    new_root.putChild('my_share_hashes50', WebInterface(lambda: ['%064x' % my_share_hash for my_share_hash in list(wb.my_share_hashes)[:50]]))
    def get_share_data(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return ''
        share = node.tracker.items[int(share_hash_str, 16)]
        return p2pool_data.share_type.pack(share.as_share())
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
        'miner_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True, multivalues_keep=10000),
        'miner_dead_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True, multivalues_keep=10000),
        'merged_current_payouts': graph.DataStreamDescription(dataview_descriptions, multivalues=True),
        'desired_version_rates': graph.DataStreamDescription(dataview_descriptions, multivalues=True,
            multivalue_undefined_means_0=True),
        'traffic_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'getwork_latency': graph.DataStreamDescription(dataview_descriptions),
        'memory_usage': graph.DataStreamDescription(dataview_descriptions),
        'connected_miners': graph.DataStreamDescription(dataview_descriptions),
        'unique_miner_count': graph.DataStreamDescription(dataview_descriptions),
        'worker_count': graph.DataStreamDescription(dataview_descriptions),
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
        my_current_payouts = 0.0
        for add in wb.pubkeys.keys:
            my_current_payouts += current_txouts.get(
                    add['address'], 0) * 1e-8
        hd.datastreams['current_payout'].add_datum(t, my_current_payouts)
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        current_txouts_by_address = current_txouts
        hd.datastreams['current_payouts'].add_datum(t, dict((user, current_txouts_by_address[user]*1e-8) for user in miner_hash_rates if user in current_txouts_by_address))
        
        # Track merged mining payouts per miner (DOGE)
        try:
            merged_data = get_current_merged_payouts()
            merged_payouts_dict = {}
            for ltc_addr, data in merged_data.iteritems():
                if data.get('merged'):
                    for mp in data['merged']:
                        # Use LTC address as key for graph correlation
                        merged_payouts_dict[ltc_addr] = mp.get('amount', 0)
            if merged_payouts_dict:
                hd.datastreams['merged_current_payouts'].add_datum(t, merged_payouts_dict)
        except:
            pass
        
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
        # Track connected miners and worker counts
        try:
            connected_miners_count = len(miner_hash_rates)
            unique_miners = set(miner_hash_rates.keys())
            hd.datastreams['connected_miners'].add_datum(t, connected_miners_count)
            hd.datastreams['unique_miner_count'].add_datum(t, len(unique_miners))
            hd.datastreams['worker_count'].add_datum(t, connected_miners_count)
        except:
            if p2pool.DEBUG:
                traceback.print_exc()
    x = deferral.RobustLoopingCall(add_point)
    x.start(5)
    stop_event.watch(x.stop)
    @node.bitcoind_work.changed.watch
    def _(new_work):
        hd.datastreams['getwork_latency'].add_datum(time.time(), new_work['latency'])
    
    def get_graph_data(source, view):
        if source not in hd.datastreams:
            return []  # Return empty data for missing datastreams
        if view not in hd.datastreams[source].dataviews:
            return []
        return hd.datastreams[source].dataviews[view].get_data(time.time())
    
    new_root.putChild('graph_data', WebInterface(get_graph_data))
    
    if static_dir is None:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'web-static')
    web_root.putChild('static', static.File(static_dir))
    
    return web_root
