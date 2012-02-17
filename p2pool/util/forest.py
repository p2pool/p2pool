'''
forest data structure
'''

import itertools
import weakref

from p2pool.util import skiplist, variable


class TrackerSkipList(skiplist.SkipList):
    def __init__(self, tracker):
        skiplist.SkipList.__init__(self)
        self.tracker = tracker
        
        self_ref = weakref.ref(self, lambda _: tracker.removed.unwatch(watch_id))
        watch_id = self.tracker.removed.watch(lambda share: self_ref().forget_item(share.hash))
    
    def previous(self, element):
        return self.tracker.delta_type.from_element(self.tracker.shares[element]).tail


class DistanceSkipList(TrackerSkipList):
    def get_delta(self, element):
        return element, 1, self.previous(element)
    
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

def get_attributedelta_type(attrs): # attrs: {name: func}
    class ProtoAttributeDelta(object):
        __slots__ = ['head', 'tail'] + attrs.keys()
        
        @classmethod
        def get_none(cls, element_id):
            return cls(element_id, element_id, **dict((k, 0) for k in attrs))
        
        @classmethod
        def from_element(cls, share):
            return cls(share.hash, share.previous_hash, **dict((k, v(share)) for k, v in attrs.iteritems()))
        
        def __init__(self, head, tail, **kwargs):
            self.head, self.tail = head, tail
            for k, v in kwargs.iteritems():
                setattr(self, k, v)
        
        def __add__(self, other):
            assert self.tail == other.head
            return self.__class__(self.head, other.tail, **dict((k, getattr(self, k) + getattr(other, k)) for k in attrs))
        
        def __sub__(self, other):
            if self.head == other.head:
                return self.__class__(other.tail, self.tail, **dict((k, getattr(self, k) - getattr(other, k)) for k in attrs))
            elif self.tail == other.tail:
                return self.__class__(self.head, other.head, **dict((k, getattr(self, k) - getattr(other, k)) for k in attrs))
            else:
                raise AssertionError()
        
        def __repr__(self):
            return '%s(%r, %r%s)' % (self.__class__, self.head, self.tail, ''.join(', %s=%r' % (k, getattr(self, k)) for k in attrs))
    ProtoAttributeDelta.attrs = attrs
    return ProtoAttributeDelta

AttributeDelta = get_attributedelta_type(dict(
    height=lambda item: 1,
))

class Tracker(object):
    def __init__(self, shares=[], delta_type=AttributeDelta):
        self.shares = {} # hash -> share
        self.reverse_shares = {} # delta.tail -> set of share_hashes
        
        self.heads = {} # head hash -> tail_hash
        self.tails = {} # tail hash -> set of head hashes
        
        self.deltas = {} # share_hash -> delta, ref
        self.reverse_deltas = {} # ref -> set of share_hashes
        
        self.ref_generator = itertools.count()
        self.delta_refs = {} # ref -> delta
        self.reverse_delta_refs = {} # delta.tail -> ref
        
        self.added = variable.Event()
        self.removed = variable.Event()
        
        self.get_nth_parent_hash = DistanceSkipList(self)
        
        self.delta_type = delta_type
        
        for share in shares:
            self.add(share)
    
    def add(self, share):
        assert not isinstance(share, (int, long, type(None)))
        delta = self.delta_type.from_element(share)
        
        if delta.head in self.shares:
            raise ValueError('share already present')
        
        if delta.head in self.tails:
            heads = self.tails.pop(delta.head)
        else:
            heads = set([delta.head])
        
        if delta.tail in self.heads:
            tail = self.heads.pop(delta.tail)
        else:
            tail = self.get_last(delta.tail)
        
        self.shares[delta.head] = share
        self.reverse_shares.setdefault(delta.tail, set()).add(delta.head)
        
        self.tails.setdefault(tail, set()).update(heads)
        if delta.tail in self.tails[tail]:
            self.tails[tail].remove(delta.tail)
        
        for head in heads:
            self.heads[head] = tail
        
        self.added.happened(share)
    
    def remove(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        if share_hash not in self.shares:
            raise KeyError()
        
        share = self.shares[share_hash]
        del share_hash
        
        delta = self.delta_type.from_element(share)
        
        children = self.reverse_shares.get(delta.head, set())
        
        if delta.head in self.heads and delta.tail in self.tails:
            tail = self.heads.pop(delta.head)
            self.tails[tail].remove(delta.head)
            if not self.tails[delta.tail]:
                self.tails.pop(delta.tail)
        elif delta.head in self.heads:
            tail = self.heads.pop(delta.head)
            self.tails[tail].remove(delta.head)
            if self.reverse_shares[delta.tail] != set([delta.head]):
                pass # has sibling
            else:
                self.tails[tail].add(delta.tail)
                self.heads[delta.tail] = tail
        elif delta.tail in self.tails and len(self.reverse_shares[delta.tail]) <= 1:
            # move delta refs referencing children down to this, so they can be moved up in one step
            if delta.tail in self.reverse_delta_refs:
                for x in list(self.reverse_deltas.get(self.reverse_delta_refs.get(delta.head, object()), set())):
                    self.get_last(x)
                assert delta.head not in self.reverse_delta_refs, list(self.reverse_deltas.get(self.reverse_delta_refs.get(delta.head, None), set()))
            
            heads = self.tails.pop(delta.tail)
            for head in heads:
                self.heads[head] = delta.head
            self.tails[delta.head] = set(heads)
            
            # move ref pointing to this up
            if delta.tail in self.reverse_delta_refs:
                assert delta.head not in self.reverse_delta_refs, list(self.reverse_deltas.get(self.reverse_delta_refs.get(delta.head, object()), set()))
                
                ref = self.reverse_delta_refs[delta.tail]
                cur_delta = self.delta_refs[ref]
                assert cur_delta.tail == delta.tail
                self.delta_refs[ref] = cur_delta - self.delta_type.from_element(share)
                assert self.delta_refs[ref].tail == delta.head
                del self.reverse_delta_refs[delta.tail]
                self.reverse_delta_refs[delta.head] = ref
        else:
            raise NotImplementedError()
        
        # delete delta entry and ref if it is empty
        if delta.head in self.deltas:
            delta1, ref = self.deltas.pop(delta.head)
            self.reverse_deltas[ref].remove(delta.head)
            if not self.reverse_deltas[ref]:
                del self.reverse_deltas[ref]
                delta2 = self.delta_refs.pop(ref)
                del self.reverse_delta_refs[delta2.tail]
        
        self.shares.pop(delta.head)
        self.reverse_shares[delta.tail].remove(delta.head)
        if not self.reverse_shares[delta.tail]:
            self.reverse_shares.pop(delta.tail)
        
        self.removed.happened(share)
    
    def get_height(self, share_hash):
        return self.get_delta(share_hash).height
    
    def get_work(self, share_hash):
        return self.get_delta(share_hash).work
    
    def get_last(self, share_hash):
        return self.get_delta(share_hash).tail
    
    def get_height_and_last(self, share_hash):
        delta = self.get_delta(share_hash)
        return delta.height, delta.tail
    
    def get_height_work_and_last(self, share_hash):
        delta = self.get_delta(share_hash)
        return delta.height, delta.work, delta.tail
    
    def _get_delta(self, share_hash):
        if share_hash in self.deltas:
            delta1, ref = self.deltas[share_hash]
            delta2 = self.delta_refs[ref]
            res = delta1 + delta2
        else:
            res = self.delta_type.from_element(self.shares[share_hash])
        assert res.head == share_hash
        return res
    
    def _set_delta(self, share_hash, delta):
        other_share_hash = delta.tail
        if other_share_hash not in self.reverse_delta_refs:
            ref = self.ref_generator.next()
            assert ref not in self.delta_refs
            self.delta_refs[ref] = self.delta_type.get_none(other_share_hash)
            self.reverse_delta_refs[other_share_hash] = ref
            del ref
        
        ref = self.reverse_delta_refs[other_share_hash]
        ref_delta = self.delta_refs[ref]
        assert ref_delta.tail == other_share_hash
        
        if share_hash in self.deltas:
            prev_ref = self.deltas[share_hash][1]
            self.reverse_deltas[prev_ref].remove(share_hash)
            if not self.reverse_deltas[prev_ref] and prev_ref != ref:
                self.reverse_deltas.pop(prev_ref)
                x = self.delta_refs.pop(prev_ref)
                self.reverse_delta_refs.pop(x.tail)
        self.deltas[share_hash] = delta - ref_delta, ref
        self.reverse_deltas.setdefault(ref, set()).add(share_hash)
    
    def get_delta(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        delta = self.delta_type.get_none(share_hash)
        updates = []
        while delta.tail in self.shares:
            updates.append((delta.tail, delta))
            this_delta = self._get_delta(delta.tail)
            delta += this_delta
        for update_hash, delta_then in updates:
            self._set_delta(update_hash, delta - delta_then)
        return delta
    
    def get_chain(self, start_hash, length):
        assert length <= self.get_height(start_hash)
        for i in xrange(length):
            yield self.shares[start_hash]
            start_hash = self.delta_type.from_element(self.shares[start_hash]).tail
    
    def is_child_of(self, share_hash, possible_child_hash):
        height, last = self.get_height_and_last(share_hash)
        child_height, child_last = self.get_height_and_last(possible_child_hash)
        if child_last != last:
            return None # not connected, so can't be determined
        height_up = child_height - height
        return height_up >= 0 and self.get_nth_parent_hash(possible_child_hash, height_up) == share_hash
