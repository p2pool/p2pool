from __future__ import division

import itertools
import random
import time

from twisted.internet import defer
from twisted.python import log

import p2pool
from p2pool import skiplists
from p2pool.bitcoin import data as bitcoin_data, script
from p2pool.util import memoize, expiring_dict, math, deferral


merkle_branch_type = bitcoin_data.ListType(bitcoin_data.ComposedType([
    ('side', bitcoin_data.StructType('<B')), # enum?
    ('hash', bitcoin_data.HashType()),
]))


share_data_type = bitcoin_data.ComposedType([
    ('previous_share_hash', bitcoin_data.PossiblyNone(0, bitcoin_data.HashType())),
    ('target', bitcoin_data.FloatingIntegerType()),
    ('nonce', bitcoin_data.VarStrType()),
])


coinbase_type = bitcoin_data.ComposedType([
    ('identifier', bitcoin_data.FixedStrType(8)),
    ('share_data', share_data_type),
])

share_info_type = bitcoin_data.ComposedType([
    ('share_data', share_data_type),
    ('new_script', bitcoin_data.VarStrType()),
    ('subsidy', bitcoin_data.StructType('<Q')),
])


share1a_type = bitcoin_data.ComposedType([
    ('header', bitcoin_data.block_header_type),
    ('share_info', share_info_type),
    ('merkle_branch', merkle_branch_type),
])

share1b_type = bitcoin_data.ComposedType([
    ('header', bitcoin_data.block_header_type),
    ('share_info', share_info_type),
    ('other_txs', bitcoin_data.ListType(bitcoin_data.tx_type)),
])

def calculate_merkle_branch(txs, index):
    hash_list = [(bitcoin_data.tx_type.hash256(tx), i == index, []) for i, tx in enumerate(txs)]
    
    while len(hash_list) > 1:
        hash_list = [
            (
                bitcoin_data.merkle_record_type.hash256(dict(left=left, right=right)),
                left_f or right_f,
                (left_l if left_f else right_l) + [dict(side=1, hash=right) if left_f else dict(side=0, hash=left)],
            )
            for (left, left_f, left_l), (right, right_f, right_l) in
                zip(hash_list[::2], hash_list[1::2] + [hash_list[::2][-1]])
        ]
    
    assert hash_list[0][1]
    assert check_merkle_branch(txs[index], hash_list[0][2]) == hash_list[0][0]
    
    return hash_list[0][2]

def check_merkle_branch(tx, branch):
    hash_ = bitcoin_data.tx_type.hash256(tx)
    for step in branch:
        if not step['side']:
            hash_ = bitcoin_data.merkle_record_type.hash256(dict(left=step['hash'], right=hash_))
        else:
            hash_ = bitcoin_data.merkle_record_type.hash256(dict(left=hash_, right=step['hash']))
    return hash_

def gentx_to_share_info(gentx):
    return dict(
        share_data=coinbase_type.unpack(gentx['tx_ins'][0]['script'])['share_data'],
        subsidy=sum(tx_out['value'] for tx_out in gentx['tx_outs']),
        new_script=gentx['tx_outs'][-1]['script'],
    )

def share_info_to_gentx(share_info, block_target, tracker, net):
    return generate_transaction(
        tracker=tracker,
        previous_share_hash=share_info['share_data']['previous_share_hash'],
        new_script=share_info['new_script'],
        subsidy=share_info['subsidy'],
        nonce=share_info['share_data']['nonce'],
        block_target=block_target,
        net=net,
    )

class Share(object):
    @classmethod
    def from_block(cls, block):
        return cls(block['header'], gentx_to_share_info(block['txs'][0]), other_txs=block['txs'][1:])
    
    @classmethod
    def from_share1a(cls, share1a):
        return cls(**share1a)
    
    @classmethod
    def from_share1b(cls, share1b):
        return cls(**share1b)
    
    __slots__ = 'header previous_block share_info merkle_branch other_txs timestamp share_data new_script subsidy previous_hash previous_share_hash target nonce bitcoin_hash hash time_seen shared peer'.split(' ')
    
    def __init__(self, header, share_info, merkle_branch=None, other_txs=None):
        if merkle_branch is None and other_txs is None:
            raise ValueError('need either merkle_branch or other_txs')
        if other_txs is not None:
            new_merkle_branch = calculate_merkle_branch([dict(version=0, tx_ins=[], tx_outs=[], lock_time=0)] + other_txs, 0)
            if merkle_branch is not None:
                if merke_branch != new_merkle_branch:
                    raise ValueError('invalid merkle_branch and other_txs')
            merkle_branch = new_merkle_branch
        
        if len(merkle_branch) > 16:
            raise ValueError('merkle_branch too long!')
        
        self.header = header
        self.previous_block = header['previous_block']
        self.share_info = share_info
        self.merkle_branch = merkle_branch
        self.other_txs = other_txs
        
        self.timestamp = self.header['timestamp']
        
        self.share_data = self.share_info['share_data']
        self.new_script = self.share_info['new_script']
        self.subsidy = self.share_info['subsidy']
        
        if len(self.new_script) > 100:
            raise ValueError('new_script too long!')
        
        self.previous_hash = self.previous_share_hash = self.share_data['previous_share_hash']
        self.target = self.share_data['target']
        self.nonce = self.share_data['nonce']
        
        if len(self.nonce) > 100:
            raise ValueError('nonce too long!')
        
        self.bitcoin_hash = bitcoin_data.block_header_type.hash256(header)
        self.hash = share1a_type.hash256(self.as_share1a())
        
        if self.bitcoin_hash > self.target:
            print 'hash', hex(self.bitcoin_hash)
            print 'targ', hex(self.target)
            raise ValueError('not enough work!')
        
        if script.get_sigop_count(self.new_script) > 1:
            raise ValueError('too many sigops!')
        
        # XXX eww
        self.time_seen = time.time()
        self.shared = False
        self.peer = None
    
    def as_block(self, tracker, net):
        if self.other_txs is None:
            raise ValueError('share does not contain all txs')
        
        gentx = share_info_to_gentx(self.share_info, self.header['target'], tracker, net)
        
        return dict(header=self.header, txs=[gentx] + self.other_txs)
    
    def as_share1a(self):
        return dict(header=self.header, share_info=self.share_info, merkle_branch=self.merkle_branch)
    
    def as_share1b(self):
        return dict(header=self.header, share_info=self.share_info, other_txs=self.other_txs)
    
    def check(self, tracker, now, net):
        import time
        if self.previous_share_hash is not None:
            if self.header['timestamp'] <= math.median((s.timestamp for s in itertools.islice(tracker.get_chain_to_root(self.previous_share_hash), 11)), use_float=False):
                raise ValueError('share from too far in the past!')
        
        if self.header['timestamp'] > now + 2*60*60:
            raise ValueError('share from too far in the future!')
        
        gentx = share_info_to_gentx(self.share_info, self.header['target'], tracker, net)
        
        if len(gentx['tx_ins'][0]['script']) > 100:
            raise ValueError('''coinbase too large!''')
        
        if check_merkle_branch(gentx, self.merkle_branch) != self.header['merkle_root']:
            raise ValueError('''gentx doesn't match header via merkle_branch''')
        
        if self.other_txs is not None:
            if bitcoin_data.merkle_hash([gentx] + self.other_txs) != self.header['merkle_root']:
                raise ValueError('''gentx doesn't match header via other_txs''')
            
            if len(bitcoin_data.block_type.pack(dict(header=self.header, txs=[gentx] + self.other_txs))) > 1000000 - 1000:
                raise ValueError('''block size too large''')
    
    def flag_shared(self):
        self.shared = True
    
    def __repr__(self):
        return '<Share %s>' % (' '.join('%s=%r' % (k, v) for k, v in self.__dict__.iteritems()),)

def get_pool_attempts_per_second(tracker, previous_share_hash, net, dist=None):
    if dist is None:
        dist = net.TARGET_LOOKBEHIND
    near = tracker.shares[previous_share_hash]
    far = tracker.shares[tracker.get_nth_parent_hash(previous_share_hash, dist - 1)]
    attempts = tracker.get_work(near.hash) - tracker.get_work(far.hash)
    time = near.timestamp - far.timestamp
    if time == 0:
        time = 1
    return attempts//time

def generate_transaction(tracker, previous_share_hash, new_script, subsidy, nonce, block_target, net):
    height, last = tracker.get_height_and_last(previous_share_hash)
    if height < net.TARGET_LOOKBEHIND:
        target = bitcoin_data.FloatingIntegerType().truncate_to(2**256//2**20 - 1)
    else:
        attempts_per_second = get_pool_attempts_per_second(tracker, previous_share_hash, net)
        pre_target = 2**256//(net.SHARE_PERIOD*attempts_per_second) - 1
        previous_share = tracker.shares[previous_share_hash] if previous_share_hash is not None else None
        pre_target2 = math.clip(pre_target, (previous_share.target*9//10, previous_share.target*11//10))
        pre_target3 = math.clip(pre_target2, (0, net.MAX_TARGET))
        target = bitcoin_data.FloatingIntegerType().truncate_to(pre_target3)
    
    attempts_to_block = bitcoin_data.target_to_average_attempts(block_target)
    max_weight = net.SPREAD * attempts_to_block
    
    this_weight = min(bitcoin_data.target_to_average_attempts(target), max_weight)
    other_weights, other_weights_total = tracker.get_cumulative_weights(previous_share_hash, min(height, net.CHAIN_LENGTH), max(0, max_weight - this_weight))
    dest_weights, total_weight = math.add_dicts([{new_script: this_weight}, other_weights]), this_weight + other_weights_total
    assert total_weight == sum(dest_weights.itervalues())
    
    amounts = dict((script, subsidy*(396*weight)//(400*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[new_script] = amounts.get(new_script, 0) + subsidy*2//400
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy*2//400
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    if sum(amounts.itervalues()) != subsidy:
        raise ValueError()
    if any(x < 0 for x in amounts.itervalues()):
        raise ValueError()
    
    pre_dests = sorted(amounts.iterkeys(), key=lambda script: (amounts[script], script))
    pre_dests = pre_dests[-4000:] # block length limit, unlikely to ever be hit
    
    dests = sorted(pre_dests, key=lambda script: (script == new_script, script))
    assert dests[-1] == new_script
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=None,
            sequence=None,
            script=coinbase_type.pack(dict(
                identifier=net.IDENTIFIER,
                share_data=dict(
                    previous_share_hash=previous_share_hash,
                    nonce=nonce,
                    target=target,
                ),
            )),
        )],
        tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script]],
        lock_time=0,
    )



class OkayTracker(bitcoin_data.Tracker):
    def __init__(self, net):
        bitcoin_data.Tracker.__init__(self)
        self.net = net
        self.verified = bitcoin_data.Tracker()
        
        self.get_cumulative_weights = skiplists.WeightsSkipList(self)
    
    def attempt_verify(self, share, now):
        if share.hash in self.verified.shares:
            return True
        height, last = self.get_height_and_last(share.hash)
        if height < self.net.CHAIN_LENGTH and last is not None:
            raise AssertionError()
        try:
            share.check(self, now, self.net)
        except:
            log.err(None, 'Share check failed:')
            return False
        else:
            self.verified.add(share)
            return True
    
    def think(self, ht, previous_block, now):
        desired = set()
        
        # O(len(self.heads))
        #   make 'unverified heads' set?
        # for each overall head, attempt verification
        # if it fails, attempt on parent, and repeat
        # if no successful verification because of lack of parents, request parent
        bads = set()
        for head in set(self.heads) - set(self.verified.heads):
            head_height, last = self.get_height_and_last(head)
            
            for share in itertools.islice(self.get_chain_known(head), None if last is None else min(5, max(0, head_height - self.net.CHAIN_LENGTH))):
                if self.attempt_verify(share, now):
                    break
                if share.hash in self.heads:
                    bads.add(share.hash)
            else:
                if last is not None:
                    desired.add((self.shares[random.choice(list(self.reverse_shares[last]))].peer, last))
        for bad in bads:
            assert bad not in self.verified.shares
            assert bad in self.heads
            self.remove(bad)
        
        # try to get at least CHAIN_LENGTH height for each verified head, requesting parents if needed
        for head in list(self.verified.heads):
            head_height, last_hash = self.verified.get_height_and_last(head)
            last_height, last_last_hash = self.get_height_and_last(last_hash)
            # XXX review boundary conditions
            want = max(self.net.CHAIN_LENGTH - head_height, 0)
            can = max(last_height - 1 - self.net.CHAIN_LENGTH, 0) if last_last_hash is not None else last_height
            get = min(want, can)
            #print 'Z', head_height, last_hash is None, last_height, last_last_hash is None, want, can, get
            for share in itertools.islice(self.get_chain_known(last_hash), get):
                if not self.attempt_verify(share, now):
                    break
            if head_height < self.net.CHAIN_LENGTH and last_last_hash is not None:
                desired.add((self.verified.shares[random.choice(list(self.verified.reverse_shares[last_hash]))].peer, last_last_hash))
        
        # decide best tree
        best_tail = max(self.verified.tails, key=lambda h: self.score(max(self.verified.tails[h], key=self.verified.get_height), ht)) if self.verified.tails else None
        # decide best verified head
        scores = sorted(self.verified.tails.get(best_tail, []), key=lambda h: (
            self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))),
            ht.get_min_height(self.verified.shares[h].previous_block),
            self.verified.shares[h].peer is None,
            -self.verified.shares[h].time_seen
        ))
        
        
        if p2pool.DEBUG:
            print len(self.verified.tails.get(best_tail, []))
            for h in scores:
                print '   ', format_hash(h), format_hash(self.verified.shares[h].previous_hash), (
                    self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))),
                    ht.get_min_height(self.verified.shares[h].previous_block),
                    self.verified.shares[h].peer is None,
                    -self.verified.shares[h].time_seen
                )
        
        # eat away at heads
        while True:
            removed = False
            for share_hash in list(self.heads):
                if share_hash in scores[-5:]:
                    continue
                if self.shares[share_hash].time_seen > time.time() - 30:
                    continue
                self.remove(share_hash)
                if share_hash in self.verified.shares:
                    self.verified.remove(share_hash)
                removed = True
            if not removed:
                break
        
        # drop tails
        while True:
            removed = False
            # if removed from this, it must be removed from verified
            for tail, heads in list(self.tails.iteritems()):
                if min(self.get_height(head) for head in heads) < 2*self.net.CHAIN_LENGTH + 10:
                    continue
                start = time.time()
                for aftertail in list(self.reverse_shares.get(tail, set())):
                    self.remove(aftertail)
                    if tail in self.verified.shares:
                        self.verified.remove(aftertail)
                    removed = True
                end = time.time()
                print "removed! %x %f" % (tail, end - start)
            if not removed:
                break
        
        best = scores[-1] if scores else None
        
        if best is not None:
            best_share = self.verified.shares[best]
            if ht.get_min_height(best_share.header['previous_block']) < ht.get_min_height(previous_block) and best_share.bitcoin_hash != previous_block and best_share.peer is not None:
                if p2pool.DEBUG:
                    print 'Stale detected!'
                best = best_share.previous_hash
        
        return best, desired
    
    @memoize.memoize_with_backing(expiring_dict.ExpiringDict(5, get_touches=False))
    def score(self, share_hash, ht):
        head_height, last = self.verified.get_height_and_last(share_hash)
        score2 = 0
        attempts = 0
        max_height = 0
        share2_hash = self.verified.get_nth_parent_hash(share_hash, min(self.net.CHAIN_LENGTH//2, head_height//2)) if last is not None else share_hash
        for share in reversed(list(itertools.islice(self.verified.get_chain_known(share2_hash), self.net.CHAIN_LENGTH))):
            max_height = max(max_height, ht.get_min_height(share.header['previous_block']))
            attempts += bitcoin_data.target_to_average_attempts(share.target)
            this_score = attempts//(ht.get_highest_height() - max_height + 1)
            if this_score > score2:
                score2 = this_score
        return min(head_height, self.net.CHAIN_LENGTH), score2

def format_hash(x):
    if x is None:
        return 'xxxxxxxx'
    return '%08x' % (x % 2**32)

class Mainnet(bitcoin_data.Mainnet):
    SHARE_PERIOD = 5 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')
    IDENTIFIER = 'fc70035c7a81bc6f'.decode('hex')
    PREFIX = '2472ef181efcd37b'.decode('hex')
    ADDRS_TABLE = 'addrs'
    P2P_PORT = 9333
    MAX_TARGET = 2**256//2**32 - 1
    PERSIST = True

class Testnet(bitcoin_data.Testnet):
    SHARE_PERIOD = 1 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    SCRIPT = '410403ad3dee8ab3d8a9ce5dd2abfbe7364ccd9413df1d279bf1a207849310465b0956e5904b1155ecd17574778f9949589ebfd4fb33ce837c241474a225cf08d85dac'.decode('hex')
    IDENTIFIER = '5fc2be2d4f0d6bfb'.decode('hex')
    PREFIX = '3f6057a15036f441'.decode('hex')
    ADDRS_TABLE = 'addrs_testnet'
    P2P_PORT = 19333
    MAX_TARGET = 2**256//2**20 - 1
    PERSIST = False
