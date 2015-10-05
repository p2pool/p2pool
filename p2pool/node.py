import random
import sys
import time

from twisted.internet import defer, reactor
from twisted.python import log

from p2pool import data as p2pool_data, p2p
from p2pool.bitcoin import data as bitcoin_data, helper, height_tracker
from p2pool.util import deferral, variable


class P2PNode(p2p.Node):
    def __init__(self, node, **kwargs):
        self.node = node
        p2p.Node.__init__(self,
            best_share_hash_func=lambda: node.best_share_var.value,
            net=node.net,
            known_txs_var=node.known_txs_var,
            mining_txs_var=node.mining_txs_var,
        **kwargs)
    
    def handle_shares(self, shares, peer):
        if len(shares) > 5:
            print 'Processing %i shares from %s...' % (len(shares), '%s:%i' % peer.addr if peer is not None else None)
        
        new_count = 0
        all_new_txs = {}
        for share, new_txs in shares:
            if new_txs is not None:
                all_new_txs.update((bitcoin_data.hash256(bitcoin_data.tx_type.pack(new_tx)), new_tx) for new_tx in new_txs)
            
            if share.hash in self.node.tracker.items:
                #print 'Got duplicate share, ignoring. Hash: %s' % (p2pool_data.format_hash(share.hash),)
                continue
            
            new_count += 1
            
            #print 'Received share %s from %r' % (p2pool_data.format_hash(share.hash), share.peer_addr)
            
            self.node.tracker.add(share)
        
        self.node.known_txs_var.add(all_new_txs)
        
        if new_count:
            self.node.set_best_share()
        
        if len(shares) > 5:
            print '... done processing %i shares. New: %i Have: %i/~%i' % (len(shares), new_count, len(self.node.tracker.items), 2*self.node.net.CHAIN_LENGTH)
    
    @defer.inlineCallbacks
    def handle_share_hashes(self, hashes, peer):
        new_hashes = [x for x in hashes if x not in self.node.tracker.items]
        if not new_hashes:
            return
        try:
            shares = yield peer.get_shares(
                hashes=new_hashes,
                parents=0,
                stops=[],
            )
        except:
            log.err(None, 'in handle_share_hashes:')
        else:
            self.handle_shares([(share, []) for share in shares], peer)
    
    def handle_get_shares(self, hashes, parents, stops, peer):
        parents = min(parents, 1000//len(hashes))
        stops = set(stops)
        shares = []
        for share_hash in hashes:
            for share in self.node.tracker.get_chain(share_hash, min(parents + 1, self.node.tracker.get_height(share_hash))):
                if share.hash in stops:
                    break
                shares.append(share)
        if len(shares) > 0:
            print 'Sending %i shares to %s:%i' % (len(shares), peer.addr[0], peer.addr[1])
        return shares
    
    def handle_bestblock(self, header, peer):
        if self.node.net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(header)) > header['bits'].target:
            raise p2p.PeerMisbehavingError('received block header fails PoW test')
        self.node.handle_header(header)
    
    def broadcast_share(self, share_hash):
        shares = []
        for share in self.node.tracker.get_chain(share_hash, min(5, self.node.tracker.get_height(share_hash))):
            if share.hash in self.shared_share_hashes:
                break
            self.shared_share_hashes.add(share.hash)
            shares.append(share)
        
        for peer in self.peers.itervalues():
            peer.sendShares([share for share in shares if share.peer_addr != peer.addr], self.node.tracker, self.node.known_txs_var.value, include_txs_with=[share_hash])
    
    def start(self):
        p2p.Node.start(self)
        
        self.shared_share_hashes = set(self.node.tracker.items)
        self.node.tracker.removed.watch_weakref(self, lambda self, share: self.shared_share_hashes.discard(share.hash))
        
        @apply
        @defer.inlineCallbacks
        def download_shares():
            while True:
                desired = yield self.node.desired_var.get_when_satisfies(lambda val: len(val) != 0)
                peer_addr, share_hash = random.choice(desired)
                
                if len(self.peers) == 0:
                    yield deferral.sleep(1)
                    continue
                peer = random.choice(self.peers.values())
                
                print 'Requesting parent share %s from %s' % (p2pool_data.format_hash(share_hash), '%s:%i' % peer.addr)
                try:
                    shares = yield peer.get_shares(
                        hashes=[share_hash],
                        parents=random.randrange(500), # randomize parents so that we eventually get past a too large block of shares
                        stops=list(set(self.node.tracker.heads) | set(
                            self.node.tracker.get_nth_parent_hash(head, min(max(0, self.node.tracker.get_height_and_last(head)[0] - 1), 10)) for head in self.node.tracker.heads
                        ))[:100],
                    )
                except defer.TimeoutError:
                    print 'Share request timed out!'
                    continue
                except:
                    log.err(None, 'in download_shares:')
                    continue
                
                if not shares:
                    yield deferral.sleep(1) # sleep so we don't keep rerequesting the same share nobody has
                    continue
                self.handle_shares([(share, []) for share in shares], peer)
        
        
        @self.node.best_block_header.changed.watch
        def _(header):
            for peer in self.peers.itervalues():
                peer.send_bestblock(header=header)
        
        # send share when the chain changes to their chain
        self.node.best_share_var.changed.watch(self.broadcast_share)
        
        @self.node.tracker.verified.added.watch
        def _(share):
            if not (share.pow_hash <= share.header['bits'].target):
                return
            
            def spread():
                if (self.node.get_height_rel_highest(share.header['previous_block']) > -5 or
                    self.node.bitcoind_work.value['previous_block'] in [share.header['previous_block'], share.header_hash]):
                    self.broadcast_share(share.hash)
            spread()
            reactor.callLater(5, spread) # so get_height_rel_highest can update
        

class Node(object):
    def __init__(self, factory, bitcoind, shares, known_verified_share_hashes, net):
        self.factory = factory
        self.bitcoind = bitcoind
        self.net = net
        
        self.tracker = p2pool_data.OkayTracker(self.net)
        
        for share in shares:
            self.tracker.add(share)
        
        for share_hash in known_verified_share_hashes:
            if share_hash in self.tracker.items:
                self.tracker.verified.add(self.tracker.items[share_hash])
        
        self.p2p_node = None # overwritten externally
    
    @defer.inlineCallbacks
    def start(self):
        stop_signal = variable.Event()
        self.stop = stop_signal.happened
        
        # BITCOIND WORK
        
        self.bitcoind_work = variable.Variable((yield helper.getwork(self.bitcoind)))
        @defer.inlineCallbacks
        def work_poller():
            while stop_signal.times == 0:
                flag = self.factory.new_block.get_deferred()
                try:
                    self.bitcoind_work.set((yield helper.getwork(self.bitcoind, self.bitcoind_work.value['use_getblocktemplate'])))
                except:
                    log.err()
                yield defer.DeferredList([flag, deferral.sleep(15)], fireOnOneCallback=True)
        work_poller()
        
        # PEER WORK
        
        self.best_block_header = variable.Variable(None)
        def handle_header(new_header):
            # check that header matches current target
            if not (self.net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(new_header)) <= self.bitcoind_work.value['bits'].target):
                return
            bitcoind_best_block = self.bitcoind_work.value['previous_block']
            if (self.best_block_header.value is None
                or (
                    new_header['previous_block'] == bitcoind_best_block and
                    bitcoin_data.hash256(bitcoin_data.block_header_type.pack(self.best_block_header.value)) == bitcoind_best_block
                ) # new is child of current and previous is current
                or (
                    bitcoin_data.hash256(bitcoin_data.block_header_type.pack(new_header)) == bitcoind_best_block and
                    self.best_block_header.value['previous_block'] != bitcoind_best_block
                )): # new is current and previous is not a child of current
                self.best_block_header.set(new_header)
        self.handle_header = handle_header
        @defer.inlineCallbacks
        def poll_header():
            if self.factory.conn.value is None:
                return
            handle_header((yield self.factory.conn.value.get_block_header(self.bitcoind_work.value['previous_block'])))
        self.bitcoind_work.changed.watch(lambda _: poll_header())
        yield deferral.retry('Error while requesting best block header:')(poll_header)()
        
        # BEST SHARE
        
        self.known_txs_var = variable.VariableDict({}) # hash -> tx
        self.mining_txs_var = variable.Variable({}) # hash -> tx
        self.get_height_rel_highest = yield height_tracker.get_height_rel_highest_func(self.bitcoind, self.factory, lambda: self.bitcoind_work.value['previous_block'], self.net)
        
        self.best_share_var = variable.Variable(None)
        self.desired_var = variable.Variable(None)
        self.bitcoind_work.changed.watch(lambda _: self.set_best_share())
        self.set_best_share()
        
        # setup p2p logic and join p2pool network
        
        # update mining_txs according to getwork results
        @self.bitcoind_work.changed.run_and_watch
        def _(_=None):
            new_mining_txs = {}
            added_known_txs = {}
            for tx_hash, tx in zip(self.bitcoind_work.value['transaction_hashes'], self.bitcoind_work.value['transactions']):
                new_mining_txs[tx_hash] = tx
                added_known_txs[tx_hash] = tx
            self.mining_txs_var.set(new_mining_txs)
            self.known_txs_var.add(added_known_txs)
        # add p2p transactions from bitcoind to known_txs
        @self.factory.new_tx.watch
        def _(tx):
            self.known_txs_var.add({
                bitcoin_data.hash256(bitcoin_data.tx_type.pack(tx)): tx,
            })
        # forward transactions seen to bitcoind
        @self.known_txs_var.transitioned.watch
        @defer.inlineCallbacks
        def _(before, after):
            yield deferral.sleep(random.expovariate(1/1))
            if self.factory.conn.value is None:
                return
            for tx_hash in set(after) - set(before):
                self.factory.conn.value.send_tx(tx=after[tx_hash])
        
        @self.tracker.verified.added.watch
        def _(share):
            if not (share.pow_hash <= share.header['bits'].target):
                return
            
            block = share.as_block(self.tracker, self.known_txs_var.value)
            if block is None:
                print >>sys.stderr, 'GOT INCOMPLETE BLOCK FROM PEER! %s bitcoin: %s%064x' % (p2pool_data.format_hash(share.hash), self.net.PARENT.BLOCK_EXPLORER_URL_PREFIX, share.header_hash)
                return
            helper.submit_block(block, True, self.factory, self.bitcoind, self.bitcoind_work, self.net)
            print
            print 'GOT BLOCK FROM PEER! Passing to bitcoind! %s bitcoin: %s%064x' % (p2pool_data.format_hash(share.hash), self.net.PARENT.BLOCK_EXPLORER_URL_PREFIX, share.header_hash)
            print
        
        def forget_old_txs():
            new_known_txs = {}
            if self.p2p_node is not None:
                for peer in self.p2p_node.peers.itervalues():
                    new_known_txs.update(peer.remembered_txs)
            new_known_txs.update(self.mining_txs_var.value)
            for share in self.tracker.get_chain(self.best_share_var.value, min(120, self.tracker.get_height(self.best_share_var.value))):
                for tx_hash in share.new_transaction_hashes:
                    if tx_hash in self.known_txs_var.value:
                        new_known_txs[tx_hash] = self.known_txs_var.value[tx_hash]
            self.known_txs_var.set(new_known_txs)
        t = deferral.RobustLoopingCall(forget_old_txs)
        t.start(10)
        stop_signal.watch(t.stop)
        
        t = deferral.RobustLoopingCall(self.clean_tracker)
        t.start(5)
        stop_signal.watch(t.stop)
    
    def set_best_share(self):
        best, desired, decorated_heads, bad_peer_addresses = self.tracker.think(self.get_height_rel_highest, self.bitcoind_work.value['previous_block'], self.bitcoind_work.value['bits'], self.known_txs_var.value)
        
        self.best_share_var.set(best)
        self.desired_var.set(desired)
        if self.p2p_node is not None:
            for bad_peer_address in bad_peer_addresses:
                # XXX O(n)
                for peer in self.p2p_node.peers.itervalues():
                    if peer.addr == bad_peer_address:
                        peer.badPeerHappened()
                        break
    
    def get_current_txouts(self):
        return p2pool_data.get_expected_payouts(self.tracker, self.best_share_var.value, self.bitcoind_work.value['bits'].target, self.bitcoind_work.value['subsidy'], self.net)
    
    def clean_tracker(self):
        best, desired, decorated_heads, bad_peer_addresses = self.tracker.think(self.get_height_rel_highest, self.bitcoind_work.value['previous_block'], self.bitcoind_work.value['bits'], self.known_txs_var.value)
        
        # eat away at heads
        if decorated_heads:
            for i in xrange(1000):
                to_remove = set()
                for share_hash, tail in self.tracker.heads.iteritems():
                    if share_hash in [head_hash for score, head_hash in decorated_heads[-5:]]:
                        #print 1
                        continue
                    if self.tracker.items[share_hash].time_seen > time.time() - 300:
                        #print 2
                        continue
                    if share_hash not in self.tracker.verified.items and max(self.tracker.items[after_tail_hash].time_seen for after_tail_hash in self.tracker.reverse.get(tail)) > time.time() - 120: # XXX stupid
                        #print 3
                        continue
                    to_remove.add(share_hash)
                if not to_remove:
                    break
                for share_hash in to_remove:
                    if share_hash in self.tracker.verified.items:
                        self.tracker.verified.remove(share_hash)
                    self.tracker.remove(share_hash)
                #print "_________", to_remove
        
        # drop tails
        for i in xrange(1000):
            to_remove = set()
            for tail, heads in self.tracker.tails.iteritems():
                if min(self.tracker.get_height(head) for head in heads) < 2*self.tracker.net.CHAIN_LENGTH + 10:
                    continue
                to_remove.update(self.tracker.reverse.get(tail, set()))
            if not to_remove:
                break
            # if removed from this, it must be removed from verified
            #start = time.time()
            for aftertail in to_remove:
                if self.tracker.items[aftertail].previous_hash not in self.tracker.tails:
                    print "erk", aftertail, self.tracker.items[aftertail].previous_hash
                    continue
                if aftertail in self.tracker.verified.items:
                    self.tracker.verified.remove(aftertail)
                self.tracker.remove(aftertail)
            #end = time.time()
            #print "removed! %i %f" % (len(to_remove), (end - start)/len(to_remove))
        
        self.set_best_share()
