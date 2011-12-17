import random
import unittest

from p2pool.util import forest, math
from p2pool.bitcoin import data as bitcoin_data

class DumbTracker(object):
    def __init__(self, shares=[]):
        self.shares = {} # hash -> share
        self.reverse_shares = {} # previous_hash -> set of share_hashes
        
        for share in shares:
            self.add(share)
    
    def add(self, share):
        if share.hash in self.shares:
            raise ValueError('share already present')
        self.shares[share.hash] = share
        self.reverse_shares.setdefault(share.previous_hash, set()).add(share.hash)
    
    def remove(self, share_hash):
        share = self.shares[share_hash]
        del share_hash
        
        self.shares.pop(share.hash)
        self.reverse_shares[share.previous_hash].remove(share.hash)
        if not self.reverse_shares[share.previous_hash]:
            self.reverse_shares.pop(share.previous_hash)
    
    @property
    def heads(self):
        return dict((x, self.get_last(x)) for x in self.shares if x not in self.reverse_shares)
    
    @property
    def tails(self):
        return dict((x, set(y for y in self.shares if self.get_last(y) == x and y not in self.reverse_shares)) for x in self.reverse_shares if x not in self.shares)
    
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
    
    def get_nth_parent_hash(self, share_hash, n):
        for i in xrange(n):
            share_hash = self.shares[share_hash].previous_hash
        return share_hash
    
    def get_height_work_and_last(self, share_hash):
        height = 0
        work = 0
        while share_hash in self.shares:
            share_hash, work_inc = self.shares[share_hash].previous_hash, bitcoin_data.target_to_average_attempts(self.shares[share_hash].target)
            height += 1
            work += work_inc
        return height, work, share_hash
    
    def get_chain(self, start_hash, length):
        # same implementation :/
        assert length <= self.get_height(start_hash)
        for i in xrange(length):
            yield self.shares[start_hash]
            start_hash = self.shares[start_hash].previous_hash
    
    def is_child_of(self, share_hash, possible_child_hash):
        if self.get_last(share_hash) != self.get_last(possible_child_hash):
            return None
        while True:
            if possible_child_hash == share_hash:
                return True
            if possible_child_hash not in self.shares:
                return False
            possible_child_hash = self.shares[possible_child_hash].previous_hash

class FakeShare(object):
    target = 2**256 - 1
    def __init__(self, **kwargs):
        for k, v in kwargs.iteritems():
            setattr(self, k, v)
        self._attrs = kwargs
    
    def __repr__(self):
        return 'FakeShare(' + ', '.join('%s=%r' % (k, v) for k, v in self._attrs.iteritems()) + ')'

def test_tracker(self):
    t = DumbTracker(self.shares.itervalues())
    
    assert self.shares == t.shares, (self.shares, t.shares)
    assert self.reverse_shares == t.reverse_shares, (self.reverse_shares, t.reverse_shares)
    assert self.heads == t.heads, (self.heads, t.heads)
    assert self.tails == t.tails, (self.tails, t.tails)
    
    if random.random() < 0.9:
        return
    
    for start in self.shares:
        a, b = self.get_height_work_and_last(start), t.get_height_work_and_last(start)
        assert a == b, (a, b)
        
        other = random.choice(self.shares.keys())
        assert self.is_child_of(start, other) == t.is_child_of(start, other)
        assert self.is_child_of(other, start) == t.is_child_of(other, start)
        
        length = random.randrange(a[0])
        assert list(self.get_chain(start, length)) == list(t.get_chain(start, length))

def generate_tracker_simple(n):
    t = forest.Tracker(math.shuffled(FakeShare(hash=i, previous_hash=i - 1 if i > 0 else None) for i in xrange(n)))
    test_tracker(t)
    return t

def generate_tracker_random(n):
    shares = []
    for i in xrange(n):
        x = random.choice(shares + [FakeShare(hash=None), FakeShare(hash=random.randrange(1000000, 2000000))]).hash
        shares.append(FakeShare(hash=i, previous_hash=x))
    t = forest.Tracker(math.shuffled(shares))
    test_tracker(t)
    return t

class Test(unittest.TestCase):
    def test_tracker(self):
        t = generate_tracker_simple(100)
        
        assert t.heads == {99: None}
        assert t.tails == {None: set([99])}
        
        assert t.get_nth_parent_hash(90, 50) == 90 - 50
        assert t.get_nth_parent_hash(91, 42) == 91 - 42
    
    def test_get_nth_parent_hash(self):
        t = generate_tracker_simple(200)
        
        for i in xrange(1000):
            a = random.randrange(200)
            b = random.randrange(a + 1)
            res = t.get_nth_parent_hash(a, b)
            assert res == a - b, (a, b, res)
    
    def test_tracker2(self):
        for ii in xrange(20):
            t = generate_tracker_random(random.randrange(100))
            #print "--start--"
            while t.shares:
                while True:
                    try:
                        t.remove(random.choice(list(t.shares)))
                    except NotImplementedError:
                        pass # print "aborted", x
                    else:
                        break
                test_tracker(t)
    
    def test_tracker3(self):
        for ii in xrange(10):
            shares = []
            for i in xrange(random.randrange(100)):
                x = random.choice(shares + [FakeShare(hash=None), FakeShare(hash=random.randrange(1000000, 2000000))]).hash
                shares.append(FakeShare(hash=i, previous_hash=x))
            
            t = forest.Tracker()
            test_tracker(t)
            
            for share in math.shuffled(shares):
                t.add(share)
                test_tracker(t)
                if random.randrange(3) == 0:
                    while True:
                        try:
                            t.remove(random.choice(list(t.shares)))
                        except NotImplementedError:
                            pass
                        else:
                            break
                    test_tracker(t)
            
            for share in math.shuffled(shares):
                if share.hash not in t.shares:
                    t.add(share)
                    test_tracker(t)
                if random.randrange(3) == 0:
                    while True:
                        try:
                            t.remove(random.choice(list(t.shares)))
                        except NotImplementedError:
                            pass
                        else:
                            break
                    test_tracker(t)
            
            while t.shares:
                while True:
                    try:
                        t.remove(random.choice(list(t.shares)))
                    except NotImplementedError:
                        pass
                    else:
                        break
                test_tracker(t)
