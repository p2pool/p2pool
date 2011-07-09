from __future__ import division

import itertools

from bitcoin import data as bitcoin_data

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
    ('identifier', bitcoin_data.StructType('<Q')),
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

def share_info_to_gentx(share_info, chain, net):
    return generate_transaction(
        previous_share2=chain.share2s[share_info['share_data']['previous_share_hash']],
        nonce=share_info['share_data']['nonce'],
        new_script=share_info['new_script'],
        subsidy=share_info['subsidy'],
        net=net,
    )

class Share(object):
    def __init__(self, header, share_info, merkle_branch=None, other_txs=None):
        if merkle_branch is None and other_txs is None:
            raise ValueError('need either merkle_branch or other_txs')
        self.header = header
        self.share_info = share_info
        self.merkle_branch = merkle_branch
        self.other_txs = other_txs
        
        self.share_data = self.share_info['share_data']
        self.new_script = self.share_info['new_script']
        self.subsidy = self.share_info['subsidy']
        
        self.previous_share_hash = self.share_data['previous_share_hash']
        self.previous_shares_hash = self.share_data['previous_shares_hash']
        self.target2 = self.share_data['target2']
        
        self.hash = bitcoin_data.block_header_type.hash256(header)
    
    @classmethod
    def from_block(cls, block):
        return cls(block['header'], gentx_to_share_info(block['txs'][0]), other_txs=block['txs'][1:])
    
    @classmethod
    def from_share1a(cls, share1a):
        return cls(**share1a)
    
    @classmethod
    def from_share1b(cls, share1b):
        return cls(**share1b)
    
    def as_block(self):
        if self.txs is None:
            raise ValueError('share does not contain all txs')
        
        return dict(header=self.header, txs=self.txs)
    
    def as_share1(self):
        return dict(header=self.header, gentx_info=self.gentx_info)
    
    def check(self, chain, height, previous_share2, net):
        if self.chain_id_data != chain.chain_id_data:
            raise ValueError('wrong chain')
        
        if self.hash > net.TARGET_MULTIPLIER*bitcoin_data.bits_to_target(self.header['bits']):
            raise ValueError('not enough work!')
        
        gentx, shares, merkle_root = gentx_info_to_gentx_shares_and_merkle_root(self.gentx_info, chain, net)
        
        if merkle_root != self.header['merkle_root']:
            raise ValueError("gentx doesn't match header")
        
        return Share2(self, shares, height)

class Share2(object):
    '''Share with associated data'''
    
    def __init__(self, share, shares, height):
        self.share = share
        self.shares = shares
        self.height = height
        
        self.shared = False
    
    def flag_shared(self):
        self.shared = True

def generate_transaction(tracker, previous_share_hash, new_script, subsidy, nonce, block_target, net):
    previous_share2 = tracker.shares[previous_share_hash] if previous_share_hash is not None else None
    #previous_share2 = chain.shares
    #previous_shares
    #shares = 
    #shares = (previous_share2.shares if previous_share2 is not None else [net.SCRIPT]*net.SPREAD)[1:-1] + [new_script, new_script]
    
    chain = list(itertools.islice(tracker.get_chain(previous_share_hash), net.CHAIN_LENGTH))
    if len(chain) < 100:
        target2 = bitcoin_data.FloatingIntegerType().truncate_to(2**256//2**32 - 1)
    else:
        attempts_per_second = sum(bitcoin_data.target_to_average_attempts(share.target) for share in itertools.islice(chain, 0, max(0, len(chain) - 1)))//(chain[0].timestamp - chain[-1].timestamp)
        pre_target = 2**256*net.SHARE_PERIOD//attempts_per_second
        pre_target2 = math.clip(pre_target, (previous_share2.target*9//10, previous_share2.target*11//10))
        pre_target3 = math.clip(pre_target2, (0, 2**256//2**32 - 1))
        target2 = bitcoin_data.FloatingIntegerType().truncate_to(pre_target3)
    
    
    attempts_to_block = bitcoin_data.target_to_average_attempts(block_target)
    total_weight = 0
    
    class fake_share(object):
        script = new_script
        share = dict(target=target2)
    
    dest_weights = {}
    for share in itertools.chain([fake_share], itertools.islice(tracker.get_chain(previous_share_hash), net.CHAIN_LENGTH)):
        weight = bitcoin_data.target_to_average_attempts(share.share['target'])
        weight = max(weight, attempts_to_block - total_weight)
        
        dest_weights[share.script] = dest_weights.get(share.script, 0) + weight
        total_weight += weight
        
        if total_weight == attempts_to_block:
            break
    
    amounts = dict((script, subsidy*(199*weight)//(200*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy*1//200 # prevent fake previous p2pool blocks
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    
    dests = sorted(amounts.iterkeys(), key=lambda script: (script == new_script, script))
    assert dests[-1] == new_script, dests
    
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
        self.reverse_shares = {} # previous_share_hash -> share_hash
        self.heads = {} # hash -> (height, tail hash)
        self.heads = set()
    
    def add_share(self, share):
        if share.hash in self.shares:
            return # XXX raise exception?
        
        self.shares[share.hash] = share
        self.reverse_shares.setdefault(share.previous_share_hash, set()).add(share.hash)
        
        if self.reverse_shares.get(share.hash, set()):
            pass # not a head
        else:
            self.heads.add(share.hash)
            if share.previous_share_hash in self.heads:
                self.heads.remove(share.previous_share_hash)
    
    def get_chain(self, start):
        share_hash_to_get = start
        while share_hash_to_get in self.shares:
            share = self.shares[share_hash_to_get]
            yield share
            share_hash_to_get = share.previous_share_hash
    
    def get_best_share_hash(self):
        if not self.heads:
            return None
        return max(self.heads, key=self.score_chain)
    
    def score_chain(self, start):
        length = len(self.get_chain(start))
        
        score = 0
        for share in itertools.islice(self.get_chain(start), self.net.CHAIN_LENGTH):
            score += a
        
        return (min(length, 1000), score)

class OkayTracker(Tracker):
    def __init__(self):
        Tracker.__init__(self)
        self.okay_cache = set()
    def is_okay(self, start):
        '''
        Returns:
            {'result': 'okay', verified_height: ...} # if share has an okay parent or if share has CHAIN_LENGTH children and CHAIN_LENTH parents that it verified with
            {'result': 'needs_parent', 'parent_hash': ...} # if share doesn't have CHAIN_LENGTH parents
            {'result': 'needs_share_shares', 'share_hash': ...} # if share has CHAIN_LENGTH children and needs its shares to 
            {'result': 'not_okay'} # if the share has a not okay parent or if the share has an okay parent and failed validation
        '''
        
        length = len
        to_end_rev = []
        for share in itertools.islice(self.get_chain(start), self.net.CHAIN_LENGTH):
            if share in self.okay_cache:
                return validate(share, to_end_rev[::-1])
            to_end_rev.append(share)
        # picking up last share from for loop, ew
        self.okay_cache.add(share)
        return validate(share, to_end_rev[::-1])
class Chain(object):
    def __init__(self):
        pass

def get_chain_descriptor(tracker, start):
    for item in tracker.get_chain(self.net.CHAIN_LENGTH):
        a
    pass

if __name__ == '__main__':
    class FakeShare(object):
        def __init__(self, hash, previous_share_hash):
            self.hash = hash
            self.previous_share_hash = previous_share_hash
    
    t = Tracker()
    
    t.add_share(FakeShare(1, 2))
    print t.heads
    t.add_share(FakeShare(4, 0))
    print t.heads
    t.add_share(FakeShare(3, 4))
    print t.heads

class Mainnet(bitcoin_data.Mainnet):
    SHARE_PERIOD = 5 # seconds
    CHAIN_LENGTH = 1000 # shares
    SPREAD = 10 # blocks
    ROOT_BLOCK = 0x6c9cb0589a44808d9a9361266a4ffb9fea2e2cf4d70bb2118b5
    SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')
    IDENTIFIER = 0x7452839666e1f8f8
    PREFIX = '2d4224bf18c87b87'.decode('hex')
    ADDRS_TABLE = 'addrs'
    P2P_PORT = 9333

class Testnet(bitcoin_data.Testnet):
    SHARE_PERIOD = 5 # seconds
    CHAIN_LENGTH = 1000 # shares
    SPREAD = 10 # blocks
    ROOT_BLOCK = 0xd5070cd4f2987ad2191af71393731a2b143f094f7b84c9e6aa9a6a
    SCRIPT = '410403ad3dee8ab3d8a9ce5dd2abfbe7364ccd9413df1d279bf1a207849310465b0956e5904b1155ecd17574778f9949589ebfd4fb33ce837c241474a225cf08d85dac'.decode('hex')
    IDENTIFIER = 0x1ae3479e4eb6700a
    PREFIX = 'd19778c812754854'.decode('hex')
    ADDRS_TABLE = 'addrs_testnet'
    P2P_PORT = 19333
