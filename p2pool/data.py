from __future__ import division

import hashlib
import os
import random
import sys
import time
import array
import traceback

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
    import sys
    # Debug: Uncomment to trace hash_link SHA256 internals (confirmed working)
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] prefix length: %d' % len(prefix)
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] const_ending length: %d' % len(const_ending)
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] const_ending: %s' % const_ending.encode('hex')
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] last 50 bytes of prefix: %s' % prefix[-50:].encode('hex')
    
    assert prefix.endswith(const_ending), (prefix, const_ending)
    x = sha256.sha256(prefix)
    
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] SHA256 state: %s (len=%d)' % (x.state.encode('hex'), len(x.state))
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] SHA256 buf: %s (len=%d)' % (x.buf.encode('hex'), len(x.buf))
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] SHA256 length: %d' % x.length
    extra_data = x.buf[:max(0, len(x.buf)-len(const_ending))]
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] extra_data: %s (len=%d)' % (extra_data.encode('hex'), len(extra_data))
    # print >>sys.stderr, '[PREFIX_TO_HASH_LINK] length//8: %d' % (x.length//8)
    
    return dict(state=x.state, extra_data=extra_data, length=x.length//8)

def check_hash_link(hash_link, data, const_ending=''):
    # Debug: Uncomment to trace hash_link validation (confirmed working)
    # import sys
    # print >>sys.stderr, '[CHECK_HASH_LINK] hash_link[length]: %d' % hash_link['length']
    # print >>sys.stderr, '[CHECK_HASH_LINK] hash_link[state]: %s (len=%d)' % (hash_link['state'].encode('hex'), len(hash_link['state']))
    # print >>sys.stderr, '[CHECK_HASH_LINK] hash_link[extra_data]: %s (len=%d)' % (hash_link['extra_data'].encode('hex'), len(hash_link['extra_data']))
    # print >>sys.stderr, '[CHECK_HASH_LINK] data: %s (len=%d)' % (data.encode('hex'), len(data))
    # print >>sys.stderr, '[CHECK_HASH_LINK] const_ending: %s (len=%d)' % (const_ending.encode('hex'), len(const_ending))
    
    extra_length = hash_link['length'] % (512//8)
    assert len(hash_link['extra_data']) == max(0, extra_length - len(const_ending))
    extra = (hash_link['extra_data'] + const_ending)[len(hash_link['extra_data']) + len(const_ending) - extra_length:]
    assert len(extra) == extra_length
    
    # print >>sys.stderr, '[CHECK_HASH_LINK] extra_length: %d' % extra_length
    # print >>sys.stderr, '[CHECK_HASH_LINK] extra: %s' % extra.encode('hex')
    # print >>sys.stderr, '[CHECK_HASH_LINK] About to reconstruct hash with:'
    # print >>sys.stderr, '[CHECK_HASH_LINK]   state: %s' % hash_link['state'].encode('hex')
    # print >>sys.stderr, '[CHECK_HASH_LINK]   extra: %s' % extra.encode('hex')
    # print >>sys.stderr, '[CHECK_HASH_LINK]   length*8: %d' % (8*hash_link['length'])
    # print >>sys.stderr, '[CHECK_HASH_LINK]   data to hash: %s' % data.encode('hex')
    
    result = pack.IntType(256).unpack(hashlib.sha256(sha256.sha256(data, (hash_link['state'], extra, 8*hash_link['length'])).digest()).digest())
    # print >>sys.stderr, '[CHECK_HASH_LINK] Reconstructed gentx_hash: %064x' % result
    return result

# shares

share_type = pack.ComposedType([
    ('type', pack.VarIntType()),
    ('contents', pack.VarStrType()),
])

def load_share(share, net, peer_addr):
    assert peer_addr is None or isinstance(peer_addr, tuple)
    if share['type'] in share_versions:
        net.PARENT.padding_bugfix = (share['type'] >= 35)
        return share_versions[share['type']](net, peer_addr, share_versions[share['type']].get_dynamic_types(net)['share_type'].unpack(share['contents']))

    elif share['type'] < Share.VERSION:
        from p2pool import p2p
        raise p2p.PeerMisbehavingError('sent an obsolete share')
    else:
        raise ValueError('unknown share type: %r' % (share['type'],))

def is_segwit_activated(version, net):
    assert not(version is None or net is None)
    segwit_activation_version = getattr(net, 'SEGWIT_ACTIVATION_VERSION', 0)
    return version >= segwit_activation_version and segwit_activation_version > 0

# P2PKH donation script (modern format) - Dash address: XdgF55wEHBRWwbuBniNYH4GvvaoYMgL84u
# Format: OP_DUP OP_HASH160 <20-byte pubkey_hash> OP_EQUALVERIFY OP_CHECKSIG
DONATION_SCRIPT = '76a91420cb5c22b1e4d5947e5c112c7696b51ad9af3c6188ac'.decode('hex')
def donation_script_to_address(net):
    try:
        return bitcoin_data.script2_to_address(
                DONATION_SCRIPT, net.PARENT.ADDRESS_VERSION, -1, net.PARENT)
    except ValueError:
        return bitcoin_data.script2_to_address(
                DONATION_SCRIPT, net.PARENT.ADDRESS_P2SH_VERSION, -1, net.PARENT)

class BaseShare(object):
    VERSION = 0
    VOTING_VERSION = 0
    SUCCESSOR = None
    MINIMUM_PROTOCOL_VERSION = 1400
    
    small_block_header_type = pack.ComposedType([
        ('version', pack.VarIntType()),
        ('previous_block', pack.PossiblyNoneType(0, pack.IntType(256))),
        ('timestamp', pack.IntType(32)),
        ('bits', bitcoin_data.FloatingIntegerType()),
        ('nonce', pack.IntType(32)),
    ])
    share_info_type = None
    share_type = None
    ref_type = None

    gentx_before_refhash = pack.VarStrType().pack(DONATION_SCRIPT) + pack.IntType(64).pack(0) + pack.VarStrType().pack('\x6a\x28' + pack.IntType(256).pack(0) + pack.IntType(64).pack(0))[:3]

    gentx_size = 50000 # conservative estimate, will be overwritten during execution
    gentx_weight = 200000
    cached_types = None
    @classmethod
    def get_dynamic_types(cls, net):
        if not cls.cached_types == None:
            return cls.cached_types
        t = dict(share_info_type=None, share_type=None, ref_type=None)
        segwit_data = ('segwit_data', pack.PossiblyNoneType(dict(txid_merkle_link=dict(branch=[], index=0), wtxid_merkle_root=2**256-1), pack.ComposedType([
            ('txid_merkle_link', pack.ComposedType([
                ('branch', pack.ListType(pack.IntType(256))),
                ('index', pack.IntType(0)), # it will always be 0
            ])),
            ('wtxid_merkle_root', pack.IntType(256))
        ])))
        t['share_info_type'] = pack.ComposedType([
            ('share_data', pack.ComposedType([
                ('previous_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
                ('coinbase', pack.VarStrType()),
                ('nonce', pack.IntType(32)),
                ] + ([('address', pack.VarStrType())]
                        if cls.VERSION >= 34
                            else [('pubkey_hash', pack.IntType(160))]) + [
                ('subsidy', pack.IntType(64)),
                ('donation', pack.IntType(16)),
                ('stale_info', pack.EnumType(pack.IntType(8), dict((k, {0: None, 253: 'orphan', 254: 'doa'}.get(k, 'unk%i' % (k,))) for k in xrange(256)))),
                ('desired_version', pack.VarIntType()),
            ]))] + ([segwit_data] if is_segwit_activated(cls.VERSION, net) else []) + ([
            ('new_transaction_hashes', pack.ListType(pack.IntType(256))),
            ('transaction_hash_refs', pack.ListType(pack.VarIntType(), 2)), # pairs of share_count, tx_count
            ] if cls.VERSION < 34 else []) + [
            ('far_share_hash', pack.PossiblyNoneType(0, pack.IntType(256))),
            ('max_bits', bitcoin_data.FloatingIntegerType()),
            ('bits', bitcoin_data.FloatingIntegerType()),
            ('timestamp', pack.IntType(32)),
            ('absheight', pack.IntType(32)),
            ('abswork', pack.IntType(128)),
        ])
        t['share_type'] = pack.ComposedType([
            ('min_header', cls.small_block_header_type),
            ('share_info', t['share_info_type']),
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
            ('actual_header_merkle_root', pack.PossiblyNoneType(0, pack.IntType(256))),  # For merged mining - stores the actual mined merkle_root
        ])
        t['ref_type'] = pack.ComposedType([
            ('identifier', pack.FixedStrType(64//8)),
            ('share_info', t['share_info_type']),
        ])
        cls.cached_types = t
        return t

    @classmethod
    def generate_transaction(cls, tracker, share_data, block_target, desired_timestamp, desired_target, ref_merkle_link, desired_other_transaction_hashes_and_fees, net, known_txs=None, last_txout_nonce=0, base_subsidy=None, segwit_data=None):
        t0 = time.time()
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
        new_transaction_size = 0 # including witnesses
        all_transaction_stripped_size = 0 # stripped size
        all_transaction_real_size = 0 # including witnesses, for statistics
        new_transaction_weight = 0
        all_transaction_weight = 0
        transaction_hash_refs = []
        other_transaction_hashes = []
        t1 = time.time()
        tx_hash_to_this = {}
        if cls.VERSION < 34:
            past_shares = list(tracker.get_chain(share_data['previous_share_hash'], min(height, 100)))
            for i, share in enumerate(past_shares):
                for j, tx_hash in enumerate(share.new_transaction_hashes):
                    if tx_hash not in tx_hash_to_this:
                        tx_hash_to_this[tx_hash] = [1+i, j] # share_count, tx_count

        t2 = time.time()
        for tx_hash, fee in desired_other_transaction_hashes_and_fees:
            if known_txs is not None:
                this_stripped_size = bitcoin_data.get_stripped_size(known_txs[tx_hash])
                this_real_size     = bitcoin_data.get_size(known_txs[tx_hash])
                this_weight        = this_real_size + 3*this_stripped_size
            else: # we're just verifying someone else's share. We'll calculate sizes in should_punish_reason()
                this_stripped_size = 0
                this_real_size = 0
                this_weight = 0

            if all_transaction_stripped_size + this_stripped_size + 80 + cls.gentx_size +  500 > net.BLOCK_MAX_SIZE:
                break
            if all_transaction_weight + this_weight + 4*80 + cls.gentx_weight + 2000 > net.BLOCK_MAX_WEIGHT:
                break

            if tx_hash in tx_hash_to_this:
                this = tx_hash_to_this[tx_hash]
                if known_txs is not None:
                    all_transaction_stripped_size += this_stripped_size
                    all_transaction_real_size += this_real_size
                    all_transaction_weight += this_weight
            else:
                if known_txs is not None:
                    new_transaction_size += this_real_size
                    all_transaction_stripped_size += this_stripped_size
                    all_transaction_real_size += this_real_size
                    new_transaction_weight += this_weight
                    all_transaction_weight += this_weight
                new_transaction_hashes.append(tx_hash)
                this = [0, len(new_transaction_hashes)-1]
            transaction_hash_refs.extend(this)
            other_transaction_hashes.append(tx_hash)

        t3 = time.time()
        if transaction_hash_refs and max(transaction_hash_refs) < 2**16:
            transaction_hash_refs = array.array('H', transaction_hash_refs)
        elif transaction_hash_refs and max(transaction_hash_refs) < 2**32: # in case we see blocks with more than 65536 tx
            transaction_hash_refs = array.array('L', transaction_hash_refs)
        t4 = time.time()

        if all_transaction_stripped_size and p2pool.DEBUG:
            print "Generating a share with %i bytes, %i WU (new: %i B, %i WU) in %i tx (%i new), plus est gentx of %i bytes/%i WU" % (
                all_transaction_real_size,
                all_transaction_weight,
                new_transaction_size,
                new_transaction_weight,
                len(other_transaction_hashes),
                len(new_transaction_hashes),
                cls.gentx_size,
                cls.gentx_weight)
            print "Total block stripped size=%i B, full size=%i B,  weight: %i WU" % (
                80+all_transaction_stripped_size+cls.gentx_size, 
                80+all_transaction_real_size+cls.gentx_size, 
                3*80+all_transaction_weight+cls.gentx_weight)

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
        if 'address' not in share_data:
            this_address = bitcoin_data.pubkey_hash_to_address(
                    share_data['pubkey_hash'], net.PARENT.ADDRESS_VERSION,
                    -1, net.PARENT)
        else:
            this_address = share_data['address']
        donation_address = donation_script_to_address(net)
        # 0.5% goes to block finder
        amounts[this_address] = amounts.get(this_address, 0) \
                                + share_data['subsidy']//200
        # all that's left over is the donation weight and some extra
        # satoshis due to rounding
        amounts[donation_address] = amounts.get(donation_address, 0) \
                                    + share_data['subsidy'] \
                                    - sum(amounts.itervalues())
        if cls.VERSION < 34 and 'pubkey_hash' not in share_data:
            share_data['pubkey_hash'], _, _ = bitcoin_data.address_to_pubkey_hash(
                    this_address, net.PARENT)
            del(share_data['address'])
        
        if sum(amounts.itervalues()) != share_data['subsidy'] or any(x < 0 for x in amounts.itervalues()):
            raise ValueError()

        # block length limit, unlikely to ever be hit
        dests = sorted(amounts.iterkeys(), key=lambda address: (
            address == donation_address, amounts[address], address))[-4000:]
        if len(dests) >= 200:
            print "found %i payment dests. Antminer S9s may crash when this is close to 226." % len(dests)

        segwit_activated = is_segwit_activated(cls.VERSION, net)
        if segwit_data is None and known_txs is None:
            segwit_activated = False
        if not(segwit_activated or known_txs is None) and any(bitcoin_data.is_segwit_tx(known_txs[h]) for h in other_transaction_hashes):
            raise ValueError('segwit transaction included before activation')
        if segwit_activated and known_txs is not None:
            # Build list of (tx, txid) tuples for share transactions
            share_txs = [(known_txs[h], bitcoin_data.get_txid(known_txs[h])) for h in other_transaction_hashes]
            # IMPORTANT: For wtxid calculation, do NOT pass 'h' as txhash - 'h' is the txid (lookup key),
            # not the wtxid. Pass None for txhash so get_wtxid() computes the actual wtxid by hashing
            # the full transaction including witness data.
            segwit_data = dict(txid_merkle_link=bitcoin_data.calculate_merkle_link([None] + [tx[1] for tx in share_txs], 0), wtxid_merkle_root=bitcoin_data.merkle_hash([0] + [bitcoin_data.get_wtxid(tx[0], tx[1], None) for tx in share_txs]))
        if segwit_activated and segwit_data is not None:
            witness_reserved_value_str = '[P2Pool]'*4
            witness_reserved_value = pack.IntType(256).unpack(witness_reserved_value_str)
            witness_commitment_hash = bitcoin_data.get_witness_commitment_hash(segwit_data['wtxid_merkle_root'], witness_reserved_value)

        share_info = dict(
            share_data=share_data,
            far_share_hash=None if last is None and height < 99 else tracker.get_nth_parent_hash(share_data['previous_share_hash'], 99),
            max_bits=max_bits,
            bits=bits,

            timestamp=(math.clip(desired_timestamp, (
                        (previous_share.timestamp + net.SHARE_PERIOD) - (net.SHARE_PERIOD - 1), # = previous_share.timestamp + 1
                        (previous_share.timestamp + net.SHARE_PERIOD) + (net.SHARE_PERIOD - 1),)) if previous_share is not None else desired_timestamp
                      ) if cls.VERSION < 32 else
                      max(desired_timestamp, (previous_share.timestamp + 1)) if previous_share is not None else desired_timestamp,
            absheight=((previous_share.absheight if previous_share is not None else 0) + 1) % 2**32,
            abswork=((previous_share.abswork if previous_share is not None else 0) + bitcoin_data.target_to_average_attempts(bits.target)) % 2**128,
        )
        if cls.VERSION < 34:
            share_info['new_transaction_hashes'] = new_transaction_hashes
            share_info['transaction_hash_refs'] = transaction_hash_refs

        if previous_share != None and desired_timestamp > previous_share.timestamp + 180:
            print "Warning: Previous share's timestamp is %i seconds old." % int(desired_timestamp - previous_share.timestamp)
            print "Make sure your system clock is accurate, and ensure that you're connected to decent peers."
            print "If your clock is more than 300 seconds behind, it can result in orphaned shares."
            print "(It's also possible that this share is just taking a long time to mine.)"
        if previous_share != None and previous_share.timestamp > int(time.time()) + 3:
            print "WARNING! Previous share's timestamp is %i seconds in the future. This is not normal." % \
                   int(previous_share.timestamp - (int(time.time())))
            print "Make sure your system clock is accurate. Errors beyond 300 sec result in orphaned shares."

        if segwit_activated:
            share_info['segwit_data'] = segwit_data
        
        payouts = [dict(value=amounts[addr],
                        script=bitcoin_data.address_to_script2(addr, net.PARENT)
                        ) for addr in dests if amounts[addr] and addr != donation_address]
        payouts.append({'script': DONATION_SCRIPT, 'value': amounts[donation_address]})
        
        # Debug: Uncomment to trace payout structure (confirmed working)
        # import sys
        # print >>sys.stderr, '[PAYOUT DEBUG] Number of payout outputs: %d' % len(payouts)
        # for i, payout in enumerate(payouts):
        #     script_address = 'unknown'
        #     try:
        #         script_address = bitcoin_data.script2_to_address(payout['script'], net.PARENT)[:20] + '...'
        #     except:
        #         pass
        #     print >>sys.stderr, '[PAYOUT DEBUG]   Output %d: value=%d, script_len=%d, addr=%s' % (i, payout['value'], len(payout['script']), script_address)

        gentx = dict(
            version=1,
            tx_ins=[dict(
                previous_output=None,
                sequence=None,
                script=share_data['coinbase'],
            )],
            tx_outs=([dict(value=0, script='\x6a\x24\xaa\x21\xa9\xed' \
                                           + pack.IntType(256).pack(
                                                witness_commitment_hash))]
                                           if segwit_activated else []) \
                    + payouts \
                    + [dict(value=0, script='\x6a\x28' + cls.get_ref_hash(
                        net, share_info, ref_merkle_link) \
                                + pack.IntType(64).pack(last_txout_nonce))],
            lock_time=0,
        )
        
        # Debug: Uncomment to trace gentx creation (confirmed working)
        # import sys
        # print >>sys.stderr, '[GENTX CREATION] coinbase script length: %d bytes' % len(share_data['coinbase'])
        # print >>sys.stderr, '[GENTX CREATION] coinbase script hex: %s' % share_data['coinbase'].encode('hex')
        # print >>sys.stderr, '[GENTX CREATION] num payouts: %d' % len(payouts)
        # print >>sys.stderr, '[GENTX CREATION] total outputs: %d' % (len(gentx['tx_outs']))
        
        # DEBUG: Verify gentx_before_refhash structure
        packed_gentx = bitcoin_data.tx_id_type.pack(gentx)
        cutoff_prefix = packed_gentx[:-32-8-4]  # Remove ref_hash + nonce + lock_time
        # Debug: Uncomment to trace gentx validation (confirmed working)
        #print >>sys.stderr, '[GENTX DEBUG] Total packed length: %d bytes' % len(packed_gentx)
        #print >>sys.stderr, '[GENTX DEBUG] Prefix length (after cut): %d bytes' % len(cutoff_prefix)
        #print >>sys.stderr, '[GENTX DEBUG] gentx_before_refhash length: %d bytes' % len(cls.gentx_before_refhash)
        #print >>sys.stderr, '[GENTX DEBUG] Last 50 bytes of prefix: %s' % cutoff_prefix[-50:].encode('hex')
        #print >>sys.stderr, '[GENTX DEBUG] gentx_before_refhash: %s' % cls.gentx_before_refhash.encode('hex')
        if not cutoff_prefix.endswith(cls.gentx_before_refhash):
            # Keep ERROR logs - these indicate actual problems
            print >>sys.stderr, '[GENTX ERROR] Prefix does NOT end with gentx_before_refhash!'
            print >>sys.stderr, '[GENTX ERROR] Expected ending: %s' % cls.gentx_before_refhash.encode('hex')
            print >>sys.stderr, '[GENTX ERROR] Actual ending:   %s' % cutoff_prefix[-len(cls.gentx_before_refhash):].encode('hex')
        #else:
            #print >>sys.stderr, '[GENTX DEBUG] OK: Prefix ends with gentx_before_refhash'
        
        if segwit_activated:
            gentx['marker'] = 0
            gentx['flag'] = 1
            gentx['witness'] = [[witness_reserved_value_str]]
        
        def get_share(header, last_txout_nonce=last_txout_nonce):
            min_header = dict(header); del min_header['merkle_root']
            share = cls(net, None, dict(
                min_header=min_header,
                share_info=share_info,
                ref_merkle_link=dict(branch=[], index=0),
                last_txout_nonce=last_txout_nonce,
                hash_link=prefix_to_hash_link(bitcoin_data.tx_id_type.pack(gentx)[:-32-8-4], cls.gentx_before_refhash),
                merkle_link=bitcoin_data.calculate_merkle_link([None] + other_transaction_hashes, 0),
                actual_header_merkle_root=header['merkle_root'],  # Pass the actual mined merkle_root for merged mining
            ))
            assert share.header == header # checks merkle_root
            return share
        t5 = time.time()
        if p2pool.BENCH: print "%8.3f ms for data.py:generate_transaction(). Parts: %8.3f %8.3f %8.3f %8.3f %8.3f " % (
            (t5-t0)*1000.,
            (t1-t0)*1000.,
            (t2-t1)*1000.,
            (t3-t2)*1000.,
            (t4-t3)*1000.,
            (t5-t4)*1000.)
        return share_info, gentx, other_transaction_hashes, get_share
    
    @classmethod
    def get_ref_hash(cls, net, share_info, ref_merkle_link):
        return pack.IntType(256).pack(bitcoin_data.check_merkle_link(bitcoin_data.hash256(cls.get_dynamic_types(net)['ref_type'].pack(dict(
            identifier=net.IDENTIFIER,
            share_info=share_info,
        ))), ref_merkle_link))
    
    __slots__ = 'net peer_addr contents min_header share_info hash_link merkle_link hash share_data max_target target timestamp previous_hash new_script desired_version gentx_hash header pow_hash header_hash new_transaction_hashes time_seen absheight abswork'.split(' ')
    
    def __init__(self, net, peer_addr, contents):
        dynamic_types = self.get_dynamic_types(net)
        self.share_info_type = dynamic_types['share_info_type']
        self.share_type = dynamic_types['share_type']
        self.ref_type = dynamic_types['ref_type']

        self.net = net
        self.peer_addr = peer_addr
        self.contents = contents
        
        self.min_header = contents['min_header']
        self.share_info = contents['share_info']
        self.hash_link = contents['hash_link']
        self.merkle_link = contents['merkle_link']
        self.naughty = 0

        # save some memory if we can
        if self.VERSION < 34:
            txrefs = self.share_info['transaction_hash_refs']
            if txrefs and max(txrefs) < 2**16:
                self.share_info['transaction_hash_refs'] = array.array('H', txrefs)
            elif txrefs and max(txrefs) < 2**32: # in case we see blocks with more than 65536 tx in the future
                self.share_info['transaction_hash_refs'] = array.array('L', txrefs)
        
        segwit_activated = is_segwit_activated(self.VERSION, net)
        
        if not (2 <= len(self.share_info['share_data']['coinbase']) <= 100):
            raise ValueError('''bad coinbase size! %i bytes''' % (len(self.share_info['share_data']['coinbase']),))
        
        assert not self.hash_link['extra_data'], repr(self.hash_link['extra_data'])
        
        self.share_data = self.share_info['share_data']
        self.max_target = self.share_info['max_bits'].target
        self.target = self.share_info['bits'].target
        self.timestamp = self.share_info['timestamp']
        self.previous_hash = self.share_data['previous_share_hash']
        if self.VERSION >= 34:
            self.new_script = bitcoin_data.address_to_script2(
                    self.share_data['address'], net.PARENT)
            self.address = self.share_data['address']
        else:
            self.new_script = bitcoin_data.pubkey_hash_to_script2(
                    self.share_data['pubkey_hash'],
                    net.PARENT.ADDRESS_VERSION, -1, net.PARENT)
            self.address = bitcoin_data.pubkey_hash_to_address(
                    self.share_data['pubkey_hash'],
                    net.PARENT.ADDRESS_VERSION, -1, net.PARENT)
        self.desired_version = self.share_data['desired_version']
        self.absheight = self.share_info['absheight']
        self.abswork = self.share_info['abswork']
        if net.NAME == 'bitcoin' and self.absheight > 3927800 and self.desired_version == 16:
            raise ValueError("This is not a hardfork-supporting share!")
        
        if self.VERSION < 34:
            n = set()
            for share_count, tx_count in self.iter_transaction_hash_refs():
                assert share_count < 110
                if share_count == 0:
                    n.add(tx_count)
            assert n == set(range(len(self.share_info['new_transaction_hashes'])))
        
        # Debug: Uncomment to trace share validation (confirmed working)
        # import sys
        # print >>sys.stderr, '[VALIDATION] coinbase script length: %d bytes' % len(self.share_info['share_data']['coinbase'])
        # print >>sys.stderr, '[VALIDATION] coinbase script hex: %s' % self.share_info['share_data']['coinbase'].encode('hex')
        
        self.gentx_hash = check_hash_link(
            self.hash_link,
            self.get_ref_hash(net, self.share_info, contents['ref_merkle_link']) + pack.IntType(64).pack(self.contents['last_txout_nonce']) + pack.IntType(32).pack(0),
            self.gentx_before_refhash,
        )
        # For merged mining, use the actual mined merkle_root if provided (contains merged mining commitment)
        # Otherwise reconstruct it from gentx_hash and merkle_link (normal p2pool operation)
        if contents.get('actual_header_merkle_root') is not None:
            merkle_root = contents['actual_header_merkle_root']
        else:
            merkle_root = bitcoin_data.check_merkle_link(self.gentx_hash, self.share_info['segwit_data']['txid_merkle_link'] if segwit_activated else self.merkle_link)
        self.header = dict(self.min_header, merkle_root=merkle_root)
        
        # Debug: Uncomment to trace share creation (prints on every share)
        # import sys
        # print >>sys.stderr, '[SHARE __init__] Calculated merkle_root: %064x' % merkle_root
        # print >>sys.stderr, '[SHARE __init__] gentx_hash: %064x' % self.gentx_hash
        # print >>sys.stderr, '[SHARE __init__] merkle_link branches: %d' % len(self.merkle_link['branch'])
        
        self.pow_hash = net.PARENT.POW_FUNC(bitcoin_data.block_header_type.pack(self.header))
        self.hash = self.header_hash = bitcoin_data.hash256(bitcoin_data.block_header_type.pack(self.header))
        
        # Debug: Uncomment to trace share validation (prints on every share)
        # import sys
        # print >>sys.stderr, '[SHARE VALIDATION DEBUG]'
        # print >>sys.stderr, '  gentx_hash:  %064x' % self.gentx_hash
        # print >>sys.stderr, '  merkle_root: %064x' % merkle_root
        # print >>sys.stderr, '  pow_hash:    %064x' % self.pow_hash
        # print >>sys.stderr, '  target:      %064x' % self.target
        # print >>sys.stderr, '  passes:      %s' % (self.pow_hash <= self.target)
        
        if self.target > net.MAX_TARGET:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('share target invalid')
        
        if self.pow_hash > self.target:
            from p2pool import p2p
            raise p2p.PeerMisbehavingError('share PoW invalid')
        
        if self.VERSION < 34:
            self.new_transaction_hashes = self.share_info['new_transaction_hashes']
        
        # XXX eww
        self.time_seen = time.time()
    
    def __repr__(self):
        return 'Share' + repr((self.net, self.peer_addr, self.contents))
    
    def as_share(self):
        return dict(type=self.VERSION, contents=self.share_type.pack(self.contents))
    
    def iter_transaction_hash_refs(self):
        try:
            return zip(self.share_info['transaction_hash_refs'][::2], self.share_info['transaction_hash_refs'][1::2])
        except AttributeError:
            return zip()
        except KeyError:
            return zip()

    def check(self, tracker, known_txs=None, block_abs_height_func=None, feecache=None):
        from p2pool import p2p
        if self.timestamp > int(time.time()) + 600:
            raise ValueError("Share timestamp is %i seconds in the future! Check your system clock." % \
                self.timestamp - int(time.time()))
        counts = None
        if self.share_data['previous_share_hash'] is not None and block_abs_height_func is not None:
            previous_share = tracker.items[self.share_data['previous_share_hash']]
            if tracker.get_height(self.share_data['previous_share_hash']) >= self.net.CHAIN_LENGTH:
                counts = get_desired_version_counts(tracker, tracker.get_nth_parent_hash(previous_share.hash, self.net.CHAIN_LENGTH*9//10), self.net.CHAIN_LENGTH//10)
                if type(self) is type(previous_share):
                    pass
                elif type(self) is type(previous_share).SUCCESSOR:
                    # switch only valid if 60% of hashes in [self.net.CHAIN_LENGTH*9//10, self.net.CHAIN_LENGTH] for new version
                    if counts.get(self.VERSION, 0) < sum(counts.itervalues())*60//100:
                        raise p2p.PeerMisbehavingError('switch without enough hash power upgraded')
                else:
                    raise p2p.PeerMisbehavingError('''%s can't follow %s''' % (type(self).__name__, type(previous_share).__name__))
            elif type(self) is type(previous_share).SUCCESSOR:
                raise p2p.PeerMisbehavingError('switch without enough history')
        
        if self.VERSION < 34:
            other_tx_hashes = [tracker.items[tracker.get_nth_parent_hash(self.hash, share_count)].share_info['new_transaction_hashes'][tx_count] for share_count, tx_count in self.iter_transaction_hash_refs()]
        else:
            other_tx_hashes = []
        if known_txs is not None and not isinstance(known_txs, dict):
            print "Performing maybe-unnecessary packing and hashing"
            known_txs = dict((bitcoin_data.hash256(bitcoin_data.tx_type.pack(tx)), tx) for tx in known_txs)
        
        share_info, gentx, other_tx_hashes2, get_share = self.generate_transaction(tracker, self.share_info['share_data'], self.header['bits'].target, self.share_info['timestamp'], self.share_info['bits'].target, self.contents['ref_merkle_link'], [(h, None) for h in other_tx_hashes], self.net,
            known_txs=None, last_txout_nonce=self.contents['last_txout_nonce'], segwit_data=self.share_info.get('segwit_data', None))

        if self.VERSION < 34:
            # check for excessive fees
            if self.share_data['previous_share_hash'] is not None and block_abs_height_func is not None:
                height = (block_abs_height_func(self.header['previous_block'])+1)
                base_subsidy = self.net.PARENT.SUBSIDY_FUNC(height)
                fees = [feecache[x] for x in other_tx_hashes if x in feecache]
                missing = sum([1 for x in other_tx_hashes if not x in feecache])
                if missing == 0:
                    max_subsidy = sum(fees) + base_subsidy
                    details = "Max allowed = %i, requested subsidy = %i, share hash = %064x, miner = %s" % (
                            max_subsidy, self.share_data['subsidy'], self.hash,
                            self.address)
                    if self.share_data['subsidy'] > max_subsidy:
                        self.naughty = 1
                        print "Excessive block reward in share! Naughty. " + details
                    elif self.share_data['subsidy'] < max_subsidy:
                        print "Strange, we received a share that did not include as many coins in the block reward as was allowed. "
                        print "While permitted by the protocol, this causes coins to be lost forever if mined as a block, and costs us money."
                        print details

        if self.share_data['previous_share_hash'] and tracker.items[self.share_data['previous_share_hash']].naughty:
            print "naughty ancestor found %i generations ago" % tracker.items[self.share_data['previous_share_hash']].naughty
            # I am not easily angered ...
            print "I will not fail to punish children and grandchildren to the third and fourth generation for the sins of their parents."
            self.naughty = 1 + tracker.items[self.share_data['previous_share_hash']].naughty
            if self.naughty > 6:
                self.naughty = 0

        assert other_tx_hashes2 == other_tx_hashes
        if share_info != self.share_info:
            raise ValueError('share_info invalid')
        if bitcoin_data.get_txid(gentx) != self.gentx_hash:
            print bitcoin_data.get_txid(gentx), self.gentx_hash
            print gentx
            raise ValueError('''gentx doesn't match hash_link''')
        if self.VERSION < 34:
            if bitcoin_data.calculate_merkle_link([None] + other_tx_hashes, 0) != self.merkle_link: # the other hash commitments are checked in the share_info assertion
                raise ValueError('merkle_link and other_tx_hashes do not match')
        
        update_min_protocol_version(counts, self)

        self.gentx_size = len(bitcoin_data.tx_id_type.pack(gentx))
        self.gentx_weight = len(bitcoin_data.tx_type.pack(gentx)) + 3*self.gentx_size

        type(self).gentx_size   = self.gentx_size # saving this share's gentx size as a class variable is an ugly hack, and you're welcome to hate me for doing it. But it works.
        type(self).gentx_weight = self.gentx_weight

        _diff = self.net.PARENT.DUMB_SCRYPT_DIFF*float(
                bitcoin_data.target_to_difficulty(self.target))
        if not self.naughty:
            print("Received good share: diff=%.2e hash=%064x miner=%s" %
                    (_diff, self.hash, self.address))
        else:
            print("Received naughty=%i share: diff=%.2e hash=%064x miner=%s" %
                    (self.naughty, _diff, self.hash, self.address))
        return gentx # only used by as_block
    
    def get_other_tx_hashes(self, tracker):
        parents_needed = max(share_count for share_count, tx_count in self.iter_transaction_hash_refs()) if self.share_info.get('transaction_hash_refs', None) else 0
        parents = tracker.get_height(self.hash) - 1
        if parents < parents_needed:
            return None
        last_shares = list(tracker.get_chain(self.hash, parents_needed + 1))
        ret = []
        for share_count, tx_count in self.iter_transaction_hash_refs():
            try:
                ret.append(last_shares[share_count]
                              .share_info['new_transaction_hashes'][tx_count])
            except AttributeError:
                continue
        return ret
    
    def _get_other_txs(self, tracker, known_txs):
        other_tx_hashes = self.get_other_tx_hashes(tracker)
        if other_tx_hashes is None:
            return None # not all parents present
        
        if not all(tx_hash in known_txs for tx_hash in other_tx_hashes):
            return None # not all txs present
        
        return [known_txs[tx_hash] for tx_hash in other_tx_hashes]
    
    def should_punish_reason(self, previous_block, bits, tracker, known_txs):
        if self.pow_hash <= self.header['bits'].target:
            return -1, 'block solution'
        if self.naughty == 1:
            return self.naughty, 'naughty share (excessive block reward or otherwise would make an invalid block)'
        if self.naughty:
            return self.naughty, 'descendent of naughty share                                                    '
        if self.VERSION < 34:
            other_txs = self._get_other_txs(tracker, known_txs)
        else:
            other_txs = None
        if other_txs is None:
            pass
        else:
            if not hasattr(self, 'all_tx_size'):
                self.all_txs_size = sum(bitcoin_data.get_size(tx) for tx in other_txs)
                self.stripped_txs_size = sum(bitcoin_data.get_stripped_size(tx) for tx in other_txs)
            if self.all_txs_size + 3 * self.stripped_txs_size + 4*80 + self.gentx_weight > tracker.net.BLOCK_MAX_WEIGHT:
                return True, 'txs over block weight limit'
            if self.stripped_txs_size + 80 + self.gentx_size > tracker.net.BLOCK_MAX_SIZE:
                return True, 'txs over block size limit'
        
        return False, None
    
    def as_block(self, tracker, known_txs):
        other_txs = self._get_other_txs(tracker, known_txs)
        if other_txs is None:
            return None # not all txs present
        return dict(header=self.header, txs=[self.check(tracker, other_txs)] + other_txs)

class PaddingBugfixShare(BaseShare):
    VERSION=35
    VOTING_VERSION = 35
    SUCCESSOR = None
    MINIMUM_PROTOCOL_VERSION = 3500

class SegwitMiningShare(BaseShare):
    VERSION = 34
    VOTING_VERSION = 34
    SUCCESSOR = PaddingBugfixShare
    MINIMUM_PROTOCOL_VERSION = 3300

class NewShare(BaseShare):
    VERSION = 33
    VOTING_VERSION = 33
    SUCCESSOR = PaddingBugfixShare
    MINIMUM_PROTOCOL_VERSION = 3300

class PreSegwitShare(BaseShare):
    VERSION = 32
    VOTING_VERSION = 32
    SUCCESSOR = PaddingBugfixShare

class Share(BaseShare):
    VERSION = 17
    VOTING_VERSION = 17
    SUCCESSOR = PaddingBugfixShare


share_versions = {s.VERSION:s for s in [PaddingBugfixShare, SegwitMiningShare, NewShare, PreSegwitShare, Share]}

class WeightsSkipList(forest.TrackerSkipList):
    # share_count, weights, total_weight
    
    def get_delta(self, element):
        from p2pool.bitcoin import data as bitcoin_data
        share = self.tracker.items[element]
        att = bitcoin_data.target_to_average_attempts(share.target)
        return (1, {share.address: att*(65535-share.share_data['donation'])},
                att*65535, att*share.share_data['donation'])
    
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

    def attempt_verify(self, share, block_abs_height_func, known_txs, feecache):
        if share.hash in self.verified.items:
            return True
        height, last = self.get_height_and_last(share.hash)
        if height < self.net.CHAIN_LENGTH + 1 and last is not None:
            raise AssertionError()
        try:
            share.gentx = share.check(self, known_txs, block_abs_height_func=block_abs_height_func, feecache=feecache)
        except:
            log.err(None, 'Share check failed: %064x -> %064x' % (share.hash, share.previous_hash if share.previous_hash is not None else 0))
            return False
        else:
            self.verified.add(share)
            return True
    
    def think(self, block_rel_height_func, block_abs_height_func, previous_block, bits, known_txs, feecache):
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
                if self.attempt_verify(share, block_abs_height_func, known_txs, feecache):
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
                if not self.attempt_verify(share, block_abs_height_func, known_txs, feecache):
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
            self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))) -
            min(self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0], 1) * bitcoin_data.target_to_average_attempts(self.items[h].target),
            #self.items[h].peer_addr is None,
            -self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0],
            #-self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0] * bitcoin_data.target_to_average_attempts(self.items[h].target),
            -self.items[h].time_seen,
        ), h) for h in self.verified.tails.get(best_tail, []))
        traditional_sort = sorted(((
            self.verified.get_work(self.verified.get_nth_parent_hash(h, min(5, self.verified.get_height(h)))),
            #self.items[h].peer_addr is None,
            -self.items[h].time_seen, # assume they can't tell we should punish this share and will be sorting based on time
            -self.items[h].should_punish_reason(previous_block, bits, self, known_txs)[0],
        ), h) for h in self.verified.tails.get(best_tail, []))
        punish_aggressively = traditional_sort[-1][0][2] if traditional_sort else False

        if p2pool.DEBUG:
            print len(decorated_heads), 'heads. Top 10:'
            for score, head_hash in decorated_heads[-10:]:
                print '   ', format_hash(head_hash), format_hash(self.items[head_hash].previous_hash), score
            print "Traditional sort:"
            for score, head_hash in traditional_sort[-10:]:
                print '   ', format_hash(head_hash), format_hash(self.items[head_hash].previous_hash), score
        best_head_score, best = decorated_heads[-1] if decorated_heads else (None, None)

        punish = 0
        if best is not None:
            best_share = self.items[best]
            punish, punish_reason = best_share.should_punish_reason(previous_block, bits, self, known_txs)
            while punish > 0:
                print 'Punishing share for %r! Jumping from %s to %s!' % (punish_reason, format_hash(best), format_hash(best_share.previous_hash))
                best = best_share.previous_hash
                best_share = self.items[best]
                punish, punish_reason = best_share.should_punish_reason(previous_block, bits, self, known_txs)
                if not punish:
                    def best_descendent(hsh, limit=20):
                        child_hashes = self.reverse.get(hsh, set())
                        best_kids = sorted((best_descendent(child, limit-1) for child in child_hashes if not self.items[child].naughty))
                        if not best_kids or limit<0: # in case the only children are naughty
                            return 0, hsh
                        return (best_kids[-1][0]+1, best_kids[-1][1])
                    try:
                        gens, hsh = best_descendent(best)
                        if p2pool.DEBUG: print "best_descendent went %i generations for share %s from %s" % (gens, format_hash(hsh), format_hash(best))
                        best = hsh
                        best_share = self.items[best]
                    except:
                        traceback.print_exc()
            
            timestamp_cutoff = min(int(time.time()), best_share.timestamp) - 3600
            target_cutoff = int(2**256//(self.net.SHARE_PERIOD*best_tail_score[1] + 1) * 2 + .5) if best_tail_score[1] is not None else 2**256-1

            # Hard fork logic:
            # If our best share is v34 or higher, we will correctly zero-pad output scripts
            # Otherwise, we preserve a bug in order to avoid a chainsplit
            self.net.PARENT.padding_bugfix = (best_share.VERSION >= 35)

        else:
            timestamp_cutoff = int(time.time()) - 24*60*60
            target_cutoff = 2**256-1
        
        if p2pool.DEBUG:
            print 'Desire %i shares. Cutoff: %s old diff>%.2f' % (len(desired), math.format_dt(time.time() - timestamp_cutoff), bitcoin_data.target_to_difficulty(target_cutoff))
            for peer_addr, hash, ts, targ in desired:
                print '   ', None if peer_addr is None else '%s:%i' % peer_addr, format_hash(hash), math.format_dt(time.time() - ts), bitcoin_data.target_to_difficulty(targ), ts >= timestamp_cutoff, targ <= target_cutoff
        
        return best, [(peer_addr, hash) for peer_addr, hash, ts, targ in desired if ts >= timestamp_cutoff], decorated_heads, bad_peer_addresses, punish_aggressively
    
    def score(self, share_hash, block_rel_height_func):
        # returns approximate lower bound on chain's hashrate in the last self.net.CHAIN_LENGTH*15//16*self.net.SHARE_PERIOD time
        
        head_height = self.verified.get_height(share_hash)
        if head_height < self.net.CHAIN_LENGTH:
            return head_height, None
        
        end_point = self.verified.get_nth_parent_hash(share_hash, self.net.CHAIN_LENGTH*15//16)
        
        block_height = max(block_rel_height_func(share.header['previous_block']) for share in
            self.verified.get_chain(end_point, self.net.CHAIN_LENGTH//16))
        
        return self.net.CHAIN_LENGTH, self.verified.get_delta(share_hash, end_point).work/((0 - block_height + 1)*self.net.PARENT.BLOCK_PERIOD)

def update_min_protocol_version(counts, share):
    minpver = getattr(share.net, 'MINIMUM_PROTOCOL_VERSION', 1400)
    newminpver = share.MINIMUM_PROTOCOL_VERSION
    if (counts is not None) and (minpver < newminpver):
            if counts.get(share.VERSION, 0) >= sum(counts.itervalues())*95//100:
                share.net.MINIMUM_PROTOCOL_VERSION = newminpver # Reject peers running obsolete nodes
                print 'Setting MINIMUM_PROTOCOL_VERSION = %d' % (newminpver)

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

def get_user_stale_props(tracker, share_hash, lookbehind, net):
    res = {}
    for share in tracker.get_chain(share_hash, lookbehind - 1):
        if share.VERSION < 34:
            stale, total = res.get(share.share_data['pubkey_hash'], (0, 0))
            key = bitcoin_data.pubkey_hash_to_address(
                    share.share_data['pubkey_hash'], net.ADDRESS_VERSION, -1,
                    net)
        else:
            key = share.share_data['address']
            stale, total = res.get(key, (0, 0))
        total += 1
        if share.share_data['stale_info'] is not None:
            stale += 1
            total += 1
        res[key] = stale, total
    return dict((pubkey_hash, stale/total) for pubkey_hash, (stale, total) in res.iteritems())

def get_expected_payouts(tracker, best_share_hash, block_target, subsidy, net):
    weights, total_weight, donation_weight = tracker.get_cumulative_weights(best_share_hash, min(tracker.get_height(best_share_hash), net.REAL_CHAIN_LENGTH), 65535*net.SPREAD*bitcoin_data.target_to_average_attempts(block_target))
    res = dict((script, subsidy*weight//total_weight) for script, weight in weights.iteritems())
    donation_addr = donation_script_to_address(net)
    res[donation_addr] = res.get(donation_addr, 0) + subsidy - sum(res.itervalues())
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
    if majority_desired_version not in share_versions and desired_version_counts[majority_desired_version] > sum(desired_version_counts.itervalues())/2:
        res.append('A MAJORITY OF SHARES CONTAIN A VOTE FOR AN UNSUPPORTED SHARE IMPLEMENTATION! (v%i with %i%% support)\n'
            'An upgrade is likely necessary. Check https://github.com/jtoomim/p2pool/tree/1mb_segwit or https://forum.bitcoin.com/pools/p2pool-decentralized-dos-resistant-trustless-censorship-resistant-pool-t69932-99999.html for more information.' % (
                majority_desired_version, 100*desired_version_counts[majority_desired_version]/sum(desired_version_counts.itervalues())))
    
    if bitcoind_getinfo['warnings'] != '':
        if 'This is a pre-release test build' not in bitcoind_getinfo['warnings']:
            res.append('(from bitcoind) %s' % (bitcoind_getinfo['warnings'],))
    
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

        start = time.time()
        
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

        print "Share loading took %.3f seconds" % (time.time() - start)
    
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
