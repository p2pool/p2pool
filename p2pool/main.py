#!/usr/bin/python

from __future__ import division

import argparse
import datetime
import itertools
import os
import random
import sqlite3
import struct
import sys
import time

from twisted.internet import defer, reactor
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
        defer.returnValue(res['script'])
    elif res['reply'] == 'denied':
        defer.returnValue(None)
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
        print '''Testing bitcoind RPC connection to '%s' with username '%s'...''' % (url, args.bitcoind_rpc_username)
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
        
        ht = bitcoin.p2p.HeightTracker(factory)
        
        tracker = p2pool.OkayTracker(args.net)
        chains = expiring_dict.ExpiringDict(300)
        def get_chain(chain_id_data):
            return chains.setdefault(chain_id_data, Chain(chain_id_data))
        
        peer_heads = expiring_dict.ExpiringDict(300) # hash -> peers that know of it
        
        # information affecting work that should trigger a long-polling update
        current_work = variable.Variable(None)
        # information affecting work that should not trigger a long-polling update
        current_work2 = variable.Variable(None)
        
        work_updated = variable.Event()
        tracker_updated = variable.Event()
        
        requested = expiring_dict.ExpiringDict(300)
        
        @defer.inlineCallbacks
        def set_real_work1():
            work, height = yield getwork(bitcoind)
            # XXX call tracker_updated
            current_work.set(dict(
                version=work.version,
                previous_block=work.previous_block,
                target=work.target,
                height=height,
                best_share_hash=current_work.value['best_share_hash'] if current_work.value is not None else None,
            ))
            current_work2.set(dict(
                clock_offset=time.time() - work.timestamp,
            ))
        
        @defer.inlineCallbacks
        def set_real_work2():
            best, desired = yield tracker.think(ht, current_work.value['previous_block'], time.time() - current_work2.value['clock_offset'])
            
            t = dict(current_work.value)
            t['best_share_hash'] = best
            current_work.set(t)
            
            for peer2, share_hash in desired:
                if share_hash not in tracker.tails: # was received in the time tracker.think was running
                    continue
                last_request_time, count = requested.get(share_hash, (None, 0))
                if last_request_time is not None and last_request_time - 5 < time.time() < last_request_time + 10 * 1.5**count:
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
                
                print 'Requesting parent share %s from %s' % (p2pool.format_hash(share_hash), '%s:%i' % peer.addr)
                peer.send_getshares(
                    hashes=[share_hash],
                    parents=2000,
                    stops=list(set(tracker.heads) | set(
                        tracker.get_nth_parent_hash(head, min(max(0, tracker.get_height_and_last(head)[0] - 1), 10)) for head in tracker.heads
                    ))[:100],
                )
                requested[share_hash] = time.time(), count + 1
        
        print 'Initializing work...'
        yield set_real_work1()
        yield set_real_work2()
        print '    ...success!'
        
        start_time = time.time() - current_work2.value['clock_offset']
        
        # setup p2p logic and join p2pool network
        
        def share_share(share, ignore_peer=None):
            for peer in p2p_node.peers.itervalues():
                if peer is ignore_peer:
                    continue
                peer.send_shares([share])
            share.flag_shared()
        
        def p2p_shares(shares, peer=None):
            if len(shares) > 5:
                print 'Processing %i shares...' % (len(shares),)
            
            some_new = False
            for share in shares:
                if share.hash in tracker.shares:
                    #print 'Got duplicate share, ignoring. Hash: %s' % (p2pool.format_hash(share.hash),)
                    continue
                some_new = True
                
                #print 'Received share %s from %r' % (p2pool.format_hash(share.hash), share.peer.addr if share.peer is not None else None)
                
                tracker.add(share)
                #for peer2, share_hash in desired:
                #    print 'Requesting parent share %x' % (share_hash,)
                #    peer2.send_getshares(hashes=[share_hash], parents=2000)
                
                if share.bitcoin_hash <= share.header['target']:
                    print
                    print 'GOT BLOCK! Passing to bitcoind! %s bitcoin: %x' % (p2pool.format_hash(share.hash), share.bitcoin_hash,)
                    print
                    if factory.conn.value is not None:
                        factory.conn.value.send_block(block=share.as_block(tracker, args.net))
                    else:
                        print 'No bitcoind connection! Erp!'
            
            if shares and peer is not None:
                peer_heads.setdefault(shares[0].hash, set()).add(peer)
            
            if some_new:
                tracker_updated.happened()
            
            if len(shares) > 5:
                print '... done processing %i shares. Have: %i/~%i' % (len(shares), len(tracker.shares), 2*args.net.CHAIN_LENGTH)
        
        def p2p_share_hashes(share_hashes, peer):
            get_hashes = []
            for share_hash in share_hashes:
                if share_hash in tracker.shares:
                    pass # print 'Got share hash, already have, ignoring. Hash: %s' % (p2pool.format_hash(share_hash),)
                else:
                    print 'Got share hash, requesting! Hash: %s' % (p2pool.format_hash(share_hash),)
                    get_hashes.append(share_hash)
            
            if share_hashes and peer is not None:
                peer_heads.setdefault(share_hashes[0], set()).add(peer)
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
            log.err(None, 'Error resolving bootstrap node IP:')
        
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
        
        def compute(state):
            if state['best_share_hash'] is None and args.net.PERSIST:
                raise jsonrpc.Error(-12345, u'p2pool is downloading shares')
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
            
            timestamp = int(time.time() - current_work2.value['clock_offset'])
            if state['best_share_hash'] is not None:
                timestamp2 = math.median((s.timestamp for s in itertools.islice(tracker.get_chain_to_root(state['best_share_hash']), 11)), use_float=False) + 1
                if timestamp2 > timestamp:
                    print 'Toff', timestamp2 - timestamp
                    timestamp = timestamp2
            target2 = p2pool.coinbase_type.unpack(generate_tx['tx_ins'][0]['script'])['share_data']['target']
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
                if hash_ <= block['header']['target'] or p2pool_init.DEBUG:
                    print
                    print 'GOT BLOCK! Passing to bitcoind! bitcoin: %x' % (hash_,)
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
                print 'GOT SHARE! %s prev %s age %.2fs' % (p2pool.format_hash(share.hash), p2pool.format_hash(share.previous_hash), time.time() - times[share.nonce]) + (' DEAD ON ARRIVAL' if share.previous_hash != current_work.value['best_share_hash'] else '')
                good = share.previous_hash == current_work.value['best_share_hash']
                # maybe revert back to tracker being non-blocking so 'good' can be more accurate?
                p2p_shares([share])
                # eg. good = share.hash == current_work.value['best_share_hash'] here
                return good
            except:
                log.err(None, 'Error processing data received from worker:')
                return False
        
        def get_rate():
            if current_work.value['best_share_hash'] is not None:
                height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
                att_s = p2pool.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], args.net, min(height, 720))
                return att_s
        
        def get_users():
            height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
            weights, total_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 720), 2**256)
            res = {}
            for script in sorted(weights, key=lambda s: weights[s]):
                res[script.encode('hex')] = weights[script]/total_weight
            return res

        
        reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response, get_rate, get_users, args.net)))
        
        print '    ...success!'
        print
        
        # done!
        
        tx_pool = expiring_dict.ExpiringDict(600, get_touches=False) # hash -> tx
        get_raw_transaction = deferral.DeferredCacher(lambda tx_hash: bitcoind.rpc_getrawtransaction('%x' % tx_hash), expiring_dict.ExpiringDict(100))
        
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
        
        @defer.inlineCallbacks
        def new_tx(tx_hash):
            try:
                assert isinstance(tx_hash, (int, long))
                #print 'REQUESTING', tx_hash
                tx = yield (yield factory.getProtocol()).get_tx(tx_hash)
                #print 'GOT', tx
                tx_pool[bitcoin.data.tx_type.hash256(tx)] = Tx(tx, current_work.value['previous_block'])
            except:
                log.err(None, 'Error handling tx:')
        # disable for now, for testing impact on stales
        #factory.new_tx.watch(new_tx)
        
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
                yield defer.DeferredList([flag, deferral.sleep(random.expovariate(1/1))], fireOnOneCallback=True)
        
        @defer.inlineCallbacks
        def work2_thread():
            while True:
                flag = tracker_updated.get_deferred()
                try:
                    yield set_real_work2()
                except:
                    log.err()
                yield defer.DeferredList([flag, deferral.sleep(random.expovariate(1/1))], fireOnOneCallback=True)
        
        work1_thread()
        work2_thread()
        
        counter = skiplist.CountsSkipList(tracker, run_identifier)
        
        while True:
            yield deferral.sleep(random.expovariate(1/1))
            try:
                if current_work.value['best_share_hash'] is not None:
                    height, last = tracker.get_height_and_last(current_work.value['best_share_hash'])
                    if height > 5:
                        att_s = p2pool.get_pool_attempts_per_second(tracker, current_work.value['best_share_hash'], args.net)
                        weights, total_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 120), 2**100)
                        count = counter(current_work.value['best_share_hash'], height, 2**100)
                        print 'Pool: %sH/s in %i shares Recent: %.02f%% >%sH/s Shares: %i (%i stale)' % (
                            math.format(att_s),
                            height,
                            weights.get(my_script, 0)/total_weight*100,
                            math.format(weights.get(my_script, 0)/total_weight*att_s),
                            len(my_shares),
                            len(my_shares) - count,
                        )
                        #weights, total_weight = tracker.get_cumulative_weights(current_work.value['best_share_hash'], min(height, 100), 2**100)
                        #for k, v in weights.iteritems():
                        #    print k.encode('hex'), v/total_weight
            except:
                log.err()
    except:
        log.err(None, 'Fatal error:')
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
        sys.stdout = sys.stderr = log.DefaultObserver.stderr = TimestampingPipe(TeePipe([sys.stderr, open(os.path.join(os.path.dirname(sys.argv[0]), 'debug.log'), 'w')]))
    
    if args.bitcoind_p2p_port is None:
        args.bitcoind_p2p_port = args.net.BITCOIN_P2P_PORT
    
    if args.p2pool_port is None:
        args.p2pool_port = args.net.P2P_PORT
    
    if args.address is not None:
        try:
            args.pubkey_hash = bitcoin.data.address_to_pubkey_hash(args.address, args.net)
        except Exception, e:
            raise ValueError('error parsing address: ' + repr(e))
    else:
        args.pubkey_hash = None
    
    reactor.callWhenRunning(main, args)
    reactor.run()
