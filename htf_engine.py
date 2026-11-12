import math
from typing import List, Dict, Tuple, Optional, Any, Union


def is_qualifying_htf_zone(box: Dict) -> bool:
    """
    Institutional 7-Section HTF Zone Qualification Filter:
      1. TJL1 & TJL2 from BOS
      2. QML & Double Top / Double Bottom from Single CHoCH
      3. A+ from Dual CHoCH (ELIMINATED per forensic optimization)
      4. SBR / RBS from Dual CHoCH only (in_dual_choch == True)
    """
    box_id = str(box.get("id") or "").lower()
    txt = (box.get("text") or box.get("name") or "").upper()
    if box_id.startswith("tjl1") or box_id.startswith("tjl2") or "TJL1" in txt or "TJL2" in txt:
        return True
    if "QML" in txt:
        return True
    if "DOUBLE TOP" in txt or "DOUBLE BOTTOM" in txt:
        return True
    if "A+" in txt:
        return True
    if ("SBR" in txt or "RBS" in txt) and box.get("in_dual_choch", False):
        return True
    return False


def is_htf_box_active(box: Dict, current_time: int, htf_sec: Any = 14400) -> bool:
    """
    Checks if an HTF box is active and eligible to be traded at current_time:
    1. Must be a qualifying HTF zone (TJL1, TJL2 BOS, QML single CHoCH, SBR/RBS dual CHoCH, DT/DB).
    2. Must have formed on or before current_time (current_time >= box.left).
    3. Rolling 500-candle FIFO horizon: formation must not be older than 500 HTF bars (TradingView model).
    4. Must NOT be broken or mitigated by 2 closes beyond opposite boundary (Rule ZONE-003).
    """
    if isinstance(htf_sec, str):
        tf = htf_sec.lower()
        if tf in ["15m", "m15"]:
            htf_sec = 900
        elif tf in ["1h", "h1"]:
            htf_sec = 3600
        elif tf in ["4h", "h4"]:
            htf_sec = 14400
        elif tf in ["1d", "d1"]:
            htf_sec = 86400
        elif tf.endswith("m"):
            htf_sec = int(tf[:-1]) * 60
        elif tf.endswith("h"):
            htf_sec = int(tf[:-1]) * 3600
        else:
            htf_sec = 14400

    if not is_qualifying_htf_zone(box):
        return False

    left = box.get("confirmed_formation_time") or box.get("left") or box.get("start_time") or box.get("time") or 0
    if current_time < left:
        return False

    # 1. Rolling 500-candle horizon (TradingView FIFO model)
    if (current_time - left) > (500 * htf_sec):
        return False

    # 2. Mitigation / Breakout check (Rule ZONE-003)
    if box.get("is_mitigated") or box.get("is_broken"):
        mit_time = box.get("mitigated_time") or box.get("right")
        if mit_time:
            if current_time >= mit_time:
                return False
        else:
            return False

    return True


class HTFEngine:
    """
    Python implementation of 'HTF Structure & Level.pine'
    (TopG Last Swing Structure [BOS / CHoCH / Dual CHoCH]).
    
    Processes OHLCV candles bar-by-bar and computes structure events:
    - 2-Candle Retracement (2RTR)
    - Market Structure (Uptrend / Downtrend)
    - BOS (Break of Structure)
    - CHoCH (Change of Character)
    - Dual CHoCH
    - Level of 4 CHoCH breaks
    - TJL Rectangles (TJL1, TJL2, Double Top/Bottom, Level of 3, Level of 4, QML, SBR/RBS)
    - Active Structure Levels
    """
    def __init__(self, 
                 lookback_bars: int = 500,
                 show_bos: bool = True,
                 show_choch: bool = True,
                 show_dual_choch: bool = True,
                 show_triple_choch: bool = True,
                 show_retracement_shapes: bool = False,
                 show_active_swings: bool = True,
                 show_tjl_boxes: bool = True,
                 tjl_extend: bool = True, # Enable level extension rules
                 box_width_bars: int = 12, # Number of bars box extends from setup candle
                 active_swing_length_bars: int = 30, # Length of active swing preview lines
                 **kwargs):
        self.lookback_bars = lookback_bars
        self.show_bos = show_bos
        self.show_choch = show_choch
        self.show_dual_choch = show_dual_choch
        self.show_triple_choch = show_triple_choch
        self.show_retracement_shapes = show_retracement_shapes
        self.show_active_swings = show_active_swings
        self.show_tjl_boxes = show_tjl_boxes
        self.tjl_extend = tjl_extend
        self.box_width_bars = box_width_bars
        self.active_swing_length_bars = active_swing_length_bars

    def run(self, candles: List[Dict]) -> Dict:
        """
        Process candles and return structure data (lines, labels, boxes, markers, active_levels).
        """
        n = len(candles)
        if n < 5:
            return {"lines": [], "labels": [], "boxes": [], "markers": [], "active_levels": []}

        start_lookback_bar = max(0, n - self.lookback_bars)

        # State machine variables
        trend = 0  # 0 = Neutral, 1 = Uptrend, -1 = Downtrend
        point_a_bar = None
        waiting_for_2rtr = True

        point_c_val = None
        point_c_bar = None
        point_c_active = False

        confirmed_hl_val = None
        confirmed_hl_bar = None
        confirmed_hl_active = False

        confirmed_lh_val = None
        confirmed_lh_bar = None
        confirmed_lh_active = False

        consecutive_choch_count = 0
        has_bos_after_choch = True
        dual_choch_target_val = None
        dual_choch_target_bar = None
        dual_choch_active = False

        last_draw_bar = -1

        level_of_4_val = None
        level_of_4_bar = None
        level_of_4_active = False

        last_tjl1_box_idx = None
        last_tjl2_box_idx = None
        last_double_box_idx = None
        last_level4_box_idx = None

        def get_choch_props(count: int, is_bull: bool) -> Tuple[str, str, bool]:
            if count == 1:
                col = "#26a69a" if is_bull else "#ef5350"
                return "CHoCH", col, self.show_choch
            elif count == 2:
                return "Dual CHoCH", "#ff9800", self.show_dual_choch
            else:
                return "Triple CHoCH", "#9c27b0", self.show_triple_choch

        lines = []
        labels = []
        boxes = []
        markers = []
        active_levels = []

        def get_highest_peak(s_bar: int, e_bar: int) -> Tuple[float, int]:
            s_bar = max(0, s_bar)
            e_bar = max(0, min(e_bar, n - 1))
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
            s_bar = max(0, s_bar)
            e_bar = max(0, min(e_bar, n - 1))
            if s_bar > e_bar:
                s_bar, e_bar = e_bar, s_bar
            best_val = candles[s_bar]["low"]
            best_bar = s_bar
            for b in range(s_bar, e_bar + 1):
                if candles[b]["low"] <= best_val:
                    best_val = candles[b]["low"]
                    best_bar = b
            return best_val, best_bar

        def get_box_right_time(start_bar_idx: int, current_bar_idx: int) -> int:
            if self.tjl_extend:
                return candles[min(n - 1, current_bar_idx)]["time"]
            target_idx = min(n - 1, start_bar_idx + self.box_width_bars)
            return candles[target_idx]["time"]

        def get_box_style(is_bull: bool) -> Tuple[str, str, bool, str]:
            c_fill = "rgba(38, 166, 154, 0.25)" if is_bull else "rgba(239, 83, 80, 0.25)"
            c_border = "#26a69a" if is_bull else "#ef5350"
            level_type = "demand" if is_bull else "supply"
            return c_fill, c_border, is_bull, level_type

        def set_cycle_boxes_polarity(is_bull: bool):
            c_fill, c_border, is_bull_val, level_type = get_box_style(is_bull)
            for b_idx in [last_tjl1_box_idx, last_tjl2_box_idx, last_double_box_idx, last_level4_box_idx]:
                if b_idx is not None and 0 <= b_idx < len(boxes):
                    boxes[b_idx]["color"] = c_fill
                    boxes[b_idx]["borderColor"] = c_border
                    boxes[b_idx]["is_bullish"] = is_bull_val
                    boxes[b_idx]["level_type"] = level_type

        # Initialization at lookback boundary start bar
        point_a_bar = start_lookback_bar
        point_c_val = candles[start_lookback_bar]["high"]
        point_c_bar = start_lookback_bar
        confirmed_hl_val = candles[start_lookback_bar]["low"]
        confirmed_hl_bar = start_lookback_bar
        confirmed_lh_val = candles[start_lookback_bar]["high"]
        confirmed_lh_bar = start_lookback_bar

        for bar_index in range(n):
            if bar_index < start_lookback_bar:
                continue

            c_curr = candles[bar_index]
            c_prev = candles[bar_index - 1] if bar_index > 0 else c_curr

            # 2-Candle Retracement (2RTR) flags
            is_red1 = c_prev["close"] < c_prev["open"]
            is_red2 = c_curr["close"] < c_curr["open"]
            bearish_pullback = is_red1 and is_red2 and (c_curr["close"] < c_prev["low"])

            is_green1 = c_prev["close"] > c_prev["open"]
            is_green2 = c_curr["close"] > c_curr["open"]
            bullish_pullback = is_green1 and is_green2 and (c_curr["close"] > c_prev["high"])

            if self.show_retracement_shapes:
                if bearish_pullback:
                    markers.append({
                        "time": c_curr["time"],
                        "position": "aboveBar",
                        "color": "#ef5350",
                        "shape": "arrowDown",
                        "text": "2RTR"
                    })
                elif bullish_pullback:
                    markers.append({
                        "time": c_curr["time"],
                        "position": "belowBar",
                        "color": "#26a69a",
                        "shape": "arrowUp",
                        "text": "2RTR"
                    })

            # 1. Neutral Cold Start
            if trend == 0:
                recent_start = max(start_lookback_bar, bar_index - 30)
                if bearish_pullback:
                    h_val, h_bar = get_highest_peak(recent_start, bar_index)
                    point_c_val = h_val
                    point_c_bar = h_bar
                    point_c_active = True
                    trend = 1
                    waiting_for_2rtr = False
                    point_a_bar = bar_index
                elif bullish_pullback:
                    l_val, l_bar = get_lowest_trough(recent_start, bar_index)
                    point_c_val = l_val
                    point_c_bar = l_bar
                    point_c_active = True
                    trend = -1
                    waiting_for_2rtr = False
                    point_a_bar = bar_index

            # 2. Dual / Triple CHoCH Break Evaluation
            if dual_choch_active and not has_bos_after_choch and dual_choch_target_val is not None:
                if trend == -1 and c_prev["close"] > dual_choch_target_val and c_curr["close"] > dual_choch_target_val:
                    trend = 1
                    dual_choch_active = False
                    point_c_active = False
                    has_bos_after_choch = True
                    consecutive_choch_count += 1
                    last_draw_bar = bar_index

                    choch_text, choch_col, should_draw = get_choch_props(consecutive_choch_count, True)
                    if should_draw:
                        x1_bar = dual_choch_target_bar if dual_choch_target_bar is not None else start_lookback_bar
                        lines.append({
                            "id": f"choch_{bar_index}",
                            "x1": candles[x1_bar]["time"],
                            "y1": dual_choch_target_val,
                            "x2": c_curr["time"],
                            "y2": dual_choch_target_val,
                            "color": choch_col,
                            "style": "solid",
                            "type": choch_text
                        })
                        avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                        labels.append({
                            "id": f"lbl_choch_{bar_index}",
                            "x": avg_time,
                            "y": dual_choch_target_val,
                            "text": choch_text,
                            "color": choch_col,
                            "textColor": "#ffffff",
                            "style": "label_down"
                        })

                    ll_bar = point_c_bar if (point_c_bar is not None and point_c_bar >= point_a_bar) else None
                    if ll_bar is None:
                        _, ll_bar = get_lowest_trough(point_a_bar, max(point_a_bar, bar_index - 1))
                    
                    if self.show_tjl_boxes:
                        if last_tjl1_box_idx is not None and last_tjl1_box_idx < len(boxes):
                            boxes[last_tjl1_box_idx]["text"] = "A+"
                            boxes[last_tjl1_box_idx]["active_start_bar"] = bar_index
                        if last_tjl2_box_idx is not None and last_tjl2_box_idx < len(boxes):
                            boxes[last_tjl2_box_idx]["text"] = "RBS"
                            boxes[last_tjl2_box_idx]["in_dual_choch"] = True
                            boxes[last_tjl2_box_idx]["active_start_bar"] = bar_index
                        if last_double_box_idx is not None and last_double_box_idx < len(boxes):
                            boxes[last_double_box_idx]["text"] = "LEVEL of 3"
                            boxes[last_double_box_idx]["active_start_bar"] = bar_index
                        
                        if 0 <= ll_bar < n:
                            c_ll = candles[ll_bar]
                            db_top = min(c_ll["open"], c_ll["close"])
                            db_bot = c_ll["low"]
                            right_time = get_box_right_time(ll_bar, bar_index)
                            c_fill, c_border, is_bull, l_type = get_box_style(True)
                            last_level4_box_idx = len(boxes)
                            boxes.append({
                                "id": f"box_l4_{bar_index}",
                                "created_bar": bar_index,
                                "left": c_ll["time"],
                                "top": db_top,
                                "right": right_time,
                                "bottom": db_bot,
                                "color": c_fill,
                                "borderColor": c_border,
                                "text": "level of 4",
                                "is_bullish": is_bull,
                                "level_type": l_type
                            })
                        set_cycle_boxes_polarity(True)

                    if 0 <= ll_bar < n:
                        c_ll = candles[ll_bar]
                        db_bot = c_ll["low"]
                        level_of_4_val = db_bot
                        level_of_4_bar = ll_bar
                        level_of_4_active = True

                    point_a_bar = bar_index
                    waiting_for_2rtr = True

                elif trend == 1 and c_prev["close"] < dual_choch_target_val and c_curr["close"] < dual_choch_target_val:
                    trend = -1
                    dual_choch_active = False
                    point_c_active = False
                    has_bos_after_choch = True
                    consecutive_choch_count += 1
                    last_draw_bar = bar_index

                    choch_text, choch_col, should_draw = get_choch_props(consecutive_choch_count, False)
                    if should_draw:
                        x1_bar = dual_choch_target_bar if dual_choch_target_bar is not None else start_lookback_bar
                        lines.append({
                            "id": f"choch_{bar_index}",
                            "x1": candles[x1_bar]["time"],
                            "y1": dual_choch_target_val,
                            "x2": c_curr["time"],
                            "y2": dual_choch_target_val,
                            "color": choch_col,
                            "style": "solid",
                            "type": choch_text
                        })
                        avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                        labels.append({
                            "id": f"lbl_choch_{bar_index}",
                            "x": avg_time,
                            "y": dual_choch_target_val,
                            "text": choch_text,
                            "color": choch_col,
                            "textColor": "#ffffff",
                            "style": "label_down"
                        })

                    hh_bar = point_c_bar if (point_c_bar is not None and point_c_bar >= point_a_bar) else None
                    if hh_bar is None:
                        _, hh_bar = get_highest_peak(point_a_bar, max(point_a_bar, bar_index - 1))
                    
                    if self.show_tjl_boxes:
                        if last_tjl1_box_idx is not None and last_tjl1_box_idx < len(boxes):
                            boxes[last_tjl1_box_idx]["text"] = "A+"
                            boxes[last_tjl1_box_idx]["active_start_bar"] = bar_index
                        if last_tjl2_box_idx is not None and last_tjl2_box_idx < len(boxes):
                            boxes[last_tjl2_box_idx]["text"] = "SBR"
                            boxes[last_tjl2_box_idx]["in_dual_choch"] = True
                            boxes[last_tjl2_box_idx]["active_start_bar"] = bar_index
                        if last_double_box_idx is not None and last_double_box_idx < len(boxes):
                            boxes[last_double_box_idx]["text"] = "LEVEL of 3"
                            boxes[last_double_box_idx]["active_start_bar"] = bar_index

                        if 0 <= hh_bar < n:
                            c_hh = candles[hh_bar]
                            dt_top = c_hh["high"]
                            dt_bot = max(c_hh["open"], c_hh["close"])
                            right_time = get_box_right_time(hh_bar, bar_index)
                            c_fill, c_border, is_bull, l_type = get_box_style(False)
                            last_level4_box_idx = len(boxes)
                            boxes.append({
                                "id": f"box_l4_{bar_index}",
                                "created_bar": bar_index,
                                "left": c_hh["time"],
                                "top": dt_top,
                                "right": right_time,
                                "bottom": dt_bot,
                                "color": c_fill,
                                "borderColor": c_border,
                                "text": "level of 4",
                                "is_bullish": is_bull,
                                "level_type": l_type
                            })
                        set_cycle_boxes_polarity(False)

                    if 0 <= hh_bar < n:
                        c_hh = candles[hh_bar]
                        dt_top = c_hh["high"]
                        level_of_4_val = dt_top
                        level_of_4_bar = hh_bar
                        level_of_4_active = True

                    point_a_bar = bar_index
                    waiting_for_2rtr = True

            # 2.5 Level of 4 Breakout Evaluation
            if level_of_4_active and level_of_4_val is not None:
                if trend == 1 and c_prev["close"] < level_of_4_val and c_curr["close"] < level_of_4_val and last_draw_bar != bar_index:
                    trend = -1
                    level_of_4_active = False
                    point_c_active = False
                    confirmed_hl_active = False
                    confirmed_lh_active = False
                    has_bos_after_choch = False
                    dual_choch_active = True
                    consecutive_choch_count += 1
                    last_draw_bar = bar_index

                    last_tjl1_box_idx = None
                    last_tjl2_box_idx = None
                    last_double_box_idx = None
                    last_level4_box_idx = None

                    choch_text, choch_col, should_draw = get_choch_props(consecutive_choch_count, False)
                    if should_draw:
                        x1_bar = level_of_4_bar if level_of_4_bar is not None else start_lookback_bar
                        lines.append({
                            "id": f"choch_l4_{bar_index}",
                            "x1": candles[x1_bar]["time"],
                            "y1": level_of_4_val,
                            "x2": c_curr["time"],
                            "y2": level_of_4_val,
                            "color": choch_col,
                            "style": "solid",
                            "type": choch_text
                        })
                        avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                        labels.append({
                            "id": f"lbl_choch_l4_{bar_index}",
                            "x": avg_time,
                            "y": level_of_4_val,
                            "text": choch_text,
                            "color": choch_col,
                            "textColor": "#ffffff",
                            "style": "label_down"
                        })

                    point_a_bar = bar_index
                    waiting_for_2rtr = True

                elif trend == -1 and c_prev["close"] > level_of_4_val and c_curr["close"] > level_of_4_val and last_draw_bar != bar_index:
                    trend = 1
                    level_of_4_active = False
                    point_c_active = False
                    confirmed_hl_active = False
                    confirmed_lh_active = False
                    has_bos_after_choch = False
                    dual_choch_active = True
                    consecutive_choch_count += 1
                    last_draw_bar = bar_index

                    last_tjl1_box_idx = None
                    last_tjl2_box_idx = None
                    last_double_box_idx = None
                    last_level4_box_idx = None

                    choch_text, choch_col, should_draw = get_choch_props(consecutive_choch_count, True)
                    if should_draw:
                        x1_bar = level_of_4_bar if level_of_4_bar is not None else start_lookback_bar
                        lines.append({
                            "id": f"choch_l4_{bar_index}",
                            "x1": candles[x1_bar]["time"],
                            "y1": level_of_4_val,
                            "x2": c_curr["time"],
                            "y2": level_of_4_val,
                            "color": choch_col,
                            "style": "solid",
                            "type": choch_text
                        })
                        avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                        labels.append({
                            "id": f"lbl_choch_l4_{bar_index}",
                            "x": avg_time,
                            "y": level_of_4_val,
                            "text": choch_text,
                            "color": choch_col,
                            "textColor": "#ffffff",
                            "style": "label_down"
                        })

                    point_a_bar = bar_index
                    waiting_for_2rtr = True

            # 3. Search for Point B (2RTR after BOS / Point A)
            if waiting_for_2rtr and point_a_bar is not None:
                if trend == 1 and bearish_pullback:
                    peak_val, peak_bar = get_highest_peak(point_a_bar, bar_index)
                    point_c_val = peak_val
                    point_c_bar = peak_bar
                    point_c_active = True
                    waiting_for_2rtr = False
                elif trend == -1 and bullish_pullback:
                    trough_val, trough_bar = get_lowest_trough(point_a_bar, bar_index)
                    point_c_val = trough_val
                    point_c_bar = trough_bar
                    point_c_active = True
                    waiting_for_2rtr = False

            # 4. CHoCH Evaluation (Break of HL / LH)
            if trend == 1 and confirmed_hl_active and confirmed_hl_val is not None and c_prev["close"] < confirmed_hl_val and c_curr["close"] < confirmed_hl_val:
                confirmed_hl_active = False
                trend = -1
                consecutive_choch_count += 1

                if not has_bos_after_choch:
                    has_bos_after_choch = True
                    dual_choch_active = False
                    point_c_active = False
                    last_draw_bar = bar_index

                    choch_text, choch_col, should_draw = get_choch_props(consecutive_choch_count, False)
                    if should_draw:
                        x1_bar = confirmed_hl_bar if confirmed_hl_bar is not None else start_lookback_bar
                        lines.append({
                            "id": f"choch_hl_{bar_index}",
                            "x1": candles[x1_bar]["time"],
                            "y1": confirmed_hl_val,
                            "x2": c_curr["time"],
                            "y2": confirmed_hl_val,
                            "color": choch_col,
                            "style": "solid",
                            "type": choch_text
                        })
                        avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                        labels.append({
                            "id": f"lbl_choch_hl_{bar_index}",
                            "x": avg_time,
                            "y": confirmed_hl_val,
                            "text": choch_text,
                            "color": choch_col,
                            "textColor": "#ffffff",
                            "style": "label_down"
                        })

                    hh_bar = point_c_bar if (point_c_bar is not None and point_c_bar >= point_a_bar) else None
                    if hh_bar is None:
                        _, hh_bar = get_highest_peak(point_a_bar, max(point_a_bar, bar_index - 1))
                    
                    if 0 <= hh_bar < n:
                        c_hh = candles[hh_bar]
                        dt_top = c_hh["high"]
                        dt_bot = max(c_hh["open"], c_hh["close"])

                        if self.show_tjl_boxes:
                            if last_tjl1_box_idx is not None and last_tjl1_box_idx < len(boxes):
                                boxes[last_tjl1_box_idx]["text"] = "A+"
                                boxes[last_tjl1_box_idx]["active_start_bar"] = bar_index
                            if last_tjl2_box_idx is not None and last_tjl2_box_idx < len(boxes):
                                boxes[last_tjl2_box_idx]["text"] = "SBR"
                                boxes[last_tjl2_box_idx]["in_dual_choch"] = True
                                boxes[last_tjl2_box_idx]["active_start_bar"] = bar_index
                            if last_double_box_idx is not None and last_double_box_idx < len(boxes):
                                boxes[last_double_box_idx]["text"] = "LEVEL of 3"
                                boxes[last_double_box_idx]["active_start_bar"] = bar_index

                            if 0 <= hh_bar < n:
                                c_hh = candles[hh_bar]
                                dt_top = c_hh["high"]
                                dt_bot = max(c_hh["open"], c_hh["close"])
                                right_time = get_box_right_time(hh_bar, bar_index)
                                c_fill, c_border, is_bull, l_type = get_box_style(False)
                                last_level4_box_idx = len(boxes)
                                boxes.append({
                                    "id": f"box_l4_hl_{bar_index}",
                                    "created_bar": bar_index,
                                    "left": c_hh["time"],
                                    "top": dt_top,
                                    "right": right_time,
                                    "bottom": dt_bot,
                                    "color": c_fill,
                                    "borderColor": c_border,
                                    "text": "level of 4",
                                    "is_bullish": is_bull,
                                    "level_type": l_type
                                })
                            set_cycle_boxes_polarity(False)

                        if 0 <= hh_bar < n:
                            c_hh = candles[hh_bar]
                            dt_top = c_hh["high"]
                            level_of_4_val = dt_top
                            level_of_4_bar = hh_bar
                            level_of_4_active = True
                else:
                    has_bos_after_choch = False
                    last_draw_bar = bar_index

                    choch_text, choch_col, should_draw = get_choch_props(consecutive_choch_count, False)
                    if should_draw:
                        x1_bar = confirmed_hl_bar if confirmed_hl_bar is not None else start_lookback_bar
                        lines.append({
                            "id": f"choch_hl_{bar_index}",
                            "x1": candles[x1_bar]["time"],
                            "y1": confirmed_hl_val,
                            "x2": c_curr["time"],
                            "y2": confirmed_hl_val,
                            "color": choch_col,
                            "style": "solid",
                            "type": choch_text
                        })
                        avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                        labels.append({
                            "id": f"lbl_choch_hl_{bar_index}",
                            "x": avg_time,
                            "y": confirmed_hl_val,
                            "text": choch_text,
                            "color": choch_col,
                            "textColor": "#ffffff",
                            "style": "label_down"
                        })

                    if self.show_tjl_boxes:
                        if last_tjl1_box_idx is not None and last_tjl1_box_idx < len(boxes):
                            boxes[last_tjl1_box_idx]["text"] = "QML"
                            boxes[last_tjl1_box_idx]["is_bullish"] = False
                            boxes[last_tjl1_box_idx]["active_start_bar"] = bar_index
                        if last_tjl2_box_idx is not None and last_tjl2_box_idx < len(boxes):
                            boxes[last_tjl2_box_idx]["text"] = "SBR"
                            boxes[last_tjl2_box_idx]["is_bullish"] = False
                            boxes[last_tjl2_box_idx]["active_start_bar"] = bar_index

                        hh_bar = point_c_bar if (point_c_bar is not None and point_c_bar >= point_a_bar) else None
                        if hh_bar is None:
                            _, hh_bar = get_highest_peak(point_a_bar, max(point_a_bar, bar_index - 1))
                        
                        if 0 <= hh_bar < n:
                            c_hh = candles[hh_bar]
                            dt_top = c_hh["high"]
                            dt_bot = max(c_hh["open"], c_hh["close"])
                            right_time = get_box_right_time(hh_bar, bar_index)
                            
                            c_fill, c_border, is_bull, l_type = get_box_style(False)
                            last_double_box_idx = len(boxes)
                            boxes.append({
                                "id": f"box_dt_{bar_index}",
                                "created_bar": bar_index,
                                "left": c_hh["time"],
                                "top": dt_top,
                                "right": right_time,
                                "bottom": dt_bot,
                                "color": c_fill,
                                "borderColor": c_border,
                                "text": "Double Top",
                                "is_bullish": is_bull,
                                "level_type": l_type
                            })
                        set_cycle_boxes_polarity(False)

                    dual_choch_target_val = point_c_val
                    dual_choch_target_bar = point_c_bar
                    dual_choch_active = True
                    point_c_active = False

                point_a_bar = bar_index
                waiting_for_2rtr = True

            elif trend == -1 and confirmed_lh_active and confirmed_lh_val is not None and c_prev["close"] > confirmed_lh_val and c_curr["close"] > confirmed_lh_val:
                confirmed_lh_active = False
                trend = 1
                consecutive_choch_count += 1

                if not has_bos_after_choch:
                    has_bos_after_choch = True
                    dual_choch_active = False
                    point_c_active = False
                    last_draw_bar = bar_index

                    choch_text, choch_col, should_draw = get_choch_props(consecutive_choch_count, True)
                    if should_draw:
                        x1_bar = confirmed_lh_bar if confirmed_lh_bar is not None else start_lookback_bar
                        lines.append({
                            "id": f"choch_lh_{bar_index}",
                            "x1": candles[x1_bar]["time"],
                            "y1": confirmed_lh_val,
                            "x2": c_curr["time"],
                            "y2": confirmed_lh_val,
                            "color": choch_col,
                            "style": "solid",
                            "type": choch_text
                        })
                        avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                        labels.append({
                            "id": f"lbl_choch_lh_{bar_index}",
                            "x": avg_time,
                            "y": confirmed_lh_val,
                            "text": choch_text,
                            "color": choch_col,
                            "textColor": "#ffffff",
                            "style": "label_down"
                        })

                    ll_bar = point_c_bar if (point_c_bar is not None and point_c_bar >= point_a_bar) else None
                    if ll_bar is None:
                        _, ll_bar = get_lowest_trough(point_a_bar, max(point_a_bar, bar_index - 1))
                    
                        if self.show_tjl_boxes:
                            if last_tjl1_box_idx is not None and last_tjl1_box_idx < len(boxes):
                                boxes[last_tjl1_box_idx]["text"] = "A+"
                                boxes[last_tjl1_box_idx]["active_start_bar"] = bar_index
                            if last_tjl2_box_idx is not None and last_tjl2_box_idx < len(boxes):
                                boxes[last_tjl2_box_idx]["text"] = "RBS"
                                boxes[last_tjl2_box_idx]["in_dual_choch"] = True
                                boxes[last_tjl2_box_idx]["active_start_bar"] = bar_index
                            if last_double_box_idx is not None and last_double_box_idx < len(boxes):
                                boxes[last_double_box_idx]["text"] = "LEVEL of 3"
                                boxes[last_double_box_idx]["active_start_bar"] = bar_index

                            if 0 <= ll_bar < n:
                                c_ll = candles[ll_bar]
                                db_top = min(c_ll["open"], c_ll["close"])
                                db_bot = c_ll["low"]
                                right_time = get_box_right_time(ll_bar, bar_index)
                                c_fill, c_border, is_bull, l_type = get_box_style(True)
                                last_level4_box_idx = len(boxes)
                                boxes.append({
                                    "id": f"box_l4_lh_{bar_index}",
                                    "created_bar": bar_index,
                                    "left": c_ll["time"],
                                    "top": db_top,
                                    "right": right_time,
                                    "bottom": db_bot,
                                    "color": c_fill,
                                    "borderColor": c_border,
                                    "text": "level of 4",
                                    "is_bullish": is_bull,
                                    "level_type": l_type
                                })
                            set_cycle_boxes_polarity(True)

                        if 0 <= ll_bar < n:
                            c_ll = candles[ll_bar]
                            db_bot = c_ll["low"]
                            level_of_4_val = db_bot
                            level_of_4_bar = ll_bar
                            level_of_4_active = True
                else:
                    has_bos_after_choch = False
                    last_draw_bar = bar_index

                    choch_text, choch_col, should_draw = get_choch_props(consecutive_choch_count, True)
                    if should_draw:
                        x1_bar = confirmed_lh_bar if confirmed_lh_bar is not None else start_lookback_bar
                        lines.append({
                            "id": f"choch_lh_{bar_index}",
                            "x1": candles[x1_bar]["time"],
                            "y1": confirmed_lh_val,
                            "x2": c_curr["time"],
                            "y2": confirmed_lh_val,
                            "color": choch_col,
                            "style": "solid",
                            "type": choch_text
                        })
                        avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                        labels.append({
                            "id": f"lbl_choch_lh_{bar_index}",
                            "x": avg_time,
                            "y": confirmed_lh_val,
                            "text": choch_text,
                            "color": choch_col,
                            "textColor": "#ffffff",
                            "style": "label_down"
                        })

                    if self.show_tjl_boxes:
                        if last_tjl1_box_idx is not None and last_tjl1_box_idx < len(boxes):
                            boxes[last_tjl1_box_idx]["text"] = "QML"
                            boxes[last_tjl1_box_idx]["is_bullish"] = True
                            boxes[last_tjl1_box_idx]["active_start_bar"] = bar_index
                        if last_tjl2_box_idx is not None and last_tjl2_box_idx < len(boxes):
                            boxes[last_tjl2_box_idx]["text"] = "RBS"
                            boxes[last_tjl2_box_idx]["is_bullish"] = True
                            boxes[last_tjl2_box_idx]["active_start_bar"] = bar_index

                        ll_bar = point_c_bar if (point_c_bar is not None and point_c_bar >= point_a_bar) else None
                        if ll_bar is None:
                            _, ll_bar = get_lowest_trough(point_a_bar, max(point_a_bar, bar_index - 1))
                        
                        if 0 <= ll_bar < n:
                            c_ll = candles[ll_bar]
                            db_top = min(c_ll["open"], c_ll["close"])
                            db_bot = c_ll["low"]
                            right_time = get_box_right_time(ll_bar, bar_index)
                            
                            c_fill, c_border, is_bull, l_type = get_box_style(True)
                            last_double_box_idx = len(boxes)
                            boxes.append({
                                "id": f"box_db_{bar_index}",
                                "created_bar": bar_index,
                                "left": c_ll["time"],
                                "top": db_top,
                                "right": right_time,
                                "bottom": db_bot,
                                "color": c_fill,
                                "borderColor": c_border,
                                "text": "Double Bottom",
                                "is_bullish": is_bull,
                                "level_type": l_type
                            })
                        set_cycle_boxes_polarity(True)

                    dual_choch_target_val = point_c_val
                    dual_choch_target_bar = point_c_bar
                    dual_choch_active = True
                    point_c_active = False

                point_a_bar = bar_index
                waiting_for_2rtr = True

            # 5. BOS Evaluation (Break of Point C & TJL Rectangles)
            if trend == 1 and point_c_active and point_c_val is not None and c_curr["close"] > point_c_val and last_draw_bar != bar_index:
                point_c_active = False
                has_bos_after_choch = True
                dual_choch_active = False
                level_of_4_active = False
                consecutive_choch_count = 0  # Valid BOS resets consecutive CHoCH counter
                last_draw_bar = bar_index
                last_double_box_idx = None
                last_level4_box_idx = None

                if self.show_bos:
                    x1_bar = point_c_bar if point_c_bar is not None else start_lookback_bar
                    lines.append({
                        "id": f"bos_bull_{bar_index}",
                        "x1": candles[x1_bar]["time"],
                        "y1": point_c_val,
                        "x2": c_curr["time"],
                        "y2": point_c_val,
                        "color": "#26a69a",
                        "style": "solid",
                        "type": "BOS"
                    })
                    avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                    labels.append({
                        "id": f"lbl_bos_bull_{bar_index}",
                        "x": avg_time,
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

                if self.show_tjl_boxes:
                    pc_bar_idx = point_c_bar if point_c_bar is not None else start_lookback_bar
                    if 0 <= pc_bar_idx < n:
                        c_pc = candles[pc_bar_idx]
                        tjl1_top = c_pc["high"]
                        tjl1_bot = max(c_pc["open"], c_pc["close"])
                        right_time = get_box_right_time(pc_bar_idx, bar_index)
                        
                        c_fill, c_border, is_bull, l_type = get_box_style(True)
                        last_tjl1_box_idx = len(boxes)
                        boxes.append({
                            "id": f"tjl1_{bar_index}",
                            "created_bar": bar_index,
                            "left": c_pc["time"],
                            "top": tjl1_top,
                            "right": right_time,
                            "bottom": tjl1_bot,
                            "color": c_fill,
                            "borderColor": c_border,
                            "text": "TJL1",
                            "is_bullish": is_bull,
                            "level_type": l_type
                        })

                    if 0 <= hl_bar < n:
                        c_hl = candles[hl_bar]
                        tjl2_top = min(c_hl["open"], c_hl["close"])
                        tjl2_bot = c_hl["low"]
                        right_time = get_box_right_time(hl_bar, bar_index)
                        
                        c_fill, c_border, is_bull, l_type = get_box_style(True)
                        last_tjl2_box_idx = len(boxes)
                        boxes.append({
                            "id": f"tjl2_{bar_index}",
                            "created_bar": bar_index,
                            "left": c_hl["time"],
                            "top": tjl2_top,
                            "right": right_time,
                            "bottom": tjl2_bot,
                            "color": c_fill,
                            "borderColor": c_border,
                            "text": "TJL2",
                            "is_bullish": is_bull,
                            "level_type": l_type
                        })

                    set_cycle_boxes_polarity(True)

                point_a_bar = bar_index
                waiting_for_2rtr = True

            elif trend == -1 and point_c_active and point_c_val is not None and c_curr["close"] < point_c_val and last_draw_bar != bar_index:
                point_c_active = False
                has_bos_after_choch = True
                dual_choch_active = False
                level_of_4_active = False
                consecutive_choch_count = 0  # Valid BOS resets consecutive CHoCH counter
                last_draw_bar = bar_index
                last_double_box_idx = None
                last_level4_box_idx = None

                if self.show_bos:
                    x1_bar = point_c_bar if point_c_bar is not None else start_lookback_bar
                    lines.append({
                        "id": f"bos_bear_{bar_index}",
                        "x1": candles[x1_bar]["time"],
                        "y1": point_c_val,
                        "x2": c_curr["time"],
                        "y2": point_c_val,
                        "color": "#ef5350",
                        "style": "solid",
                        "type": "BOS"
                    })
                    avg_time = (candles[x1_bar]["time"] + c_curr["time"]) // 2
                    labels.append({
                        "id": f"lbl_bos_bear_{bar_index}",
                        "x": avg_time,
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

                if self.show_tjl_boxes:
                    pc_bar_idx = point_c_bar if point_c_bar is not None else start_lookback_bar
                    if 0 <= pc_bar_idx < n:
                        c_pc = candles[pc_bar_idx]
                        tjl1_top = min(c_pc["open"], c_pc["close"])
                        tjl1_bot = c_pc["low"]
                        right_time = get_box_right_time(pc_bar_idx, bar_index)
                        
                        c_fill, c_border, is_bull, l_type = get_box_style(False)
                        last_tjl1_box_idx = len(boxes)
                        boxes.append({
                            "id": f"tjl1_{bar_index}",
                            "created_bar": bar_index,
                            "left": c_pc["time"],
                            "top": tjl1_top,
                            "right": right_time,
                            "bottom": tjl1_bot,
                            "color": c_fill,
                            "borderColor": c_border,
                            "text": "TJL1",
                            "is_bullish": is_bull,
                            "level_type": l_type
                        })

                    if 0 <= lh_bar < n:
                        c_lh = candles[lh_bar]
                        tjl2_top = c_lh["high"]
                        tjl2_bot = max(c_lh["open"], c_lh["close"])
                        right_time = get_box_right_time(lh_bar, bar_index)
                        
                        c_fill, c_border, is_bull, l_type = get_box_style(False)
                        last_tjl2_box_idx = len(boxes)
                        boxes.append({
                            "id": f"tjl2_{bar_index}",
                            "created_bar": bar_index,
                            "left": c_lh["time"],
                            "top": tjl2_top,
                            "right": right_time,
                            "bottom": tjl2_bot,
                            "color": c_fill,
                            "borderColor": c_border,
                            "text": "TJL2",
                            "is_bullish": is_bull,
                            "level_type": l_type
                        })

                    set_cycle_boxes_polarity(False)

                point_a_bar = bar_index
                waiting_for_2rtr = True

        # 6. Render Dynamic Active Structure Levels (shortened to active_swing_length_bars)
        if self.show_active_swings:
            last_candle_idx = n - 1
            if trend == 1:
                if point_c_active and point_c_val is not None:
                    x1_bar = point_c_bar if point_c_bar is not None else start_lookback_bar
                    x2_bar = n - 1
                    active_levels.append({
                        "id": "active_high",
                        "x1": candles[x1_bar]["time"],
                        "y1": point_c_val,
                        "x2": candles[x2_bar]["time"],
                        "y2": point_c_val,
                        "color": "#ef5350",
                        "style": "dashed",
                        "type": "Active High"
                    })
                if confirmed_hl_active and confirmed_hl_val is not None:
                    x1_bar = confirmed_hl_bar if confirmed_hl_bar is not None else start_lookback_bar
                    x2_bar = n - 1
                    active_levels.append({
                        "id": "active_low",
                        "x1": candles[x1_bar]["time"],
                        "y1": confirmed_hl_val,
                        "x2": candles[x2_bar]["time"],
                        "y2": confirmed_hl_val,
                        "color": "#26a69a",
                        "style": "dashed",
                        "type": "Active Low"
                    })
            elif trend == -1:
                if point_c_active and point_c_val is not None:
                    x1_bar = point_c_bar if point_c_bar is not None else start_lookback_bar
                    x2_bar = n - 1
                    active_levels.append({
                        "id": "active_low",
                        "x1": candles[x1_bar]["time"],
                        "y1": point_c_val,
                        "x2": candles[x2_bar]["time"],
                        "y2": point_c_val,
                        "color": "#26a69a",
                        "style": "dashed",
                        "type": "Active Low"
                    })
                if confirmed_lh_active and confirmed_lh_val is not None:
                    x1_bar = confirmed_lh_bar if confirmed_lh_bar is not None else start_lookback_bar
                    x2_bar = n - 1
                    active_levels.append({
                        "id": "active_high",
                        "x1": candles[x1_bar]["time"],
                        "y1": confirmed_lh_val,
                        "x2": candles[x2_bar]["time"],
                        "y2": confirmed_lh_val,
                        "color": "#ef5350",
                        "style": "dashed",
                        "type": "Active High"
                    })

        # 7. Level Extension Rules:
        # Extend a level when price taps into it and gets rejected (does not close beyond).
        # When 2 consecutive candles close beyond the level boundary, the level breaks
        # and stops extending, freezing at the last valid tap just before the closing beyond.
        # Only extend: TJL2 in BOS, QML in CHoCH, RBS/SBR and A+ in Dual CHoCH.
        # Don't extend any other level (they remain strictly at their fixed origin width).
        def is_qualifying_level(b: Dict) -> bool:
            txt = b.get("text", "")
            if txt in ("QML", "TJL2", "A+"):
                return True
            if txt in ("RBS", "SBR"):
                return bool(b.get("in_dual_choch", False))
            return False

        if self.tjl_extend:
            time_to_idx = {c["time"]: i for i, c in enumerate(candles)}
            for box in boxes:
                left_idx = time_to_idx.get(box["left"], box.get("created_bar", 0))
                default_right_idx = min(n - 1, left_idx + self.box_width_bars)
                default_right_time = candles[default_right_idx]["time"]

                b_top = max(box["top"], box["bottom"])
                b_bot = min(box["top"], box["bottom"])
                is_bull = box.get("is_bullish", True)
                start_scan_bar = box.get("active_start_bar", box.get("created_bar", left_idx))

                if start_scan_bar is None or start_scan_bar >= n - 1:
                    box["right"] = default_right_time
                    continue

                first_valid_tap_bar = None
                last_valid_tap_bar = None
                consecutive_closes_beyond = 0
                box_cycles = []
                in_zone = False
                current_tap_bar = None
                break_bar = None

                for k in range(start_scan_bar + 1, n):
                    cand = candles[k]
                    c_prev = candles[k - 1] if k > 0 else cand

                    # Closed beyond level boundary check (breaks/invalidates level)
                    if is_bull:
                        closed_beyond = (cand["close"] < b_bot)
                    else:
                        closed_beyond = (cand["close"] > b_top)

                    if closed_beyond:
                        consecutive_closes_beyond += 1
                    else:
                        consecutive_closes_beyond = 0

                    if not in_zone:
                        # Check if price taps / enters the zone from the valid entry side:
                        # For buying level: price enters from above (cand["low"] <= b_top and (c_prev["close"] >= b_top or cand["open"] >= b_top))
                        # For selling level: price enters from below (cand["high"] >= b_bot and (c_prev["close"] <= b_bot or cand["open"] <= b_bot))
                        if is_bull:
                            enters = (cand["low"] <= b_top and (c_prev["close"] >= b_top or cand["open"] >= b_top))
                        else:
                            enters = (cand["high"] >= b_bot and (c_prev["close"] <= b_bot or cand["open"] <= b_bot))

                        if enters:
                            if first_valid_tap_bar is None:
                                first_valid_tap_bar = k
                            if closed_beyond:
                                # Candle tapped into the zone and immediately closed beyond it on the same bar
                                exit_pos = "below" if is_bull else "above"
                                exit_y = b_bot if is_bull else b_top
                                box_cycles.append({
                                    "tap_bar": k,
                                    "exit_bar": k,
                                    "exit_pos": exit_pos,
                                    "exit_y": exit_y
                                })
                                in_zone = False
                                current_tap_bar = None
                            else:
                                in_zone = True
                                current_tap_bar = k
                                last_valid_tap_bar = k
                    else:
                        # Price is currently inside the zone / tapping
                        if closed_beyond:
                            # 1 candle closing beyond exits immediately at this candle
                            exit_pos = "below" if is_bull else "above"
                            exit_y = b_bot if is_bull else b_top
                            box_cycles.append({
                                "tap_bar": current_tap_bar,
                                "exit_bar": k,
                                "exit_pos": exit_pos,
                                "exit_y": exit_y
                            })
                            in_zone = False
                            current_tap_bar = None
                        else:
                            last_valid_tap_bar = k
                            # Check exit:
                            # As per rule: wicks beyond opposite boundary (wick < b_bot for buying, wick > b_top for selling)
                            # are NOT considered zone exit or tapping finished!
                            # Exit ONLY happens when price goes out from the side it entered!
                            if is_bull:
                                # Buying level: entered from top side.
                                # Exits when price goes out above b_top (closes above or at b_top, or low > b_top)
                                exits = (cand["close"] >= b_top or cand["low"] > b_top)
                                if exits:
                                    in_zone = False
                                    box_cycles.append({
                                        "tap_bar": current_tap_bar,
                                        "exit_bar": k,
                                        "exit_pos": "above",
                                        "exit_y": b_top
                                    })
                                    current_tap_bar = None
                            else:
                                # Selling level: entered from bottom side.
                                # Exits when price goes out below b_bot (closes below or at b_bot, or high < b_bot)
                                exits = (cand["close"] <= b_bot or cand["high"] < b_bot)
                                if exits:
                                    in_zone = False
                                    box_cycles.append({
                                        "tap_bar": current_tap_bar,
                                        "exit_bar": k,
                                        "exit_pos": "below",
                                        "exit_y": b_bot
                                    })
                                    current_tap_bar = None

                    if consecutive_closes_beyond >= 2:
                        # 2 consecutive candles closed beyond opposite level boundary.
                        break_bar = k
                        break

                if in_zone and current_tap_bar is not None:
                    box_cycles.append({
                        "tap_bar": current_tap_bar,
                        "exit_bar": None,
                        "exit_pos": None,
                        "exit_y": None
                    })

                box["cycles"] = box_cycles
                box["is_tapped"] = (first_valid_tap_bar is not None)
                box["is_broken"] = (consecutive_closes_beyond >= 2)

                if box["is_broken"]:
                    b_bar = break_bar if break_bar is not None else n - 1
                    box["right"] = candles[b_bar]["time"]
                else:
                    box["right"] = candles[n - 1]["time"]

                if last_valid_tap_bar is not None:
                    box["tap_bar"] = last_valid_tap_bar
                    box["tap_time"] = candles[last_valid_tap_bar]["time"]
                    box["first_tap_bar"] = first_valid_tap_bar
                    box["first_tap_time"] = candles[first_valid_tap_bar]["time"]

        # 8. Overlap Resolution:
        # Only stop extending levels upon merge if the extending level gets merged or struck by:
        # - QML of CHoCH
        # - TJL2 of BOS
        # - A+ of Dual CHoCH
        # - RBS/SBR of Dual CHoCH
        # No other levels (e.g. TJL1, Double Top/Bottom, Level of 3, level of 4) can stop an extending level.
        for i in range(len(boxes)):
            b1 = boxes[i]
            # Only extending levels can be stopped upon merge
            if not is_qualifying_level(b1):
                continue

            top1 = max(b1["top"], b1["bottom"])
            bot1 = min(b1["top"], b1["bottom"])
            t1_left = b1["left"]
            t1_right = b1["right"]

            earliest_cutoff = t1_right
            merged_at_time = None
            for j in range(len(boxes)):
                if i == j:
                    continue
                b2 = boxes[j]
                # Only qualifying levels can stop extending levels
                if not is_qualifying_level(b2):
                    continue

                t2_left = b2["left"]
                # Second level comes into view strictly after first level
                if t2_left <= t1_left:
                    continue

                top2 = max(b2["top"], b2["bottom"])
                bot2 = min(b2["top"], b2["bottom"])

                # Check if they share vertical price range
                if max(bot1, bot2) < min(top1, top2):
                    # If b1 extends up to or past the moment b2 comes into view
                    if t1_right >= t2_left:
                        if t2_left < earliest_cutoff or merged_at_time is None:
                            if t2_left <= earliest_cutoff:
                                earliest_cutoff = t2_left
                                merged_at_time = t2_left

            if merged_at_time is not None:
                b1["right"] = earliest_cutoff
                b1["merged_at"] = merged_at_time

        # 9. Level Tap & Exit Labels:
        # For extendable levels (TJL2, QML, A+, and RBS/SBR in Dual CHoCH),
        # when price taps the level, show a label over the point where price entered the zone,
        # and when price leaves the zone, mark that leaving point.
        # If price taps more than once, also mention every subsequent tap and exit.
        # EXCLUSION: When 2 levels merge (1 level ends because another level has started there),
        # do NOT record tap or exit at or after the merger point!
        for idx, box in enumerate(boxes):
            if not is_qualifying_level(box):
                continue
            if not box.get("is_tapped"):
                continue

            cycles = box.get("cycles", [])
            if not cycles:
                continue

            merged_at = box.get("merged_at")
            box_right = box.get("right")
            text = box.get("text", "")
            is_bull = box.get("is_bullish", True)
            b_top = max(box["top"], box["bottom"])
            b_bot = min(box["top"], box["bottom"])
            tap_color = "#26a69a" if is_bull else "#ef5350"

            for cycle in cycles:
                t_bar = cycle.get("tap_bar")
                if t_bar is None or t_bar >= n:
                    continue

                tap_time = candles[t_bar]["time"]

                # When 2 levels merge (1 level ends because another level has started there):
                # Don't record tap at or after the merger point!
                if merged_at is not None and tap_time >= merged_at:
                    continue

                # Only display if tap occurred while level was active
                if box_right is not None and tap_time > box_right:
                    continue

                c_cand = candles[t_bar]
                c_prev = candles[t_bar - 1] if t_bar > 0 else c_cand

                if c_prev["close"] < b_bot:
                    entry_y = b_bot
                elif c_prev["close"] > b_top:
                    entry_y = b_top
                else:
                    entry_y = b_bot if not is_bull else b_top

                entry_pos = "below" if c_prev["close"] < b_bot else ("above" if c_prev["close"] > b_top else ("below" if not is_bull else "above"))

                labels.append({
                    "id": f"lbl_tap_{box.get('id', idx)}_{t_bar}",
                    "x": tap_time,
                    "y": entry_y,
                    "text": f"{text} Tap",
                    "color": tap_color,
                    "textColor": "#ffffff",
                    "position": entry_pos,
                    "style": "label_down" if not is_bull else "label_up"
                })

                e_bar = cycle.get("exit_bar")
                if e_bar is not None and e_bar < n:
                    exit_time = candles[e_bar]["time"]

                    # When 2 levels merge (1 level ends because another level has started there):
                    # Don't record exit at or after the merger point!
                    if merged_at is not None and exit_time >= merged_at:
                        continue

                    exit_y = cycle.get("exit_y")
                    exit_pos = cycle.get("exit_pos", "below")

                    labels.append({
                        "id": f"lbl_exit_{box.get('id', idx)}_{e_bar}",
                        "x": exit_time,
                        "y": exit_y,
                        "text": f"{text} Exit",
                        "color": tap_color,
                        "textColor": "#ffffff",
                        "position": exit_pos,
                        "style": "label_down" if exit_pos == "below" else "label_up"
                    })

        return {
            "lines": lines,
            "labels": labels,
            "boxes": boxes,
            "markers": markers,
            "active_levels": active_levels,
            "trend": "Uptrend" if trend == 1 else ("Downtrend" if trend == -1 else "Neutral")
        }

