"""
Multi-Timeframe Strategy Orchestrator (Canonical Facade)
=========================================================
Unifies live execution, dashboard chart signaling, and backtesting under
the canonical TopG institutional methodology:
- 500-Candle Rolling FIFO Lookback (ZONE-003)
- Outside-In Zone Tap Detection (is_valid_tap_approach)
- 120-Candle Reaction Cycle State Machine (ZONE-004)
- Pure Price Action Reversal Confirmation (Engulfing, Morning/Evening Star)
- Institutional Risk-to-Reward Ratio (4H 3R | 1H/15M >= 2.5R Opposing Liquidity Target)
- Immutable 1-Trade-Per-Zone Registry Lock (RISK-003)
- Zero FVG Logic (Completely Decoupled)
"""

import bisect
from typing import List, Dict, Tuple, Optional, Any
from htf_engine import HTFEngine, is_htf_box_active
from ltf_approach_engine import is_valid_tap_approach, compute_ltf_approach_structure
from zone_trade_registry import zone_trade_registry


class ZoneExecutionTracker:
    """
    Tracks state and trade execution lifecycle for an individual HTF zone.
    Maintains backwards compatibility with dashboard inspection APIs.
    """
    def __init__(self,
                 zone_id: str,
                 zone_name: str,
                 zone_type: str,
                 top: float,
                 bottom: float,
                 min_rr: float = 3.0):
        self.zone_id = zone_id
        self.zone_name = zone_name
        self.zone_type = zone_type.upper()  # BUY or SELL
        self.top = max(top, bottom)
        self.bottom = min(top, bottom)
        self.min_rr = min_rr

        self.state = "FRESH"  # FRESH, INSIDE_ZONE, TRADED, INVALIDATED
        self.tap_time: Optional[int] = None
        self.trade_history: List[Dict] = []
        self.has_traded = False

    def check_tap(self, candle: Dict, candles_history: List[Dict], idx: int) -> bool:
        if self.has_traded:
            return False
        c_high = candle.get("high", 0.0)
        c_low = candle.get("low", 0.0)
        touching = (c_high >= self.bottom and c_low <= self.top)
        if touching and self.state == "FRESH":
            box_mock = {
                "top": self.top,
                "bottom": self.bottom,
                "is_bullish": (self.zone_type == "BUY")
            }
            if is_valid_tap_approach(box_mock, candles_history, idx):
                self.state = "INSIDE_ZONE"
                self.tap_time = candle.get("time")
                return True
        return False


class MTFStrategy:
    """
    Canonical Multi-Timeframe Strategy Orchestrator.
    Serves as the Single Source of Truth for:
    - Live background trading loop
    - Web dashboard chart markers & signals (/api/chart_signals)
    - Automated backtest verification
    """
    def __init__(self,
                 htf_interval: str = "4h",
                 ltf_interval: str = "5m",
                 market_type: str = "futures",
                 min_rr: float = 3.0):
        self.htf_interval = htf_interval
        self.ltf_interval = ltf_interval or self.get_ltf_interval(htf_interval) or "5m"
        self.market_type = market_type
        self.min_rr = min_rr

        # HTF Engine with 500-candle rolling lookback
        self.htf_engine = HTFEngine(
            lookback_bars=500,
            show_retracement_shapes=False,
            tjl_extend=True,
            box_width_bars=12,
            active_swing_length_bars=30
        )

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
        tf = (tf or "4h").lower()
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
        Executes canonical 120-candle reaction cycles and generates trade signals / chart markers.
        """
        if not htf_candles or not htf_boxes:
            return [], [], htf_boxes or [], []

        sorted_ltf = sorted(ltf_candles, key=lambda c: c["time"]) if ltf_candles else []
        n_ltf = len(sorted_ltf)
        current_time = htf_candles[-1]["time"]
        current_price = htf_candles[-1]["close"]
        ltf_sec = self.get_candle_duration_seconds(self.ltf_interval)
        htf_sec = self.get_candle_duration_seconds(self.htf_interval)
        max_cycle_seconds = 120 * ltf_sec

        markers: List[Dict] = []
        signals: List[Dict] = []
        updated_boxes: List[Dict] = []
        executed_zone_keys = set()

        for box in htf_boxes:
            box_copy = dict(box)
            b_top = max(box_copy.get("top", 0), box_copy.get("bottom", 0))
            b_bot = min(box_copy.get("top", 0), box_copy.get("bottom", 0))
            is_bull = box_copy.get("is_bullish", True)
            box_name = box_copy.get("text", "Level")
            box_left = box_copy.get("left", 0)

            # Immutable zone key (Rule RISK-003)
            b_id = f"{box_name}_{box_left}_{b_top:.2f}_{b_bot:.2f}"
            zone_key = b_id
            reg_key = zone_trade_registry.get_zone_key("BTCUSDT", self.htf_interval, b_id)

            # Check if box is active per 500-candle lookback and invalidation
            if not is_htf_box_active(box_copy, current_time, htf_sec):
                box_copy["status"] = "INVALIDATED"
                updated_boxes.append(box_copy)
                continue

            # Persistent 1-trade-per-zone lock check (Rule RISK-003)
            if zone_trade_registry.is_zone_locked(reg_key) or zone_key in executed_zone_keys:
                box_copy["status"] = "TRADED"
                box_copy["trade_count"] = 1
                updated_boxes.append(box_copy)
                continue

            # Evaluate reaction cycles on LTF candles via canonical compute_ltf_approach_structure
            trade_found = False
            if sorted_ltf and n_ltf >= 2:
                cycle_active = False
                cycle_tap_time = 0

                for i in range(1, n_ltf):
                    cand = sorted_ltf[i]
                    c_time = cand["time"]
                    c_high = cand["high"]
                    c_low = cand["low"]

                    # Check touch
                    if c_high >= b_bot and c_low <= b_top:
                        if not cycle_active:
                            if is_valid_tap_approach(box_copy, sorted_ltf, i):
                                cycle_active = True
                                cycle_tap_time = c_time

                                # Canonical pipeline: 5-wave vs CHoCH race -> retest -> pattern -> target model
                                res = compute_ltf_approach_structure(
                                    target_time=cycle_tap_time,
                                    ltf_candles=sorted_ltf,
                                    htf_boxes=htf_boxes,
                                    htf_sec=htf_sec,
                                    htf_candles=htf_candles,
                                    override_tap_time=cycle_tap_time,
                                    override_box=box_copy,
                                    as_of_time=current_time
                                )
                                tap_info = res.get("tap_info")
                                if tap_info and tap_info.get("trade"):
                                    tr = tap_info["trade"]
                                    if tr.get("executed"):
                                        entry_p = tr["entry_price"]
                                        sl_p = tr["sl_price"]
                                        tp_p = tr["tp_price"]
                                        action = tr["action"]
                                        pattern = tr.get("pattern_name", "")
                                        sig_id = f"sig_{tr['time']}_{zone_key}"
                                        sig_obj = {
                                            "id": sig_id,
                                            "time": tr["time"],
                                            "action": action,
                                            "type": action,
                                            "entry": round(entry_p, 2),
                                            "sl": round(sl_p, 2),
                                            "tp": round(tp_p, 2),
                                            "rr": tr.get("rr", self.min_rr),
                                            "risk": round(tr.get("risk", abs(entry_p - sl_p)), 2),
                                            "reward": round(tr.get("reward", abs(tp_p - entry_p)), 2),
                                            "pattern": pattern,
                                            "level": box_name,
                                            "box_id": zone_key
                                        }
                                        marker_obj = {
                                            "time": tr["time"],
                                            "position": "belowBar" if is_bull else "aboveBar",
                                            "color": "#00E676" if is_bull else "#FF5252",
                                            "shape": "arrowUp" if is_bull else "arrowDown",
                                            "text": f"{action} @ {entry_p:.2f} ({pattern} at {box_name})",
                                            "id": sig_id
                                        }
                                        signals.append(sig_obj)
                                        markers.append(marker_obj)
                                        executed_zone_keys.add(zone_key)
                                        trade_found = True
                                        break

                    if cycle_active and (c_time - cycle_tap_time) > max_cycle_seconds:
                        cycle_active = False

            box_copy["status"] = "TRADED" if trade_found else ("INSIDE_ZONE" if (current_price >= b_bot and current_price <= b_top) else "FRESH")
            box_copy["trade_count"] = 1 if trade_found else 0

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

        # Proximity Filter - Nearest active levels
        active_levels = [b for b in updated_boxes if b.get("status") in ["FRESH", "INSIDE_ZONE"]]
        active_levels.sort(key=lambda b: b.get("distance", float("inf")))
        nearby_levels = active_levels[:10]

        return markers, signals, updated_boxes, nearby_levels

    def run_strategy(self, htf_candles: List[Dict], ltf_candles: List[Dict] = None) -> Dict:
        """
        Executes unified Higher Timeframe Structure Mapping and LTF trade signal generation.
        Strictly enforces the rolling 500-candle FIFO window.
        """
        if not htf_candles:
            return {
                "lines": [],
                "labels": [],
                "boxes": [],
                "markers": [],
                "signals": [],
                "htf_trend": "Neutral",
                "ltf_trend": "Neutral",
                "nearby_levels": []
            }

        # Dynamic lookback slice preserving caller-specified lookback_bars
        lookback = getattr(self.htf_engine, "lookback_bars", 500) if self.htf_engine else 500
        if not lookback or lookback < 500:
            lookback = 500
        htf_slice = htf_candles[-lookback:] if len(htf_candles) > lookback else htf_candles
        htf_res = self.htf_engine.run(htf_slice)

        htf_boxes = htf_res.get("boxes", [])
        htf_lines = htf_res.get("lines", []) + htf_res.get("active_levels", [])
        htf_labels = htf_res.get("labels", [])

        markers, signals, updated_boxes, nearby_levels = self.process_trading_framework(
            htf_slice, ltf_candles, htf_boxes, htf_lines
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
            "total_signals": len(signals)
        }

    def run_standalone_strategy(self, candles: List[Dict], ltf_candles: List[Dict] = None) -> Dict:
        return self.run_strategy(candles, ltf_candles)
