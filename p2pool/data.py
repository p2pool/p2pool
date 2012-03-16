from __future__ import division

import hashlib
import os
import random
import time

from twisted.python import log

import p2pool
from p2pool.bitcoin import data as bitcoin_data, script, sha256
from p2pool.util import math, forest, pack

# hashlink

hash_link_type = pack.ComposedType([
    ('state', pack.FixedStrType(32)),
    ('extra_data', pack.FixedStrType(0)), # bit of a hack, but since the donation script is at the end, const_ending is long enough to always make this empty
    ('length', pack.VarIntType()),
])

def prefix_to_hash_link(prefix, const_ending=''):
    assert prefix.endswith(const_ending), (prefix, const_ending)
    x = sha256.sha256(prefix)
    return dict(state=x.state, extra_data=x.buf[:max(0, len(x.buf)-len(const_ending))], length=x.length//8)

def check_hash_link(hash_link, data, const_ending=''):
    extra_length = hash_link['length'] % (512//8)
    assert len(hash_link['extra_data']) == max(0, extra_length - len(const_ending))
    extra = (hash_link['extra_data'] + const_ending)[len(hash_link['extra_data']) + len(const_ending) - extra_length:]
    assert len(extra) == extra_length
    return pack.IntType(256).unpack(hashlib.sha256(sha256.sha256(data, (hash_link['state'], extra, 8*hash_link['length'])).digest()).digest())

# shares

small_block_header_type = pack.ComposedType([
    ('version', pack.VarIntType()), # XXX must be constrained to 32 bits
    ('previous_block', pack.PossiblyNoneType(0, pack.IntType(256))),
    ('timestamp', pack.IntType(32)),
    ('bits', bitcoin_data.FloatingIntegerType()),
    ('nonce', pack.IntType(32)),
])

share_data_type = pack.ComposedType([
    ('previous_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
    ('coinbase', pack.VarStrType()),
    ('nonce', pack.IntType(32)),
    ('pubkey_hash', pack.IntType(160)),
    ('subsidy', pack.IntType(64)),
    ('donation', pack.IntType(16)),
    ('stale_info', pack.IntType(8)), # 0 nothing, 253 orphan, 254 doa
])

share_info_type = pack.ComposedType([
    ('share_data', share_data_type),
    ('max_bits', bitcoin_data.FloatingIntegerType()),
    ('bits', bitcoin_data.FloatingIntegerType()),
    ('timestamp', pack.IntType(32)),
])

share1a_type = pack.ComposedType([
    ('min_header', small_block_header_type),
    ('share_info', share_info_type),
    ('hash_link', hash_link_type),
    ('merkle_branch', bitcoin_data.merkle_branch_type),
])

share1b_type = pack.ComposedType([
    ('min_header', small_block_header_type),
    ('share_info', share_info_type),
    ('hash_link', hash_link_type),
    ('other_txs', pack.ListType(bitcoin_data.tx_type)),
])


# type:
# 2: share1a
# 3: share1b

share_type = pack.ComposedType([
    ('type', pack.VarIntType()),
    ('contents', pack.VarStrType()),
])


def get_pool_attempts_per_second(tracker, previous_share_hash, dist, min_work=False, integer=False):
    assert dist >= 2
    near = tracker.shares[previous_share_hash]
    far = tracker.shares[tracker.get_nth_parent_hash(previous_share_hash, dist - 1)]
    attempts = tracker.get_work(near.hash) - tracker.get_work(far.hash) if not min_work else tracker.get_delta(near.hash).min_work - tracker.get_delta(far.hash).min_work
    time = near.timestamp - far.timestamp
    if time <= 0:
        time = 1
    if integer:
        return attempts//time
    return attempts/time

def get_average_stale_prop(tracker, share_hash, lookbehind):
    stales = sum(1 for share in tracker.get_chain(share_hash, lookbehind) if share.share_data['stale_info'] in [253, 254])
    return stales/(lookbehind + stales)

DONATION_SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')

ref_type = pack.ComposedType([
    ('identifier', pack.FixedStrType(64//8)),
    ('share_info', share_info_type),
])

gentx_before_refhash = pack.VarStrType().pack(DONATION_SCRIPT) + pack.IntType(64).pack(0) + pack.VarStrType().pack('\x20' + pack.IntType(256).pack(0))[:2]

def generate_transaction(tracker, share_data, block_target, desired_timestamp, desired_target, net):
    previous_share = tracker.shares[share_data['previous_share_hash']] if share_data['previous_share_hash'] is not None else None
    
    height, last = tracker.get_height_and_last(share_data['previous_share_hash'])
    assert height >= net.REAL_CHAIN_LENGTH or last is None
    if height < net.TARGET_LOOKBEHIND:
        pre_target3 = net.MAX_TARGET
    else:
        attempts_per_second = get_pool_attempts_per_second(tracker, share_data['previous_share_hash'], net.TARGET_LOOKBEHIND, min_work=True, integer=True)
        pre_target = 2**256//(net.SHARE_PERIOD*attempts_per_second) - 1 if attempts_per_second else 2**256-1
        pre_target2 = math.clip(pre_target, (previous_share.max_target*9//10, previous_share.max_target*11//10))
        pre_target3 = math.clip(pre_target2, (0, net.MAX_TARGET))
    max_bits = bitcoin_data.FloatingInteger.from_target_upper_bound(pre_target3)
    bits = bitcoin_data.FloatingInteger.from_target_upper_bound(math.clip(desired_target, (pre_target3//10, pre_target3)))
    
    weights, total_weight, donation_weight = tracker.get_cumulative_weights(share_data['previous_share_hash'],
        min(height, net.REAL_CHAIN_LENGTH),
        65535*net.SPREAD*bitcoin_data.target_to_average_attempts(block_target),
    )
    assert total_weight == sum(weights.itervalues()) + donation_weight, (total_weight, sum(weights.itervalues()) + donation_weight)
    
    amounts = dict((script, share_data['subsidy']*(199*weight)//(200*total_weight)) for script, weight in weights.iteritems()) # 99.5% goes according to weights prior to this share
    this_script = bitcoin_data.pubkey_hash_to_script2(share_data['pubkey_hash'])
    amounts[this_script] = amounts.get(this_script, 0) + share_data['subsidy']//200 # 0.5% goes to block finder
    amounts[DONATION_SCRIPT] = amounts.get(DONATION_SCRIPT, 0) + share_data['subsidy'] - sum(amounts.itervalues()) # all that's left over is the donation weight and some extra satoshis due to rounding
    
    if sum(amounts.itervalues()) != share_data['subsidy'] or any(x < 0 for x in amounts.itervalues()):
        raise ValueError()
    
    dests = sorted(amounts.iterkeys(), key=lambda script: (script == DONATION_SCRIPT, amounts[script], script))[-4000:] # block length limit, unlikely to ever be hit
    
    share_info = dict(
        share_data=share_data,
        max_bits=max_bits,
        bits=bits,
        timestamp=math.clip(desired_timestamp, (
            (previous_share.timestamp + net.SHARE_PERIOD) - (net.SHARE_PERIOD - 1), # = previous_share.timestamp + 1
            (previous_share.timestamp + net.SHARE_PERIOD) + (net.SHARE_PERIOD - 1),
        )) if previous_share is not None else desired_timestamp,
    )
    
    return share_info, dict(
        version=1,
        tx_ins=[dict(
            previous_output=None,
            sequence=None,
            script=share_data['coinbase'].ljust(2, '\x00'),
        )],
        tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script]] + [dict(
            value=0,
            script='\x20' + pack.IntType(256).pack(bitcoin_data.hash256(ref_type.pack(dict(
                identifier=net.IDENTIFIER,
                share_info=share_info,
            )))),
        )],
        lock_time=0,
    )

def get_expected_payouts(tracker, best_share_hash, block_target, subsidy, net):
    weights, total_weight, donation_weight = tracker.get_cumulative_weights(best_share_hash, min(tracker.get_height(best_share_hash), net.REAL_CHAIN_LENGTH), 65535*net.SPREAD*bitcoin_data.target_to_average_attempts(block_target))
    res = dict((script, subsidy*weight//total_weight) for script, weight in weights.iteritems())
    res[DONATION_SCRIPT] = res.get(DONATION_SCRIPT, 0) + subsidy - sum(res.itervalues())
    return res

class Share(object):
    __slots__ = 'net min_header share_info hash_link merkle_branch other_txs hash share_data max_target target timestamp previous_hash new_script gentx_hash header pow_hash header_hash time_seen peer'.split(' ')
    
    @classmethod
    def from_share(cls, share, net, peer):
        if share['type'] in [0, 1]:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('sent an obsolete share')
        elif share['type'] == 2:
            return cls(net, peer, other_txs=None, **share1a_type.unpack(share['contents']))
        elif share['type'] == 3:
            share1b = share1b_type.unpack(share['contents'])
            return cls(net, peer, merkle_branch=bitcoin_data.calculate_merkle_branch([0] + [bitcoin_data.hash256(bitcoin_data.tx_type.pack(x)) for x in share1b['other_txs']], 0), **share1b)
        else:
            raise ValueError('unknown share type: %r' % (share['type'],))
    
    def __init__(self, net, peer, min_header, share_info, hash_link, merkle_branch, other_txs):
        if len(share_info['share_data']['coinbase']) > 100:
            raise ValueError('''coinbase too large! %i bytes''' % (len(self.share_data['coinbase']),))
        
        if len(merkle_branch) > 16:
            raise ValueError('merkle_branch too long!')
        
        if p2pool.DEBUG and other_txs is not None and bitcoin_data.calculate_merkle_branch([0] + [bitcoin_data.hash256(bitcoin_data.tx_type.pack(x)) for x in other_txs], 0) != merkle_branch:
            raise ValueError('merkle_branch and other_txs do not match')
        
        assert not hash_link['extra_data'], repr(hash_link['extra_data'])
        
        self.net = net
        self.peer = peer
        self.min_header = min_header
        self.share_info = share_info
        self.hash_link = hash_link
        self.merkle_branch = merkle_branch
        self.other_txs = other_txs
        
        self.share_data = self.share_info['share_data']
        self.max_target = self.share_info['max_bits'].target
        self.target = self.share_info['bits'].target
        self.timestamp = self.share_info['timestamp']
        self.previous_hash = self.share_data['previous_share_hash']
        self.new_script = bitcoin_data.pubkey_hash_to_script2(self.share_data['pubkey_hash'])
        
        self.gentx_hash = check_hash_link(
            hash_link,
            pack.IntType(256).pack(bitcoin_data.hash256(ref_type.pack(dict(
                identifier=net.IDENTIFIER,
                share_info=share_info,
            )))) + pack.IntType(32).pack(0),
            gentx_before_refhash,
        )
        merkle_root = bitcoin_data.check_merkle_branch(self.gentx_hash, 0, merkle_branch)
        self.header = dict(min_header, merkle_root=merkle_root)
        self.pow_hash = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(self.header))
        self.header_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(self.header))
        
        if self.pow_hash > self.target:
            raise p2p.PeerMisbehavingError('share PoW invalid')
        
        if other_txs is not None and not self.pow_hash <= self.header['bits'].target:
            raise ValueError('other_txs provided when not a block solution')
        if other_txs is None and self.pow_hash <= self.header['bits'].target:
            raise ValueError('other_txs not provided when a block solution')
        
        self.hash = bitcoin_data.hash256(share_type.pack(self.as_share()))
        
        # XXX eww
        self.time_seen = time.time()
    
    def __repr__(self):
        return '<Share %s>' % (' '.join('%s=%r' % (k, getattr(self, k)) for k in self.__slots__),)
    
    def check(self, tracker):
        share_info, gentx = generate_transaction(tracker, self.share_info['share_data'], self.header['bits'].target, self.share_info['timestamp'], self.share_info['bits'].target, self.net)
        if share_info != self.share_info:
            raise ValueError('share difficulty invalid')
        if bitcoin_data.hash256(bitcoin_data.tx_type.pack(gentx)) != self.gentx_hash:
            raise ValueError('''gentx doesn't match hash_link''')
    
    def as_share(self):
        if not self.pow_hash <= self.header['bits'].target: # share1a
            return dict(type=2, contents=share1a_type.pack(dict(min_header=self.min_header, share_info=self.share_info, hash_link=self.hash_link, merkle_branch=self.merkle_branch)))
        else: # share1b
            return dict(type=3, contents=share1b_type.pack(dict(min_header=self.min_header, share_info=self.share_info, hash_link=self.hash_link, other_txs=self.other_txs)))
    
    def as_block(self, tracker):
        if self.other_txs is None:
            raise ValueError('share does not contain all txs')
        
        share_info, gentx = generate_transaction(tracker, self.share_info['share_data'], self.header['bits'].target, self.share_info['timestamp'], self.share_info['bits'].target, self.net)
        assert share_info == self.share_info
        
        return dict(header=self.header, txs=[gentx] + self.other_txs)

class WeightsSkipList(forest.TrackerSkipList):
    # share_count, weights, total_weight
    
    def get_delta(self, element):
        from p2pool.bitcoin import data as bitcoin_data
        share = self.tracker.shares[element]
        att = bitcoin_data.target_to_average_attempts(share.target)
        return 1, {share.new_script: att*(65535-share.share_data['donation'])}, att*65535, att*share.share_data['donation']
    
    def combine_deltas(self, (share_count1, weights1, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2)):
        return share_count1 + share_count2, math.add_dicts(weights1, weights2), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def initial_solution(self, start, (max_shares, desired_weight)):
        assert desired_weight % 65535 == 0, divmod(desired_weight, 65535)
        return 0, None, 0, 0
    
    def apply_delta(self, (share_count1, weights_list, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2), (max_shares, desired_weight)):
        if total_weight1 + total_weight2 > desired_weight and share_count2 == 1:
            assert (desired_weight - total_weight1) % 65535 == 0
            script, = weights2.iterkeys()
            new_weights = dict(script=(desired_weight - total_weight1)//65535*weights2[script]//(total_weight2//65535))
            return share_count1 + share_count2, (weights_list, new_weights), desired_weight, total_donation_weight1 + (desired_weight - total_weight1)//65535*total_donation_weight2//(total_weight2//65535)
        return share_count1 + share_count2, (weights_list, weights2), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def judge(self, (share_count, weights_list, total_weight, total_donation_weight), (max_shares, desired_weight)):
        if share_count > max_shares or total_weight > desired_weight:
            return 1
        elif share_count == max_shares or total_weight == desired_weight:
            return 0
        else:
            return -1
    
    def finalize(self, (share_count, weights_list, total_weight, total_donation_weight), (max_shares, desired_weight)):
        assert share_count <= max_shares and total_weight <= desired_weight
        assert share_count == max_shares or total_weight == desired_weight
        return math.add_dicts(*math.flatten_linked_list(weights_list)), total_weight, total_donation_weight

class OkayTracker(forest.Tracker):
    def __init__(self, net, my_share_hashes, my_doa_share_hashes):
        forest.Tracker.__init__(self, delta_type=forest.get_attributedelta_type(dict(forest.AttributeDelta.attrs,
            work=lambda share: bitcoin_data.target_to_average_attempts(share.target),
            min_work=lambda share: bitcoin_data.target_to_average_attempts(share.max_target),
        )))
        self.net = net
        self.verified = forest.Tracker(delta_type=forest.get_attributedelta_type(dict(forest.AttributeDelta.attrs,
            work=lambda share: bitcoin_data.target_to_average_attempts(share.target),
            my_count=lambda share: 1 if share.hash in my_share_hashes else 0,
            my_doa_count=lambda share: 1 if share.hash in my_doa_share_hashes else 0,
            my_orphan_announce_count=lambda share: 1 if share.hash in my_share_hashes and share.share_data['stale_info'] == 253 else 0,
            my_dead_announce_count=lambda share: 1 if share.hash in my_share_hashes and share.share_data['stale_info'] == 254 else 0,
        )))
        self.verified.get_nth_parent_hash = self.get_nth_parent_hash # self is a superset of self.verified
        
        self.get_cumulative_weights = WeightsSkipList(self)
    
    def attempt_verify(self, share):
        if share.hash in self.verified.shares:
            return True
        height, last = self.get_height_and_last(share.hash)
        if height < self.net.CHAIN_LENGTH + 1 and last is not None:
            raise AssertionError()
        try:
            share.check(self)
        except:
            log.err(None, 'Share check failed:')
            return False
        else:
            self.verified.add(share)
            return True
    
    def think(self, block_rel_height_func, previous_block, bits):
        desired = set()
        
        # O(len(self.heads))
        #   make 'unverified heads' set?
        # for each overall head, attempt verification
        # if it fails, attempt on parent, and repeat
        # if no successful verification because of lack of parents, request parent
        bads = set()
        for head in set(self.heads) - set(self.verified.heads):
            head_height, last = self.get_height_and_last(head)
            
            for share in self.get_chain(head, head_height if last is None else min(5, max(0, head_height - self.net.CHAIN_LENGTH))):
                if self.attempt_verify(share):
                    break
                if share.hash in self.heads:
                    bads.add(share.hash)
            else:
                if last is not None:
                    desired.add((
                        self.shares[random.choice(list(self.reverse_shares[last]))].peer,
                        last,
                        max(x.timestamp for x in self.get_chain(head, min(head_height, 5))),
                        min(x.target for x in self.get_chain(head, min(head_height, 5))),
                    ))
        for bad in bads:
            assert bad not in self.verified.shares
            assert bad in self.heads
            if p2pool.DEBUG:
                print "BAD", bad
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
            for share in self.get_chain(last_hash, get):
                if not self.attempt_verify(share):
                    break
            if head_height < self.net.CHAIN_LENGTH and last_last_hash is not None:
                desired.add((
                    self.shares[random.choice(list(self.verified.reverse_shares[last_hash]))].peer,
                    last_last_hash,
                    max(x.timestamp for x in self.get_chain(head, min(head_height, 5))),
                    min(x.target for x in self.get_chain(head, min(head_height, 5))),
                ))
        
        # decide best tree
        decorated_tails = sorted((self.score(max(self.verified.tails[tail_hash], key=self.verified.get_work), block_rel_height_func), tail_hash) for tail_hash in self.verified.tails)
        if p2pool.DEBUG:
            print len(decorated_tails), 'tails:'
            for score, tail_hash in decorated_tails:
                print format_hash(tail_hash), score
        best_tail_score, best_tail = decorated_tails[-1] if decorated_tails else (None, None)
        
        # decide best verified head
        decorated_heads = sorted(((
            self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))),
            #self.shares[h].peer is None,
            self.shares[h].pow_hash <= self.shares[h].header['bits'].target, # is block solution
            (self.shares[h].header['previous_block'], self.shares[h].header['bits']) == (previous_block, bits) or self.shares[h].peer is None,
            -self.shares[h].time_seen,
        ), h) for h in self.verified.tails.get(best_tail, []))
        if p2pool.DEBUG:
            print len(decorated_heads), 'heads. Top 10:'
            for score, head_hash in decorated_heads[-10:]:
                print '   ', format_hash(head_hash), format_hash(self.shares[head_hash].previous_hash), score
        best_head_score, best = decorated_heads[-1] if decorated_heads else (None, None)
        
        # eat away at heads
        if decorated_heads:
            for i in xrange(1000):
                to_remove = set()
                for share_hash, tail in self.heads.iteritems():
                    if share_hash in [head_hash for score, head_hash in decorated_heads[-5:]]:
                        #print 1
                        continue
                    if self.shares[share_hash].time_seen > time.time() - 300:
                        #print 2
                        continue
                    if share_hash not in self.verified.shares and max(self.shares[after_tail_hash].time_seen for after_tail_hash in self.reverse_shares.get(tail)) > time.time() - 120: # XXX stupid
                        #print 3
                        continue
                    to_remove.add(share_hash)
                if not to_remove:
                    break
                for share_hash in to_remove:
                    self.remove(share_hash)
                    if share_hash in self.verified.shares:
                        self.verified.remove(share_hash)
                #print "_________", to_remove
        
        # drop tails
        for i in xrange(1000):
            to_remove = set()
            for tail, heads in self.tails.iteritems():
                if min(self.get_height(head) for head in heads) < 2*self.net.CHAIN_LENGTH + 10:
                    continue
                for aftertail in self.reverse_shares.get(tail, set()):
                    if len(self.reverse_shares[self.shares[aftertail].previous_hash]) > 1: # XXX
                        print "raw"
                        continue
                    to_remove.add(aftertail)
            if not to_remove:
                break
            # if removed from this, it must be removed from verified
            #start = time.time()
            for aftertail in to_remove:
                if self.shares[aftertail].previous_hash not in self.tails:
                    print "erk", aftertail, self.shares[aftertail].previous_hash
                    continue
                self.remove(aftertail)
                if aftertail in self.verified.shares:
                    self.verified.remove(aftertail)
            #end = time.time()
            #print "removed! %i %f" % (len(to_remove), (end - start)/len(to_remove))
        
        if best is not None:
            best_share = self.shares[best]
            if (best_share.header['previous_block'], best_share.header['bits']) != (previous_block, bits) and best_share.header_hash != previous_block and best_share.peer is not None:
                if p2pool.DEBUG:
                    print 'Stale detected! %x < %x' % (best_share.header['previous_block'], previous_block)
                best = best_share.previous_hash
            
            timestamp_cutoff = min(int(time.time()), best_share.timestamp) - 3600
            target_cutoff = 2**256//(self.net.SHARE_PERIOD*best_tail_score[1] + 1) * 2 if best_tail_score[1] is not None else 2**256-1
        else:
            timestamp_cutoff = int(time.time()) - 24*60*60
            target_cutoff = 2**256-1
        
        if p2pool.DEBUG:
            print 'Desire %i shares. Cutoff: %s old diff>%.2f' % (len(desired), math.format_dt(time.time() - timestamp_cutoff), bitcoin_data.target_to_difficulty(target_cutoff))
            for peer, hash, ts, targ in desired:
                print '   ', '%s:%i' % peer.addr if peer is not None else None, format_hash(hash), math.format_dt(time.time() - ts), bitcoin_data.target_to_difficulty(targ), ts >= timestamp_cutoff, targ <= target_cutoff
        
        return best, [(peer, hash) for peer, hash, ts, targ in desired if ts >= timestamp_cutoff and targ <= target_cutoff]
    
    def score(self, share_hash, block_rel_height_func):
        # returns approximate lower bound on chain's hashrate in the last self.net.CHAIN_LENGTH*15//16*self.net.SHARE_PERIOD time
        
        head_height = self.verified.get_height(share_hash)
        if head_height < self.net.CHAIN_LENGTH:
            return head_height, None
        
        end_point = self.verified.get_nth_parent_hash(share_hash, self.net.CHAIN_LENGTH*15//16)
        
        block_height = max(block_rel_height_func(share.header['previous_block']) for share in
            self.verified.get_chain(end_point, self.net.CHAIN_LENGTH//16))
        
        return self.net.CHAIN_LENGTH, (self.verified.get_work(share_hash) - self.verified.get_work(end_point))//((0 - block_height + 1)*self.net.PARENT.BLOCK_PERIOD)

def format_hash(x):
    if x is None:
        return 'xxxxxxxx'
    return '%08x' % (x % 2**32)

class ShareStore(object):
    def __init__(self, prefix, net):
        self.filename = prefix
        self.dirname = os.path.dirname(os.path.abspath(prefix))
        self.filename = os.path.basename(os.path.abspath(prefix))
        self.net = net
        self.known = None # will be filename -> set of share hashes, set of verified hashes
        self.known_desired = None
    
    def get_shares(self):
        if self.known is not None:
            raise AssertionError()
        known = {}
        filenames, next = self.get_filenames_and_next()
        for filename in filenames:
            share_hashes, verified_hashes = known.setdefault(filename, (set(), set()))
            with open(filename, 'rb') as f:
                for line in f:
                    try:
                        type_id_str, data_hex = line.strip().split(' ')
                        type_id = int(type_id_str)
                        if type_id == 0:
                            pass
                        elif type_id == 1:
                            pass
                        elif type_id == 2:
                            verified_hash = int(data_hex, 16)
                            yield 'verified_hash', verified_hash
                            verified_hashes.add(verified_hash)
                        elif type_id == 5:
                            raw_share = share_type.unpack(data_hex.decode('hex'))
                            if raw_share['type'] in [0, 1]:
                                continue
                            share = Share.from_share(raw_share, self.net, None)
                            yield 'share', share
                            share_hashes.add(share.hash)
                        else:
                            raise NotImplementedError("share type %i" % (type_id,))
                    except Exception:
                        log.err(None, "Error while reading saved shares, continuing where left off:")
        self.known = known
        self.known_desired = dict((k, (set(a), set(b))) for k, (a, b) in known.iteritems())
    
    def _add_line(self, line):
        filenames, next = self.get_filenames_and_next()
        if filenames and os.path.getsize(filenames[-1]) < 10e6:
            filename = filenames[-1]
        else:
            filename = next
        
        with open(filename, 'ab') as f:
            f.write(line + '\n')
        
        return filename
    
    def add_share(self, share):
        for filename, (share_hashes, verified_hashes) in self.known.iteritems():
            if share.hash in share_hashes:
                break
        else:
            filename = self._add_line("%i %s" % (5, share_type.pack(share.as_share()).encode('hex')))
            share_hashes, verified_hashes = self.known.setdefault(filename, (set(), set()))
            share_hashes.add(share.hash)
        share_hashes, verified_hashes = self.known_desired.setdefault(filename, (set(), set()))
        share_hashes.add(share.hash)
    
    def add_verified_hash(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known.iteritems():
            if share_hash in verified_hashes:
                break
        else:
            filename = self._add_line("%i %x" % (2, share_hash))
            share_hashes, verified_hashes = self.known.setdefault(filename, (set(), set()))
            verified_hashes.add(share_hash)
        share_hashes, verified_hashes = self.known_desired.setdefault(filename, (set(), set()))
        verified_hashes.add(share_hash)
    
    def get_filenames_and_next(self):
        suffixes = sorted(int(x[len(self.filename):]) for x in os.listdir(self.dirname) if x.startswith(self.filename) and x[len(self.filename):].isdigit())
        return [os.path.join(self.dirname, self.filename + str(suffix)) for suffix in suffixes], os.path.join(self.dirname, self.filename + (str(suffixes[-1] + 1) if suffixes else str(0)))
    
    def forget_share(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            if share_hash in share_hashes:
                share_hashes.remove(share_hash)
        self.check_remove()
    
    def forget_verified_share(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            if share_hash in verified_hashes:
                verified_hashes.remove(share_hash)
        self.check_remove()
    
    def check_remove(self):
        to_remove = set()
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            #print filename, len(share_hashes) + len(verified_hashes)
            if not share_hashes and not verified_hashes:
                to_remove.add(filename)
        for filename in to_remove:
            self.known.pop(filename)
            self.known_desired.pop(filename)
            os.remove(filename)
            print "REMOVED", filename
