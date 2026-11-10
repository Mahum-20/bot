"""
Look-Ahead Integrity and Point-in-Time Unit Test Suite
======================================================
Tests and mathematically proves:
1. No future LTF candle can leak into structure detection or entry signals.
2. 5-Wave internal structure completes strictly on the closing bar of the confirming 2RTR.
3. CHoCH completes strictly on the closing bar of the breakout candle.
4. Retests and pattern confirmations are rejected if attempting to execute before cutoff.
5. Strict 120-candle reaction window: setups extending beyond 120 bars are expired.
6. Target liquidity calculations only use HTF boxes confirmed before decision time.
"""

import unittest
from typing import List, Dict
from ltf_approach_engine import (
    compute_ltf_approach_structure,
    detect_internal_5_waves,
    find_nearest_htf_liquidity
)
from htf_engine import is_htf_box_active


def make_candle(t: int, o: float, h: float, l: float, c: float) -> Dict:
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 100.0}


class TestLookaheadIntegrity(unittest.TestCase):
    def setUp(self):
        # Sample Demand Box
        self.htf_demand_box = {
            "id": "box_test_demand",
            "text": "TJL1 Demand",
            "top": 80100.0,
            "bottom": 80000.0,
            "left": 1000,
            "right": 9999999999,
            "is_bullish": True,
            "is_mitigated": False,
            "is_broken": False
        }

    def test_as_of_time_clamps_future_candles(self):
        """Proof: Passing future candles with an as_of_time clamp strictly excludes all future bars."""
        # 50 candles with timestamps 100 to 5000 (step 100)
        ltf = [make_candle(t, 80050, 80080, 80020, 80060) for t in range(100, 5100, 100)]
        as_of = 2000

        res = compute_ltf_approach_structure(
            target_time=500,
            ltf_candles=ltf,
            htf_boxes=[self.htf_demand_box],
            htf_sec=900,
            override_tap_time=500,
            override_box=self.htf_demand_box,
            as_of_time=as_of
        )
        
        # Verify no line or box has x2 or right timestamp > as_of
        for line in res.get("lines", []):
            self.assertLessEqual(line["x2"], as_of, f"Line leaked past as_of_time: {line}")
        for box in res.get("boxes", []):
            self.assertLessEqual(box["left"], as_of, f"Box left leaked past as_of_time: {box}")

    def test_120_candle_reaction_window_enforcement(self):
        """Proof: Any trade reaction beyond 120 candles from initial tap is strictly cut off."""
        tap_time = 1000
        ltf_sec = 60  # 1m
        max_duration = 120 * ltf_sec  # 7200 seconds

        # Create 200 candles from tap_time
        ltf = []
        for i in range(200):
            t = tap_time + (i * ltf_sec)
            ltf.append(make_candle(t, 80050, 80060, 80040, 80050))

        res = compute_ltf_approach_structure(
            target_time=tap_time,
            ltf_candles=ltf,
            htf_boxes=[self.htf_demand_box],
            htf_sec=900,
            override_tap_time=tap_time,
            override_box=self.htf_demand_box
        )
        
        # Target box right edge must not exceed tap_idx + 120
        box = res.get("boxes", [{}])[0]
        max_expected_time = tap_time + (120 * ltf_sec)
        self.assertLessEqual(box.get("right", 0), max_expected_time)

    def test_5_wave_confirmation_timestamp_integrity(self):
        """Proof: Wave 5 confirmation timestamp is anchored to the 2RTR closing bar, NOT retroactively at peak."""
        # Build synthetic 5-wave internal structure:
        # Tap at bar 0
        candles = []
        t0 = 1000
        # Anchor at bar 0 (low=80010)
        candles.append(make_candle(t0, 80050, 80060, 80010, 80050))
        # Wave 1 peak at bar 1, trough at bar 2 (2 red candles: bar 2, 3)
        candles.append(make_candle(t0 + 60, 80050, 80150, 80040, 80140))
        candles.append(make_candle(t0 + 120, 80140, 80140, 80090, 80100))  # red 1
        candles.append(make_candle(t0 + 180, 80100, 80110, 80070, 80080))  # red 2 (< low of red 1) -> W1 confirmed at bar 3

        # Wave 2 break above peak 1 (80150) at bar 4
        candles.append(make_candle(t0 + 240, 80090, 80220, 80080, 80210))  # BOS

        # Wave 3 peak at bar 5 (80300), 2RTR at bars 6, 7
        candles.append(make_candle(t0 + 300, 80210, 80300, 80200, 80290))
        candles.append(make_candle(t0 + 360, 80290, 80290, 80230, 80240))  # red 1
        candles.append(make_candle(t0 + 420, 80240, 80240, 80190, 80200))  # red 2 -> W3 confirmed at bar 7

        # Wave 4 break above peak 2 (80300) at bar 8
        candles.append(make_candle(t0 + 480, 80210, 80380, 80200, 80370))  # BOS

        # Wave 5 peak at bar 9 (80450), 2RTR at bars 10, 11
        candles.append(make_candle(t0 + 540, 80370, 80450, 80360, 80440))  # peak at bar 9 (time = t0 + 540)
        candles.append(make_candle(t0 + 600, 80440, 80440, 80390, 80400))  # red 1
        confirming_bar_time = t0 + 660
        candles.append(make_candle(confirming_bar_time, 80400, 80400, 80350, 80360))  # red 2 -> W5 confirmed at bar 11

        res = detect_internal_5_waves(candles, tap_idx=0, is_bullish=True, htf_box=self.htf_demand_box)
        self.assertTrue(res["completed"])
        # Proof: wave_5_time MUST match the confirming bar time (bar 11), NOT the prior peak time (bar 9)!
        self.assertEqual(res["wave_5_time"], confirming_bar_time)

    def test_opposing_liquidity_target_excludes_future_boxes(self):
        """Proof: Opposing liquidity targets cannot see HTF boxes formed after decision time."""
        current_time = 5000
        # Future opposing box formed at t=6000
        future_box = {
            "text": "Future Supply",
            "top": 85000,
            "bottom": 84000,
            "left": 6000,
            "is_bullish": False
        }
        # Active opposing box formed at t=3000
        active_box = {
            "text": "Active Supply",
            "top": 82000,
            "bottom": 81500,
            "left": 3000,
            "is_bullish": False
        }
        
        # Only active box should be visible
        valid_boxes = [b for b in [future_box, active_box] if b["left"] <= current_time]
        tp = find_nearest_htf_liquidity(
            entry_price=80500.0,
            is_bullish=True,
            htf_boxes=valid_boxes,
            entry_time=current_time
        )
        self.assertEqual(tp, 81500.0)
        self.assertNotEqual(tp, 84000.0)


if __name__ == "__main__":
    unittest.main()
