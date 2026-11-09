import bisect
from typing import List, Dict, Tuple, Optional
from htf_engine import HTFEngine
from ltf_engine import LTFEngine
from binance_feed import fetch_klines
from pattern_scanner import (
    is_valid_bullish_engulfing,
    is_valid_bearish_engulfing,
    is_valid_morning_star,
    is_valid_evening_star,
    is_non_doji
)

# ==============================================================================
# ENTRY LOGIC HOOK (Awaiting User Redefinition)
# ==============================================================================
# The previous entry logic (candlestick reversal patterns + 2-to-3 bar rolling
# extreme lag filter) has been dropped.
# 
# The Higher Timeframe Structure Mapping (BOS, CHoCH, Dual CHoCH, Swings,
# and TJL Supply & Demand levels) remains 100% active and intact.
#
# When you define your new entry logic, implement it inside `evaluate_new_entry` below.
# ==============================================================================

def evaluate_new_entry(
    zone: Dict,
    candle: Dict,
    bar_idx: int,
    candles_history: List[Dict],
    htf_candles: List[Dict] = None,
    htf_breaks: List[Dict] = None
) -> Optional[Dict]:
    """
    TopG Candlestick Reversal Confirmation at HTF Level:
    - Demand (BUY): Bullish Engulfing or Morning Star touching within/at the zone
    - Supply (SELL): Bearish Engulfing or Evening Star touching within/at the zone
    - Minimum R:R: 2.5
    """
    if bar_idx < 2 or not candles_history:
        return None

    is_bull = (zone.get("type", "").upper() == "BUY")
    z_top = zone.get("top", 0)
    z_bot = zone.get("bottom", 0)
    buffer = max(1.0, round(z_top * 0.0005, 2))

    prev_c = candles_history[bar_idx - 1]
    prev_2c = candles_history[bar_idx - 2] if bar_idx >= 2 else None

    # Check pattern and touch
    pattern_name = None
    extreme_p = None

    if is_bull:
        if is_valid_bullish_engulfing(prev_c, candle):
            # Must touch within or at demand zone
            if min(prev_c["low"], candle["low"]) <= z_top + buffer and max(prev_c["high"], candle["high"]) >= z_bot - buffer:
                pattern_name = "Bullish Engulfing"
                extreme_p = min(prev_c["low"], candle["low"])
        elif prev_2c and is_valid_morning_star(prev_2c, prev_c, candle):
            if min(prev_2c["low"], prev_c["low"], candle["low"]) <= z_top + buffer:
                pattern_name = "Morning Star"
                extreme_p = min(prev_2c["low"], prev_c["low"], candle["low"])
    else:
        if is_valid_bearish_engulfing(prev_c, candle):
            # Must touch within or at supply zone
            if max(prev_c["high"], candle["high"]) >= z_bot - buffer and min(prev_c["low"], candle["low"]) <= z_top + buffer:
                pattern_name = "Bearish Engulfing"
                extreme_p = max(prev_c["high"], candle["high"])
        elif prev_2c and is_valid_evening_star(prev_2c, prev_c, candle):
            if max(prev_2c["high"], prev_c["high"], candle["high"]) >= z_bot - buffer:
                pattern_name = "Evening Star"
                extreme_p = max(prev_2c["high"], prev_c["high"], candle["high"])

    if not pattern_name or extreme_p is None:
        return None

    entry_p = float(candle["close"])
    tick = max(0.1, round(entry_p * 0.0001, 2))
    sl_p = float(extreme_p - (2 * tick) if is_bull else extreme_p + (2 * tick))
    risk = abs(entry_p - sl_p)

    if risk <= 0:
        return None

    min_rr = 2.5
    reward = round(min_rr * risk, 2)
    tp_p = float(entry_p + reward if is_bull else entry_p - reward)

    return {
        "action": "BUY" if is_bull else "SELL",
        "entry_price": round(entry_p, 2),
        "sl_price": round(sl_p, 2),
        "tp_price": round(tp_p, 2),
        "pattern_name": pattern_name,
        "min_rr": min_rr
    }


class ZoneExecutionTracker:
    """
    Quantitative State Tracker for HTF Levels executing on LTF Candlesticks.
    Maintains zone touch detection, rolling extreme tracking, and zone lifecycle
    while keeping the HTF structure mapping fully intact.
    """
    def __init__(self, zone_id: str, zone_name: str, zone_type: str, top: float, bottom: float, min_rr: float = 2.5):
        self.zone_id = zone_id
        self.zone_name = zone_name
        self.zone_type = zone_type.upper()  # 'BUY' or 'SELL' strictly!
        self.top = max(top, bottom)
        self.bottom = min(top, bottom)
        self.min_rr = min_rr
        
        self.state = "FRESH"  # FRESH, INSIDE_ZONE, MITIGATED, EXPIRED, INVALIDATED, SL_HIT_REENTRY_AVAILABLE
        self.extreme_price = None
        self.extreme_bar_idx = None
        self.current_bar_count = 0
        self.has_triggered_initial = False
        self.has_triggered_reentry = False
        
        self.trade_history = []
        self.session_count = 0
        self.oscillation_count = 0
        self.session_start_idx = None
        self.session_trade_taken = False

    def is_touching(self, candle: Dict) -> bool:
        return candle["low"] <= self.top and candle["high"] >= self.bottom

    def evaluate_ltf_candle(self, 
                            candle: Dict, 
                            bar_idx: int, 
                            candles_history: List[Dict], 
                            htf_candles: List[Dict], 
                            htf_breaks: List[Dict]) -> Optional[Dict]:
        """
        Evaluates an LTF candle against this zone.
        Zone tracking and lifecycle remain active; entry logic is dispatched to evaluate_new_entry.
        """
        if self.state in ["MITIGATED", "EXPIRED", "INVALIDATED"]:
            return None

        touching = self.is_touching(candle)

        # 1. Zone Entry / Touch tracking
        if self.state in ["FRESH", "SL_HIT_REENTRY_AVAILABLE"] and touching:
            self.state = "INSIDE_ZONE"
            self.session_count += 1
            self.session_trade_taken = False
            self.session_start_idx = bar_idx
            self.extreme_price = candle["low"] if self.zone_type == "BUY" else candle["high"]
            self.extreme_bar_idx = bar_idx
            self.current_bar_count = 0

        elif self.state == "INSIDE_ZONE":
            if not touching:
                # Zone exit without trade
                if not self.session_trade_taken:
                    self.state = "MITIGATED"
                return None

            self.current_bar_count += 1
            if self.current_bar_count > 40:
                self.oscillation_count += 1
            if self.oscillation_count >= 2 or self.session_count >= 4:
                self.state = "INVALIDATED"
                return None

            # Track rolling extreme wick depth
            if self.zone_type == "BUY":
                if self.extreme_price is None or candle["low"] < self.extreme_price:
                    self.extreme_price = candle["low"]
                    self.extreme_bar_idx = bar_idx
            elif self.zone_type == "SELL":
                if self.extreme_price is None or candle["high"] > self.extreme_price:
                    self.extreme_price = candle["high"]
                    self.extreme_bar_idx = bar_idx

            # 2. Call new entry logic hook
            zone_info = {
                "id": self.zone_id,
                "name": self.zone_name,
                "type": self.zone_type,
                "top": self.top,
                "bottom": self.bottom,
                "extreme_price": self.extreme_price,
                "extreme_bar_idx": self.extreme_bar_idx,
                "current_bar_count": self.current_bar_count
            }
            entry_res = evaluate_new_entry(
                zone_info, candle, bar_idx, candles_history, htf_candles, htf_breaks
            )
            if entry_res:
                # Dispatches custom entry signal when redefined by user
                return self._build_execution_signal(
                    entry_res, candle, bar_idx, candles_history, htf_candles, htf_breaks
                )

        return None

    def _build_execution_signal(self,
                                entry_res: Dict,
                                candle: Dict,
                                bar_idx: int,
                                candles_history: List[Dict],
                                htf_candles: List[Dict],
                                htf_breaks: List[Dict]) -> Dict:
        """Helper to structure an executed signal when entry logic is defined."""
        self.session_trade_taken = True
        is_reentry = self.has_triggered_initial
        if not self.has_triggered_initial:
            self.has_triggered_initial = True
        else:
            self.has_triggered_reentry = True

        action_name = entry_res.get("action", self.zone_type)
        entry_price = entry_res.get("entry_price", candle["close"])
        sl_price = entry_res.get("sl_price", self.extreme_price)
        min_rr = entry_res.get("min_rr", self.min_rr)
        tp_price = entry_res.get("tp_price", entry_price + (abs(entry_price - sl_price) * min_rr))
        pattern_name = entry_res.get("pattern_name", "Custom Entry")

        h_idx = bisect.bisect_right([c["time"] for c in htf_candles], candle["time"]) - 1
        h_idx = max(0, min(h_idx, len(htf_candles) - 1))
        h_time = htf_candles[h_idx]["time"]

        marker = {
            "time": h_time,
            "position": "belowBar" if action_name == "BUY" else "aboveBar",
            "color": "#26a69a" if action_name == "BUY" else "#ef5350",
            "shape": "arrowUp" if action_name == "BUY" else "arrowDown",
            "text": f"{action_name} ({pattern_name})",
            "id": f"{action_name.lower()}_{self.zone_id}_{candle['time']}",
            "level": self.zone_name,
            "type": f"{action_name.capitalize()} ({pattern_name})",
            "entry": round(entry_price, 6),
            "sl": round(sl_price, 6),
            "tp": round(tp_price, 6),
            "is_reentry": is_reentry,
            "sub_time": candle["time"]
        }

        trade_info = {
            "id": f"sig_{self.zone_id}_{len(self.trade_history) + 1}",
            "type": action_name,
            "pattern": pattern_name,
            "is_reentry": is_reentry,
            "time": candle["time"],
            "entry": round(entry_price, 6),
            "sl": round(sl_price, 6),
            "tp": round(tp_price, 6),
            "price": round(entry_price, 6),
            "rr": min_rr,
            "outcome": "OPEN",
            "sim_close_idx": None,
            "sim_close_time": None
        }
        self.trade_history.append(trade_info)
        return {"marker": marker, "signal": trade_info, "sim_close_idx": None}


class MTFStrategy:
    """
    Multi-Timeframe Strategy Orchestrator.
    Maintains Higher Timeframe Structure Mapping (HTFEngine lookback=1000 bars,
    TJL boxes, BOS, CHoCH, swings, trend detection).
    Entry logic is dropped and decoupled, ready for user redefinition.
    """
    def __init__(self,
                 htf_interval: str = "4h",
                 ltf_interval: str = "5m",
                 market_type: str = "futures",
                 min_rr: float = 2.5):
        self.htf_interval = htf_interval
        self.ltf_interval = ltf_interval
        self.market_type = market_type
        self.min_rr = min_rr
        
        self.htf_engine = HTFEngine(lookback_bars=500, show_retracement_shapes=False, tjl_extend=True, box_width_bars=12, active_swing_length_bars=30)
        self.ltf_engine = LTFEngine(lookback_bars=500, use_wick_break=True, min_rr=min_rr, htf_tap_required=True, show_reversal_signals=False)

    @staticmethod
    def get_ltf_interval(htf_tf: str) -> Optional[str]:
        htf_tf = (htf_tf or "").lower()
        if htf_tf in ["15m", "m15"]:
            return "1m"
        elif htf_tf in ["1h", "h1"]:
            return "1m"
        elif htf_tf in ["4h", "h4"]:
            return "5m"
        return None

    @staticmethod
    def get_candle_duration_seconds(tf: str) -> int:
        tf = tf.lower()
        if tf.endswith("m"):
            return int(tf[:-1]) * 60
        elif tf.endswith("h"):
            return int(tf[:-1]) * 3600
        elif tf.endswith("d"):
            return int(tf[:-1]) * 86400
        return 14400

    def process_trading_framework(self, 
                                  htf_candles: List[Dict], 
                                  ltf_candles: List[Dict], 
                                  htf_boxes: List[Dict], 
                                  htf_lines: List[Dict]) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict]]:
        """
        Processes HTF Structure Boxes, proximity calculations, and active tracking.
        Entry logic is currently dropped awaiting redefinition.
        """
        if not htf_candles or not htf_boxes:
            return [], [], htf_boxes, []

        sorted_ltf = sorted(ltf_candles, key=lambda c: c["time"]) if ltf_candles else []
        ltf_times = [c["time"] for c in sorted_ltf]
        n_ltf = len(sorted_ltf)
        current_price = htf_candles[-1]["close"]

        # Extract all HTF structural break events (BOS, CHoCH, Dual CHoCH)
        htf_breaks = []
        for line in htf_lines:
            l_type = line.get("type", "")
            if l_type in ["BOS", "CHoCH", "Dual CHoCH"]:
                htf_breaks.append({
                    "time": line.get("x2", 0),
                    "type": l_type,
                    "id": line.get("id", "")
                })
        htf_breaks.sort(key=lambda b: b["time"])

        markers = []
        signals = []
        updated_boxes = []

        for box in htf_boxes:
            box_copy = dict(box)
            box_id = box_copy.get("id", str(box_copy.get("created_bar")))
            b_top = max(box_copy.get("top", 0), box_copy.get("bottom", 0))
            b_bot = min(box_copy.get("top", 0), box_copy.get("bottom", 0))
            is_bull_level = box_copy.get("is_bullish", True)
            box_name = box_copy.get("text", "Level")
            
            start_scan_bar = box_copy.get("active_start_bar", box_copy.get("created_bar", 0))
            if start_scan_bar < len(htf_candles):
                start_time = htf_candles[start_scan_bar]["time"]
            else:
                start_time = htf_candles[0]["time"]

            zone_type = "BUY" if is_bull_level else "SELL"
            tracker = ZoneExecutionTracker(
                zone_id=box_id,
                zone_name=box_name,
                zone_type=zone_type,
                top=b_top,
                bottom=b_bot,
                min_rr=self.min_rr
            )

            # Evaluate LTF candles if present (using the new hook)
            if sorted_ltf:
                cycles = box_copy.get("cycles", [])
                if cycles:
                    first_tap_bar = cycles[0].get("tap_bar", 0)
                    first_tap_time = htf_candles[first_tap_bar]["time"] if first_tap_bar < len(htf_candles) else start_time
                    if first_tap_time >= ltf_times[0]:
                        ltf_start_idx = bisect.bisect_left(ltf_times, max(start_time, first_tap_time - 3600))
                        i = max(0, ltf_start_idx - 2)
                        while i < n_ltf:
                            candle = sorted_ltf[i]
                            res = tracker.evaluate_ltf_candle(candle, i, sorted_ltf, htf_candles, htf_breaks)
                            if res:
                                markers.append(res["marker"])
                                signals.append(res["signal"])
                            i += 1
                elif box_copy.get("is_tapped", True):
                    ltf_start_idx = bisect.bisect_left(ltf_times, start_time)
                    i = ltf_start_idx
                    while i < n_ltf:
                        candle = sorted_ltf[i]
                        res = tracker.evaluate_ltf_candle(candle, i, sorted_ltf, htf_candles, htf_breaks)
                        if res:
                            markers.append(res["marker"])
                            signals.append(res["signal"])
                        i += 1

            # Maintain box visual styling and lifecycle
            box_copy["status"] = tracker.state
            box_copy["trade_count"] = len(tracker.trade_history)

            # Proximity calculation
            level_mid = (b_top + b_bot) / 2.0
            dist = abs(level_mid - current_price)
            box_copy["distance"] = round(dist, 2)
            box_copy["distance_pct"] = round((dist / current_price) * 100.0, 2)
            if b_bot > current_price:
                box_copy["position_type"] = "Above (Supply)"
            elif b_top < current_price:
                box_copy["position_type"] = "Below (Demand)"
            else:
                box_copy["position_type"] = "At Price (Inside Zone)"

            updated_boxes.append(box_copy)

        markers.sort(key=lambda m: m["time"])
        signals.sort(key=lambda s: s["time"])

        # Proximity Filter - Nearest unmitigated / active levels
        unmitigated_levels = [b for b in updated_boxes if b.get("status") in ["FRESH", "INSIDE_ZONE", "SL_HIT_REENTRY_AVAILABLE"]]
        unmitigated_levels.sort(key=lambda b: b.get("distance", float("inf")))
        nearby_levels = unmitigated_levels[:10]

        return markers, signals, updated_boxes, nearby_levels

    def run_strategy(self, htf_candles: List[Dict], ltf_candles: List[Dict] = None) -> Dict:
        """
        Executes complete Higher Timeframe Structure Mapping:
        - BOS (Break of Structure lines)
        - CHoCH (Change of Character lines)
        - Dual CHoCH & Triple CHoCH lines
        - Swings & Structure Labels
        - TJL Boxes (Supply & Demand levels)
        - Trend Direction (Bullish / Bearish / Neutral)
        """
        if not htf_candles:
            return {"lines": [], "labels": [], "boxes": [], "markers": [], "signals": [], "htf_trend": "Neutral", "ltf_trend": "Neutral"}

        htf_res = self.htf_engine.run(htf_candles)
        htf_boxes = htf_res.get("boxes", [])
        htf_lines = htf_res.get("lines", []) + htf_res.get("active_levels", [])
        htf_labels = htf_res.get("labels", [])

        markers, signals, updated_boxes, nearby_levels = self.process_trading_framework(
            htf_candles, ltf_candles, htf_boxes, htf_lines
        )

        return {
            "mode": "mtf",
            "htf_interval": self.htf_interval,
            "ltf_interval": self.ltf_interval,
            "htf_trend": htf_res.get("trend", "Neutral"),
            "ltf_trend": htf_res.get("trend", "Neutral"),
            "lines": htf_lines,
            "labels": htf_labels,
            "boxes": updated_boxes,
            "markers": markers,
            "signals": signals,
            "nearby_levels": nearby_levels,
            "htf_boxes_count": len(updated_boxes),
            "total_signals": len(markers)
        }

    def run_standalone_strategy(self, candles: List[Dict], ltf_candles: List[Dict] = None) -> Dict:
        return self.run_strategy(candles, ltf_candles)
