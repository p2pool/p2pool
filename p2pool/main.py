#!/usr/bin/python
# coding=utf-8

from __future__ import division

import argparse
import codecs
import datetime
import itertools
import os
import random
import struct
import sys
import time
import json
import signal
import traceback

from twisted.internet import defer, reactor, task
from twisted.web import server, resource
from twisted.python import log
from nattraverso import portmapper, ipdiscover

import bitcoin.p2p as bitcoin_p2p, bitcoin.getwork as bitcoin_getwork, bitcoin.data as bitcoin_data
from bitcoin import worker_interface
from util import expiring_dict, jsonrpc, variable, deferral, math
from . import p2p, skiplists, networks
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
        target=bitcoin_data.FloatingIntegerType().unpack(work['bits'].decode('hex')[::-1]) if isinstance(work['bits'], (str, unicode)) else bitcoin_data.FloatingInteger(work['bits']),
    ))

@deferral.retry('Error creating payout script:', 10)
@defer.inlineCallbacks
def get_payout_script2(bitcoind, net):
    address = yield bitcoind.rpc_getaccountaddress('p2pool')
    validate_response = yield bitcoind.rpc_validateaddress(address)
    if 'pubkey' not in validate_response:
        print '    Pubkey request failed. Falling back to payout to address.'
        defer.returnValue(bitcoin_data.pubkey_hash_to_script2(bitcoin_data.address_to_pubkey_hash(address, net)))
    pubkey = validate_response['pubkey'].decode('hex')
    defer.returnValue(bitcoin_data.pubkey_to_script2(pubkey))

@defer.inlineCallbacks
def main(args, net, datadir_path):
    try:
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
        good = yield deferral.retry('Error while checking bitcoind identity:', 1)(net.BITCOIN_RPC_CHECK)(bitcoind)
        if not good:
            print "    Check failed! Make sure that you're connected to the right bitcoind with --bitcoind-rpc-port!"
            return
        temp_work = yield getwork(bitcoind)
        print '    ...success!'
        print '    Current block hash: %x' % (temp_work['previous_block_hash'],)
        print
        
        # connect to bitcoind over bitcoin-p2p
        print '''Testing bitcoind P2P connection to '%s:%s'...''' % (args.bitcoind_address, args.bitcoind_p2p_port)
        factory = bitcoin_p2p.ClientFactory(net)
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        yield factory.getProtocol() # waits until handshake is successful
        print '    ...success!'
        print
        
        if args.pubkey_hash is None:
            print 'Getting payout address from bitcoind...'
            my_script = yield get_payout_script2(bitcoind, net)
        else:
            print 'Computing payout script from provided address....'
            my_script = bitcoin_data.pubkey_hash_to_script2(args.pubkey_hash)
        print '    ...success!'
        print '    Payout script:', bitcoin_data.script2_to_human(my_script, net)
        print
        
        ht = bitcoin_p2p.HeightTracker(bitcoind, factory)
        
        tracker = p2pool_data.OkayTracker(net)
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
        
        peer_heads = expiring_dict.ExpiringDict(300) # hash -> peers that know of it
        
        pre_current_work = variable.Variable(None)
        pre_current_work2 = variable.Variable(None)
        pre_merged_work = variable.Variable(None)
        # information affecting work that should trigger a long-polling update
        current_work = variable.Variable(None)
        # information affecting work that should not trigger a long-polling update
        current_work2 = variable.Variable(None)
        
        work_updated = variable.Event()
        
        requested = expiring_dict.ExpiringDict(300)
        
        @defer.inlineCallbacks
        def set_real_work1():
            work = yield getwork(bitcoind)
            pre_current_work2.set(dict(
                time=work['time'],
                transactions=work['transactions'],
                subsidy=work['subsidy'],
                clock_offset=time.time() - work['time'],
                last_update=time.time(),
            )) # second set first because everything hooks on the first
            pre_current_work.set(dict(
                version=work['version'],
                previous_block=work['previous_block_hash'],
                target=work['target'],
            ))
        
        def set_real_work2():
            best, desired = tracker.think(ht, pre_current_work.value['previous_block'], time.time() - pre_current_work2.value['clock_offset'])
            
            current_work2.set(pre_current_work2.value)
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
        
        @defer.inlineCallbacks
        def set_merged_work():
            if not args.merged_url:
                return
            merged = jsonrpc.Proxy(args.merged_url, (args.merged_userpass,))
            while True:
                auxblock = yield deferral.retry('Error while calling merged getauxblock:', 1)(merged.rpc_getauxblock)()
                pre_merged_work.set(dict(
                    hash=int(auxblock['hash'], 16),
                    target=bitcoin_data.HashType().unpack(auxblock['target'].decode('hex')),
                    chain_id=auxblock['chainid'],
                ))
                yield deferral.sleep(1)
        set_merged_work()
        
        start_time = time.time() - current_work2.value['clock_offset']
        
        # setup p2p logic and join p2pool network
        
        def p2p_shares(shares, peer=None):
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
        
        @tracker.verified.added.watch
        def _(share):
            if share.pow_hash <= share.header['target']:
                if factory.conn.value is not None:
                    factory.conn.value.send_block(block=share.as_block(tracker))
                else:
                    print 'No bitcoind connection! Erp!'
                print
                print 'GOT BLOCK! Passing to bitcoind! %s bitcoin: %x' % (p2pool_data.format_hash(share.hash), share.header_hash,)
                print
        
        def p2p_share_hashes(share_hashes, peer):
            t = time.time()
            get_hashes = []
            for share_hash in share_hashes:
                if share_hash in tracker.shares:
                    continue
                last_request_time, count = requested.get(share_hash, (None, 0))
                if last_request_time is not None and last_request_time - 5 < t < last_request_time + 10 * 1.5**count:
                    continue
                print 'Got share hash, requesting! Hash: %s' % (p2pool_data.format_hash(share_hash),)
                get_hashes.append(share_hash)
                requested[share_hash] = t, count + 1
            
            if share_hashes and peer is not None:
                peer_heads.setdefault(share_hashes[0], set()).add(peer)
            if get_hashes:
                peer.send_getshares(hashes=get_hashes, parents=0, stops=[])
        
        def p2p_get_shares(share_hashes, parents, stops, peer):
            parents = min(parents, 1000//len(share_hashes))
            stops = set(stops)
            shares = []
            for share_hash in share_hashes:
                for share in tracker.get_chain(share_hash, min(parents + 1, tracker.get_height(share_hash))):
                    if share.hash in stops:
                        break
                    shares.append(share)
            print 'Sending %i shares to %s:%i' % (len(shares), peer.addr[0], peer.addr[1])
            peer.sendShares(shares)
        
        print 'Joining p2pool network using port %i...' % (args.p2pool_port,)
        
        def parse(x):
            if ':' in x:
                ip, port = x.split(':')
                return ip, int(port)
            else:
                return x, net.P2P_PORT
        
        nodes = set([
            ('72.14.191.28', net.P2P_PORT),
            ('62.204.197.159', net.P2P_PORT),
            ('142.58.248.28', net.P2P_PORT),
            ('94.23.34.145', net.P2P_PORT),
        ])
        for host in [
            'p2pool.forre.st',
            'dabuttonfactory.com',
            ] + (['liteco.in'] if net.NAME == 'litecoin' else []) + [
        ]:
            try:
                nodes.add(((yield reactor.resolve(host)), net.P2P_PORT))
            except:
                log.err(None, 'Error resolving bootstrap node IP:')
        
        addrs = {}
        try:
            addrs = dict(eval(x) for x in open(os.path.join(datadir_path, 'addrs.txt')))
        except:
            print "error reading addrs"
        
        def save_addrs():
            open(os.path.join(datadir_path, 'addrs.txt'), 'w').writelines(repr(x) + '\n' for x in addrs.iteritems())
        task.LoopingCall(save_addrs).start(60)
        
        p2p_node = p2p.Node(
            current_work=current_work,
            port=args.p2pool_port,
            net=net,
            addr_store=addrs,
            preferred_addrs=set(map(parse, args.p2pool_nodes)) | nodes,
        )
        p2p_node.handle_shares = p2p_shares
        p2p_node.handle_share_hashes = p2p_share_hashes
        p2p_node.handle_get_shares = p2p_get_shares
        
        p2p_node.start()
        
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
                        yield pm._upnp.add_port_mapping(lan_ip, args.p2pool_port, args.p2pool_port, 'p2pool', 'TCP') # XXX try to forward external correct port?
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
        
        # setup worker logic
        
        merkle_root_to_transactions = expiring_dict.ExpiringDict(300)
        run_identifier = struct.pack('<I', random.randrange(2**32))
        
        share_counter = skiplists.CountsSkipList(tracker, run_identifier)
        removed_unstales = set()
        def get_share_counts(doa=False):
            height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
            matching_in_chain = share_counter(current_work.value['best_share_hash'], height) | removed_unstales
            shares_in_chain = my_shares & matching_in_chain
            stale_shares = my_shares - matching_in_chain
            if doa:
                stale_doa_shares = stale_shares & doa_shares
                stale_not_doa_shares = stale_shares - stale_doa_shares
                return len(shares_in_chain) + len(stale_shares), len(stale_doa_shares), len(stale_not_doa_shares)
            return len(shares_in_chain) + len(stale_shares), len(stale_shares)
        @tracker.verified.removed.watch
        def _(share):
            if share.hash in my_shares and tracker.is_child_of(share.hash, current_work.value['best_share_hash']):
                removed_unstales.add(share.hash)
        
        
        def get_payout_script_from_username(user):
            if user is None:
                return None
            try:
                return bitcoin_data.pubkey_hash_to_script2(bitcoin_data.address_to_pubkey_hash(user, net))
            except: # XXX blah
                return None
        
        def compute(request):
            state = current_work.value
            user = worker_interface.get_username(request)
            
            payout_script = get_payout_script_from_username(user)
            if payout_script is None or random.uniform(0, 100) < args.worker_fee:
                payout_script = my_script
            
            if len(p2p_node.peers) == 0 and net.PERSIST:
                raise jsonrpc.Error(-12345, u'p2pool is not connected to any peers')
            if state['best_share_hash'] is None and net.PERSIST:
                raise jsonrpc.Error(-12345, u'p2pool is downloading shares')
            if time.time() > current_work2.value['last_update'] + 60:
                raise jsonrpc.Error(-12345, u'lost contact with bitcoind')
            
            previous_share = None if state['best_share_hash'] is None else tracker.shares[state['best_share_hash']]
            subsidy = current_work2.value['subsidy']
            share_info, generate_tx = p2pool_data.generate_transaction(
                tracker=tracker,
                share_data=dict(
                    previous_share_hash=state['best_share_hash'],
                    coinbase='' if state['aux_work'] is None else '\xfa\xbemm' + bitcoin_data.HashType().pack(state['aux_work']['hash'])[::-1] + struct.pack('<ii', 1, 0),
                    nonce=run_identifier + struct.pack('<Q', random.randrange(2**64)),
                    new_script=payout_script,
                    subsidy=subsidy,
                    donation=math.perfect_round(65535*args.donation_percentage/100),
                    stale_frac=(lambda shares, stales:
                        255 if shares == 0 else math.perfect_round(254*stales/shares)
                    )(*get_share_counts()),
                ),
                block_target=state['target'],
                desired_timestamp=int(time.time() - current_work2.value['clock_offset']),
                net=net,
            )
            
            print 'New work for worker %s! Difficulty: %.06f Payout if block: %.6f %s Total block value: %.6f %s including %i transactions' % (
                user,
                bitcoin_data.target_to_difficulty(share_info['target']),
                (sum(t['value'] for t in generate_tx['tx_outs'] if t['script'] == payout_script) - subsidy//200)*1e-8, net.BITCOIN_SYMBOL,
                subsidy*1e-8, net.BITCOIN_SYMBOL,
                len(current_work2.value['transactions']),
            )
            
            transactions = [generate_tx] + list(current_work2.value['transactions'])
            merkle_root = bitcoin_data.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = share_info, transactions, time.time()
            
            return bitcoin_getwork.BlockAttempt(state['version'], state['previous_block'], merkle_root, current_work2.value['time'], state['target'], share_info['target']), state['best_share_hash']
        
        my_shares = set()
        doa_shares = set()
        
        def got_response(header, request):
            try:
                user = worker_interface.get_username(request)
                # match up with transactions
                xxx = merkle_root_to_transactions.get(header['merkle_root'], None)
                if xxx is None:
                    print '''Couldn't link returned work's merkle root with its transactions - should only happen if you recently restarted p2pool'''
                    return False
                share_info, transactions, getwork_time = xxx
                
                hash_ = bitcoin_data.block_header_type.hash256(header)
                
                pow_hash = net.BITCOIN_POW_FUNC(header)
                
                if pow_hash <= header['target'] or p2pool.DEBUG:
                    if factory.conn.value is not None:
                        factory.conn.value.send_block(block=dict(header=header, txs=transactions))
                    else:
                        print 'No bitcoind connection! Erp!'
                    if pow_hash <= header['target']:
                        print
                        print 'GOT BLOCK! Passing to bitcoind! bitcoin: %x' % (hash_,)
                        print
                
                if current_work.value['aux_work'] is not None and pow_hash <= current_work.value['aux_work']['target']:
                    try:
                        aux_pow = dict(
                            merkle_tx=dict(
                                tx=transactions[0],
                                block_hash=hash_,
                                merkle_branch=[x['hash'] for x in p2pool_data.calculate_merkle_branch(transactions, 0)],
                                index=0,
                            ),
                            merkle_branch=[],
                            index=0,
                            parent_block_header=header,
                        )
                        
                        a, b = transactions[0]['tx_ins'][0]['script'][-32-8:-8].encode('hex'), bitcoin_data.aux_pow_type.pack(aux_pow).encode('hex')
                        #print a, b
                        merged = jsonrpc.Proxy(args.merged_url, (args.merged_userpass,))
                        def _(res):
                            print "MERGED RESULT:", res
                        merged.rpc_getauxblock(a, b).addBoth(_)
                    except:
                        log.err(None, 'Error while processing merged mining POW:')
                
                target = share_info['target']
                if pow_hash > target:
                    print 'Worker submitted share with hash > target:\nhash  : %x\ntarget: %x' % (pow_hash, target)
                    return False
                share = p2pool_data.Share(net, header, share_info, other_txs=transactions[1:])
                my_shares.add(share.hash)
                if share.previous_hash != current_work.value['best_share_hash']:
                    doa_shares.add(share.hash)
                print 'GOT SHARE! %s %s prev %s age %.2fs' % (user, p2pool_data.format_hash(share.hash), p2pool_data.format_hash(share.previous_hash), time.time() - getwork_time) + (' DEAD ON ARRIVAL' if share.previous_hash != current_work.value['best_share_hash'] else '')
                good = share.previous_hash == current_work.value['best_share_hash']
                # maybe revert back to tracker being non-blocking so 'good' can be more accurate?
                p2p_shares([share])
                # eg. good = share.hash == current_work.value['best_share_hash'] here
                return good
            except:
                log.err(None, 'Error processing data received from worker:')
                return False
        
        web_root = worker_interface.WorkerInterface(compute, got_response, current_work.changed)
        
        def get_rate():
            if current_work.value['best_share_hash'] is not None:
                height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
                att_s = p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], min(height - 1, 720))
                fracs = [share.stale_frac for share in tracker.get_chain(current_work.value['best_share_hash'], min(120, height)) if share.stale_frac is not None]
                return json.dumps(int(att_s / (1. - (math.median(fracs) if fracs else 0))))
            return json.dumps(None)
        
        def get_users():
            height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
            weights, total_weight, donation_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 720), 65535*2**256)
            res = {}
            for script in sorted(weights, key=lambda s: weights[s]):
                res[bitcoin_data.script2_to_human(script, net)] = weights[script]/total_weight
            return json.dumps(res)
        
        class WebInterface(resource.Resource):
            def __init__(self, func, mime_type):
                self.func, self.mime_type = func, mime_type
            
            def render_GET(self, request):
                request.setHeader('Content-Type', self.mime_type)
                return self.func()
        
        web_root.putChild('rate', WebInterface(get_rate, 'application/json'))
        web_root.putChild('users', WebInterface(get_users, 'application/json'))
        web_root.putChild('fee', WebInterface(lambda: json.dumps(args.worker_fee), 'application/json'))
        if draw is not None:
            web_root.putChild('chain_img', WebInterface(lambda: draw.get(tracker, current_work.value['best_share_hash']), 'image/png'))
        
        reactor.listenTCP(args.worker_port, server.Site(web_root))
        
        print '    ...success!'
        print
        
        # done!
        
        # do new getwork when a block is heard on the p2p interface
        
        def new_block(block_hash):
            work_updated.happened()
        factory.new_block.watch(new_block)
        
        print 'Started successfully!'
        print
        
        @defer.inlineCallbacks
        def work1_thread():
            while True:
                flag = work_updated.get_deferred()
                try:
                    yield set_real_work1()
                except:
                    log.err()
                yield defer.DeferredList([flag, deferral.sleep(random.uniform(1, 10))], fireOnOneCallback=True)
        
        @defer.inlineCallbacks
        def work2_thread():
            while True:
                try:
                    set_real_work2()
                except:
                    log.err()
                yield deferral.sleep(random.expovariate(1/20))
        
        work1_thread()
        work2_thread()
        
        
        if hasattr(signal, 'SIGALRM'):
            def watchdog_handler(signum, frame):
                print 'Watchdog timer went off at:'
                traceback.print_stack()
            
            signal.signal(signal.SIGALRM, watchdog_handler)
            task.LoopingCall(signal.alarm, 30).start(1)
        
        @defer.inlineCallbacks
        def status_thread():
            last_str = None
            last_time = 0
            while True:
                yield deferral.sleep(3)
                try:
                    if time.time() > current_work2.value['last_update'] + 60:
                        print '''---> LOST CONTACT WITH BITCOIND for 60 seconds, check that it isn't frozen or dead <---'''
                    if current_work.value['best_share_hash'] is not None:
                        height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
                        if height > 2:
                            att_s = p2pool_data.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], min(height - 1, 720))
                            weights, total_weight, donation_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 720), 65535*2**256)
                            shares, stale_doa_shares, stale_not_doa_shares = get_share_counts(True)
                            stale_shares = stale_doa_shares + stale_not_doa_shares
                            fracs = [share.stale_frac for share in tracker.get_chain(current_work.value['best_share_hash'], min(120, height)) if share.stale_frac is not None]
                            this_str = 'Pool: %sH/s in %i shares (%i/%i verified) Recent: %.02f%% >%sH/s Shares: %i (%i orphan, %i dead) Peers: %i' % (
                                math.format(int(att_s / (1. - (math.median(fracs) if fracs else 0)))),
                                height,
                                len(tracker.verified.shares),
                                len(tracker.shares),
                                weights.get(my_script, 0)/total_weight*100,
                                math.format(int(weights.get(my_script, 0)*att_s//total_weight / (1. - (math.median(fracs) if fracs else 0)))),
                                shares,
                                stale_not_doa_shares,
                                stale_doa_shares,
                                len(p2p_node.peers),
                            ) + (' FDs: %i R/%i W' % (len(reactor.getReaders()), len(reactor.getWriters())) if p2pool.DEBUG else '')
                            if fracs:
                                med = math.median(fracs)
                                this_str += '\nPool stales: %i%%' % (int(100*med+.5),)
                                conf = 0.95
                                if shares:
                                    this_str += u' Own: %i±%i%%' % tuple(int(100*x+.5) for x in math.interval_to_center_radius(math.binomial_conf_interval(stale_shares, shares, conf)))
                                    if med < .99:
                                        this_str += u' Own efficiency: %i±%i%%' % tuple(int(100*x+.5) for x in math.interval_to_center_radius((1 - y)/(1 - med) for y in math.binomial_conf_interval(stale_shares, shares, conf)[::-1]))
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
        help='''connect to JSON-RPC interface at this port (default: %s)''' % ', '.join('%s:%i' % (n.NAME, n.BITCOIN_RPC_PORT) for _, n in sorted(networks.realnets.items())),
        type=int, action='store', default=None, dest='bitcoind_rpc_port')
    bitcoind_group.add_argument('--bitcoind-p2p-port', metavar='BITCOIND_P2P_PORT',
        help='''connect to P2P interface at this port (default: %s)''' % ', '.join('%s:%i' % (n.NAME, n.BITCOIN_P2P_PORT) for _, n in sorted(networks.realnets.items())),
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
                data = data.encode(self.inner_file.encoding, 'replace')
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
                self.inner_file.write('%s %s\n' % (datetime.datetime.now().strftime("%H:%M:%S.%f"), line))
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
    logfile = LogFile(args.logfile)
    sys.stdout = sys.stderr = log.DefaultObserver.stderr = AbortPipe(TimestampingPipe(TeePipe([EncodeReplacerPipe(sys.stderr), logfile])))
    if hasattr(signal, "SIGUSR1"):
        def sigusr1(signum, frame):
            print 'Caught SIGUSR1, closing %r...' % (args.logfile,)
            logfile.reopen()
            print '...and reopened %r after catching SIGUSR1.' % (args.logfile,)
        signal.signal(signal.SIGUSR1, sigusr1)
    task.LoopingCall(logfile.reopen).start(5)
    
    if args.bitcoind_rpc_port is None:
        args.bitcoind_rpc_port = net.BITCOIN_RPC_PORT
    
    if args.bitcoind_p2p_port is None:
        args.bitcoind_p2p_port = net.BITCOIN_P2P_PORT
    
    if args.p2pool_port is None:
        args.p2pool_port = net.P2P_PORT
    
    if args.worker_port is None:
        args.worker_port = net.WORKER_PORT
    
    if args.address is not None:
        try:
            args.pubkey_hash = bitcoin_data.address_to_pubkey_hash(args.address, net)
        except Exception, e:
            parser.error('error parsing address: ' + repr(e))
    else:
        args.pubkey_hash = None
    
    if (args.merged_url is None) ^ (args.merged_userpass is None):
        parser.error('must specify --merged-url and --merged-userpass')
    
    reactor.callWhenRunning(main, args, net, datadir_path)
    reactor.run()
