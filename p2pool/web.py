from __future__ import division

import errno
import json
import os
import sys
import time
import traceback

from twisted.internet import defer, reactor
from twisted.python import log
from twisted.web import resource, static

import p2pool
from bitcoin import data as bitcoin_data
from . import data as p2pool_data, p2p
from util import deferral, deferred_resource, graph, math, memory, pack, variable

def _atomic_read(filename):
    try:
        with open(filename, 'rb') as f:
            return f.read()
    except IOError, e:
        if e.errno != errno.ENOENT:
            raise
    try:
        with open(filename + '.new', 'rb') as f:
            return f.read()
    except IOError, e:
        if e.errno != errno.ENOENT:
            raise
    return None

def _atomic_write(filename, data):
    with open(filename + '.new', 'wb') as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except:
            pass
    try:
        os.rename(filename + '.new', filename)
    except: # XXX windows can't overwrite
        os.remove(filename)
        os.rename(filename + '.new', filename)

def get_web_root(wb, datadir_path, bitcoind_getinfo_var, stop_event=variable.Event(), static_dir=None,
                 enable_miner_messages=False, transition_message=None, trusted_proxy=None):
    node = wb.node
    start_time = time.time()

    _LOCALHOST_IPS = ('127.0.0.1', '::1', '::ffff:127.0.0.1')

    def _get_real_client_ip(request):
        """Get the real client IP, respecting X-Forwarded-For if behind a trusted proxy."""
        peer_ip = request.getClientIP()
        if trusted_proxy and peer_ip == trusted_proxy:
            forwarded = request.getHeader('X-Forwarded-For')
            if forwarded:
                # X-Forwarded-For: client, proxy1, proxy2 — take the first (leftmost)
                return forwarded.split(',')[0].strip()
        return peer_ip

    def _is_localhost(request):
        """Check if the request originates from localhost."""
        return _get_real_client_ip(request) in _LOCALHOST_IPS
    
    web_root = resource.Resource()
    
    def get_users():
        height, last = node.tracker.get_height_and_last(node.best_share_var.value)
        weights, total_weight, donation_weight = node.tracker.get_cumulative_weights(node.best_share_var.value, min(height, 720), 65535*2**256)
        res = {}
        for addr in sorted(weights, key=lambda s: weights[s]):
            res[addr] = weights[addr]/total_weight
        return res
    
    def get_current_scaled_txouts(scale, trunc=0):
        txouts = node.get_current_txouts()
        total = sum(txouts.itervalues())
        results = dict((addr, value*scale//total) for addr, value in txouts.iteritems())
        if trunc > 0:
            total_random = 0
            random_set = set()
            for s in sorted(results, key=results.__getitem__):
                if results[s] >= trunc:
                    break
                total_random += results[s]
                random_set.add(s)
            if total_random:
                winner = math.weighted_choice((addr, results[script]) for addr in random_set)
                for addr in random_set:
                    del results[addr]
                results[winner] = total_random
        if sum(results.itervalues()) < int(scale):
            results[math.weighted_choice(results.iteritems())] += int(scale) - sum(results.itervalues())
        return results
    
    def get_patron_sendmany(total=None, trunc='0.01'):
        if total is None:
            return 'need total argument. go to patron_sendmany/<TOTAL>'
        total = int(float(total)*1e8)
        trunc = int(float(trunc)*1e8)
        return json.dumps(dict(
            (bitcoin_data.script2_to_address(script, node.net.PARENT), value/1e8)
            for script, value in get_current_scaled_txouts(total, trunc).iteritems()
            if bitcoin_data.script2_to_address(script, node.net.PARENT) is not None
        ))
    
    def get_version_signaling():
        """
        Get version signaling statistics for version upgrade tracking.
        
        Three key metrics:
        - share_types: Actual share class VERSION in chain (e.g. V17=Share, V35=PaddingBugfixShare, V36=MergedMiningShare)
        - versions (desired_version): What each share votes FOR (signals next upgrade)
        - successor signaling: Tracks the SUCCESSOR transition even during propagation phase
        
        The transition has multiple phases:
        1. BUILDING_CHAIN: Chain hasn't reached CHAIN_LENGTH yet
        2. PROPAGATING: Current type's shares are voting for SUCCESSOR but haven't reached sampling window
        3. SIGNALING: SUCCESSOR votes appearing in sampling window (0-60%)
        4. SIGNALING_STRONG: Strong signaling (60-95%)
        5. ACTIVATING: Threshold reached (95%+), switchover imminent
        """
        if node.best_share_var.value is None:
            return None
        
        chain_height = node.tracker.get_height(node.best_share_var.value)
        if chain_height < 10:
            return None
        
        chain_length = node.net.CHAIN_LENGTH
        sampling_window_size = chain_length // 10  # 864 for litecoin
        
        # Get desired_version counts from the sampling window (or full chain if immature)
        lookbehind = min(chain_height, chain_length // 10)
        try:
            previous_share = node.tracker.items[node.best_share_var.value]
            counts = p2pool_data.get_desired_version_counts(
                node.tracker,
                node.tracker.get_nth_parent_hash(previous_share.hash, chain_length * 9 // 10) if chain_height >= chain_length else node.best_share_var.value,
                lookbehind
            )
        except:
            counts = {}
        
        total_weight = sum(counts.itervalues())
        if total_weight == 0:
            return None
        
        # Calculate percentages for desired_version voting
        version_percentages = {}
        for version, weight in counts.iteritems():
            version_percentages[str(version)] = {
                'weight': weight,
                'percentage': (weight / total_weight) * 100
            }
        
        # Single-pass scan of the active chain (up to CHAIN_LENGTH).
        # Only consensus-relevant shares matter for voting/signaling stats.
        # Shares beyond CHAIN_LENGTH are aged-out history and would dilute %.
        # Collects: share type counts, desired_version votes, V36 propagation
        # depth, and chain desired_version breakdown — all in one walk.
        share_type_counts = {}       # VERSION -> count (active chain)
        share_type_names = {
            17: 'Share', 32: 'PreSegwitShare', 33: 'NewShare',
            34: 'SegwitMiningShare', 35: 'PaddingBugfixShare', 36: 'MergedMiningShare'
        }
        overall_v36_votes = 0        # shares with desired_version >= 36
        overall_v36_shares = 0       # shares with VERSION >= 36 (actual format)
        overall_total = 0            # total shares scanned
        full_chain_desired = {}      # desired_version -> count (active chain, unweighted)
        propagation_target = chain_length  # 8640 for LTC — full chain length
        v36_contiguous_from_tip = 0  # consecutive V36 votes from tip
        deepest_v36_pos = 0          # deepest position where V36 vote exists
        _contiguous = True
        _scan_limit = min(chain_height, chain_length)  # cap at CHAIN_LENGTH
        try:
            _sh = node.best_share_var.value
            _pos = 0
            while _sh is not None and _pos < _scan_limit:
                _s = node.tracker.items.get(_sh)
                if _s is None:
                    break
                # Share type (VERSION)
                share_type_counts[_s.VERSION] = share_type_counts.get(_s.VERSION, 0) + 1
                # Desired version vote
                _dv = getattr(_s, 'desired_version', _s.VERSION)
                full_chain_desired[_dv] = full_chain_desired.get(_dv, 0) + 1
                overall_total += 1
                if _dv >= 36:
                    overall_v36_votes += 1
                    deepest_v36_pos = _pos + 1
                    if _contiguous:
                        v36_contiguous_from_tip = _pos + 1
                elif _contiguous:
                    _contiguous = False
                if _s.VERSION >= 36:
                    overall_v36_shares += 1
                _sh = _s.previous_hash
                _pos += 1
        except:
            pass
        
        overall_v36_vote_pct = (overall_v36_votes * 100.0 / overall_total) if overall_total > 0 else 0
        overall_v36_share_pct = (overall_v36_shares * 100.0 / overall_total) if overall_total > 0 else 0
        
        total_shares = sum(share_type_counts.values()) if share_type_counts else 0
        share_types = {}
        for version, cnt in sorted(share_type_counts.items()):
            name = share_type_names.get(version, 'V%d' % version)
            share_types[str(version)] = {
                'name': name,
                'count': cnt,
                'percentage': (cnt / total_shares * 100) if total_shares > 0 else 0
            }
        
        # Full-chain desired_version percentages (unweighted, all shares)
        full_chain_version_pcts = {}
        for ver, cnt in full_chain_desired.items():
            full_chain_version_pcts[str(ver)] = {
                'count': cnt,
                'percentage': (cnt * 100.0 / overall_total) if overall_total > 0 else 0
            }
        
        # Current share type being produced (tip of chain)
        current_share = node.tracker.items.get(node.best_share_var.value)
        current_share_type = current_share.VERSION if current_share else None
        current_share_name = share_type_names.get(current_share_type, 'V%d' % current_share_type) if current_share_type else 'Unknown'
        
        # Determine the SUCCESSOR version from the share class hierarchy
        # This is the key: even when dominant vote == current type, if current type
        # has a SUCCESSOR, we're in a transition toward that successor
        successor_version = None
        successor_name = None
        if current_share is not None and hasattr(type(current_share), 'SUCCESSOR') and type(current_share).SUCCESSOR is not None:
            successor_version = type(current_share).SUCCESSOR.VERSION
            successor_name = share_type_names.get(successor_version, 'V%d' % successor_version)
        
        # Find the dominant desired version in sampling window
        target_version = None
        target_percentage = 0
        for ver, weight in counts.iteritems():
            pct = (weight / total_weight) * 100 if total_weight > 0 else 0
            if pct > target_percentage:
                target_version = ver
                target_percentage = pct
        target_version_name = share_type_names.get(target_version, 'V%d' % target_version) if target_version else 'Unknown'
        
        
        # Determine transition state
        # A transition is happening if:
        # 1. Current type differs from dominant vote (classic detection), OR
        # 2. Current type has a SUCCESSOR (we're producing shares that vote for successor)
        classic_transition = current_share_type is not None and target_version is not None and current_share_type != target_version
        successor_transition = successor_version is not None
        is_transitioning = classic_transition or successor_transition
        
        # Hide transition widget when AutoRatchet is CONFIRMED — the
        # V35->V36 transition is complete, all tasks done.
        # But detect stale confirmed state: if chain is <50% V36, treat as voting
        ratchet = getattr(wb, 'auto_ratchet', None)
        ratchet_state = getattr(ratchet, 'state', '') if ratchet else ''
        effective_ratchet_state = ratchet_state
        if ratchet_state == 'confirmed' and chain_height > 0:
            # Check if confirmed state is stale (chain mostly V35)
            v36_share_count = sum(c for v, c in share_type_counts.iteritems() if v >= 36)
            if total_shares > 0 and v36_share_count * 100 // total_shares < 50:
                effective_ratchet_state = 'voting'  # stale confirmed, override
        ratchet_confirmed = effective_ratchet_state == 'confirmed'
        ratchet_active = effective_ratchet_state in ('voting', 'activated')
        show_transition = (is_transitioning or ratchet_active) and not ratchet_confirmed
        
        # The effective target is the SUCCESSOR version when we're in successor transition
        effective_target = successor_version if successor_transition else target_version
        effective_target_name = share_type_names.get(effective_target, 'V%d' % effective_target) if effective_target else 'Unknown'
        
        # Chain maturity
        chain_maturity = min(chain_height / float(chain_length), 1.0) if chain_length > 0 else 0
        
        # Calculate signaling for the EFFECTIVE TARGET in the sampling window
        sampling_signaling = 0
        sampling_counts = {}
        if chain_height >= chain_length:
            try:
                sampling_start = node.tracker.get_nth_parent_hash(
                    node.best_share_var.value, chain_length * 9 // 10)
                sampling_counts = p2pool_data.get_desired_version_counts(
                    node.tracker, sampling_start, sampling_window_size)
                sampling_total = sum(sampling_counts.itervalues())
                if sampling_total > 0 and effective_target is not None:
                    sampling_signaling = (sampling_counts.get(effective_target, 0) / float(sampling_total)) * 100
            except:
                pass
        
        # Propagation: how far V36 votes have aged toward the sampling window
        propagation_pct = min(deepest_v36_pos / float(propagation_target) * 100, 100) if propagation_target > 0 else 0
        shares_to_window = max(0, propagation_target - deepest_v36_pos)
        time_to_window_seconds = shares_to_window * node.net.SHARE_PERIOD
        
        # Legacy field for backward compat
        current_type_count = share_type_counts.get(current_share_type, 0) if current_share_type else 0
        
        # Determine status and message
        if not is_transitioning and not ratchet_active:
            status = 'no_transition'
            message = 'No version transition in progress'
            transition_progress = 100
        elif not is_transitioning and ratchet_active:
            # Share type already switched to V36 but ratchet still needs confirmation
            v36_format_count = sum(c for v, c in share_type_counts.iteritems() if v >= 36)
            v36_format_pct = (v36_format_count * 100 // total_shares) if total_shares > 0 else 0
            confirm_window = chain_length * 2
            activated_height = getattr(ratchet, '_activated_height', None)
            shares_since = max(0, chain_height - activated_height) if activated_height else 0
            status = 'confirming'
            message = 'V36 ACTIVATED — confirmation in progress: %d/%d shares (%d%% V36 format)' % (
                shares_since, confirm_window, v36_format_pct)
            transition_progress = min(shares_since * 100.0 / confirm_window, 100) if confirm_window > 0 else 0
        elif chain_height < chain_length:
            status = 'building_chain'
            shares_remaining = chain_length - chain_height
            message = 'Building chain: %d/%d shares (need %d more before upgrade checks activate)' % (
                chain_height, chain_length, shares_remaining)
            transition_progress = (chain_height / float(chain_length)) * 100
        elif sampling_signaling >= 95:
            status = 'activating'
            message = 'V%d activation threshold reached! %.1f%% in sampling window — switchover imminent' % (
                effective_target, sampling_signaling)
            transition_progress = 100
        elif sampling_signaling >= 60:
            status = 'signaling_strong'
            message = 'Strong V%d signaling — activation approaching (need 95%%)' % (
                effective_target,)
            transition_progress = sampling_signaling
        elif sampling_signaling > 0:
            status = 'signaling'
            message = 'Network is signaling for V%d upgrade' % (
                effective_target,)
            transition_progress = sampling_signaling
        elif overall_v36_votes > 0 and deepest_v36_pos < propagation_target:
            # V36 votes exist in the chain but haven't reached the sampling window yet
            status = 'propagating'
            message = 'V%d votes propagating: %d votes (%.1f%% of chain), deepest at position %d/%d. Reach sampling window in ~%s' % (
                effective_target, overall_v36_votes, overall_v36_vote_pct,
                deepest_v36_pos, propagation_target, format_eta(time_to_window_seconds))
            transition_progress = propagation_pct
        elif overall_v36_votes > 0:
            # V36 votes exist and have reached sampling window position but are 0% weighted
            # (edge case: votes exist at the right position but weight rounds to 0)
            status = 'signaling'
            message = 'V%d votes appearing in sampling window. %d votes (%.1f%%) in chain overall' % (
                effective_target, overall_v36_votes, overall_v36_vote_pct)
            transition_progress = overall_v36_vote_pct
        else:
            # No V36 votes anywhere in the chain
            status = 'waiting'
            message = 'Waiting for miners to upgrade. No V%d votes in chain yet (0/%d shares). Miners need V36-capable software.' % (
                effective_target, total_shares)
            transition_progress = 0
        
        # AutoRatchet state for dashboard — report effective state
        ratchet_info = None
        if ratchet is not None:
            ratchet_info = dict(
                state=effective_ratchet_state,
                persisted_state=getattr(ratchet, 'state', 'unknown'),
                activated_at=getattr(ratchet, '_activated_at', None),
                activated_height=getattr(ratchet, '_activated_height', None),
                confirmed_at=getattr(ratchet, '_confirmed_at', None),
            )
        
        return dict(
            chain_height=chain_height,
            chain_length_required=chain_length,
            chain_ready=chain_height >= chain_length,
            chain_maturity=round(chain_maturity * 100, 2),
            lookbehind=lookbehind,
            total_weight=total_weight,
            sampling_window_size=sampling_window_size,
            sampling_signaling=round(sampling_signaling, 2),
            share_types=share_types,
            current_share_type=current_share_type,
            current_share_name=current_share_name,
            # The effective target (SUCCESSOR version or dominant vote)
            target_version=effective_target,
            target_version_name=effective_target_name,
            # When successor overrides the dominant vote, report the effective
            # target's actual signaling % — not the dominant vote's %.
            target_percentage=round(sampling_signaling if successor_transition else target_percentage, 2),
            # Successor info
            successor_version=successor_version,
            successor_name=successor_name,
            # Desired version voting breakdown (sampling window, weighted)
            versions=version_percentages,
            # Full-chain desired_version votes (unweighted, all tracked shares)
            full_chain_versions=full_chain_version_pcts,
            # Overall V36 stats (full chain, not just sampling window)
            overall_v36_votes=overall_v36_votes,
            overall_v36_vote_pct=round(overall_v36_vote_pct, 2),
            overall_v36_shares=overall_v36_shares,
            overall_v36_share_pct=round(overall_v36_share_pct, 2),
            overall_total=overall_total,
            # Propagation tracking (V36 votes aging toward sampling window)
            propagation_pct=round(propagation_pct, 2),
            propagation_target=propagation_target,
            deepest_v36_position=deepest_v36_pos,
            v36_contiguous_from_tip=v36_contiguous_from_tip,
            current_type_count=current_type_count,
            shares_to_window=shares_to_window,
            time_to_window_seconds=round(time_to_window_seconds, 0),
            # Transition state
            show_transition=show_transition,
            is_transitioning=is_transitioning,
            transition_progress=round(transition_progress, 2),
            thresholds=dict(accept=60, activate=95),
            status=status,
            message=message,
            # Confirmation tracking (ACTIVATED state)
            confirmation_window=chain_length * 2,
            shares_since_activation=max(0, chain_height - (getattr(ratchet, '_activated_height', None) or chain_height)) if ratchet else 0,
            # AutoRatchet state
            auto_ratchet=ratchet_info,
            # Transition message from share messaging system
            transition_message=_get_transition_message(),
            # Authority announcements (non-transition, always shown)
            authority_announcements=_get_authority_announcements(),
            # Address format warnings during transition
            address_warnings=_get_address_warnings(
                is_transitioning, ratchet_confirmed, effective_target),
        )
    
    def _get_authority_announcements():
        """Get authority announcements and alerts (non-transition messages).
        
        Returns a list of dicts with text, type, urgency, timestamp, etc.
        These are always shown on the dashboard regardless of transition state.
        Includes MSG_POOL_ANNOUNCE (0x03), MSG_EMERGENCY (0x10), and other
        authority messages that are NOT MSG_TRANSITION_SIGNAL.
        """
        try:
            store = getattr(node, '_message_store', None)
            if store is None:
                return []
            from p2pool.share_messages import MSG_TRANSITION_SIGNAL
            # Get all authority messages, exclude transition signals
            msgs = store.get_messages(authority_only=True, limit=20)
            msgs = [m for m in msgs if m.msg_type != MSG_TRANSITION_SIGNAL]
            if not msgs:
                return []
            result = []
            for msg in msgs[:10]:
                entry = dict(
                    type=msg.type_name,
                    type_id=msg.msg_type,
                    timestamp=msg.timestamp,
                    age=int(msg.age),
                    verified=msg.verified,
                    authority=msg.is_protocol_authority,
                )
                # Text-based messages (POOL_ANNOUNCE, EMERGENCY)
                if hasattr(msg, 'payload') and msg.payload:
                    try:
                        data = json.loads(msg.payload)
                        entry['text'] = data.get('msg', data.get('text', ''))
                        entry['urgency'] = data.get('urg', data.get('urgency', 'info'))
                        entry['url'] = data.get('url', '')
                    except (ValueError, TypeError):
                        try:
                            entry['text'] = msg.payload.decode('utf-8')
                        except (UnicodeDecodeError, AttributeError):
                            entry['text'] = ''
                        entry['urgency'] = 'info'
                result.append(entry)
            return result
        except Exception:
            return []

    def _get_address_warnings(is_transitioning, ratchet_confirmed, effective_target):
        """Generate address format warnings for V36 merged mining.

        These are node-generated (not authority-signed) informational
        messages.  Always shown so miners can prepare their address
        configuration BEFORE V36 activates — the multi-address stratum
        format only takes effect after the transition switch.
        """
        warnings = []

        parent_symbol = getattr(node.net.PARENT, 'SYMBOL', 'LTC') if hasattr(node.net, 'PARENT') else 'LTC'

        # V35-phase limitation: shares can't carry explicit merged addresses
        if not ratchet_confirmed and effective_target >= 36:
            warnings.append(dict(
                id='v35_addr_limitation',
                urgency='recommended',
                title='V35 Address Limitation (Current Phase)',
                text=(
                    'During V35 (current share format), shares cannot carry '
                    'explicit merged mining addresses. Even if you configure '
                    '%s,DOGE in stratum, PPLNS will use ONLY auto-converted '
                    'DOGE addresses derived from your %s public key hash. '
                    'Explicit address support activates after V36 transition.'
                ) % (parent_symbol, parent_symbol),
            ))

        warnings.append(dict(
            id='multiaddr_format',
            urgency='recommended',
            title='Multi-Address Mining Format',
            text=(
                'V36 introduces merged mining. To receive rewards on both '
                'chains, configure your miner\'s stratum username as: '
                '%s_ADDRESS,DOGE_ADDRESS.worker_name  '
                'Example: Labc...xyz,D9ab...def.rig1'
            ) % parent_symbol,
        ))

        # Auto-conversion warning
        warnings.append(dict(
            id='auto_convert',
            urgency='info',
            title='Address Auto-Conversion',
            text=(
                'If you only provide a %s address, a DOGE address will be '
                'auto-derived from its public key hash. This derived address '
                'may NOT match your actual DOGE wallet — you could lose '
                'merged mining rewards. Always specify your own DOGE address '
                'explicitly.'
            ) % parent_symbol,
        ))

        # Invalid address redistribution warning
        warnings.append(dict(
            id='invalid_addr_redist',
            urgency='info',
            title='Invalid Address Redistribution',
            text=(
                'Miners with invalid or unparseable DOGE addresses will NOT '
                'receive merged mining rewards. Their share of merged rewards '
                'is redistributed probabilistically to other PPLNS miners '
                'with valid addresses.'
            ),
        ))

        return warnings

    # Builtin transition blobs — loaded as fallback if file-based loading fails.
    # Prefer shipping blobs in transition_messages/*.hex instead of embedding here.
    # The ECDSA import fix (coincurve) ensures file-based loading now works reliably.
    _BUILTIN_TRANSITION_BLOBS = [
        # V35 -> V36 mainnet blob moved to transition_messages/transition_v35_v36_mainnet.hex
    ]

    _blobs_loaded = [False]

    def _load_blob_dirs(store):
        """Load transition/bootstrap blobs from all known directories.

        Called once at store creation.  Blobs are deduplicated by
        message hash, so calling again is safe but wasteful (re-reads
        files, re-decrypts, re-verifies ECDSA just to be rejected by
        the dedup set).  To pick up new blobs added after startup,
        restart the node.
        """
        if _blobs_loaded[0]:
            return
        _blobs_loaded[0] = True

        # 1. data/<net>/{bootstrap_messages,transition_messages,transitional_messages}/
        if datadir_path:
            for dirname in ('bootstrap_messages', 'transition_messages', 'transitional_messages'):
                bdir = os.path.join(datadir_path, dirname)
                if os.path.isdir(bdir):
                    n = store.load_bootstrap_blobs(bdir)
                    if n > 0:
                        print('Messaging: loaded %d bootstrap message(s) from %s' % (n, bdir))

        # 2. <repo>/transition_messages/ (shipped with the source code)
        _script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        _module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _search_bases = list(dict.fromkeys([_script_dir, _module_dir]))
        _found_shipped = False
        for _base in _search_bases:
            for _dname in ('transition_messages', 'transitional_messages'):
                shipped_dir = os.path.join(_base, _dname)
                if os.path.isdir(shipped_dir):
                    n = store.load_bootstrap_blobs(shipped_dir)
                    if n > 0:
                        print('Messaging: loaded %d shipped message(s) from %s' % (n, shipped_dir))
                        _found_shipped = True
        if not _found_shipped:
            print('Messaging: no shipped blobs found (searched %s)' % ', '.join(
                os.path.join(b, d) for b in _search_bases for d in ('transition_messages', 'transitional_messages')))

        # 3. --transition-message CLI blob
        if transition_message:
            blob_hex = transition_message
            if os.path.isfile(blob_hex):
                try:
                    with open(blob_hex, 'r') as f:
                        blob_hex = f.read().strip()
                except Exception as e:
                    print('Messaging: ERROR reading --transition-message file %s: %s' % (transition_message, e))
            n = store.load_blob_hex(blob_hex)
            if n > 0:
                print('Messaging: loaded %d message(s) from --transition-message' % n)

        # 4. Builtin hardcoded blobs (always available, no file path dependencies)
        for blob_hex in _BUILTIN_TRANSITION_BLOBS:
            try:
                n = store.load_blob_hex(blob_hex)
                if n > 0:
                    print('Messaging: loaded %d builtin message(s)' % n)
            except Exception:
                pass

    def _get_transition_message():
        """Extract the latest TRANSITION_SIGNAL from the share messaging system.
        
        Returns dict with msg, url, urgency, from_ver, to_ver if found, else None.
        Called on every version_signaling API request (cheap — message store is cached).
        """
        try:
            store = getattr(node, '_message_store', None)
            if store is None:
                # Lazily create the message store (same as _get_message_store in msg API)
                from p2pool.share_messages import ShareMessageStore, BanList
                ban_path = os.path.join(datadir_path, 'banned_senders.json') if datadir_path else None
                ban_list = BanList(persist_path=ban_path) if ban_path else BanList()
                # max_age = sharechain PPLNS window duration (e.g. 8640 * 15 = 36h)
                chain_window_secs = node.net.CHAIN_LENGTH * node.net.SHARE_PERIOD
                store = ShareMessageStore(max_age=chain_window_secs, ban_list=ban_list)
                node._message_store = store
                if node.best_share_var.value is not None:
                    try:
                        chain_len = min(node.net.CHAIN_LENGTH,
                                        node.tracker.get_height(node.best_share_var.value))
                        store.rebuild_from_tracker(
                            node.tracker, node.best_share_var.value, chain_len)
                    except Exception:
                        pass

            # Load blob dirs once (idempotent — skips if already loaded).
            _load_blob_dirs(store)

            from p2pool.share_messages import MSG_TRANSITION_SIGNAL
            signals = store.get_messages(
                msg_type=MSG_TRANSITION_SIGNAL, authority_only=True, limit=5)
            if not signals:
                return None
            # Return the most recent authority-signed transition signal
            msg = signals[0]
            try:
                data = json.loads(msg.payload)
            except (ValueError, TypeError):
                return None
            return dict(
                msg=data.get('msg', ''),
                url=data.get('url', ''),
                urgency=data.get('urg', 'info'),
                from_ver=data.get('from', ''),
                to_ver=data.get('to', ''),
                timestamp=msg.timestamp,
                verified=msg.verified,
                authority=msg.is_protocol_authority,
            )
        except Exception as e:
            print('Messaging: _get_transition_message error: %s' % e)
            return None

    def format_eta(seconds):
        """Format seconds into human-readable ETA."""
        if seconds <= 0:
            return 'now'
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        if hours > 0:
            return '%dh %dm' % (hours, minutes)
        return '%dm' % minutes
    
    def get_global_stats():
        # averaged over last hour
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.tracker.get_height(node.best_share_var.value), 3600//node.net.SHARE_PERIOD)
        
        nonstale_hash_rate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
        stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        diff = bitcoin_data.target_to_difficulty(wb.current_work.value['bits'].target)

        return dict(
            pool_nonstale_hash_rate=nonstale_hash_rate,
            pool_hash_rate=nonstale_hash_rate/(1 - stale_prop),
            pool_stale_prop=stale_prop,
            min_difficulty=bitcoin_data.target_to_difficulty(node.tracker.items[node.best_share_var.value].max_target),
            network_block_difficulty=diff,
            network_hashrate=(diff * 2**32 // node.net.PARENT.BLOCK_PERIOD),
        )
    
    def get_attempts_to_merged_block(wb):
        """Get the average attempts needed to find a merged mining block"""
        try:
            if hasattr(wb, 'merged_work') and wb.merged_work and hasattr(wb.merged_work, 'value') and wb.merged_work.value:
                for chain_id, chain in wb.merged_work.value.iteritems():
                    # First try template path (getblocktemplate)
                    if 'template' in chain and chain['template']:
                        template = chain['template']
                        if 'bits' in template:
                            bits_hex = template['bits']
                            if isinstance(bits_hex, basestring):
                                bits_int = int(bits_hex, 16)
                            else:
                                bits_int = bits_hex
                            exponent = bits_int >> 24
                            mantissa = bits_int & 0xffffff
                            target = mantissa * (1 << (8 * (exponent - 3)))
                            return bitcoin_data.target_to_average_attempts(target)
                    
                    # Fallback: use target directly from createauxblock/getauxblock
                    if 'target' in chain and chain['target'] != 'p2pool':
                        target = chain['target']
                        if isinstance(target, (int, long)):
                            return bitcoin_data.target_to_average_attempts(target)
        except Exception as e:
            print "[MERGED] Error getting attempts_to_merged_block: %s" % e
        return None
    
    def get_local_stats():
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.tracker.get_height(node.best_share_var.value), 3600//node.net.SHARE_PERIOD)
        
        global_stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        
        my_unstale_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes)
        my_orphan_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes and share.share_data['stale_info'] == 'orphan')
        my_doa_count = sum(1 for share in node.tracker.get_chain(node.best_share_var.value, lookbehind) if share.hash in wb.my_share_hashes and share.share_data['stale_info'] == 'doa')
        my_share_count = my_unstale_count + my_orphan_count + my_doa_count
        my_stale_count = my_orphan_count + my_doa_count
        
        my_stale_prop = my_stale_count/my_share_count if my_share_count != 0 else None
        
        my_work = sum(bitcoin_data.target_to_average_attempts(share.target)
            for share in node.tracker.get_chain(node.best_share_var.value, lookbehind - 1)
            if share.hash in wb.my_share_hashes)
        actual_time = (node.tracker.items[node.best_share_var.value].timestamp -
            node.tracker.items[node.tracker.get_nth_parent_hash(node.best_share_var.value, lookbehind - 1)].timestamp)
        share_att_s = my_work / actual_time
        
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()

        miner_last_difficulties = {}
        for addr in wb.last_work_shares.value:
            miner_last_difficulties[addr] = bitcoin_data.target_to_difficulty(wb.last_work_shares.value[addr].target)
        
        return dict(
            my_hash_rates_in_last_hour=dict(
                note="DEPRECATED",
                nonstale=share_att_s,
                rewarded=share_att_s/(1 - global_stale_prop),
                actual=share_att_s/(1 - my_stale_prop) if my_stale_prop is not None else 0, # 0 because we don't have any shares anyway
            ),
            my_share_counts_in_last_hour=dict(
                shares=my_share_count,
                unstale_shares=my_unstale_count,
                stale_shares=my_stale_count,
                orphan_stale_shares=my_orphan_count,
                doa_stale_shares=my_doa_count,
            ),
            my_stale_proportions_in_last_hour=dict(
                stale=my_stale_prop,
                orphan_stale=my_orphan_count/my_share_count if my_share_count != 0 else None,
                dead_stale=my_doa_count/my_share_count if my_share_count != 0 else None,
            ),
            miner_hash_rates=miner_hash_rates,
            miner_dead_hash_rates=miner_dead_hash_rates,
            miner_last_difficulties=miner_last_difficulties,
            efficiency_if_miner_perfect=(1 - stale_orphan_shares/shares)/(1 - global_stale_prop) if shares else None, # ignores dead shares because those are miner's fault and indicated by pseudoshare rejection
            efficiency=(1 - (stale_orphan_shares+stale_doa_shares)/shares)/(1 - global_stale_prop) if shares else None,
            peers=dict(
                incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
                outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
            ),
            shares=dict(
                total=shares,
                orphan=stale_orphan_shares,
                dead=stale_doa_shares,
            ),
            uptime=time.time() - start_time,
            attempts_to_share=bitcoin_data.target_to_average_attempts(node.tracker.items[node.best_share_var.value].max_target),
            attempts_to_block=bitcoin_data.target_to_average_attempts(node.bitcoind_work.value['bits'].target),
            attempts_to_merged_block=get_attempts_to_merged_block(wb),
            block_value=node.bitcoind_work.value['subsidy']*1e-8,
            warnings=p2pool_data.get_warnings(node.tracker, node.best_share_var.value, node.net, bitcoind_getinfo_var.value, node.bitcoind_work.value,
                merged_work=wb.merged_work.value if hasattr(wb, 'merged_work') and wb.merged_work and hasattr(wb.merged_work, 'value') and wb.merged_work.value else None,
                auto_ratchet=getattr(wb, 'auto_ratchet', None)),
            donation_proportion=wb.donation_percentage/100,
            version=p2pool.__version__,
            protocol_version=p2p.Protocol.VERSION,
            fee=getattr(wb, 'node_owner_fee', wb.worker_fee),
        )
    
    class WebInterface(deferred_resource.DeferredResource):
        def __init__(self, func, mime_type='application/json', args=()):
            deferred_resource.DeferredResource.__init__(self)
            self.func, self.mime_type, self.args = func, mime_type, args
        
        def getChild(self, child, request):
            return WebInterface(self.func, self.mime_type, self.args + (child,))
        
        @defer.inlineCallbacks
        def render_GET(self, request):
            request.setHeader('Content-Type', self.mime_type)
            request.setHeader('Access-Control-Allow-Origin', '*')
            res = yield self.func(*self.args)
            defer.returnValue(json.dumps(res) if self.mime_type == 'application/json' else res)
    
    def decent_height():
        return min(node.tracker.get_height(node.best_share_var.value), 720)
    web_root.putChild('rate', WebInterface(lambda: p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, decent_height())/(1-p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, decent_height()))))
    web_root.putChild('difficulty', WebInterface(lambda: bitcoin_data.target_to_difficulty(node.tracker.items[node.best_share_var.value].max_target)))
    web_root.putChild('users', WebInterface(get_users))
    web_root.putChild('user_stales', WebInterface(lambda:
        p2pool_data.get_user_stale_props(node.tracker, node.best_share_var.value,
            node.tracker.get_height(node.best_share_var.value), node.net.PARENT)))
    web_root.putChild('fee', WebInterface(lambda: getattr(wb, 'node_owner_fee', wb.worker_fee)))
    web_root.putChild('current_payouts', WebInterface(lambda: dict(
        (address, value/1e8) for address, value
            in node.get_current_txouts().iteritems())))
    
    # Import merged chain networks for address conversion
    try:
        from p2pool.bitcoin.networks import dogecoin_testnet as dogecoin_testnet_net
        from p2pool.bitcoin.networks import dogecoin as dogecoin_net
    except ImportError:
        dogecoin_testnet_net = None
        dogecoin_net = None
    
    def get_current_merged_payouts():
        """
        Get current payouts with merged chain addresses from V36 PPLNS weights.
        
        Uses get_v36_merged_weights() to compute the actual sharechain-derived
        payout distribution. Two types of merged address keys:
          - 'MERGED:<hex_script>': Explicit merged chain address from V36 share's
            merged_addresses field. Decoded and displayed directly.
          - Parent chain address string: Auto-converted from LTC to DOGE format.
            P2SH/P2WSH/P2TR addresses cannot be converted — their weight is
            redistributed proportionally to convertible/explicit addresses.
        
        Returns dict: {parent_address: {amount: X, merged: [{network, symbol, address, amount, source}, ...]}}
        """
        from p2pool.work import is_pubkey_hash_address
        
        # Get main chain payouts for display
        main_payouts = dict((address, value/1e8) for address, value
                            in node.get_current_txouts().iteritems())
        
        # Check if we have merged work active
        merged_chains = []
        if hasattr(wb, 'merged_work') and wb.merged_work.value:
            for chainid, aux_work in wb.merged_work.value.iteritems():
                merged_reward = aux_work.get('coinbasevalue', 0)
                if merged_reward == 0:
                    template = aux_work.get('template')
                    if template and 'coinbasevalue' in template:
                        merged_reward = template['coinbasevalue']
                
                if chainid == 98:  # Dogecoin
                    merged_net_name = 'Dogecoin'
                    merged_net_symbol = 'DOGE'
                    parent_symbol = getattr(node.net.PARENT, 'SYMBOL', '') if hasattr(node.net, 'PARENT') else ''
                    is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
                    if is_testnet:
                        merged_net_name = 'Dogecoin Testnet'
                        merged_net_symbol = 'tDOGE'
                        merged_addr_net = dogecoin_testnet_net
                    else:
                        merged_addr_net = dogecoin_net
                else:
                    merged_net_name = aux_work.get('merged_net_name', 'Unknown')
                    merged_net_symbol = aux_work.get('merged_net_symbol', 'AUX')
                    merged_addr_net = None
                
                if merged_addr_net:
                    merged_chains.append({
                        'chainid': chainid,
                        'network': merged_net_name,
                        'symbol': merged_net_symbol,
                        'addr_net': merged_addr_net,
                        'reward': merged_reward,
                    })
        
        # Build result — start with main chain payouts
        result = {}
        for parent_address, amount in main_payouts.iteritems():
            result[parent_address] = {'amount': amount, 'merged': []}
        
        best = node.best_share_var.value
        parent_net = node.net.PARENT if hasattr(node.net, 'PARENT') else node.net
        
        for chain in merged_chains:
            if best is None or chain['reward'] <= 0:
                continue
            
            # Get V36 PPLNS weights for this merged chain
            try:
                share_height = node.tracker.get_height(best)
                parent_block_target = node.bitcoind_work.value['bits'].target
                weights, total_weight, donation_weight = p2pool_data.get_v36_merged_weights(
                    node.tracker,
                    best,
                    max(0, min(share_height, node.net.REAL_CHAIN_LENGTH)),
                    65535 * node.net.SPREAD * bitcoin_data.target_to_average_attempts(parent_block_target),
                    chain_id=chain['chainid'],
                )
            except Exception:
                continue
            
            if total_weight <= 0:
                continue
            
            # Build MERGED_script → parent_address mapping by walking shares.
            # get_v36_merged_weights loses this association. We need it to nest
            # explicit DOGE payouts under their parent LTC address in the result.
            merged_key_to_parent = {}  # {'MERGED:<script_hex>': parent_address}
            try:
                chain_len = max(0, min(share_height, node.net.REAL_CHAIN_LENGTH))
                for share in node.tracker.get_chain(best, chain_len):
                    if share.VERSION >= 36:
                        merged_addrs = getattr(share, 'merged_addresses', None)
                        if merged_addrs is None and hasattr(share, 'share_info') and isinstance(share.share_info, dict):
                            merged_addrs = share.share_info.get('merged_addresses', None)
                        if merged_addrs:
                            for entry in merged_addrs:
                                if entry['chain_id'] == chain['chainid']:
                                    mkey = 'MERGED:' + entry['script'].encode('hex')
                                    if mkey not in merged_key_to_parent:
                                        merged_key_to_parent[mkey] = share.address
                                    break
            except Exception:
                pass
            
            # Resolve weight keys to merged chain addresses.
            # Two key types from get_v36_merged_weights():
            #   'MERGED:<hex_script>' = explicit merged chain script
            #   parent_address_string = needs auto-conversion
            resolved = {}       # {merged_address: weight}
            key_to_parent = {}  # {merged_address: parent_address}
            accepted_weight = 0
            
            for key, weight in weights.iteritems():
                try:
                    if key.startswith('MERGED:'):
                        # Explicit merged chain script from V36 share
                        merged_script = key[7:].decode('hex')
                        try:
                            merged_address = bitcoin_data.script2_to_address(
                                merged_script, chain['addr_net'].ADDRESS_VERSION, -1, chain['addr_net'])
                        except Exception:
                            merged_address = 'script:' + key[7:]  # Fallback for non-P2PKH scripts
                        resolved[merged_address] = resolved.get(merged_address, 0) + weight
                        # Use the share chain mapping to find the parent LTC address
                        parent_addr = merged_key_to_parent.get(key, None)
                        if parent_addr:
                            key_to_parent[merged_address] = parent_addr
                        accepted_weight += weight
                    else:
                        # Parent chain address — try auto-conversion
                        addr_result = is_pubkey_hash_address(key, parent_net)
                        is_convertible = addr_result[0]
                        pubkey_hash = addr_result[1]
                        addr_type = addr_result[3] if len(addr_result) > 3 else 'p2pkh'
                        if is_convertible and pubkey_hash is not None:
                            if addr_type == 'p2sh':
                                merged_address = bitcoin_data.pubkey_hash_to_address(
                                    pubkey_hash, chain['addr_net'].ADDRESS_P2SH_VERSION, -1, chain['addr_net'])
                            else:
                                merged_address = bitcoin_data.pubkey_hash_to_address(
                                    pubkey_hash, chain['addr_net'].ADDRESS_VERSION, -1, chain['addr_net'])
                            resolved[merged_address] = resolved.get(merged_address, 0) + weight
                            key_to_parent[merged_address] = key
                            accepted_weight += weight
                        # else: unconvertible — weight redistributed via smaller denominator
                except Exception:
                    pass
            
            if accepted_weight <= 0:
                continue
            
            # Distributable merged reward = total reward minus donation portion
            # total_weight from get_v36_merged_weights() already includes donation_weight
            # (convention: total_weight == sum(weights.values()) + donation_weight)
            miner_weight = total_weight - donation_weight
            miner_reward = chain['reward'] * float(miner_weight) / float(total_weight) if total_weight > 0 else chain['reward']
            donation_reward = chain['reward'] - miner_reward
            
            # Enforce dust threshold to match actual coinbase builder (merged_mining.py)
            dust_threshold = getattr(chain['addr_net'], 'DUST_THRESHOLD', int(1e8))
            if donation_reward < dust_threshold and chain['reward'] > dust_threshold:
                donation_reward = float(dust_threshold)
                miner_reward = chain['reward'] - donation_reward
            
            # Assign merged payouts to parent addresses
            for merged_address, weight in resolved.iteritems():
                fraction = float(weight) / float(accepted_weight)
                merged_amount = miner_reward * fraction / 1e8
                
                parent_addr = key_to_parent.get(merged_address, None)
                source = 'auto-convert' if parent_addr and merged_address not in merged_key_to_parent.values() else 'explicit'
                # Determine source: if merged_address came from a MERGED: key, it's explicit
                has_explicit_key = any(merged_key_to_parent.get(k) == parent_addr 
                                       for k in weights if k.startswith('MERGED:')) if parent_addr else False
                if has_explicit_key:
                    source = 'explicit'
                elif parent_addr:
                    source = 'auto-convert'
                else:
                    source = 'explicit'
                
                entry = {
                    'network': chain['network'],
                    'symbol': chain['symbol'],
                    'address': merged_address,
                    'amount': merged_amount,
                    'source': source,
                }
                
                if parent_addr and parent_addr in result:
                    result[parent_addr]['merged'].append(entry)
                elif merged_address not in result:
                    result[merged_address] = {'amount': 0, 'merged': []}
                    result[merged_address]['merged'].append(entry)
                else:
                    result[merged_address]['merged'].append(entry)
            
            # Add donation info — use precomputed DOGE P2SH address and nest
            # under the LTC donation address that already exists in main payouts.
            # All addresses are hardcoded constants to avoid per-request crypto
            # (DDoS on web API must not starve the mining reactor loop).
            if donation_reward > 0:
                from p2pool import data as p2pool_data_mod
                ltc_donation_addr = p2pool_data_mod.donation_script_to_address(node.net)
                
                # Precomputed DOGE P2SH addresses for COMBINED_DONATION_SCRIPT
                if chain['chainid'] == 98:  # Dogecoin
                    parent_symbol = getattr(node.net.PARENT, 'SYMBOL', '') if hasattr(node.net, 'PARENT') else ''
                    is_testnet = parent_symbol.lower().startswith('t') or 'test' in parent_symbol.lower()
                    doge_donation_addr = p2pool_data_mod.COMBINED_DONATION_DOGE_TESTNET if is_testnet else p2pool_data_mod.COMBINED_DONATION_DOGE_MAINNET
                else:
                    doge_donation_addr = '(donation)'
                
                donation_entry = {
                    'network': chain['network'],
                    'symbol': chain['symbol'],
                    'address': doge_donation_addr,
                    'amount': donation_reward / 1e8,
                    'source': 'donation',
                }
                # Attach to the LTC donation address entry
                if ltc_donation_addr and ltc_donation_addr in result:
                    result[ltc_donation_addr]['merged'].append(donation_entry)
                else:
                    # Fallback: create the entry if main payouts didn't include it
                    result.setdefault(ltc_donation_addr or '_donation', {'amount': 0, 'merged': []})
                    result[ltc_donation_addr or '_donation']['merged'].append(donation_entry)
        
        return result
    
    web_root.putChild('current_merged_payouts', WebInterface(get_current_merged_payouts))
    web_root.putChild('patron_sendmany', WebInterface(get_patron_sendmany, 'text/plain'))
    web_root.putChild('global_stats', WebInterface(get_global_stats))
    web_root.putChild('local_stats', WebInterface(get_local_stats))
    web_root.putChild('version_signaling', WebInterface(get_version_signaling))
    web_root.putChild('peer_addresses', WebInterface(lambda: ' '.join('%s%s' % (peer.transport.getPeer().host, ':'+str(peer.transport.getPeer().port) if peer.transport.getPeer().port != node.net.P2P_PORT else '') for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('peer_txpool_sizes', WebInterface(lambda: dict(('%s:%i' % (peer.transport.getPeer().host, peer.transport.getPeer().port), peer.remembered_txs_size) for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('pings', WebInterface(defer.inlineCallbacks(lambda: defer.returnValue(
        dict([(a, (yield b)) for a, b in
            [(
                '%s:%i' % (peer.transport.getPeer().host, peer.transport.getPeer().port),
                defer.inlineCallbacks(lambda peer=peer: defer.returnValue(
                    min([(yield peer.do_ping().addCallback(lambda x: x/0.001).addErrback(lambda fail: None)) for i in xrange(3)])
                ))()
            ) for peer in list(node.p2p_node.peers.itervalues())]
        ])
    ))))
    web_root.putChild('peer_versions', WebInterface(lambda: dict(('%s:%i' % peer.addr, peer.other_sub_version) for peer in node.p2p_node.peers.itervalues())))
    web_root.putChild('payout_addr', WebInterface(lambda: wb.address))
    web_root.putChild('payout_addrs', WebInterface(
        lambda: list(add['address'] for add in wb.pubkeys.keys)))
    
    # ==== Stratum statistics endpoint ====
    def get_stratum_stats():
        """Get stratum pool statistics including per-worker data"""
        try:
            from p2pool.bitcoin.stratum import pool_stats
            stats = pool_stats.get_pool_stats()
            worker_stats = pool_stats.get_worker_stats()
            connected_workers = pool_stats.get_connected_workers()
            
            # Format worker stats for JSON
            formatted_workers = {}
            for worker_name, wstats in worker_stats.items():
                # Get aggregate connection stats
                conn_aggregate = pool_stats.get_worker_aggregate_stats(worker_name)
                
                # Get merged addresses from connected workers if available
                cw_info = connected_workers.get(worker_name, {})
                
                formatted_workers[worker_name] = {
                    'shares': wstats.get('shares', 0),
                    'accepted': wstats.get('accepted', 0),
                    'rejected': wstats.get('rejected', 0),
                    'hash_rate': wstats.get('hash_rate', 0),
                    'last_seen': wstats.get('last_seen', 0),
                    'first_seen': wstats.get('first_seen', 0),
                    # Connection aggregate stats
                    'connections': conn_aggregate.get('connection_count', 0) if conn_aggregate else 0,
                    'active_connections': conn_aggregate.get('active_connections', 0) if conn_aggregate else 0,
                    'backup_connections': conn_aggregate.get('backup_connections', 0) if conn_aggregate else 0,
                    'connection_difficulties': conn_aggregate.get('difficulties', []) if conn_aggregate else [],
                    'merged_addresses': cw_info.get('merged_addresses', {}),
                    'merged_auto_converted': cw_info.get('merged_auto_converted', False),
                }
            
            # Also include currently connected workers (even if no shares yet)
            for worker_name, winfo in connected_workers.items():
                if worker_name not in formatted_workers:
                    formatted_workers[worker_name] = {
                        'shares': 0,
                        'accepted': 0,
                        'rejected': 0,
                        'hash_rate': 0,
                        'last_seen': 0,
                        'first_seen': 0,
                        'connections': winfo.get('connections', 0),
                        'active_connections': 0,
                        'backup_connections': winfo.get('connections', 0),
                        'connection_difficulties': winfo.get('difficulties', []),
                        'merged_addresses': winfo.get('merged_addresses', {}),
                        'merged_auto_converted': winfo.get('merged_auto_converted', False),
                    }
                else:
                    # Update connection info for existing workers
                    formatted_workers[worker_name]['connections'] = winfo.get('connections', 0)
                    formatted_workers[worker_name]['connection_difficulties'] = winfo.get('difficulties', [])
                    # Add merged addresses if not already set
                    if 'merged_addresses' not in formatted_workers[worker_name]:
                        formatted_workers[worker_name]['merged_addresses'] = winfo.get('merged_addresses', {})
                        formatted_workers[worker_name]['merged_auto_converted'] = winfo.get('merged_auto_converted', False)
            
            return {
                'pool': stats,
                'workers': formatted_workers,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'error': str(e)}
    
    web_root.putChild('stratum_stats', WebInterface(get_stratum_stats))
    
    # ==== Stratum security monitoring endpoint ====
    def get_stratum_security():
        """Get stratum security and DDoS detection metrics"""
        try:
            from p2pool.bitcoin.stratum import pool_stats
            return pool_stats.get_security_stats()
        except Exception as e:
            return {'error': str(e)}
    
    web_root.putChild('stratum_security', WebInterface(get_stratum_security))
    
    # ==== Ban stats endpoint ====
    def get_ban_stats():
        """Get current ban statistics"""
        try:
            from p2pool.bitcoin.stratum import pool_stats
            return pool_stats.get_ban_stats()
        except Exception as e:
            return {'error': str(e)}
    
    web_root.putChild('ban_stats', WebInterface(get_ban_stats))
    
    # ==== Connected miners endpoint (all miners currently connected via stratum) ====
    def get_connected_miners():
        """Get list of all currently connected miner addresses"""
        try:
            from p2pool.bitcoin.stratum import pool_stats
            connected_workers = pool_stats.get_connected_workers()
            
            # Extract unique addresses from connected workers
            addresses = set()
            for worker_name, winfo in connected_workers.items():
                addr = winfo.get('address')
                if addr:
                    addresses.add(addr)
                else:
                    # Try to extract address from worker name (format: address.worker or address)
                    base_addr = worker_name.split('+')[0].split('/')[0].split('.')[0].split('_')[0]
                    if base_addr:
                        addresses.add(base_addr)
            
            return list(addresses)
        except Exception as e:
            return []
    
    web_root.putChild('connected_miners', WebInterface(get_connected_miners))
    
    # ==== Individual miner stats endpoint ====
    def get_miner_stats(address=None):
        """Get detailed statistics for a specific miner address"""
        if not address:
            return {'error': 'No address provided', 'active': False}
        
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        
        # Extract base address and find all matching workers
        # Supported formats: address.worker, address_worker, address+diff, address/diff, address,dogeaddr
        def extract_base_address(worker_name):
            # Handle multiaddress format: LTC_ADDR,DOGE_ADDR.worker
            base = worker_name.split(',')[0]  # Take LTC address part
            return base.split('+')[0].split('/')[0].split('.')[0].split('_')[0]
        
        # Aggregate stats for all workers belonging to this address
        hashrate = 0
        dead_hashrate = 0
        found_workers = False
        estimated_hashrate = False
        worker_difficulties = {}
        
        # First, check measured hashrate from miner_hash_rates
        for worker_name in miner_hash_rates:
            if extract_base_address(worker_name) == address:
                found_workers = True
                hashrate += miner_hash_rates.get(worker_name, 0)
                dead_hashrate += miner_dead_hash_rates.get(worker_name, 0)
        
        # If no measured hashrate, check stratum connections and estimate from difficulty
        if not found_workers or hashrate == 0:
            try:
                from p2pool.bitcoin.stratum import pool_stats
                if pool_stats:
                    stratum_workers = pool_stats.get_worker_stats()
                    
                    dumb_scrypt_diff = node.net.PARENT.DUMB_SCRYPT_DIFF if hasattr(node.net.PARENT, 'DUMB_SCRYPT_DIFF') else 2**32
                    vardiff_target = wb.share_rate if hasattr(wb, 'share_rate') else 3.0  # Default 3 seconds per share
                    
                    for worker_name, worker_data in stratum_workers.items():
                        if extract_base_address(worker_name) == address:
                            found_workers = True
                            # Get difficulty from stratum connection
                            worker_diff = 0
                            # Get aggregate stats for this worker to get connection difficulties
                            conn_aggregate = pool_stats.get_worker_aggregate_stats(worker_name)
                            if conn_aggregate and conn_aggregate.get('difficulties'):
                                worker_diff = conn_aggregate['difficulties'][0]
                                worker_difficulties[worker_name] = worker_diff
                            
                            # Try measured hashrate first, then estimate from difficulty
                            worker_hashrate = worker_data.get('hash_rate', 0)
                            if worker_hashrate == 0 and worker_diff > 0:
                                # Estimate: hashrate = difficulty * DUMB_SCRYPT_DIFF / vardiff_target
                                worker_hashrate = worker_diff * dumb_scrypt_diff / vardiff_target
                                estimated_hashrate = True
                            
                            hashrate += worker_hashrate
                    
                    # Also check connected workers (those with active connections but no shares yet)
                    connected_workers = pool_stats.get_connected_workers()
                    for worker_name, winfo in connected_workers.items():
                        if extract_base_address(worker_name) == address and worker_name not in stratum_workers:
                            found_workers = True
                            conn_aggregate = pool_stats.get_worker_aggregate_stats(worker_name)
                            if conn_aggregate and conn_aggregate.get('difficulties'):
                                worker_diff = conn_aggregate['difficulties'][0]
                                worker_difficulties[worker_name] = worker_diff
                                # Estimate hashrate from difficulty
                                worker_hashrate = worker_diff * dumb_scrypt_diff / vardiff_target
                                hashrate += worker_hashrate
                                estimated_hashrate = True
            except Exception as e:
                import traceback
                traceback.print_exc()
        
        if not found_workers:
            return {'error': 'Miner not found', 'active': False}
        
        # Current rates
        doa_rate = dead_hashrate / hashrate if hashrate > 0 else 0
        
        # Current payout - txouts keys are already addresses
        current_payout = 0
        try:
            current_txouts = node.get_current_txouts()
            # txouts is {address: satoshis}, address is the key we need
            current_payout = current_txouts.get(address, 0) / 1e8
        except (ValueError, KeyError, IndexError):
            pass
        
        # Share difficulty - check all workers for this address
        # First check last_work_shares, then use stratum worker_difficulties if available
        miner_last_diff = 0
        for worker_name in wb.last_work_shares.value:
            if extract_base_address(worker_name) == address:
                worker_diff = bitcoin_data.target_to_difficulty(wb.last_work_shares.value[worker_name].target)
                miner_last_diff = max(miner_last_diff, worker_diff)
        
        # Fall back to stratum difficulties if we didn't find any from last_work_shares
        if miner_last_diff == 0 and worker_difficulties:
            for worker_name, worker_diff in worker_difficulties.items():
                miner_last_diff = max(miner_last_diff, worker_diff)
        
        # Time to share - use attempts_to_share from local_stats
        dumb_scrypt_diff = node.net.PARENT.DUMB_SCRYPT_DIFF if hasattr(node.net.PARENT, 'DUMB_SCRYPT_DIFF') else 2**32
        attempts_to_share = bitcoin_data.target_to_average_attempts(node.tracker.items[node.best_share_var.value].max_target)
        time_to_share = attempts_to_share / hashrate if hashrate > 0 else float('inf')
        
        # Get global stats for context
        global_stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, min(node.tracker.get_height(node.best_share_var.value), 720))
        
        # Get merged mining payouts for this address
        merged_payouts = []
        try:
            merged_data = get_current_merged_payouts()
            if address in merged_data and 'merged' in merged_data[address]:
                merged_payouts = merged_data[address]['merged']
        except:
            pass
        
        # Get best difficulty for all workers of this address
        best_diff_all_time = 0
        best_diff_session = 0
        best_diff_round = 0
        session_start = wb.session_start_time
        for worker_name in miner_hash_rates:
            if extract_base_address(worker_name) == address:
                worker_best = wb.get_miner_best_difficulty(worker_name)
                best_diff_all_time = max(best_diff_all_time, worker_best['all_time'])
                best_diff_session = max(best_diff_session, worker_best['session'])
                best_diff_round = max(best_diff_round, worker_best['round'])
        
        # Get hashrate periods for all workers of this address
        hashrate_periods = {'1m': {'hashrate': 0, 'dead_hashrate': 0},
                          '10m': {'hashrate': 0, 'dead_hashrate': 0},
                          '1h': {'hashrate': 0, 'dead_hashrate': 0}}
        for worker_name in miner_hash_rates:
            if extract_base_address(worker_name) == address:
                worker_periods = wb.get_miner_hashrate_periods(worker_name)
                for period in hashrate_periods:
                    if period in worker_periods:
                        hashrate_periods[period]['hashrate'] += worker_periods[period]['hashrate']
                        hashrate_periods[period]['dead_hashrate'] += worker_periods[period]['dead_hashrate']
        
        # Calculate network difficulty for "chance to find block"
        network_difficulty = bitcoin_data.target_to_difficulty(node.bitcoind_work.value['bits'].target)
        chance_to_find_block = (best_diff_all_time / network_difficulty * 100) if network_difficulty > 0 and best_diff_all_time > 0 else 0
        
        # Calculate equivalent hashrate for best difficulty
        # For Scrypt: hashrate = difficulty * DUMB_SCRYPT_DIFF (2^16 = 65536)
        # For SHA256: hashrate = difficulty * 2^32
        dumb_scrypt_diff = node.net.PARENT.DUMB_SCRYPT_DIFF if hasattr(node.net.PARENT, 'DUMB_SCRYPT_DIFF') else 2**32
        best_diff_hashrate_all_time = best_diff_all_time * dumb_scrypt_diff
        best_diff_hashrate_session = best_diff_session * dumb_scrypt_diff
        
        # Count shares for this miner address in the current window
        lookbehind = min(node.tracker.get_height(node.best_share_var.value), 3600//node.net.SHARE_PERIOD)
        miner_share_count = 0
        miner_orphan_count = 0
        miner_doa_count = 0
        try:
            for share in node.tracker.get_chain(node.best_share_var.value, lookbehind):
                share_addr = getattr(share, 'address', None)
                if share_addr == address:
                    if share.share_data.get('stale_info') == 'orphan':
                        miner_orphan_count += 1
                    elif share.share_data.get('stale_info') == 'doa':
                        miner_doa_count += 1
                    else:
                        miner_share_count += 1
        except Exception as e:
            pass
        
        total_miner_shares = miner_share_count + miner_orphan_count + miner_doa_count
        miner_dead_shares = miner_orphan_count + miner_doa_count
        
        return dict(
            address=address,
            active=True,
            hashrate=hashrate,
            estimated_hashrate=estimated_hashrate,  # True if hashrate is estimated from difficulty
            dead_hashrate=dead_hashrate,
            doa_rate=doa_rate,
            share_difficulty=miner_last_diff,
            time_to_share=time_to_share,
            current_payout=current_payout,
            merged_payouts=merged_payouts,
            global_stale_prop=global_stale_prop,
            # New fields for enhanced stats
            best_difficulty_all_time=best_diff_all_time,
            best_difficulty_session=best_diff_session,
            best_difficulty_round=best_diff_round,
            best_diff_hashrate_all_time=best_diff_hashrate_all_time,
            best_diff_hashrate_session=best_diff_hashrate_session,
            session_start=session_start,
            round_start=wb.node_best_difficulty['round_start'],
            hashrate_periods=hashrate_periods,
            network_difficulty=network_difficulty,
            chance_to_find_block=chance_to_find_block,
            # Share counts
            total_shares=total_miner_shares,
            unstale_shares=miner_share_count,
            dead_shares=miner_dead_shares,
            orphan_shares=miner_orphan_count,
            doa_shares=miner_doa_count,
        )
    
    web_root.putChild('miner_stats', WebInterface(get_miner_stats))
    
    # ==== Node-wide best share stats (BitAxe style) ====
    def get_best_share():
        """Return node-wide best share stats: all-time, session, and current round"""
        nb = wb.node_best_difficulty
        network_difficulty = bitcoin_data.target_to_difficulty(node.bitcoind_work.value['bits'].target)
        
        def pct_of_block(diff, net_diff):
            return (diff / net_diff * 100) if net_diff > 0 and diff > 0 else 0
        
        result = dict(
            network_difficulty=network_difficulty,
            all_time=dict(
                difficulty=nb['all_time'],
                pct_of_block=pct_of_block(nb['all_time'], network_difficulty),
                miner=nb['all_time_user'],
                timestamp=nb['all_time_ts'],
            ),
            session=dict(
                difficulty=nb['session'],
                pct_of_block=pct_of_block(nb['session'], network_difficulty),
                miner=nb['session_user'],
                timestamp=nb['session_ts'],
                started=wb.session_start_time,
            ),
            round=dict(
                difficulty=nb['round'],
                pct_of_block=pct_of_block(nb['round'], network_difficulty),
                miner=nb['round_user'],
                timestamp=nb['round_ts'],
                started=nb['round_start'],
            ),
        )
        
        # Add merged chain (DOGE) best share stats
        mb = wb.merged_best_difficulty
        merged_difficulty = 0
        merged_symbol = None
        try:
            for chainid, aux_work in wb.merged_work.value.iteritems():
                merged_target = aux_work.get('target', 0)
                if merged_target and merged_target > 0:
                    merged_difficulty = bitcoin_data.target_to_difficulty(merged_target)
                    merged_symbol = aux_work.get('merged_net_symbol', 'DOGE' if chainid == 98 else 'AUX')
                    break
        except Exception:
            pass
        
        if merged_difficulty > 0 or mb['all_time'] > 0:
            result['merged'] = dict(
                network_difficulty=merged_difficulty,
                symbol=merged_symbol or 'DOGE',
                all_time=dict(
                    difficulty=mb['all_time'],
                    pct_of_block=pct_of_block(mb['all_time'], merged_difficulty),
                    miner=mb['all_time_user'],
                    timestamp=mb['all_time_ts'],
                ),
                round=dict(
                    difficulty=mb['round'],
                    pct_of_block=pct_of_block(mb['round'], merged_difficulty),
                    miner=mb['round_user'],
                    timestamp=mb['round_ts'],
                    started=mb['round_start'],
                ),
            )
        
        return result
    web_root.putChild('best_share', WebInterface(get_best_share))
    
    # ==== Individual miner payouts endpoint ====
    def get_miner_payouts(address=None):
        """Get payout history for a specific miner address"""
        if not address:
            return {'error': 'No address provided'}
        
        # Current payout from txouts - keys are already addresses
        current_payout = 0
        try:
            current_txouts = node.get_current_txouts()
            current_payout = current_txouts.get(address, 0) / 1e8
        except (ValueError, KeyError, IndexError):
            pass
        
        # Find blocks found by this miner from block_history
        miner_blocks = []
        total_estimated_rewards = 0.0
        confirmed_rewards = 0.0
        maturing_rewards = 0.0
        
        try:
            block_explorer_url = node.net.PARENT.BLOCK_EXPLORER_URL_PREFIX
        except:
            block_explorer_url = ''
        
        # Get current blockchain height for confirmation tracking
        try:
            current_height = node.bitcoind_work.value['height']
        except:
            current_height = 0
        
        # Fallback subsidy (current) for old blocks that don't have it stored
        try:
            current_subsidy = node.bitcoind_work.value['subsidy']
        except:
            current_subsidy = 0
        
        # Coinbase maturity (100 for LTC)
        COINBASE_MATURITY = 100
        
        for b in block_history:
            # Strip merged DOGE address (comma) and worker suffix for matching
            block_miner = b.get('miner', '')
            if block_miner:
                block_miner = block_miner.split(',')[0].split('.')[0].split('+')[0].split('/')[0].split('_')[0]
            if block_miner == address:
                block_hash = b.get('hash', '')
                block_height = b.get('number', 0)
                
                # Block reward (subsidy) in coins - fall back to current if missing
                subsidy = b.get('subsidy', 0) or current_subsidy
                block_reward = subsidy / 1e8 if subsidy > 0 else 0
                
                # Miner's estimated payout from this block (in coins)
                # Fall back to current_payout proportion * block_reward if not stored
                stored_payout = b.get('miner_payout', 0)
                if stored_payout > 0:
                    est_payout = stored_payout / 1e8
                elif current_payout > 0 and block_reward > 0:
                    # Estimate: miner's current share proportion * block reward
                    est_payout = current_payout
                else:
                    est_payout = 0
                
                # Confirmation tracking
                confirmations = max(0, current_height - block_height) if current_height > 0 and block_height > 0 else 0
                is_mature = confirmations >= COINBASE_MATURITY
                
                if b.get('status') == 'confirmed' or b.get('verified'):
                    if is_mature:
                        status = 'confirmed'
                    else:
                        status = 'maturing'
                else:
                    status = 'pending'
                
                block_entry = {
                    'timestamp': b.get('ts', 0),
                    'block_height': block_height,
                    'block_hash': block_hash,
                    'block_reward': block_reward,
                    'explorer_url': block_explorer_url + block_hash if block_explorer_url else '',
                    'status': status,
                    'estimated_payout': est_payout,
                    'confirmations': confirmations,
                    'confirmations_required': COINBASE_MATURITY,
                }
                miner_blocks.append(block_entry)
                
                # Accumulate reward totals
                if est_payout > 0:
                    total_estimated_rewards += est_payout
                    if is_mature:
                        confirmed_rewards += est_payout
                    else:
                        maturing_rewards += est_payout
                
        return {
            'address': address,
            'current_payout': current_payout,
            'blocks_found': len(miner_blocks),
            'total_estimated_rewards': total_estimated_rewards,
            'confirmed_rewards': confirmed_rewards,
            'maturing_rewards': maturing_rewards,
            'blocks': miner_blocks[:10],  # Limit to 10 most recent
        }
    
    web_root.putChild('miner_payouts', WebInterface(get_miner_payouts))
    
    def get_merged_miner_payouts(address=None):
        """Get merged mining payout history for a specific miner address"""
        if not address:
            return {'error': 'No address provided'}
        
        # Current merged payout from PPLNS distribution
        current_merged_payout = 0
        merged_payout_symbol = ''
        try:
            if hasattr(wb, 'merged_work') and wb.merged_work and hasattr(wb.merged_work, 'value') and wb.merged_work.value:
                for chain_id, chain in wb.merged_work.value.iteritems():
                    shareholders = chain.get('shareholders', {})
                    template = chain.get('template', {})
                    coinbasevalue = 0
                    if template:
                        coinbasevalue = template.get('coinbasevalue', 0)
                    elif chain.get('coinbasevalue'):
                        coinbasevalue = chain['coinbasevalue']
                    
                    don_pct = chain.get('donation_percentage', 1.0)
                    node_owner_fee = chain.get('node_owner_fee', chain.get('worker_fee', 0))
                    miners_reward = coinbasevalue - int(coinbasevalue * don_pct / 100) - (int(coinbasevalue * node_owner_fee / 100) if node_owner_fee > 0 else 0)
                    
                    merged_payout_symbol = chain.get('merged_net_symbol', 'DOGE' if chain_id == 98 else 'AUX')
                    
                    for sh_addr, val in shareholders.iteritems():
                        frac = val[0] if isinstance(val, tuple) else val
                        sh_base = sh_addr.split(',')[0].split('.')[0].split('_')[0].split('+')[0].split('/')[0]
                        if sh_base == address:
                            current_merged_payout = int(miners_reward * frac) / 1e8
                            break
        except Exception:
            pass
        
        # Find merged blocks found by this miner
        miner_merged_blocks = []
        total_estimated_rewards = 0.0
        confirmed_rewards = 0.0
        maturing_rewards = 0.0
        
        # Coinbase maturity for DOGE testnet (240 blocks)
        MERGED_COINBASE_MATURITY = 240
        
        # Get current merged chain height for confirmation tracking
        merged_current_height = 0
        try:
            if hasattr(wb, 'merged_work') and wb.merged_work and hasattr(wb.merged_work, 'value') and wb.merged_work.value:
                for chain_id, chain in wb.merged_work.value.iteritems():
                    template = chain.get('template', {})
                    if template:
                        merged_current_height = template.get('height', 0)
                        break
        except Exception:
            pass
        
        # Block explorer URLs for merged chains
        merged_explorers = {
            98: {'testnet': 'https://dogechain.info/block/',
                 'mainnet': 'https://dogechain.info/block/'}
        }
        
        for b in wb.recent_merged_blocks:
            if b.get('verified') == False:
                continue  # Skip orphaned blocks
            
            block_miner = b.get('miner', '')
            block_miner_parent = b.get('miner_parent', '')
            # Strip merged DOGE address (comma) and worker suffix for matching
            if block_miner:
                block_miner = block_miner.split(',')[0].split('.')[0].split('+')[0].split('/')[0].split('_')[0]
            if block_miner_parent:
                block_miner_parent = block_miner_parent.split(',')[0].split('.')[0].split('+')[0].split('/')[0].split('_')[0]
            
            if block_miner == address or block_miner_parent == address:
                block_hash = b.get('hash', '')
                block_height = b.get('height', 0)
                sym = b.get('symbol', merged_payout_symbol or 'COIN')
                chainid = b.get('chainid', 0)
                coinbasevalue = b.get('coinbasevalue', 0)
                block_reward = coinbasevalue / 1e8 if coinbasevalue > 0 else 0
                
                # Miner's estimated payout (in satoshis, stored at block-find time)
                stored_payout = b.get('miner_payout', 0)
                if stored_payout > 0:
                    est_payout = stored_payout / 1e8
                elif current_merged_payout > 0:
                    # Fallback: use current PPLNS proportion
                    est_payout = current_merged_payout
                else:
                    est_payout = block_reward  # Assume full reward if no PPLNS data
                
                # Confirmation tracking
                confirmations = max(0, merged_current_height - block_height) if merged_current_height > 0 and block_height > 0 else 0
                is_mature = confirmations >= MERGED_COINBASE_MATURITY
                
                if b.get('verified') == True:
                    if is_mature:
                        status = 'confirmed'
                    else:
                        status = 'maturing'
                else:
                    status = 'pending'
                
                # Explorer URL
                is_testnet = b.get('is_testnet', True)
                explorer = merged_explorers.get(chainid, {})
                explorer_url = ''
                if explorer:
                    base_url = explorer.get('testnet' if is_testnet else 'mainnet', '')
                    pow_hash = b.get('pow_hash', block_hash)
                    explorer_url = base_url + pow_hash if base_url else ''
                
                block_entry = {
                    'timestamp': b.get('ts', 0),
                    'block_height': block_height,
                    'block_hash': block_hash,
                    'pow_hash': b.get('pow_hash', ''),
                    'block_reward': block_reward,
                    'explorer_url': explorer_url,
                    'status': status,
                    'estimated_payout': est_payout,
                    'confirmations': confirmations,
                    'confirmations_required': MERGED_COINBASE_MATURITY,
                    'network': b.get('network', ''),
                    'symbol': sym,
                    'chainid': chainid,
                }
                miner_merged_blocks.append(block_entry)
                
                # Accumulate reward totals
                if est_payout > 0:
                    total_estimated_rewards += est_payout
                    if status == 'confirmed':
                        confirmed_rewards += est_payout
                    elif status == 'maturing':
                        maturing_rewards += est_payout
        
        return {
            'address': address,
            'current_payout': current_merged_payout,
            'symbol': merged_payout_symbol,
            'blocks_found': len(miner_merged_blocks),
            'total_estimated_rewards': total_estimated_rewards,
            'confirmed_rewards': confirmed_rewards,
            'maturing_rewards': maturing_rewards,
            'blocks': miner_merged_blocks[:10],  # Limit to 10 most recent
        }
    
    web_root.putChild('merged_miner_payouts', WebInterface(get_merged_miner_payouts))
    
    # Block history storage - persisted to disk
    block_history = []
    block_history_path = os.path.join(datadir_path, 'block_history')
    
    # Load existing block history
    if os.path.exists(block_history_path):
        try:
            with open(block_history_path, 'rb') as f:
                block_history = json.loads(f.read())
                print('Loaded %d historical blocks from disk' % len(block_history))
        except Exception as e:
            log.err(None, 'Error loading block history:')
    
    # Set to track known block hashes (avoid duplicates)
    known_block_hashes = set(b['hash'] for b in block_history)
    
    def save_block_history():
        """Save block history to disk
        
        Block history stores all found blocks with luck/timing data.
        Dashboards handle their own display windowing (e.g., last 100 blocks).
        No artificial limit needed here - let it grow and persist all history.
        """
        try:
            # Optional: Uncomment below to limit storage if memory/disk becomes an issue
            # Note: List is sorted newest-first (descending), so pop() removes oldest
            # while len(block_history) > 1000:
            #     oldest = block_history.pop()  # Remove from END (oldest blocks)
            #     known_block_hashes.discard(oldest['hash'])
            _atomic_write(block_history_path, json.dumps(block_history))
        except Exception as e:
            log.err(None, 'Error saving block history:')
    
    def add_block_to_history(block_info):
        """Add a new block to history if not already known"""
        block_hash = block_info['hash']
        if block_hash not in known_block_hashes:
            block_history.append(block_info)
            known_block_hashes.add(block_hash)
            # Sort by timestamp descending
            block_history.sort(key=lambda x: x['ts'], reverse=True)
            return True
        return False
    
    def get_recent_blocks():
        """Get recent blocks found by the pool with luck and timing info"""
        try:
            # Get pool hashrate for luck calculations
            height = node.tracker.get_height(node.best_share_var.value)
            if height < 10:
                return block_history  # Return historical blocks if tracker not ready
            
            lookbehind = min(height, 720)
            pool_hashrate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
            
            # Find all blocks in the current tracker chain
            chain_length = min(height, node.net.CHAIN_LENGTH)
            tracker_blocks = []
            for s in node.tracker.get_chain(node.best_share_var.value, chain_length):
                if s.pow_hash <= s.header['bits'].target:
                    tracker_blocks.append(s)
            
            # Build block info for each block in tracker
            new_blocks_added = False
            for i, s in enumerate(tracker_blocks):
                block_hash = '%064x' % s.header_hash
                
                # Skip if already in history
                if block_hash in known_block_hashes:
                    # Update verification status and fill in missing fields
                    # (immediate-path blocks start with pending status and no share/miner data)
                    for b in block_history:
                        if b['hash'] == block_hash:
                            is_verified = s.hash in node.tracker.verified.items
                            b['verified'] = is_verified
                            b['status'] = 'confirmed' if is_verified else 'pending'
                            # Fill in data that wasn't available at immediate-recording time
                            if not b.get('share') or b['share'] == '':
                                b['share'] = '%064x' % s.hash
                            if not b.get('number') or b['number'] == 0:
                                try:
                                    b['number'] = p2pool_data.parse_bip0034(s.share_data['coinbase'])[0]
                                except:
                                    pass
                            if not b.get('share_difficulty') or b['share_difficulty'] == 0:
                                b['share_difficulty'] = bitcoin_data.target_to_difficulty(s.target)
                            if not b.get('miner') or b['miner'] == '':
                                try:
                                    b['miner'] = bitcoin_data.script2_to_address(
                                        s.new_script, node.net.PARENT.ADDRESS_VERSION, -1, node.net.PARENT)
                                except Exception as e:
                                    try:
                                        b['miner'] = bitcoin_data.script2_to_address(
                                            s.new_script, -1, 0, node.net.PARENT)  # bech32 v0
                                    except Exception as e2:
                                        try:
                                            b['miner'] = bitcoin_data.script2_to_address(
                                                s.new_script, node.net.PARENT.ADDRESS_P2SH_VERSION, -1, node.net.PARENT)  # P2SH
                                        except Exception as e3:
                                            print('Failed to extract miner address: %s / %s / %s' % (e, e2, e3))
                            # Fill in subsidy and miner_payout if missing
                            if not b.get('subsidy'):
                                try:
                                    b['subsidy'] = node.bitcoind_work.value['subsidy']
                                except:
                                    pass
                            if not b.get('miner_payout') and b.get('miner'):
                                try:
                                    current_txouts = node.get_current_txouts()
                                    miner_addr = b['miner'].split(',')[0].split('.')[0].split('_')[0]
                                    b['miner_payout'] = current_txouts.get(miner_addr, 0)
                                except:
                                    pass
                            break
                    continue
                
                is_verified = s.hash in node.tracker.verified.items
                # Extract miner address from share's payout script
                miner_addr = ''
                try:
                    miner_addr = bitcoin_data.script2_to_address(
                        s.new_script, node.net.PARENT.ADDRESS_VERSION, -1, node.net.PARENT)
                except Exception:
                    try:
                        miner_addr = bitcoin_data.script2_to_address(
                            s.new_script, -1, 0, node.net.PARENT)  # bech32 v0
                    except Exception:
                        try:
                            miner_addr = bitcoin_data.script2_to_address(
                                s.new_script, node.net.PARENT.ADDRESS_P2SH_VERSION, -1, node.net.PARENT)  # P2SH
                        except Exception as e:
                            print('Failed to extract miner from share %s: %s' % ('%064x' % s.hash, e))
                block_info = {
                    'ts': s.timestamp,
                    'hash': block_hash,
                    'number': p2pool_data.parse_bip0034(s.share_data['coinbase'])[0],
                    'share': '%064x' % s.hash,
                    'miner': miner_addr,
                    'network_difficulty': bitcoin_data.target_to_difficulty(s.header['bits'].target),
                    'share_difficulty': bitcoin_data.target_to_difficulty(s.target),
                    'actual_hash_difficulty': bitcoin_data.target_to_difficulty(s.pow_hash),
                    'verified': is_verified,
                    'status': 'confirmed' if is_verified else 'pending',
                    'pool_hashrate_at_find': pool_hashrate,
                    'subsidy': node.bitcoind_work.value.get('subsidy', 0),
                }
                # Get miner's payout from current txouts
                try:
                    current_txouts = node.get_current_txouts()
                    base_addr = miner_addr.split(',')[0].split('.')[0].split('_')[0]
                    block_info['miner_payout'] = current_txouts.get(base_addr, 0)
                except:
                    block_info['miner_payout'] = 0
                
                # Calculate expected time based on difficulty and pool hashrate
                if pool_hashrate > 0:
                    expected_hashes = bitcoin_data.target_to_average_attempts(s.header['bits'].target)
                    expected_time = expected_hashes / pool_hashrate
                    block_info['expected_time'] = expected_time
                
                # Calculate time_to_find based on previous block
                if i + 1 < len(tracker_blocks):
                    prev_block = tracker_blocks[i + 1]
                    time_to_find = s.timestamp - prev_block.timestamp
                    block_info['time_to_find'] = time_to_find
                    
                    if pool_hashrate > 0 and expected_time > 0 and time_to_find > 0:
                        luck = (expected_time / time_to_find) * 100
                        block_info['luck'] = luck
                        block_info['luck_method'] = 'simple_avg'
                else:
                    block_info['luck_method'] = 'first_block'
                
                if add_block_to_history(block_info):
                    new_blocks_added = True
                    print('Added new block to history: height=%s hash=%s diff=%.8f' % (block_info['number'], block_hash[:16], block_info['network_difficulty']))
                    # Also record network difficulty sample with this block
                    # (add_network_diff_sample is defined later but will exist when this runs)
                    try:
                        add_network_diff_sample(block_info['ts'], block_info['network_difficulty'], 'block')
                    except:
                        pass  # Ignore if not yet defined during startup
            
            # Save to disk if new blocks were added
            if new_blocks_added:
                save_block_history()
                try:
                    save_network_diff_history()
                except:
                    pass  # Ignore if not yet defined during startup
            
            # RPC fallback verification for blocks still pending after tracker scan.
            # When p2pool restarts, shares may be evicted from the tracker but the
            # blocks they produced are still valid on the parent chain.
            # Fire-and-forget async verification for any stale pending blocks.
            now = time.time()
            for b in block_history:
                if b.get('status') == 'pending' and (now - b.get('ts', 0)) > 30:
                    def verify_via_rpc(block_rec):
                        def on_result(block_data):
                            if block_data and isinstance(block_data, dict):
                                confs = block_data.get('confirmations', 0)
                                block_height = block_data.get('height', 0)
                                changed = False
                                if confs > 0:
                                    block_rec['verified'] = True
                                    block_rec['status'] = 'confirmed'
                                    if block_height > 0 and (not block_rec.get('number') or block_rec['number'] == 0):
                                        block_rec['number'] = block_height
                                    changed = True
                                elif confs < 0:
                                    block_rec['verified'] = False
                                    block_rec['status'] = 'orphaned'
                                    changed = True
                                if changed:
                                    save_block_history()
                        def on_error(err):
                            pass  # Block not found or RPC error - leave as pending
                        try:
                            d = node.bitcoind.rpc_getblock(block_rec['hash'])
                            d.addCallback(on_result)
                            d.addErrback(on_error)
                        except:
                            pass
                    verify_via_rpc(b)
            
            # Calculate pool average luck from all blocks with luck data
            total_luck = 0
            luck_count = 0
            for b in block_history:
                if b.get('luck'):
                    total_luck += b['luck']
                    luck_count += 1
            
            # Return a copy with pool_avg_luck added
            result = list(block_history)  # block_history is sorted newest-first
            if result and luck_count > 0:
                result[0] = dict(result[0])
                result[0]['pool_avg_luck'] = total_luck / luck_count
            
            return result
        except Exception as e:
            import traceback
            traceback.print_exc()
            return block_history  # Return what we have on error
    
    web_root.putChild('recent_blocks', WebInterface(get_recent_blocks))
    
    # =========================================================================
    # Immediate block recording when a block is found
    # This ensures blocks are saved to disk right away, not just when API is queried
    # =========================================================================
    def on_block_found(block_info):
        """Called immediately when a parent network block is found.
        
        Records the block to history and network difficulty immediately,
        ensuring no data is lost if dashboard isn't being watched.
        """
        try:
            # Get pool hashrate for luck calculations
            height = node.tracker.get_height(node.best_share_var.value)
            pool_hashrate = 0
            if height >= 10:
                lookbehind = min(height, 720)
                pool_hashrate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
            
            # Build full block info with luck data
            full_block_info = {
                'ts': block_info['ts'],
                'hash': block_info['hash'],  # SHA256d hash (matches tracker's s.header_hash)
                'pow_hash_hex': block_info.get('pow_hash_hex', ''),  # Scrypt/PoW hash for display
                'number': block_info['number'],
                'miner': block_info.get('miner', ''),  # Miner address who found the block
                'share': '',  # Will be filled in when tracker catches up
                'network_difficulty': block_info['network_difficulty'],
                'share_difficulty': 0,  # Will be filled in when tracker catches up  
                'actual_hash_difficulty': bitcoin_data.target_to_difficulty(block_info['pow_hash']),
                'verified': False,
                'status': 'pending',
                'pool_hashrate_at_find': pool_hashrate,
                'subsidy': block_info.get('subsidy', 0),
                'miner_payout': block_info.get('miner_payout', 0),
            }
            
            # Calculate expected time and luck
            if pool_hashrate > 0:
                expected_hashes = bitcoin_data.target_to_average_attempts(block_info['target'])
                expected_time = expected_hashes / pool_hashrate
                full_block_info['expected_time'] = expected_time
                
                # Calculate time_to_find based on previous block in history
                if block_history:
                    prev_block = block_history[0]  # Most recent block (sorted descending)
                    time_to_find = block_info['ts'] - prev_block['ts']
                    full_block_info['time_to_find'] = time_to_find
                    
                    if expected_time > 0 and time_to_find > 0:
                        luck = (expected_time / time_to_find) * 100
                        full_block_info['luck'] = luck
                        full_block_info['luck_method'] = 'immediate'
            
            # Add to history and save immediately
            if add_block_to_history(full_block_info):
                print('IMMEDIATE: Added block to history: height=%s hash=%s diff=%.8f' % (
                    block_info['number'], block_info['hash'][:16], block_info['network_difficulty']))
                save_block_history()
                
                # Also record network difficulty sample with this block
                add_network_diff_sample(block_info['ts'], block_info['network_difficulty'], 'block')
                save_network_diff_history()
        except Exception as e:
            import traceback
            print('Error in on_block_found callback:')
            traceback.print_exc()
    
    # Note: wb.block_found.watch(on_block_found) is registered later after
    # add_network_diff_sample and save_network_diff_history are defined
    
    # Debug endpoint to check tracker status
    def get_tracker_debug():
        """Debug endpoint to inspect tracker shares and their difficulty comparison"""
        try:
            height = node.tracker.get_height(node.best_share_var.value)
            chain_length = min(height, node.net.CHAIN_LENGTH) if height > 0 else 0
            
            # Sample first 10 shares
            shares_debug = []
            block_candidates = 0
            total_checked = 0
            for s in node.tracker.get_chain(node.best_share_var.value, chain_length):
                total_checked += 1
                pow_hash = s.pow_hash
                network_target = s.header['bits'].target
                is_block = pow_hash <= network_target
                if is_block:
                    block_candidates += 1
                if total_checked <= 10:
                    shares_debug.append({
                        'share_hash': '%064x' % s.hash,
                        'pow_hash': '%064x' % pow_hash,
                        'network_target': '%064x' % network_target,
                        'share_target': '%064x' % s.target,
                        'is_block': is_block,
                        'ts': s.timestamp,
                        'header_hash': '%064x' % s.header_hash,
                    })
            
            return {
                'tracker_height': height,
                'chain_length_checked': total_checked,
                'block_candidates_found': block_candidates,
                'sample_shares': shares_debug,
                'known_block_hashes_count': len(known_block_hashes),
                'block_history_count': len(block_history),
                'best_share_var': '%064x' % node.best_share_var.value if node.best_share_var.value else None,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'error': str(e)}
    
    web_root.putChild('tracker_debug', WebInterface(get_tracker_debug))
    
    # Merged block history storage - persisted to disk
    merged_block_history_path = os.path.join(datadir_path, 'merged_block_history')
    merged_known_hashes = set()
    
    # Load existing merged block history
    if os.path.exists(merged_block_history_path):
        try:
            with open(merged_block_history_path, 'rb') as f:
                loaded_merged = json.loads(f.read())
                # Merge with any existing blocks in wb.recent_merged_blocks
                for b in loaded_merged:
                    if b.get('hash') not in merged_known_hashes:
                        wb.recent_merged_blocks.append(b)
                        merged_known_hashes.add(b.get('hash'))
                print('Loaded %d historical merged blocks from disk' % len(loaded_merged))
        except Exception as e:
            log.err(None, 'Error loading merged block history:')
    
    # Initialize known hashes from any existing blocks
    for b in wb.recent_merged_blocks:
        if b.get('hash'):
            merged_known_hashes.add(b.get('hash'))
    
    def save_merged_block_history():
        """Save merged block history to disk"""
        try:
            # Keep last 500 merged blocks
            while len(wb.recent_merged_blocks) > 500:
                oldest = wb.recent_merged_blocks.pop(0)
                merged_known_hashes.discard(oldest.get('hash'))
            _atomic_write(merged_block_history_path, json.dumps(wb.recent_merged_blocks))
        except Exception as e:
            log.err(None, 'Error saving merged block history:')
    
    # Periodically save merged blocks
    x_merged = deferral.RobustLoopingCall(save_merged_block_history)
    x_merged.start(60)  # Save every 60 seconds
    stop_event.watch(x_merged.stop)
    
    # Merged mined blocks endpoint - show verified and pending blocks (not orphaned)
    web_root.putChild('recent_merged_blocks', WebInterface(lambda: [b for b in wb.recent_merged_blocks[::-1] if b.get('verified') != False]))
    
    # All merged blocks endpoint - for debugging (includes orphaned and pending)
    web_root.putChild('all_merged_blocks', WebInterface(lambda: wb.recent_merged_blocks[::-1]))
    
    # Merged mining stats endpoint
    def get_merged_stats():
        """Get merged mining statistics"""
        blocks = wb.recent_merged_blocks
        
        # Get current merged block value from createauxblock coinbasevalue (includes fees)
        merged_block_value = 0
        merged_symbol = ''
        try:
            if hasattr(wb, 'merged_work') and wb.merged_work and hasattr(wb.merged_work, 'value') and wb.merged_work.value:
                for chain_id, chain in wb.merged_work.value.iteritems():
                    # Determine symbol: check merged_net_symbol, symbol, or derive from chain_id
                    if chain_id == 98:
                        merged_symbol = chain.get('merged_net_symbol', 'DOGE')
                    else:
                        merged_symbol = chain.get('merged_net_symbol', chain.get('symbol', 'AUX'))
                    
                    # Use coinbasevalue from createauxblock (includes subsidy + fees)
                    if 'coinbasevalue' in chain and chain['coinbasevalue'] > 0:
                        merged_block_value = chain['coinbasevalue'] / 1e8
                        break
                    # Fallback: try template (getblocktemplate path)
                    elif 'template' in chain and chain['template']:
                        template = chain['template']
                        merged_block_value = template.get('coinbasevalue', 0) / 1e8
                        break
        except Exception as e:
            print "[MERGED STATS] Error getting merged work: %s" % e
        
        if not blocks:
            return {
                'total_blocks': 0,
                'verified_blocks': 0,
                'pending_blocks': 0,
                'orphaned_blocks': 0,
                'networks': {},
                'block_value': merged_block_value,
                'symbol': merged_symbol,
            }
        
        verified = len([b for b in blocks if b.get('verified') == True])
        pending = len([b for b in blocks if b.get('verified') is None])
        orphaned = len([b for b in blocks if b.get('verified') == False])
        
        # Group by network
        networks = {}
        for b in blocks:
            net = b.get('network', 'Unknown')
            if net not in networks:
                networks[net] = {'total': 0, 'verified': 0, 'pending': 0, 'orphaned': 0, 'symbol': b.get('symbol', '?')}
            networks[net]['total'] += 1
            if b.get('verified') == True:
                networks[net]['verified'] += 1
            elif b.get('verified') is None:
                networks[net]['pending'] += 1
            else:
                networks[net]['orphaned'] += 1
        
        return {
            'total_blocks': len(blocks),
            'verified_blocks': verified,
            'pending_blocks': pending,
            'orphaned_blocks': orphaned,
            'networks': networks,
            'recent': [b for b in blocks[-10:][::-1]],  # Last 10 blocks
            'block_value': merged_block_value,
            'symbol': merged_symbol,
        }
    
    web_root.putChild('merged_stats', WebInterface(get_merged_stats))
    
    # Network difficulty history storage - persisted to disk
    network_diff_history = []
    network_diff_history_path = os.path.join(datadir_path, 'network_difficulty_history')
    known_diff_timestamps = set()
    
    # Load existing network difficulty history
    if os.path.exists(network_diff_history_path):
        try:
            with open(network_diff_history_path, 'rb') as f:
                network_diff_history = json.loads(f.read())
                known_diff_timestamps = set(int(d['ts']) for d in network_diff_history)
                print('Loaded %d network difficulty samples from disk' % len(network_diff_history))
        except Exception as e:
            log.err(None, 'Error loading network difficulty history:')
    
    # Seed network difficulty history from block history (if not already loaded)
    seeded_from_blocks = 0
    for b in block_history:
        if b.get('ts') and b.get('network_difficulty'):
            ts_key = int(b['ts'])
            if ts_key not in known_diff_timestamps:
                network_diff_history.append({
                    'ts': b['ts'],
                    'network_diff': b['network_difficulty'],
                    'source': 'block'
                })
                known_diff_timestamps.add(ts_key)
                seeded_from_blocks += 1
    if seeded_from_blocks > 0:
        network_diff_history.sort(key=lambda x: x['ts'])
        print('Seeded %d network difficulty samples from block history' % seeded_from_blocks)
    
    def save_network_diff_history():
        """Save network difficulty history to disk"""
        try:
            # Keep last 2000 samples (covers weeks of data at block-rate sampling)
            while len(network_diff_history) > 2000:
                oldest = network_diff_history.pop(0)
                known_diff_timestamps.discard(int(oldest['ts']))
            _atomic_write(network_diff_history_path, json.dumps(network_diff_history))
        except Exception as e:
            log.err(None, 'Error saving network difficulty history:')
    
    def add_network_diff_sample(timestamp, network_diff, source='block'):
        """Add a network difficulty sample if not already recorded for this timestamp"""
        ts_key = int(timestamp)
        if ts_key not in known_diff_timestamps:
            network_diff_history.append({
                'ts': timestamp,
                'network_diff': network_diff,
                'source': source  # 'block' or 'periodic'
            })
            known_diff_timestamps.add(ts_key)
            # Sort by timestamp ascending
            network_diff_history.sort(key=lambda x: x['ts'])
            return True
        return False
    
    # Periodically save network difficulty history
    x_netdiff = deferral.RobustLoopingCall(save_network_diff_history)
    x_netdiff.start(120)  # Save every 2 minutes
    stop_event.watch(x_netdiff.stop)
    
    # Also sample current network difficulty periodically (every 5 minutes)
    def sample_current_network_diff():
        try:
            if wb.current_work.value and 'bits' in wb.current_work.value:
                diff = bitcoin_data.target_to_difficulty(wb.current_work.value['bits'].target)
                current_time = time.time()
                if add_network_diff_sample(current_time, diff, 'periodic'):
                    print('Recorded periodic network difficulty sample: %.8f' % diff)
        except Exception as e:
            pass
    
    x_sample_diff = deferral.RobustLoopingCall(sample_current_network_diff)
    x_sample_diff.start(300)  # Sample every 5 minutes
    stop_event.watch(x_sample_diff.stop)
    
    # =========================================================================
    # Register the block_found callback now that all helper functions are defined
    # This ensures blocks AND network difficulty are saved immediately when found
    # =========================================================================
    wb.block_found.watch(on_block_found)
    print('Registered block_found callback for immediate block history persistence')
    
    # Network difficulty endpoint for graph - returns historical network difficulty
    class NetworkDifficultyResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            try:
                # Parse period parameter
                period = request.args.get('period', ['hour'])[0]
                now = time.time()
                
                # Determine time cutoff based on period
                if period == 'hour':
                    cutoff = now - 3600
                elif period == 'day':
                    cutoff = now - 86400
                elif period == 'week':
                    cutoff = now - 604800
                elif period == 'month':
                    cutoff = now - 2592000
                elif period == 'year':
                    cutoff = now - 31536000
                else:
                    cutoff = now - 3600  # Default to hour
                
                # Get samples within the time range
                samples = [d for d in network_diff_history if d['ts'] >= cutoff]
                
                # Also add current network difficulty
                if wb.current_work.value and 'bits' in wb.current_work.value:
                    diff = bitcoin_data.target_to_difficulty(wb.current_work.value['bits'].target)
                    samples.append({'ts': now, 'network_diff': diff, 'source': 'current'})
                
                # Sort by timestamp and return
                samples.sort(key=lambda x: x['ts'])
                return json.dumps(samples)
            except Exception as e:
                return json.dumps([])
    
    web_root.putChild('network_difficulty', NetworkDifficultyResource())
    
    # Node info endpoint for miner configuration display
    # Cache external IP to avoid blocking the reactor with synchronous HTTP requests
    _cached_external_ip = [None]  # mutable container for closure
    
    def _detect_local_ip():
        """Get local network IP (non-blocking, no DNS)"""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    _external_ip_resolved = [False]  # True once we have a real external IP
    
    @defer.inlineCallbacks
    def _resolve_external_ip():
        """Resolve external IP asynchronously using Twisted, cache the result"""
        if _external_ip_resolved[0]:
            return
        
        # If --external-ip was provided, use it directly and skip auto-detection
        configured_ip = getattr(node, 'external_ip', None)
        if configured_ip:
            ip = str(configured_ip)
            if ':' in ip:
                ip = ip.rsplit(':', 1)[0]
            _cached_external_ip[0] = ip
            _external_ip_resolved[0] = True
            print 'Using configured external IP: %s' % ip
            return
        
        # Set local IP as immediate fallback so dashboard never blocks
        if _cached_external_ip[0] is None:
            _cached_external_ip[0] = _detect_local_ip()
        
        # Try external services asynchronously (non-blocking)
        # Use HTTP (not HTTPS) because PyPy 2.7's cryptography/OpenSSL binding
        # is broken (undefined symbol: FIPS_mode) making TLS connections fail.
        # For IP detection, HTTPS isn't security-critical — we're just reading
        # our own public IP address, not transmitting secrets.
        for url in ['http://api.ipify.org', 'http://icanhazip.com', 'http://ifconfig.me/ip', 'http://checkip.amazonaws.com']:
            try:
                from twisted.web.client import getPage
                body = yield getPage(url.encode('ascii'), timeout=5, headers={b'User-Agent': b'p2pool'})
                ip = body.strip()
                if ip and len(ip) < 50 and ip != _detect_local_ip():
                    _cached_external_ip[0] = ip
                    _external_ip_resolved[0] = True
                    print 'Detected external IP: %s' % ip
                    break
            except:
                continue
        
        # If we still don't have external IP, retry in 30 seconds
        if not _external_ip_resolved[0]:
            print 'External IP detection failed, will retry in 30s (using %s for now)' % _cached_external_ip[0]
            reactor.callLater(30, _resolve_external_ip)
    
    # Fire and forget — resolve in background, don't block startup
    reactor.callLater(1, _resolve_external_ip)
    
    def get_node_info():
        """Get node connection info for miners (non-blocking, uses cached IP)"""
        try:
            external_ip = getattr(node, 'external_ip', None) or _cached_external_ip[0] or _detect_local_ip()
            # --external-ip accepts ADDR[:PORT], strip port if present
            if external_ip and ':' in str(external_ip):
                external_ip = str(external_ip).rsplit(':', 1)[0]
            
            return {
                'external_ip': external_ip,
                'worker_port': node.net.WORKER_PORT,
                'p2p_port': node.net.P2P_PORT,
                'network': node.net.NAME,
                'symbol': node.net.PARENT.SYMBOL,
            }
        except Exception as e:
            return {'error': str(e)}
    
    web_root.putChild('node_info', WebInterface(get_node_info))
    
    # Luck statistics endpoint
    def get_luck_stats():
        """Get pool luck statistics"""
        try:
            # Get recent blocks from tracker
            height = node.tracker.get_height(node.best_share_var.value)
            if height < 10:
                return {'luck_available': False, 'blocks': [], 'current_luck_trend': None}
            
            lookbehind = min(height, 720)
            
            # Calculate current round luck
            # Shares since last block / expected shares
            pool_hashrate = p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)
            if pool_hashrate > 0:
                expected_time = bitcoin_data.target_to_average_attempts(node.bitcoind_work.value['bits'].target) / pool_hashrate
                # Get time since last block found
                blocks_found = [s for s in node.tracker.get_chain(node.best_share_var.value, lookbehind) if s.pow_hash <= s.header['bits'].target]
                if blocks_found:
                    time_since_last = time.time() - blocks_found[0].timestamp
                    current_luck = (expected_time / max(time_since_last, 1)) * 100
                else:
                    current_luck = None
            else:
                current_luck = None
            
            # Build blocks list with luck values
            blocks = []
            for s in node.tracker.get_chain(node.best_share_var.value, lookbehind):
                if s.pow_hash <= s.header['bits'].target:
                    blocks.append({
                        'ts': s.timestamp,
                        'hash': '%064x' % s.header_hash,
                        'luck': 100,  # Placeholder - would need actual calculation
                    })
            
            return {
                'luck_available': True,
                'current_luck_trend': current_luck,
                'blocks': blocks[:20],  # Last 20 blocks
            }
        except Exception as e:
            return {'luck_available': False, 'error': str(e), 'blocks': []}
    
    web_root.putChild('luck_stats', WebInterface(get_luck_stats))
    
    # Peer list endpoint with detailed info
    def get_peer_list():
        """Get list of connected P2Pool peers with details"""
        try:
            peers = []
            for peer in node.p2p_node.peers.itervalues():
                try:
                    addr = peer.transport.getPeer()
                    peers.append({
                        'address': '%s:%s' % (addr.host, addr.port),
                        'web_port': getattr(node.net, 'WORKER_PORT', addr.port),
                        'version': getattr(peer, 'other_sub_version', None),
                        'incoming': getattr(peer, 'incoming', False),
                        'uptime': time.time() - getattr(peer, 'connected_at', time.time()) if hasattr(peer, 'connected_at') else 0,
                        'downtime': 0,
                        'txpool_size': getattr(peer, 'remembered_txs_size', 0),
                    })
                except:
                    pass
            return peers
        except Exception as e:
            return []
    
    web_root.putChild('peer_list', WebInterface(get_peer_list))
    
    # Add broadcaster network status endpoint (parent chain)
    from p2pool.bitcoin import helper as bitcoin_helper
    web_root.putChild('broadcaster_status', WebInterface(lambda: bitcoin_helper.get_broadcaster_status()))
    
    # Add merged broadcaster status endpoint (child chains like Dogecoin)
    def get_merged_broadcaster_status():
        """Get status of all merged mining broadcasters"""
        result = {'chains': {}}
        has_attr = hasattr(node, 'merged_broadcasters')
        broadcasters_dict = getattr(node, 'merged_broadcasters', None)
        if broadcasters_dict:
            for chain_id, broadcaster in broadcasters_dict.items():
                try:
                    # Use get_network_status for full peer list (same format as Litecoin broadcaster)
                    result['chains'][str(chain_id)] = broadcaster.get_network_status()
                except Exception as e:
                    result['chains'][str(chain_id)] = {'error': str(e)}
        if not result['chains']:
            result['message'] = 'No merged mining broadcasters active'
            result['debug'] = {
                'has_attr': has_attr,
                'broadcasters_type': str(type(broadcasters_dict)),
                'broadcasters_len': len(broadcasters_dict) if broadcasters_dict else 0,
                'broadcasters_keys': list(broadcasters_dict.keys()) if broadcasters_dict else [],
            }
        return result
    
    web_root.putChild('merged_broadcaster_status', WebInterface(get_merged_broadcaster_status))

    web_root.putChild('uptime', WebInterface(lambda: time.time() - start_time))
    web_root.putChild('stale_rates', WebInterface(lambda: p2pool_data.get_stale_counts(node.tracker, node.best_share_var.value, decent_height(), rates=True)))
    
    new_root = resource.Resource()
    web_root.putChild('web', new_root)
    
    stat_log = []
    if os.path.exists(os.path.join(datadir_path, 'stats')):
        try:
            with open(os.path.join(datadir_path, 'stats'), 'rb') as f:
                stat_log = json.loads(f.read())
        except:
            log.err(None, 'Error loading stats:')
    def update_stat_log():
        while stat_log and stat_log[0]['time'] < time.time() - 24*60*60:
            stat_log.pop(0)
        
        lookbehind = 3600//node.net.SHARE_PERIOD
        if node.tracker.get_height(node.best_share_var.value) < lookbehind:
            return None
        
        global_stale_prop = p2pool_data.get_average_stale_prop(node.tracker, node.best_share_var.value, lookbehind)
        (stale_orphan_shares, stale_doa_shares), shares, _ = wb.get_stale_counts()
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        
        my_current_payout=0.0
        for add in wb.pubkeys.keys:
            my_current_payout += node.get_current_txouts().get(
                    add['address'], 0)*1e-8
        stat_log.append(dict(
            time=time.time(),
            pool_hash_rate=p2pool_data.get_pool_attempts_per_second(node.tracker, node.best_share_var.value, lookbehind)/(1-global_stale_prop),
            pool_stale_prop=global_stale_prop,
            local_hash_rates=miner_hash_rates,
            local_dead_hash_rates=miner_dead_hash_rates,
            shares=shares,
            stale_shares=stale_orphan_shares + stale_doa_shares,
            stale_shares_breakdown=dict(orphan=stale_orphan_shares, doa=stale_doa_shares),
            current_payout=my_current_payout,
            peers=dict(
                incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
                outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
            ),
            attempts_to_share=bitcoin_data.target_to_average_attempts(node.tracker.items[node.best_share_var.value].max_target),
            attempts_to_block=bitcoin_data.target_to_average_attempts(node.bitcoind_work.value['bits'].target),
            block_value=node.bitcoind_work.value['subsidy']*1e-8,
        ))
        
        with open(os.path.join(datadir_path, 'stats'), 'wb') as f:
            f.write(json.dumps(stat_log))
    x = deferral.RobustLoopingCall(update_stat_log)
    x.start(5*60)
    stop_event.watch(x.stop)
    new_root.putChild('log', WebInterface(lambda: stat_log))
    
    def get_share(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return None
        share = node.tracker.items[int(share_hash_str, 16)]
        
        result = dict(
            parent='%064x' % share.previous_hash if share.previous_hash else "None",
            far_parent='%064x' % share.share_info['far_share_hash'] if share.share_info['far_share_hash'] else "None",
            children=['%064x' % x for x in sorted(node.tracker.reverse.get(share.hash, set()), key=lambda sh: -len(node.tracker.reverse.get(sh, set())))], # sorted from most children to least children
            type_name=type(share).__name__,
            local=dict(
                verified=share.hash in node.tracker.verified.items,
                time_first_seen=start_time if share.time_seen == 0 else share.time_seen,
                peer_first_received_from=share.peer_addr,
            ),
            share_data=dict(
                timestamp=share.timestamp,
                target=share.target,
                max_target=share.max_target,
                payout_address=share.address if share.address else
                                bitcoin_data.script2_to_address(
                                    share.new_script,
                                    node.net.PARENT.ADDRESS_VERSION,
                                    node.net.PARENT),
                donation=share.share_data['donation']/65535,
                stale_info=share.share_data['stale_info'],
                nonce=share.share_data['nonce'],
                desired_version=share.share_data['desired_version'],
                absheight=share.absheight,
                abswork=share.abswork,
            ),
            block=dict(
                hash='%064x' % share.header_hash,
                header=dict(
                    version=share.header['version'],
                    previous_block='%064x' % share.header['previous_block'],
                    merkle_root='%064x' % share.header['merkle_root'],
                    timestamp=share.header['timestamp'],
                    target=share.header['bits'].target,
                    nonce=share.header['nonce'],
                ),
                gentx=dict(
                    hash='%064x' % share.gentx_hash,
                    raw=bitcoin_data.tx_id_type.pack(share.gentx).encode('hex') if hasattr(share, 'gentx') else "unknown",
                    coinbase=share.share_data['coinbase'].ljust(2, '\x00').encode('hex'),
                    value=share.share_data['subsidy']*1e-8,
                    last_txout_nonce='%016x' % share.contents['last_txout_nonce'],
                ),
                other_transaction_hashes=['%064x' % x for x in share.get_other_tx_hashes(node.tracker)],
            ),
        )
        
        # Add V36 metadata if available
        if share.VERSION >= 36:
            v36_meta = {}
            
            # merged_addresses: per-chain payment scripts provided by miner via stratum
            merged_addrs = getattr(share, 'merged_addresses', None)
            if merged_addrs:
                v36_meta['merged_addresses'] = []
                for entry in merged_addrs:
                    addr_info = {'chain_id': entry['chain_id'], 'script_hex': entry['script'].encode('hex')}
                    # Try to resolve to human-readable address
                    try:
                        chain_id = entry['chain_id']
                        if chain_id == 98:  # Dogecoin
                            try:
                                from p2pool.bitcoin.networks import dogecoin_testnet4alpha as dtn4a
                                addr_info['address'] = bitcoin_data.script2_to_address(entry['script'], dtn4a.ADDRESS_VERSION, dtn4a)
                            except Exception:
                                try:
                                    from p2pool.bitcoin.networks import dogecoin_testnet as dtn
                                    addr_info['address'] = bitcoin_data.script2_to_address(entry['script'], dtn.ADDRESS_VERSION, dtn)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    v36_meta['merged_addresses'].append(addr_info)
            else:
                v36_meta['merged_addresses'] = None  # auto-conversion fallback
            
            # merged_payout_hash: consensus commitment for PPLNS distribution
            mph = share.share_info.get('merged_payout_hash', None)
            v36_meta['merged_payout_hash'] = '%064x' % mph if mph else None
            
            # message_data: share messaging payload
            msg_data = getattr(share, '_message_data', None)
            if msg_data:
                v36_meta['message_data_hex'] = msg_data.encode('hex')
                v36_meta['message_data_size'] = len(msg_data)
                # Try to parse message types
                try:
                    from p2pool.share_messages import unpack_share_messages
                    parsed = unpack_share_messages(msg_data)
                    v36_meta['messages'] = [{'type': m.msg_type, 'flags': m.flags} for m in parsed]
                except Exception:
                    v36_meta['messages'] = None
            else:
                v36_meta['message_data_hex'] = None
                v36_meta['message_data_size'] = 0
                v36_meta['messages'] = None
            
            result['v36_metadata'] = v36_meta
        
        result['version'] = share.VERSION
        return result

    def get_share_address(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return None
        share = node.tracker.items[int(share_hash_str, 16)]
        try:
            return share.address
        except AttributeError:
            return bitcoin_data.script2_to_address(share.new_script,
                                                   node.net.ADDRESS_VERSION, -1,
                                                   node.net.PARENT)

    new_root.putChild('payout_address', WebInterface(lambda share_hash_str: get_share_address(share_hash_str)))
    new_root.putChild('share', WebInterface(lambda share_hash_str: get_share(share_hash_str)))
    
    def get_v36_status():
        """Diagnostic endpoint for V36 share metadata, AutoRatchet state, and merged address tracking."""
        status = {}
        
        # AutoRatchet state
        ratchet = getattr(wb, 'auto_ratchet', None)
        if ratchet:
            status['auto_ratchet'] = {
                'state': ratchet.state,
                'activated_at': ratchet._activated_at,
                'activated_height': ratchet._activated_height,
                'confirmed_at': ratchet._confirmed_at,
            }
        else:
            status['auto_ratchet'] = None
        
        # Share version stats from recent chain
        best = node.best_share_var.value
        if best is not None:
            height = node.tracker.get_height(best)
            sample = min(height, node.net.REAL_CHAIN_LENGTH)
            v35_count = 0
            v36_count = 0
            v36_with_merged_addr = 0
            v36_with_message = 0
            v36_with_payout_hash = 0
            
            for share in node.tracker.get_chain(best, sample):
                if share.VERSION >= 36:
                    v36_count += 1
                    if getattr(share, 'merged_addresses', None):
                        v36_with_merged_addr += 1
                    if getattr(share, '_message_data', None):
                        v36_with_message += 1
                    if share.share_info.get('merged_payout_hash', None):
                        v36_with_payout_hash += 1
                else:
                    v35_count += 1
            
            status['share_chain'] = {
                'height': height,
                'sample_size': sample,
                'v35_shares': v35_count,
                'v36_shares': v36_count,
                'v36_with_explicit_merged_addr': v36_with_merged_addr,
                'v36_with_message_data': v36_with_message,
                'v36_with_payout_hash': v36_with_payout_hash,
                'v36_percentage': round(v36_count * 100.0 / sample, 2) if sample > 0 else 0,
            }
        else:
            status['share_chain'] = None
        
        # Current merged mining info
        current_merged = getattr(wb, '_current_merged_addresses', {})
        if current_merged:
            status['current_miner_merged_addresses'] = {
                'dogecoin': current_merged.get('dogecoin', None),
                'has_validated': current_merged.get('_validated') is not None,
            }
        else:
            status['current_miner_merged_addresses'] = None
        
        # Merged PPLNS weights summary  
        if best is not None and hasattr(wb, 'merged_work') and wb.merged_work.value:
            for chain_id in wb.merged_work.value:
                try:
                    share_height = node.tracker.get_height(best)
                    parent_block_target = node.bitcoind_work.value['bits'].target
                    weights, total_weight, donation_weight = p2pool_data.get_v36_merged_weights(
                        node.tracker, best,
                        max(0, min(share_height, node.net.REAL_CHAIN_LENGTH)),
                        65535 * node.net.SPREAD * bitcoin_data.target_to_average_attempts(parent_block_target),
                        chain_id)
                    explicit_count = sum(1 for k in weights if k.startswith('MERGED:'))
                    fallback_count = sum(1 for k in weights if not k.startswith('MERGED:'))
                    status['merged_pplns_chain_%d' % chain_id] = {
                        'total_miners': len(weights),
                        'explicit_merged_addr_miners': explicit_count,
                        'auto_convert_miners': fallback_count,
                        'total_weight': total_weight,
                        'donation_weight': donation_weight,
                    }
                except Exception as e:
                    status['merged_pplns_chain_%d' % chain_id] = {'error': str(e)}
        
        return status
    
    new_root.putChild('v36_status', WebInterface(get_v36_status))
    web_root.putChild('v36_status', WebInterface(get_v36_status))
    new_root.putChild('heads', WebInterface(lambda: ['%064x' % x for x in node.tracker.heads]))
    new_root.putChild('verified_heads', WebInterface(lambda: ['%064x' % x for x in node.tracker.verified.heads]))
    new_root.putChild('tails', WebInterface(lambda: ['%064x' % x for t in node.tracker.tails for x in node.tracker.reverse.get(t, set())]))
    new_root.putChild('verified_tails', WebInterface(lambda: ['%064x' % x for t in node.tracker.verified.tails for x in node.tracker.verified.reverse.get(t, set())]))
    new_root.putChild('best_share_hash', WebInterface(lambda: '%064x' % node.best_share_var.value))
    new_root.putChild('my_share_hashes', WebInterface(lambda: ['%064x' % my_share_hash for my_share_hash in wb.my_share_hashes]))
    new_root.putChild('my_share_hashes50', WebInterface(lambda: ['%064x' % my_share_hash for my_share_hash in list(wb.my_share_hashes)[:50]]))
    def get_share_data(share_hash_str):
        if int(share_hash_str, 16) not in node.tracker.items:
            return ''
        share = node.tracker.items[int(share_hash_str, 16)]
        return p2pool_data.share_type.pack(share.as_share())
    new_root.putChild('share_data', WebInterface(lambda share_hash_str: get_share_data(share_hash_str), 'application/octet-stream'))
    new_root.putChild('currency_info', WebInterface(lambda: dict(
        symbol=node.net.PARENT.SYMBOL,
        block_explorer_url_prefix=node.net.PARENT.BLOCK_EXPLORER_URL_PREFIX,
        address_explorer_url_prefix=node.net.PARENT.ADDRESS_EXPLORER_URL_PREFIX,
        tx_explorer_url_prefix=node.net.PARENT.TX_EXPLORER_URL_PREFIX,
    )))
    new_root.putChild('version', WebInterface(lambda: p2pool.__version__))
    
    hd_path = os.path.join(datadir_path, 'graph_db')
    hd_data = _atomic_read(hd_path)
    hd_obj = {}
    if hd_data is not None:
        try:
            hd_obj = json.loads(hd_data)
        except Exception:
            log.err(None, 'Error reading graph database:')
    dataview_descriptions = {
        'last_hour': graph.DataViewDescription(150, 60*60),
        'last_day': graph.DataViewDescription(300, 60*60*24),
        'last_week': graph.DataViewDescription(300, 60*60*24*7),
        'last_month': graph.DataViewDescription(300, 60*60*24*30),
        'last_year': graph.DataViewDescription(300, 60*60*24*365.25),
    }
    hd = graph.HistoryDatabase.from_obj({
        'local_hash_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False),
        'local_dead_hash_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False),
        'local_share_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False,
            multivalues=True, multivalue_undefined_means_0=True,
            default_func=graph.make_multivalue_migrator(dict(good='local_share_hash_rate', dead='local_dead_share_hash_rate', orphan='local_orphan_share_hash_rate'),
                post_func=lambda bins: [dict((k, (v[0] - (sum(bin.get(rem_k, (0, 0))[0] for rem_k in ['dead', 'orphan']) if k == 'good' else 0), v[1])) for k, v in bin.iteritems()) for bin in bins])),
        'pool_rates': graph.DataStreamDescription(dataview_descriptions, multivalues=True,
            multivalue_undefined_means_0=True),
        'current_payout': graph.DataStreamDescription(dataview_descriptions),
        'current_payouts': graph.DataStreamDescription(dataview_descriptions, multivalues=True),
        'peers': graph.DataStreamDescription(dataview_descriptions, multivalues=True, default_func=graph.make_multivalue_migrator(dict(incoming='incoming_peers', outgoing='outgoing_peers'))),
        'miner_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True, multivalues_keep=10000),
        'miner_dead_hash_rates': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True, multivalues_keep=10000),
        'merged_current_payouts': graph.DataStreamDescription(dataview_descriptions, multivalues=True),
        'desired_version_rates': graph.DataStreamDescription(dataview_descriptions, multivalues=True,
            multivalue_undefined_means_0=True),
        'traffic_rate': graph.DataStreamDescription(dataview_descriptions, is_gauge=False, multivalues=True),
        'getwork_latency': graph.DataStreamDescription(dataview_descriptions),
        'memory_usage': graph.DataStreamDescription(dataview_descriptions),
        'connected_miners': graph.DataStreamDescription(dataview_descriptions),
        'unique_miner_count': graph.DataStreamDescription(dataview_descriptions),
        'worker_count': graph.DataStreamDescription(dataview_descriptions),
    }, hd_obj)
    x = deferral.RobustLoopingCall(lambda: _atomic_write(hd_path, json.dumps(hd.to_obj())))
    x.start(100)
    stop_event.watch(x.stop)
    @wb.pseudoshare_received.watch
    def _(work, dead, user):
        t = time.time()
        hd.datastreams['local_hash_rate'].add_datum(t, work)
        if dead:
            hd.datastreams['local_dead_hash_rate'].add_datum(t, work)
        if user is not None:
            hd.datastreams['miner_hash_rates'].add_datum(t, {user: work})
            if dead:
                hd.datastreams['miner_dead_hash_rates'].add_datum(t, {user: work})
    @wb.share_received.watch
    def _(work, dead, share_hash):
        t = time.time()
        if not dead:
            hd.datastreams['local_share_hash_rates'].add_datum(t, dict(good=work))
        else:
            hd.datastreams['local_share_hash_rates'].add_datum(t, dict(dead=work))
        def later():
            res = node.tracker.is_child_of(share_hash, node.best_share_var.value)
            if res is None: res = False # share isn't connected to sharechain? assume orphaned
            if res and dead: # share was DOA, but is now in sharechain
                # move from dead to good
                hd.datastreams['local_share_hash_rates'].add_datum(t, dict(dead=-work, good=work))
            elif not res and not dead: # share wasn't DOA, and isn't in sharechain
                # move from good to orphan
                hd.datastreams['local_share_hash_rates'].add_datum(t, dict(good=-work, orphan=work))
        reactor.callLater(200, later)
    @node.p2p_node.traffic_happened.watch
    def _(name, bytes):
        hd.datastreams['traffic_rate'].add_datum(time.time(), {name: bytes})
    def add_point():
        if node.tracker.get_height(node.best_share_var.value) < 10:
            return None
        lookbehind = min(node.net.CHAIN_LENGTH, 60*60//node.net.SHARE_PERIOD, node.tracker.get_height(node.best_share_var.value))
        t = time.time()
        
        pool_rates = p2pool_data.get_stale_counts(node.tracker, node.best_share_var.value, lookbehind, rates=True)
        pool_total = sum(pool_rates.itervalues())
        hd.datastreams['pool_rates'].add_datum(t, pool_rates)
        
        current_txouts = node.get_current_txouts()
        my_current_payouts = 0.0
        for add in wb.pubkeys.keys:
            my_current_payouts += current_txouts.get(
                    add['address'], 0) * 1e-8
        hd.datastreams['current_payout'].add_datum(t, my_current_payouts)
        miner_hash_rates, miner_dead_hash_rates = wb.get_local_rates()
        # Build payout dict keyed by base address (strip worker suffix)
        # miner_hash_rates keys may have .worker suffix, current_txouts keys are base addresses
        payouts_by_address = {}
        for user in miner_hash_rates:
            base_addr = user.split('.')[0].split('_')[0]
            if base_addr in current_txouts:
                payouts_by_address[base_addr] = current_txouts[base_addr] * 1e-8
        hd.datastreams['current_payouts'].add_datum(t, payouts_by_address)
        
        # Track merged mining payouts per miner (DOGE)
        try:
            merged_data = get_current_merged_payouts()
            merged_payouts_dict = {}
            for ltc_addr, data in merged_data.iteritems():
                if data.get('merged'):
                    for mp in data['merged']:
                        # Use LTC address as key for graph correlation
                        merged_payouts_dict[ltc_addr] = mp.get('amount', 0)
            if merged_payouts_dict:
                hd.datastreams['merged_current_payouts'].add_datum(t, merged_payouts_dict)
        except:
            pass
        
        hd.datastreams['peers'].add_datum(t, dict(
            incoming=sum(1 for peer in node.p2p_node.peers.itervalues() if peer.incoming),
            outgoing=sum(1 for peer in node.p2p_node.peers.itervalues() if not peer.incoming),
        ))
        
        vs = p2pool_data.get_desired_version_counts(node.tracker, node.best_share_var.value, lookbehind)
        vs_total = sum(vs.itervalues())
        hd.datastreams['desired_version_rates'].add_datum(t, dict((str(k), v/vs_total*pool_total) for k, v in vs.iteritems()))
        try:
            hd.datastreams['memory_usage'].add_datum(t, memory.resident())
        except:
            if p2pool.DEBUG:
                traceback.print_exc()        
        # Track connected miners and worker counts
        try:
            connected_miners_count = len(miner_hash_rates)
            unique_miners = set(miner_hash_rates.keys())
            hd.datastreams['connected_miners'].add_datum(t, connected_miners_count)
            hd.datastreams['unique_miner_count'].add_datum(t, len(unique_miners))
            hd.datastreams['worker_count'].add_datum(t, connected_miners_count)
        except:
            if p2pool.DEBUG:
                traceback.print_exc()
    x = deferral.RobustLoopingCall(add_point)
    x.start(5)
    stop_event.watch(x.stop)
    @node.bitcoind_work.changed.watch
    def _(new_work):
        hd.datastreams['getwork_latency'].add_datum(time.time(), new_work['latency'])
    
    def get_graph_data(source, view):
        if source not in hd.datastreams:
            return []  # Return empty data for missing datastreams
        if view not in hd.datastreams[source].dataviews:
            return []
        return hd.datastreams[source].dataviews[view].get_data(time.time())
    
    new_root.putChild('graph_data', WebInterface(get_graph_data))
    
    # ====================================================================
    # /msg/* — Share Messaging API
    # ====================================================================
    #
    # Provides REST access to PoW-protected share messages.
    # Messages live as long as their carrying share is in the sharechain.
    # Authority messages (from COMBINED_DONATION_SCRIPT signers) persist longer.
    # Node-local BanList filters messages from display (not from relay).
    #
    # GET  /msg/recent          — recent messages (all types)
    # GET  /msg/chat            — miner-to-miner chat (verified)
    # GET  /msg/announcements   — pool operator announcements
    # GET  /msg/alerts          — emergency alerts
    # GET  /msg/status          — node status reports
    # GET  /msg/stats           — store statistics
    # GET  /msg/bans            — current ban list
    # POST /msg/ban             — add a ban (signing_id, address, keyword, type)
    # POST /msg/unban           — remove a ban
    # ====================================================================
    
    msg_root = resource.Resource()
    web_root.putChild('msg', msg_root)
    
    def _get_message_store():
        """Get or lazily create the ShareMessageStore on the node."""
        store = getattr(node, '_message_store', None)
        if store is None:
            from p2pool.share_messages import ShareMessageStore, BanList
            ban_path = os.path.join(datadir_path, 'banned_senders.json')
            ban_list = BanList(persist_path=ban_path)
            # max_age = sharechain PPLNS window duration (e.g. 8640 * 15 = 36h)
            chain_window_secs = node.net.CHAIN_LENGTH * node.net.SHARE_PERIOD
            store = ShareMessageStore(max_age=chain_window_secs, ban_list=ban_list)
            node._message_store = store
            # Rebuild from current sharechain
            if node.best_share_var.value is not None:
                try:
                    chain_len = min(node.net.CHAIN_LENGTH,
                                    node.tracker.get_height(node.best_share_var.value))
                    rebuilt = store.rebuild_from_tracker(
                        node.tracker, node.best_share_var.value, chain_len)
                    if rebuilt > 0:
                        print('Messaging: rebuilt %d messages from sharechain' % rebuilt)
                except Exception:
                    pass
        # Always try to (re-)load blob dirs — debounced to every 5 min.
        # This picks up blobs added after startup (e.g. via git pull).
        _load_blob_dirs(store)
        return store
    
    from p2pool.share_messages import MSG_EMERGENCY
    
    # GET /msg/config — display policy for dashboard
    class MsgConfigResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            return json.dumps({
                'enable_miner_messages': enable_miner_messages,
                'authority_only': not enable_miner_messages,
            })
    
    msg_root.putChild('config', MsgConfigResource())
    
    # GET /msg/recent?limit=20&since=<timestamp>
    # Without --enable-miner-messages: returns only authority messages
    class MsgRecentResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            try:
                store = _get_message_store()
                limit = int(request.args.get('limit', ['20'])[0])
                since = request.args.get('since', [None])[0]
                since = float(since) if since else None
                msgs = store.get_messages(since=since, limit=min(limit, 200),
                                          authority_only=not enable_miner_messages)
                return json.dumps([m.to_dict() for m in msgs])
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('recent', MsgRecentResource())
    
    # GET /msg/chat?limit=50&verified=1
    # Returns empty unless --enable-miner-messages is set
    class MsgChatResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            if not enable_miner_messages:
                return json.dumps([])
            try:
                store = _get_message_store()
                limit = int(request.args.get('limit', ['50'])[0])
                verified = request.args.get('verified', ['1'])[0] == '1'
                if verified:
                    msgs = store.get_chat(limit=min(limit, 200))
                else:
                    msgs = store.get_all_chat(limit=min(limit, 200))
                return json.dumps([m.to_dict() for m in msgs])
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('chat', MsgChatResource())
    
    # GET /msg/announcements?limit=10
    # Returns empty unless --enable-miner-messages is set
    # (pool announcements are non-authority miner messages)
    class MsgAnnouncementsResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            if not enable_miner_messages:
                return json.dumps([])
            try:
                store = _get_message_store()
                limit = int(request.args.get('limit', ['10'])[0])
                msgs = store.get_announcements(limit=min(limit, 50))
                return json.dumps([m.to_dict() for m in msgs])
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('announcements', MsgAnnouncementsResource())
    
    # GET /msg/alerts?limit=5
    # Returns only authority alerts by default;
    # all alerts when --enable-miner-messages is set
    class MsgAlertsResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            try:
                store = _get_message_store()
                limit = int(request.args.get('limit', ['5'])[0])
                msgs = store.get_messages(msg_type=MSG_EMERGENCY,
                                          limit=min(limit, 20),
                                          authority_only=not enable_miner_messages)
                return json.dumps([m.to_dict() for m in msgs])
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('alerts', MsgAlertsResource())
    
    # GET /msg/status?limit=20
    # Returns empty unless --enable-miner-messages is set
    class MsgStatusResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            if not enable_miner_messages:
                return json.dumps([])
            try:
                store = _get_message_store()
                limit = int(request.args.get('limit', ['20'])[0])
                msgs = store.get_node_statuses(limit=min(limit, 100))
                return json.dumps([m.to_dict() for m in msgs])
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('status', MsgStatusResource())
    
    # GET /msg/stats
    class MsgStatsResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            try:
                store = _get_message_store()
                return json.dumps(store.stats)
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('stats', MsgStatsResource())
    
    # GET /msg/bans
    class MsgBansResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            try:
                store = _get_message_store()
                return json.dumps(store.ban_list.to_json())
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('bans', MsgBansResource())

    # GET /msg/diag — blob loading diagnostics (helps operators debug
    # why transition messages may not be showing)
    class MsgDiagResource(resource.Resource):
        def render_GET(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            # Security: only allow from localhost (exposes filesystem paths)
            if not _is_localhost(request):
                request.setResponseCode(403)
                return json.dumps({'error': 'forbidden: localhost only'})
            try:
                store = _get_message_store()
                # Directories that _load_blob_dirs scans
                _script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                _module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                _search_bases = list(dict.fromkeys([_script_dir, _module_dir]))

                scanned_dirs = []
                # data dir blobs
                if datadir_path:
                    for dirname in ('bootstrap_messages', 'transition_messages', 'transitional_messages'):
                        d = os.path.join(datadir_path, dirname)
                        exists = os.path.isdir(d)
                        files = []
                        if exists:
                            for fn in sorted(os.listdir(d)):
                                if fn.endswith('.hex') or fn.endswith('.blob'):
                                    fp = os.path.join(d, fn)
                                    try:
                                        readable = os.access(fp, os.R_OK)
                                        size = os.path.getsize(fp)
                                    except Exception:
                                        readable = False
                                        size = -1
                                    files.append({'name': fn, 'readable': readable, 'size': size})
                        scanned_dirs.append({'path': d, 'exists': exists, 'files': files})

                # shipped dirs
                for _base in _search_bases:
                    for _dname in ('transition_messages', 'transitional_messages'):
                        d = os.path.join(_base, _dname)
                        exists = os.path.isdir(d)
                        files = []
                        if exists:
                            for fn in sorted(os.listdir(d)):
                                if fn.endswith('.hex') or fn.endswith('.blob'):
                                    fp = os.path.join(d, fn)
                                    try:
                                        readable = os.access(fp, os.R_OK)
                                        size = os.path.getsize(fp)
                                    except Exception:
                                        readable = False
                                        size = -1
                                    files.append({'name': fn, 'readable': readable, 'size': size})
                        scanned_dirs.append({'path': d, 'exists': exists, 'files': files})

                # Store state
                msg_count = len(store.messages) if hasattr(store, 'messages') else 0
                transition_msgs = [m.to_dict() for m in store.messages
                                   if hasattr(m, 'msg_type') and m.msg_type == 0x20]

                return json.dumps({
                    'blob_scan_count': _blob_scan_count[0],
                    'last_blob_scan': _last_blob_scan[0],
                    'seconds_since_scan': int(time.time() - _last_blob_scan[0]) if _last_blob_scan[0] else None,
                    'cli_transition_message': transition_message or None,
                    'scanned_dirs': scanned_dirs,
                    'builtin_blobs': len(_BUILTIN_TRANSITION_BLOBS),
                    'store_message_count': msg_count,
                    'transition_signals': transition_msgs,
                    'enable_miner_messages': enable_miner_messages,
                })
            except Exception as e:
                import traceback
                print('Messaging: /msg/diag error: %s' % traceback.format_exc())
                return json.dumps({'error': 'internal error'})

    msg_root.putChild('diag', MsgDiagResource())

    # POST /msg/ban — add a ban
    # Body: {"signing_id": "hex"} or {"address": "addr"} or
    #       {"keyword": "word"} or {"type": 2}
    class MsgBanResource(resource.Resource):
        def render_POST(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            # Security: only allow from localhost
            if not _is_localhost(request):
                request.setResponseCode(403)
                return json.dumps({'error': 'forbidden: localhost only'})
            try:
                store = _get_message_store()
                content = request.content.read(65536)
                if len(content) >= 65536:
                    request.setResponseCode(413)
                    return json.dumps({'error': 'request body too large'})
                body = json.loads(content)
                actions = []
                if 'signing_id' in body:
                    store.ban_list.ban_signing_id(body['signing_id'])
                    actions.append('banned signing_id %s' % body['signing_id'])
                if 'address' in body:
                    store.ban_list.ban_address(body['address'])
                    actions.append('banned address %s' % body['address'])
                if 'keyword' in body:
                    store.ban_list.ban_keyword(body['keyword'])
                    actions.append('banned keyword "%s"' % body['keyword'])
                if 'type' in body:
                    store.ban_list.ban_type(int(body['type']))
                    actions.append('banned type 0x%02x' % int(body['type']))
                if not actions:
                    return json.dumps({'error': 'no ban target specified'})
                return json.dumps({'ok': True, 'actions': actions})
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('ban', MsgBanResource())
    
    # POST /msg/unban — remove a ban
    # Body: same format as /msg/ban
    class MsgUnbanResource(resource.Resource):
        def render_POST(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            # Security: only allow from localhost
            if not _is_localhost(request):
                request.setResponseCode(403)
                return json.dumps({'error': 'forbidden: localhost only'})
            try:
                store = _get_message_store()
                content = request.content.read(65536)
                if len(content) >= 65536:
                    request.setResponseCode(413)
                    return json.dumps({'error': 'request body too large'})
                body = json.loads(content)
                actions = []
                if 'signing_id' in body:
                    store.ban_list.unban_signing_id(body['signing_id'])
                    actions.append('unbanned signing_id %s' % body['signing_id'])
                if 'address' in body:
                    store.ban_list.unban_address(body['address'])
                    actions.append('unbanned address %s' % body['address'])
                if 'keyword' in body:
                    store.ban_list.unban_keyword(body['keyword'])
                    actions.append('unbanned keyword "%s"' % body['keyword'])
                if 'type' in body:
                    store.ban_list.unban_type(int(body['type']))
                    actions.append('unbanned type 0x%02x' % int(body['type']))
                if not actions:
                    return json.dumps({'error': 'no unban target specified'})
                return json.dumps({'ok': True, 'actions': actions})
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('unban', MsgUnbanResource())
    
    # POST /msg/load_blob — load a transition/authority message blob at runtime
    # Body: {"blob_hex": "<hex_string>"} or {"blob_file": "<path_to_hex_file>"}
    # Restricted to localhost connections for security.
    # This allows loading new transition signals for future transitions
    # (e.g. V36→V37) without restarting the node.
    class MsgLoadBlobResource(resource.Resource):
        def render_POST(self, request):
            request.setHeader('Content-Type', 'application/json')
            request.setHeader('Access-Control-Allow-Origin', '*')
            # Security: only allow from localhost
            if not _is_localhost(request):
                request.setResponseCode(403)
                return json.dumps({'error': 'forbidden: localhost only'})
            try:
                store = _get_message_store()
                content = request.content.read(65536)
                if len(content) >= 65536:
                    request.setResponseCode(413)
                    return json.dumps({'error': 'request body too large'})
                body = json.loads(content)
                blob_hex = body.get('blob_hex', '')
                blob_file = body.get('blob_file', '')
                if blob_file:
                    if not os.path.isfile(blob_file):
                        return json.dumps({'error': 'blob_file not found: %s' % blob_file})
                    with open(blob_file, 'r') as f:
                        blob_hex = f.read().strip()
                if not blob_hex:
                    return json.dumps({'error': 'no blob_hex or blob_file provided'})
                n = store.load_blob_hex(blob_hex)
                if n > 0:
                    print('Messaging: loaded %d message(s) from /msg/load_blob' % n)
                return json.dumps({'ok': True, 'loaded': n})
            except Exception as e:
                return json.dumps({'error': str(e)})
    
    msg_root.putChild('load_blob', MsgLoadBlobResource())
    
    # ====================================================================
    # Live share message ingestion
    # ====================================================================
    # When a V36+ share is verified and carries message_data, its
    # already-validated _parsed_messages (from check()) are added to the
    # message store immediately.  This means transition signals embedded
    # in shares appear in the API/dashboard as soon as the share is
    # accepted, rather than only on startup via rebuild_from_tracker().
    def _on_verified_share(share_hash):
        store = getattr(node, '_message_store', None)
        if store is None:
            return
        try:
            share = node.tracker.items[share_hash]
            if not hasattr(share, '_parsed_messages') or not share._parsed_messages:
                return
            added = 0
            for msg in share._parsed_messages:
                msg.share_hash = share.hash
                msg.sender_address = getattr(share, 'address', None)
                if store._add_message(msg):
                    added += 1
            if added > 0:
                print('Messaging: ingested %d message(s) from verified share %064x' % (added, share.hash))
        except Exception:
            pass  # Share might be gone from tracker
    
    node.tracker.verified.added.watch(_on_verified_share)
    
    if static_dir is None:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'web-static')
    web_root.putChild('static', static.File(static_dir))
    
    return web_root
