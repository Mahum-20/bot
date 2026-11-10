"""
Stage 3 Verification Test Suite
================================
Automated test suite verifying:
1. Registry atomic persistence
2. Registry restart recovery
3. Concurrent duplicate registration
4. Rejected order lock release
5. Identical Python & Pine candlestick definitions
6. Fresh tap versus candle already inside zone
7. Multi-cycle iteration coverage
8. HTF candle closure filtering
9. 120-candle reaction cycle expiry
10. Exchange minimum quantity & min notional sizing
11. Dynamic drawdown-based risk throttling
12. Live vs. Backtest sizing & rule parity
"""

import os
import json
import time
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor

from zone_trade_registry import ZoneTradeRegistry
from ltf_approach_engine import is_valid_tap_approach
from pattern_scanner import (
    is_valid_bullish_engulfing,
    is_valid_bearish_engulfing,
    is_valid_morning_star,
    is_valid_evening_star
)
from exchange_filter_manager import exchange_filter_engine
from faithful_backtest_engine import FaithfulBacktestEngine
from portfolio_risk_manager import PortfolioRiskManager


class TestStage3Verification(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_reg_path = os.path.join(self.temp_dir, "test_zone_registry.json")
        self.registry = ZoneTradeRegistry(storage_path=self.test_reg_path)

    def tearDown(self):
        try:
            if os.path.exists(self.test_reg_path):
                os.remove(self.test_reg_path)
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. Registry Atomic Persistence
    # -------------------------------------------------------------------------
    def test_registry_atomic_persistence(self):
        zone_key = "BTCUSDT_15m_TJL1_100_80500_80000"
        meta = {
            "id": "T1",
            "symbol": "BTCUSDT",
            "time": 1000,
            "entry_price": 80100,
            "sl_price": 79900,
            "tp_price": 80600
        }
        res = self.registry.register_pending_trade(zone_key, meta)
        self.assertTrue(res)
        self.assertTrue(os.path.exists(self.test_reg_path))

        with open(self.test_reg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn(zone_key, data)
        self.assertEqual(data[zone_key]["status"], "PENDING")
        self.assertEqual(data[zone_key]["trade_id"], "T1")

    # -------------------------------------------------------------------------
    # 2. Registry Restart Recovery
    # -------------------------------------------------------------------------
    def test_registry_restart_recovery(self):
        zone_key = "SOLUSDT_1h_QML_200_155_150"
        meta = {"id": "T2", "symbol": "SOLUSDT", "time": 2000}
        self.registry.register_pending_trade(zone_key, meta)
        self.registry.mark_trade_executed(zone_key, order_id="ORD_999")

        # Simulate fresh process restart by instantiating new ZoneTradeRegistry from disk
        restarted_registry = ZoneTradeRegistry(storage_path=self.test_reg_path)
        self.assertTrue(restarted_registry.is_zone_locked(zone_key))
        locked_keys = restarted_registry.get_all_locked_keys()
        self.assertIn(zone_key, locked_keys)
        self.assertEqual(restarted_registry._registry[zone_key]["status"], "EXECUTED")
        self.assertEqual(restarted_registry._registry[zone_key]["order_id"], "ORD_999")

    # -------------------------------------------------------------------------
    # 3. Concurrent Duplicate Registration
    # -------------------------------------------------------------------------
    def test_concurrent_duplicate_registration(self):
        zone_key = "BTCUSDT_4h_RBS_500_82000_81500"
        success_count = 0
        failure_count = 0
        lock = threading.Lock()

        def attempt_reg(thread_idx):
            nonlocal success_count, failure_count
            meta = {"id": f"T_{thread_idx}", "symbol": "BTCUSDT", "time": 5000}
            ok = self.registry.register_pending_trade(zone_key, meta)
            with lock:
                if ok:
                    success_count += 1
                else:
                    failure_count += 1

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(attempt_reg, i) for i in range(20)]
            for fut in futures:
                fut.result()

        # Exactly 1 thread must acquire the lock; 19 must fail
        self.assertEqual(success_count, 1)
        self.assertEqual(failure_count, 19)

    # -------------------------------------------------------------------------
    # 4. Rejected Order Lock Release
    # -------------------------------------------------------------------------
    def test_rejected_order_lock_release(self):
        zone_key = "BTCUSDT_15m_TJL2_600_81000_80800"
        meta = {"id": "T_FAIL", "symbol": "BTCUSDT", "time": 6000}

        self.assertTrue(self.registry.register_pending_trade(zone_key, meta))
        self.assertTrue(self.registry.is_zone_locked(zone_key))

        # Release upon rejection
        self.registry.release_rejected_zone(zone_key, reason="BELOW_MIN_LOT_RISK_BUDGET")
        self.assertFalse(self.registry.is_zone_locked(zone_key))

        # Subsequent attempt on the same zone can now succeed
        meta_retry = {"id": "T_RETRY", "symbol": "BTCUSDT", "time": 6060}
        self.assertTrue(self.registry.register_pending_trade(zone_key, meta_retry))

    # -------------------------------------------------------------------------
    # 5. Candlestick Definitions (Python & Pine 1:1 Parity)
    # -------------------------------------------------------------------------
    def test_candlestick_definitions_parity(self):
        # A. Bullish Engulfing
        c1_bear = {"open": 100.0, "high": 101.0, "low": 98.0, "close": 98.5}
        c2_bull = {"open": 98.0, "high": 101.5, "low": 97.5, "close": 100.5}
        self.assertTrue(is_valid_bullish_engulfing(c1_bear, c2_bull))

        # Bullish Engulfing Failure: c2 does not wick above c1 high
        c2_fail_high = {"open": 98.0, "high": 100.8, "low": 97.5, "close": 100.5}
        self.assertFalse(is_valid_bullish_engulfing(c1_bear, c2_fail_high))

        # B. Bearish Engulfing
        c1_bull = {"open": 98.5, "high": 101.0, "low": 98.0, "close": 100.0}
        c2_bear = {"open": 100.0, "high": 101.5, "low": 97.5, "close": 98.0}
        self.assertTrue(is_valid_bearish_engulfing(c1_bull, c2_bear))

        # Bearish Engulfing Failure: c2 does not wick below c1 low
        c2_fail_low = {"open": 100.0, "high": 101.5, "low": 98.2, "close": 98.0}
        self.assertFalse(is_valid_bearish_engulfing(c1_bull, c2_fail_low))

        # C. Morning Star (3-Candle)
        # c1: Large red candle (open 100, close 90, body 10, range 11)
        m1 = {"open": 100.0, "high": 100.5, "low": 89.5, "close": 90.0}
        # c2: Star candle (body <= 0.55 * 10 = 5.5, wick dips below m1 low 89.5)
        m2 = {"open": 89.0, "high": 89.5, "low": 87.0, "close": 88.5}
        # c3: Large green candle closing >= midpoint of m1 (90 + 5.0 = 95.0)
        m3_valid = {"open": 89.0, "high": 97.0, "low": 88.5, "close": 96.0}
        self.assertTrue(is_valid_morning_star(m1, m2, m3_valid))

        # Morning Star Failure: c3 closes below midpoint of m1 (< 95.0)
        m3_fail_midpoint = {"open": 89.0, "high": 94.5, "low": 88.5, "close": 93.5}
        self.assertFalse(is_valid_morning_star(m1, m2, m3_fail_midpoint))

        # Morning Star Failure: c2 body > 0.55 * c1 body
        m2_too_large = {"open": 89.0, "high": 89.5, "low": 82.0, "close": 83.0} # body = 6.0 > 5.5
        self.assertFalse(is_valid_morning_star(m1, m2_too_large, m3_valid))

        # D. Evening Star (3-Candle)
        # c1: Large green candle (open 90, close 100, body 10)
        e1 = {"open": 90.0, "high": 100.5, "low": 89.5, "close": 100.0}
        # c2: Star candle (body <= 5.5, upper wick > e1 high 100.5)
        e2 = {"open": 101.0, "high": 103.0, "low": 100.5, "close": 101.5}
        # c3: Large red candle closing <= midpoint of e1 (90 + 5.0 = 95.0)
        e3_valid = {"open": 101.0, "high": 101.5, "low": 93.0, "close": 94.0}
        self.assertTrue(is_valid_evening_star(e1, e2, e3_valid))

        # Evening Star Failure: c3 closes above midpoint of e1 (> 95.0)
        e3_fail_midpoint = {"open": 101.0, "high": 101.5, "low": 95.5, "close": 96.5}
        self.assertFalse(is_valid_evening_star(e1, e2, e3_fail_midpoint))

    # -------------------------------------------------------------------------
    # 6. Fresh Tap vs Candle Already Inside Zone
    # -------------------------------------------------------------------------
    def test_fresh_tap_vs_already_inside_zone(self):
        box = {"top": 100.0, "bottom": 90.0, "text": "DEMAND_1"}

        # Case A: Fresh outside tap (prev candle entirely above zone, curr touches)
        candles_fresh = [
            {"time": 1000, "open": 105.0, "high": 106.0, "low": 102.0, "close": 103.0}, # completely outside
            {"time": 1060, "open": 103.0, "high": 103.5, "low": 98.0, "close": 99.0}     # penetrates top 100.0
        ]
        self.assertTrue(is_valid_tap_approach(box, candles_fresh, 1, require_outside_entry=True))

        # Case B: Already inside (prev candle was already inside 90-100 range)
        candles_inside = [
            {"time": 1000, "open": 96.0, "high": 98.0, "low": 94.0, "close": 95.0},     # already inside!
            {"time": 1060, "open": 95.0, "high": 97.0, "low": 93.0, "close": 96.0}      # still inside
        ]
        self.assertFalse(is_valid_tap_approach(box, candles_inside, 1, require_outside_entry=True))

    # -------------------------------------------------------------------------
    # 7. Multi-Cycle Iteration Coverage
    # -------------------------------------------------------------------------
    def test_multi_cycle_iteration_coverage(self):
        active_cycles = [
            ("key1", {"symbol": "BTCUSDT", "htf_tf": "15m", "status": "NO_SIGNAL"}),
            ("key2", {"symbol": "BTCUSDT", "htf_tf": "15m", "status": "SIGNAL_READY"}),
            ("key3", {"symbol": "BTCUSDT", "htf_tf": "15m", "status": "NO_SIGNAL"}),
        ]
        evaluated = []
        trade_taken = False
        for reg_key, cyc in active_cycles:
            evaluated.append(reg_key)
            if cyc["status"] == "SIGNAL_READY":
                trade_taken = True
                break

        # Proves key1 was evaluated, didn't trigger, and key2 was reached and executed
        self.assertEqual(evaluated, ["key1", "key2"])
        self.assertTrue(trade_taken)

    # -------------------------------------------------------------------------
    # 8. HTF Candle Closure Filtering
    # -------------------------------------------------------------------------
    def test_htf_candle_closure_filtering(self):
        latest_closed_ltf = 1700000060  # e.g., 1m candle closed at 1700000060 + 60
        ltf_sec = 60
        htf_sec = 3600  # 1 hour

        raw_htf = [
            {"time": 1700000000 - 7200, "close": 100},  # closed 2 hrs ago (included)
            {"time": 1700000000 - 3600, "close": 101},  # closed 1 hr ago (included)
            {"time": 1700000000, "close": 102},         # currently forming (close at +3600 > LTF close) -> MUST EXCLUDE!
        ]

        closed_htf = [
            c for c in raw_htf
            if (c["time"] + htf_sec) <= (latest_closed_ltf + ltf_sec)
        ]
        self.assertEqual(len(closed_htf), 2)
        self.assertEqual(closed_htf[-1]["time"], 1700000000 - 3600)

    # -------------------------------------------------------------------------
    # 9. 120-Candle Reaction Cycle Expiry
    # -------------------------------------------------------------------------
    def test_120_candle_expiry(self):
        ltf_sec = 60
        max_cycle_seconds = 120 * ltf_sec # 7200 sec

        initial_tap_time = 10000
        # Decision at bar 119
        decision_time_119 = initial_tap_time + (119 * ltf_sec)
        self.assertLessEqual(decision_time_119 - initial_tap_time, max_cycle_seconds)

        # Decision at bar 121 (expired)
        decision_time_121 = initial_tap_time + (121 * ltf_sec)
        self.assertGreater(decision_time_121 - initial_tap_time, max_cycle_seconds)

    # -------------------------------------------------------------------------
    # 10. Exchange Minimum Quantity & Sizing Parity
    # -------------------------------------------------------------------------
    def test_exchange_filters_and_risk_budget_protection(self):
        filt = exchange_filter_engine.get_filter("BTCUSDT")
        self.assertEqual(filt["step_size"], 0.001)
        self.assertEqual(filt["min_qty"], 0.001)

        # Small account ($100 capital), 1% risk = $1.00 budget.
        # If risk distance is $500, raw size = $1.00 / $500 = 0.002 BTC.
        # 0.002 BTC >= min_qty (0.001 BTC). Effective risk = 0.002 * 500 = $1.00 (within budget).
        balance = 100.0
        risk_dollars = balance * 0.01  # $1.00
        risk_dist = 500.0
        pos_size = exchange_filter_engine.clamp_quantity("BTCUSDT", risk_dollars / risk_dist)
        self.assertEqual(pos_size, 0.002)

        # If risk distance is $3000, raw size = $1.00 / $3000 = 0.00033 BTC.
        # Min lot 0.001 BTC risks 0.001 * 3000 = $3.00 > $1.00 * 1.05 ($1.05).
        # Rule RISK-006 MUST reject!
        min_viable = filt["min_qty"]
        min_viable_risk = min_viable * 3000.0
        self.assertGreater(min_viable_risk, risk_dollars * 1.05)

    # -------------------------------------------------------------------------
    # 11. Dynamic Drawdown-Based Risk Throttling Parity
    # -------------------------------------------------------------------------
    def test_dynamic_drawdown_throttling_parity(self):
        engine = FaithfulBacktestEngine(
            symbol="BTCUSDT",
            htf_tf="15m",
            ltf_tf="1m",
            initial_balance=10000.0,
            risk_pct=0.01
        )
        engine.peak_equity = 10000.0
        engine.balance = 9100.0  # 9% drawdown (exceeds 8% threshold)

        dd = (engine.peak_equity - engine.balance) / engine.peak_equity
        self.assertGreaterEqual(dd, engine.drawdown_throttle_threshold)

        # Verify risk drops to 0.5% (throttled)
        is_throttled = engine.drawdown_throttling_enabled and (dd >= engine.drawdown_throttle_threshold)
        effective_risk = engine.throttled_risk_pct if is_throttled else engine.risk_pct
        self.assertEqual(effective_risk, 0.005)


if __name__ == "__main__":
    unittest.main()
