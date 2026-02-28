#!/usr/bin/env python
"""Tests for AutoRatchet — automated V35->V36 share version ratchet.

Tests the state machine: VOTING -> ACTIVATED -> CONFIRMED
and all edge cases including network reversions, empty chains, etc.

Run: pypy test_auto_ratchet.py
"""
from __future__ import division
import os
import sys
import json
import tempfile
import shutil
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from p2pool.data import AutoRatchet, MergedMiningShare, PaddingBugfixShare


class MockShare(object):
    """Minimal share mock for AutoRatchet testing."""
    def __init__(self, version, desired_version, target=2**256 - 1):
        self.VERSION = version
        self.desired_version = desired_version
        self.share_data = {'desired_version': desired_version, 'donation': 0}
        self.target = target
        self.hash = os.urandom(32).encode('hex')


class MockTracker(object):
    """Minimal tracker mock that returns a chain of MockShares."""
    def __init__(self, shares=None):
        self._shares = shares or []
        self.items = {}
    
    def get_height(self, best_share_hash):
        return len(self._shares)
    
    def get_chain(self, best_share_hash, length):
        return self._shares[:length]


class MockNet(object):
    """Minimal network config mock."""
    def __init__(self, real_chain_length=400):
        self.REAL_CHAIN_LENGTH = real_chain_length
        self.CHAIN_LENGTH = real_chain_length
        self.NAME = 'test'


class TestAutoRatchetInit(unittest.TestCase):
    """Test initialization and state persistence."""
    
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self.tmpdir)
    
    def test_fresh_start_voting(self):
        """Fresh AutoRatchet starts in VOTING state."""
        r = AutoRatchet(self.tmpdir)
        self.assertEqual(r.state, AutoRatchet.STATE_VOTING)
    
    def test_state_persisted_to_disk(self):
        """State is saved to and loaded from disk."""
        r = AutoRatchet(self.tmpdir)
        # Manually set state
        r._state = AutoRatchet.STATE_CONFIRMED
        r._confirmed_at = 1234567890
        r._save()
        
        # New instance should load persisted state
        r2 = AutoRatchet(self.tmpdir)
        self.assertEqual(r2.state, AutoRatchet.STATE_CONFIRMED)
        self.assertEqual(r2._confirmed_at, 1234567890)
    
    def test_corrupted_state_file(self):
        """Corrupted state file doesn't crash — defaults to VOTING."""
        state_file = os.path.join(self.tmpdir, 'v36_ratchet.json')
        with open(state_file, 'w') as f:
            f.write('not valid json{{{')
        
        r = AutoRatchet(self.tmpdir)
        self.assertEqual(r.state, AutoRatchet.STATE_VOTING)
    
    def test_none_datadir(self):
        """None datadir doesn't crash."""
        r = AutoRatchet(None)
        self.assertEqual(r.state, AutoRatchet.STATE_VOTING)


class TestAutoRatchetVoting(unittest.TestCase):
    """Test VOTING state behavior."""
    
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.net = MockNet(real_chain_length=10)  # Small window for tests
    
    def tearDown(self):
        shutil.rmtree(self.tmpdir)
    
    def test_empty_chain_returns_v35(self):
        """Empty chain in VOTING state → V35 shares."""
        r = AutoRatchet(self.tmpdir)
        tracker = MockTracker([])
        share_type, desired = r.get_share_version(tracker, None, self.net)
        self.assertEqual(share_type, PaddingBugfixShare)
        self.assertEqual(desired, 36)
    
    def test_partial_window_stays_voting(self):
        """Less than REAL_CHAIN_LENGTH shares → stays VOTING even if all vote V36."""
        r = AutoRatchet(self.tmpdir)
        shares = [MockShare(35, 36) for _ in range(5)]  # Only 5 of 10 needed
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(r.state, AutoRatchet.STATE_VOTING)
        self.assertEqual(share_type, PaddingBugfixShare)
    
    def test_full_window_95pct_activates(self):
        """Full window with 95%+ V36 votes → ACTIVATED."""
        r = AutoRatchet(self.tmpdir)
        # 10 shares, all voting V36 (100%)
        shares = [MockShare(35, 36) for _ in range(10)]
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(r.state, AutoRatchet.STATE_ACTIVATED)
        self.assertEqual(share_type, MergedMiningShare)
    
    def test_full_window_below_threshold_stays_voting(self):
        """Full window with <95% V36 votes → stays VOTING."""
        r = AutoRatchet(self.tmpdir)
        # 10 shares: 9 vote V36, 1 votes V35 = 90% < 95%
        shares = [MockShare(35, 36) for _ in range(9)] + [MockShare(35, 35)]
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(r.state, AutoRatchet.STATE_VOTING)
        self.assertEqual(share_type, PaddingBugfixShare)


class TestAutoRatchetActivated(unittest.TestCase):
    """Test ACTIVATED state behavior."""
    
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.net = MockNet(real_chain_length=10)
    
    def tearDown(self):
        shutil.rmtree(self.tmpdir)
    
    def _activate(self):
        """Helper: create an ACTIVATED ratchet."""
        r = AutoRatchet(self.tmpdir)
        r._state = AutoRatchet.STATE_ACTIVATED
        r._activated_at = 1000000
        r._activated_height = 100
        r._save()
        return r
    
    def test_activated_creates_v36(self):
        """ACTIVATED state → creates V36 shares."""
        r = self._activate()
        shares = [MockShare(36, 36) for _ in range(10)]
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(share_type, MergedMiningShare)
    
    def test_activated_reverts_on_v35_majority(self):
        """ACTIVATED reverts to VOTING when <50% vote V36."""
        r = self._activate()
        # 10 shares: 4 vote V36 (40%), 6 vote V35 (60%) → below 50% threshold
        shares = [MockShare(35, 36) for _ in range(4)] + [MockShare(35, 35) for _ in range(6)]
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(r.state, AutoRatchet.STATE_VOTING)
        self.assertEqual(share_type, PaddingBugfixShare)
    
    def test_activated_empty_chain_returns_v35(self):
        """ACTIVATED but empty chain → V35 (not safe to assume V36 without peers)."""
        r = self._activate()
        tracker = MockTracker([])
        share_type, desired = r.get_share_version(tracker, None, self.net)
        self.assertEqual(share_type, PaddingBugfixShare)
        self.assertEqual(desired, 36)
    
    def test_activated_to_confirmed(self):
        """ACTIVATED → CONFIRMED after sustained V36 majority."""
        r = AutoRatchet(self.tmpdir)
        r._state = AutoRatchet.STATE_ACTIVATED
        r._activated_at = 1000000
        r._activated_height = 10  # Activated at height 10
        r._save()
        
        # Confirmation window = 2 * 10 = 20
        # Current height needs to be >= 10 + 20 = 30
        # And 95% of shares need to be actual V36 format
        shares = [MockShare(36, 36) for _ in range(30)]
        tracker = MockTracker(shares)
        # Height = 30, activated_height = 10, shares_since = 20 >= 20 (confirmation_window)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(r.state, AutoRatchet.STATE_CONFIRMED)
        self.assertEqual(share_type, MergedMiningShare)
    
    def test_activated_not_confirmed_too_early(self):
        """ACTIVATED stays ACTIVATED when not enough sustained shares."""
        r = AutoRatchet(self.tmpdir)
        r._state = AutoRatchet.STATE_ACTIVATED
        r._activated_at = 1000000
        r._activated_height = 10
        r._save()
        
        # Only 15 shares since activation, need 20 (2 * REAL_CHAIN_LENGTH)
        shares = [MockShare(36, 36) for _ in range(10)]  # height=10, since=0
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(r.state, AutoRatchet.STATE_ACTIVATED)
        # Still creates V36 though
        self.assertEqual(share_type, MergedMiningShare)


class TestAutoRatchetConfirmed(unittest.TestCase):
    """Test CONFIRMED state behavior."""
    
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.net = MockNet(real_chain_length=10)
    
    def tearDown(self):
        shutil.rmtree(self.tmpdir)
    
    def _confirm(self):
        """Helper: create a CONFIRMED ratchet."""
        r = AutoRatchet(self.tmpdir)
        r._state = AutoRatchet.STATE_CONFIRMED
        r._activated_at = 1000000
        r._activated_height = 100
        r._confirmed_at = 2000000
        r._save()
        return r
    
    def test_confirmed_empty_chain_stays_v36(self):
        """CONFIRMED with empty chain → V36 immediately (the key benefit)."""
        r = self._confirm()
        tracker = MockTracker([])
        share_type, desired = r.get_share_version(tracker, None, self.net)
        self.assertEqual(share_type, MergedMiningShare)
        self.assertEqual(desired, 36)
    
    def test_confirmed_survives_restart(self):
        """CONFIRMED state persists across object recreation."""
        r = self._confirm()
        # Simulate restart — new AutoRatchet instance
        r2 = AutoRatchet(self.tmpdir)
        self.assertEqual(r2.state, AutoRatchet.STATE_CONFIRMED)
        
        tracker = MockTracker([])
        share_type, desired = r2.get_share_version(tracker, None, self.net)
        self.assertEqual(share_type, MergedMiningShare)
    
    def test_confirmed_follows_v35_network(self):
        """CONFIRMED but V35 network majority → follows network (creates V35)."""
        r = self._confirm()
        # Network is 70% V35 — confirmed node should follow consensus
        shares = [MockShare(35, 36) for _ in range(3)] + [MockShare(35, 35) for _ in range(7)]
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(share_type, PaddingBugfixShare)  # Follows V35 network
        self.assertEqual(desired, 36)  # Still votes V36
        # State stays CONFIRMED (doesn't lose confirmation)
        self.assertEqual(r.state, AutoRatchet.STATE_CONFIRMED)
    
    def test_confirmed_normal_v36_network(self):
        """CONFIRMED with V36 network → normal V36 operation."""
        r = self._confirm()
        shares = [MockShare(36, 36) for _ in range(10)]
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(share_type, MergedMiningShare)


class TestAutoRatchetMainnetWindow(unittest.TestCase):
    """Test with mainnet-sized window (8640 shares)."""
    
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.net = MockNet(real_chain_length=8640)
    
    def tearDown(self):
        shutil.rmtree(self.tmpdir)
    
    def test_mainnet_needs_full_window(self):
        """Mainnet: doesn't activate with partial window even if all V36."""
        r = AutoRatchet(self.tmpdir)
        # 1000 shares (all V36) but need 8640
        shares = [MockShare(35, 36) for _ in range(1000)]
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(r.state, AutoRatchet.STATE_VOTING)
    
    def test_mainnet_confirmation_window(self):
        """Mainnet: confirmation requires 2*8640 = 17280 shares since activation."""
        r = AutoRatchet(self.tmpdir)
        r._state = AutoRatchet.STATE_ACTIVATED
        r._activated_at = 1000000
        r._activated_height = 1000  # Activated at height 1000
        r._save()
        
        # Need height >= 1000 + 17280 = 18280
        # Supply 8640 shares (window), height reports 8640, shares_since = 8640 - 1000 = 7640 < 17280
        shares = [MockShare(36, 36) for _ in range(8640)]
        tracker = MockTracker(shares)
        share_type, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(r.state, AutoRatchet.STATE_ACTIVATED)  # Not confirmed yet
        self.assertEqual(share_type, MergedMiningShare)  # But still creates V36


class TestAutoRatchetDesiredVersion(unittest.TestCase):
    """Test that desired_version is always 36."""
    
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.net = MockNet(real_chain_length=10)
    
    def tearDown(self):
        shutil.rmtree(self.tmpdir)
    
    def test_voting_always_votes_36(self):
        r = AutoRatchet(self.tmpdir)
        tracker = MockTracker([])
        _, desired = r.get_share_version(tracker, None, self.net)
        self.assertEqual(desired, 36)
    
    def test_activated_always_votes_36(self):
        r = AutoRatchet(self.tmpdir)
        r._state = AutoRatchet.STATE_ACTIVATED
        r._activated_at = 1000000
        r._activated_height = 0
        tracker = MockTracker([MockShare(36, 36) for _ in range(10)])
        _, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(desired, 36)
    
    def test_confirmed_following_v35_still_votes_36(self):
        r = AutoRatchet(self.tmpdir)
        r._state = AutoRatchet.STATE_CONFIRMED
        r._confirmed_at = 1000000
        # V35 majority network
        shares = [MockShare(35, 35) for _ in range(10)]
        tracker = MockTracker(shares)
        _, desired = r.get_share_version(tracker, 'hash', self.net)
        self.assertEqual(desired, 36)


if __name__ == '__main__':
    unittest.main()
