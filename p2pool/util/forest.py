'''
forest data structure
'''

import itertools
import weakref

from p2pool.util import skiplist, variable
from p2pool.bitcoin import data as bitcoin_data


class TrackerSkipList(skiplist.SkipList):
    def __init__(self, tracker):
        skiplist.SkipList.__init__(self)
        self.tracker = tracker
        
        self_ref = weakref.ref(self, lambda _: tracker.removed.unwatch(watch_id))
        watch_id = self.tracker.removed.watch(lambda share: self_ref().forget_item(share.hash))
    
    def previous(self, element):
        return self.tracker.shares[element].previous_hash


class DistanceSkipList(TrackerSkipList):
    def get_delta(self, element):
        return element, 1, self.tracker.shares[element].previous_hash
    
    def combine_deltas(self, (from_hash1, dist1, to_hash1), (from_hash2, dist2, to_hash2)):
        if to_hash1 != from_hash2:
            raise AssertionError()
        return from_hash1, dist1 + dist2, to_hash2
    
    def initial_solution(self, start, (n,)):
        return 0, start
    
    def apply_delta(self, (dist1, to_hash1), (from_hash2, dist2, to_hash2), (n,)):
        if to_hash1 != from_hash2:
            raise AssertionError()
        return dist1 + dist2, to_hash2
    
    def judge(self, (dist, hash), (n,)):
        if dist > n:
            return 1
        elif dist == n:
            return 0
        else:
            return -1
    
    def finalize(self, (dist, hash), (n,)):
        assert dist == n
        return hash


class AttributeDelta(object):
    __slots__ = 'height work'.split(' ')
    
    @classmethod
    def get_none(cls):
        return cls(0, 0)
    
    @classmethod
    def from_element(cls, share):
        return cls(1, bitcoin_data.target_to_average_attempts(share.target))
    
    def __init__(self, height, work):
        self.height, self.work = height, work
    
    def __add__(self, other):
        return AttributeDelta(self.height + other.height, self.work + other.work)
    
    def __sub__(self, other):
        return AttributeDelta(self.height - other.height, self.work - other.work)

class Tracker(object):
    def __init__(self, shares=[], delta_type=AttributeDelta):
        self.shares = {} # hash -> share
        self.reverse_shares = {} # previous_hash -> set of share_hashes
        
        self.heads = {} # head hash -> tail_hash
        self.tails = {} # tail hash -> set of head hashes
        
        self.deltas = {} # share_hash -> delta, ref
        self.reverse_deltas = {} # ref -> set of share_hashes
        
        self.ref_generator = itertools.count()
        self.delta_refs = {} # ref -> delta, share_hash
        self.reverse_delta_refs = {} # share_hash -> ref
        
        self.added = variable.Event()
        self.removed = variable.Event()
        
        self.get_nth_parent_hash = DistanceSkipList(self)
        
        self.delta_type = delta_type
        
        for share in shares:
            self.add(share)
    
    def add(self, share):
        assert not isinstance(share, (int, long, type(None)))
        if share.hash in self.shares:
            raise ValueError('share already present')
        
        if share.hash in self.tails:
            heads = self.tails.pop(share.hash)
        else:
            heads = set([share.hash])
        
        if share.previous_hash in self.heads:
            tail = self.heads.pop(share.previous_hash)
        else:
            tail = self.get_last(share.previous_hash)
        
        self.shares[share.hash] = share
        self.reverse_shares.setdefault(share.previous_hash, set()).add(share.hash)
        
        self.tails.setdefault(tail, set()).update(heads)
        if share.previous_hash in self.tails[tail]:
            self.tails[tail].remove(share.previous_hash)
        
        for head in heads:
            self.heads[head] = tail
        
        self.added.happened(share)
    
    def remove(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        if share_hash not in self.shares:
            raise KeyError()
        
        share = self.shares[share_hash]
        del share_hash
        
        children = self.reverse_shares.get(share.hash, set())
        
        if share.hash in self.heads and share.previous_hash in self.tails:
            tail = self.heads.pop(share.hash)
            self.tails[tail].remove(share.hash)
            if not self.tails[share.previous_hash]:
                self.tails.pop(share.previous_hash)
        elif share.hash in self.heads:
            tail = self.heads.pop(share.hash)
            self.tails[tail].remove(share.hash)
            if self.reverse_shares[share.previous_hash] != set([share.hash]):
                pass # has sibling
            else:
                self.tails[tail].add(share.previous_hash)
                self.heads[share.previous_hash] = tail
        elif share.previous_hash in self.tails and len(self.reverse_shares[share.previous_hash]) <= 1:
            # move delta refs referencing children down to this, so they can be moved up in one step
            if share.previous_hash in self.reverse_delta_refs:
                for x in list(self.reverse_deltas.get(self.reverse_delta_refs.get(share.hash, object()), set())):
                    self.get_last(x)
                assert share.hash not in self.reverse_delta_refs, list(self.reverse_deltas.get(self.reverse_delta_refs.get(share.hash, None), set()))
            
            heads = self.tails.pop(share.previous_hash)
            for head in heads:
                self.heads[head] = share.hash
            self.tails[share.hash] = set(heads)
            
            # move ref pointing to this up
            if share.previous_hash in self.reverse_delta_refs:
                assert share.hash not in self.reverse_delta_refs, list(self.reverse_deltas.get(self.reverse_delta_refs.get(share.hash, object()), set()))
                
                ref = self.reverse_delta_refs[share.previous_hash]
                cur_delta, cur_hash = self.delta_refs[ref]
                assert cur_hash == share.previous_hash
                self.delta_refs[ref] = cur_delta - self.delta_type.from_element(share), share.hash
                del self.reverse_delta_refs[share.previous_hash]
                self.reverse_delta_refs[share.hash] = ref
        else:
            raise NotImplementedError()
        
        # delete delta entry and ref if it is empty
        if share.hash in self.deltas:
            delta1, ref = self.deltas.pop(share.hash)
            self.reverse_deltas[ref].remove(share.hash)
            if not self.reverse_deltas[ref]:
                del self.reverse_deltas[ref]
                delta2, ref_hash = self.delta_refs.pop(ref)
                del self.reverse_delta_refs[ref_hash]
        
        self.shares.pop(share.hash)
        self.reverse_shares[share.previous_hash].remove(share.hash)
        if not self.reverse_shares[share.previous_hash]:
            self.reverse_shares.pop(share.previous_hash)
        
        self.removed.happened(share)
    
    def get_height(self, share_hash):
        delta, last = self.get_delta(share_hash)
        return delta.height
    
    def get_work(self, share_hash):
        delta, last = self.get_delta(share_hash)
        return delta.work
    
    def get_last(self, share_hash):
        delta, last = self.get_delta(share_hash)
        return last
    
    def get_height_and_last(self, share_hash):
        delta, last = self.get_delta(share_hash)
        return delta.height, last
    
    def get_height_work_and_last(self, share_hash):
        delta, last = self.get_delta(share_hash)
        return delta.height, delta.work, last
    
    def _get_delta(self, share_hash):
        if share_hash in self.deltas:
            delta1, ref = self.deltas[share_hash]
            delta2, share_hash = self.delta_refs[ref]
            return delta1 + delta2, share_hash
        else:
            return self.delta_type.from_element(self.shares[share_hash]), self.shares[share_hash].previous_hash
    
    def _set_delta(self, share_hash, delta, other_share_hash):
        if other_share_hash not in self.reverse_delta_refs:
            ref = self.ref_generator.next()
            assert ref not in self.delta_refs
            self.delta_refs[ref] = self.delta_type.get_none(), other_share_hash
            self.reverse_delta_refs[other_share_hash] = ref
            del ref
        
        ref = self.reverse_delta_refs[other_share_hash]
        ref_delta, ref_share_hash = self.delta_refs[ref]
        assert ref_share_hash == other_share_hash
        
        if share_hash in self.deltas:
            prev_ref = self.deltas[share_hash][1]
            self.reverse_deltas[prev_ref].remove(share_hash)
            if not self.reverse_deltas[prev_ref] and prev_ref != ref:
                self.reverse_deltas.pop(prev_ref)
                _, x = self.delta_refs.pop(prev_ref)
                self.reverse_delta_refs.pop(x)
        self.deltas[share_hash] = delta - ref_delta, ref
        self.reverse_deltas.setdefault(ref, set()).add(share_hash)
    
    def get_delta(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        delta = self.delta_type.get_none()
        updates = []
        while share_hash in self.shares:
            updates.append((share_hash, delta))
            this_delta, share_hash = self._get_delta(share_hash)
            delta += this_delta
        for update_hash, delta_then in updates:
            self._set_delta(update_hash, delta - delta_then, share_hash)
        return delta, share_hash
    
    def get_chain(self, start_hash, length):
        assert length <= self.get_height(start_hash)
        for i in xrange(length):
            yield self.shares[start_hash]
            start_hash = self.shares[start_hash].previous_hash
    
    def is_child_of(self, share_hash, possible_child_hash):
        height, last = self.get_height_and_last(share_hash)
        child_height, child_last = self.get_height_and_last(possible_child_hash)
        if child_last != last:
            return None # not connected, so can't be determined
        height_up = child_height - height
        return height_up >= 0 and self.get_nth_parent_hash(possible_child_hash, height_up) == share_hash
