import itertools

from p2pool.util import skiplist, variable

from p2pool.bitcoin import data as bitcoin_data

class DistanceSkipList(skiplist.SkipList):
    def __init__(self, tracker):
        skiplist.SkipList.__init__(self)
        self.tracker = tracker
    
    def previous(self, element):
        return self.tracker.shares[element].previous_hash
    
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
    
    def finalize(self, (dist, hash)):
        return hash


# linked list tracker

class Tracker(object):
    def __init__(self, shares=[]):
        self.shares = {} # hash -> share
        #self.ids = {} # hash -> (id, height)
        self.reverse_shares = {} # previous_hash -> set of share_hashes
        
        self.heads = {} # head hash -> tail_hash
        self.tails = {} # tail hash -> set of head hashes
        
        self.heights = {} # share_hash -> height_to, ref, work_inc
        self.reverse_heights = {} # ref -> set of share_hashes
        
        self.ref_generator = itertools.count()
        self.height_refs = {} # ref -> height, share_hash, work_inc
        self.reverse_height_refs = {} # share_hash -> ref
        
        self.get_nth_parent_hash = DistanceSkipList(self)
        
        self.added = variable.Event()
        self.removed = variable.Event()
        
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
            #tail2 = share.previous_hash
            #while tail2 in self.shares:
            #    tail2 = self.shares[tail2].previous_hash
            #assert tail == tail2
        
        self.shares[share.hash] = share
        self.reverse_shares.setdefault(share.previous_hash, set()).add(share.hash)
        
        self.tails.setdefault(tail, set()).update(heads)
        if share.previous_hash in self.tails[tail]:
            self.tails[tail].remove(share.previous_hash)
        
        for head in heads:
            self.heads[head] = tail
        
        self.added.happened(share)
    
    def test(self):
        t = Tracker()
        for s in self.shares.itervalues():
            t.add(s)
        
        assert self.shares == t.shares, (self.shares, t.shares)
        assert self.reverse_shares == t.reverse_shares, (self.reverse_shares, t.reverse_shares)
        assert self.heads == t.heads, (self.heads, t.heads)
        assert self.tails == t.tails, (self.tails, t.tails)
    
    def remove(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        if share_hash not in self.shares:
            raise KeyError()
        
        share = self.shares[share_hash]
        del share_hash
        
        children = self.reverse_shares.get(share.hash, set())
        
        # move height refs referencing children down to this, so they can be moved up in one step
        if share.previous_hash in self.reverse_height_refs:
            if share.previous_hash not in self.tails:
                for x in list(self.reverse_heights.get(self.reverse_height_refs.get(share.previous_hash, object()), set())):
                    self.get_last(x)
            for x in list(self.reverse_heights.get(self.reverse_height_refs.get(share.hash, object()), set())):
                self.get_last(x)
            assert share.hash not in self.reverse_height_refs, list(self.reverse_heights.get(self.reverse_height_refs.get(share.hash, None), set()))
        
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
        elif share.previous_hash in self.tails:
            heads = self.tails[share.previous_hash]
            if len(self.reverse_shares[share.previous_hash]) > 1:
                raise NotImplementedError()
            else:
                del self.tails[share.previous_hash]
                for head in heads:
                    self.heads[head] = share.hash
                self.tails[share.hash] = set(heads)
        else:
            raise NotImplementedError()
        
        # move ref pointing to this up
        if share.previous_hash in self.reverse_height_refs:
            assert share.hash not in self.reverse_height_refs, list(self.reverse_heights.get(self.reverse_height_refs.get(share.hash, object()), set()))
            
            ref = self.reverse_height_refs[share.previous_hash]
            cur_height, cur_hash, cur_work = self.height_refs[ref]
            assert cur_hash == share.previous_hash
            self.height_refs[ref] = cur_height - 1, share.hash, cur_work - bitcoin_data.target_to_average_attempts(share.target)
            del self.reverse_height_refs[share.previous_hash]
            self.reverse_height_refs[share.hash] = ref
        
        # delete height entry, and ref if it is empty
        if share.hash in self.heights:
            _, ref, _ = self.heights.pop(share.hash)
            self.reverse_heights[ref].remove(share.hash)
            if not self.reverse_heights[ref]:
                del self.reverse_heights[ref]
                _, ref_hash, _ = self.height_refs.pop(ref)
                del self.reverse_height_refs[ref_hash]
        
        self.shares.pop(share.hash)
        self.reverse_shares[share.previous_hash].remove(share.hash)
        if not self.reverse_shares[share.previous_hash]:
            self.reverse_shares.pop(share.previous_hash)
        
        #assert self.test() is None
        self.removed.happened(share)
    
    def get_height(self, share_hash):
        height, work, last = self.get_height_work_and_last(share_hash)
        return height
    
    def get_work(self, share_hash):
        height, work, last = self.get_height_work_and_last(share_hash)
        return work
    
    def get_last(self, share_hash):
        height, work, last = self.get_height_work_and_last(share_hash)
        return last
    
    def get_height_and_last(self, share_hash):
        height, work, last = self.get_height_work_and_last(share_hash)
        return height, last
    
    def _get_height_jump(self, share_hash):
        if share_hash in self.heights:
            height_to1, ref, work_inc1 = self.heights[share_hash]
            height_to2, share_hash, work_inc2 = self.height_refs[ref]
            height_inc = height_to1 + height_to2
            work_inc = work_inc1 + work_inc2
        else:
            height_inc, share_hash, work_inc = 1, self.shares[share_hash].previous_hash, bitcoin_data.target_to_average_attempts(self.shares[share_hash].target)
        return height_inc, share_hash, work_inc
    
    def _set_height_jump(self, share_hash, height_inc, other_share_hash, work_inc):
        if other_share_hash not in self.reverse_height_refs:
            ref = self.ref_generator.next()
            assert ref not in self.height_refs
            self.height_refs[ref] = 0, other_share_hash, 0
            self.reverse_height_refs[other_share_hash] = ref
            del ref
        
        ref = self.reverse_height_refs[other_share_hash]
        ref_height_to, ref_share_hash, ref_work_inc = self.height_refs[ref]
        assert ref_share_hash == other_share_hash
        
        if share_hash in self.heights:
            prev_ref = self.heights[share_hash][1]
            self.reverse_heights[prev_ref].remove(share_hash)
            if not self.reverse_heights[prev_ref] and prev_ref != ref:
                self.reverse_heights.pop(prev_ref)
                _, x, _ = self.height_refs.pop(prev_ref)
                self.reverse_height_refs.pop(x)
        self.heights[share_hash] = height_inc - ref_height_to, ref, work_inc - ref_work_inc
        self.reverse_heights.setdefault(ref, set()).add(share_hash)
    
    def get_height_work_and_last(self, share_hash):
        assert isinstance(share_hash, (int, long, type(None)))
        orig = share_hash
        height = 0
        work = 0
        updates = []
        while share_hash in self.shares:
            updates.append((share_hash, height, work))
            height_inc, share_hash, work_inc = self._get_height_jump(share_hash)
            height += height_inc
            work += work_inc
        for update_hash, height_then, work_then in updates:
            self._set_height_jump(update_hash, height - height_then, share_hash, work - work_then)
        return height, work, share_hash
    
    def get_chain_known(self, start_hash):
        assert isinstance(start_hash, (int, long, type(None)))
        '''
        Chain starting with item of hash I{start_hash} of items that this Tracker contains
        '''
        item_hash_to_get = start_hash
        while True:
            if item_hash_to_get not in self.shares:
                break
            share = self.shares[item_hash_to_get]
            assert not isinstance(share, long)
            yield share
            item_hash_to_get = share.previous_hash
    
    def get_chain_to_root(self, start_hash, root=None):
        assert isinstance(start_hash, (int, long, type(None)))
        assert isinstance(root, (int, long, type(None)))
        '''
        Chain of hashes starting with share_hash of shares to the root (doesn't include root)
        Raises an error if one is missing
        '''
        share_hash_to_get = start_hash
        while share_hash_to_get != root:
            share = self.shares[share_hash_to_get]
            yield share
            share_hash_to_get = share.previous_hash
    
    def get_best_hash(self):
        '''
        Returns hash of item with the most items in its chain
        '''
        if not self.heads:
            return None
        return max(self.heads, key=self.get_height_and_last)
    
    def get_highest_height(self):
        return max(self.get_height_and_last(head)[0] for head in self.heads) if self.heads else 0
    
    def is_child_of(self, share_hash, possible_child_hash):
        height, last = self.get_height_and_last(share_hash)
        child_height, child_last = self.get_height_and_last(possible_child_hash)
        if child_last != last:
            return None # not connected, so can't be determined
        height_up = child_height - height
        return height_up >= 0 and self.get_nth_parent_hash(possible_child_hash, height_up) == share_hash
