from p2pool.util import skiplist

class NotSkipList(object):
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
    
    def finalize(self, sol):
        return sol

skiplist.SkipList
