from p2pool.util import skiplist

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

if __name__ == '__main__':
    import random
    from p2pool.bitcoin import data
    t = data.Tracker()
    d = DistanceSkipList(t)
    for i in xrange(2000):
        t.add(data.FakeShare(hash=i, previous_hash=i - 1 if i > 0 else None))
    for i in xrange(2000):
        a = random.randrange(2000)
        b = random.randrange(a + 1)
        res = d(a, b)
        assert res == a - b, (a, b, res)
