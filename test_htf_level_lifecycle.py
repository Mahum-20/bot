"""
Unit Tests for HTF Level Invalidation & Overlap Management
==========================================================
Tests A through J covering:
- Test A: Trade consumption (Win and Loss both consume level, no second trade)
- Test B: Two overlapping levels (Grouped into one collective opportunity, exactly 1 trade)
- Test C: Three or more overlapping levels (Single collective opportunity)
- Test D: Consumed group receives a new overlapping level (Inherits consumed state, no trade)
- Test E: Two consecutive closes beyond demand (Invalidation after 2 closes)
- Test F: Non-consecutive closes (Reset counter on inside close)
- Test G: Supply invalidation (Two consecutive closes above upper boundary)
- Test H: Timeframe isolation (H1 level only invalidated by H1 candles, not M5)
- Test I: Candle processing (No double-counting, incomplete candle excluded, deterministic)
- Test J: Merging groups (Merged group inherits consumed state from consumed component)
"""

import os
import tempfile
import unittest

from htf_level_lifecycle_manager import (
    HTFLevelLifecycleManager,
    LevelStatus,
    GroupStatus
)


class TestHTFLevelLifecycle(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_storage_path = os.path.join(self.temp_dir, "test_lifecycle.json")
        self.manager = HTFLevelLifecycleManager(storage_path=self.test_storage_path)

    def tearDown(self):
        try:
            if os.path.exists(self.test_storage_path):
                os.remove(self.test_storage_path)
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Test A: Trade Consumption
    # -------------------------------------------------------------------------
    def test_a_trade_consumption(self):
        box_h1 = {
            "text": "TJL1 (Demand)",
            "top": 105.0,
            "bottom": 100.0,
            "left": 1000,
            "confirmed_formation_time": 1000,
            "is_bullish": True
        }
        self.manager.register_or_update_box("BTCUSDT", "1h", box_h1)

        # 1. Active initially
        can_trade, reason = self.manager.is_box_tradable("BTCUSDT", "1h", box_h1)
        self.assertTrue(can_trade)

        # 2. Execute a winning buy trade
        self.manager.mark_trade_executed("BTCUSDT", "1h", box_h1, trade_id="TRADE_WIN_1")

        # 3. Level is now consumed
        can_trade_after, reason = self.manager.is_box_tradable("BTCUSDT", "1h", box_h1)
        self.assertFalse(can_trade_after)
        self.assertIn("CONSUMED", reason)

        # 4. Repeat with another level and a losing trade
        box_loss = {
            "text": "TJL2 (Demand)",
            "top": 95.0,
            "bottom": 90.0,
            "left": 2000,
            "confirmed_formation_time": 2000,
            "is_bullish": True
        }
        self.manager.register_or_update_box("BTCUSDT", "1h", box_loss)
        self.assertTrue(self.manager.is_box_tradable("BTCUSDT", "1h", box_loss)[0])

        self.manager.mark_trade_executed("BTCUSDT", "1h", box_loss, trade_id="TRADE_LOSS_2")
        can_trade_loss, reason_loss = self.manager.is_box_tradable("BTCUSDT", "1h", box_loss)
        self.assertFalse(can_trade_loss)
        self.assertIn("CONSUMED", reason_loss)

    # -------------------------------------------------------------------------
    # Test B: Two Overlapping Levels
    # -------------------------------------------------------------------------
    def test_b_two_overlapping_levels(self):
        # H1 demand zone: 100 - 105
        box_h1 = {
            "text": "TJL1 (Demand)",
            "top": 105.0,
            "bottom": 100.0,
            "left": 1000,
            "confirmed_formation_time": 1000,
            "is_bullish": True
        }
        # M15 demand zone: 103 - 108 (overlaps with H1 demand in 103-105)
        box_m15 = {
            "text": "QML (Demand)",
            "top": 108.0,
            "bottom": 103.0,
            "left": 1500,
            "confirmed_formation_time": 1500,
            "is_bullish": True
        }

        lvl_h1 = self.manager.register_or_update_box("BTCUSDT", "1h", box_h1)
        lvl_m15 = self.manager.register_or_update_box("BTCUSDT", "15m", box_m15)

        # Verify they share the exact same group_id
        self.assertIsNotNone(lvl_h1.group_id)
        self.assertEqual(lvl_h1.group_id, lvl_m15.group_id)

        group = self.manager.groups[lvl_h1.group_id]
        self.assertEqual(len(group.constituent_ids), 2)
        self.assertEqual(group.top, 108.0)
        self.assertEqual(group.bottom, 100.0)

        # Both initially tradable as constituents of active group
        self.assertTrue(self.manager.is_box_tradable("BTCUSDT", "1h", box_h1)[0])
        self.assertTrue(self.manager.is_box_tradable("BTCUSDT", "15m", box_m15)[0])

        # Execute trade from M15 level
        self.manager.mark_trade_executed("BTCUSDT", "15m", box_m15, trade_id="TRADE_M15_EXEC")

        # Now BOTH H1 and M15 levels must be CONSUMED (only 1 trade from collective group)
        self.assertFalse(self.manager.is_box_tradable("BTCUSDT", "1h", box_h1)[0])
        self.assertFalse(self.manager.is_box_tradable("BTCUSDT", "15m", box_m15)[0])
        self.assertTrue(group.consumed)

    # -------------------------------------------------------------------------
    # Test C: Three or More Overlapping Levels
    # -------------------------------------------------------------------------
    def test_c_three_or_more_overlapping_levels(self):
        # Level 1 (H4): 100 - 110
        box1 = {"text": "TJL1 (Demand)", "top": 110.0, "bottom": 100.0, "left": 1000, "is_bullish": True}
        # Level 2 (H1): 108 - 115 (overlaps Level 1 in 108-110)
        box2 = {"text": "TJL2 (Demand)", "top": 115.0, "bottom": 108.0, "left": 1500, "is_bullish": True}
        # Level 3 (M15): 112 - 120 (overlaps Level 2 in 112-115)
        box3 = {"text": "RBS (Demand)", "top": 120.0, "bottom": 112.0, "left": 2000, "is_bullish": True}

        lvl1 = self.manager.register_or_update_box("BTCUSDT", "4h", box1)
        lvl2 = self.manager.register_or_update_box("BTCUSDT", "1h", box2)
        lvl3 = self.manager.register_or_update_box("BTCUSDT", "15m", box3)

        # Transitive overlap: all three belong to the same group
        self.assertEqual(lvl1.group_id, lvl2.group_id)
        self.assertEqual(lvl2.group_id, lvl3.group_id)

        group = self.manager.groups[lvl1.group_id]
        self.assertEqual(len(group.constituent_ids), 3)

        # One trade consumes all 3
        self.manager.mark_trade_executed("BTCUSDT", "4h", box1, trade_id="TRADE_GROUP_3")
        self.assertFalse(self.manager.is_box_tradable("BTCUSDT", "4h", box1)[0])
        self.assertFalse(self.manager.is_box_tradable("BTCUSDT", "1h", box2)[0])
        self.assertFalse(self.manager.is_box_tradable("BTCUSDT", "15m", box3)[0])

    # -------------------------------------------------------------------------
    # Test D: Consumed Group Receives a New Overlapping Level
    # -------------------------------------------------------------------------
    def test_d_consumed_group_inherits_state(self):
        # 1. Create and group H1 and M15 demand
        box_h1 = {"text": "TJL1 (Demand)", "top": 105.0, "bottom": 100.0, "left": 1000, "is_bullish": True}
        box_m15 = {"text": "TJL2 (Demand)", "top": 104.0, "bottom": 101.0, "left": 1500, "is_bullish": True}

        self.manager.register_or_update_box("BTCUSDT", "1h", box_h1)
        self.manager.register_or_update_box("BTCUSDT", "15m", box_m15)

        # 2. Execute trade
        self.manager.mark_trade_executed("BTCUSDT", "1h", box_h1, trade_id="TRADE_PAST")

        # 3. Later, a newly generated M15 demand forms overlapping the consumed price zone
        box_m15_new = {"text": "QML (Demand)", "top": 103.0, "bottom": 98.0, "left": 3000, "is_bullish": True}
        lvl_new = self.manager.register_or_update_box("BTCUSDT", "15m", box_m15_new)

        # Must inherit CONSUMED state immediately
        self.assertTrue(lvl_new.consumed)
        can_trade, reason = self.manager.is_box_tradable("BTCUSDT", "15m", box_m15_new)
        self.assertFalse(can_trade)
        self.assertIn("CONSUMED", reason)

    # -------------------------------------------------------------------------
    # Test E: Two Consecutive Closes Beyond Demand
    # -------------------------------------------------------------------------
    def test_e_two_consecutive_closes_beyond_demand(self):
        box_h1 = {"text": "TJL1 (Demand)", "top": 105.0, "bottom": 100.0, "left": 1000, "is_bullish": True}
        self.manager.register_or_update_box("BTCUSDT", "1h", box_h1)

        # Candle 1: closes below demand at 99.0 (1/2)
        c1 = {"time": 3600, "open": 102.0, "high": 103.0, "low": 98.5, "close": 99.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c1, htf_sec=3600)

        lvl = self.manager.levels[self.manager.format_level_id("BTCUSDT", "1h", box_h1)]
        self.assertEqual(lvl.consecutive_beyond_closes, 1)
        self.assertEqual(lvl.status, LevelStatus.ACTIVE)
        self.assertTrue(self.manager.is_box_tradable("BTCUSDT", "1h", box_h1)[0])

        # Candle 2: consecutive close below demand at 98.0 (2/2) -> INVALIDATED
        c2 = {"time": 7200, "open": 99.0, "high": 99.5, "low": 97.0, "close": 98.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c2, htf_sec=3600)

        self.assertEqual(lvl.consecutive_beyond_closes, 2)
        self.assertEqual(lvl.status, LevelStatus.INVALIDATED)
        can_trade, reason = self.manager.is_box_tradable("BTCUSDT", "1h", box_h1)
        self.assertFalse(can_trade)
        self.assertIn("INVALIDATED", reason)

    # -------------------------------------------------------------------------
    # Test F: Non-Consecutive Closes
    # -------------------------------------------------------------------------
    def test_f_non_consecutive_closes_reset_counter(self):
        box_h1 = {"text": "TJL1 (Demand)", "top": 105.0, "bottom": 100.0, "left": 1000, "is_bullish": True}
        self.manager.register_or_update_box("BTCUSDT", "1h", box_h1)
        lvl = self.manager.levels[self.manager.format_level_id("BTCUSDT", "1h", box_h1)]

        # Candle 1: close below at 99 (1/2)
        c1 = {"time": 3600, "close": 99.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c1, htf_sec=3600)
        self.assertEqual(lvl.consecutive_beyond_closes, 1)

        # Candle 2: close back inside at 102.0 -> counter resets to 0
        c2 = {"time": 7200, "close": 102.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c2, htf_sec=3600)
        self.assertEqual(lvl.consecutive_beyond_closes, 0)
        self.assertEqual(lvl.status, LevelStatus.ACTIVE)

        # Candle 3: close below again at 98.5 -> counter is 1/2 (NOT invalidated)
        c3 = {"time": 10800, "close": 98.5}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c3, htf_sec=3600)
        self.assertEqual(lvl.consecutive_beyond_closes, 1)
        self.assertEqual(lvl.status, LevelStatus.ACTIVE)

        # Candle 4: consecutive close below at 97.0 -> now 2/2 -> INVALIDATED
        c4 = {"time": 14400, "close": 97.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c4, htf_sec=3600)
        self.assertEqual(lvl.consecutive_beyond_closes, 2)
        self.assertEqual(lvl.status, LevelStatus.INVALIDATED)

    # -------------------------------------------------------------------------
    # Test G: Supply Invalidation
    # -------------------------------------------------------------------------
    def test_g_supply_invalidation(self):
        box_supply = {"text": "QML (Supply)", "top": 115.0, "bottom": 110.0, "left": 1000, "is_bullish": False}
        self.manager.register_or_update_box("BTCUSDT", "1h", box_supply)
        lvl = self.manager.levels[self.manager.format_level_id("BTCUSDT", "1h", box_supply)]

        # Candle 1 closes above upper boundary 115.0 at 116.0 (1/2)
        c1 = {"time": 3600, "close": 116.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c1, htf_sec=3600)
        self.assertEqual(lvl.consecutive_beyond_closes, 1)
        self.assertEqual(lvl.status, LevelStatus.ACTIVE)

        # Candle 2 closes above upper boundary at 117.0 (2/2) -> INVALIDATED
        c2 = {"time": 7200, "close": 117.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c2, htf_sec=3600)
        self.assertEqual(lvl.consecutive_beyond_closes, 2)
        self.assertEqual(lvl.status, LevelStatus.INVALIDATED)
        self.assertFalse(self.manager.is_box_tradable("BTCUSDT", "1h", box_supply)[0])

    # -------------------------------------------------------------------------
    # Test H: Timeframe Isolation
    # -------------------------------------------------------------------------
    def test_h_timeframe_isolation(self):
        box_h1 = {"text": "TJL1 (Demand)", "top": 105.0, "bottom": 100.0, "left": 1000, "is_bullish": True}
        self.manager.register_or_update_box("BTCUSDT", "1h", box_h1)
        lvl = self.manager.levels[self.manager.format_level_id("BTCUSDT", "1h", box_h1)]

        # Generate M5 candles closing below 100.0: MUST NOT invalidate the H1 level!
        m5_c1 = {"time": 1300, "close": 98.0}
        m5_c2 = {"time": 1600, "close": 97.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "5m", m5_c1, htf_sec=300)
        self.manager.process_closed_htf_candle("BTCUSDT", "5m", m5_c2, htf_sec=300)

        # H1 level remains untouched
        self.assertEqual(lvl.consecutive_beyond_closes, 0)
        self.assertEqual(lvl.status, LevelStatus.ACTIVE)

        # Only H1 candles can invalidate H1 level
        h1_c1 = {"time": 3600, "close": 98.0}
        h1_c2 = {"time": 7200, "close": 97.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", h1_c1, htf_sec=3600)
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", h1_c2, htf_sec=3600)

        self.assertEqual(lvl.status, LevelStatus.INVALIDATED)

    # -------------------------------------------------------------------------
    # Test I: Candle Processing Integrity
    # -------------------------------------------------------------------------
    def test_i_candle_processing_integrity(self):
        box = {"text": "TJL1 (Demand)", "top": 105.0, "bottom": 100.0, "left": 1000, "is_bullish": True}
        self.manager.register_or_update_box("BTCUSDT", "1h", box)
        lvl = self.manager.levels[self.manager.format_level_id("BTCUSDT", "1h", box)]

        # 1. Processing the same completed candle twice must NOT increment counter twice
        c1 = {"time": 3600, "close": 99.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c1, htf_sec=3600)
        self.assertEqual(lvl.consecutive_beyond_closes, 1)

        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c1, htf_sec=3600)
        self.assertEqual(lvl.consecutive_beyond_closes, 1)  # Still 1, not 2!

        # 2. Incomplete candle is excluded
        c2_incomplete = {"time": 7200, "close": 98.0}
        self.manager.process_closed_htf_candle("BTCUSDT", "1h", c2_incomplete, htf_sec=3600, is_completed=False)
        self.assertEqual(lvl.consecutive_beyond_closes, 1)  # Still 1!

    # -------------------------------------------------------------------------
    # Test J: Merging Groups with Consumed Component
    # -------------------------------------------------------------------------
    def test_j_merging_groups_inherits_consumed(self):
        # Group 1: 100 - 105 (H1 Demand)
        box1 = {"text": "TJL1 (Demand)", "top": 105.0, "bottom": 100.0, "left": 1000, "is_bullish": True}
        self.manager.register_or_update_box("BTCUSDT", "1h", box1)

        # Consume Group 1 via executed trade
        self.manager.mark_trade_executed("BTCUSDT", "1h", box1, trade_id="TRADE_GRP_1")

        # Group 2: 110 - 115 (Separate H1 Demand, not overlapping Group 1)
        box2 = {"text": "TJL2 (Demand)", "top": 115.0, "bottom": 110.0, "left": 2000, "is_bullish": True}
        lvl2 = self.manager.register_or_update_box("BTCUSDT", "1h", box2)
        # Group 2 is active
        self.assertTrue(self.manager.is_box_tradable("BTCUSDT", "1h", box2)[0])

        # New level bridges the gap: 104 - 111 (overlaps both Group 1 in 104-105 and Group 2 in 110-111)
        box_bridge = {"text": "QML (Demand)", "top": 111.0, "bottom": 104.0, "left": 3000, "is_bullish": True}
        lvl_bridge = self.manager.register_or_update_box("BTCUSDT", "15m", box_bridge)

        # Because the groups merged with a consumed component, the merged group MUST remain CONSUMED
        self.assertTrue(lvl_bridge.consumed)
        self.assertFalse(self.manager.is_box_tradable("BTCUSDT", "15m", box_bridge)[0])
        self.assertFalse(self.manager.is_box_tradable("BTCUSDT", "1h", box2)[0])


if __name__ == "__main__":
    unittest.main()
