from __future__ import division

import bitcoin_p2p
import conv

chain_id_type = bitcoin_p2p.ComposedType([
    ('last_p2pool_block_hash', bitcoin_p2p.HashType()),
    ('bits', bitcoin_p2p.StructType('<I')),
])

coinbase_type = bitcoin_p2p.ComposedType([
    ('identifier', bitcoin_p2p.StructType('<Q')),
    ('last_p2pool_block_hash', bitcoin_p2p.HashType()),
    ('previous_p2pool_share_hash', bitcoin_p2p.HashType()),
    ('subsidy', bitcoin_p2p.StructType('<Q')),
    ('last_share_index', bitcoin_p2p.StructType('<I')),
    ('nonce', bitcoin_p2p.StructType('<Q')),
])

merkle_branch = bitcoin_p2p.ListType(bitcoin_p2p.ComposedType([
    ('side', bitcoin_p2p.StructType('<B')),
    ('hash', bitcoin_p2p.HashType()),
]))

share1 = bitcoin_p2p.ComposedType([
    ('header', bitcoin_p2p.block_header),
    ('gentx', bitcoin_p2p.ComposedType([
        ('tx', bitcoin_p2p.tx),
        ('merkle_branch', merkle_branch),
    ])),
])

def calculate_merkle_branch(txn_list, index):
    hash_list = [(bitcoin_p2p.doublesha(bitcoin_p2p.tx.pack(data)), i == index, []) for i, data in enumerate(txn_list)]
    
    while len(hash_list) > 1:
        hash_list = [
            (
                bitcoin_p2p.doublesha(bitcoin_p2p.merkle_record.pack(dict(left=left, right=right))),
                left_f or right_f,
                (left_l if left_f else right_l) + [dict(side=1, hash=right) if left_f else dict(side=0, hash=left)],
            )
            for (left, left_f, left_l), (right, right_f, right_l) in
                zip(hash_list[::2], hash_list[1::2] + [hash_list[::2][-1]])
        ]
    
    assert check_merkle_branch(txn_list[index], hash_list[0][2]) == hash_list[0][0]
    
    return hash_list[0][2]

def check_merkle_branch(txn, branch):
    hash_ = bitcoin_p2p.doublesha(bitcoin_p2p.tx.pack(txn))
    for step in branch:
        if not step['side']:
            hash_ = bitcoin_p2p.doublesha(bitcoin_p2p.merkle_record.pack(dict(left=step['hash'], right=hash_)))
        else:
            hash_ = bitcoin_p2p.doublesha(bitcoin_p2p.merkle_record.pack(dict(left=hash_, right=step['hash'])))
    return hash_

def txns_to_gentx(txns):
    return dict(
        tx=txns[0],
        merkle_branch=calculate_merkle_branch(txns, 0),
    )

class Share(object):
    def __init__(self, header, txns=None, gentx=None):
        self.header = header
        self.hash = bitcoin_p2p.block_hash(header)
        
        self.txns = txns
        if txns is None:
            if gentx is not None:
                self.gentx = gentx
                if check_merkle_branch(gentx['tx'], gentx['merkle_branch']) != header['merkle_root']:
                    print '%x' % check_merkle_branch(gentx['tx'], gentx['merkle_branch'])
                    print '%x' % header['merkle_root']
                    raise ValueError("gentx doesn't match header")
            else:
                raise ValueError("need either txns or gentx")
        else:
            self.gentx = txns_to_gentx(txns)
            if gentx is not None:
                if gentx != self.gentx:
                    raise ValueError("invalid gentx")
        
        self.coinbase = coinbase_type.unpack(self.gentx['tx']['tx_ins'][0]['script'], ignore_extra=True)
        self.previous_share_hash = self.coinbase['previous_p2pool_share_hash'] if self.coinbase['previous_p2pool_share_hash'] != 2**256 - 1 else None
        self.chain_id_data = chain_id_type.pack(dict(last_p2pool_block_hash=self.coinbase['last_p2pool_block_hash'], bits=self.header['bits']))
    
    def as_block(self):
        if self.txns is None:
            raise ValueError("share does not contain all txns")
        return dict(header=self.header, txns=self.txns)
    
    def as_share1(self):
        return dict(header=self.header, gentx=self.gentx)
    
    def check(self, chain, height, previous_share2, net):
        if self.chain_id_data != chain.chain_id_data:
            raise ValueError('wrong chain')
        if self.hash > net.TARGET_MULTIPLIER*conv.bits_to_target(self.header['bits']):
            raise ValueError('not enough work!')
        
        t = self.gentx['tx']
        t2, shares = generate_transaction(
            last_p2pool_block_hash=chain.last_p2pool_block_hash,
            previous_share2=previous_share2,
            add_script=t['tx_outs'][self.coinbase['last_share_index']]['script'],
            subsidy=self.coinbase['subsidy'],
            nonce=self.coinbase['nonce'],
            net=net,
        )
        if t2 != t:
            raise ValueError('invalid generate txn')
        
        return Share2(self, chain, shares, height)

class Share2(object):
    """Share with associated data"""
    
    def __init__(self, share, chain, shares, height):
        self.share = share
        self.shares = shares
        self.height = height
        self.chain = chain
        self.shared = False
    
    def flag_shared(self):
        self.shared = True

def generate_transaction(last_p2pool_block_hash, previous_share2, add_script, subsidy, nonce, net):
    shares = (previous_share2.shares if previous_share2 is not None else [net.SCRIPT]*net.SPREAD)[1:-1] + [add_script, add_script]
    
    dest_weights = {}
    for script in shares:
        dest_weights[script] = dest_weights.get(script, 0) + 1
    total_weight = sum(dest_weights.itervalues())
    
    amounts = dict((script, subsidy*weight*63//(64*total_weight)) for (script, weight) in dest_weights.iteritems())
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy//64 # prevent fake previous p2pool blocks
    amounts[net.SCRIPT] = amounts.get(net.SCRIPT, 0) + subsidy - sum(amounts.itervalues()) # collect any extra
    
    dests = sorted(amounts.iterkeys())
    
    return dict(
        version=1,
        tx_ins=[dict(
            previous_output=dict(index=4294967295, hash=0),
            sequence=4294967295,
            script=coinbase_type.pack(dict(
                identifier=net.IDENTIFIER,
                last_p2pool_block_hash=last_p2pool_block_hash,
                previous_p2pool_share_hash=previous_share2.share.hash if previous_share2 is not None else 2**256 - 1,
                subsidy=subsidy,
                last_share_index=dests.index(add_script),
                nonce=nonce,
            )),
        )],
        tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script]],
        lock_time=0,
    ), shares


# TARGET_MULTIPLIER needs to be less than the current difficulty to prevent miner clients from missing shares

class Testnet(object):
    TARGET_MULTIPLIER = 300000
    SPREAD = 300000
    ROOT_BLOCK = 0x3575d1e7b40fe37ad12d41169a1012d26df5f3c35486e2abfbe9d2c
    SCRIPT = '410489175c7658845fd7c33d61029ebf4042e8386443ff6e6628fdb5ac938c31072dc61cee691ae1e8355c3a87cb4813cc9bf036fdb09078d35eacf9e9ab52374ebeac'.decode('hex')
    IDENTIFIER = 0x808330dc87e313b7

class Main(object):
    TARGET_MULTIPLIER = SPREAD = 300
    ROOT_BLOCK = 0xf78e83f63fd0f4e0f584d3bc2c7010f679834cd8886d61876d
    SCRIPT = '410441ccbae5ca6ecfaa014028b0c49df2cd5588cb6058ac260d650bc13c9ec466f95c7a6d80a3ea7f7b8e2e87e49b96081e9b20415b06433d7a5b6a156b58690d96ac'.decode('hex')
    IDENTIFIER = 0x49ddc0b4938708ad
