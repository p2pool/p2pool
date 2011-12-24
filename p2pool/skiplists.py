import operator

from p2pool.util import forest, math

class WeightsSkipList(forest.TrackerSkipList):
    # share_count, weights, total_weight
    
    def get_delta(self, element):
        from p2pool.bitcoin import data as bitcoin_data
        if element is None:
            return (2**256, {}, 0, 0) # XXX
        share = self.tracker.shares[element]
        att = bitcoin_data.target_to_average_attempts(share.target)
        return 1, {share.new_script: att*(65535-share.donation)}, att*65535, att*share.donation
    
    def combine_deltas(self, (share_count1, weights1, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2)):
        return share_count1 + share_count2, math.add_dicts(weights1, weights2), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def initial_solution(self, start, (max_shares, desired_weight)):
        assert desired_weight % 65535 == 0, divmod(desired_weight, 65535)
        return 0, None, 0, 0
    
    def apply_delta(self, (share_count1, weights_list, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2), (max_shares, desired_weight)):
        if total_weight1 + total_weight2 > desired_weight and share_count2 == 1:
            assert (desired_weight - total_weight1) % 65535 == 0
            script, = weights2.iterkeys()
            new_weights = dict(script=(desired_weight - total_weight1)//65535*weights2[script]//(total_weight2//65535))
            return share_count1 + share_count2, (weights_list, new_weights), desired_weight, total_donation_weight1 + (desired_weight - total_weight1)//65535*total_donation_weight2//(total_weight2//65535)
        return share_count1 + share_count2, (weights_list, weights2), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def judge(self, (share_count, weights_list, total_weight, total_donation_weight), (max_shares, desired_weight)):
        if share_count > max_shares or total_weight > desired_weight:
            return 1
        elif share_count == max_shares or total_weight == desired_weight:
            return 0
        else:
            return -1
    
    def finalize(self, (share_count, weights_list, total_weight, total_donation_weight), (max_shares, desired_weight)):
        assert share_count <= max_shares and total_weight <= desired_weight
        assert share_count == max_shares or total_weight == desired_weight
        return math.add_dicts(*math.flatten_linked_list(weights_list)), total_weight, total_donation_weight

class SumSkipList(forest.TrackerSkipList):
    def __init__(self, tracker, value_func, identity_value=0, add_func=operator.add):
        forest.TrackerSkipList.__init__(self, tracker)
        self.value_func = value_func
        self.identity_value = identity_value
        self.add_func = add_func
    
    
    def get_delta(self, element):
        return self.value_func(self.tracker.shares[element]), 1
    
    def combine_deltas(self, (result1, count1), (result2, count2)):
        return self.add_func(result1, result2), count1 + count2
    
    
    def initial_solution(self, start_hash, (desired_count,)):
        return self.identity_value, 0
    
    def apply_delta(self, (result, count), (d_result, d_count), (desired_count,)):
        return self.add_func(result, d_result), count + d_count
    
    def judge(self, (result, count), (desired_count,)):
        return cmp(count, desired_count)
    
    def finalize(self, (result, count), (desired_count,)):
        assert count == desired_count
        return result
