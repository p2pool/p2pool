#!/usr/bin/python
# coding=utf-8

from __future__ import division

import argparse
import codecs
import datetime
import os
import random
import struct
import sys
import time
import json
import signal
import traceback

from twisted.internet import defer, reactor, protocol, task
from twisted.web import server, resource
from twisted.python import log
from nattraverso import portmapper, ipdiscover

import bitcoin.p2p as bitcoin_p2p, bitcoin.getwork as bitcoin_getwork, bitcoin.data as bitcoin_data
from bitcoin import worker_interface
from util import expiring_dict, jsonrpc, variable, deferral, math
from . import p2p, networks, graphs
import p2pool, p2pool.data as p2pool_data

@deferral.retry('Error getting work from bitcoind:', 3)
@defer.inlineCallbacks
def getwork(bitcoind):
    work = yield bitcoind.rpc_getmemorypool()
    defer.returnValue(dict(
        version=work['version'],
        previous_block_hash=int(work['previousblockhash'], 16),
        transactions=[bitcoin_data.tx_type.unpack(x.decode('hex')) for x in work['transactions']],
        subsidy=work['coinbasevalue'],
        time=work['time'],
        bits=bitcoin_data.FloatingIntegerType().unpack(work['bits'].decode('hex')[::-1]) if isinstance(work['bits'], (str, unicode)) else bitcoin_data.FloatingInteger(work['bits']),
        coinbaseflags=work['coinbaseflags'].decode('hex') if 'coinbaseflags' in work else ''.join(x.decode('hex') for x in work['coinbaseaux'].itervalues()) if 'coinbaseaux' in work else '',
    ))

@defer.inlineCallbacks
def main(args, net, datadir_path):
    try:
        my_share_hashes = set()
        my_doa_share_hashes = set()
        p2pool_data.OkayTrackerDelta.my_share_hashes = my_share_hashes
        p2pool_data.OkayTrackerDelta.my_doa_share_hashes = my_doa_share_hashes
        
        print 'p2pool (version %s)' % (p2pool.__version__,)
        print
        try:
            from . import draw
        except ImportError:
            draw = None
            print "Install Pygame and PIL to enable visualizations! Visualizations disabled."
            print
        
        # connect to bitcoind over JSON-RPC and do initial getmemorypool
        url = 'http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port)
        print '''Testing bitcoind RPC connection to '%s' with username '%s'...''' % (url, args.bitcoind_rpc_username)
        bitcoind = jsonrpc.Proxy(url, (args.bitcoind_rpc_username, args.bitcoind_rpc_password))
        good = yield deferral.retry('Error while checking bitcoind identity:', 1)(net.PARENT.RPC_CHECK)(bitcoind)
        if not good:
            print >>sys.stderr, "    Check failed! Make sure that you're connected to the right bitcoind with --bitcoind-rpc-port!"
            return
        temp_work = yield getwork(bitcoind)
        print '    ...success!'
        print '    Current block hash: %x' % (temp_work['previous_block_hash'],)
        print
        
        # connect to bitcoind over bitcoin-p2p
        print '''Testing bitcoind P2P connection to '%s:%s'...''' % (args.bitcoind_address, args.bitcoind_p2p_port)
        factory = bitcoin_p2p.ClientFactory(net.PARENT)
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        yield factory.getProtocol() # waits until handshake is successful
        print '    ...success!'
        print
        
        if args.pubkey_hash is None:
            print 'Getting payout address from bitcoind...'
            my_script = yield deferral.retry('Error getting payout address from bitcoind:', 5)(defer.inlineCallbacks(lambda: defer.returnValue(
                bitcoin_data.pubkey_hash_to_script2(bitcoin_data.address_to_pubkey_hash((yield bitcoind.rpc_getaccountaddress('p2pool')), net.PARENT)))
            ))()
        else:
            print 'Computing payout script from provided address....'
            my_script = bitcoin_data.pubkey_hash_to_script2(args.pubkey_hash)
        print '    ...success!'
        print '    Payout script:', bitcoin_data.script2_to_human(my_script, net.PARENT)
        print
        
        ht = bitcoin_p2p.HeightTracker(bitcoind, factory)
        
        tracker = p2pool_data.OkayTracker(net)
        shared_share_hashes = set()
        ss = p2pool_data.ShareStore(os.path.join(datadir_path, 'shares.'), net)
        known_verified = set()
        recent_blocks = []
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
        
        peer_heads = expiring_dict.ExpiringDict(300) # hash -> peers that know of it
        
        pre_current_work = variable.Variable(None)
        pre_merged_work = variable.Variable(None)
        # information affecting work that should trigger a long-polling update
        current_work = variable.Variable(None)
        # information affecting work that should not trigger a long-polling update
        current_work2 = variable.Variable(None)
        
        requested = expiring_dict.ExpiringDict(300)
        
        @defer.inlineCallbacks
        def set_real_work1():
            work = yield getwork(bitcoind)
            current_work2.set(dict(
                time=work['time'],
                transactions=work['transactions'],
                subsidy=work['subsidy'],
                clock_offset=time.time() - work['time'],
                last_update=time.time(),
            )) # second set first because everything hooks on the first
            pre_current_work.set(dict(
                version=work['version'],
                previous_block=work['previous_block_hash'],
                bits=work['bits'],
                coinbaseflags=work['coinbaseflags'],
            ))
        
        def set_real_work2():
            best, desired = tracker.think(ht, pre_current_work.value['previous_block'])
            
            t = dict(pre_current_work.value)
            t['best_share_hash'] = best
            t['aux_work'] = pre_merged_work.value
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
        pre_current_work.changed.watch(lambda _: set_real_work2())
        
        print 'Initializing work...'
        yield set_real_work1()
        print '    ...success!'
        print
        
        pre_merged_work.changed.watch(lambda _: set_real_work2())
        ht.updated.watch(set_real_work2)
        
        merged_proxy = jsonrpc.Proxy(args.merged_url, (args.merged_userpass,)) if args.merged_url else None
        
        @defer.inlineCallbacks
        def set_merged_work():
            while True:
                auxblock = yield deferral.retry('Error while calling merged getauxblock:', 1)(merged_proxy.rpc_getauxblock)()
                pre_merged_work.set(dict(
                    hash=int(auxblock['hash'], 16),
                    target=bitcoin_data.IntType(256).unpack(auxblock['target'].decode('hex')),
                    chain_id=auxblock['chainid'],
                ))
                yield deferral.sleep(1)
        if merged_proxy is not None:
            set_merged_work()
        
        @pre_merged_work.changed.watch
        def _(new_merged_work):
            print "Got new merged mining work! Difficulty: %f" % (bitcoin_data.target_to_difficulty(new_merged_work['target']),)
        
        # setup p2p logic and join p2pool network
        
        class Node(p2p.Node):
            def handle_shares(self, shares, peer):
                if len(shares) > 5:
                    print 'Processing %i shares...' % (len(shares),)
                
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
                    set_real_work2()
                
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
                peer.sendShares(shares)
        
        @tracker.verified.added.watch
        def _(share):
            if share.pow_hash <= share.header['bits'].target:
                if factory.conn.value is not None:
                    factory.conn.value.send_block(block=share.as_block(tracker))
                else:
                    print >>sys.stderr, 'No bitcoind connection when block submittal attempted! Erp!'
                print
                print 'GOT BLOCK FROM PEER! Passing to bitcoind! %s bitcoin: %x' % (p2pool_data.format_hash(share.hash), share.header_hash)
                print
                recent_blocks.append({ 'ts': share.timestamp, 'hash': '%x' % (share.header_hash) })
        
        print 'Joining p2pool network using port %i...' % (args.p2pool_port,)
        
        def parse(x):
            if ':' in x:
                ip, port = x.split(':')
                return ip, int(port)
            else:
                return x, net.P2P_PORT
        
        addrs = {}
        if os.path.exists(os.path.join(datadir_path, 'addrs.txt')):
            try:
                addrs.update(dict(eval(x) for x in open(os.path.join(datadir_path, 'addrs.txt'))))
            except:
                print >>sys.stderr, "error reading addrs"
        for addr in map(parse, net.BOOTSTRAP_ADDRS):
            if addr not in addrs:
                addrs[addr] = (0, time.time(), time.time())
        
        p2p_node = Node(
            best_share_hash_func=lambda: current_work.value['best_share_hash'],
            port=args.p2pool_port,
            net=net,
            addr_store=addrs,
            connect_addrs=set(map(parse, args.p2pool_nodes)),
        )
        p2p_node.start()
        
        def save_addrs():
            open(os.path.join(datadir_path, 'addrs.txt'), 'w').writelines(repr(x) + '\n' for x in p2p_node.addr_store.iteritems())
        task.LoopingCall(save_addrs).start(60)
        
        # send share when the chain changes to their chain
        def work_changed(new_work):
            #print 'Work changed:', new_work
            shares = []
            for share in tracker.get_chain(new_work['best_share_hash'], tracker.get_height(new_work['best_share_hash'])):
                if share.hash in shared_share_hashes:
                    break
                shared_share_hashes.add(share.hash)
                shares.append(share)
            
            for peer in p2p_node.peers.itervalues():
                peer.sendShares([share for share in shares if share.peer is not peer])
        
        current_work.changed.watch(work_changed)
        
        def save_shares():
            for share in tracker.get_chain(current_work.value['best_share_hash'], min(tracker.get_height(current_work.value['best_share_hash']), 2*net.CHAIN_LENGTH)):
                ss.add_share(share)
                if share.hash in tracker.verified.shares:
                    ss.add_verified_hash(share.hash)
        task.LoopingCall(save_shares).start(60)
        
        print '    ...success!'
        print
        
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
                        log.err(None, "UPnP error:")
                yield deferral.sleep(random.expovariate(1/120))
        
        if args.upnp:
            upnp_thread()
        
        # start listening for workers with a JSON-RPC server
        
        print 'Listening for workers on port %i...' % (args.worker_port,)
        
        if os.path.exists(os.path.join(datadir_path, 'vip_pass')):
            with open(os.path.join(datadir_path, 'vip_pass'), 'rb') as f:
                vip_pass = f.read().strip('\r\n')
        else:
            vip_pass = '%016x' % (random.randrange(2**64),)
            with open(os.path.join(datadir_path, 'vip_pass'), 'wb') as f:
                f.write(vip_pass)
        print '    Worker password:', vip_pass, '(only required for generating graphs)'
        
        # setup worker logic
        
        removed_unstales_var = variable.Variable((0, 0, 0))
        @tracker.verified.removed.watch
        def _(share):
            if share.hash in my_share_hashes and tracker.is_child_of(share.hash, current_work.value['best_share_hash']):
                assert share.share_data['stale_info'] in [0, 253, 254] # we made these shares in this instance
                removed_unstales_var.set((
                    removed_unstales_var.value[0] + 1,
                    removed_unstales_var.value[1] + (1 if share.share_data['stale_info'] == 253 else 0),
                    removed_unstales_var.value[2] + (1 if share.share_data['stale_info'] == 254 else 0),
                ))
        
        removed_doa_unstales_var = variable.Variable(0)
        @tracker.verified.removed.watch
        def _(share):
            if share.hash in my_doa_share_hashes and tracker.is_child_of(share.hash, current_work.value['best_share_hash']):
                removed_doa_unstales.set(removed_doa_unstales.value + 1)
        
        def get_stale_counts():
            '''Returns (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain)'''
            my_shares = len(my_share_hashes)
            my_doa_shares = len(my_doa_share_hashes)
            delta = tracker.verified.get_delta(current_work.value['best_share_hash'])
            my_shares_in_chain = delta.my_count + removed_unstales_var.value[0]
            my_doa_shares_in_chain = delta.my_doa_count + removed_doa_unstales_var.value
            orphans_recorded_in_chain = delta.my_orphan_announce_count + removed_unstales_var.value[1]
            doas_recorded_in_chain = delta.my_dead_announce_count + removed_unstales_var.value[2]
            
            my_shares_not_in_chain = my_shares - my_shares_in_chain
            my_doa_shares_not_in_chain = my_doa_shares - my_doa_shares_in_chain
            
            return (my_shares_not_in_chain - my_doa_shares_not_in_chain, my_doa_shares_not_in_chain), my_shares, (orphans_recorded_in_chain, doas_recorded_in_chain)
        
        class WorkerBridge(worker_interface.WorkerBridge):
            def __init__(self):
                worker_interface.WorkerBridge.__init__(self)
                self.new_work_event = current_work.changed
                
                self.merkle_root_to_transactions = expiring_dict.ExpiringDict(300)
                self.recent_shares_ts_work = []
            
            def _get_payout_script_from_username(self, user):
                if user is None:
                    return None
                try:
                    pubkey_hash = bitcoin_data.address_to_pubkey_hash(user, net.PARENT)
                except: # XXX blah
                    return None
                return bitcoin_data.pubkey_hash_to_script2(pubkey_hash)
            
            def preprocess_request(self, request):
                payout_script = self._get_payout_script_from_username(request.getUser())
                if payout_script is None or random.uniform(0, 100) < args.worker_fee:
                    payout_script = my_script
                return payout_script,
            
            def get_work(self, payout_script):
                if len(p2p_node.peers) == 0 and net.PERSIST:
                    raise jsonrpc.Error(-12345, u'p2pool is not connected to any peers')
                if current_work.value['best_share_hash'] is None and net.PERSIST:
                    raise jsonrpc.Error(-12345, u'p2pool is downloading shares')
                if time.time() > current_work2.value['last_update'] + 60:
                    raise jsonrpc.Error(-12345, u'lost contact with bitcoind')
                
                share_info, generate_tx = p2pool_data.generate_transaction(
                    tracker=tracker,
                    share_data=dict(
                        previous_share_hash=current_work.value['best_share_hash'],
                        coinbase=(('' if current_work.value['aux_work'] is None else
                            '\xfa\xbemm' + bitcoin_data.IntType(256, 'big').pack(current_work.value['aux_work']['hash']) + struct.pack('<ii', 1, 0)) + current_work.value['coinbaseflags'])[:100],
                        nonce=struct.pack('<Q', random.randrange(2**64)),
                        new_script=payout_script,
                        subsidy=current_work2.value['subsidy'],
                        donation=math.perfect_round(65535*args.donation_percentage/100),
                        stale_info=(lambda (orphans, doas), total, (orphans_recorded_in_chain, doas_recorded_in_chain):
                            253 if orphans > orphans_recorded_in_chain else
                            254 if doas > doas_recorded_in_chain else
                            0
                        )(*get_stale_counts()),
                    ),
                    block_target=current_work.value['bits'].target,
                    desired_timestamp=int(time.time() - current_work2.value['clock_offset']),
                    net=net,
                )
                
                target = 2**256//2**32 - 1
                if len(self.recent_shares_ts_work) == 50:
                    hash_rate = sum(work for ts, work in self.recent_shares_ts_work)//(self.recent_shares_ts_work[-1][0] - self.recent_shares_ts_work[0][0])
                    target = min(target, 2**256//(hash_rate * 5))
                target = max(target, share_info['bits'].target)
                if current_work.value['aux_work']:
                    target = max(target, current_work.value['aux_work']['target'])
                
                transactions = [generate_tx] + list(current_work2.value['transactions'])
                merkle_root = bitcoin_data.merkle_hash(map(bitcoin_data.tx_type.hash256, transactions))
                self.merkle_root_to_transactions[merkle_root] = share_info, transactions, time.time(), current_work.value['aux_work'], target
                
                print 'New work for worker! Difficulty: %.06f Share difficulty: %.06f Payout if block: %.6f %s Total block value: %.6f %s including %i transactions' % (
                    bitcoin_data.target_to_difficulty(target),
                    bitcoin_data.target_to_difficulty(share_info['bits'].target),
                    (sum(t['value'] for t in generate_tx['tx_outs'] if t['script'] == payout_script) - current_work2.value['subsidy']//200)*1e-8, net.PARENT.SYMBOL,
                    current_work2.value['subsidy']*1e-8, net.PARENT.SYMBOL,
                    len(current_work2.value['transactions']),
                )
                
                return bitcoin_getwork.BlockAttempt(
                    version=current_work.value['version'],
                    previous_block=current_work.value['previous_block'],
                    merkle_root=merkle_root,
                    timestamp=current_work2.value['time'],
                    bits=current_work.value['bits'],
                    share_target=target,
                )
            
            def got_response(self, header, request):
                # match up with transactions
                if header['merkle_root'] not in self.merkle_root_to_transactions:
                    print >>sys.stderr, '''Couldn't link returned work's merkle root with its transactions - should only happen if you recently restarted p2pool'''
                    return False
                share_info, transactions, getwork_time, aux_work, target = self.merkle_root_to_transactions[header['merkle_root']]
                
                pow_hash = net.PARENT.POW_FUNC(header)
                on_time = current_work.value['best_share_hash'] == share_info['share_data']['previous_share_hash']
                
                try:
                    if pow_hash <= header['bits'].target or p2pool.DEBUG:
                        if factory.conn.value is not None:
                            factory.conn.value.send_block(block=dict(header=header, txs=transactions))
                        else:
                            print >>sys.stderr, 'No bitcoind connection when block submittal attempted! Erp!'
                        if pow_hash <= header['bits'].target:
                            print
                            print 'GOT BLOCK FROM MINER! Passing to bitcoind! bitcoin: %x' % (bitcoin_data.block_header_type.hash256(header),)
                            print
                            recent_blocks.append({ 'ts': time.time(), 'hash': '%x' % (bitcoin_data.block_header_type.hash256(header),) })
                except:
                    log.err(None, 'Error while processing potential block:')
                
                try:
                    if aux_work is not None and (pow_hash <= aux_work['target'] or p2pool.DEBUG):
                        assert bitcoin_data.IntType(256, 'big').pack(aux_work['hash']).encode('hex') == transactions[0]['tx_ins'][0]['script'][4:4+32].encode('hex')
                        df = deferral.retry('Error submitting merged block: (will retry)', 10, 10)(merged_proxy.rpc_getauxblock)(
                            bitcoin_data.IntType(256, 'big').pack(aux_work['hash']).encode('hex'),
                            bitcoin_data.aux_pow_type.pack(dict(
                                merkle_tx=dict(
                                    tx=transactions[0],
                                    block_hash=bitcoin_data.block_header_type.hash256(header),
                                    merkle_branch=bitcoin_data.calculate_merkle_branch(map(bitcoin_data.tx_type.hash256, transactions), 0),
                                    index=0,
                                ),
                                merkle_branch=[],
                                index=0,
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
                
                if pow_hash <= share_info['bits'].target:
                    share = p2pool_data.Share(net, header, share_info, other_txs=transactions[1:])
                    print 'GOT SHARE! %s %s prev %s age %.2fs%s' % (
                        request.getUser(),
                        p2pool_data.format_hash(share.hash),
                        p2pool_data.format_hash(share.previous_hash),
                        time.time() - getwork_time,
                        ' DEAD ON ARRIVAL' if not on_time else '',
                    )
                    my_share_hashes.add(share.hash)
                    if not on_time:
                        my_doa_share_hashes.add(share.hash)
                    p2p_node.handle_shares([share], None)
                    try:
                        if pow_hash <= header['bits'].target:
                            for peer in p2p_node.peers.itervalues():
                                peer.sendShares([share])
                            shared_share_hashes.add(share.hash)
                    except:
                        log.err(None, 'Error forwarding block solution:')
                
                if pow_hash <= target:
                    reactor.callLater(1, grapher.add_localrate_point, bitcoin_data.target_to_average_attempts(target), not on_time)
                    if request.getPassword() == vip_pass:
                        reactor.callLater(1, grapher.add_localminer_point, request.getUser(), bitcoin_data.target_to_average_attempts(target), not on_time)
                    self.recent_shares_ts_work.append((time.time(), bitcoin_data.target_to_average_attempts(target)))
                    while len(self.recent_shares_ts_work) > 50:
                        self.recent_shares_ts_work.pop(0)
                
                if pow_hash > target:
                    print 'Worker submitted share with hash > target:'
                    print '    Hash:   %56x' % (pow_hash,)
                    print '    Target: %56x' % (target,)
                
                return on_time
        
        web_root = resource.Resource()
        worker_interface.WorkerInterface(WorkerBridge()).attach_to(web_root)
        
        def get_rate():
            if tracker.get_height(current_work.value['best_share_hash']) < 720:
                return json.dumps(None)
            return json.dumps(p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], 720)
                / (1 - p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], 720)))
        
        def get_users():
            height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
            weights, total_weight, donation_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 720), 65535*2**256)
            res = {}
            for script in sorted(weights, key=lambda s: weights[s]):
                res[bitcoin_data.script2_to_human(script, net.PARENT)] = weights[script]/total_weight
            return json.dumps(res)
        
        def get_current_txouts():
            wb = WorkerBridge()
            tmp_tag = str(random.randrange(2**64))
            outputs = wb.merkle_root_to_transactions[wb.get_work(tmp_tag).merkle_root][1][0]['tx_outs']
            total = sum(out['value'] for out in outputs)
            total_without_tag = sum(out['value'] for out in outputs if out['script'] != tmp_tag)
            total_diff = total - total_without_tag
            return dict((out['script'], out['value'] + math.perfect_round(out['value']*total_diff/total)) for out in outputs if out['script'] != tmp_tag and out['value'])
        
        def get_current_scaled_txouts(scale, trunc=0):
            txouts = get_current_txouts()
            total = sum(txouts.itervalues())
            results = dict((script, value*scale//total) for script, value in txouts.iteritems())
            if trunc > 0:
                total_random = 0
                random_set = set()
                for s in sorted(results, key=results.__getitem__):
                    total_random += results[s]
                    random_set.add(s)
                    if total_random >= trunc and results[s] >= trunc:
                        break
                winner = math.weighted_choice((script, results[script]) for script in random_set)
                for script in random_set:
                    del results[script]
                results[winner] = total_random
            if sum(results.itervalues()) < int(scale):
                results[math.weighted_choice(results.iteritems())] += int(scale) - sum(results.itervalues())
            return results
        
        def get_current_payouts():
            return json.dumps(dict((bitcoin_data.script2_to_human(script, net.PARENT), value/1e8) for script, value in get_current_txouts().iteritems()))
        
        def get_patron_sendmany(this):
            try:
                if '/' in this:
                    this, trunc = this.split('/', 1)
                else:
                    trunc = '0.01'
                return json.dumps(dict(
                    (bitcoin_data.script2_to_address(script, net.PARENT), value/1e8)
                    for script, value in get_current_scaled_txouts(scale=int(float(this)*1e8), trunc=int(float(trunc)*1e8)).iteritems()
                    if bitcoin_data.script2_to_address(script, net.PARENT) is not None
                ))
            except:
                return json.dumps(None)
        
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
            
            return json.dumps(dict(
                my_hash_rates_in_last_hour=dict(
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
            ))
        
        def get_peer_addresses():
            return ' '.join(peer.transport.getPeer().host + (':' + str(peer.transport.getPeer().port) if peer.transport.getPeer().port != net.P2P_PORT else '') for peer in p2p_node.peers.itervalues())
        
        class WebInterface(resource.Resource):
            def __init__(self, func, mime_type, *fields):
                self.func, self.mime_type, self.fields = func, mime_type, fields
            
            def render_GET(self, request):
                request.setHeader('Content-Type', self.mime_type)
                request.setHeader('Access-Control-Allow-Origin', '*')
                return self.func(*(request.args[field][0] for field in self.fields))
        
        web_root.putChild('rate', WebInterface(get_rate, 'application/json'))
        web_root.putChild('users', WebInterface(get_users, 'application/json'))
        web_root.putChild('fee', WebInterface(lambda: json.dumps(args.worker_fee), 'application/json'))
        web_root.putChild('current_payouts', WebInterface(get_current_payouts, 'application/json'))
        web_root.putChild('patron_sendmany', WebInterface(get_patron_sendmany, 'text/plain', 'total'))
        web_root.putChild('global_stats', WebInterface(get_global_stats, 'application/json'))
        web_root.putChild('local_stats', WebInterface(get_local_stats, 'application/json'))
        web_root.putChild('peer_addresses', WebInterface(get_peer_addresses, 'text/plain'))
        web_root.putChild('payout_addr', WebInterface(lambda: json.dumps(bitcoin_data.script2_to_human(my_script, net.PARENT)), 'application/json'))
        web_root.putChild('recent_blocks', WebInterface(lambda: json.dumps(recent_blocks), 'application/json'))
        if draw is not None:
            web_root.putChild('chain_img', WebInterface(lambda: draw.get(tracker, current_work.value['best_share_hash']), 'image/png'))
        
        grapher = graphs.Grapher(os.path.join(datadir_path, 'rrd'))
        web_root.putChild('graphs', grapher.get_resource())
        def add_point():
            if tracker.get_height(current_work.value['best_share_hash']) < 720:
                return
            grapher.add_poolrate_point(p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], 720)
                / (1 - p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], 720)))
        task.LoopingCall(add_point).start(100)
        
        reactor.listenTCP(args.worker_port, server.Site(web_root))
        
        print '    ...success!'
        print
        
        
        @defer.inlineCallbacks
        def work_poller():
            while True:
                flag = factory.new_block.get_deferred()
                try:
                    yield set_real_work1()
                except:
                    log.err()
                yield defer.DeferredList([flag, deferral.sleep(15)], fireOnOneCallback=True)
        work_poller()
        
        
        # done!
        print 'Started successfully!'
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
                nickname = 'p2pool'
                def lineReceived(self, line):
                    print repr(line)
                    irc.IRCClient.lineReceived(self, line)
                def signedOn(self):
                    irc.IRCClient.signedOn(self)
                    self.factory.resetDelay()
                    self.join('#p2pool')
                    self.watch_id = current_work.changed.watch(self._work_changed)
                    self.announced_hashes = set()
                def _work_changed(self, new_work):
                    share = tracker.shares[new_work['best_share_hash']]
                    if share.pow_hash <= share.header['bits'].target and share.header_hash not in self.announced_hashes:
                        self.privmsg('#p2pool', '\x033,4BLOCK FOUND! http://blockexplorer.com/block/' + bitcoin_data.IntType(256, 'big').pack(share.header_hash).encode('hex'))
                def connectionLost(self, reason):
                    current_work.changed.unwatch(self.watch_id)
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
                    if time.time() > current_work2.value['last_update'] + 60:
                        print >>sys.stderr, '''---> LOST CONTACT WITH BITCOIND for 60 seconds, check that it isn't frozen or dead <---'''
                    if current_work.value['best_share_hash'] is not None:
                        height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
                        if height > 2:
                            att_s = p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], min(height - 1, 720))
                            weights, total_weight, donation_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 720), 65535*2**256)
                            (stale_orphan_shares, stale_doa_shares), shares, _ = get_stale_counts()
                            stale_prop = p2pool_data.get_average_stale_prop(tracker, current_work.value['best_share_hash'], min(720, height))
                            real_att_s = att_s / (1 - stale_prop)
                            my_att_s = real_att_s*weights.get(my_script, 0)/total_weight
                            this_str = 'Pool: %sH/s in %i shares (%i/%i verified) Recent: %.02f%% >%sH/s Shares: %i (%i orphan, %i dead) Peers: %i (%i incoming)' % (
                                math.format(int(real_att_s)),
                                height,
                                len(tracker.verified.shares),
                                len(tracker.shares),
                                weights.get(my_script, 0)/total_weight*100,
                                math.format(int(my_att_s)),
                                shares,
                                stale_orphan_shares,
                                stale_doa_shares,
                                len(p2p_node.peers),
                                sum(1 for peer in p2p_node.peers.itervalues() if peer.incoming),
                            ) + (' FDs: %i R/%i W' % (len(reactor.getReaders()), len(reactor.getWriters())) if p2pool.DEBUG else '')
                            this_str += '\nAverage time between blocks: %.2f days' % (
                                2**256 / current_work.value['bits'].target / real_att_s / (60 * 60 * 24),
                            )
                            this_str += '\nPool stales: %i%%' % (int(100*stale_prop+.5),)
                            stale_center, stale_radius = math.binomial_conf_center_radius(stale_orphan_shares + stale_doa_shares, shares, 0.95)
                            this_str += u' Own: %i±%i%%' % (int(100*stale_center+.5), int(100*stale_radius+.5))
                            this_str += u' Own efficiency: %i±%i%%' % (int(100*(1 - stale_center)/(1 - stale_prop)+.5), int(100*stale_radius/(1 - stale_prop)+.5))
                            if this_str != last_str or time.time() > last_time + 15:
                                print this_str
                                last_str = this_str
                                last_time = time.time()
                except:
                    log.err()
        status_thread()
    except:
        log.err(None, 'Fatal error:')

def run():
    class FixedArgumentParser(argparse.ArgumentParser):
        def _read_args_from_files(self, arg_strings):
            # expand arguments referencing files
            new_arg_strings = []
            for arg_string in arg_strings:
                
                # for regular arguments, just add them back into the list
                if not arg_string or arg_string[0] not in self.fromfile_prefix_chars:
                    new_arg_strings.append(arg_string)
                
                # replace arguments referencing files with the file content
                else:
                    try:
                        args_file = open(arg_string[1:])
                        try:
                            arg_strings = []
                            for arg_line in args_file.read().splitlines():
                                for arg in self.convert_arg_line_to_args(arg_line):
                                    arg_strings.append(arg)
                            arg_strings = self._read_args_from_files(arg_strings)
                            new_arg_strings.extend(arg_strings)
                        finally:
                            args_file.close()
                    except IOError:
                        err = sys.exc_info()[1]
                        self.error(str(err))
            
            # return the modified argument list
            return new_arg_strings
        
        def convert_arg_line_to_args(self, arg_line):
            return [arg for arg in arg_line.split() if arg.strip()]
    
    parser = FixedArgumentParser(description='p2pool (version %s)' % (p2pool.__version__,), fromfile_prefix_chars='@')
    parser.add_argument('--version', action='version', version=p2pool.__version__)
    parser.add_argument('--net',
        help='use specified network (default: bitcoin)',
        action='store', choices=sorted(networks.realnets), default='bitcoin', dest='net_name')
    parser.add_argument('--testnet',
        help='''use the network's testnet''',
        action='store_const', const=True, default=False, dest='testnet')
    parser.add_argument('--debug',
        help='enable debugging mode',
        action='store_const', const=True, default=False, dest='debug')
    parser.add_argument('-a', '--address',
        help='generate payouts to this address (default: <address requested from bitcoind>)',
        type=str, action='store', default=None, dest='address')
    parser.add_argument('--logfile',
        help='''log to this file (default: data/<NET>/log)''',
        type=str, action='store', default=None, dest='logfile')
    parser.add_argument('--merged-url',
        help='call getauxblock on this url to get work for merged mining (example: http://127.0.0.1:10332/)',
        type=str, action='store', default=None, dest='merged_url')
    parser.add_argument('--merged-userpass',
        help='use this user and password when requesting merged mining work (example: ncuser:ncpass)',
        type=str, action='store', default=None, dest='merged_userpass')
    parser.add_argument('--give-author', metavar='DONATION_PERCENTAGE',
        help='donate this percentage of work to author of p2pool (default: 0.5)',
        type=float, action='store', default=0.5, dest='donation_percentage')
    parser.add_argument('--irc-announce',
        help='announce any blocks found on irc://irc.freenode.net/#p2pool',
        action='store_true', default=False, dest='irc_announce')
    
    p2pool_group = parser.add_argument_group('p2pool interface')
    p2pool_group.add_argument('--p2pool-port', metavar='PORT',
        help='use port PORT to listen for connections (forward this port from your router!) (default: %s)' % ', '.join('%s:%i' % (n.NAME, n.P2P_PORT) for _, n in sorted(networks.realnets.items())),
        type=int, action='store', default=None, dest='p2pool_port')
    p2pool_group.add_argument('-n', '--p2pool-node', metavar='ADDR[:PORT]',
        help='connect to existing p2pool node at ADDR listening on port PORT (defaults to default p2pool P2P port) in addition to builtin addresses',
        type=str, action='append', default=[], dest='p2pool_nodes')
    parser.add_argument('--disable-upnp',
        help='''don't attempt to use UPnP to forward p2pool's P2P port from the Internet to this computer''',
        action='store_false', default=True, dest='upnp')
    
    worker_group = parser.add_argument_group('worker interface')
    worker_group.add_argument('-w', '--worker-port', metavar='PORT',
        help='listen on PORT for RPC connections from miners (default: %s)' % ', '.join('%s:%i' % (n.NAME, n.WORKER_PORT) for _, n in sorted(networks.realnets.items())),
        type=int, action='store', default=None, dest='worker_port')
    worker_group.add_argument('-f', '--fee', metavar='FEE_PERCENTAGE',
        help='''charge workers mining to their own bitcoin address (by setting their miner's username to a bitcoin address) this percentage fee to mine on your p2pool instance. Amount displayed at http://127.0.0.1:WORKER_PORT/fee (default: 0)''',
        type=float, action='store', default=0, dest='worker_fee')
    
    bitcoind_group = parser.add_argument_group('bitcoind interface')
    bitcoind_group.add_argument('--bitcoind-address', metavar='BITCOIND_ADDRESS',
        help='connect to this address (default: 127.0.0.1)',
        type=str, action='store', default='127.0.0.1', dest='bitcoind_address')
    bitcoind_group.add_argument('--bitcoind-rpc-port', metavar='BITCOIND_RPC_PORT',
        help='''connect to JSON-RPC interface at this port (default: %s)''' % ', '.join('%s:%i' % (n.NAME, n.PARENT.RPC_PORT) for _, n in sorted(networks.realnets.items())),
        type=int, action='store', default=None, dest='bitcoind_rpc_port')
    bitcoind_group.add_argument('--bitcoind-p2p-port', metavar='BITCOIND_P2P_PORT',
        help='''connect to P2P interface at this port (default: %s)''' % ', '.join('%s:%i' % (n.NAME, n.PARENT.P2P_PORT) for _, n in sorted(networks.realnets.items())),
        type=int, action='store', default=None, dest='bitcoind_p2p_port')
    
    bitcoind_group.add_argument(metavar='BITCOIND_RPCUSER',
        help='bitcoind RPC interface username (default: <empty>)',
        type=str, action='store', default='', nargs='?', dest='bitcoind_rpc_username')
    bitcoind_group.add_argument(metavar='BITCOIND_RPCPASSWORD',
        help='bitcoind RPC interface password',
        type=str, action='store', dest='bitcoind_rpc_password')
    
    args = parser.parse_args()
    
    if args.debug:
        p2pool.DEBUG = True
    
    net = networks.nets[args.net_name + ('_testnet' if args.testnet else '')]
    
    datadir_path = os.path.join(os.path.dirname(sys.argv[0]), 'data', net.NAME)
    if not os.path.exists(datadir_path):
        os.makedirs(datadir_path)
    
    if args.logfile is None:
        args.logfile = os.path.join(datadir_path, 'log')
    
    class EncodeReplacerPipe(object):
        def __init__(self, inner_file):
            self.inner_file = inner_file
            self.softspace = 0
        def write(self, data):
            if isinstance(data, unicode):
                try:
                    data = data.encode(self.inner_file.encoding, 'replace')
                except:
                    data = data.encode('ascii', 'replace')
            self.inner_file.write(data)
        def flush(self):
            self.inner_file.flush()
    class LogFile(object):
        def __init__(self, filename):
            self.filename = filename
            self.inner_file = None
            self.reopen()
        def reopen(self):
            if self.inner_file is not None:
                self.inner_file.close()
            open(self.filename, 'a').close()
            f = open(self.filename, 'rb')
            f.seek(0, os.SEEK_END)
            length = f.tell()
            if length > 100*1000*1000:
                f.seek(-1000*1000, os.SEEK_END)
                while True:
                    if f.read(1) in ('', '\n'):
                        break
                data = f.read()
                f.close()
                f = open(self.filename, 'wb')
                f.write(data)
            f.close()
            self.inner_file = codecs.open(self.filename, 'a', 'utf-8')
        def write(self, data):
            self.inner_file.write(data)
        def flush(self):
            self.inner_file.flush()
    class TeePipe(object):
        def __init__(self, outputs):
            self.outputs = outputs
        def write(self, data):
            for output in self.outputs:
                output.write(data)
        def flush(self):
            for output in self.outputs:
                output.flush()
    class TimestampingPipe(object):
        def __init__(self, inner_file):
            self.inner_file = inner_file
            self.buf = ''
            self.softspace = 0
        def write(self, data):
            buf = self.buf + data
            lines = buf.split('\n')
            for line in lines[:-1]:
                self.inner_file.write('%s %s\n' % (datetime.datetime.now(), line))
                self.inner_file.flush()
            self.buf = lines[-1]
        def flush(self):
            pass
    class AbortPipe(object):
        def __init__(self, inner_file):
            self.inner_file = inner_file
            self.softspace = 0
        def write(self, data):
            try:
                self.inner_file.write(data)
            except:
                sys.stdout = sys.__stdout__
                log.DefaultObserver.stderr = sys.stderr = sys.__stderr__
                raise
        def flush(self):
            self.inner_file.flush()
    class PrefixPipe(object):
        def __init__(self, inner_file, prefix):
            self.inner_file = inner_file
            self.prefix = prefix
            self.buf = ''
            self.softspace = 0
        def write(self, data):
            buf = self.buf + data
            lines = buf.split('\n')
            for line in lines[:-1]:
                self.inner_file.write(self.prefix + line + '\n')
                self.inner_file.flush()
            self.buf = lines[-1]
        def flush(self):
            pass
    logfile = LogFile(args.logfile)
    pipe = TimestampingPipe(TeePipe([EncodeReplacerPipe(sys.stderr), logfile]))
    sys.stdout = AbortPipe(pipe)
    sys.stderr = log.DefaultObserver.stderr = AbortPipe(PrefixPipe(pipe, '> '))
    if hasattr(signal, "SIGUSR1"):
        def sigusr1(signum, frame):
            print 'Caught SIGUSR1, closing %r...' % (args.logfile,)
            logfile.reopen()
            print '...and reopened %r after catching SIGUSR1.' % (args.logfile,)
        signal.signal(signal.SIGUSR1, sigusr1)
    task.LoopingCall(logfile.reopen).start(5)
    
    if args.bitcoind_rpc_port is None:
        args.bitcoind_rpc_port = net.PARENT.RPC_PORT
    
    if args.bitcoind_p2p_port is None:
        args.bitcoind_p2p_port = net.PARENT.P2P_PORT
    
    if args.p2pool_port is None:
        args.p2pool_port = net.P2P_PORT
    
    if args.worker_port is None:
        args.worker_port = net.WORKER_PORT
    
    if args.address is not None:
        try:
            args.pubkey_hash = bitcoin_data.address_to_pubkey_hash(args.address, net.PARENT)
        except Exception, e:
            parser.error('error parsing address: ' + repr(e))
    else:
        args.pubkey_hash = None
    
    if (args.merged_url is None) ^ (args.merged_userpass is None):
        parser.error('must specify --merged-url and --merged-userpass')
    
    reactor.callWhenRunning(main, args, net, datadir_path)
    reactor.run()
