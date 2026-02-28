#!/usr/bin/env python3
"""
Analyze share store files to diagnose v36 activation signaling.

Pure Python 3 - no p2pool imports, no twisted.
Reimplements minimal binary parsing from p2pool's pack module.
"""

import struct
import io
import os
import sys
import time
import datetime
import collections

# ============================================================================
# Minimal reimplementation of p2pool's pack types (Python 3)
# ============================================================================

class VarIntType:
    def read(self, f):
        b = f.read(1)
        if len(b) == 0:
            raise EOFError()
        first = b[0]
        if first < 0xfd:
            return first
        if first == 0xfd:
            return struct.unpack('<H', f.read(2))[0]
        elif first == 0xfe:
            return struct.unpack('<I', f.read(4))[0]
        elif first == 0xff:
            return struct.unpack('<Q', f.read(8))[0]

class VarStrType:
    _vi = VarIntType()
    def read(self, f):
        length = self._vi.read(f)
        return f.read(length)

class IntType:
    def __init__(self, bits, endianness='little'):
        self.bytes = bits // 8
        self.little = (endianness == 'little')

    def read(self, f):
        if self.bytes == 0:
            return 0
        data = f.read(self.bytes)
        if len(data) < self.bytes:
            raise EOFError()
        return int.from_bytes(data, 'little' if self.little else 'big')

class FixedStrType:
    def __init__(self, length):
        self.length = length
    def read(self, f):
        return f.read(self.length)

class StructType:
    def __init__(self, fmt):
        self.fmt = fmt
        self.size = struct.calcsize(fmt)
    def read(self, f):
        data = f.read(self.size)
        if len(data) < self.size:
            raise EOFError()
        return struct.unpack(self.fmt, data)[0]

def make_int_type(bits, endianness='little'):
    """Factory matching p2pool's IntType behavior - small sizes use struct."""
    if bits in (8, 16, 32, 64):
        prefix = '<' if endianness == 'little' else '>'
        fmt_map = {8: 'B', 16: 'H', 32: 'I', 64: 'Q'}
        return StructType(prefix + fmt_map[bits])
    return IntType(bits, endianness)

class EnumType:
    def __init__(self, inner, mapping):
        self.inner = inner
        self.mapping = mapping
    def read(self, f):
        val = self.inner.read(f)
        return self.mapping.get(val, 'unk%d' % val)

class ListType:
    _vi = VarIntType()
    def __init__(self, item_type, mul=1, max_count=None):
        self.item_type = item_type
        self.mul = mul
    def read(self, f):
        length = self._vi.read(f) * self.mul
        return [self.item_type.read(f) for _ in range(length)]

class PossiblyNoneType:
    def __init__(self, none_value, inner):
        self.none_value = none_value
        self.inner = inner
    def read(self, f):
        value = self.inner.read(f)
        return None if value == self.none_value else value

class ComposedType:
    def __init__(self, fields):
        self.fields = fields
    def read(self, f):
        result = {}
        for name, typ in self.fields:
            result[name] = typ.read(f)
        return result

class FloatingIntegerType:
    _inner = make_int_type(32)
    def read(self, f):
        bits = self._inner.read(f)
        # Decode target from compact "bits" format
        mantissa = bits & 0x00ffffff
        exponent = bits >> 24
        target = mantissa * (256 ** (exponent - 3)) if exponent >= 3 else mantissa >> (8 * (3 - exponent))
        return {'bits': bits, 'target': target}


# ============================================================================
# Share format definitions (matching p2pool/data.py)
# ============================================================================

# Outer wrapper: type_id varint + contents varstr
outer_share_type = ComposedType([
    ('type', VarIntType()),
    ('contents', VarStrType()),
])

# small_block_header_type (same for V34-V36)
small_block_header_type = ComposedType([
    ('version', VarIntType()),
    ('previous_block', PossiblyNoneType(0, IntType(256))),
    ('timestamp', make_int_type(32)),
    ('bits', FloatingIntegerType()),
    ('nonce', make_int_type(32)),
])

# hash_link_type
hash_link_type = ComposedType([
    ('state', FixedStrType(32)),
    ('extra_data', FixedStrType(0)),
    ('length', VarIntType()),
])

# merkle_link_type (used in both ref_merkle_link and merkle_link)
merkle_link_type = ComposedType([
    ('branch', ListType(IntType(256))),
    ('index', IntType(0)),  # 0-bit int = always 0
])

stale_info_type = EnumType(
    make_int_type(8),
    {k: {0: None, 253: 'orphan', 254: 'doa'}.get(k, 'unk%d' % k) for k in range(256)}
)

segwit_data_type = PossiblyNoneType(
    {'txid_merkle_link': {'branch': [], 'index': 0}, 'wtxid_merkle_root': 2**256 - 1},
    ComposedType([
        ('txid_merkle_link', ComposedType([
            ('branch', ListType(IntType(256))),
            ('index', IntType(0)),
        ])),
        ('wtxid_merkle_root', IntType(256)),
    ])
)


def make_share_info_type(version):
    """Build share_info_type for a given share VERSION."""
    
    # share_data fields common to all
    share_data_fields = [
        ('previous_share_hash', PossiblyNoneType(0, IntType(256))),
        ('coinbase', VarStrType()),
        ('nonce', make_int_type(32)),
    ]
    
    # V34+ uses string address, older uses pubkey_hash
    if version >= 34:
        share_data_fields.append(('address', VarStrType()))
    else:
        share_data_fields.append(('pubkey_hash', IntType(160)))
    
    share_data_fields.extend([
        ('subsidy', make_int_type(64)),
        ('donation', make_int_type(16)),
        ('stale_info', stale_info_type),
        ('desired_version', VarIntType()),
    ])
    
    share_data_type = ComposedType(share_data_fields)
    
    # Build share_info fields
    info_fields = [('share_data', share_data_type)]
    
    # V34+ has segwit_data (segwit activated for litecoin)
    if version >= 34:
        info_fields.append(('segwit_data', segwit_data_type))
    
    # V33 and below have transaction hashes inline
    if version < 34:
        info_fields.extend([
            ('new_transaction_hashes', ListType(IntType(256))),
            ('transaction_hash_refs', ListType(VarIntType(), 2)),
        ])
    
    # V36 has merged_addresses after segwit_data
    if version >= 36:
        merged_address_entry = ComposedType([
            ('chain_id', make_int_type(32)),
            ('script', VarStrType()),
        ])
        info_fields.append(('merged_addresses', PossiblyNoneType(
            [],
            ListType(merged_address_entry, max_count=8)
        )))
    
    info_fields.extend([
        ('far_share_hash', PossiblyNoneType(0, IntType(256))),
        ('max_bits', FloatingIntegerType()),
        ('bits', FloatingIntegerType()),
        ('timestamp', make_int_type(32)),
        ('absheight', make_int_type(32)),
        ('abswork', IntType(128)),
    ])
    
    return ComposedType(info_fields)


def make_inner_share_type(version):
    """Build the inner share_type for a given share VERSION."""
    share_info_type = make_share_info_type(version)
    return ComposedType([
        ('min_header', small_block_header_type),
        ('share_info', share_info_type),
        ('ref_merkle_link', merkle_link_type),
        ('last_txout_nonce', make_int_type(64)),
        ('hash_link', hash_link_type),
        ('merkle_link', merkle_link_type),
    ])


# Pre-build parsers for versions we care about
INNER_TYPES = {}
for v in [17, 32, 33, 34, 35, 36]:
    try:
        INNER_TYPES[v] = make_inner_share_type(v)
    except Exception as e:
        print(f"  Warning: could not build parser for version {v}: {e}")


# ============================================================================
# Helper functions
# ============================================================================

def target_to_average_attempts(target):
    if target <= 0:
        return 2**256
    return 2**256 // (target + 1)

def target_to_difficulty(target):
    if target <= 0:
        return float('inf')
    return (0xffff0000 * 2**(256-64) + 1) / (target + 1)

CHAIN_LENGTH = 24 * 60 * 60 // 10  # 8640 shares


# ============================================================================
# Share loading
# ============================================================================

def load_all_shares(share_dir):
    """Load all shares from share store files."""
    shares = {}
    files = sorted(
        [f for f in os.listdir(share_dir) if f.startswith('shares.') and f[7:].isdigit()],
        key=lambda f: int(f[7:])
    )
    
    total_errors = 0
    for fname in files:
        fpath = os.path.join(share_dir, fname)
        count = 0
        errors = 0
        with open(fpath, 'rb') as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    parts = line.split(b' ', 1)
                    type_id = int(parts[0])
                    
                    if type_id != 5:
                        continue  # skip verified hashes (type 2) and others
                    
                    data_hex = parts[1]
                    data_bin = bytes.fromhex(data_hex.decode('ascii'))
                    
                    # Parse outer wrapper: type (varint) + contents (varstr)
                    bio = io.BytesIO(data_bin)
                    outer = outer_share_type.read(bio)
                    share_version = outer['type']
                    contents_bin = outer['contents']
                    
                    if share_version not in INNER_TYPES:
                        continue
                    
                    # Parse inner share
                    inner_bio = io.BytesIO(contents_bin)
                    try:
                        inner = INNER_TYPES[share_version].read(inner_bio)
                    except Exception:
                        errors += 1
                        continue
                    
                    share_data = inner['share_info']['share_data']
                    share_info = inner['share_info']
                    
                    # Extract address
                    if share_version >= 34:
                        address = share_data['address'].decode('ascii', errors='replace')
                    else:
                        address = 'pubkey_hash:%x' % share_data.get('pubkey_hash', 0)
                    
                    bits_target = share_info['bits']['target']
                    
                    share_obj = {
                        'version': share_version,
                        'desired_version': share_data['desired_version'],
                        'address': address,
                        'target': bits_target,
                        'max_target': share_info['max_bits']['target'],
                        'timestamp': share_info['timestamp'],
                        'absheight': share_info['absheight'],
                        'previous_share_hash': share_data['previous_share_hash'],
                        'subsidy': share_data['subsidy'],
                        'donation': share_data['donation'],
                        'stale_info': share_data['stale_info'],
                    }
                    
                    share_id = share_info['absheight']
                    share_obj['id'] = share_id
                    
                    # Keep latest version if duplicate absheight (shouldn't happen on valid chain)
                    shares[share_id] = share_obj
                    count += 1
                    
                except Exception as e:
                    errors += 1
                    if errors <= 3:
                        print(f"    Error in {fname}:{line_no}: {e}")
        
        total_errors += errors
        print(f"  {fname}: {count} shares loaded ({errors} errors)")
    
    print(f"\nTotal: {len(shares)} unique shares loaded ({total_errors} errors)")
    return shares


def build_chain(shares):
    """Build the chain using absheight ordering (monotonically increasing)."""
    if not shares:
        return []
    
    # Sort by absheight descending (newest first = tip at index 0)
    sorted_heights = sorted(shares.keys(), reverse=True)
    
    # Verify continuity
    gaps = 0
    gap_ranges = []
    expected = sorted_heights[0]
    gap_start = None
    for h in sorted_heights:
        if h != expected:
            if gap_start is None:
                gap_start = expected
            gaps += expected - h
        else:
            if gap_start is not None:
                gap_ranges.append((gap_start, expected + 1))
                gap_start = None
        expected = h - 1
    
    tip_height = sorted_heights[0]
    tail_height = sorted_heights[-1]
    print(f"Chain: {len(sorted_heights)} shares, absheight {tail_height} to {tip_height} (tip)")
    if gaps:
        print(f"  WARNING: {gaps} missing absheights in sequence")
    
    return sorted_heights  # newest first (tip at index 0)


def analyze_activation_window(shares, chain):
    """Analyze the activation window (positions 7776-8640 from tip = oldest 10%)."""
    window_start = CHAIN_LENGTH * 9 // 10  # 7776
    window_size = CHAIN_LENGTH // 10        # 864
    
    print("\n" + "=" * 80)
    print("ACTIVATION WINDOW ANALYSIS")
    print("=" * 80)
    print(f"Chain length: {len(chain)}  (CHAIN_LENGTH={CHAIN_LENGTH})")
    print(f"Window: positions {window_start} to {window_start + window_size - 1} from tip (oldest 10%)")
    
    if len(chain) < window_start + window_size:
        print(f"WARNING: Chain too short! Need {window_start + window_size}, have {len(chain)}")
        actual_end = min(window_start + window_size, len(chain))
        actual_start = min(window_start, len(chain))
        window_heights = chain[actual_start:actual_end]
    else:
        window_heights = chain[window_start:window_start + window_size]
    
    if not window_heights:
        print("No shares in activation window!")
        return
    
    version_weights = collections.defaultdict(float)
    version_counts = collections.defaultdict(int)
    miner_version_weights = collections.defaultdict(float)
    miner_version_counts = collections.defaultdict(int)
    share_type_counts = collections.defaultdict(int)
    timestamps = []
    
    for h in window_heights:
        share = shares[h]
        weight = target_to_average_attempts(share['target'])
        dv = share['desired_version']
        sv = share['version']
        addr = share['address']
        
        version_weights[dv] += weight
        version_counts[dv] += 1
        miner_version_weights[(addr, dv)] += weight
        miner_version_counts[(addr, dv)] += 1
        share_type_counts[sv] += 1
        timestamps.append(share['timestamp'])
    
    total_weight = sum(version_weights.values())
    
    print(f"\n--- Desired Version Distribution (by weight) ---")
    for dv in sorted(version_weights.keys()):
        pct = 100.0 * version_weights[dv] / total_weight if total_weight else 0
        print(f"  v{dv}: {pct:.2f}% weight ({version_weights[dv]:.2e}), {version_counts[dv]} shares")
    
    print(f"\n--- Share Type (VERSION) Distribution ---")
    for sv in sorted(share_type_counts.keys()):
        print(f"  Share.VERSION={sv}: {share_type_counts[sv]} shares")
    
    print(f"\n--- Miner Breakdown (by weight, all) ---")
    sorted_miners = sorted(miner_version_weights.items(), key=lambda x: -x[1])
    for (addr, dv), weight in sorted_miners:
        pct = 100.0 * weight / total_weight if total_weight else 0
        cnt = miner_version_counts[(addr, dv)]
        print(f"  {addr:<36s}  v{dv}  {pct:6.2f}% ({cnt} shares)")
    
    if timestamps:
        min_ts, max_ts = min(timestamps), max(timestamps)
        print(f"\n--- Time Range ---")
        print(f"  Oldest: {datetime.datetime.fromtimestamp(min_ts):%Y-%m-%d %H:%M:%S} ({(time.time()-min_ts)/3600:.1f}h ago)")
        print(f"  Newest: {datetime.datetime.fromtimestamp(max_ts):%Y-%m-%d %H:%M:%S} ({(time.time()-max_ts)/3600:.1f}h ago)")
        print(f"  Absheight range: {min(window_heights)} to {max(window_heights)}")


def analyze_full_chain(shares, chain):
    """Analyze the entire chain for version distribution over time."""
    print("\n" + "=" * 80)
    print("FULL CHAIN VERSION DISTRIBUTION (by segment)")
    print("=" * 80)
    
    segment_size = CHAIN_LENGTH // 10  # 864
    
    print(f"\n{'Position':<14s} {'v35':>7s} {'v36':>7s} {'Other':>7s} {'Shares':>7s}  {'Oldest':<14s} {'Newest':<14s}")
    print("-" * 80)
    
    for seg_start in range(0, len(chain), segment_size):
        seg_end = min(seg_start + segment_size, len(chain))
        seg_heights = chain[seg_start:seg_end]
        
        v35_w = v36_w = other_w = 0.0
        ts_list = []
        
        for h in seg_heights:
            s = shares[h]
            w = target_to_average_attempts(s['target'])
            dv = s['desired_version']
            if dv == 35: v35_w += w
            elif dv == 36: v36_w += w
            else: other_w += w
            ts_list.append(s['timestamp'])
        
        total = v35_w + v36_w + other_w
        v35_pct = 100.0 * v35_w / total if total else 0
        v36_pct = 100.0 * v36_w / total if total else 0
        other_pct = 100.0 * other_w / total if total else 0
        
        oldest = datetime.datetime.fromtimestamp(min(ts_list)).strftime('%m-%d %H:%M') if ts_list else '?'
        newest = datetime.datetime.fromtimestamp(max(ts_list)).strftime('%m-%d %H:%M') if ts_list else '?'
        
        label = f"{seg_start}-{seg_end-1}"
        marker = " <-- ACTIVATION" if seg_start == CHAIN_LENGTH * 9 // 10 else ""
        print(f"  {label:<12s} {v35_pct:6.1f}%  {v36_pct:6.1f}%  {other_pct:6.1f}%  {len(seg_heights):>5d}   {oldest}  ->  {newest}{marker}")


def analyze_v35_shares(shares, chain):
    """Deep dive into v35-voting shares."""
    print("\n" + "=" * 80)
    print("V35 SHARE DEEP DIVE")
    print("=" * 80)
    
    v35_shares = []
    for i, h in enumerate(chain):
        s = shares[h]
        if s['desired_version'] == 35:
            v35_shares.append((i, s))
    
    print(f"Total v35 shares in chain: {len(v35_shares)} / {len(chain)} ({100.0*len(v35_shares)/len(chain):.1f}%)")
    
    if not v35_shares:
        print("No v35 shares found — chain is 100% v36!")
        return
    
    # Group by address
    by_addr = collections.defaultdict(list)
    for pos, s in v35_shares:
        by_addr[s['address']].append((pos, s))
    
    print(f"\n--- V35 shares by miner address ---")
    for addr, slist in sorted(by_addr.items(), key=lambda x: -len(x[1])):
        positions = [p for p, s in slist]
        timestamps = [s['timestamp'] for p, s in slist]
        weights = [target_to_average_attempts(s['target']) for p, s in slist]
        diffs = [target_to_difficulty(s['target']) for p, s in slist]
        
        print(f"\n  Address: {addr}")
        print(f"    Count: {len(slist)} shares")
        print(f"    Positions: {min(positions)} to {max(positions)} from tip")
        print(f"    Time: {datetime.datetime.fromtimestamp(min(timestamps)):%Y-%m-%d %H:%M:%S} to {datetime.datetime.fromtimestamp(max(timestamps)):%Y-%m-%d %H:%M:%S}")
        print(f"    Avg difficulty: {sum(diffs)/len(diffs):.4f}")
        print(f"    Total weight: {sum(weights):.2e}")
        print(f"    Share.VERSION values: {set(s['version'] for p, s in slist)}")
    
    # Position histogram
    print(f"\n--- V35 position distribution (bucketed by {CHAIN_LENGTH//10}) ---")
    buckets = collections.defaultdict(int)
    for pos, s in v35_shares:
        bucket = pos // (CHAIN_LENGTH // 10)
        buckets[bucket] += 1
    
    for bucket in sorted(buckets.keys()):
        start = bucket * (CHAIN_LENGTH // 10)
        end = start + (CHAIN_LENGTH // 10) - 1
        bar = '#' * min(buckets[bucket] // 3 + 1, 60)
        marker = " <-- ACTIVATION" if start == CHAIN_LENGTH * 9 // 10 else ""
        print(f"  {start:>5d}-{end:>5d}: {buckets[bucket]:>4d} shares  {bar}{marker}")


def analyze_v36_shares(shares, chain):
    """Summary of v36-voting shares."""
    print("\n" + "=" * 80)
    print("V36 SHARE SUMMARY")
    print("=" * 80)
    
    v36_shares = [(i, shares[h]) for i, h in enumerate(chain) if shares[h]['desired_version'] == 36]
    
    if not v36_shares:
        print("No v36 shares found!")
        return
    
    by_addr = collections.defaultdict(list)
    for pos, s in v36_shares:
        by_addr[s['address']].append((pos, s))
    
    print(f"Total v36 shares: {len(v36_shares)} / {len(chain)} ({100.0*len(v36_shares)/len(chain):.1f}%)")
    print(f"\n--- V36 shares by miner ---")
    for addr, slist in sorted(by_addr.items(), key=lambda x: -len(x[1])):
        weights = sum(target_to_average_attempts(s['target']) for _, s in slist)
        positions = [p for p, _ in slist]
        print(f"  {addr:<36s}  {len(slist):>5d} shares  pos {min(positions)}-{max(positions)}  weight {weights:.2e}")


if __name__ == '__main__':
    share_dir = sys.argv[1] if len(sys.argv) > 1 else '/tmp/shares'
    
    print(f"Loading shares from {share_dir}...")
    shares = load_all_shares(share_dir)
    
    if not shares:
        print("No shares found!")
        sys.exit(1)
    
    chain = build_chain(shares)
    
    if not chain:
        print("Could not build chain!")
        sys.exit(1)
    
    analyze_activation_window(shares, chain)
    analyze_full_chain(shares, chain)
    analyze_v35_shares(shares, chain)
    analyze_v36_shares(shares, chain)
    
    # Final summary
    print("\n" + "=" * 80)
    print("ACTIVATION VERDICT")
    print("=" * 80)
    
    window_start = CHAIN_LENGTH * 9 // 10
    window_size = CHAIN_LENGTH // 10
    if len(chain) >= window_start + window_size:
        v36_weight = total_weight = 0.0
        for h in chain[window_start:window_start + window_size]:
            s = shares[h]
            w = target_to_average_attempts(s['target'])
            total_weight += w
            if s['desired_version'] == 36:
                v36_weight += w
        v36_pct = 100.0 * v36_weight / total_weight if total_weight else 0
        print(f"Activation window v36: {v36_pct:.2f}%  (need 95%)")
        print(f"Status: {'YES - WOULD ACTIVATE' if v36_pct >= 95.0 else 'NO - NOT YET'}")
        if v36_pct < 95.0:
            # Find the nearest v35 share to tip in the window
            v35_nearest_pos = None
            for i, h in enumerate(chain[window_start:window_start + window_size]):
                if shares[h]['desired_version'] == 35:
                    if v35_nearest_pos is None:
                        v35_nearest_pos = window_start + i
            if v35_nearest_pos is not None:
                remaining_positions = CHAIN_LENGTH - v35_nearest_pos
                est_seconds = remaining_positions * 10
                est_hours = est_seconds / 3600
                print(f"  Nearest v35 share at position {v35_nearest_pos} from tip")
                print(f"  Needs {remaining_positions} more shares to age out of window")
                print(f"  Estimated time: ~{est_hours:.1f} hours ({est_seconds/60:.0f} min)")
    else:
        print(f"Chain too short ({len(chain)} < {window_start + window_size})")
