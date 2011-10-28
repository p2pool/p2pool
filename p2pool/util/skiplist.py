from p2pool.util import math, expiring_dict, memoize

class Base(object):
    def finalize(self, sol):
        return sol

class SkipList(Base):
    P = .5
    
    def __init__(self):
        self.skips = expiring_dict.ExpiringDict(600)
    
    @memoize.memoize_with_backing(expiring_dict.ExpiringDict(5, get_touches=False))
    def __call__(self, start, *args, **kwargs):
        updates = {}
        pos = start
        sol = self.initial_solution(start, args)
        if self.judge(sol, args) == 0:
            return self.finalize(sol)
        while True:
            if pos not in self.skips:
                self.skips[pos] = math.geometric(self.P), [(self.previous(pos), self.get_delta(pos))]
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

class NotSkipList(Base):
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
