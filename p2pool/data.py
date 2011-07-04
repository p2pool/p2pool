from __future__ import division

from bitcoin import data as bitcoin_data

share_data_type = bitcoin_data.ComposedType([
    ('previous_p2pool_share_hash', bitcoin_data.HashType()),
    ('bits2', bitcoin_data.FixedStrType(4)),
    ('nonce', bitcoin_data.VarStrType()),
])

coinbase_type = bitcoin_data.ComposedType([
    ('identifier', bitcoin_data.StructType('<Q')),
    ('share_data', share_data_type),
])

merkle_branch_type = bitcoin_data.ListType(bitcoin_data.ComposedType([
    ('side', bitcoin_data.StructType('<B')),
    ('hash', bitcoin_data.HashType()),
]))

gentx_info_type = bitcoin_data.ComposedType([
    ('share_info', bitcoin_data.ComposedType([
        ('share_data', share_data_type),
        ('new_script', bitcoin_data.VarStrType()),
        ('subsidy', bitcoin_data.StructType('<Q')),
    ])),
    ('merkle_branch', merkle_branch_type),
])

share1_type = bitcoin_data.ComposedType([
    ('header', bitcoin_data.block_header_type),
    ('gentx_info', gentx_info_type),
])

def calculate_merkle_branch(txs, index):
    hash_list = [(bitcoin_data.tx_hash(tx), i == index, []) for i, tx in enumerate(txs)]
    
    while len(hash_list) > 1:
        hash_list = [
            (
                bitcoin_data.doublesha(bitcoin_data.merkle_record_type.pack(dict(left=left, right=right))),
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
    hash_ = bitcoin_data.tx_hash(tx)
    for step in branch:
        if not step['side']:
            hash_ = bitcoin_data.doublesha(bitcoin_data.merkle_record_type.pack(dict(left=step['hash'], right=hash_)))
        else:
            hash_ = bitcoin_data.doublesha(bitcoin_data.merkle_record_type.pack(dict(left=hash_, right=step['hash'])))
    return hash_

def txs_to_gentx_info(txs):
    return dict(
        share_info=dict(
            share_data=coinbase_type.unpack(txs[0]['tx_ins'][0]['script'])['share_data'],
            subsidy=sum(tx_out['value'] for tx_out in txs[0]['tx_outs']),
            new_script=txs[0]['tx_outs'][-1]['script'],
        ),
        merkle_branch=calculate_merkle_branch(txs, 0),
    )

def share_info_to_gentx_and_shares(share_info, chain, net):
    return generate_transaction(
        previous_share2=chain.share2s[share_info['share_data']['previous_p2pool_share_hash']],
        nonce=share_info['share_data']['nonce'],
        new_script=share_info['new_script'],
        subsidy=share_info['subsidy'],
        net=net,
    )

def gentx_info_to_gentx_shares_and_merkle_root(gentx_info, chain, net):
    gentx, shares = share_info_to_gentx_and_shares(gentx_info['share_info'], chain, net)
    return gentx, shares, check_merkle_branch(gentx, gentx_info['merkle_branch'])

class Share(object):
    def __init__(self, header, txs=None, gentx_info=None):
        if txs is not None:
            if bitcoin_data.merkle_hash(txs) != header['merkle_root']:
                raise ValueError("txs don't match header")
        
        if gentx_info is None:
            if txs is None:
                raise ValueError('need either txs or gentx_info')
            
            gentx_info = txs_to_gentx_info(txs)
        
        coinbase = gentx_info['share_info']['coinbase']
        
        self.header = header
        self.txs = txs
        self.gentx_info = gentx_info
        self.hash = bitcoin_data.block_hash(header)
        self.previous_share_hash = coinbase['previous_p2pool_share_hash'] if coinbase['previous_p2pool_share_hash'] != 2**256 - 1 else None
        self.chain_id_data = chain_id_type.pack(dict(last_p2pool_block_hash=coinbase['last_p2pool_block_hash'], bits=header['bits']))
    
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

def generate_transaction(last_p2pool_block_hash, previous_share2, new_script, subsidy, nonce, net):
    shares = (previous_share2.shares if previous_share2 is not None else [net.SCRIPT]*net.SPREAD)[1:-1] + [new_script, new_script]
    
    dest_weights = {}
    for script in shares:
        dest_weights[script] = dest_weights.get(script, 0) + 1
    total_weight = sum(dest_weights.itervalues())
    
    amounts = dict((script, subsidy*weight*63//(64*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy//64 # prevent fake previous p2pool blocks
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    
    dests = sorted(amounts.iterkeys(), key=lambda script: (script == new_script, script))
    assert dests[-1] == new_script
    
    pre_target = sum(bitcoin_data.target_to_average_attempts(share(x ago).target) for x in xrange(1000))/(share(1000 ago).timestamp - share(1 ago).timestamp)
    bits2 = bitcoin_data.compress_target_to_bits(pre_target)
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=dict(index=4294967295, hash=0),
            sequence=4294967295,
            script=coinbase_type.pack(dict(
                identifier=net.IDENTIFIER,
                share_data=dict(
                    last_p2pool_block_hash=last_p2pool_block_hash,
                    previous_p2pool_share_hash=previous_share2.share.hash if previous_share2 is not None else 2**256 - 1,
                    nonce=nonce,
                    bits2=bits2,
                ),
            )),
        )],
        tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script]],
        lock_time=0,
    ), shares


class Tracker(object):
    def __init__(self):
        self.shares = {} # hash -> share
        self.reverse_shares = {} # previous_hash -> share_hash
        self.heads = {} # hash -> (height, tail hash)
        self.heads = set()
    
    def add_share(self, share):
        if share.hash in self.shares:
            return # XXX
        
        self.shares[share.hash] = share
        self.reverse_shares.setdefault(share.previous_hash, set()).add(share.hash)
        
        if self.reverse_shares.get(share.hash, set()):
            pass # not a head
        else:
            self.heads.add(share.hash)
            if share.previous_hash in self.heads:
                self.heads.remove(share.previous_hash)
    
    def get_chain(self, start):
        share_hash_to_get = start
        while share_hash_to_get in self.shares:
            share = self.shares[share_hash_to_get]
            yield share
            share_hash_to_get = share.previous_hash
    
    def best(self):
        return max(self.heads, key=self.score_chain)
    
    def score_chain(self, start):
        length = len(self.get_chain(start))
        
        score = 0
        for share in itertools.islice(self.get_chain(start), 1000):
            score += a
        
        return (min(length, 1000), score)

if __name__ == '__main__':
    class FakeShare(object):
        def __init__(self, hash, previous_hash):
            self.hash = hash
            self.previous_hash = previous_hash
    
    t = Tracker()
    
    t.add_share(FakeShare(1, 2))
    print t.heads
    t.add_share(FakeShare(4, 0))
    print t.heads
    t.add_share(FakeShare(3, 4))
    print t.heads

# TARGET_MULTIPLIER needs to be less than the current difficulty to prevent miner clients from missing shares

class Mainnet(bitcoin_data.Mainnet):
    TARGET_MULTIPLIER = SPREAD = 600
    ROOT_BLOCK = 0x6c9cb0589a44808d9a9361266a4ffb9fea2e2cf4d70bb2118b5
    SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')
    IDENTIFIER = 0x7452839666e1f8f8
    PREFIX = '2d4224bf18c87b87'.decode('hex')
    ADDRS_TABLE = 'addrs'
    P2P_PORT = 9333

class Testnet(bitcoin_data.Testnet):
    TARGET_MULTIPLIER = SPREAD = 30
    ROOT_BLOCK = 0xd5070cd4f2987ad2191af71393731a2b143f094f7b84c9e6aa9a6a
    SCRIPT = '410403ad3dee8ab3d8a9ce5dd2abfbe7364ccd9413df1d279bf1a207849310465b0956e5904b1155ecd17574778f9949589ebfd4fb33ce837c241474a225cf08d85dac'.decode('hex')
    IDENTIFIER = 0x1ae3479e4eb6700a
    PREFIX = 'd19778c812754854'.decode('hex')
    ADDRS_TABLE = 'addrs_testnet'
    P2P_PORT = 19333
