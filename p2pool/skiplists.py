from p2pool.util import math, skiplist

class WeightsSkipList(skiplist.SkipList):
    # share_count, weights, total_weight
    
    def __init__(self, tracker):
        skiplist.SkipList.__init__(self)
        self.tracker = tracker
    
    def previous(self, element):
        return self.tracker.shares[element].previous_hash
    
    def get_delta(self, element):
        from p2pool.bitcoin import data as bitcoin_data
        if element is None:
            return (2**256, {}, 0, 0) # XXX
        share = self.tracker.shares[element]
        att = bitcoin_data.target_to_average_attempts(share.target)
        return 1, {share.new_script: att*(65535-share.donation)}, att*65535, att*share.donation
    
    def combine_deltas(self, (share_count1, weights1, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2)):
        return share_count1 + share_count2, math.add_dicts([weights1, weights2]), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def initial_solution(self, start, (max_shares, desired_weight)):
        assert desired_weight % 65535 == 0, divmod(desired_weight, 65535)
        return 0, {}, 0, 0
    
    def apply_delta(self, (share_count1, weights1, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2), (max_shares, desired_weight)):
        if total_weight1 + total_weight2 > desired_weight and share_count2 == 1:
            script, = weights2.iterkeys()
            new_weights = dict(weights1)
            assert (desired_weight - total_weight1) % 65535 == 0
            new_weights[script] = new_weights.get(script, 0) + (desired_weight - total_weight1)//65535*weights2[script]//(total_weight2//65535)
            return share_count1 + share_count2, new_weights, desired_weight, total_donation_weight1 + (desired_weight - total_weight1)//65535*total_donation_weight2//(total_weight2//65535)
        return share_count1 + share_count2, math.add_dicts([weights1, weights2]), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def judge(self, (share_count, weights, total_weight, total_donation_weight), (max_shares, desired_weight)):
        if share_count > max_shares or total_weight > desired_weight:
            return 1
        elif share_count == max_shares or total_weight == desired_weight:
            return 0
        else:
            return -1
    
    def finalize(self, (share_count, weights, total_weight, total_donation_weight)):
        return weights, total_weight, total_donation_weight

class CountsSkipList(skiplist.SkipList):
    # share_count, counts, total_count
    
    def __init__(self, tracker, run_identifier):
        skiplist.SkipList.__init__(self)
        self.tracker = tracker
        self.run_identifier = run_identifier
    
    def previous(self, element):
        return self.tracker.shares[element].previous_hash
    
    def get_delta(self, element):
        if element is None:
            raise AssertionError()
        share = self.tracker.shares[element]
        return 1, set([share.hash]) if share.nonce.startswith(self.run_identifier) else set()
    
    def combine_deltas(self, (share_count1, share_hashes1), (share_count2, share_hashes2)):
        if share_hashes1 & share_hashes2:
            raise AssertionError()
        return share_count1 + share_count2, share_hashes1 | share_hashes2
    
    def initial_solution(self, start, (desired_shares,)):
        return 0, set()
    
    def apply_delta(self, (share_count1, share_hashes1), (share_count2, share_hashes2), (desired_shares,)):
        if share_hashes1 & share_hashes2:
            raise AssertionError()
        return share_count1 + share_count2, share_hashes1 | share_hashes2
    
    def judge(self, (share_count, share_hashes), (desired_shares,)):
        if share_count > desired_shares:
            return 1
        elif share_count == desired_shares:
            return 0
        else:
            return -1
    
    def finalize(self, (share_count, share_hashes)):
        return share_hashes
