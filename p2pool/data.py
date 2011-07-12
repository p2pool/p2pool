from __future__ import division

import itertools
import traceback

from p2pool.util import math
from p2pool.bitcoin import data as bitcoin_data

class CompressedList(bitcoin_data.Type):
    def __init__(self, inner):
        self.inner = inner
    
    def read(self, file):
        values = bitcoin_data.ListType(self.inner).read(file)
        if values != sorted(set(values)):
            raise ValueError("invalid values")
        references = bitcoin_data.ListType(bitcoin_data.VarIntType()).read(file)
        return [values[reference] for reference in references]
    
    def write(self, file, item):
        values = sorted(set(item))
        values_map = dict((value, i) for i, value in enumerate(values))
        bitcoin_data.ListType(self.inner).write(file, values)
        bitcoin_data.ListType(bitcoin_data.VarIntType()).write(file, [values_map[subitem] for subitem in item])


merkle_branch_type = bitcoin_data.ListType(bitcoin_data.ComposedType([
    ('side', bitcoin_data.StructType('<B')), # enum?
    ('hash', bitcoin_data.HashType()),
]))


share_data_type = bitcoin_data.ComposedType([
    ('previous_share_hash', bitcoin_data.PossiblyNone(0, bitcoin_data.HashType())),
    ('previous_shares_hash', bitcoin_data.HashType()),
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
    ('header', bitcoin_data.block_header_type), # merkle_header not completely needed
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
        
        self.header = header
        self.share_info = share_info
        self.merkle_branch = merkle_branch
        self.other_txs = other_txs
        
        self.timestamp = self.header['timestamp']
        
        self.share_data = self.share_info['share_data']
        self.new_script = self.share_info['new_script']
        self.subsidy = self.share_info['subsidy']
        
        self.previous_share_hash = self.share_data['previous_share_hash']
        self.previous_shares_hash = self.share_data['previous_shares_hash']
        self.target2 = self.share_data['target2']
        
        self.hash = bitcoin_data.block_header_type.hash256(header)
        
        if self.hash > self.target2:
            print "hash", hex(self.hash)
            print "targ", hex(self.target2)
            raise ValueError('not enough work!')
        
        
        self.shared = False
    
    def as_block(self):
        if self.txs is None:
            raise ValueError('share does not contain all txs')
        
        return dict(header=self.header, txs=self.txs)
    
    def as_share1a(self):
        return dict(header=self.header, share_info=self.share_info, merkle_branch=self.merkle_branch)
    
    def as_share1b(self):
        return dict(header=self.header, share_info=self.share_info, other_txs=self.other_txs)
    
    def check(self, tracker, net):
        gentx = share_info_to_gentx(self.share_info, self.header['target'], tracker, net)
        
        if self.merkle_branch is not None:
            if check_merkle_branch(gentx, self.merkle_branch) != self.header['merkle_root']:
                raise ValueError("gentx doesn't match header via merkle_branch")
        
        if self.other_txs is not None:
            if bitcoin_data.merkle_hash([gentx] + self.other_txs) != self.header['merkle_root']:
                raise ValueError("gentx doesn't match header via other_txs")
        
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
    previous_share2 = tracker.shares[previous_share_hash] if previous_share_hash is not None else None
    #previous_share2 = chain.shares
    #previous_shares
    #shares = 
    #shares = (previous_share2.shares if previous_share2 is not None else [net.SCRIPT]*net.SPREAD)[1:-1] + [new_script, new_script]
    
    lookbehind = 120
    chain = list(itertools.islice(tracker.get_chain_to_root(previous_share_hash), lookbehind))
    if len(chain) < lookbehind:
        target2 = bitcoin_data.FloatingIntegerType().truncate_to(2**256//2**16 - 1)
    else:
        attempts = sum(bitcoin_data.target_to_average_attempts(share.target2) for share in chain)
        time = chain[0].timestamp - chain[-1].timestamp
        if time == 0:
            time = 1
        attempts_per_second = attempts//time
        pre_target = 2**256//(net.SHARE_PERIOD*attempts_per_second) - 1
        pre_target2 = math.clip(pre_target, (previous_share2.target2*9//10, previous_share2.target2*11//10))
        pre_target3 = math.clip(pre_target2, (0, 2**256//2**16 - 1))
        target2 = bitcoin_data.FloatingIntegerType().truncate_to(pre_target3)
        print attempts_per_second//1000, "KHASH"
        print "TARGET", 2**256//target2, 2**256/pre_target
        print "ATT", bitcoin_data.target_to_average_attempts(target2)//1000
    
    
    attempts_to_block = bitcoin_data.target_to_average_attempts(block_target)
    max_weight = net.SPREAD * attempts_to_block
    total_weight = 0
    
    class fake_share(object):
        script = new_script
        share = dict(target=target2)
    
    dest_weights = {}
    for i, share in enumerate(itertools.chain([fake_share], itertools.islice(tracker.get_chain_to_root(previous_share_hash), net.CHAIN_LENGTH))):
        weight = bitcoin_data.target_to_average_attempts(share.share['target'])
        weight = max(weight, max_weight - total_weight)
        
        dest_weights[share.script] = dest_weights.get(share.script, 0) + weight
        total_weight += weight
        
        if total_weight == max_weight:
            break
    
    amounts = dict((script, subsidy*(199*weight)//(200*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy*1//200
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    
    dests = sorted(amounts.iterkeys(), key=lambda script: (script == new_script, script))
    assert dests[-1] == new_script
    
    previous_shares = [] # XXX
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=None,
            sequence=None,
            script=coinbase_type.pack(dict(
                identifier=net.IDENTIFIER,
                share_data=dict(
                    previous_share_hash=previous_share_hash,
                    previous_shares_hash=shares_type.hash256(previous_shares),
                    nonce=nonce,
                    target2=target2,
                ),
            )),
        )],
        tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script]],
        lock_time=0,
    )


class Tracker(object):
    def __init__(self):        
        self.shares = {} # hash -> share
        self.reverse_shares = {} # previous_share_hash -> set of share_hashes
        
        self.heads = {} # head hash -> tail_hash
        self.tails = {} # tail hash -> set of head hashes
        self.heights = {} # share_hash -> height_to, other_share_hash
    
    def add_share(self, share):
        if share.hash in self.shares:
            return # XXX raise exception?
        
        self.shares[share.hash] = share
        self.reverse_shares.setdefault(share.previous_share_hash, set()).add(share.hash)
        
        if share.hash in self.tails:
            heads = self.tails.pop(share.hash)
        else:
            heads = set([share.hash])
        
        if share.previous_share_hash in self.heads:
            tail = self.heads.pop(share.previous_share_hash)
        else:
            tail = share.previous_share_hash
        
        self.tails.setdefault(tail, set()).update(heads)
        if share.previous_share_hash in self.tails[tail]:
            self.tails[tail].remove(share.previous_share_hash)
        
        for head in heads:
            self.heads[head] = tail
    
    def get_height_and_last(self, share_hash):
        orig = share_hash
        height = 0
        updates = []
        while True:
            if share_hash is None or share_hash not in self.shares:
                break
            updates.append((share_hash, height))
            if share_hash in self.heights:
                height_inc, share_hash = self.heights[share_hash]
            else:
                height_inc, share_hash = 1, self.shares[share_hash].previous_share_hash
            height += height_inc
        for update_hash, height_then in updates:
            self.heights[update_hash] = height - height_then, share_hash
        assert (height, share_hash) == self.get_height_and_last2(orig), ((height, share_hash), self.get_height_and_last2(orig))
        return height, share_hash
    
    def get_height_and_last2(self, share_hash):
        height = 0
        while True:
            if share_hash not in self.shares:
                break
            share_hash = self.shares[share_hash].previous_share_hash
            height += 1
        return height, share_hash
    
    def get_chain_known(self, share_hash):
        while True:
            if share_hash not in self.shares:
                break
            yield share_hash
            share_hash = self.shares[share_hash].previous_share_hash
    
    def get_chain_to_root(self, start):
        share_hash_to_get = start
        while share_hash_to_get is not None:
            share = self.shares[share_hash_to_get]
            yield share
            share_hash_to_get = share.previous_share_hash
    
    
    def get_best_share_hash(self):
        return None
        return max(self.heads, key=self.score_chain)
    '''
    def score_chain(self, start):
        length = len(self.get_chain(start))
        
        score = 0
        for share in itertools.islice(self.get_chain(start), self.net.CHAIN_LENGTH):
            score += a
        
        return (min(length, 1000), score)
    '''

if __name__ == '__main__':
    class FakeShare(object):
        def __init__(self, hash, previous_share_hash):
            self.hash = hash
            self.previous_share_hash = previous_share_hash
    
    t = Tracker()
    
    t.add_share(FakeShare(1, 2))
    print t.heads, t.tails
    t.add_share(FakeShare(4, 0))
    print t.heads, t.tails
    t.add_share(FakeShare(3, 4))
    print t.heads, t.tails
    t.add_share(FakeShare(5, 0))
    print t.heads, t.tails
    t.add_share(FakeShare(0, 1))
    print t.heads, t.tails
    
    for share_hash in t.shares:
        print share_hash, t.get_height_and_last(share_hash)

class OkayTracker(Tracker):
    def __init__(self, net):
        Tracker.__init__(self)
        self.net = net
        self.verified = Tracker()
    """
        self.okay_cache = {} # hash -> height
    
    def is_okay(self, start, _height_after=0):
        '''
        Returns:
            {'result': 'okay', verified_height: ...} # if share has an okay parent or if share has CHAIN_LENGTH children and CHAIN_LENTH parents that it verified with
            {'result': 'needs_share', 'share_hash': ...} # if share doesn't have CHAIN_LENGTH parents
            #{'result': 'needs_share_shares', 'share_hash': ...} # if share has CHAIN_LENGTH children and needs its shares to 
            {'result': 'not_okay'} # if the share has a not okay parent or if the share has an okay parent and failed validation
        '''
        
        if start in self.okay_cache:
            return dict(result='okay', verified_height=self.okay_cache['start'])
        
        share = self.shares[start]
        if start not in self.shares:
            return dict(result='needs_share', share_hash=start)
        
        length = len
        to_end_rev = []
        for share in itertools.islice(self.get_chain(start), self.net.CHAIN_LENGTH):
            if share in self.okay_cache:
                return validate(share, to_end_rev[::-1])
            to_end_rev.append(share)
        # picking up last share from for loop, ew
        self.okay_cache.add(share)
        return validate(share, to_end_rev[::-1])
    """
    def think(self):
        desired = set()
        
        # for each overall head, attempt verification
        # if it fails, attempt on parent, and repeat
        # if no successful verification because of lack of parents, request parent
        for head in self.heads:
            head_height, last = self.get_height_and_last(head)
            if head_height < a and last is not None:
                # request more
            
            for share in itertools.islice(self.get_chain_known(head), None if last is None else head_height - self.net.CHAIN_LENGTH): # XXX change length for None
                in share in self.verified.shares:
                    break
                try:
                    share.check(self, self.net)
                except:
                    print
                    print "Share check failed:"
                    traceback.print_exc()
                    print
                else:
                    self.verified.add_share(share_hash)
                    break
        
        # try to get at least CHAIN_LENGTH height for each verified head, requesting parents if needed
        for head in self.verified.heads:
            head_height, last = self.verified.get_height_and_last(head)
            a
        
        # decide best verified head
        def score(share_hash):
            share = self.verified.shares[share_hash]
            head_height, last = self.verified.get_height_and_last(share)
            return (min(head_height, net.CHAIN_LENGTH), RECENTNESS)
        best = max(self.verified.heads, key=score)
        
        return best, desired


class Mainnet(bitcoin_data.Mainnet):
    SHARE_PERIOD = 5 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    SPREAD = 3 # blocks
    SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')
    IDENTIFIER = '7452839666e1f8f8'.decode('hex')
    PREFIX = '2d4224bf18c87b87'.decode('hex')
    ADDRS_TABLE = 'addrs'
    P2P_PORT = 9333

class Testnet(bitcoin_data.Testnet):
    SHARE_PERIOD = 5 # seconds
    CHAIN_LENGTH = 24*60*60//5 # shares
    SPREAD = 3 # blocks
    SCRIPT = '410403ad3dee8ab3d8a9ce5dd2abfbe7364ccd9413df1d279bf1a207849310465b0956e5904b1155ecd17574778f9949589ebfd4fb33ce837c241474a225cf08d85dac'.decode('hex')
    IDENTIFIER = '1ae3479e4eb6700a'.decode('hex')
    PREFIX = 'd19778c812754854'.decode('hex')
    ADDRS_TABLE = 'addrs_testnet'
    P2P_PORT = 19333
