from p2pool.util import math, memoize

class SkipList(object):
    def __init__(self, p=0.5):
        self.p = p
        
        self.skips = {}
    
    def forget_item(self, item):
        self.skips.pop(item, None)
    
    @memoize.memoize_with_backing(memoize.LRUDict(5))
    def __call__(self, start, *args):
        updates = {}
        pos = start
        sol = self.initial_solution(start, args)
        if self.judge(sol, args) == 0:
            return self.finalize(sol, args)
        while True:
            if pos not in self.skips:
                self.skips[pos] = math.geometric(self.p), [(self.previous(pos), self.get_delta(pos))]
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
                    return self.finalize(sol_if, args)
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
    
    def finalize(self, sol, args):
        return sol
