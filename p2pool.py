from __future__ import division

import bitcoin_p2p
import conv

chain_id_type = bitcoin_p2p.ComposedType([
    ('last_p2pool_block_hash', bitcoin_p2p.HashType()),
    ('bits', bitcoin_p2p.StructType('<I')),
])

share_data_type = bitcoin_p2p.ComposedType([
    ('last_p2pool_block_hash', bitcoin_p2p.HashType()),
    ('previous_p2pool_share_hash', bitcoin_p2p.HashType()),
    ('nonce', bitcoin_p2p.StructType('<Q')),
])

coinbase_type = bitcoin_p2p.ComposedType([
    ('identifier', bitcoin_p2p.StructType('<Q')),
    ('share_data', share_data_type),
])

merkle_branch_type = bitcoin_p2p.ListType(bitcoin_p2p.ComposedType([
    ('side', bitcoin_p2p.StructType('<B')),
    ('hash', bitcoin_p2p.HashType()),
]))

gentx_info_type = bitcoin_p2p.ComposedType([
    ('share_info', bitcoin_p2p.ComposedType([
        ('share_data', share_data_type),
        ('new_script', bitcoin_p2p.VarStrType()),
        ('subsidy', bitcoin_p2p.StructType('<Q')),
    ])),
    ('merkle_branch', merkle_branch_type),
])

share1_type = bitcoin_p2p.ComposedType([
    ('header', bitcoin_p2p.block_header_type),
    ('gentx_info', gentx_info_type),
])

def calculate_merkle_branch(tx_list, index):
    hash_list = [(bitcoin_p2p.doublesha(bitcoin_p2p.tx_type.pack(data)), i == index, []) for i, data in enumerate(tx_list)]
    
    while len(hash_list) > 1:
        hash_list = [
            (
                bitcoin_p2p.doublesha(bitcoin_p2p.merkle_record_type.pack(dict(left=left, right=right))),
                left_f or right_f,
                (left_l if left_f else right_l) + [dict(side=1, hash=right) if left_f else dict(side=0, hash=left)],
            )
            for (left, left_f, left_l), (right, right_f, right_l) in
                zip(hash_list[::2], hash_list[1::2] + [hash_list[::2][-1]])
        ]
    
    assert hash_list[0][1]
    assert check_merkle_branch(tx_list[index], hash_list[0][2]) == hash_list[0][0]
    
    return hash_list[0][2]

def check_merkle_branch(tx, branch):
    hash_ = bitcoin_p2p.doublesha(bitcoin_p2p.tx_type.pack(tx))
    for step in branch:
        if not step['side']:
            hash_ = bitcoin_p2p.doublesha(bitcoin_p2p.merkle_record_type.pack(dict(left=step['hash'], right=hash_)))
        else:
            hash_ = bitcoin_p2p.doublesha(bitcoin_p2p.merkle_record_type.pack(dict(left=hash_, right=step['hash'])))
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
        last_p2pool_block_hash=share_info['share_data']['last_p2pool_block_hash'],
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
            if bitcoin_p2p.merkle_hash(txs) != header['merkle_root']:
                raise ValueError("txs don't match header")
        
        if gentx_info is None:
            if txs is None:
                raise ValueError('need either txs or gentx_info')
            
            gentx_info = txs_to_gentx_info(txs)
        
        coinbase = gentx_info['share_info']['coinbase']
        
        self.header = header
        self.txs = txs
        self.gentx_info = gentx_info
        self.hash = bitcoin_p2p.block_hash(header)
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
        if self.hash > net.TARGET_MULTIPLIER*conv.bits_to_target(self.header['bits']):
            raise ValueError('not enough work!')
        
        gentx, shares, merkle_root = gentx_info_to_gentx_shares_and_merkle_root(self.gentx_info, chain, net)
        
        if merkle_root != self.header['merkle_root']:
            raise ValueError("gentx doesn't match header")
        
        return Share2(self, shares, height)

class Share2(object):
    '''Share with associated data'''
    
    def __init__(self, share, shares, height):
        self.share = share
        self.shares = map(intern, shares)
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
    
    dests = sorted(amounts.iterkeys())
    dests.remove(new_script)
    dests = dests + [new_script]
    
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
                ),
            )),
        )],
        tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script]],
        lock_time=0,
    ), shares


# TARGET_MULTIPLIER needs to be less than the current difficulty to prevent miner clients from missing shares

class Testnet(object):
    TARGET_MULTIPLIER = SPREAD = 30
    ROOT_BLOCK = 0xd5070cd4f2987ad2191af71393731a2b143f094f7b84c9e6aa9a6a
    SCRIPT = '410403ad3dee8ab3d8a9ce5dd2abfbe7364ccd9413df1d279bf1a207849310465b0956e5904b1155ecd17574778f9949589ebfd4fb33ce837c241474a225cf08d85dac'.decode('hex')
    IDENTIFIER = 0x1ae3479e4eb6700a
    PREFIX= 'd19778c812754854'.decode('hex')
    ADDRS_TABLE = 'addrs_testnet'

class Main(object):
    TARGET_MULTIPLIER = SPREAD = 600
    ROOT_BLOCK = 0x11a22c6e314b1a3f44cbbf50246187a37756ea8af4d41c43a8d6
    SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')
    IDENTIFIER = 0x7452839666e1f8f8
    PREFIX = '2d4224bf18c87b87'.decode('hex')
    ADDRS_TABLE = 'addrs'
