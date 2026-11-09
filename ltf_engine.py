import math
from typing import List, Dict, Tuple, Optional
from pattern_scanner import (
    is_valid_bullish_engulfing,
    is_valid_bearish_engulfing,
    is_valid_morning_star,
    is_valid_evening_star
)

class LTFEngine:
    """
    Python implementation of 'LTF Buy & Sell SL TP.pine'.
    
    Processes LTF OHLCV candles (e.g. M5 or M1) bar-by-bar:
    - Inside Bar (Mother Candle) tracking & Valid Pullback detection
    - Market Structure (Single, Dual, Triple CHoCH & BOS)
    - Fresh CHoCH / Triple CHoCH Fair Value Gap (FVG) detection
    - Reversal Candlestick Pattern detection on FVG tap (Bullish/Bearish Engulfing, Morning/Evening Star)
    - Stop Loss (proportional buffer) & Liquidity Pool TP targeting (min 2.5 RR floor, uncapped max RR)
    """
    def __init__(self,
                 lookback_bars: int = 500,
                 use_wick_break: bool = True,
                 show_choch_fvg: bool = True,
                 show_reversal_signals: bool = False,
                 min_rr: float = 2.5,
                 sl_prop_percent: float = 0.15,
                 htf_tap_required: bool = True):
        self.lookback_bars = lookback_bars
        self.use_wick_break = use_wick_break
        self.show_choch_fvg = show_choch_fvg
        self.show_reversal_signals = show_reversal_signals
        self.min_rr = min_rr
        self.sl_prop_percent = sl_prop_percent
        self.htf_tap_required = htf_tap_required

    def run(self, candles: List[Dict], htf_zones: List[Dict] = None, tap_bar_idx: Optional[int] = None) -> Dict:
        """
        Process LTF candles and optional active HTF zones to generate LTF structure, FVGs, and Trade Signals.
        Starts market structure calculation exactly 20 candles prior to the HTF level tap.
        """
        n = len(candles)
        if n < 5:
            return {"lines": [], "labels": [], "boxes": [], "signals": [], "trend": "Neutral"}

        active_tap_idx = tap_bar_idx
        if active_tap_idx is None and self.htf_tap_required and htf_zones:
            for b_idx in range(n):
                c = candles[b_idx]
                c_low = c.get("low")
                c_high = c.get("high")
                if c_low is not None and c_high is not None:
                    for z in htf_zones:
                        top = z.get("top")
                        bot = z.get("bottom")
                        if top is not None and bot is not None:
                            z_max = max(top, bot)
                            z_min = min(top, bot)
                            if c_low <= z_max and c_high >= z_min:
                                active_tap_idx = b_idx
                                break
                    if active_tap_idx is not None:
                        break
            if active_tap_idx is None:
                return {"lines": [], "labels": [], "boxes": [], "signals": [], "trend": "Neutral"}

        start_lookback_bar = max(0, n - self.lookback_bars)

        # State machine variables
        trend = 0  # 0 = Neutral, 1 = Uptrend, -1 = Downtrend
        consecutive_choch_count = 0
        choch_stop_bar = None
        stop_bar = None
        bos_outside_zone_count = 0
        point_a_bar = None
        waiting_for_pullback = True

        # HTF Zone properties
        is_bull_zone = True
        z_top = None
        z_bot = None
        if htf_zones and len(htf_zones) > 0:
            z0 = htf_zones[0]
            if "top" in z0 and "bottom" in z0:
                z_top = max(z0["top"], z0["bottom"])
                z_bot = min(z0["top"], z0["bottom"])
            if "is_bullish" in z0:
                is_bull_zone = bool(z0["is_bullish"])
            elif active_tap_idx is not None and active_tap_idx > 0 and z_top is not None:
                c_prev = candles[active_tap_idx - 1]
                if c_prev["close"] > z_top:
                    is_bull_zone = True
                elif c_prev["close"] < z_bot:
                    is_bull_zone = False

        point_c_val = None
        point_c_bar = None
        point_c_active = False

        confirmed_hl_val = None
        confirmed_hl_bar = None
        confirmed_hl_active = False

        confirmed_lh_val = None
        confirmed_lh_bar = None
        confirmed_lh_active = False

        mother_high = None
        mother_low = None

        last_draw_bar = -1

        active_fvgs = []
        
        lines = []
        labels = []
        boxes = []
        signals = []
        active_levels = []

        def get_highest_peak(s_bar: int, e_bar: int) -> Tuple[float, int]:
            s_bar = max(start_lookback_bar, max(0, s_bar))
            e_bar = max(start_lookback_bar, max(0, min(e_bar, n - 1)))
            if s_bar > e_bar:
                s_bar, e_bar = e_bar, s_bar
            best_val = candles[s_bar]["high"]
            best_bar = s_bar
            for b in range(s_bar, e_bar + 1):
                if candles[b]["high"] >= best_val:
                    best_val = candles[b]["high"]
                    best_bar = b
            return best_val, best_bar

        def get_lowest_trough(s_bar: int, e_bar: int) -> Tuple[float, int]:
            s_bar = max(start_lookback_bar, max(0, s_bar))
            e_bar = max(start_lookback_bar, max(0, min(e_bar, n - 1)))
            if s_bar > e_bar:
                s_bar, e_bar = e_bar, s_bar
            best_val = candles[s_bar]["low"]
            best_bar = s_bar
            for b in range(s_bar, e_bar + 1):
                if candles[b]["low"] <= best_val:
                    best_val = candles[b]["low"]
                    best_bar = b
            return best_val, best_bar

        def find_buy_liquidity_tp(entry_price: float, sl_price: float, min_rr_val: float, bar_idx: int) -> Tuple[float, float]:
            risk = entry_price - sl_price
            if risk <= 0:
                return entry_price * 1.05, min_rr_val
            min_tp_price = entry_price + (risk * min_rr_val)
            candidate = None

            if point_c_active and point_c_val is not None and point_c_val >= min_tp_price:
                candidate = point_c_val
            if confirmed_lh_active and confirmed_lh_val is not None and confirmed_lh_val >= min_tp_price:
                candidate = confirmed_lh_val if candidate is None else min(candidate, confirmed_lh_val)

            search_range = min(280, bar_idx - start_lookback_bar)
            if search_range >= 5:
                for i in range(bar_idx - 2, max(start_lookback_bar, bar_idx - search_range), -1):
                    if i > 1 and i < n - 1:
                        if candles[i]["high"] > candles[i+1]["high"] and candles[i]["high"] > candles[i-1]["high"]:
                            if candles[i]["high"] >= min_tp_price:
                                candidate = candles[i]["high"] if candidate is None else min(candidate, candles[i]["high"])

            selected_tp = candidate if candidate is not None else min_tp_price
            rr_val = (selected_tp - entry_price) / risk if risk > 0 else min_rr_val
            return selected_tp, round(rr_val, 2)

        def find_sell_liquidity_tp(entry_price: float, sl_price: float, min_rr_val: float, bar_idx: int) -> Tuple[float, float]:
            risk = sl_price - entry_price
            if risk <= 0:
                return entry_price * 0.95, min_rr_val
            min_tp_price = entry_price - (risk * min_rr_val)
            candidate = None

            if point_c_active and point_c_val is not None and point_c_val <= min_tp_price:
                candidate = point_c_val
            if confirmed_hl_active and confirmed_hl_val is not None and confirmed_hl_val <= min_tp_price:
                candidate = confirmed_hl_val if candidate is None else max(candidate, confirmed_hl_val)

            search_range = min(280, bar_idx - start_lookback_bar)
            if search_range >= 5:
                for i in range(bar_idx - 2, max(start_lookback_bar, bar_idx - search_range), -1):
                    if i > 1 and i < n - 1:
                        if candles[i]["low"] < candles[i+1]["low"] and candles[i]["low"] < candles[i-1]["low"]:
                            if candles[i]["low"] <= min_tp_price:
                                candidate = candles[i]["low"] if candidate is None else max(candidate, candles[i]["low"])

            selected_tp = candidate if candidate is not None else min_tp_price
            rr_val = (entry_price - selected_tp) / risk if risk > 0 else min_rr_val
            return selected_tp, round(rr_val, 2)

        def is_fvg_htf_tapped(fvg_top: float, fvg_bottom: float, b_idx: int) -> bool:
            if not self.htf_tap_required or not htf_zones or active_tap_idx is not None:
                return True
            c = candles[b_idx]
            c_low = c.get("low")
            c_high = c.get("high")
            if c_low is None or c_high is None:
                return False
            for z in htf_zones:
                top = z.get("top")
                bot = z.get("bottom")
                if top is not None and bot is not None:
                    z_max = max(top, bot)
                    z_min = min(top, bot)
                    # Overlap check between FVG zone and HTF zone
                    if max(fvg_top, fvg_bottom) >= z_min and min(fvg_top, fvg_bottom) <= z_max:
                        return True
                    # Or price tap check
                    if c_low <= z_max and c_high >= z_min:
                        return True
            return False

        # Initialization at lookback boundary start bar
        point_a_bar = start_lookback_bar
        point_c_val = candles[start_lookback_bar]["high"]
        point_c_bar = start_lookback_bar
        confirmed_hl_val = candles[start_lookback_bar]["low"]
        confirmed_hl_bar = start_lookback_bar
        confirmed_lh_val = candles[start_lookback_bar]["high"]
        confirmed_lh_bar = start_lookback_bar
        mother_high = candles[start_lookback_bar]["high"]
        mother_low = candles[start_lookback_bar]["low"]

        # Bar-by-bar loop
        for bar_index in range(n):
            if bar_index < start_lookback_bar:
                continue

            c_curr = candles[bar_index]

            # 1. Inside Bar check
            is_inside_bar = False
            if mother_high is not None and mother_low is not None:
                is_inside_bar = (c_curr["high"] <= mother_high) and (c_curr["low"] >= mother_low)

            valid_bear_pullback = False
            valid_bull_pullback = False

            if not is_inside_bar:
                if mother_low is not None and c_curr["low"] < mother_low:
                    valid_bear_pullback = True
                if mother_high is not None and c_curr["high"] > mother_high:
                    valid_bull_pullback = True

            # 2. Cold Start Initialization
            if trend == 0:
                recent_start = max(start_lookback_bar, bar_index - 30)
                if valid_bear_pullback:
                    h_val, h_bar = get_highest_peak(recent_start, bar_index)
                    point_c_val = h_val
                    point_c_bar = h_bar
                    point_c_active = True
                    trend = 1
                    waiting_for_pullback = False
                    point_a_bar = bar_index
                    mother_high = c_curr["high"]
                    mother_low = c_curr["low"]
                elif valid_bull_pullback:
                    l_val, l_bar = get_lowest_trough(recent_start, bar_index)
                    point_c_val = l_val
                    point_c_bar = l_bar
                    point_c_active = True
                    trend = -1
                    waiting_for_pullback = False
                    point_a_bar = bar_index
                    mother_high = c_curr["high"]
                    mother_low = c_curr["low"]
                elif not is_inside_bar:
                    mother_high = c_curr["high"]
                    mother_low = c_curr["low"]

            # 3. Search for Point C (Valid Pullback)
            if trend != 0 and waiting_for_pullback and point_a_bar is not None:
                if trend == 1 and valid_bear_pullback:
                    peak_val, peak_bar = get_highest_peak(point_a_bar, bar_index)
                    point_c_val = peak_val
                    point_c_bar = peak_bar
                    point_c_active = True
                    waiting_for_pullback = False
                elif trend == -1 and valid_bull_pullback:
                    trough_val, trough_bar = get_lowest_trough(point_a_bar, bar_index)
                    point_c_val = trough_val
                    point_c_bar = trough_bar
                    point_c_active = True
                    waiting_for_pullback = False

            # 4. CHoCH Evaluation
            break_val_bear = c_curr["low"] if self.use_wick_break else c_curr["close"]
            if trend == 1 and confirmed_hl_active and confirmed_hl_val is not None and break_val_bear < confirmed_hl_val:
                confirmed_hl_active = False
                trend = -1
                consecutive_choch_count += 1
                last_draw_bar = bar_index

                lh_peak_val, lh_peak_bar = get_highest_peak(confirmed_hl_bar if confirmed_hl_bar is not None else start_lookback_bar, bar_index)
                confirmed_lh_val = lh_peak_val
                confirmed_lh_bar = lh_peak_bar
                confirmed_lh_active = True

                choch_label_text = "CHoCH" if consecutive_choch_count == 1 else ("Dual CHoCH" if consecutive_choch_count == 2 else "Triple CHoCH")
                choch_color = "#ef5350" if consecutive_choch_count == 1 else ("#ff9800" if consecutive_choch_count == 2 else "#9c27b0")

                if consecutive_choch_count >= 3:
                    for fvg in active_fvgs:
                        if fvg["choch_type"] == "CHoCH" and not fvg["is_mitigated"]:
                            fvg["is_mitigated"] = True

                was_before_stop = (choch_stop_bar is None or bar_index <= choch_stop_bar) and (stop_bar is None or bar_index <= stop_bar)
                # In a BUYING level (is_bull_zone == True), DO NOT fall for bearish CHoCH or set choch_stop_bar!
                if active_tap_idx is not None and bar_index >= active_tap_idx and choch_stop_bar is None:
                    if is_bull_zone is not True:
                        choch_stop_bar = bar_index

                # Suppress drawing Bearish CHoCH after tap if inside a buying level
                show_this_choch = was_before_stop and not (is_bull_zone is True and active_tap_idx is not None and bar_index >= active_tap_idx)

                if show_this_choch:
                    x1_bar = confirmed_hl_bar if confirmed_hl_bar is not None else start_lookback_bar
                    lines.append({
                        "id": f"ltf_choch_{bar_index}",
                        "x1": candles[x1_bar]["time"],
                        "y1": confirmed_hl_val,
                        "x2": c_curr["time"],
                        "y2": confirmed_hl_val,
                        "color": choch_color,
                        "style": "solid",
                        "type": choch_label_text
                    })
                    labels.append({
                        "id": f"lbl_ltf_choch_{bar_index}",
                        "x": (candles[x1_bar]["time"] + c_curr["time"]) // 2,
                        "y": confirmed_hl_val,
                        "text": choch_label_text,
                        "color": choch_color,
                        "textColor": "#ffffff",
                        "style": "label_down"
                    })

                    # ONLY DETECT BEARISH FVG(S) IN SINGLE/TRIPLE CHOCH LEGS IF NOT IN A BUYING LEVEL!
                    if self.show_choch_fvg and confirmed_hl_bar is not None and consecutive_choch_count != 2 and is_bull_zone is not True:
                        if active_tap_idx is None or bar_index >= active_tap_idx:
                            leg_start = max(confirmed_hl_bar, start_lookback_bar)
                            if active_tap_idx is not None:
                                leg_start = max(leg_start, active_tap_idx)
                            if leg_start + 2 <= bar_index:
                                for b_idx in range(leg_start + 2, bar_index + 1):
                                    fvg_top = candles[b_idx - 2]["low"]
                                    fvg_bot = candles[b_idx]["high"]
                                    if fvg_bot < fvg_top:
                                        is_fresh = True
                                        if b_idx < bar_index:
                                            for k in range(b_idx + 1, bar_index + 1):
                                                if candles[k]["high"] >= fvg_top:
                                                    is_fresh = False
                                                    break
                                        if is_fresh:
                                            active_fvgs.append({
                                                "id": f"fvg_{b_idx}",
                                                "left": candles[b_idx - 1]["time"],
                                                "top": fvg_top,
                                                "right": c_curr["time"],
                                                "bottom": fvg_bot,
                                                "is_bullish": False,
                                                "start_bar": b_idx - 1,
                                                "choch_bar": bar_index,
                                                "is_mitigated": False,
                                                "signal_fired": False,
                                                "choch_type": choch_label_text
                                            })

                point_c_active = False
                point_a_bar = bar_index
                waiting_for_pullback = True
                mother_high = c_curr["high"]
                mother_low = c_curr["low"]

            break_val_bull = c_curr["high"] if self.use_wick_break else c_curr["close"]
            if trend == -1 and confirmed_lh_active and confirmed_lh_val is not None and break_val_bull > confirmed_lh_val:
                confirmed_lh_active = False
                trend = 1
                consecutive_choch_count += 1
                last_draw_bar = bar_index

                hl_trough_val, hl_trough_bar = get_lowest_trough(confirmed_lh_bar if confirmed_lh_bar is not None else start_lookback_bar, bar_index)
                confirmed_hl_val = hl_trough_val
                confirmed_hl_bar = hl_trough_bar
                confirmed_hl_active = True

                choch_label_text = "CHoCH" if consecutive_choch_count == 1 else ("Dual CHoCH" if consecutive_choch_count == 2 else "Triple CHoCH")
                choch_color = "#26a69a" if consecutive_choch_count == 1 else ("#ff9800" if consecutive_choch_count == 2 else "#9c27b0")

                if consecutive_choch_count >= 3:
                    for fvg in active_fvgs:
                        if fvg["choch_type"] == "CHoCH" and not fvg["is_mitigated"]:
                            fvg["is_mitigated"] = True

                was_before_stop = (choch_stop_bar is None or bar_index <= choch_stop_bar) and (stop_bar is None or bar_index <= stop_bar)
                # In a SELLING level (is_bull_zone == False), DO NOT fall for bullish CHoCH or set choch_stop_bar!
                if active_tap_idx is not None and bar_index >= active_tap_idx and choch_stop_bar is None:
                    if is_bull_zone is not False:
                        choch_stop_bar = bar_index

                # Suppress drawing Bullish CHoCH after tap if inside a selling level
                show_this_choch = was_before_stop and not (is_bull_zone is False and active_tap_idx is not None and bar_index >= active_tap_idx)

                if show_this_choch:
                    x1_bar = confirmed_lh_bar if confirmed_lh_bar is not None else start_lookback_bar
                    lines.append({
                        "id": f"ltf_choch_{bar_index}",
                        "x1": candles[x1_bar]["time"],
                        "y1": confirmed_lh_val,
                        "x2": c_curr["time"],
                        "y2": confirmed_lh_val,
                        "color": choch_color,
                        "style": "solid",
                        "type": choch_label_text
                    })
                    labels.append({
                        "id": f"lbl_ltf_choch_{bar_index}",
                        "x": (candles[x1_bar]["time"] + c_curr["time"]) // 2,
                        "y": confirmed_lh_val,
                        "text": choch_label_text,
                        "color": choch_color,
                        "textColor": "#ffffff",
                        "style": "label_down"
                    })

                    # ONLY DETECT BULLISH FVG(S) IN SINGLE/TRIPLE CHOCH LEGS IF NOT IN A SELLING LEVEL!
                    if self.show_choch_fvg and confirmed_lh_bar is not None and consecutive_choch_count != 2 and is_bull_zone is not False:
                        if active_tap_idx is None or bar_index >= active_tap_idx:
                            leg_start = max(confirmed_lh_bar, start_lookback_bar)
                            if active_tap_idx is not None:
                                leg_start = max(leg_start, active_tap_idx)
                            if leg_start + 2 <= bar_index:
                                for b_idx in range(leg_start + 2, bar_index + 1):
                                    fvg_top = candles[b_idx]["low"]
                                    fvg_bot = candles[b_idx - 2]["high"]
                                    if fvg_top > fvg_bot:
                                        is_fresh = True
                                        if b_idx < bar_index:
                                            for k in range(b_idx + 1, bar_index + 1):
                                                if candles[k]["low"] <= fvg_bot:
                                                    is_fresh = False
                                                    break
                                        if is_fresh:
                                            active_fvgs.append({
                                                "id": f"fvg_{b_idx}",
                                                "left": candles[b_idx - 1]["time"],
                                                "top": fvg_top,
                                                "right": c_curr["time"],
                                                "bottom": fvg_bot,
                                                "is_bullish": True,
                                                "start_bar": b_idx - 1,
                                                "choch_bar": bar_index,
                                                "is_mitigated": False,
                                                "signal_fired": False,
                                                "choch_type": choch_label_text
                                            })

                point_c_active = False
                point_a_bar = bar_index
                waiting_for_pullback = True
                mother_high = c_curr["high"]
                mother_low = c_curr["low"]

            # 5. BOS Evaluation
            break_val_bos_bull = c_curr["high"] if self.use_wick_break else c_curr["close"]
            if trend == 1 and point_c_active and point_c_val is not None and break_val_bos_bull > point_c_val and last_draw_bar != bar_index:
                point_c_active = False
                last_draw_bar = bar_index
                consecutive_choch_count = 0

                # Check if this Bullish BOS occurred above selling level after tap without CHoCH
                if active_tap_idx is not None and bar_index >= active_tap_idx and not is_bull_zone and z_top is not None:
                    if c_curr["close"] > z_top or (point_c_val is not None and point_c_val >= z_top) or break_val_bos_bull > z_top:
                        if choch_stop_bar is None:
                            bos_outside_zone_count += 1
                            if bos_outside_zone_count >= 2 and stop_bar is None:
                                stop_bar = bar_index

                was_before_all_stops = (choch_stop_bar is None or bar_index <= choch_stop_bar) and (stop_bar is None or bar_index <= stop_bar)
                if was_before_all_stops:
                    x1_bar = point_c_bar if point_c_bar is not None else start_lookback_bar
                    lines.append({
                        "id": f"ltf_bos_{bar_index}",
                        "x1": candles[x1_bar]["time"],
                        "y1": point_c_val,
                        "x2": c_curr["time"],
                        "y2": point_c_val,
                        "color": "#26a69a",
                        "style": "solid",
                        "type": "BOS"
                    })
                    labels.append({
                        "id": f"lbl_ltf_bos_{bar_index}",
                        "x": (candles[x1_bar]["time"] + c_curr["time"]) // 2,
                        "y": point_c_val,
                        "text": "BOS",
                        "color": "#26a69a",
                        "textColor": "#ffffff",
                        "style": "label_down"
                    })

                hl_val, hl_bar = get_lowest_trough(point_c_bar if point_c_bar is not None else start_lookback_bar, bar_index)
                confirmed_hl_val = hl_val
                confirmed_hl_bar = hl_bar
                confirmed_hl_active = True

                point_a_bar = bar_index
                waiting_for_pullback = True
                mother_high = c_curr["high"]
                mother_low = c_curr["low"]

            break_val_bos_bear = c_curr["low"] if self.use_wick_break else c_curr["close"]
            if trend == -1 and point_c_active and point_c_val is not None and break_val_bos_bear < point_c_val and last_draw_bar != bar_index:
                point_c_active = False
                last_draw_bar = bar_index
                consecutive_choch_count = 0

                # Check if this Bearish BOS occurred below buying level after tap without CHoCH
                if active_tap_idx is not None and bar_index >= active_tap_idx and is_bull_zone and z_bot is not None:
                    if c_curr["close"] < z_bot or (point_c_val is not None and point_c_val <= z_bot) or break_val_bos_bear < z_bot:
                        if choch_stop_bar is None:
                            bos_outside_zone_count += 1
                            if bos_outside_zone_count >= 2 and stop_bar is None:
                                stop_bar = bar_index

                was_before_all_stops = (choch_stop_bar is None or bar_index <= choch_stop_bar) and (stop_bar is None or bar_index <= stop_bar)
                if was_before_all_stops:
                    x1_bar = point_c_bar if point_c_bar is not None else start_lookback_bar
                    lines.append({
                        "id": f"ltf_bos_{bar_index}",
                        "x1": candles[x1_bar]["time"],
                        "y1": point_c_val,
                        "x2": c_curr["time"],
                        "y2": point_c_val,
                        "color": "#ef5350",
                        "style": "solid",
                        "type": "BOS"
                    })
                    labels.append({
                        "id": f"lbl_ltf_bos_{bar_index}",
                        "x": (candles[x1_bar]["time"] + c_curr["time"]) // 2,
                        "y": point_c_val,
                        "text": "BOS",
                        "color": "#ef5350",
                        "textColor": "#ffffff",
                        "style": "label_down"
                    })

                lh_val, lh_bar = get_highest_peak(point_c_bar if point_c_bar is not None else start_lookback_bar, bar_index)
                confirmed_lh_val = lh_val
                confirmed_lh_bar = lh_bar
                confirmed_lh_active = True

                point_a_bar = bar_index
                waiting_for_pullback = True
                mother_high = c_curr["high"]
                mother_low = c_curr["low"]

            if not is_inside_bar:
                mother_high = c_curr["high"]
                mother_low = c_curr["low"]

            # 6. FVG Re-Test, Candlestick Reversal Signals & Trade Generation (HTF zone tap verified)
            for fvg in active_fvgs:
                if not fvg["is_mitigated"] and bar_index > fvg["choch_bar"]:
                    fvg["right"] = c_curr["time"]

                    c0_touch = (c_curr["low"] <= fvg["top"]) and (c_curr["high"] >= fvg["bottom"])
                    c1_touch = (bar_index - 1 > fvg["choch_bar"]) and (candles[bar_index - 1]["low"] <= fvg["top"]) and (candles[bar_index - 1]["high"] >= fvg["bottom"])
                    c2_touch = (bar_index - 2 > fvg["choch_bar"]) and (candles[bar_index - 2]["low"] <= fvg["top"]) and (candles[bar_index - 2]["high"] >= fvg["bottom"])

                    any_touch = c0_touch or c1_touch or c2_touch

                    if any_touch and self.show_reversal_signals and not fvg["signal_fired"]:
                        # Verify HTF tap condition for signal triggering
                        if is_fvg_htf_tapped(fvg["top"], fvg["bottom"], bar_index):
                            c0 = candles[bar_index]
                            c1 = candles[bar_index - 1] if bar_index > 0 else c0
                            c2 = candles[bar_index - 2] if bar_index > 1 else c1

                            if fvg["is_bullish"]:
                                b_engulfing = is_valid_bullish_engulfing(c1, c0)
                                m_star = is_valid_morning_star(c2, c1, c0)

                                valid_eng = b_engulfing and (c0_touch or c1_touch)
                                valid_mstar = m_star and (c0_touch or c1_touch or c2_touch)

                                if valid_eng or valid_mstar:
                                    fvg["signal_fired"] = True
                                    fvg["is_mitigated"] = True
                                    pat_name = "Bullish Engulfing" if valid_eng else "Morning Star"
                                    
                                    base_sl = min(c0["low"], c1["low"]) if valid_eng else c1["low"]
                                    sl_price = base_sl * (1.0 - self.sl_prop_percent / 100.0)
                                    entry_price = c0["close"]
                                    
                                    tp_price, rr_ratio = find_buy_liquidity_tp(entry_price, sl_price, self.min_rr, bar_index)

                                    signals.append({
                                        "id": f"buy_sig_{bar_index}",
                                        "type": "BUY",
                                        "time": c0["time"],
                                        "price": entry_price,
                                        "sl": round(sl_price, 4),
                                        "tp": round(tp_price, 4),
                                        "rr": rr_ratio,
                                        "pattern": pat_name,
                                        "origin_fvg": fvg["choch_type"]
                                    })
                                    labels.append({
                                        "id": f"lbl_signal_{bar_index}",
                                        "x": c0["time"],
                                        "y": c0["low"],
                                        "text": pat_name,
                                        "color": "#26a69a",
                                        "textColor": "#ffffff",
                                        "position": "below",
                                        "style": "label_up"
                                    })

                            else:
                                bear_engulfing = is_valid_bearish_engulfing(c1, c0)
                                e_star = is_valid_evening_star(c2, c1, c0)

                                valid_eng = bear_engulfing and (c0_touch or c1_touch)
                                valid_estar = e_star and (c0_touch or c1_touch or c2_touch)

                                if valid_eng or valid_estar:
                                    fvg["signal_fired"] = True
                                    fvg["is_mitigated"] = True
                                    pat_name = "Bearish Engulfing" if valid_eng else "Evening Star"

                                    base_sl = max(c0["high"], c1["high"]) if valid_eng else c1["high"]
                                    sl_price = base_sl * (1.0 + self.sl_prop_percent / 100.0)
                                    entry_price = c0["close"]

                                    tp_price, rr_ratio = find_sell_liquidity_tp(entry_price, sl_price, self.min_rr, bar_index)

                                    signals.append({
                                        "id": f"sell_sig_{bar_index}",
                                        "type": "SELL",
                                        "time": c0["time"],
                                        "price": entry_price,
                                        "sl": round(sl_price, 4),
                                        "tp": round(tp_price, 4),
                                        "rr": rr_ratio,
                                        "pattern": pat_name,
                                        "origin_fvg": fvg["choch_type"]
                                    })
                                    labels.append({
                                        "id": f"lbl_signal_{bar_index}",
                                        "x": c0["time"],
                                        "y": c0["high"],
                                        "text": pat_name,
                                        "color": "#ef5350",
                                        "textColor": "#ffffff",
                                        "position": "above",
                                        "style": "label_down"
                                    })

                    breached = (c_curr["low"] < fvg["bottom"]) if fvg["is_bullish"] else (c_curr["high"] > fvg["top"])
                    if breached:
                        fvg["is_mitigated"] = True

        # Convert active unmitigated/fresh FVGs into box dicts for rendering
        fvg_boxes = []
        for fvg in active_fvgs:
            bg_color = "rgba(38, 166, 154, 0.25)" if fvg["is_bullish"] else "rgba(239, 83, 80, 0.25)"
            if fvg["is_mitigated"]:
                bg_color = "rgba(120, 123, 134, 0.1)"
            fvg_boxes.append({
                "id": fvg["id"],
                "left": fvg["left"],
                "top": fvg["top"],
                "right": fvg["right"],
                "bottom": fvg["bottom"],
                "color": bg_color,
                "borderColor": "#26a69a" if fvg["is_bullish"] else "#ef5350",
                "text": "LTF FVG" if not fvg["is_mitigated"] else "Mitigated FVG"
            })

        # Reveal LTF primitives starting from last 30 candles prior to tap point up to the CHoCH
        min_mark_idx = max(0, active_tap_idx - 30) if active_tap_idx is not None else start_lookback_bar
        min_valid_time = candles[min_mark_idx]["time"]
        max_valid_time = None
        if active_tap_idx is not None and stop_bar is not None and stop_bar < active_tap_idx:
            stop_bar = None
        if choch_stop_bar is not None and stop_bar is not None:
            max_valid_time = min(candles[choch_stop_bar]["time"], candles[stop_bar]["time"])
        elif choch_stop_bar is not None:
            max_valid_time = candles[choch_stop_bar]["time"]
        elif stop_bar is not None:
            max_valid_time = candles[stop_bar]["time"]

        lines = [l for l in lines if l.get("x2", 0) >= min_valid_time and (max_valid_time is None or l.get("x2", 0) <= max_valid_time)]
        kept_line_label_ids = {"lbl_" + l["id"] for l in lines}
        labels = [lbl for lbl in labels if (lbl.get("id") in kept_line_label_ids or lbl.get("x", 0) >= min_valid_time) and (max_valid_time is None or lbl.get("x", 0) <= max_valid_time or "signal" in lbl.get("id", ""))]
        # FVGs and trade signals must ONLY be marked on or after the tap in zone!
        tap_time_threshold = candles[active_tap_idx]["time"] if active_tap_idx is not None else min_valid_time
        stop_time = candles[stop_bar]["time"] if stop_bar is not None else None
        fvg_boxes = [b for b in fvg_boxes if b.get("left", 0) >= tap_time_threshold and (max_valid_time is None or b.get("left", 0) <= max_valid_time) and (stop_time is None or b.get("left", 0) <= stop_time)]
        signals = [s for s in signals if s.get("time", 0) >= tap_time_threshold and (stop_time is None or s.get("time", 0) <= stop_time)]

        return {
            "lines": lines,
            "labels": labels,
            "boxes": fvg_boxes,
            "signals": signals,
            "trend": "Uptrend" if trend == 1 else ("Downtrend" if trend == -1 else "Neutral")
        }

