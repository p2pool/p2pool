from p2pool.util import math, expiring_dict

class Base(object):
    def finalize(self, sol):
        return sol

class SkipList(Base):
    def __init__(self):
        self.skips = expiring_dict.ExpiringDict(3600)
    
    def __call__(self, start, *args, **kwargs):
        updates = {}
        pos = start
        sol = self.initial_solution(start, args)
        if self.judge(sol, args) == 0:
            return self.finalize(sol)
        while True:
            if pos not in self.skips:
                self.skips[pos] = math.geometric(.5), [(self.previous(pos), self.get_delta(pos))]
            skip_length, skip = self.skips[pos]
            
            # fill previous updates
            for i in xrange(skip_length):
                if i in updates:
                    that_hash, delta = updates.pop(i)
                    x, y = self.skips[that_hash]
                    assert len(y) == i
                    y.append((pos, delta))
            
            # put desired skip nodes in updates
            for i in xrange(len(skip), skip_length):
                updates[i] = pos, None
            
            #if skip_length + 1 in updates:
            #    updates[skip_length + 1] = self.combine(updates[skip_length + 1], updates[skip_length])
            
            for jump, delta in reversed(skip):
                sol_if = self.apply_delta(sol, delta, args)
                decision = self.judge(sol_if, args)
                #print pos, sol, jump, delta, sol_if, decision
                if decision == 0:
                    return self.finalize(sol_if)
                elif decision < 0:
                    sol = sol_if
                    break
            else:
                raise AssertionError()
            
            sol = sol_if
            pos = jump
            
            # XXX could be better by combining updates
            for x in updates:
                updates[x] = updates[x][0], self.combine_deltas(updates[x][1], delta) if updates[x][1] is not None else delta
        
        
        return item_hash

class DumbSkipList(Base):
    def __call__(self, start, *args):
        pos = start
        sol = self.initial_solution(start, args)
        while True:
            decision = self.judge(sol, args)
            if decision > 0:
                raise AssertionError()
            elif decision == 0:
                return self.finalize(sol)
            
            delta = self.get_delta(pos)
            sol = self.apply_delta(sol, delta, args)
            
            pos = self.previous(pos)

class DistanceSkipList(SkipList):
    def __init__(self, tracker):
        SkipList.__init__(self)
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

class WeightsSkipList(SkipList):
    # share_count, weights, total_weight
    
    def __init__(self, tracker):
        SkipList.__init__(self)
        self.tracker = tracker
    
    def previous(self, element):
        return self.tracker.shares[element].previous_hash
    
    def get_delta(self, element):
        from p2pool.bitcoin import data as bitcoin_data
        if element is None:
            return (2**256, {}, 0) # XXX
        share = self.tracker.shares[element]
        att = bitcoin_data.target_to_average_attempts(share.target)
        return 1, {share.new_script: att}, att
    
    def combine_deltas(self, (share_count1, weights1, total_weight1), (share_count2, weights2, total_weight2)):
        return share_count1 + share_count2, math.add_dicts([weights1, weights2]), total_weight1 + total_weight2
    
    def initial_solution(self, start, (max_shares, desired_weight)):
        return 0, {}, 0
    
    def apply_delta(self, (share_count1, weights1, total_weight1), (share_count2, weights2, total_weight2), (max_shares, desired_weight)):
        if total_weight1 + total_weight2 > desired_weight and len(weights2) == 1:
            script, = weights2.iterkeys()
            new_weights = dict(weights1)
            new_weights[script] = new_weights.get(script, 0) + desired_weight - total_weight1
            return share_count1 + share_count2, new_weights, desired_weight
        return share_count1 + share_count2, math.add_dicts([weights1, weights2]), total_weight1 + total_weight2
    
    def judge(self, (share_count, weights, total_weight), (max_shares, desired_weight)):
        if share_count > max_shares or total_weight > desired_weight:
            return 1
        elif share_count == max_shares or total_weight == desired_weight:
            return 0
        else:
            return -1
    
    def finalize(self, (share_count, weights, total_weight)):
        return weights, total_weight

class CountsSkipList(SkipList):
    # share_count, counts, total_count
    
    def __init__(self, tracker, script, run_identifier):
        SkipList.__init__(self)
        self.tracker = tracker
        self.script = script
        self.run_identifier = run_identifier
    
    def previous(self, element):
        return self.tracker.shares[element].previous_hash
    
    def get_delta(self, element):
        from p2pool.bitcoin import data as bitcoin_data
        if element is None:
            return 0 # XXX
        share = self.tracker.shares[element]
        weight = 1 if share.new_script == self.script and share.nonce[:8] == self.run_identifier else 0
        return 1, weight, 1
    
    def combine_deltas(self, (share_count1, weights1, total_weight1), (share_count2, weights2, total_weight2)):
        return share_count1 + share_count2, weights1 + weights2, total_weight1 + total_weight2
    
    def initial_solution(self, start, (max_shares, desired_weight)):
        return 0, 0, 0
    
    
    def apply_delta(self, (share_count1, weights1, total_weight1), (share_count2, weights2, total_weight2), (max_shares, desired_weight)):
        return share_count1 + share_count2, weights1 + weights2, total_weight1 + total_weight2
    
    def judge(self, (share_count, weights, total_weight), (max_shares, desired_weight)):
        if share_count > max_shares or total_weight > desired_weight:
            return 1
        elif share_count == max_shares or total_weight == desired_weight:
            return 0
        else:
            return -1
    
    def finalize(self, (share_count, weights, total_weight)):
        if share_count != total_weight:
            raise AssertionError()
        return weights

if __name__ == '__main__':
    import random
    from p2pool.bitcoin import data
    t = data.Tracker()
    d = WeightsSkipList(t)
    for i in xrange(2000):
        t.add(data.FakeShare(hash=i, previous_hash=i - 1 if i > 0 else None, new_script=i, target=random.randrange(2**249, 2**250)))
    for i in xrange(2000):
        #a = random.randrange(2000)
        a = 1999
        print d(a, a, 1000000)[1]
