class SkipList(object):
    def query(self, start, *args, **kwargs):
        updates = {}
        pos = start
        while True:
            if pos not in self.skips:
                self.skips[pos] = math.geometric(.5), [self.base(pos)]
            skip_length, skip = self.skips[pos]
            
            for i in xrange(skip_length):
                if i in updates:
                    n_then, that_hash = updates.pop(i)
                    x, y = self.skips[that_hash]
                    assert len(y) == i
                    y.append((n_then - n, pos))
            
            for i in xrange(len(skip), skip_length):
                updates[i] = n, item_hash
            
            if skip_length + 1 in updates:
                updates[skip_length + 1] = self.combine(updates[skip_length + 1], updates[skip_length])
            
            for delta, jump in reversed(skip):
                sol_if = self.combine(sol, delta)
                decision = self.judge(sol_if)
                if decision == 0:
                    return sol_if
                elif decision < 0:
                    break
            else:
                raise AssertionError()
        
        return item_hash

class DistanceSkipList(SkipList):
    def combine(self, a, b):
        return a + b
    
    def base(self, element):
        return 1, self.tracker.shares[element].previous_hash

class WeightsList(SkipList):
    # share_count, weights, total_weight
    def combine(self, (ac, a, at), (bc, b, bt)):
        return ac + bc, dict((k, a.get(k, 0) + b.get(k, 0)) for k in set(a.keys() + b.keys())), at + bt
    
    def base(self, element):
        share = self.tracker.shares[element]
        att = target_to_average_attempts(share.target2)
        return (1, {share.new_script: att}, att), self.tracker.shares[element].previous_hash
    
    def judge(self, (share_count, weights, total_weight), max_shares, desired_weight):
        if share_count > max_shares:
            return 1
