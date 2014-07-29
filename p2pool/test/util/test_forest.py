import random
import unittest

from p2pool.util import forest, math

class DumbTracker(object):
    def __init__(self, items=[]):
        self.items = {} # hash -> item
        self.reverse = {} # previous_hash -> set of item_hashes
        
        for item in items:
            self.add(item)
    
    def add(self, item):
        if item.hash in self.items:
            raise ValueError('item already present')
        self.items[item.hash] = item
        self.reverse.setdefault(item.previous_hash, set()).add(item.hash)
    
    def remove(self, item_hash):
        item = self.items[item_hash]
        del item_hash
        
        self.items.pop(item.hash)
        self.reverse[item.previous_hash].remove(item.hash)
        if not self.reverse[item.previous_hash]:
            self.reverse.pop(item.previous_hash)
    
    @property
    def heads(self):
        return dict((x, self.get_last(x)) for x in self.items if x not in self.reverse)
    
    @property
    def tails(self):
        return dict((x, set(y for y in self.items if self.get_last(y) == x and y not in self.reverse)) for x in self.reverse if x not in self.items)
    
    def get_nth_parent_hash(self, item_hash, n):
        for i in xrange(n):
            item_hash = self.items[item_hash].previous_hash
        return item_hash
    
    def get_height(self, item_hash):
        height, last = self.get_height_and_last(item_hash)
        return height
    
    def get_last(self, item_hash):
        height, last = self.get_height_and_last(item_hash)
        return last
    
    def get_height_and_last(self, item_hash):
        height = 0
        while item_hash in self.items:
            item_hash = self.items[item_hash].previous_hash
            height += 1
        return height, item_hash
    
    def get_chain(self, start_hash, length):
        # same implementation :/
        assert length <= self.get_height(start_hash)
        for i in xrange(length):
            yield self.items[start_hash]
            start_hash = self.items[start_hash].previous_hash
    
    def is_child_of(self, item_hash, possible_child_hash):
        if self.get_last(item_hash) != self.get_last(possible_child_hash):
            return None
        while True:
            if possible_child_hash == item_hash:
                return True
            if possible_child_hash not in self.items:
                return False
            possible_child_hash = self.items[possible_child_hash].previous_hash

class FakeShare(object):
    def __init__(self, **kwargs):
        for k, v in kwargs.iteritems():
            setattr(self, k, v)
        self._attrs = kwargs

def test_tracker(self):
    t = DumbTracker(self.items.itervalues())
    
    assert self.items == t.items, (self.items, t.items)
    assert self.reverse == t.reverse, (self.reverse, t.reverse)
    assert self.heads == t.heads, (self.heads, t.heads)
    assert self.tails == t.tails, (self.tails, t.tails)
    
    if random.random() < 0.9:
        return
    
    for start in self.items:
        a, b = self.get_height_and_last(start), t.get_height_and_last(start)
        assert a == b, (a, b)
        
        other = random.choice(self.items.keys())
        assert self.is_child_of(start, other) == t.is_child_of(start, other)
        assert self.is_child_of(other, start) == t.is_child_of(other, start)
        
        length = random.randrange(a[0])
        assert list(self.get_chain(start, length)) == list(t.get_chain(start, length))

def generate_tracker_simple(n):
    t = forest.Tracker(math.shuffled(FakeShare(hash=i, previous_hash=i - 1 if i > 0 else None) for i in xrange(n)))
    test_tracker(t)
    return t

def generate_tracker_random(n):
    items = []
    for i in xrange(n):
        x = random.choice(items + [FakeShare(hash=None), FakeShare(hash=random.randrange(1000000, 2000000))]).hash
        items.append(FakeShare(hash=i, previous_hash=x))
    t = forest.Tracker(math.shuffled(items))
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
            while t.items:
                while True:
                    try:
                        t.remove(random.choice(list(t.items)))
                    except NotImplementedError:
                        pass # print "aborted", x
                    else:
                        break
                test_tracker(t)
    
    def test_tracker3(self):
        for ii in xrange(10):
            items = []
            for i in xrange(random.randrange(100)):
                x = random.choice(items + [FakeShare(hash=None), FakeShare(hash=random.randrange(1000000, 2000000))]).hash
                items.append(FakeShare(hash=i, previous_hash=x))
            
            t = forest.Tracker()
            test_tracker(t)
            
            for item in math.shuffled(items):
                t.add(item)
                test_tracker(t)
                if random.randrange(3) == 0:
                    while True:
                        try:
                            t.remove(random.choice(list(t.items)))
                        except NotImplementedError:
                            pass
                        else:
                            break
                    test_tracker(t)
            
            for item in math.shuffled(items):
                if item.hash not in t.items:
                    t.add(item)
                    test_tracker(t)
                if random.randrange(3) == 0:
                    while True:
                        try:
                            t.remove(random.choice(list(t.items)))
                        except NotImplementedError:
                            pass
                        else:
                            break
                    test_tracker(t)
            
            while t.items:
                while True:
                    try:
                        t.remove(random.choice(list(t.items)))
                    except NotImplementedError:
                        pass
                    else:
                        break
                test_tracker(t)
