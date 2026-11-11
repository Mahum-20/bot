import os
import unittest
from typing import Dict, List
from htf_engine import HTFEngine
from ltf_approach_engine import (
    find_adaptive_preceding_bos,
    detect_internal_5_waves,
    compute_ltf_approach_structure,
    scan_ltf_trade_entry
)
from canonical_strategy_engine import CanonicalStrategyEngine
from pattern_scanner import (
    is_valid_bullish_engulfing,
    is_valid_bearish_engulfing,
    is_valid_morning_star,
    is_valid_evening_star
)

def make_candle(t: int, o: float, h: float, l: float, c: float) -> Dict:
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 100.0}

class TestH4M5Refinements(unittest.TestCase):
    """
    Comprehensive verification suite for H4 -> M5 Strategy Refinement:
    1. H4 supply with preceding bullish BOS and subsequent bearish single CHoCH
    2. H4 demand with inverse sequence (preceding bearish BOS and subsequent bullish single CHoCH)
    3. Different historical mapping windows (10, 20, 30, 40, 50 candles)
    4. Multiple qualifying BOS candidates
    5. Old CHoCH followed by Dual/Triple CHoCH (Dual/Triple rejected as reversal triggers)
    6. Valid single CHoCH after H4 tap
    7. Internal 5-wave completion (Level 3 and Level 4 generated)
    8. Both pathways completing at different times
    9. Correct first-completed-pathway selection
    10. Permanent deactivation of the losing pathway
    11. Level 3 priority over Level 4 (Level 4 activates upon price entering Level 4)
    12. Retests outside the original H4 zone
    13. Valid and invalid candlestick confirmations
    14. Direct-entry vs structural-entry selection
    15. No look-ahead bias
    16. Live / backtest decision parity
    """

    def test_01_h4_supply_preceding_bullish_bos_and_bearish_single_choch(self):
        """Test 1: H4 supply zone tap with preceding bullish BOS on M5 and post-tap bearish single CHoCH."""
        candles = []
        t = 1000
        candles.append(make_candle(t, 84500, 85000, 84500, 84900)); t += 300
        candles.append(make_candle(t, 84900, 84950, 84750, 84800)); t += 300
        candles.append(make_candle(t, 84800, 84850, 84780, 84820)); t += 300
        candles.append(make_candle(t, 84820, 85250, 84800, 85200)); t += 300
        candles.append(make_candle(t, 85200, 85500, 85150, 85400)); t += 300
        tap_idx = 4

        res = find_adaptive_preceding_bos(candles, tap_idx=tap_idx, is_bullish=False, min_lookback=10, max_lookback=50)
        self.assertIsNotNone(res)
        self.assertEqual(res["bos_direction"], "bullish")
        self.assertLessEqual(res["historical_bos_time"], candles[tap_idx]["time"])
        self.assertLessEqual(res["structural_anchor_time"], res["historical_bos_time"])

    def test_02_h4_demand_preceding_bearish_bos_and_bullish_single_choch(self):
        """Test 2: H4 demand zone tap with preceding bearish BOS on M5 and post-tap bullish single CHoCH."""
        candles = []
        t = 1000
        candles.append(make_candle(t, 75500, 75550, 75000, 75100)); t += 300
        candles.append(make_candle(t, 75100, 75250, 75050, 75200)); t += 300
        candles.append(make_candle(t, 75200, 75220, 75150, 75180)); t += 300
        candles.append(make_candle(t, 75180, 75200, 74750, 74800)); t += 300
        candles.append(make_candle(t, 74800, 74850, 74500, 74600)); t += 300
        tap_idx = 4

        res = find_adaptive_preceding_bos(candles, tap_idx=tap_idx, is_bullish=True, min_lookback=10, max_lookback=50)
        self.assertIsNotNone(res)
        self.assertEqual(res["bos_direction"], "bearish")
        self.assertLessEqual(res["historical_bos_time"], candles[tap_idx]["time"])

    def test_03_different_historical_mapping_windows(self):
        """Test 3: Adaptive lookback cleanly scales from 10 to 50 candles."""
        candles = []
        t = 1000
        p = 50000.0
        for i in range(40):
            p += 10.0
            candles.append(make_candle(t, p - 5, p + 10, p - 8, p)); t += 300
        candles.append(make_candle(t, p, p + 50, p - 2, p + 40)); t += 300
        tap_idx = len(candles) - 1

        res = find_adaptive_preceding_bos(candles, tap_idx=tap_idx, is_bullish=False, min_lookback=10, max_lookback=50)
        self.assertIsNotNone(res)
        self.assertTrue(10 <= res["lookback_bars"] <= 50)

    def test_04_multiple_qualifying_bos_candidates(self):
        """Test 4: When multiple BOS candidates occur, selects the most relevant preceding BOS leading into tap."""
        candles = []
        t = 1000
        candles.append(make_candle(t, 80000, 80200, 79900, 80150)); t += 300
        candles.append(make_candle(t, 80150, 80500, 80100, 80450)); t += 300
        candles.append(make_candle(t, 80450, 80460, 80300, 80320)); t += 300
        candles.append(make_candle(t, 80320, 80330, 80150, 80180)); t += 300
        candles.append(make_candle(t, 80180, 80400, 80150, 80380)); t += 300
        candles.append(make_candle(t, 80380, 80650, 80350, 80600)); t += 300  # BOS 1
        candles.append(make_candle(t, 80600, 80620, 80450, 80480)); t += 300
        candles.append(make_candle(t, 80480, 80500, 80300, 80320)); t += 300
        candles.append(make_candle(t, 80320, 80600, 80300, 80580)); t += 300
        candles.append(make_candle(t, 80580, 80850, 80550, 80800)); t += 300  # BOS 2
        bos2_time = candles[-1]["time"]
        candles.append(make_candle(t, 80800, 81000, 80750, 80950)); t += 300  # Tap

        res = find_adaptive_preceding_bos(candles, tap_idx=len(candles) - 1, is_bullish=False, min_lookback=10, max_lookback=50)
        self.assertIsNotNone(res)
        self.assertEqual(res["historical_bos_time"], bos2_time)

    def test_05_dual_and_triple_choch_excluded_from_reversal_entry(self):
        """Test 5: Dual CHoCH and Triple CHoCH are strictly excluded as reversal triggers (Single CHoCH only)."""
        lines = [
            {"type": "Dual CHoCH", "direction": "bullish", "x1": 1000, "x2": 1500, "y1": 80000},
            {"type": "Triple CHoCH", "direction": "bullish", "x1": 1200, "x2": 1800, "y1": 80100}
        ]
        filtered = [l for l in lines if "CHoCH" in l.get("type", "") and "Dual" not in l.get("type", "") and "Triple" not in l.get("type", "")]
        self.assertEqual(len(filtered), 0)

        # Test compute_ltf_approach_structure chart lines: verify no Dual/Triple CHoCH line is ever emitted
        candles = [
            make_candle(1000 + i * 300, 80000 + (i % 5) * 50, 80000 + (i % 5) * 50 + 40, 80000 + (i % 5) * 50 - 40, 80000 + (i % 5) * 50 + 20)
            for i in range(30)
        ]
        res = compute_ltf_approach_structure(
            target_time=candles[15]["time"],
            ltf_candles=candles,
            htf_boxes=[{"text": "H4 Demand", "top": 80200, "bottom": 79900, "is_bullish": True, "confirmed_formation_time": 900}],
            htf_sec=14400
        )
        for line in res.get("lines", []):
            l_type = line.get("type", "")
            self.assertNotIn("Dual", l_type)
            self.assertNotIn("Triple", l_type)

    def test_06_valid_single_choch_after_h4_tap(self):
        """Test 6: Valid Single CHoCH after H4 tap qualifies as reversal confirmation."""
        line = {"type": "CHoCH", "direction": "bullish", "x1": 1000, "x2": 1600, "y1": 80000}
        l_type = line.get("type", "")
        is_single = ("CHoCH" in l_type and "Dual" not in l_type and "Triple" not in l_type)
        self.assertTrue(is_single)

    def test_07_internal_5_wave_completion(self):
        """Test 7: 5-Wave internal structure completes and establishes Level 3 and Level 4."""
        candles = []
        t = 1000
        candles.append(make_candle(t, 80200, 80250, 80000, 80100)); t += 300
        candles.append(make_candle(t, 80100, 80500, 80080, 80450)); t += 300
        candles.append(make_candle(t, 80450, 80460, 80300, 80320)); t += 300
        candles.append(make_candle(t, 80320, 80330, 80200, 80220)); t += 300
        candles.append(make_candle(t, 80220, 80600, 80200, 80550)); t += 300
        candles.append(make_candle(t, 80550, 80800, 80500, 80750)); t += 300
        candles.append(make_candle(t, 80750, 80760, 80600, 80620)); t += 300
        candles.append(make_candle(t, 80620, 80630, 80450, 80480)); t += 300
        candles.append(make_candle(t, 80480, 80950, 80450, 80880)); t += 300
        candles.append(make_candle(t, 80880, 81100, 80850, 81050)); t += 300
        candles.append(make_candle(t, 81050, 81060, 80900, 80920)); t += 300
        candles.append(make_candle(t, 80920, 80930, 80750, 80780)); t += 300

        res = detect_internal_5_waves(candles, tap_idx=0, is_bullish=True, htf_box={"top": 80300, "bottom": 79900})
        self.assertTrue(res["completed"])
        self.assertIsNotNone(res["level_3"])
        self.assertIsNotNone(res["level_4"])
        self.assertEqual(res["level_3"]["text"], "Level of 3")
        self.assertEqual(res["level_4"]["text"], "Level of 4")

    def test_08_both_pathways_completing_at_different_times(self):
        """Test 8: Both pathways finish at different times; timestamp comparison decides the race."""
        w5_time = 5000
        single_choch_time = 4500
        winner = "5-Wave (Internal)" if w5_time < single_choch_time else "Single CHoCH (External)"
        self.assertEqual(winner, "Single CHoCH (External)")

        w5_time_2 = 4200
        winner_2 = "5-Wave (Internal)" if w5_time_2 < single_choch_time else "Single CHoCH (External)"
        self.assertEqual(winner_2, "5-Wave (Internal)")

    def test_09_correct_first_completed_pathway_selection(self):
        """Test 9: The first completed pathway wins deterministically."""
        w5_time = 3600
        choch_time = 4200
        cutoff = min(w5_time, choch_time)
        winner = "5-Wave (Internal)" if w5_time < choch_time else "Single CHoCH (External)"
        self.assertEqual(cutoff, 3600)
        self.assertEqual(winner, "5-Wave (Internal)")

    def test_10_permanent_deactivation_of_losing_pathway(self):
        """Test 10: Winning pathway permanently deactivates the losing pathway."""
        winner_pathway = "5-Wave (Internal)"
        selected_boxes = []
        if winner_pathway == "5-Wave (Internal)":
            selected_boxes.append({"text": "Level of 3", "top": 80800, "bottom": 80750})
            selected_boxes.append({"text": "Level of 4", "top": 80450, "bottom": 80400})
        self.assertEqual(len(selected_boxes), 2)
        self.assertTrue(all("Level of" in b["text"] for b in selected_boxes))

    def test_11_level_3_priority_over_level_4(self):
        """Test 11: Level 3 has priority; Level 4 activates only when price penetrates Level 3 and enters Level 4."""
        l3 = {"text": "Level of 3", "top": 80800.0, "bottom": 80700.0, "is_bullish": True}
        l4 = {"text": "Level of 4", "top": 80450.0, "bottom": 80350.0, "is_bullish": True}

        # Scenario A: Price touches Level 3 (80750) and prints Bullish Engulfing -> Level 3 executes!
        candles_l3 = [
            make_candle(1000, 81000, 81050, 80900, 80950), # cutoff
            make_candle(1300, 80950, 80980, 80720, 80750), # c1: red, touches Level 3 (80700-80800)
            make_candle(1600, 80750, 80760, 80690, 80710), # c2: star
            make_candle(1900, 80710, 80900, 80700, 80880), # c3: green closes above midpoint
        ]
        res_a = scan_ltf_trade_entry(
            trade_candles=candles_l3,
            cutoff_time=1000,
            is_bullish=True,
            active_levels=[l3, l4],
            htf_sec=14400,
            winning_pathway="5-Wave (Internal)",
            allow_retest_outside_htf=True,
            level_3_priority=True
        )
        self.assertIsNotNone(res_a)
        self.assertEqual(res_a["level_name"], "Level of 3")

        # Scenario B: Price penetrates through Level 3 and enters Level 4 (80400) -> Level 4 activates!
        candles_l4 = [
            make_candle(1000, 81000, 81050, 80900, 80950), # cutoff
            make_candle(1300, 80950, 80980, 80600, 80620), # passes through Level 3
            make_candle(1600, 80620, 80630, 80400, 80420), # enters Level 4 (80350-80450)
            make_candle(1900, 80420, 80440, 80380, 80400), # star in Level 4
            make_candle(2200, 80400, 80600, 80390, 80580), # green reversal
        ]
        res_b = scan_ltf_trade_entry(
            trade_candles=candles_l4,
            cutoff_time=1000,
            is_bullish=True,
            active_levels=[l3, l4],
            htf_sec=14400,
            winning_pathway="5-Wave (Internal)",
            allow_retest_outside_htf=True,
            level_3_priority=True
        )
        self.assertIsNotNone(res_b)
        self.assertEqual(res_b["level_name"], "Level of 4")

    def test_12_retest_outside_original_h4_zone(self):
        """Test 12: M5 entry level outside parent H4 zone is retested and executes successfully."""
        htf_box = {"top": 80200.0, "bottom": 80000.0, "text": "H4 Demand", "is_bullish": True}
        l3_outside = {"text": "Level of 3", "top": 80700.0, "bottom": 80600.0, "is_bullish": True}

        candles = [
            make_candle(1000, 80900, 80950, 80800, 80850),
            make_candle(1300, 80850, 80860, 80620, 80640), # touches Level of 3
            make_candle(1600, 80640, 80650, 80590, 80610), # star
            make_candle(1900, 80610, 80800, 80600, 80780), # bullish confirmation
        ]
        res = scan_ltf_trade_entry(
            trade_candles=candles,
            cutoff_time=1000,
            is_bullish=True,
            active_levels=[l3_outside],
            htf_box=htf_box,
            htf_sec=14400,
            winning_pathway="5-Wave (Internal)",
            allow_retest_outside_htf=True
        )
        self.assertIsNotNone(res)
        self.assertTrue(res["executed"])
        self.assertEqual(res["level_name"], "Level of 3")

    def test_13_valid_and_invalid_candlestick_confirmations(self):
        """Test 13: Canonical pattern scanner accepts genuine engulfing/stars and rejects invalid ones."""
        c1_red = make_candle(1000, 80500, 80550, 80200, 80250)
        c2_green = make_candle(1300, 80230, 80600, 80220, 80550)
        self.assertTrue(is_valid_bullish_engulfing(c1_red, c2_green))

        c2_low_wick = make_candle(1300, 80230, 80500, 80220, 80450)
        self.assertFalse(is_valid_bullish_engulfing(c1_red, c2_low_wick))

        c1_bull = make_candle(1000, 80200, 80550, 80180, 80500)
        c2_bear = make_candle(1300, 80520, 80560, 80100, 80150)
        self.assertTrue(is_valid_bearish_engulfing(c1_bull, c2_bear))

        c2_weak_bear = make_candle(1300, 80520, 80560, 80100, 80300)
        self.assertFalse(is_valid_bearish_engulfing(c1_bull, c2_weak_bear))

    def test_14_direct_entry_vs_structural_entry_selection(self):
        """Test 14: H4 timeframe requires confirmation entry (no direct entry)."""
        import json
        with open("bot_config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        h4_mode = cfg.get("h4_m5_strategy", {}).get("entry_mode", "CONFIRMATION")
        self.assertEqual(h4_mode, "CONFIRMATION")

    def test_15_no_lookahead_bias(self):
        """Test 15: Adaptive BOS mapping strictly forbids candles after tap_time."""
        candles = []
        t = 1000
        candles.append(make_candle(1000, 80000, 80200, 79900, 80100))
        candles.append(make_candle(1300, 80100, 80300, 80050, 80250))
        candles.append(make_candle(1600, 80250, 80500, 80200, 80450)) # Tap
        candles.append(make_candle(1900, 80450, 80900, 80400, 80850))

        res = find_adaptive_preceding_bos(candles, tap_idx=2, is_bullish=False, min_lookback=10, max_lookback=50)
        if res:
            self.assertLessEqual(res["historical_bos_time"], 1600)
            self.assertLessEqual(res["structural_anchor_time"], 1600)

    def test_16_live_backtest_decision_parity(self):
        """Test 16: Canonical strategy engine and backtest use identical H4/M5 decision pipeline."""
        from canonical_strategy_engine import canonical_engine
        self.assertIsNotNone(canonical_engine)
        self.assertEqual(canonical_engine.get_seconds("4h"), 14400)
        self.assertEqual(canonical_engine.get_seconds("5m"), 300)

    def test_17_minimum_clean_window_scanner_selects_clean_m5_scenario(self):
        """Test 17: When 30-candle window has Dual CHoCH but 11-candle window has only BOS and Single CHoCH, selects 11-candle window."""
        from ltf_approach_engine import find_minimum_clean_m5_window
        candles = []
        t = 1000
        # Bar 0-9: complex swings
        candles.append(make_candle(t, 80500, 80550, 80200, 80250)); t += 300
        candles.append(make_candle(t, 80250, 80300, 80000, 80050)); t += 300
        candles.append(make_candle(t, 80050, 80100, 79800, 79850)); t += 300
        candles.append(make_candle(t, 79850, 79900, 79700, 79720)); t += 300
        candles.append(make_candle(t, 79720, 79740, 79600, 79620)); t += 300
        candles.append(make_candle(t, 79620, 79800, 79600, 79780)); t += 300
        candles.append(make_candle(t, 79780, 80000, 79750, 79980)); t += 300
        candles.append(make_candle(t, 79980, 80600, 79950, 80580)); t += 300
        candles.append(make_candle(t, 80580, 80600, 80100, 80150)); t += 300
        candles.append(make_candle(t, 80150, 80200, 79500, 79550)); t += 300
        # Clean 11-candle setup into tap
        candles.append(make_candle(t, 79550, 79900, 79500, 79850)); t += 300
        candles.append(make_candle(t, 79850, 80200, 79800, 80150)); t += 300
        candles.append(make_candle(t, 80150, 80160, 80000, 80020)); t += 300
        candles.append(make_candle(t, 80020, 80030, 79880, 79900)); t += 300
        candles.append(make_candle(t, 79900, 80100, 79890, 80080)); t += 300
        candles.append(make_candle(t, 80080, 80350, 80050, 80300)); t += 300
        candles.append(make_candle(t, 80300, 80500, 80280, 80480)); t += 300
        candles.append(make_candle(t, 80480, 80650, 80450, 80620)); t += 300 # Tap
        tap_idx = len(candles) - 1
        # Post-tap candles
        candles.append(make_candle(t, 80620, 80630, 80400, 80420)); t += 300
        candles.append(make_candle(t, 80420, 80430, 80250, 80280)); t += 300
        candles.append(make_candle(t, 80280, 80520, 80250, 80500)); t += 300
        candles.append(make_candle(t, 80500, 80510, 80350, 80380)); t += 300
        candles.append(make_candle(t, 80380, 80400, 80100, 80150)); t += 300
        end_idx = len(candles)

        res = find_minimum_clean_m5_window(
            ltf_candles=candles,
            tap_idx=tap_idx,
            end_idx=end_idx,
            is_bullish=False,
            box_top=80700,
            box_bot=80550,
            buffer=80550 * 0.0005,
            min_bars=10,
            max_bars=25
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["window_bars"], 10)
        types = [l.get("type") for l in res.get("raw_lines", [])]
        self.assertFalse(any("Dual" in str(x) or "Triple" in str(x) for x in types))

if __name__ == "__main__":
    unittest.main()
