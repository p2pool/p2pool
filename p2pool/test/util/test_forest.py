import random
import unittest

from p2pool.util import forest

class FakeShare(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class Test(unittest.TestCase):
    def test_distanceskiplist(self):
        t = forest.Tracker()
        d = forest.DistanceSkipList(t)
        for i in xrange(2000):
            t.add(FakeShare(hash=i, previous_hash=i - 1 if i > 0 else None))
        for i in xrange(2000):
            a = random.randrange(2000)
            b = random.randrange(a + 1)
            res = d(a, b)
            assert res == a - b, (a, b, res)
    
    def test_tracker(self):
        t = forest.Tracker()

        for i in xrange(10000):
            t.add(FakeShare(hash=i, previous_hash=i - 1 if i > 0 else None))

        #t.remove(99)

        assert t.heads == {9999: None}
        assert t.tails == {None: set([9999])}

        #for share_hash, share in sorted(t.shares.iteritems()):
        #    print share_hash, share.previous_hash, t.heads.get(share_hash), t.tails.get(share_hash)

        assert t.get_nth_parent_hash(9000, 5000) == 9000 - 5000
        assert t.get_nth_parent_hash(9001, 412) == 9001 - 412
        #print t.get_nth_parent_hash(90, 51)

        for ii in xrange(5):
            t = forest.Tracker()
            for i in xrange(random.randrange(300)):
                x = random.choice(list(t.shares) + [None])
                #print i, '->', x
                t.add(FakeShare(hash=i, previous_hash=x, target=5))
            while t.shares:
                x = random.choice(list(t.shares))
                #print 'DEL', x, t.__dict__
                try:
                    t.remove(x)
                except NotImplementedError:
                    pass # print 'aborted; not implemented'
            #print 'HEADS', t.heads
            #print 'TAILS', t.tails

        #for share_hash in sorted(t.shares):
        #    print str(share_hash).rjust(4),
        #    x = t.skips.get(share_hash, None)
        #    if x is not None:
        #        print str(x[0]).rjust(4),
        #        for a in x[1]:
        #            print str(a).rjust(10),
        #    print
