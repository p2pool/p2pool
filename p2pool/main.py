#!/usr/bin/python

from __future__ import division

import argparse
import itertools
import os
import random
import sqlite3
import struct
import subprocess
import sys
import time

from twisted.internet import defer, reactor, task
from twisted.web import server
from twisted.python import log

import bitcoin.p2p, bitcoin.getwork, bitcoin.data
from util import db, expiring_dict, jsonrpc, variable, deferral, math, skiplist
from . import p2p, worker_interface
import p2pool.data as p2pool
import p2pool as p2pool_init

@deferral.retry('Error getting work from bitcoind:', 3)
@defer.inlineCallbacks
def getwork(bitcoind):
    # a block could arrive in between these two queries
    getwork_df, height_df = bitcoind.rpc_getwork(), bitcoind.rpc_getblocknumber()
    try:
        getwork, height = bitcoin.getwork.BlockAttempt.from_getwork((yield getwork_df)), (yield height_df)
    finally:
        # get rid of residual errors
        getwork_df.addErrback(lambda fail: None)
        height_df.addErrback(lambda fail: None)
    defer.returnValue((getwork, height))

@deferral.retry('Error getting payout script from bitcoind:', 1)
@defer.inlineCallbacks
def get_payout_script(factory):
    res = yield (yield factory.getProtocol()).check_order(order=bitcoin.p2p.Protocol.null_order)
    if res['reply'] == 'success':
        my_script = res['script']
    elif res['reply'] == 'denied':
        my_script = None
    else:
        raise ValueError('Unexpected reply: %r' % (res,))

@deferral.retry('Error creating payout script:', 10)
@defer.inlineCallbacks
def get_payout_script2(bitcoind, net):
    defer.returnValue(bitcoin.data.pubkey_hash_to_script2(bitcoin.data.address_to_pubkey_hash((yield bitcoind.rpc_getaccountaddress('p2pool')), net)))

@defer.inlineCallbacks
def main(args):
    try:
        print 'p2pool (version %s)' % (p2pool_init.__version__,)
        print
        
        # connect to bitcoind over JSON-RPC and do initial getwork
        url = 'http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port)
        print '''Testing bitcoind RPC connection to '%s' with authorization '%s:%s'...''' % (url, args.bitcoind_rpc_username, args.bitcoind_rpc_password)
        bitcoind = jsonrpc.Proxy(url, (args.bitcoind_rpc_username, args.bitcoind_rpc_password))
        temp_work, temp_height = yield getwork(bitcoind)
        print '    ...success!'
        print '    Current block hash: %x height: %i' % (temp_work.previous_block, temp_height)
        print
        
        # connect to bitcoind over bitcoin-p2p and do checkorder to get pubkey to send payouts to
        print '''Testing bitcoind P2P connection to '%s:%s'...''' % (args.bitcoind_address, args.bitcoind_p2p_port)
        factory = bitcoin.p2p.ClientFactory(args.net)
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        my_script = yield get_payout_script(factory)
        if args.pubkey_hash is None:
            if my_script is None:
                print 'IP transaction denied ... falling back to sending to address.'
                my_script = yield get_payout_script2(bitcoind, args.net)
        else:
            my_script = bitcoin.data.pubkey_hash_to_script2(args.pubkey_hash)
        print '    ...success!'
        print '    Payout script:', my_script.encode('hex')
        print
        
        @defer.inlineCallbacks
        def real_get_block(block_hash):
            block = yield (yield factory.getProtocol()).get_block(block_hash)
            print 'Got block %x' % (block_hash,)
            defer.returnValue(block)
        get_block = deferral.DeferredCacher(real_get_block, expiring_dict.ExpiringDict(3600))
        
        get_raw_transaction = deferral.DeferredCacher(lambda tx_hash: bitcoind.rpc_getrawtransaction('%x' % tx_hash), expiring_dict.ExpiringDict(100))
        
        ht = bitcoin.p2p.HeightTracker(factory)
        
        tracker = p2pool.OkayTracker(args.net)
        chains = expiring_dict.ExpiringDict(300)
        def get_chain(chain_id_data):
            return chains.setdefault(chain_id_data, Chain(chain_id_data))
        
        # information affecting work that should trigger a long-polling update
        current_work = variable.Variable(None)
        # information affecting work that should not trigger a long-polling update
        current_work2 = variable.Variable(None)
        
        requested = set()
        task.LoopingCall(requested.clear).start(60)
        
        @defer.inlineCallbacks
        def set_real_work1():
            work, height = yield getwork(bitcoind)
            current_work.set(dict(
                version=work.version,
                previous_block=work.previous_block,
                target=work.target,
                height=height,
                best_share_hash=current_work.value['best_share_hash'] if current_work.value is not None else None,
            ))
            current_work2.set(dict(
                time=work.timestamp,
            ))
        
        def set_real_work2():
            best, desired = tracker.think(ht, current_work.value['previous_block'], current_work2.value['time'])
            
            t = dict(current_work.value)
            t['best_share_hash'] = best
            current_work.set(t)
            
            for peer2, share_hash in desired:
                if peer2 is None:
                    continue
                if (peer2.nonce, share_hash) in requested:
                    continue
                print 'Requesting parent share %x' % (share_hash % 2**32,)
                peer2.send_getshares(
                    hashes=[share_hash],
                    parents=2000,
                    stops=list(set(tracker.heads) | set(
                        tracker.get_nth_parent_hash(head, min(max(0, tracker.get_height_and_last(head)[0] - 1), 10)) for head in tracker.heads
                    )),
                )
                requested.add((peer2.nonce, share_hash))
        
        print 'Initializing work...'
        yield set_real_work1()
        yield set_real_work2()
        print '    ...success!'
        
        # setup p2p logic and join p2pool network
        
        def share_share(share, ignore_peer=None):
            for peer in p2p_node.peers.itervalues():
                if peer is ignore_peer:
                    continue
                peer.send_shares([share])
            share.flag_shared()
        
        def p2p_shares(shares, peer=None):
            if len(shares) > 5:
                print "Processing %i shares..." % (len(shares),)
            
            for share in shares:
                if share.hash in tracker.shares:
                    #print 'Got duplicate share, ignoring. Hash: %x' % (share.hash % 2**32,)
                    continue
                
                #print 'Received share %x from %r' % (share.hash % 2**32, share.peer.transport.getPeer() if share.peer is not None else None)
                
                tracker.add(share)
                #for peer2, share_hash in desired:
                #    print 'Requesting parent share %x' % (share_hash,)
                #    peer2.send_getshares(hashes=[share_hash], parents=2000)
                
                if share.bitcoin_hash <= share.header['target']:
                        print
                        print 'GOT BLOCK! Passing to bitcoind! %x bitcoin: %x' % (share.hash % 2**32, share.bitcoin_hash,)
                        print
                        if factory.conn.value is not None:
                            factory.conn.value.send_block(block=share.as_block(tracker, net))
                        else:
                            print 'No bitcoind connection! Erp!'
            
            if shares:
                share = shares[0]
                
                best, desired = tracker.think(ht, current_work.value['previous_block'], current_work2.value['time'])
                
                if best == share.hash:
                    print ('MINE: ' if peer is None else '') + 'Accepted share, new best, will pass to peers! Hash: %x' % (share.hash % 2**32,)
                else:
                    print ('MINE: ' if peer is None else '') + 'Accepted share, not best. Hash: %x' % (share.hash % 2**32,)
                
                w = dict(current_work.value)
                w['best_share_hash'] = best
                current_work.set(w)
            
            if len(shares) > 5:
                print "... done processing %i shares." % (len(shares),)
        
        def p2p_share_hashes(share_hashes, peer):
            get_hashes = []
            for share_hash in share_hashes:
                if share_hash in tracker.shares:
                    pass # print 'Got share hash, already have, ignoring. Hash: %x' % (share_hash % 2**32,)
                else:
                    print 'Got share hash, requesting! Hash: %x' % (share_hash % 2**32,)
                    get_hashes.append(share_hash)
            if get_hashes:
                peer.send_getshares(hashes=get_hashes, parents=0, stops=[])
        
        def p2p_get_shares(share_hashes, parents, stops, peer):
            parents = min(parents, 1000//len(share_hashes))
            stops = set(stops)
            shares = []
            for share_hash in share_hashes:
                for share in itertools.islice(tracker.get_chain_known(share_hash), parents + 1):
                    if share.hash in stops:
                        break
                    shares.append(share)
            peer.send_shares(shares, full=True)
        
        print 'Joining p2pool network using TCP port %i...' % (args.p2pool_port,)
        
        def parse(x):
            if ':' in x:
                ip, port = x.split(':')
                return ip, int(port)
            else:
                return x, args.net.P2P_PORT
        
        nodes = [
            ('72.14.191.28', args.net.P2P_PORT),
            ('62.204.197.159', args.net.P2P_PORT),
        ]
        try:
            nodes.append(((yield reactor.resolve('p2pool.forre.st')), args.net.P2P_PORT))
        except:
            print
            print 'Error resolving bootstrap node IP:'
            log.err()
            print
        
        p2p_node = p2p.Node(
            current_work=current_work,
            port=args.p2pool_port,
            net=args.net,
            addr_store=db.SQLiteDict(sqlite3.connect(os.path.join(os.path.dirname(sys.argv[0]), 'addrs.dat'), isolation_level=None), args.net.ADDRS_TABLE),
            mode=0 if args.low_bandwidth else 1,
            preferred_addrs=map(parse, args.p2pool_nodes) + nodes,
        )
        p2p_node.handle_shares = p2p_shares
        p2p_node.handle_share_hashes = p2p_share_hashes
        p2p_node.handle_get_shares = p2p_get_shares
        
        p2p_node.start()
        
        # send share when the chain changes to their chain
        def work_changed(new_work):
            #print 'Work changed:', new_work
            for share in tracker.get_chain_known(new_work['best_share_hash']):
                if share.shared:
                    break
                share_share(share, share.peer)
        current_work.changed.watch(work_changed)
        
        print '    ...success!'
        print
        
        # start listening for workers with a JSON-RPC server
        
        print 'Listening for workers on port %i...' % (args.worker_port,)
        
        # setup worker logic
        
        merkle_root_to_transactions = expiring_dict.ExpiringDict(300)
        run_identifier = struct.pack('<Q', random.randrange(2**64))
        
        def compute(state, all_targets):
            start = time.time()
            pre_extra_txs = [tx for tx in tx_pool.itervalues() if tx.is_good()]
            pre_extra_txs = pre_extra_txs[:2**16 - 1] # merkle_branch limit
            extra_txs = []
            size = 0
            for tx in pre_extra_txs:
                this_size = len(bitcoin.data.tx_type.pack(tx.tx))
                if size + this_size > 500000:
                    break
                extra_txs.append(tx)
                size += this_size
            # XXX check sigops!
            # XXX assuming generate_tx is smallish here..
            generate_tx = p2pool.generate_transaction(
                tracker=tracker,
                previous_share_hash=state['best_share_hash'],
                new_script=my_script,
                subsidy=(50*100000000 >> (state['height'] + 1)//210000) + sum(tx.value_in - tx.value_out for tx in extra_txs),
                nonce=run_identifier + struct.pack('<Q', random.randrange(2**64)),
                block_target=state['target'],
                net=args.net,
            )
            print 'Generating! Difficulty: %.06f Payout if block: %.6f BTC' % (0xffff*2**208/p2pool.coinbase_type.unpack(generate_tx['tx_ins'][0]['script'])['share_data']['target'], generate_tx['tx_outs'][-1]['value']*1e-8)
            #print 'Target: %x' % (p2pool.coinbase_type.unpack(generate_tx['tx_ins'][0]['script'])['share_data']['target'],)
            #, have', shares.count(my_script) - 2, 'share(s) in the current chain. Fee:', sum(tx.value_in - tx.value_out for tx in extra_txs)/100000000
            transactions = [generate_tx] + [tx.tx for tx in extra_txs]
            merkle_root = bitcoin.data.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = transactions # will stay for 1000 seconds
            
            timestamp = current_work2.value['time']
            if state['best_share_hash'] is not None:
                timestamp2 = math.median((s.timestamp for s in itertools.islice(tracker.get_chain_to_root(state['best_share_hash']), 11)), use_float=False) + 1
                if timestamp2 > timestamp:
                    print 'Toff', timestamp2 - timestamp
                    timestamp = timestamp2
            target2 = p2pool.coinbase_type.unpack(generate_tx['tx_ins'][0]['script'])['share_data']['target']
            if not all_targets:
                target2 = min(2**256//2**32 - 1, target2)
            print "TOOK", time.time() - start
            times[p2pool.coinbase_type.unpack(generate_tx['tx_ins'][0]['script'])['share_data']['nonce']] = time.time()
            #print 'SENT', 2**256//p2pool.coinbase_type.unpack(generate_tx['tx_ins'][0]['script'])['share_data']['target']
            return bitcoin.getwork.BlockAttempt(state['version'], state['previous_block'], merkle_root, timestamp, state['target'], target2)
        
        my_shares = set()
        times = {}
        
        def got_response(data):
            try:
                # match up with transactions
                header = bitcoin.getwork.decode_data(data)
                transactions = merkle_root_to_transactions.get(header['merkle_root'], None)
                if transactions is None:
                    print '''Couldn't link returned work's merkle root with its transactions - should only happen if you recently restarted p2pool'''
                    return False
                block = dict(header=header, txs=transactions)
                hash_ = bitcoin.data.block_header_type.hash256(block['header'])
                if hash_ <= block['header']['target']:
                    print
                    print 'GOT BLOCK! Passing to bitcoind! %x' % (hash_,)
                    print
                    if factory.conn.value is not None:
                        factory.conn.value.send_block(block=block)
                    else:
                        print 'No bitcoind connection! Erp!'
                target = p2pool.coinbase_type.unpack(transactions[0]['tx_ins'][0]['script'])['share_data']['target']
                if hash_ > target:
                    print 'Received invalid share from worker - %x/%x' % (hash_, target)
                    return False
                share = p2pool.Share.from_block(block)
                my_shares.add(share.hash)
                print 'GOT SHARE! %x %x' % (share.hash % 2**32, 0 if share.previous_hash is None else share.previous_hash), "DEAD ON ARRIVAL" if share.previous_hash != current_work.value['best_share_hash'] else "", time.time() - times[share.nonce]
                p2p_shares([share])
            except:
                print
                print 'Error processing data received from worker:'
                log.err()
                print
                return False
            else:
                return True
        
        def get_rate():
            if current_work.value['best_share_hash'] is not None:
                height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
                att_s = p2pool.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], args.net)
                return att_s
        
        reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response, get_rate)))
        
        print '    ...success!'
        print
        
        # done!
        
        def get_blocks(start_hash):
            while True:
                try:
                    block = get_block.call_now(start_hash)
                except deferral.NotNowError:
                    break
                yield start_hash, block
                start_hash = block['header']['previous_block']
        
        tx_pool = expiring_dict.ExpiringDict(600, get_touches=False) # hash -> tx
        
        class Tx(object):
            def __init__(self, tx, seen_at_block):
                self.hash = bitcoin.data.tx_type.hash256(tx)
                self.tx = tx
                self.seen_at_block = seen_at_block
                self.mentions = set([bitcoin.data.tx_type.hash256(tx)] + [tx_in['previous_output']['hash'] for tx_in in tx['tx_ins']])
                #print
                #print '%x %r' % (seen_at_block, tx)
                #for mention in self.mentions:
                #    print '%x' % mention
                #print
                self.parents_all_in_blocks = False
                self.value_in = 0
                #print self.tx
                self.value_out = sum(txout['value'] for txout in self.tx['tx_outs'])
                self._find_parents_in_blocks()
            
            @defer.inlineCallbacks
            def _find_parents_in_blocks(self):
                for tx_in in self.tx['tx_ins']:
                    try:
                        raw_transaction = yield get_raw_transaction(tx_in['previous_output']['hash'])
                    except Exception:
                        return
                    self.value_in += raw_transaction['tx']['txouts'][tx_in['previous_output']['index']]['value']
                    #print raw_transaction
                    if not raw_transaction['parent_blocks']:
                        return
                self.parents_all_in_blocks = True
            
            def is_good(self):
                if not self.parents_all_in_blocks:
                    return False
                x = self.is_good2()
                #print 'is_good:', x
                return x
            
            def is_good2(self):
                for block_hash, block in itertools.islice(get_blocks(current_work.value['previous_block']), 10):
                    if block_hash == self.seen_at_block:
                        return True
                    for tx in block['txs']:
                        mentions = set([bitcoin.data.tx_type.hash256(tx)] + [tx_in['previous_output']['hash'] for tx_in in tx['tx_ins'] if tx_in['previous_output'] is not None])
                        if mentions & self.mentions:
                            return False
                return False
        
        @defer.inlineCallbacks
        def new_tx(tx_hash):
            try:
                assert isinstance(tx_hash, (int, long))
                #print "REQUESTING", tx_hash
                tx = yield (yield factory.getProtocol()).get_tx(tx_hash)
                #print "GOT", tx
                tx_pool[bitcoin.data.tx_type.hash256(tx)] = Tx(tx, current_work.value['previous_block'])
            except:
                print
                print 'Error handling tx:'
                log.err()
                print
        factory.new_tx.watch(new_tx)
        
        @defer.inlineCallbacks
        def new_block(block):
            yield set_real_work1()
            set_real_work2()
        factory.new_block.watch(new_block)
        
        print 'Started successfully!'
        print
        
        @defer.inlineCallbacks
        def work1_thread():
            while True:
                yield deferral.sleep(random.expovariate(1/1))
                try:
                    yield set_real_work1()
                except:
                    log.err()
        
        
        @defer.inlineCallbacks
        def work2_thread():
            while True:
                yield deferral.sleep(random.expovariate(1/1))
                try:
                    yield set_real_work2()
                except:
                    log.err()
        
        work1_thread()
        work2_thread()
        
        counter = skiplist.CountsSkipList(tracker, my_script, run_identifier)
        
        while True:
            yield deferral.sleep(random.expovariate(1/1))
            try:
                if current_work.value['best_share_hash'] is not None:
                    height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
                    if height > 5:
                        att_s = p2pool.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], args.net)
                        weights, total_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 1000), 2**100)
                        count = counter(current_work.value['best_share_hash'], height, 2**100)
                        print 'Pool: %i mhash/s in %i shares Recent: %.02f%% >%i mhash/s Known: %i shares (so %i stales)' % (
                            att_s//1000000,
                            height,
                            weights.get(my_script, 0)/total_weight*100,
                            weights.get(my_script, 0)/total_weight*att_s//1000000,
                            count,
                            len(my_shares) - count,
                        )
                        #weights, total_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 100), 2**100)
                        #for k, v in weights.iteritems():
                        #    print k.encode('hex'), v/total_weight
            except:
                log.err()
    except:
        print
        print 'Fatal error:'
        log.err()
        print
        reactor.stop()

def run():
    parser = argparse.ArgumentParser(description='p2pool (version %s)' % (p2pool_init.__version__,))
    parser.add_argument('--version', action='version', version=p2pool_init.__version__)
    parser.add_argument('--testnet',
        help='use the testnet',
        action='store_const', const=p2pool.Testnet, default=p2pool.Mainnet, dest='net')
    parser.add_argument('--debug',
        help='debugging mode',
        action='store_const', const=True, default=False, dest='debug')
    parser.add_argument('-a', '--address',
        help='generate to this address (defaults to requesting one from bitcoind)',
        type=str, action='store', default=None, dest='address')
    
    p2pool_group = parser.add_argument_group('p2pool interface')
    p2pool_group.add_argument('--p2pool-port', metavar='PORT',
        help='use TCP port PORT to listen for connections (default: 9333 normally, 19333 for testnet) (forward this port from your router!)',
        type=int, action='store', default=None, dest='p2pool_port')
    p2pool_group.add_argument('-n', '--p2pool-node', metavar='ADDR[:PORT]',
        help='connect to existing p2pool node at ADDR listening on TCP port PORT (defaults to 9333 normally, 19333 for testnet), in addition to builtin addresses',
        type=str, action='append', default=[], dest='p2pool_nodes')
    parser.add_argument('-l', '--low-bandwidth',
        help='trade lower bandwidth usage for higher latency (reduced efficiency)',
        action='store_true', default=False, dest='low_bandwidth')
    
    worker_group = parser.add_argument_group('worker interface')
    worker_group.add_argument('-w', '--worker-port', metavar='PORT',
        help='listen on PORT for RPC connections from miners asking for work and providing responses (default: 9332)',
        type=int, action='store', default=9332, dest='worker_port')
    
    bitcoind_group = parser.add_argument_group('bitcoind interface')
    bitcoind_group.add_argument('--bitcoind-address', metavar='BITCOIND_ADDRESS',
        help='connect to a bitcoind at this address (default: 127.0.0.1)',
        type=str, action='store', default='127.0.0.1', dest='bitcoind_address')
    bitcoind_group.add_argument('--bitcoind-rpc-port', metavar='BITCOIND_RPC_PORT',
        help='connect to a bitcoind at this port over the RPC interface - used to get the current highest block via getwork (default: 8332)',
        type=int, action='store', default=8332, dest='bitcoind_rpc_port')
    bitcoind_group.add_argument('--bitcoind-p2p-port', metavar='BITCOIND_P2P_PORT',
        help='connect to a bitcoind at this port over the p2p interface - used to submit blocks and get the pubkey to generate to via an IP transaction (default: 8333 normally. 18333 for testnet)',
        type=int, action='store', default=None, dest='bitcoind_p2p_port')
    
    bitcoind_group.add_argument(metavar='BITCOIND_RPC_USERNAME',
        help='bitcoind RPC interface username',
        type=str, action='store', dest='bitcoind_rpc_username')
    bitcoind_group.add_argument(metavar='BITCOIND_RPC_PASSWORD',
        help='bitcoind RPC interface password',
        type=str, action='store', dest='bitcoind_rpc_password')
    
    args = parser.parse_args()
    
    if args.debug:
        p2pool_init.DEBUG = True
    
    if args.bitcoind_p2p_port is None:
        args.bitcoind_p2p_port = args.net.BITCOIN_P2P_PORT
    
    if args.p2pool_port is None:
        args.p2pool_port = args.net.P2P_PORT
    
    if args.address is not None:
        try:
            args.pubkey_hash = bitcoin.data.address_to_pubkey_hash(args.address, args.net)
        except Exception, e:
            raise ValueError("error parsing address: " + repr(e))
    else:
        args.pubkey_hash = None
    
    reactor.callWhenRunning(main, args)
    reactor.run()
