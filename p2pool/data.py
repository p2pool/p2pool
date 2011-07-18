from __future__ import division

import itertools
import random
import time

from twisted.python import log

from p2pool.bitcoin import data as bitcoin_data
from p2pool.util import memoize, expiring_dict, math, skiplist

class CompressedList(bitcoin_data.Type):
    def __init__(self, inner):
        self.inner = inner
    
    def read(self, file):
        values, file = bitcoin_data.ListType(self.inner).read(file)
        if values != sorted(set(values)):
            raise ValueError('invalid values')
        references, file = bitcoin_data.ListType(bitcoin_data.VarIntType()).read(file)
        return [values[reference] for reference in references], file
    
    def write(self, file, item):
        values = sorted(set(item))
        values_map = dict((value, i) for i, value in enumerate(values))
        file = bitcoin_data.ListType(self.inner).write(file, values)
        return bitcoin_data.ListType(bitcoin_data.VarIntType()).write(file, [values_map[subitem] for subitem in item])


merkle_branch_type = bitcoin_data.ListType(bitcoin_data.ComposedType([
    ('side', bitcoin_data.StructType('<B')), # enum?
    ('hash', bitcoin_data.HashType()),
]))


share_data_type = bitcoin_data.ComposedType([
    ('previous_share_hash', bitcoin_data.PossiblyNone(0, bitcoin_data.HashType())),
    ('target2', bitcoin_data.FloatingIntegerType()),
    ('nonce', bitcoin_data.VarStrType()),
])


coinbase_type = bitcoin_data.ComposedType([
    ('identifier', bitcoin_data.FixedStrType(8)),
    ('share_data', share_data_type),
])

share_info_type = bitcoin_data.ComposedType([
    ('share_data', share_data_type),
    ('new_script', bitcoin_data.VarStrType()),
    ('subsidy', bitcoin_data.StructType('<Q')),
])


share1a_type = bitcoin_data.ComposedType([
    ('header', bitcoin_data.block_header_type),
    ('share_info', share_info_type),
    ('merkle_branch', merkle_branch_type),
])

share1b_type = bitcoin_data.ComposedType([
    ('header', bitcoin_data.block_header_type),
    ('share_info', share_info_type),
    ('other_txs', bitcoin_data.ListType(bitcoin_data.tx_type)),
])

shares_type = CompressedList(bitcoin_data.VarStrType())

def calculate_merkle_branch(txs, index):
    hash_list = [(bitcoin_data.tx_type.hash256(tx), i == index, []) for i, tx in enumerate(txs)]
    
    while len(hash_list) > 1:
        hash_list = [
            (
                bitcoin_data.merkle_record_type.hash256(dict(left=left, right=right)),
                left_f or right_f,
                (left_l if left_f else right_l) + [dict(side=1, hash=right) if left_f else dict(side=0, hash=left)],
            )
            for (left, left_f, left_l), (right, right_f, right_l) in
                zip(hash_list[::2], hash_list[1::2] + [hash_list[::2][-1]])
        ]
    
    assert hash_list[0][1]
    assert check_merkle_branch(txs[index], hash_list[0][2]) == hash_list[0][0]
    
    return hash_list[0][2]

def check_merkle_branch(tx, branch):
    hash_ = bitcoin_data.tx_type.hash256(tx)
    for step in branch:
        if not step['side']:
            hash_ = bitcoin_data.merkle_record_type.hash256(dict(left=step['hash'], right=hash_))
        else:
            hash_ = bitcoin_data.merkle_record_type.hash256(dict(left=hash_, right=step['hash']))
    return hash_

def gentx_to_share_info(gentx):
    return dict(
        share_data=coinbase_type.unpack(gentx['tx_ins'][0]['script'])['share_data'],
        subsidy=sum(tx_out['value'] for tx_out in gentx['tx_outs']),
        new_script=gentx['tx_outs'][-1]['script'],
    )

def share_info_to_gentx(share_info, block_target, tracker, net):
    return generate_transaction(
        tracker=tracker,
        previous_share_hash=share_info['share_data']['previous_share_hash'],
        new_script=share_info['new_script'],
        subsidy=share_info['subsidy'],
        nonce=share_info['share_data']['nonce'],
        block_target=block_target,
        net=net,
    )

class Share(object):
    peer = None
    gentx = None
    
    @classmethod
    def from_block(cls, block):
        return cls(block['header'], gentx_to_share_info(block['txs'][0]), other_txs=block['txs'][1:])
    
    @classmethod
    def from_share1a(cls, share1a):
        return cls(**share1a)
    
    @classmethod
    def from_share1b(cls, share1b):
        return cls(**share1b)
    
    def __init__(self, header, share_info, merkle_branch=None, other_txs=None):
        if merkle_branch is None and other_txs is None:
            raise ValueError('need either merkle_branch or other_txs')
        if other_txs is not None:
            new_merkle_branch = calculate_merkle_branch([dict(version=0, tx_ins=[], tx_outs=[], lock_time=0)] + other_txs, 0)
            if merkle_branch is not None:
                if merke_branch != new_merkle_branch:
                    raise ValueError('invalid merkle_branch and other_txs')
            merkle_branch = new_merkle_branch
        
        if len(merkle_branch) > 16:
            raise ValueError('merkle_branch too long!')
        
        self.header = header
        self.share_info = share_info
        self.merkle_branch = merkle_branch
        self.other_txs = other_txs
        
        self.timestamp = self.header['timestamp']
        
        self.share_data = self.share_info['share_data']
        self.new_script = self.share_info['new_script']
        self.subsidy = self.share_info['subsidy']
        
        if len(self.new_script) > 100:
            raise ValueError('new_script too long!')
        
        self.previous_hash = self.previous_share_hash = self.share_data['previous_share_hash']
        self.target2 = self.share_data['target2']
        self.nonce = self.share_data['nonce']
        
        if len(self.nonce) > 20:
            raise ValueError('nonce too long!')
        
        self.hash = bitcoin_data.block_header_type.hash256(header)
        
        if self.hash > self.target2:
            print 'hash', hex(self.hash)
            print 'targ', hex(self.target2)
            raise ValueError('not enough work!')
        
        
        self.time_seen = time.time()
        self.shared = False
    
    def as_block(self):
        if self.other_txs is None:
            raise ValueError('share does not contain all txs')
        
        return dict(header=self.header, txs=[self.gentx] + self.other_txs)
    
    def as_share1a(self):
        return dict(header=self.header, share_info=self.share_info, merkle_branch=self.merkle_branch)
    
    def as_share1b(self):
        return dict(header=self.header, share_info=self.share_info, other_txs=self.other_txs)
    
    def check(self, tracker, now, net):
        import time
        if self.previous_share_hash is not None:
            if self.header['timestamp'] <= math.median((s.timestamp for s in itertools.islice(tracker.get_chain_to_root(self.previous_share_hash), 11)), use_float=False):
                raise ValueError('share from too far in the past!')
        
        if self.header['timestamp'] > now + 2*60*60:
            raise ValueError('share from too far in the future!')
        
        gentx = share_info_to_gentx(self.share_info, self.header['target'], tracker, net)
        
        if check_merkle_branch(gentx, self.merkle_branch) != self.header['merkle_root']:
            raise ValueError('''gentx doesn't match header via merkle_branch''')
        
        if self.other_txs is not None:
            if bitcoin_data.merkle_hash([gentx] + self.other_txs) != self.header['merkle_root']:
                raise ValueError('''gentx doesn't match header via other_txs''')
        
        self.gentx = gentx
        
        return Share2(self)
    
    def flag_shared(self):
        self.shared = True
    
    def __repr__(self):
        return '<Share %s>' % (' '.join('%s=%r' % (k, v) for k, v in self.__dict__.iteritems()),)

class Share2(object):
    '''Share with associated data'''
    
    def __init__(self, share):
        self.share = share
        
        self.shared = False
    
    def flag_shared(self):
        self.shared = True

def generate_transaction(tracker, previous_share_hash, new_script, subsidy, nonce, block_target, net):    
    chain = list(itertools.islice(tracker.get_chain_to_root(previous_share_hash), net.TARGET_LOOKBEHIND))
    if len(chain) < net.TARGET_LOOKBEHIND:
        target2 = bitcoin_data.FloatingIntegerType().truncate_to(2**256//2**20 - 1)
    else:
        previous_share = tracker.shares[previous_share_hash] if previous_share_hash is not None else None
        attempts = sum(bitcoin_data.target_to_average_attempts(share.target2) for share in chain[:-1])
        time = chain[0].timestamp - chain[-1].timestamp
        if time == 0:
            time = 1
        attempts_per_second = attempts//time
        pre_target = 2**256//(net.SHARE_PERIOD*attempts_per_second) - 1
        pre_target2 = math.clip(pre_target, (previous_share.target2*9//10, previous_share.target2*11//10))
        pre_target3 = math.clip(pre_target2, (0, 2**256//2**20 - 1))
        target2 = bitcoin_data.FloatingIntegerType().truncate_to(pre_target3)
        print attempts_per_second//1000, 'KHASH'
        #print 'TARGET', 2**256//target2, 2**256/pre_target
        #print 'ATT', bitcoin_data.target_to_average_attempts(target2)//1000
    
    
    attempts_to_block = bitcoin_data.target_to_average_attempts(block_target)
    max_weight = net.SPREAD * attempts_to_block
    
    '''
    class fake_share(object):
        pass
    fake_share.new_script = new_script
    fake_share.target2 = target2
    
    dest_weights = {}
    total_weight = 0
    for share in itertools.chain([fake_share], itertools.islice(tracker.get_chain_to_root(previous_share_hash), net.CHAIN_LENGTH)):
        weight = bitcoin_data.target_to_average_attempts(share.target2)
        if weight > max_weight - total_weight:
            weight = max_weight - total_weight
        
        dest_weights[share.new_script] = dest_weights.get(share.new_script, 0) + weight
        total_weight += weight
        
        if total_weight == max_weight:
            break
    '''
    
    this_weight = min(bitcoin_data.target_to_average_attempts(target2), max_weight)
    dest_weights = math.add_dicts([{new_script: this_weight}, tracker.get_cumulative_weights(previous_share_hash, min(tracker.get_height_and_last(previous_share_hash)[0], net.CHAIN_LENGTH), max(0, max_weight - this_weight))[0]])
    total_weight = sum(dest_weights.itervalues())
    #assert dest_weights == dest_weights2
    
    amounts = dict((script, subsidy*(199*weight)//(200*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy*1//200
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    
    dests = sorted(amounts.iterkeys(), key=lambda script: (script == new_script, script))
    assert dests[-1] == new_script
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=None,
            sequence=None,
            script=coinbase_type.pack(dict(
                identifier=net.IDENTIFIER,
                share_data=dict(
                    previous_share_hash=previous_share_hash,
                    nonce=nonce,
                    target2=target2,
                ),
            )),
        )],
        tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script]],
        lock_time=0,
    )



class OkayTracker(bitcoin_data.Tracker):
    def __init__(self, net):
        bitcoin_data.Tracker.__init__(self)
        self.net = net
        self.verified = bitcoin_data.Tracker()
        
        self.get_cumulative_weights = skiplist.WeightsSkipList(self)
    
    def attempt_verify(self, share, now):
        if share.hash in self.verified.shares:
            return True
        height, last = self.get_height_and_last(share.hash)
        if height < self.net.CHAIN_LENGTH and last is not None:
            raise AssertionError()
        try:
            share.check(self, now, self.net)
        except:
            print
            print 'Share check failed:'
            log.err()
            print
            return False
        else:
            self.verified.add(share)
            return True
    
    def think(self, ht, now):
        desired = set()
        
        # O(len(self.heads))
        #   make 'unverified heads' set?
        # for each overall head, attempt verification
        # if it fails, attempt on parent, and repeat
        # if no successful verification because of lack of parents, request parent
        for head in self.heads:
            head_height, last = self.get_height_and_last(head)
            
            for share in itertools.islice(self.get_chain_known(head), None if last is None else max(0, head_height - self.net.CHAIN_LENGTH)):
                if self.attempt_verify(share, now):
                    break
            else:
                desired.add((self.shares[random.choice(list(self.reverse_shares[last]))].peer, last))
        
        # try to get at least CHAIN_LENGTH height for each verified head, requesting parents if needed
        for head in list(self.verified.heads):
            head_height, last_hash = self.verified.get_height_and_last(head)
            last_height, last_last_hash = self.get_height_and_last(last_hash)
            # XXX review boundary conditions
            want = max(self.net.CHAIN_LENGTH - head_height, 0)
            can = max(last_height - 1 - self.net.CHAIN_LENGTH, 0) if last_last_hash is not None else last_height
            get = min(want, can)
            #print 'Z', head_height, last_hash is None, last_height, last_last_hash is None, want, can, get
            for share in itertools.islice(self.get_chain_known(last_hash), get):
                if not self.attempt_verify(share, now):
                    break
            if head_height < self.net.CHAIN_LENGTH and last_last_hash is not None:
                desired.add((self.verified.shares[random.choice(list(self.verified.reverse_shares[last_hash]))].peer, last_last_hash))
        
        # decide best verified head
        scores = sorted(self.verified.heads, key=lambda h: self.score(h, ht))
        
        print "---"
        for a in scores:
            print time.time()
            print '%x'%a, self.score(a, ht)
        print "---"
        
        for share_hash in scores[:-5]:
            if self.shares[share_hash].time_seen > time.time() - 30:
                continue
            self.remove(share_hash)
            self.verified.remove(share_hash)
        
        best = scores[-1] if scores else None
        
        return best, desired
    
    @memoize.memoize_with_backing(expiring_dict.ExpiringDict(5, get_touches=False))
    def score(self, share_hash, ht):
        head_height, last = self.verified.get_height_and_last(share_hash)
        score2 = 0
        attempts = 0
        max_height = 0
        # XXX should only look past a certain share, not at recent ones
        share2_hash = self.verified.get_nth_parent_hash(share_hash, min(self.net.CHAIN_LENGTH//2, head_height//2)) if last is not None else share_hash
        # XXX this must go in the opposite direction for max_height to make sense
        for share in reversed(list(itertools.islice(self.verified.get_chain_known(share2_hash), self.net.CHAIN_LENGTH))):
            max_height = max(max_height, ht.get_min_height(share.header['previous_block']))
            attempts += bitcoin_data.target_to_average_attempts(share.target2)
            this_score = attempts//(ht.get_highest_height() - max_height + 1)
            #this_score = -(ht.get_highest_height() - max_height + 1)//attempts
            if this_score > score2:
                score2 = this_score
        res = (min(head_height, self.net.CHAIN_LENGTH), score2, -self.verified.shares[share_hash].time_seen)
        #print res
        return res


class Mainnet(bitcoin_data.Mainnet):
    SHARE_PERIOD = 5 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')
    IDENTIFIER = '7452839666e1f8f8'.decode('hex')
    PREFIX = '2d4224bf18c87b87'.decode('hex')
    ADDRS_TABLE = 'addrs'
    P2P_PORT = 9333

class Testnet(bitcoin_data.Testnet):
    SHARE_PERIOD = 1 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    TARGET_LOOKBEHIND = 200 # shares
    SPREAD = 3 # blocks
    SCRIPT = '410403ad3dee8ab3d8a9ce5dd2abfbe7364ccd9413df1d279bf1a207849310465b0956e5904b1155ecd17574778f9949589ebfd4fb33ce837c241474a225cf08d85dac'.decode('hex')
    IDENTIFIER = '1ae3479e4eb6700a'.decode('hex')
    PREFIX = 'd19778c812754854'.decode('hex')
    ADDRS_TABLE = 'addrs_testnet'
    P2P_PORT = 19333
