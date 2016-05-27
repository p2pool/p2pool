from __future__ import division

import hashlib
import os
import random
import sys
import time

from twisted.python import log

import p2pool
from p2pool.bitcoin import data as bitcoin_data, script, sha256
from p2pool.util import math, forest, pack

def parse_bip0034(coinbase):
    _, opdata = script.parse(coinbase).next()
    bignum = pack.IntType(len(opdata)*8).unpack(opdata)
    if ord(opdata[-1]) & 0x80:
        bignum = -bignum
    return (bignum,)

# hashlink

hash_link_type = pack.ComposedType([
    ('state', pack.FixedStrType(32)),
    ('extra_data', pack.FixedStrType(0)), # bit of a hack, but since the donation script is at the end, const_ending is long enough to always make this empty
    ('length', pack.VarIntType()),
])

def prefix_to_hash_link(prefix, const_ending=''):
    assert prefix.endswith(const_ending), (prefix, const_ending)
    x = sha256.sha256(prefix)
    return dict(state=x.state, extra_data=x.buf[:max(0, len(x.buf)-len(const_ending))], length=x.length//8)

def check_hash_link(hash_link, data, const_ending=''):
    extra_length = hash_link['length'] % (512//8)
    assert len(hash_link['extra_data']) == max(0, extra_length - len(const_ending))
    extra = (hash_link['extra_data'] + const_ending)[len(hash_link['extra_data']) + len(const_ending) - extra_length:]
    assert len(extra) == extra_length
    return pack.IntType(256).unpack(hashlib.sha256(sha256.sha256(data, (hash_link['state'], extra, 8*hash_link['length'])).digest()).digest())

# shares

share_type = pack.ComposedType([
    ('type', pack.VarIntType()),
    ('contents', pack.VarStrType()),
])

def load_share(share, net, peer_addr):
    assert peer_addr is None or isinstance(peer_addr, tuple)
    if share['type'] < Share.VERSION:
        from p2pool import p2p
        raise p2p.PeerMisbehavingError('sent an obsolete share')
    elif share['type'] == Share.VERSION:
        return Share(net, peer_addr, Share.share_type.unpack(share['contents']))
    elif share['type'] == NewShare.VERSION:
        return NewShare(net, peer_addr, NewShare.share_type.unpack(share['contents']))
    else:
        raise ValueError('unknown share type: %r' % (share['type'],))

DONATION_SCRIPT = '4104ffd03de44a6e11b9917f3a29f9443283d9871c9d743ef30d5eddcd37094b64d1b3d8090496b53256786bf5c82932ec23c3b74d9f05a6f95a8b5529352656664bac'.decode('hex')

class NewShare(object):
    VERSION = 16
    VOTING_VERSION = 16
    SUCCESSOR = None
    
    small_block_header_type = pack.ComposedType([
        ('version', pack.VarIntType()),
        ('previous_block', pack.PossiblyNoneType(0, pack.IntType(256))),
        ('timestamp', pack.IntType(32)),
        ('bits', bitcoin_data.FloatingIntegerType()),
        ('nonce', pack.IntType(32)),
    ])
    
    share_info_type = pack.ComposedType([
        ('share_data', pack.ComposedType([
            ('previous_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
            ('coinbase', pack.VarStrType()),
            ('nonce', pack.IntType(32)),
            ('pubkey_hash', pack.IntType(160)),
            ('subsidy', pack.IntType(64)),
            ('donation', pack.IntType(16)),
            ('stale_info', pack.EnumType(pack.IntType(8), dict((k, {0: None, 253: 'orphan', 254: 'doa'}.get(k, 'unk%i' % (k,))) for k in xrange(256)))),
            ('desired_version', pack.VarIntType()),
        ])),
        ('new_transaction_hashes', pack.ListType(pack.IntType(256))),
        ('transaction_hash_refs', pack.ListType(pack.VarIntType(), 2)), # pairs of share_count, tx_count
        ('far_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
        ('max_bits', bitcoin_data.FloatingIntegerType()),
        ('bits', bitcoin_data.FloatingIntegerType()),
        ('timestamp', pack.IntType(32)),
        ('absheight', pack.IntType(32)),
        ('abswork', pack.IntType(128)),
    ])
    
    share_type = pack.ComposedType([
        ('min_header', small_block_header_type),
        ('share_info', share_info_type),
        ('ref_merkle_link', pack.ComposedType([
            ('branch', pack.ListType(pack.IntType(256))),
            ('index', pack.IntType(0)),
        ])),
        ('last_txout_nonce', pack.IntType(64)),
        ('hash_link', hash_link_type),
        ('merkle_link', pack.ComposedType([
            ('branch', pack.ListType(pack.IntType(256))),
            ('index', pack.IntType(0)), # it will always be 0
        ])),
    ])
    
    ref_type = pack.ComposedType([
        ('identifier', pack.FixedStrType(64//8)),
        ('share_info', share_info_type),
    ])
    
    gentx_before_refhash = pack.VarStrType().pack(DONATION_SCRIPT) + pack.IntType(64).pack(0) + pack.VarStrType().pack('\x6a\x28' + pack.IntType(256).pack(0) + pack.IntType(64).pack(0))[:3]
    
    @classmethod
    def generate_transaction(cls, tracker, share_data, block_target, desired_timestamp, desired_target, ref_merkle_link, desired_other_transaction_hashes_and_fees, net, known_txs=None, last_txout_nonce=0, base_subsidy=None):
        previous_share = tracker.items[share_data['previous_share_hash']] if share_data['previous_share_hash'] is not None else None
        
        height, last = tracker.get_height_and_last(share_data['previous_share_hash'])
        assert height >= net.REAL_CHAIN_LENGTH or last is None
        if height < net.TARGET_LOOKBEHIND:
            pre_target3 = net.MAX_TARGET
        else:
            attempts_per_second = get_pool_attempts_per_second(tracker, share_data['previous_share_hash'], net.TARGET_LOOKBEHIND, min_work=True, integer=True)
            pre_target = 2**256//(net.SHARE_PERIOD*attempts_per_second) - 1 if attempts_per_second else 2**256-1
            pre_target2 = math.clip(pre_target, (previous_share.max_target*9//10, previous_share.max_target*11//10))
            pre_target3 = math.clip(pre_target2, (net.MIN_TARGET, net.MAX_TARGET))
        max_bits = bitcoin_data.FloatingInteger.from_target_upper_bound(pre_target3)
        bits = bitcoin_data.FloatingInteger.from_target_upper_bound(math.clip(desired_target, (pre_target3//30, pre_target3)))
        
        new_transaction_hashes = []
        new_transaction_size = 0
        transaction_hash_refs = []
        other_transaction_hashes = []
        
        past_shares = list(tracker.get_chain(share_data['previous_share_hash'], min(height, 100)))
        tx_hash_to_this = {}
        for i, share in enumerate(past_shares):
            for j, tx_hash in enumerate(share.new_transaction_hashes):
                if tx_hash not in tx_hash_to_this:
                    tx_hash_to_this[tx_hash] = [1+i, j] # share_count, tx_count
        for tx_hash, fee in desired_other_transaction_hashes_and_fees:
            if tx_hash in tx_hash_to_this:
                this = tx_hash_to_this[tx_hash]
            else:
                if known_txs is not None:
                    this_size = bitcoin_data.tx_type.packed_size(known_txs[tx_hash])
                    if new_transaction_size + this_size > 50000: # only allow 50 kB of new txns/share
                        break
                    new_transaction_size += this_size
                new_transaction_hashes.append(tx_hash)
                this = [0, len(new_transaction_hashes)-1]
            transaction_hash_refs.extend(this)
            other_transaction_hashes.append(tx_hash)
        
        included_transactions = set(other_transaction_hashes)
        removed_fees = [fee for tx_hash, fee in desired_other_transaction_hashes_and_fees if tx_hash not in included_transactions]
        definite_fees = sum(0 if fee is None else fee for tx_hash, fee in desired_other_transaction_hashes_and_fees if tx_hash in included_transactions)
        if None not in removed_fees:
            share_data = dict(share_data, subsidy=share_data['subsidy'] - sum(removed_fees))
        else:
            assert base_subsidy is not None
            share_data = dict(share_data, subsidy=base_subsidy + definite_fees)
        
        weights, total_weight, donation_weight = tracker.get_cumulative_weights(previous_share.share_data['previous_share_hash'] if previous_share is not None else None,
            max(0, min(height, net.REAL_CHAIN_LENGTH) - 1),
            65535*net.SPREAD*bitcoin_data.target_to_average_attempts(block_target),
        )
        assert total_weight == sum(weights.itervalues()) + donation_weight, (total_weight, sum(weights.itervalues()) + donation_weight)
        
        amounts = dict((script, share_data['subsidy']*(199*weight)//(200*total_weight)) for script, weight in weights.iteritems()) # 99.5% goes according to weights prior to this share
        this_script = bitcoin_data.pubkey_hash_to_script2(share_data['pubkey_hash'])
        amounts[this_script] = amounts.get(this_script, 0) + share_data['subsidy']//200 # 0.5% goes to block finder
        amounts[DONATION_SCRIPT] = amounts.get(DONATION_SCRIPT, 0) + share_data['subsidy'] - sum(amounts.itervalues()) # all that's left over is the donation weight and some extra satoshis due to rounding
        
        if sum(amounts.itervalues()) != share_data['subsidy'] or any(x < 0 for x in amounts.itervalues()):
            raise ValueError()
        
        dests = sorted(amounts.iterkeys(), key=lambda script: (script == DONATION_SCRIPT, amounts[script], script))[-4000:] # block length limit, unlikely to ever be hit
        
        share_info = dict(
            share_data=share_data,
            far_share_hash=None if last is None and height < 99 else tracker.get_nth_parent_hash(share_data['previous_share_hash'], 99),
            max_bits=max_bits,
            bits=bits,
            timestamp=math.clip(desired_timestamp, (
                (previous_share.timestamp + net.SHARE_PERIOD) - (net.SHARE_PERIOD - 1), # = previous_share.timestamp + 1
                (previous_share.timestamp + net.SHARE_PERIOD) + (net.SHARE_PERIOD - 1),
            )) if previous_share is not None else desired_timestamp,
            new_transaction_hashes=new_transaction_hashes,
            transaction_hash_refs=transaction_hash_refs,
            absheight=((previous_share.absheight if previous_share is not None else 0) + 1) % 2**32,
            abswork=((previous_share.abswork if previous_share is not None else 0) + bitcoin_data.target_to_average_attempts(bits.target)) % 2**128,
        )
        
        gentx = dict(
            version=1,
            tx_ins=[dict(
                previous_output=None,
                sequence=None,
                script=share_data['coinbase'],
            )],
            tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script] or script == DONATION_SCRIPT] + [dict(
                value=0,
                script='\x6a\x28' + cls.get_ref_hash(net, share_info, ref_merkle_link) + pack.IntType(64).pack(last_txout_nonce),
            )],
            lock_time=0,
        )
        
        def get_share(header, last_txout_nonce=last_txout_nonce):
            min_header = dict(header); del min_header['merkle_root']
            share = cls(net, None, dict(
                min_header=min_header,
                share_info=share_info,
                ref_merkle_link=dict(branch=[], index=0),
                last_txout_nonce=last_txout_nonce,
                hash_link=prefix_to_hash_link(bitcoin_data.tx_type.pack(gentx)[:-32-8-4], cls.gentx_before_refhash),
                merkle_link=bitcoin_data.calculate_merkle_link([None] + other_transaction_hashes, 0),
            ))
            assert share.header == header # checks merkle_root
            return share
        
        return share_info, gentx, other_transaction_hashes, get_share
    
    @classmethod
    def get_ref_hash(cls, net, share_info, ref_merkle_link):
        return pack.IntType(256).pack(bitcoin_data.check_merkle_link(bitcoin_data.hash256(cls.ref_type.pack(dict(
            identifier=net.IDENTIFIER,
            share_info=share_info,
        ))), ref_merkle_link))
    
    __slots__ = 'net peer_addr contents min_header share_info hash_link merkle_link hash share_data max_target target timestamp previous_hash new_script desired_version gentx_hash header pow_hash header_hash new_transaction_hashes time_seen absheight abswork'.split(' ')
    
    def __init__(self, net, peer_addr, contents):
        self.net = net
        self.peer_addr = peer_addr
        self.contents = contents
        
        self.min_header = contents['min_header']
        self.share_info = contents['share_info']
        self.hash_link = contents['hash_link']
        self.merkle_link = contents['merkle_link']
        
        if not (2 <= len(self.share_info['share_data']['coinbase']) <= 100):
            raise ValueError('''bad coinbase size! %i bytes''' % (len(self.share_info['share_data']['coinbase']),))
        
        if len(self.merkle_link['branch']) > 16:
            raise ValueError('merkle branch too long!')
        
        assert not self.hash_link['extra_data'], repr(self.hash_link['extra_data'])
        
        self.share_data = self.share_info['share_data']
        self.max_target = self.share_info['max_bits'].target
        self.target = self.share_info['bits'].target
        self.timestamp = self.share_info['timestamp']
        self.previous_hash = self.share_data['previous_share_hash']
        self.new_script = bitcoin_data.pubkey_hash_to_script2(self.share_data['pubkey_hash'])
        self.desired_version = self.share_data['desired_version']
        self.absheight = self.share_info['absheight']
        self.abswork = self.share_info['abswork']
        
        n = set()
        for share_count, tx_count in self.iter_transaction_hash_refs():
            assert share_count < 110
            if share_count == 0:
                n.add(tx_count)
        assert n == set(range(len(self.share_info['new_transaction_hashes'])))
        
        self.gentx_hash = check_hash_link(
            self.hash_link,
            self.get_ref_hash(net, self.share_info, contents['ref_merkle_link']) + pack.IntType(64).pack(self.contents['last_txout_nonce']) + pack.IntType(32).pack(0),
            self.gentx_before_refhash,
        )
        merkle_root = bitcoin_data.check_merkle_link(self.gentx_hash, self.merkle_link)
        self.header = dict(self.min_header, merkle_root=merkle_root)
        self.pow_hash = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(self.header))
        self.hash = self.header_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(self.header))
        
        if self.target > net.MAX_TARGET:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('share target invalid')
        
        if self.pow_hash > self.target:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('share PoW invalid')
        
        self.new_transaction_hashes = self.share_info['new_transaction_hashes']
        
        # XXX eww
        self.time_seen = time.time()
    
    def __repr__(self):
        return 'Share' + repr((self.net, self.peer_addr, self.contents))
    
    def as_share(self):
        return dict(type=self.VERSION, contents=self.share_type.pack(self.contents))
    
    def iter_transaction_hash_refs(self):
        return zip(self.share_info['transaction_hash_refs'][::2], self.share_info['transaction_hash_refs'][1::2])
    
    def check(self, tracker):
        from p2pool import p2p
        if self.share_data['previous_share_hash'] is not None:
            previous_share = tracker.items[self.share_data['previous_share_hash']]
            if type(self) is type(previous_share):
                pass
            elif type(self) is type(previous_share).SUCCESSOR:
                if tracker.get_height(previous_share.hash) < self.net.CHAIN_LENGTH:
                    from p2pool import p2p
                    raise p2p.PeerMisbehavingError('switch without enough history')
                
                # switch only valid if 60% of hashes in [self.net.CHAIN_LENGTH*9//10, self.net.CHAIN_LENGTH] for new version
                counts = get_desired_version_counts(tracker,
                    tracker.get_nth_parent_hash(previous_share.hash, self.net.CHAIN_LENGTH*9//10), self.net.CHAIN_LENGTH//10)
                if counts.get(self.VERSION, 0) < sum(counts.itervalues())*60//100:
                    raise p2p.PeerMisbehavingError('switch without enough hash power upgraded')
            else:
                raise p2p.PeerMisbehavingError('''%s can't follow %s''' % (type(self).__name__, type(previous_share).__name__))
        
        other_tx_hashes = [tracker.items[tracker.get_nth_parent_hash(self.hash, share_count)].share_info['new_transaction_hashes'][tx_count] for share_count, tx_count in self.iter_transaction_hash_refs()]
        
        share_info, gentx, other_tx_hashes2, get_share = self.generate_transaction(tracker, self.share_info['share_data'], self.header['bits'].target, self.share_info['timestamp'], self.share_info['bits'].target, self.contents['ref_merkle_link'], [(h, None) for h in other_tx_hashes], self.net, last_txout_nonce=self.contents['last_txout_nonce'])
        assert other_tx_hashes2 == other_tx_hashes
        if share_info != self.share_info:
            raise ValueError('share_info invalid')
        if bitcoin_data.hash256(bitcoin_data.tx_type.pack(gentx)) != self.gentx_hash:
            raise ValueError('''gentx doesn't match hash_link''')
        
        if bitcoin_data.calculate_merkle_link([None] + other_tx_hashes, 0) != self.merkle_link:
            raise ValueError('merkle_link and other_tx_hashes do not match')
        
        return gentx # only used by as_block
    
    def get_other_tx_hashes(self, tracker):
        parents_needed = max(share_count for share_count, tx_count in self.iter_transaction_hash_refs()) if self.share_info['transaction_hash_refs'] else 0
        parents = tracker.get_height(self.hash) - 1
        if parents < parents_needed:
            return None
        last_shares = list(tracker.get_chain(self.hash, parents_needed + 1))
        return [last_shares[share_count].share_info['new_transaction_hashes'][tx_count] for share_count, tx_count in self.iter_transaction_hash_refs()]
    
    def _get_other_txs(self, tracker, known_txs):
        other_tx_hashes = self.get_other_tx_hashes(tracker)
        if other_tx_hashes is None:
            return None # not all parents present
        
        if not all(tx_hash in known_txs for tx_hash in other_tx_hashes):
            return None # not all txs present
        
        return [known_txs[tx_hash] for tx_hash in other_tx_hashes]
    
    def should_punish_reason(self, previous_block, bits, tracker, known_txs):
        if (self.header['previous_block'], self.header['bits']) != (previous_block, bits) and self.header_hash != previous_block and self.peer_addr is not None:
            return True, 'Block-stale detected! height(%x) < height(%x) or %08x != %08x' % (self.header['previous_block'], previous_block, self.header['bits'].bits, bits.bits)
        
        if self.pow_hash <= self.header['bits'].target:
            return -1, 'block solution'
        
        other_txs = self._get_other_txs(tracker, known_txs)
        if other_txs is None:
            pass
        else:
            all_txs_size = sum(bitcoin_data.tx_type.packed_size(tx) for tx in other_txs)
            if all_txs_size > 1000000:
                return True, 'txs over block size limit'
            
            new_txs_size = sum(bitcoin_data.tx_type.packed_size(known_txs[tx_hash]) for tx_hash in self.share_info['new_transaction_hashes'])
            if new_txs_size > 50000:
                return True, 'new txs over limit'
        
        return False, None
    
    def as_block(self, tracker, known_txs):
        other_txs = self._get_other_txs(tracker, known_txs)
        if other_txs is None:
            return None # not all txs present
        return dict(header=self.header, txs=[self.check(tracker)] + other_txs)

class Share(object):
    VERSION = 15
    VOTING_VERSION = 15
    SUCCESSOR = NewShare
    
    small_block_header_type = pack.ComposedType([
        ('version', pack.VarIntType()),
        ('previous_block', pack.PossiblyNoneType(0, pack.IntType(256))),
        ('timestamp', pack.IntType(32)),
        ('bits', bitcoin_data.FloatingIntegerType()),
        ('nonce', pack.IntType(32)),
    ])
    
    share_info_type = pack.ComposedType([
        ('share_data', pack.ComposedType([
            ('previous_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
            ('coinbase', pack.VarStrType()),
            ('nonce', pack.IntType(32)),
            ('pubkey_hash', pack.IntType(160)),
            ('subsidy', pack.IntType(64)),
            ('donation', pack.IntType(16)),
            ('stale_info', pack.EnumType(pack.IntType(8), dict((k, {0: None, 253: 'orphan', 254: 'doa'}.get(k, 'unk%i' % (k,))) for k in xrange(256)))),
            ('desired_version', pack.VarIntType()),
        ])),
        ('new_transaction_hashes', pack.ListType(pack.IntType(256))),
        ('transaction_hash_refs', pack.ListType(pack.VarIntType(), 2)), # pairs of share_count, tx_count
        ('far_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
        ('max_bits', bitcoin_data.FloatingIntegerType()),
        ('bits', bitcoin_data.FloatingIntegerType()),
        ('timestamp', pack.IntType(32)),
        ('absheight', pack.IntType(32)),
        ('abswork', pack.IntType(128)),
    ])
    
    share_type = pack.ComposedType([
        ('min_header', small_block_header_type),
        ('share_info', share_info_type),
        ('ref_merkle_link', pack.ComposedType([
            ('branch', pack.ListType(pack.IntType(256))),
            ('index', pack.IntType(0)),
        ])),
        ('last_txout_nonce', pack.IntType(64)),
        ('hash_link', hash_link_type),
        ('merkle_link', pack.ComposedType([
            ('branch', pack.ListType(pack.IntType(256))),
            ('index', pack.IntType(0)), # it will always be 0
        ])),
    ])
    
    ref_type = pack.ComposedType([
        ('identifier', pack.FixedStrType(64//8)),
        ('share_info', share_info_type),
    ])
    
    gentx_before_refhash = pack.VarStrType().pack(DONATION_SCRIPT) + pack.IntType(64).pack(0) + pack.VarStrType().pack('\x6a\x28' + pack.IntType(256).pack(0) + pack.IntType(64).pack(0))[:3]
    
    @classmethod
    def generate_transaction(cls, tracker, share_data, block_target, desired_timestamp, desired_target, ref_merkle_link, desired_other_transaction_hashes_and_fees, net, known_txs=None, last_txout_nonce=0, base_subsidy=None):
        previous_share = tracker.items[share_data['previous_share_hash']] if share_data['previous_share_hash'] is not None else None
        
        height, last = tracker.get_height_and_last(share_data['previous_share_hash'])
        assert height >= net.REAL_CHAIN_LENGTH or last is None
        if height < net.TARGET_LOOKBEHIND:
            pre_target3 = net.MAX_TARGET
        else:
            attempts_per_second = get_pool_attempts_per_second(tracker, share_data['previous_share_hash'], net.TARGET_LOOKBEHIND, min_work=True, integer=True)
            pre_target = 2**256//(net.SHARE_PERIOD*attempts_per_second) - 1 if attempts_per_second else 2**256-1
            pre_target2 = math.clip(pre_target, (previous_share.max_target*9//10, previous_share.max_target*11//10))
            pre_target3 = math.clip(pre_target2, (net.MIN_TARGET, net.MAX_TARGET))
        max_bits = bitcoin_data.FloatingInteger.from_target_upper_bound(pre_target3)
        bits = bitcoin_data.FloatingInteger.from_target_upper_bound(math.clip(desired_target, (pre_target3//30, pre_target3)))
        
        new_transaction_hashes = []
        new_transaction_size = 0
        transaction_hash_refs = []
        other_transaction_hashes = []
        
        past_shares = list(tracker.get_chain(share_data['previous_share_hash'], min(height, 100)))
        tx_hash_to_this = {}
        for i, share in enumerate(past_shares):
            for j, tx_hash in enumerate(share.new_transaction_hashes):
                if tx_hash not in tx_hash_to_this:
                    tx_hash_to_this[tx_hash] = [1+i, j] # share_count, tx_count
        for tx_hash, fee in desired_other_transaction_hashes_and_fees:
            if tx_hash in tx_hash_to_this:
                this = tx_hash_to_this[tx_hash]
            else:
                if known_txs is not None:
                    this_size = bitcoin_data.tx_type.packed_size(known_txs[tx_hash])
                    if new_transaction_size + this_size > 50000: # only allow 50 kB of new txns/share
                        break
                    new_transaction_size += this_size
                new_transaction_hashes.append(tx_hash)
                this = [0, len(new_transaction_hashes)-1]
            transaction_hash_refs.extend(this)
            other_transaction_hashes.append(tx_hash)
        
        included_transactions = set(other_transaction_hashes)
        removed_fees = [fee for tx_hash, fee in desired_other_transaction_hashes_and_fees if tx_hash not in included_transactions]
        definite_fees = sum(0 if fee is None else fee for tx_hash, fee in desired_other_transaction_hashes_and_fees if tx_hash in included_transactions)
        if None not in removed_fees:
            share_data = dict(share_data, subsidy=share_data['subsidy'] - sum(removed_fees))
        else:
            assert base_subsidy is not None
            share_data = dict(share_data, subsidy=base_subsidy + definite_fees)
        
        weights, total_weight, donation_weight = tracker.get_cumulative_weights(previous_share.share_data['previous_share_hash'] if previous_share is not None else None,
            max(0, min(height, net.REAL_CHAIN_LENGTH) - 1),
            65535*net.SPREAD*bitcoin_data.target_to_average_attempts(block_target),
        )
        assert total_weight == sum(weights.itervalues()) + donation_weight, (total_weight, sum(weights.itervalues()) + donation_weight)
        
        amounts = dict((script, share_data['subsidy']*(199*weight)//(200*total_weight)) for script, weight in weights.iteritems()) # 99.5% goes according to weights prior to this share
        this_script = bitcoin_data.pubkey_hash_to_script2(share_data['pubkey_hash'])
        amounts[this_script] = amounts.get(this_script, 0) + share_data['subsidy']//200 # 0.5% goes to block finder
        amounts[DONATION_SCRIPT] = amounts.get(DONATION_SCRIPT, 0) + share_data['subsidy'] - sum(amounts.itervalues()) # all that's left over is the donation weight and some extra satoshis due to rounding
        
        if sum(amounts.itervalues()) != share_data['subsidy'] or any(x < 0 for x in amounts.itervalues()):
            raise ValueError()
        
        dests = sorted(amounts.iterkeys(), key=lambda script: (script == DONATION_SCRIPT, amounts[script], script))[-4000:] # block length limit, unlikely to ever be hit
        
        share_info = dict(
            share_data=share_data,
            far_share_hash=None if last is None and height < 99 else tracker.get_nth_parent_hash(share_data['previous_share_hash'], 99),
            max_bits=max_bits,
            bits=bits,
            timestamp=math.clip(desired_timestamp, (
                (previous_share.timestamp + net.SHARE_PERIOD) - (net.SHARE_PERIOD - 1), # = previous_share.timestamp + 1
                (previous_share.timestamp + net.SHARE_PERIOD) + (net.SHARE_PERIOD - 1),
            )) if previous_share is not None else desired_timestamp,
            new_transaction_hashes=new_transaction_hashes,
            transaction_hash_refs=transaction_hash_refs,
            absheight=((previous_share.absheight if previous_share is not None else 0) + 1) % 2**32,
            abswork=((previous_share.abswork if previous_share is not None else 0) + bitcoin_data.target_to_average_attempts(bits.target)) % 2**128,
        )
        
        gentx = dict(
            version=1,
            tx_ins=[dict(
                previous_output=None,
                sequence=None,
                script=share_data['coinbase'],
            )],
            tx_outs=[dict(value=amounts[script], script=script) for script in dests if amounts[script] or script == DONATION_SCRIPT] + [dict(
                value=0,
                script='\x6a\x28' + cls.get_ref_hash(net, share_info, ref_merkle_link) + pack.IntType(64).pack(last_txout_nonce),
            )],
            lock_time=0,
        )
        
        def get_share(header, last_txout_nonce=last_txout_nonce):
            min_header = dict(header); del min_header['merkle_root']
            share = cls(net, None, dict(
                min_header=min_header,
                share_info=share_info,
                ref_merkle_link=dict(branch=[], index=0),
                last_txout_nonce=last_txout_nonce,
                hash_link=prefix_to_hash_link(bitcoin_data.tx_type.pack(gentx)[:-32-8-4], cls.gentx_before_refhash),
                merkle_link=bitcoin_data.calculate_merkle_link([None] + other_transaction_hashes, 0),
            ))
            assert share.header == header # checks merkle_root
            return share
        
        return share_info, gentx, other_transaction_hashes, get_share
    
    @classmethod
    def get_ref_hash(cls, net, share_info, ref_merkle_link):
        return pack.IntType(256).pack(bitcoin_data.check_merkle_link(bitcoin_data.hash256(cls.ref_type.pack(dict(
            identifier=net.IDENTIFIER,
            share_info=share_info,
        ))), ref_merkle_link))
    
    __slots__ = 'net peer_addr contents min_header share_info hash_link merkle_link hash share_data max_target target timestamp previous_hash new_script desired_version gentx_hash header pow_hash header_hash new_transaction_hashes time_seen absheight abswork'.split(' ')
    
    def __init__(self, net, peer_addr, contents):
        self.net = net
        self.peer_addr = peer_addr
        self.contents = contents
        
        self.min_header = contents['min_header']
        self.share_info = contents['share_info']
        self.hash_link = contents['hash_link']
        self.merkle_link = contents['merkle_link']
        
        if not (2 <= len(self.share_info['share_data']['coinbase']) <= 100):
            raise ValueError('''bad coinbase size! %i bytes''' % (len(self.share_info['share_data']['coinbase']),))
        
        if len(self.merkle_link['branch']) > 16:
            raise ValueError('merkle branch too long!')
        
        assert not self.hash_link['extra_data'], repr(self.hash_link['extra_data'])
        
        self.share_data = self.share_info['share_data']
        self.max_target = self.share_info['max_bits'].target
        self.target = self.share_info['bits'].target
        self.timestamp = self.share_info['timestamp']
        self.previous_hash = self.share_data['previous_share_hash']
        self.new_script = bitcoin_data.pubkey_hash_to_script2(self.share_data['pubkey_hash'])
        self.desired_version = self.share_data['desired_version']
        self.absheight = self.share_info['absheight']
        self.abswork = self.share_info['abswork']
        
        n = set()
        for share_count, tx_count in self.iter_transaction_hash_refs():
            assert share_count < 110
            if share_count == 0:
                n.add(tx_count)
        assert n == set(range(len(self.share_info['new_transaction_hashes'])))
        
        self.gentx_hash = check_hash_link(
            self.hash_link,
            self.get_ref_hash(net, self.share_info, contents['ref_merkle_link']) + pack.IntType(64).pack(self.contents['last_txout_nonce']) + pack.IntType(32).pack(0),
            self.gentx_before_refhash,
        )
        merkle_root = bitcoin_data.check_merkle_link(self.gentx_hash, self.merkle_link)
        self.header = dict(self.min_header, merkle_root=merkle_root)
        self.pow_hash = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(self.header))
        self.hash = self.header_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(self.header))
        
        if self.target > net.MAX_TARGET:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('share target invalid')
        
        if self.pow_hash > self.target:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('share PoW invalid')
        
        self.new_transaction_hashes = self.share_info['new_transaction_hashes']
        
        # XXX eww
        self.time_seen = time.time()
    
    def __repr__(self):
        return 'Share' + repr((self.net, self.peer_addr, self.contents))
    
    def as_share(self):
        return dict(type=self.VERSION, contents=self.share_type.pack(self.contents))
    
    def iter_transaction_hash_refs(self):
        return zip(self.share_info['transaction_hash_refs'][::2], self.share_info['transaction_hash_refs'][1::2])
    
    def check(self, tracker):
        from p2pool import p2p
        if self.share_data['previous_share_hash'] is not None:
            previous_share = tracker.items[self.share_data['previous_share_hash']]
            if type(self) is type(previous_share):
                pass
            elif type(self) is type(previous_share).SUCCESSOR:
                if tracker.get_height(previous_share.hash) < self.net.CHAIN_LENGTH:
                    from p2pool import p2p
                    raise p2p.PeerMisbehavingError('switch without enough history')
                
                # switch only valid if 60% of hashes in [self.net.CHAIN_LENGTH*9//10, self.net.CHAIN_LENGTH] for new version
                counts = get_desired_version_counts(tracker,
                    tracker.get_nth_parent_hash(previous_share.hash, self.net.CHAIN_LENGTH*9//10), self.net.CHAIN_LENGTH//10)
                if counts.get(self.VERSION, 0) < sum(counts.itervalues())*60//100:
                    raise p2p.PeerMisbehavingError('switch without enough hash power upgraded')
            else:
                raise p2p.PeerMisbehavingError('''%s can't follow %s''' % (type(self).__name__, type(previous_share).__name__))
        
        other_tx_hashes = [tracker.items[tracker.get_nth_parent_hash(self.hash, share_count)].share_info['new_transaction_hashes'][tx_count] for share_count, tx_count in self.iter_transaction_hash_refs()]
        
        share_info, gentx, other_tx_hashes2, get_share = self.generate_transaction(tracker, self.share_info['share_data'], self.header['bits'].target, self.share_info['timestamp'], self.share_info['bits'].target, self.contents['ref_merkle_link'], [(h, None) for h in other_tx_hashes], self.net, last_txout_nonce=self.contents['last_txout_nonce'])
        assert other_tx_hashes2 == other_tx_hashes
        if share_info != self.share_info:
            raise ValueError('share_info invalid')
        if bitcoin_data.hash256(bitcoin_data.tx_type.pack(gentx)) != self.gentx_hash:
            raise ValueError('''gentx doesn't match hash_link''')
        
        if bitcoin_data.calculate_merkle_link([None] + other_tx_hashes, 0) != self.merkle_link:
            raise ValueError('merkle_link and other_tx_hashes do not match')
        
        return gentx # only used by as_block
    
    def get_other_tx_hashes(self, tracker):
        parents_needed = max(share_count for share_count, tx_count in self.iter_transaction_hash_refs()) if self.share_info['transaction_hash_refs'] else 0
        parents = tracker.get_height(self.hash) - 1
        if parents < parents_needed:
            return None
        last_shares = list(tracker.get_chain(self.hash, parents_needed + 1))
        return [last_shares[share_count].share_info['new_transaction_hashes'][tx_count] for share_count, tx_count in self.iter_transaction_hash_refs()]
    
    def _get_other_txs(self, tracker, known_txs):
        other_tx_hashes = self.get_other_tx_hashes(tracker)
        if other_tx_hashes is None:
            return None # not all parents present
        
        if not all(tx_hash in known_txs for tx_hash in other_tx_hashes):
            return None # not all txs present
        
        return [known_txs[tx_hash] for tx_hash in other_tx_hashes]
    
    def should_punish_reason(self, previous_block, bits, tracker, known_txs):
        if (self.header['previous_block'], self.header['bits']) != (previous_block, bits) and self.header_hash != previous_block and self.peer_addr is not None:
            return True, 'Block-stale detected! height(%x) < height(%x) or %08x != %08x' % (self.header['previous_block'], previous_block, self.header['bits'].bits, bits.bits)
        
        if self.pow_hash <= self.header['bits'].target:
            return -1, 'block solution'
        
        other_txs = self._get_other_txs(tracker, known_txs)
        if other_txs is None:
            pass
        else:
            all_txs_size = sum(bitcoin_data.tx_type.packed_size(tx) for tx in other_txs)
            if all_txs_size > 1000000:
                return True, 'txs over block size limit'
            
            new_txs_size = sum(bitcoin_data.tx_type.packed_size(known_txs[tx_hash]) for tx_hash in self.share_info['new_transaction_hashes'])
            if new_txs_size > 50000:
                return True, 'new txs over limit'
        
        return False, None
    
    def as_block(self, tracker, known_txs):
        other_txs = self._get_other_txs(tracker, known_txs)
        if other_txs is None:
            return None # not all txs present
        return dict(header=self.header, txs=[self.check(tracker)] + other_txs)


class WeightsSkipList(forest.TrackerSkipList):
    # share_count, weights, total_weight
    
    def get_delta(self, element):
        from p2pool.bitcoin import data as bitcoin_data
        share = self.tracker.items[element]
        att = bitcoin_data.target_to_average_attempts(share.target)
        return 1, {share.new_script: att*(65535-share.share_data['donation'])}, att*65535, att*share.share_data['donation']
    
    def combine_deltas(self, (share_count1, weights1, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2)):
        return share_count1 + share_count2, math.add_dicts(weights1, weights2), total_weight1 + total_weight2, total_donation_weight1 + total_donation_weight2
    
    def initial_solution(self, start, (max_shares, desired_weight)):
        assert desired_weight % 65535 == 0, divmod(desired_weight, 65535)
        return 0, None, 0, 0
    
    def apply_delta(self, (share_count1, weights_list, total_weight1, total_donation_weight1), (share_count2, weights2, total_weight2, total_donation_weight2), (max_shares, desired_weight)):
        if total_weight1 + total_weight2 > desired_weight and share_count2 == 1:
            assert (desired_weight - total_weight1) % 65535 == 0
            script, = weights2.iterkeys()
            new_weights = {script: (desired_weight - total_weight1)//65535*weights2[script]//(total_weight2//65535)}
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

class OkayTracker(forest.Tracker):
    def __init__(self, net):
        forest.Tracker.__init__(self, delta_type=forest.get_attributedelta_type(dict(forest.AttributeDelta.attrs,
            work=lambda share: bitcoin_data.target_to_average_attempts(share.target),
            min_work=lambda share: bitcoin_data.target_to_average_attempts(share.max_target),
        )))
        self.net = net
        self.verified = forest.SubsetTracker(delta_type=forest.get_attributedelta_type(dict(forest.AttributeDelta.attrs,
            work=lambda share: bitcoin_data.target_to_average_attempts(share.target),
        )), subset_of=self)
        self.get_cumulative_weights = WeightsSkipList(self)
    
    def attempt_verify(self, share):
        if share.hash in self.verified.items:
            return True
        height, last = self.get_height_and_last(share.hash)
        if height < self.net.CHAIN_LENGTH + 1 and last is not None:
            raise AssertionError()
        try:
            share.check(self)
        except:
            log.err(None, 'Share check failed: %064x -> %064x' % (share.hash, share.previous_hash if share.previous_hash is not None else 0))
            return False
        else:
            self.verified.add(share)
            return True
    
    def think(self, block_rel_height_func, previous_block, bits, known_txs):
        desired = set()
        bad_peer_addresses = set()
        
        # O(len(self.heads))
        #   make 'unverified heads' set?
        # for each overall head, attempt verification
        # if it fails, attempt on parent, and repeat
        # if no successful verification because of lack of parents, request parent
        bads = []
        for head in set(self.heads) - set(self.verified.heads):
            head_height, last = self.get_height_and_last(head)
            
            for share in self.get_chain(head, head_height if last is None else min(5, max(0, head_height - self.net.CHAIN_LENGTH))):
                if self.attempt_verify(share):
                    break
                bads.append(share.hash)
            else:
                if last is not None:
                    desired.add((
                        self.items[random.choice(list(self.reverse[last]))].peer_addr,
                        last,
                        max(x.timestamp for x in self.get_chain(head, min(head_height, 5))),
                        min(x.target for x in self.get_chain(head, min(head_height, 5))),
                    ))
        for bad in bads:
            assert bad not in self.verified.items
            #assert bad in self.heads
            bad_share = self.items[bad]
            if bad_share.peer_addr is not None:
                bad_peer_addresses.add(bad_share.peer_addr)
            if p2pool.DEBUG:
                print "BAD", bad
            try:
                self.remove(bad)
            except NotImplementedError:
                pass
        
        # try to get at least CHAIN_LENGTH height for each verified head, requesting parents if needed
        for head in list(self.verified.heads):
            head_height, last_hash = self.verified.get_height_and_last(head)
            last_height, last_last_hash = self.get_height_and_last(last_hash)
            # XXX review boundary conditions
            want = max(self.net.CHAIN_LENGTH - head_height, 0)
            can = max(last_height - 1 - self.net.CHAIN_LENGTH, 0) if last_last_hash is not None else last_height
            get = min(want, can)
            #print 'Z', head_height, last_hash is None, last_height, last_last_hash is None, want, can, get
            for share in self.get_chain(last_hash, get):
                if not self.attempt_verify(share):
                    break
            if head_height < self.net.CHAIN_LENGTH and last_last_hash is not None:
                desired.add((
                    self.items[random.choice(list(self.verified.reverse[last_hash]))].peer_addr,
                    last_last_hash,
                    max(x.timestamp for x in self.get_chain(head, min(head_height, 5))),
                    min(x.target for x in self.get_chain(head, min(head_height, 5))),
                ))
        
        # decide best tree
        decorated_tails = sorted((self.score(max(self.verified.tails[tail_hash], key=self.verified.get_work), block_rel_height_func), tail_hash) for tail_hash in self.verified.tails)
        if p2pool.DEBUG:
            print len(decorated_tails), 'tails:'
            for score, tail_hash in decorated_tails:
                print format_hash(tail_hash), score
        best_tail_score, best_tail = decorated_tails[-1] if decorated_tails else (None, None)
        
        # decide best verified head
        decorated_heads = sorted(((
            self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))),
            #self.items[h].peer_addr is None,
            -self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0],
            -self.items[h].time_seen,
        ), h) for h in self.verified.tails.get(best_tail, []))
        if p2pool.DEBUG:
            print len(decorated_heads), 'heads. Top 10:'
            for score, head_hash in decorated_heads[-10:]:
                print '   ', format_hash(head_hash), format_hash(self.items[head_hash].previous_hash), score
        best_head_score, best = decorated_heads[-1] if decorated_heads else (None, None)
        
        if best is not None:
            best_share = self.items[best]
            punish, punish_reason = best_share.should_punish_reason(previous_block, bits, self, known_txs)
            if punish > 0:
                print 'Punishing share for %r! Jumping from %s to %s!' % (punish_reason, format_hash(best), format_hash(best_share.previous_hash))
                best = best_share.previous_hash
            
            timestamp_cutoff = min(int(time.time()), best_share.timestamp) - 3600
            target_cutoff = int(2**256//(self.net.SHARE_PERIOD*best_tail_score[1] + 1) * 2 + .5) if best_tail_score[1] is not None else 2**256-1
        else:
            timestamp_cutoff = int(time.time()) - 24*60*60
            target_cutoff = 2**256-1
        
        if p2pool.DEBUG:
            print 'Desire %i shares. Cutoff: %s old diff>%.2f' % (len(desired), math.format_dt(time.time() - timestamp_cutoff), bitcoin_data.target_to_difficulty(target_cutoff))
            for peer_addr, hash, ts, targ in desired:
                print '   ', None if peer_addr is None else '%s:%i' % peer_addr, format_hash(hash), math.format_dt(time.time() - ts), bitcoin_data.target_to_difficulty(targ), ts >= timestamp_cutoff, targ <= target_cutoff
        
        return best, [(peer_addr, hash) for peer_addr, hash, ts, targ in desired if ts >= timestamp_cutoff], decorated_heads, bad_peer_addresses
    
    def score(self, share_hash, block_rel_height_func):
        # returns approximate lower bound on chain's hashrate in the last self.net.CHAIN_LENGTH*15//16*self.net.SHARE_PERIOD time
        
        head_height = self.verified.get_height(share_hash)
        if head_height < self.net.CHAIN_LENGTH:
            return head_height, None
        
        end_point = self.verified.get_nth_parent_hash(share_hash, self.net.CHAIN_LENGTH*15//16)
        
        block_height = max(block_rel_height_func(share.header['previous_block']) for share in
            self.verified.get_chain(end_point, self.net.CHAIN_LENGTH//16))
        
        return self.net.CHAIN_LENGTH, self.verified.get_delta(share_hash, end_point).work/((0 - block_height + 1)*self.net.PARENT.BLOCK_PERIOD)

def get_pool_attempts_per_second(tracker, previous_share_hash, dist, min_work=False, integer=False):
    assert dist >= 2
    near = tracker.items[previous_share_hash]
    far = tracker.items[tracker.get_nth_parent_hash(previous_share_hash, dist - 1)]
    attempts = tracker.get_delta(near.hash, far.hash).work if not min_work else tracker.get_delta(near.hash, far.hash).min_work
    time = near.timestamp - far.timestamp
    if time <= 0:
        time = 1
    if integer:
        return attempts//time
    return attempts/time

def get_average_stale_prop(tracker, share_hash, lookbehind):
    stales = sum(1 for share in tracker.get_chain(share_hash, lookbehind) if share.share_data['stale_info'] is not None)
    return stales/(lookbehind + stales)

def get_stale_counts(tracker, share_hash, lookbehind, rates=False):
    res = {}
    for share in tracker.get_chain(share_hash, lookbehind - 1):
        res['good'] = res.get('good', 0) + bitcoin_data.target_to_average_attempts(share.target)
        s = share.share_data['stale_info']
        if s is not None:
            res[s] = res.get(s, 0) + bitcoin_data.target_to_average_attempts(share.target)
    if rates:
        dt = tracker.items[share_hash].timestamp - tracker.items[tracker.get_nth_parent_hash(share_hash, lookbehind - 1)].timestamp
        res = dict((k, v/dt) for k, v in res.iteritems())
    return res

def get_user_stale_props(tracker, share_hash, lookbehind):
    res = {}
    for share in tracker.get_chain(share_hash, lookbehind - 1):
        stale, total = res.get(share.share_data['pubkey_hash'], (0, 0))
        total += 1
        if share.share_data['stale_info'] is not None:
            stale += 1
            total += 1
        res[share.share_data['pubkey_hash']] = stale, total
    return dict((pubkey_hash, stale/total) for pubkey_hash, (stale, total) in res.iteritems())

def get_expected_payouts(tracker, best_share_hash, block_target, subsidy, net):
    weights, total_weight, donation_weight = tracker.get_cumulative_weights(best_share_hash, min(tracker.get_height(best_share_hash), net.REAL_CHAIN_LENGTH), 65535*net.SPREAD*bitcoin_data.target_to_average_attempts(block_target))
    res = dict((script, subsidy*weight//total_weight) for script, weight in weights.iteritems())
    res[DONATION_SCRIPT] = res.get(DONATION_SCRIPT, 0) + subsidy - sum(res.itervalues())
    return res

def get_desired_version_counts(tracker, best_share_hash, dist):
    res = {}
    for share in tracker.get_chain(best_share_hash, dist):
        res[share.desired_version] = res.get(share.desired_version, 0) + bitcoin_data.target_to_average_attempts(share.target)
    return res

def get_warnings(tracker, best_share, net, bitcoind_getinfo, bitcoind_work_value):
    res = []
    
    desired_version_counts = get_desired_version_counts(tracker, best_share,
        min(net.CHAIN_LENGTH, 60*60//net.SHARE_PERIOD, tracker.get_height(best_share)))
    majority_desired_version = max(desired_version_counts, key=lambda k: desired_version_counts[k])
    if majority_desired_version > (Share.SUCCESSOR if Share.SUCCESSOR is not None else Share).VOTING_VERSION and desired_version_counts[majority_desired_version] > sum(desired_version_counts.itervalues())/2:
        res.append('A MAJORITY OF SHARES CONTAIN A VOTE FOR AN UNSUPPORTED SHARE IMPLEMENTATION! (v%i with %i%% support)\n'
            'An upgrade is likely necessary. Check http://p2pool.forre.st/ for more information.' % (
                majority_desired_version, 100*desired_version_counts[majority_desired_version]/sum(desired_version_counts.itervalues())))
    
    if bitcoind_getinfo['errors'] != '':
        if 'This is a pre-release test build' not in bitcoind_getinfo['errors']:
            res.append('(from bitcoind) %s' % (bitcoind_getinfo['errors'],))
    
    version_warning = getattr(net, 'VERSION_WARNING', lambda v: None)(bitcoind_getinfo['version'])
    if version_warning is not None:
        res.append(version_warning)
    
    if time.time() > bitcoind_work_value['last_update'] + 60:
        res.append('''LOST CONTACT WITH BITCOIND for %s! Check that it isn't frozen or dead!''' % (math.format_dt(time.time() - bitcoind_work_value['last_update']),))
    
    return res

def format_hash(x):
    if x is None:
        return 'xxxxxxxx'
    return '%08x' % (x % 2**32)

class ShareStore(object):
    def __init__(self, prefix, net, share_cb, verified_hash_cb):
        self.dirname = os.path.dirname(os.path.abspath(prefix))
        self.filename = os.path.basename(os.path.abspath(prefix))
        self.net = net
        
        known = {}
        filenames, next = self.get_filenames_and_next()
        for filename in filenames:
            share_hashes, verified_hashes = known.setdefault(filename, (set(), set()))
            with open(filename, 'rb') as f:
                for line in f:
                    try:
                        type_id_str, data_hex = line.strip().split(' ')
                        type_id = int(type_id_str)
                        if type_id == 0:
                            pass
                        elif type_id == 1:
                            pass
                        elif type_id == 2:
                            verified_hash = int(data_hex, 16)
                            verified_hash_cb(verified_hash)
                            verified_hashes.add(verified_hash)
                        elif type_id == 5:
                            raw_share = share_type.unpack(data_hex.decode('hex'))
                            if raw_share['type'] < Share.VERSION:
                                continue
                            share = load_share(raw_share, self.net, None)
                            share_cb(share)
                            share_hashes.add(share.hash)
                        else:
                            raise NotImplementedError("share type %i" % (type_id,))
                    except Exception:
                        log.err(None, "HARMLESS error while reading saved shares, continuing where left off:")
        
        self.known = known # filename -> (set of share hashes, set of verified hashes)
        self.known_desired = dict((k, (set(a), set(b))) for k, (a, b) in known.iteritems())
    
    def _add_line(self, line):
        filenames, next = self.get_filenames_and_next()
        if filenames and os.path.getsize(filenames[-1]) < 10e6:
            filename = filenames[-1]
        else:
            filename = next
        
        with open(filename, 'ab') as f:
            f.write(line + '\n')
        
        return filename
    
    def add_share(self, share):
        for filename, (share_hashes, verified_hashes) in self.known.iteritems():
            if share.hash in share_hashes:
                break
        else:
            filename = self._add_line("%i %s" % (5, share_type.pack(share.as_share()).encode('hex')))
            share_hashes, verified_hashes = self.known.setdefault(filename, (set(), set()))
            share_hashes.add(share.hash)
        share_hashes, verified_hashes = self.known_desired.setdefault(filename, (set(), set()))
        share_hashes.add(share.hash)
    
    def add_verified_hash(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known.iteritems():
            if share_hash in verified_hashes:
                break
        else:
            filename = self._add_line("%i %x" % (2, share_hash))
            share_hashes, verified_hashes = self.known.setdefault(filename, (set(), set()))
            verified_hashes.add(share_hash)
        share_hashes, verified_hashes = self.known_desired.setdefault(filename, (set(), set()))
        verified_hashes.add(share_hash)
    
    def get_filenames_and_next(self):
        suffixes = sorted(int(x[len(self.filename):]) for x in os.listdir(self.dirname) if x.startswith(self.filename) and x[len(self.filename):].isdigit())
        return [os.path.join(self.dirname, self.filename + str(suffix)) for suffix in suffixes], os.path.join(self.dirname, self.filename + (str(suffixes[-1] + 1) if suffixes else str(0)))
    
    def forget_share(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            if share_hash in share_hashes:
                share_hashes.remove(share_hash)
        self.check_remove()
    
    def forget_verified_share(self, share_hash):
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            if share_hash in verified_hashes:
                verified_hashes.remove(share_hash)
        self.check_remove()
    
    def check_remove(self):
        to_remove = set()
        for filename, (share_hashes, verified_hashes) in self.known_desired.iteritems():
            #print filename, len(share_hashes) + len(verified_hashes)
            if not share_hashes and not verified_hashes:
                to_remove.add(filename)
        for filename in to_remove:
            self.known.pop(filename)
            self.known_desired.pop(filename)
            os.remove(filename)
            print "REMOVED", filename
