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
import traceback

from twisted.internet import defer, reactor
from twisted.web import server

import bitcoin.p2p, bitcoin.getwork, bitcoin.data
from util import db, expiring_dict, jsonrpc, variable, deferral
from . import p2p, worker_interface
import p2pool.data as p2pool

try:
    __version__ = subprocess.Popen(['svnversion', os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
except:
    __version__ = 'unknown'

class Chain(object):
    def __init__(self, chain_id_data):
        assert False
        self.chain_id_data = chain_id_data
        self.last_p2pool_block_hash = p2pool.chain_id_type.unpack(chain_id_data)['last_p2pool_block_hash']
        
        self.share2s = {} # hash -> share2
        self.highest = variable.Variable(None) # hash
        
        self.requesting = set()
        self.request_map = {}
    
    def accept(self, share, net):
        if share.chain_id_data != self.chain_id_data:
            raise ValueError('share does not belong to this chain')
        
        if share.hash in self.share2s:
            return 'dup'
        
        if share.previous_share_hash is None:
            previous_height, previous_share2 = -1, None
        elif share.previous_share_hash not in self.share2s:
            return 'orphan'
        else:
            previous_share2 = self.share2s[share.previous_share_hash]
            previous_height = previous_share2.height
        
        height = previous_height + 1
        
        share2 = share.check(self, height, previous_share2, net) # raises exceptions
        
        if share2.share is not share:
            raise ValueError()
        
        self.share2s[share.hash] = share2
        
        if self.highest.value is None or height > self.share2s[self.highest.value].height:
            self.highest.set(share.hash)
        
        return 'good'
    
    def get_highest_share2(self):
        return self.share2s[self.highest.value] if self.highest.value is not None else None
    
    def get_down(self, share_hash):
        blocks = []
        
        while True:
            blocks.append(share_hash)
            if share_hash not in self.share2s:
                break
            share2 = self.share2s[share_hash]
            if share2.share.previous_share_hash is None:
                break
            share_hash = share2.share.previous_share_hash
        
        return blocks

@defer.inlineCallbacks
def get_last_p2pool_block_hash(current_block_hash, get_block, net):
    block_hash = current_block_hash
    while True:
        if block_hash == net.ROOT_BLOCK:
            defer.returnValue(block_hash)
        try:
            block = yield get_block(block_hash)
        except:
            traceback.print_exc()
            continue
        coinbase_data = block['txs'][0]['tx_ins'][0]['script']
        try:
            coinbase = p2pool.coinbase_type.unpack(coinbase_data)
        except bitcoin.data.EarlyEnd:
            pass
        else:
            try:
                if coinbase['identifier'] == net.IDENTIFIER:
                    payouts = {}
                    for tx_out in block['txs'][0]['tx_outs']:
                        payouts[tx_out['script']] = payouts.get(tx_out['script'], 0) + tx_out['value']
                    subsidy = sum(payouts.itervalues())
                    if coinbase['subsidy'] == subsidy:
                        if payouts.get(net.SCRIPT, 0) >= subsidy//64:
                            defer.returnValue(block_hash)
            except Exception:
                print
                print 'Error matching block:'
                print 'block:', block
                traceback.print_exc()
                print
        block_hash = block['header']['previous_block']

@deferral.retry('Error getting work from bitcoind:', 1)
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


@defer.inlineCallbacks
def main(args):
    try:
        print 'p2pool (version %s)' % (__version__,)
        print
        
        # connect to bitcoind over JSON-RPC and do initial getwork
        url = 'http://%s:%i/' % (args.bitcoind_address, args.bitcoind_rpc_port)
        print "Testing bitcoind RPC connection to '%s' with authorization '%s:%s'..." % (url, args.bitcoind_rpc_username, args.bitcoind_rpc_password)
        bitcoind = jsonrpc.Proxy(url, (args.bitcoind_rpc_username, args.bitcoind_rpc_password))
        
        work, height = yield getwork(bitcoind)
        
        print '    ...success!'
        print '    Current block hash: %x height: %i' % (work.previous_block, height)
        print
        
        # connect to bitcoind over bitcoin-p2p and do checkorder to get pubkey to send payouts to
        print "Testing bitcoind P2P connection to '%s:%s'..." % (args.bitcoind_address, args.bitcoind_p2p_port)
        factory = bitcoin.p2p.ClientFactory(args.net)
        reactor.connectTCP(args.bitcoind_address, args.bitcoind_p2p_port, factory)
        
        while True:
            try:
                res = yield (yield factory.getProtocol()).check_order(order=bitcoin.p2p.Protocol.null_order)
                if res['reply'] != 'success':
                    print
                    print 'Error getting payout script:'
                    print res
                    print
                    continue
                my_script = res['script']
            except:
                print
                print 'Error getting payout script:'
                traceback.print_exc()
                print
            else:
                break
            yield deferral.sleep(1)
        
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
        
        tracker = p2pool.Tracker()
        chains = expiring_dict.ExpiringDict(300)
        def get_chain(chain_id_data):
            return chains.setdefault(chain_id_data, Chain(chain_id_data))
        
        # information affecting work that should trigger a long-polling update
        current_work = variable.Variable(None)
        # information affecting work that should not trigger a long-polling update
        current_work2 = variable.Variable(None)
        
        share_dbs = [db.SQLiteDict(sqlite3.connect(filename, isolation_level=None), 'shares') for filename in args.store_shares]
        
        @defer.inlineCallbacks
        def set_real_work():
            work, height = yield getwork(bitcoind)
            current_work.set(dict(
                version=work.version,
                previous_block=work.previous_block,
                target=work.target,
                
                height=height + 1,
                
                highest_p2pool_share_hash=tracker.get_best_share_hash(),
            ))
            current_work2.set(dict(
                timestamp=work.timestamp,
            ))
        
        print 'Initializing work...'
        yield set_real_work()
        print '    ...success!'
        
        # setup p2p logic and join p2pool network
        
        def share_share2(share2, ignore_peer=None):
            for peer in p2p_node.peers.itervalues():
                if peer is ignore_peer:
                    continue
                peer.send_share(share2.share)
            share2.flag_shared()
        
        def p2p_share(share, peer=None):
            if share.hash <= share.header['target']:
                print
                print 'GOT BLOCK! Passing to bitcoind! %x' % (share.hash,)
                #print share.__dict__
                print
                if factory.conn is not None:
                    factory.conn.send_block(block=share.as_block())
                else:
                    print 'No bitcoind connection! Erp!'
            
            res = tracker.add_share(share)
            if res == 'good':
                share2 = chain.share2s[share.hash]
                
                def save():
                    hash_data = bitcoin.p2p.HashType().pack(share.hash)
                    share1_data = p2pool.share1.pack(share.as_share1())
                    for share_db in share_dbs:
                        share_db[hash_data] = share1_data
                reactor.callLater(1, save)
                
                if chain is current_work.value['current_chain']:
                    if share.hash == chain.highest.value:
                        print 'Accepted share, passing to peers. Height: %i Hash: %x Script: %s' % (share2.height, share.hash, share2.shares[-1].encode('hex'))
                        share_share2(share2, peer)
                    else:
                        print 'Accepted share, not highest. Height: %i Hash: %x' % (share2.height, share.hash,)
                else:
                    print 'Accepted share to non-current chain. Height: %i Hash: %x' % (share2.height, share.hash,)
            elif res == 'dup':
                print 'Got duplicate share, ignoring. Hash: %x' % (share.hash,)
            elif res == 'orphan':
                print 'Got share referencing unknown share, requesting past shares from peer. Hash: %x' % (share.hash,)
                if peer is None:
                    raise ValueError()
                peer.send_gettobest(
                    chain_id=p2pool.chain_id_type.unpack(share.chain_id_data),
                    have=random.sample(chain.share2s.keys(), min(8, len(chain.share2s))) + [chain.share2s[chain.highest.value].share.hash] if chain.highest.value is not None else [],
                )
            else:
                raise ValueError('unknown result from chain.accept - %r' % (res,))
            
            w = dict(current_work.value)
            w['highest_p2pool_share_hash'] = w['current_chain'].get_highest_share_hash()
            current_work.set(w)
        
        def p2p_share_hash(chain_id_data, hash, peer):
            chain = get_chain(chain_id_data)
            if chain is current_work.value['current_chain']:
                if hash not in chain.share2s:
                    print "Got share hash, requesting! Hash: %x" % (hash,)
                    peer.send_getshares(chain_id=p2pool.chain_id_type.unpack(chain_id_data), hashes=[hash])
                else:
                    print "Got share hash, already have, ignoring. Hash: %x" % (hash,)
            else:
                print "Got share hash to non-current chain, storing. Hash: %x" % (hash,)
                chain.request_map.setdefault(hash, []).append(peer)
        
        def p2p_get_to_best(chain_id_data, have, peer):
            chain = get_chain(chain_id_data)
            if chain.highest.value is None:
                return
            
            chain_hashes = chain.get_down(chain.highest.value)
            
            have2 = set()
            for hash_ in have:
                have2 |= set(chain.get_down(hash_))
            
            for share_hash in reversed(chain_hashes):
                if share_hash in have2:
                    continue
                peer.send_share(chain.share2s[share_hash].share, full=True) # doesn't have to be full ... but does that still guarantee ordering?
        
        def p2p_get_shares(chain_id_data, hashes, peer):
            chain = get_chain(chain_id_data)
            for hash_ in hashes:
                if hash_ in chain.share2s:
                    peer.send_share(chain.share2s[hash_].share, full=True)
        
        print 'Joining p2pool network using TCP port %i...' % (args.p2pool_port,)
        
        def parse(x):
            if ':' in x:
                ip, port = x.split(':')
                return ip, int(port)
            else:
                return x, args.net.P2P_PORT
        
        nodes = [('72.14.191.28', args.net.P2P_PORT)]
        try:
            nodes.append(((yield reactor.resolve('p2pool.forre.st')), args.net.P2P_PORT))
        except:
            traceback.print_exc()
        
        p2p_node = p2p.Node(
            current_work=current_work,
            port=args.p2pool_port,
            net=args.net,
            addr_store=db.SQLiteDict(sqlite3.connect(os.path.join(os.path.dirname(sys.argv[0]), 'addrs.dat'), isolation_level=None), args.net.ADDRS_TABLE),
            mode=0 if args.low_bandwidth else 1,
            preferred_addrs=map(parse, args.p2pool_nodes) + nodes,
        )
        p2p_node.handle_share = p2p_share
        p2p_node.handle_share_hash = p2p_share_hash
        p2p_node.handle_get_to_best = p2p_get_to_best
        p2p_node.handle_get_shares = p2p_get_shares
        
        p2p_node.start()
        
        # send share when the chain changes to their chain
        def work_changed(new_work):
            #print 'Work changed:', new_work
            chain = new_work['current_chain']
            if chain.highest.value is not None:
                for share_hash in chain.get_down(chain.highest.value):
                    share2 = chain.share2s[share_hash]
                    if not share2.shared:
                        print 'Sharing share of switched to chain. Hash:', share2.share.hash
                        share_share2(share2)
            for hash, peers in chain.request_map.iteritems():
                if hash not in chain.share2s:
                    random.choice(peers).send_getshares(hashes=[hash])
        current_work.changed.watch(work_changed)
        
        print '    ...success!'
        print
        
        # start listening for workers with a JSON-RPC server
        
        print 'Listening for workers on port %i...' % (args.worker_port,)
        
        # setup worker logic
        
        merkle_root_to_transactions = expiring_dict.ExpiringDict(300)
        
        def compute(state):
            extra_txs = [tx for tx in tx_pool.itervalues() if tx.is_good()]
            generate_tx = p2pool.generate_transaction(
                tracker=tracker,
                previous_share_hash=state['highest_p2pool_share_hash'],
                new_script=my_script,
                subsidy=(50*100000000 >> state['height']//210000) + sum(tx.value_in - tx.value_out for tx in extra_txs),
                nonce=struct.pack("<Q", random.randrange(2**64)),
                block_target=state['target'],
                net=args.net,
            )
            print 'Generating!' #, have', shares.count(my_script) - 2, 'share(s) in the current chain. Fee:', sum(tx.value_in - tx.value_out for tx in extra_txs)/100000000
            transactions = [generate_tx] + [tx.tx for tx in extra_txs]
            merkle_root = bitcoin.data.merkle_hash(transactions)
            merkle_root_to_transactions[merkle_root] = transactions # will stay for 1000 seconds
            ba = bitcoin.getwork.BlockAttempt(state['version'], state['previous_block'], merkle_root, current_work2.value['timestamp'], state['target'])
            return ba.getwork(p2pool.coinbase_type.unpack(generate_tx['tx_ins'][0]['script'])['share_data']['target2'])
        
        def got_response(data):
            # match up with transactions
            header = bitcoin.getwork.decode_data(data)
            transactions = merkle_root_to_transactions.get(header['merkle_root'], None)
            if transactions is None:
                print "Couldn't link returned work's merkle root with its transactions - should only happen if you recently restarted p2pool"
                return False
            share = p2pool.Share.from_block(dict(header=header, txs=transactions))
            print 'GOT SHARE! %x' % (share.hash,)
            try:
                p2p_share(share)
            except:
                print
                print 'Error processing data received from worker:'
                traceback.print_exc()
                print
                return False
            else:
                return True
        
        reactor.listenTCP(args.worker_port, server.Site(worker_interface.WorkerInterface(current_work, compute, got_response)))
        
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
                #print "%x %r" % (seen_at_block, tx)
                #for mention in self.mentions:
                #    print "%x" % mention
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
                #print "is_good:", x
                return x
            
            def is_good2(self):
                for block_hash, block in itertools.islice(get_blocks(current_work.value['previous_block']), 10):
                    if block_hash == self.seen_at_block:
                        return True
                    for tx in block['txs']:
                        mentions = set([bitcoin.data.tx_type.hash256(tx)] + [tx_in['previous_output']['hash'] for tx_in in tx['tx_ins']])
                        if mentions & self.mentions:
                            return False
                return False
        
        @defer.inlineCallbacks
        def new_tx(tx_hash):
            assert isinstance(tx_hash, (int, long))
            tx = yield (yield factory.getProtocol()).get_tx(tx_hash)
            tx_pool[bitcoin.data.tx_type.hash256(tx)] = Tx(tx, current_work.value['previous_block'])
        factory.new_tx.watch(new_tx)
        
        def new_block(block):
            set_real_work()
        factory.new_block.watch(new_block)
        
        print 'Started successfully!'
        print
    except:
        print
        print 'Fatal error:'
        traceback.print_exc()
        print
        reactor.stop()

def run():
    parser = argparse.ArgumentParser(description='p2pool (version %s)' % (__version__,))
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--testnet',
        help='use the testnet; make sure you change the ports too',
        action='store_const', const=p2pool.Testnet, default=p2pool.Mainnet, dest='net')
    parser.add_argument('--store-shares', metavar='FILENAME',
        help='write shares to a database (not needed for normal usage)',
        type=str, action='append', default=[], dest='store_shares')
    
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
    
    if args.bitcoind_p2p_port is None:
        args.bitcoind_p2p_port = args.net.BITCOIN_P2P_PORT
    
    if args.p2pool_port is None:
        args.p2pool_port = args.net.P2P_PORT
    
    reactor.callWhenRunning(main, args)
    reactor.run()
