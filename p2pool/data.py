from __future__ import division

import random
import time
import os

from twisted.python import log

import p2pool
from p2pool import skiplists
from p2pool.bitcoin import data as bitcoin_data, script
from p2pool.util import math, forest, pack


share_data_type = pack.ComposedType([
    ('previous_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
    ('coinbase', pack.VarStrType()),
    ('nonce', pack.VarStrType()),
    ('new_script', pack.VarStrType()),
    ('subsidy', pack.IntType(64)),
    ('donation', pack.IntType(16)),
    ('stale_info', pack.IntType(8)), # 0 nothing, 253 orphan, 254 doa
])

share_info_type = pack.ComposedType([
    ('share_data', share_data_type),
    ('bits', bitcoin_data.FloatingIntegerType()),
    ('timestamp', pack.IntType(32)),
])

share1a_type = pack.ComposedType([
    ('header', bitcoin_data.block_header_type),
    ('share_info', share_info_type),
    ('merkle_branch', bitcoin_data.merkle_branch_type),
])

share1b_type = pack.ComposedType([
    ('header', bitcoin_data.block_header_type),
    ('share_info', share_info_type),
    ('other_txs', pack.ListType(bitcoin_data.tx_type)),
])

# type:
# 0: share1a
# 1: share1b

share_type = pack.ComposedType([
    ('type', pack.VarIntType()),
    ('contents', pack.VarStrType()),
])

class Share(object):
    __slots__ = 'header share_info merkle_branch other_txs timestamp share_data previous_hash target pow_hash header_hash hash time_seen peer net new_script max_target'.split(' ')
    
    @classmethod
    def from_share(cls, share, net):
        if share['type'] == 0:
            res = cls(net, **share1a_type.unpack(share['contents']))
            if not (res.pow_hash > res.header['bits'].target):
                raise ValueError('invalid share type')
            return res
        elif share['type'] == 1:
            share1b = share1b_type.unpack(share['contents'])
            res = cls(net, merkle_branch=bitcoin_data.calculate_merkle_branch([0] + [bitcoin_data.hash256(bitcoin_data.tx_type.pack(x)) for x in share1b['other_txs']], 0), **share1b)
            if not (res.pow_hash <= res.header['bits'].target):
                raise ValueError('invalid share type')
            return res
        else:
            raise ValueError('unknown share type: %r' % (share['type'],))
    
    def __init__(self, net, header, share_info, merkle_branch, other_txs=None):
        self.net = net
        
        if p2pool.DEBUG and other_txs is not None and bitcoin_data.calculate_merkle_branch([0] + [bitcoin_data.hash256(bitcoin_data.tx_type.pack(x)) for x in other_txs], 0) != merkle_branch:
            raise ValueError('merkle_branch and other_txs do not match')
        
        if len(merkle_branch) > 16:
            raise ValueError('merkle_branch too long!')
        
        self.header = header
        self.share_info = share_info
        self.merkle_branch = merkle_branch
        
        self.share_data = self.share_info['share_data']
        self.target = self.max_target = self.share_info['bits'].target
        self.timestamp = self.share_info['timestamp']
        
        if len(self.share_data['new_script']) > 100:
            raise ValueError('new_script too long!')
        if script.get_sigop_count(self.share_data['new_script']) > 1:
            raise ValueError('too many sigops!')
        self.new_script = self.share_data['new_script']
        
        self.previous_hash = self.share_data['previous_share_hash']
        
        if len(self.share_data['nonce']) > 100:
            raise ValueError('nonce too long!')
        
        if len(self.share_data['coinbase']) > 100:
            raise ValueError('''coinbase too large! %i bytes''' % (len(self.share_data['coinbase']),))
        
        self.pow_hash = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(header))
        self.header_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(header))
        
        self.hash = bitcoin_data.hash256(share1a_type.pack(self.as_share1a()))
        
        if self.pow_hash > self.target:
            print 'hash %x' % self.pow_hash
            print 'targ %x' % self.target
            raise ValueError('not enough work!')
        
        if other_txs is not None and not self.pow_hash <= self.header['bits'].target:
            raise ValueError('other_txs provided when not a block solution')
        if other_txs is None and self.pow_hash <= self.header['bits'].target:
            raise ValueError('other_txs not provided when a block solution')
        
        self.other_txs = other_txs
        
        # XXX eww
        self.time_seen = time.time()
        self.peer = None
    
    def __repr__(self):
        return '<Share %s>' % (' '.join('%s=%r' % (k, getattr(self, k)) for k in self.__slots__),)
    
    def check(self, tracker):
        share_info, gentx = generate_transaction(tracker, self.share_info['share_data'], self.header['bits'].target, self.share_info['timestamp'], self.net)
        if share_info != self.share_info:
            raise ValueError('share difficulty invalid')
        
        if bitcoin_data.check_merkle_branch(bitcoin_data.hash256(bitcoin_data.tx_type.pack(gentx)), 0, self.merkle_branch) != self.header['merkle_root']:
            raise ValueError('''gentx doesn't match header via merkle_branch''')
    
    def as_share(self):
        if self.pow_hash > self.header['bits'].target: # share1a
            return dict(type=0, contents=share1a_type.pack(self.as_share1a()))
        elif self.pow_hash <= self.header['bits'].target: # share1b
            if self.other_txs is None:
                raise ValueError('share does not contain all txs')
            return dict(type=1, contents=share1b_type.pack(dict(header=self.header, share_info=self.share_info, other_txs=self.other_txs)))
        else:
            raise AssertionError()
    
    def as_share1a(self):
        return dict(header=self.header, share_info=self.share_info, merkle_branch=self.merkle_branch)
    
    def as_block(self, tracker):
        if self.other_txs is None:
            raise ValueError('share does not contain all txs')
        
        share_info, gentx = generate_transaction(tracker, self.share_info['share_data'], self.header['bits'].target, self.share_info['timestamp'], self.net)
        assert share_info == self.share_info
        
        return dict(header=self.header, txs=[gentx] + self.other_txs)

def get_pool_attempts_per_second(tracker, previous_share_hash, dist, min_work=False):
    assert dist >= 2
    near = tracker.shares[previous_share_hash]
    far = tracker.shares[tracker.get_nth_parent_hash(previous_share_hash, dist - 1)]
    attempts = tracker.get_work(near.hash) - tracker.get_work(far.hash) if not min_work else tracker.get_delta(near.hash).min_work - tracker.get_delta(far.hash).min_work
    time = near.timestamp - far.timestamp
    if time <= 0:
        time = 1
    return attempts//time

def get_average_stale_prop(tracker, share_hash, lookbehind):
    stales = sum(1 for share in tracker.get_chain(share_hash, lookbehind) if share.share_data['stale_info'] in [253, 254])
    return stales/(lookbehind + stales)

DONATION_SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')

def generate_transaction(tracker, share_data, block_target, desired_timestamp, net):
    previous_share_hash = share_data['previous_share_hash']
    new_script = share_data['new_script']
    subsidy = share_data['subsidy']
    donation = share_data['donation']
    assert 0 <= donation <= 65535
    
    if len(share_data['coinbase']) > 100:
        raise ValueError('coinbase too long!')
    
    previous_share = tracker.shares[previous_share_hash] if previous_share_hash is not None else None
    
    chain_length = getattr(net, 'REAL_CHAIN_LENGTH_FUNC', lambda _: net.REAL_CHAIN_LENGTH)(previous_share.timestamp if previous_share is not None else None)
    
    height, last = tracker.get_height_and_last(previous_share_hash)
    assert height >= chain_length or last is None
    if height < net.TARGET_LOOKBEHIND:
        bits = bitcoin_data.FloatingInteger.from_target_upper_bound(net.MAX_TARGET)
    else:
        attempts_per_second = get_pool_attempts_per_second(tracker, previous_share_hash, net.TARGET_LOOKBEHIND)
        pre_target = 2**256//(net.SHARE_PERIOD*attempts_per_second) - 1
        pre_target2 = math.clip(pre_target, (previous_share.target*9//10, previous_share.target*11//10))
        pre_target3 = math.clip(pre_target2, (0, net.MAX_TARGET))
        bits = bitcoin_data.FloatingInteger.from_target_upper_bound(pre_target3)
    
    attempts_to_block = bitcoin_data.target_to_average_attempts(block_target)
    max_att = net.SPREAD * attempts_to_block
    
    this_att = min(bitcoin_data.target_to_average_attempts(bits.target), max_att)
    other_weights, other_total_weight, other_donation_weight = tracker.get_cumulative_weights(previous_share_hash, min(height, chain_length), 65535*max(0, max_att - this_att))
    assert other_total_weight == sum(other_weights.itervalues()) + other_donation_weight, (other_total_weight, sum(other_weights.itervalues()) + other_donation_weight)
    weights, total_weight, donation_weight = math.add_dicts({new_script: this_att*(65535-donation)}, other_weights), this_att*65535 + other_total_weight, this_att*donation + other_donation_weight
    assert total_weight == sum(weights.itervalues()) + donation_weight, (total_weight, sum(weights.itervalues()) + donation_weight)
    
    # 1 satoshi is always donated so that a list of p2pool generated blocks can be easily found by looking at the donation address
    amounts = dict((script, (subsidy-1)*(199*weight)//(200*total_weight)) for (script, weight) in weights.iteritems())
    amounts[new_script] = amounts.get(new_script, 0) + (subsidy-1)//200
    amounts[DONATION_SCRIPT] = amounts.get(DONATION_SCRIPT, 0) + (subsidy-1)*(199*donation_weight)//(200*total_weight)
    amounts[DONATION_SCRIPT] = amounts.get(DONATION_SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra satoshis :P
    
    if sum(amounts.itervalues()) != subsidy:
        raise ValueError()
    if any(x < 0 for x in amounts.itervalues()):
        raise ValueError()
    
    dests = sorted(amounts.iterkeys(), key=lambda script: (amounts[script], script))
    dests = dests[-4000:] # block length limit, unlikely to ever be hit
    
    share_info = dict(
        share_data=share_data,
        bits=bits,
        timestamp=math.clip(desired_timestamp, (previous_share.timestamp - 60, previous_share.timestamp + 60)) if previous_share is not None else desired_timestamp,
    )
    
    return share_info, dict(
        version=1,
        tx_ins=[dict(
            previous_output=None,
            sequence=None,
            script=share_data['coinbase'].ljust(2, '\x00'),
        )],
        tx_outs=[dict(value=0, script='\x20' + pack.IntType(256).pack(bitcoin_data.hash256(share_info_type.pack(share_info))))] + [dict(value=amounts[script], script=script) for script in dests if amounts[script]],
        lock_time=0,
    )

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
        
        self.get_cumulative_weights = skiplists.WeightsSkipList(self)
    
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
                    self.verified.shares[random.choice(list(self.verified.reverse_shares[last_hash]))].peer,
                    last_last_hash,
                    max(x.timestamp for x in self.get_chain(head, min(head_height, 5))),
                    min(x.target for x in self.get_chain(head, min(head_height, 5))),
                ))
        
        # decide best tree
        decorated_tails = sorted((self.score(max(self.verified.tails[tail_hash], key=self.verified.get_height), block_rel_height_func), tail_hash) for tail_hash in self.verified.tails) # XXX using get_height here is quite possibly incorrect and vulnerable
        if p2pool.DEBUG:
            print len(decorated_tails), 'tails:'
            for score, tail_hash in decorated_tails:
                print format_hash(tail_hash), score
        best_tail_score, best_tail = decorated_tails[-1] if decorated_tails else (None, None)
        
        # decide best verified head
        decorated_heads = sorted(((
            self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))),
            #self.verified.shares[h].peer is None,
            (self.verified.shares[h].header['previous_block'], self.verified.shares[h].header['bits']) == (previous_block, bits) or self.verified.shares[h].peer is None,
            -self.verified.shares[h].time_seen,
        ), h) for h in self.verified.tails.get(best_tail, []))
        if p2pool.DEBUG:
            print len(decorated_heads), 'heads. Top 10:'
            for score, head_hash in decorated_heads[-10:]:
                print '   ', format_hash(head_hash), format_hash(self.verified.shares[head_hash].previous_hash), score
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
            best_share = self.verified.shares[best]
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
                            share = Share.from_share(share_type.unpack(data_hex.decode('hex')), self.net)
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
