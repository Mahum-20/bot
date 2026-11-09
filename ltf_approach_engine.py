import os

import json

import logging

from typing import List, Dict, Optional, Tuple, Any

from htf_engine import HTFEngine, is_qualifying_htf_zone, is_htf_box_active

from pattern_scanner import is_valid_bullish_engulfing, is_valid_bearish_engulfing



logger = logging.getLogger("LTF_Approach_Engine")



def clean_box_name(raw_text: str) -> str:

    """Strip Demand, Supply, Zone, and bracket clutter."""

    if not raw_text:

        return "Level"

    name = str(raw_text).replace("[", "").replace("]", "").strip()

    words = ["demand", "supply", "zone", "tapped:", "new:"]

    for w in words:

        name = name.replace(w, "").replace(w.capitalize(), "").replace(w.upper(), "")

    name = name.strip()

    return name if name else "Level"





def detect_internal_5_waves(

    candles: List[Dict],

    tap_idx: int,

    is_bullish: bool,

    htf_box: Optional[Dict] = None

) -> Dict[str, Any]:

    """

    Tracks 5-wave internal structure starting strictly from the extreme point inside the tapped zone:

      - Demand Zone (is_bullish=True):

        Anchor starts at lowest low in zone. Any new lower low resets waves to 0.

        Wave 1: 1st bearish 2-candle retracement (2RTR)

        Wave 2: Bullish leg causing internal BOS (breaks Wave 1 peak)

        Wave 3: 2nd bearish 2-candle retracement -> establishes "Level of 3" (upper wick of Wave 3 peak)

        Wave 4: Bullish leg causing internal BOS -> establishes "Level of 4" (lower wick of ending candle of Wave 3 / starting candle of Wave 4)

        Wave 5: Initiated when 3rd bearish 2-candle retracement confirms

        Invalidation: If price breaks below anchor low, setup is invalidated.



      - Supply Zone (is_bullish=False):

        Inverted from highest high in zone. Any new higher high resets waves to 0.

        Wave 1: 1st bullish 2-candle retracement

        Wave 2: Bearish leg causing internal BOS (breaks Wave 1 trough)

        Wave 3: 2nd bullish 2-candle retracement -> establishes "Level of 3" (lower wick of Wave 3 trough)

        Wave 4: Bearish leg causing internal BOS -> establishes "Level of 4" (upper wick of ending candle of Wave 3 / starting candle of Wave 4)

        Wave 5: Initiated when 3rd bullish 2-candle retracement confirms

        Invalidation: If price breaks above anchor high, setup is invalidated.

    """

    n = len(candles)

    if tap_idx >= n:

        tap_idx = max(0, n - 1)



    box_top = max(htf_box.get("top", 0), htf_box.get("bottom", 0)) if htf_box else None

    box_bot = min(htf_box.get("top", 0), htf_box.get("bottom", 0)) if htf_box else None

    ref_p = box_top or (candles[0]["close"] if candles else 100.0)

    buffer = (box_top * 0.0005) if box_top else (ref_p * 0.0005)



    def is_breakout_above(close_val, peak_val):

        buf = peak_val * 0.00002

        return close_val > (peak_val + buf)



    def is_breakout_below(close_val, trough_val):

        buf = trough_val * 0.00002

        return close_val < (trough_val - buf)



    if is_bullish:

        anchor_idx = tap_idx

        anchor_val = candles[tap_idx]["low"]

        state = 0



        peak_1_val = None

        peak_1_idx = None

        trough_1_val = None

        trough_1_idx = None

        wave_2_break_idx = None



        peak_2_val = None

        peak_2_idx = None

        trough_2_val = None

        trough_2_idx = None

        wave_4_break_idx = None



        level_3 = None

        level_4 = None

        wave_5_idx = None

        waves = []



        for i in range(tap_idx, n):

            c_curr = candles[i]

            c_prev = candles[i - 1] if i > 0 else c_curr



            # 2-candle retracement check (HTF 2RTR standard)

            is_red1 = c_prev["close"] < c_prev["open"]

            is_red2 = c_curr["close"] < c_curr["open"]

            bearish_2rtr = is_red1 and is_red2 and (c_curr["close"] < c_prev["low"])



            # Reset on new lower low inside zone

            if c_curr["low"] < anchor_val:

                anchor_val = c_curr["low"]

                anchor_idx = i

                state = 0

                peak_1_val = None

                peak_1_idx = None

                trough_1_val = None

                trough_1_idx = None

                wave_2_break_idx = None

                peak_2_val = None

                peak_2_idx = None

                trough_2_val = None

                trough_2_idx = None

                wave_4_break_idx = None

                level_3 = None

                level_4 = None

                wave_5_idx = None

                waves = []

                continue



            if state == 0:

                if bearish_2rtr and i > anchor_idx:

                    highs = [candles[j]["high"] for j in range(anchor_idx, i + 1)]

                    if highs:

                        peak_1_val = max(highs)

                        peak_1_idx = anchor_idx + highs.index(peak_1_val)

                        trough_1_val = c_curr["low"]

                        trough_1_idx = i

                        waves.append({

                            "wave": 1,

                            "type": "peak",

                            "val": peak_1_val,

                            "bar": peak_1_idx,

                            "time": candles[peak_1_idx]["time"]

                        })

                        state = 1



            elif state == 1:

                if c_curr["low"] < (trough_1_val or float('inf')):

                    trough_1_val = c_curr["low"]

                    trough_1_idx = i



                if peak_1_val is not None and is_breakout_above(c_curr["close"], peak_1_val):

                    wave_2_break_idx = i

                    waves.append({

                        "wave": 2,

                        "type": "bos",

                        "val": c_curr["close"],

                        "bar": i,

                        "time": c_curr["time"]

                    })

                    state = 2



            elif state == 2:

                if bearish_2rtr and wave_2_break_idx is not None and i > wave_2_break_idx:

                    search_start = trough_1_idx if trough_1_idx is not None else wave_2_break_idx

                    highs_3 = [candles[j]["high"] for j in range(search_start, i + 1)]

                    if highs_3:

                        peak_2_val = max(highs_3)

                        peak_2_idx = search_start + highs_3.index(peak_2_val)



                        # Retracement starts from the peak or breakout, whichever is later

                        retrace_start = max(peak_2_idx, wave_2_break_idx)

                        lows_sub = [candles[j]["low"] for j in range(retrace_start, i + 1)]

                        trough_2_val = min(lows_sub)

                        trough_2_idx = retrace_start + lows_sub.index(trough_2_val)



                        top_p = candles[peak_2_idx]["high"]

                        bot_p = max(candles[peak_2_idx]["open"], candles[peak_2_idx]["close"])

                        if abs(top_p - bot_p) < 1.0:

                            bot_p = top_p - 2.0



                        level_3 = {

                            "price": peak_2_val,

                            "top": top_p,

                            "bottom": bot_p,

                            "time": candles[peak_2_idx]["time"],

                            "bar": peak_2_idx,

                            "text": "Level of 3"

                        }

                        waves.append({

                            "wave": 3,

                            "type": "peak",

                            "val": peak_2_val,

                            "bar": peak_2_idx,

                            "time": candles[peak_2_idx]["time"]

                        })

                        state = 3



            elif state == 3:

                # Track the lowest trough of the Wave 3 retracement

                retrace_start = max(peak_2_idx, wave_2_break_idx) if peak_2_idx is not None else wave_2_break_idx

                if i >= retrace_start:

                    if trough_2_val is None or c_curr["low"] < trough_2_val:

                        trough_2_val = c_curr["low"]

                        trough_2_idx = i



                if peak_2_val is not None and is_breakout_above(c_curr["close"], peak_2_val):

                    wave_4_break_idx = i

                    # Level of 4 is at lowest wick of ending candle of Wave 3 / starting candle of Wave 4

                    retrace_start = max(peak_2_idx, wave_2_break_idx)

                    lows_sub = [candles[j]["low"] for j in range(retrace_start, wave_4_break_idx + 1)]

                    min_low = min(lows_sub)

                    tr_bar = retrace_start + lows_sub.index(min_low)

                    trough_2_val = min_low

                    trough_2_idx = tr_bar



                    bot_p = candles[tr_bar]["low"]

                    top_p = min(candles[tr_bar]["open"], candles[tr_bar]["close"])

                    if abs(top_p - bot_p) < 1.0:

                        top_p = bot_p + 2.0



                    level_4 = {

                        "price": trough_2_val,

                        "top": top_p,

                        "bottom": bot_p,

                        "time": candles[tr_bar]["time"],

                        "bar": tr_bar,

                        "text": "Level of 4"

                    }

                    waves.append({

                        "wave": 4,

                        "type": "bos",

                        "val": c_curr["close"],

                        "bar": i,

                        "time": c_curr["time"]

                    })

                    state = 4



            elif state == 4:

                if bearish_2rtr and wave_4_break_idx is not None and i > wave_4_break_idx:

                    highs_5 = [candles[j]["high"] for j in range(wave_4_break_idx, i + 1)]

                    if highs_5:

                        peak_3_val = max(highs_5)

                        peak_3_idx = wave_4_break_idx + highs_5.index(peak_3_val)

                        wave_5_idx = peak_3_idx

                        waves.append({

                            "wave": 5,

                            "type": "peak",

                            "val": peak_3_val,

                            "bar": peak_3_idx,

                            "time": candles[peak_3_idx]["time"]

                        })

                    else:

                        wave_5_idx = i

                        waves.append({

                            "wave": 5,

                            "type": "peak",

                            "val": c_curr["close"],

                            "bar": i,

                            "time": c_curr["time"]

                        })

                    state = 5

                    break



        # Check invalidation

        is_invalidated = False

        if state == 5:

            for j in range(wave_5_idx, n):

                if candles[j]["low"] < anchor_val:

                    is_invalidated = True

                    break



        completed = (state == 5 and level_3 is not None and level_4 is not None and not is_invalidated)

        if box_top is not None and anchor_val > box_top + buffer:

            completed = False

        return {

            "completed": completed,

            "anchor_idx": anchor_idx,

            "anchor_val": anchor_val,

            "anchor_time": candles[anchor_idx]["time"],

            "level_3": level_3,

            "level_4": level_4,

            "wave_5_idx": wave_5_idx,

            "wave_5_time": candles[wave_5_idx]["time"] if wave_5_idx else None,

            "waves": waves,

            "is_invalidated": is_invalidated

        }



    else:

        # Supply Zone: Inverted

        anchor_idx = tap_idx

        anchor_val = candles[tap_idx]["high"]

        state = 0



        trough_1_val = None

        trough_1_idx = None

        peak_1_val = None

        peak_1_idx = None

        wave_2_break_idx = None



        trough_2_val = None

        trough_2_idx = None

        peak_2_val = None

        peak_2_idx = None

        wave_4_break_idx = None



        level_3 = None

        level_4 = None

        wave_5_idx = None

        waves = []



        for i in range(tap_idx, n):

            c_curr = candles[i]

            c_prev = candles[i - 1] if i > 0 else c_curr



            # 2-candle retracement check (HTF 2RTR standard)

            is_green1 = c_prev["close"] > c_prev["open"]

            is_green2 = c_curr["close"] > c_curr["open"]

            bullish_2rtr = is_green1 and is_green2 and (c_curr["close"] > c_prev["high"])



            # Reset on new higher high inside zone

            if c_curr["high"] > anchor_val:

                anchor_val = c_curr["high"]

                anchor_idx = i

                state = 0

                trough_1_val = None

                trough_1_idx = None

                peak_1_val = None

                peak_1_idx = None

                wave_2_break_idx = None

                trough_2_val = None

                trough_2_idx = None

                peak_2_val = None

                peak_2_idx = None

                wave_4_break_idx = None

                level_3 = None

                level_4 = None

                wave_5_idx = None

                waves = []

                continue



            if state == 0:

                if bullish_2rtr and i > anchor_idx:

                    lows = [candles[j]["low"] for j in range(anchor_idx, i + 1)]

                    if lows:

                        trough_1_val = min(lows)

                        trough_1_idx = anchor_idx + lows.index(trough_1_val)

                        peak_1_val = c_curr["high"]

                        peak_1_idx = i

                        waves.append({

                            "wave": 1,

                            "type": "trough",

                            "val": trough_1_val,

                            "bar": trough_1_idx,

                            "time": candles[trough_1_idx]["time"]

                        })

                        state = 1



            elif state == 1:

                if c_curr["high"] > (peak_1_val or float('-inf')):

                    peak_1_val = c_curr["high"]

                    peak_1_idx = i



                if trough_1_val is not None and is_breakout_below(c_curr["close"], trough_1_val):

                    wave_2_break_idx = i

                    waves.append({

                        "wave": 2,

                        "type": "bos",

                        "val": c_curr["close"],

                        "bar": i,

                        "time": c_curr["time"]

                    })

                    state = 2



            elif state == 2:

                if bullish_2rtr and wave_2_break_idx is not None and i > wave_2_break_idx:

                    search_start = peak_1_idx if peak_1_idx is not None else wave_2_break_idx

                    lows_3 = [candles[j]["low"] for j in range(search_start, i + 1)]

                    if lows_3:

                        trough_2_val = min(lows_3)

                        trough_2_idx = search_start + lows_3.index(trough_2_val)



                        # Retracement starts from the trough or breakout, whichever is later

                        retrace_start = max(trough_2_idx, wave_2_break_idx)

                        highs_sub = [candles[j]["high"] for j in range(retrace_start, i + 1)]

                        peak_2_val = max(highs_sub)

                        peak_2_idx = retrace_start + highs_sub.index(peak_2_val)



                        bot_p = candles[trough_2_idx]["low"]

                        top_p = min(candles[trough_2_idx]["open"], candles[trough_2_idx]["close"])

                        if abs(top_p - bot_p) < 1.0:

                            top_p = bot_p + 2.0



                        level_3 = {

                            "price": trough_2_val,

                            "top": top_p,

                            "bottom": bot_p,

                            "time": candles[trough_2_idx]["time"],

                            "bar": trough_2_idx,

                            "text": "Level of 3"

                        }

                        waves.append({

                            "wave": 3,

                            "type": "trough",

                            "val": trough_2_val,

                            "bar": trough_2_idx,

                            "time": candles[trough_2_idx]["time"]

                        })

                        state = 3



            elif state == 3:

                # Track the highest peak of the Wave 3 retracement

                retrace_start = max(trough_2_idx, wave_2_break_idx) if trough_2_idx is not None else wave_2_break_idx

                if i >= retrace_start:

                    if peak_2_val is None or c_curr["high"] > peak_2_val:

                        peak_2_val = c_curr["high"]

                        peak_2_idx = i



                if trough_2_val is not None and is_breakout_below(c_curr["close"], trough_2_val):

                    wave_4_break_idx = i

                    # Level of 4 is at highest wick of ending candle of Wave 3 / starting candle of Wave 4

                    retrace_start = max(trough_2_idx, wave_2_break_idx)

                    highs_sub = [candles[j]["high"] for j in range(retrace_start, wave_4_break_idx + 1)]

                    max_high = max(highs_sub)

                    pk_bar = retrace_start + highs_sub.index(max_high)

                    peak_2_val = max_high

                    peak_2_idx = pk_bar



                    top_p = candles[pk_bar]["high"]

                    bot_p = max(candles[pk_bar]["open"], candles[pk_bar]["close"])

                    if abs(top_p - bot_p) < 1.0:

                        bot_p = top_p - 2.0



                    level_4 = {

                        "price": peak_2_val,

                        "top": top_p,

                        "bottom": bot_p,

                        "time": candles[pk_bar]["time"],

                        "bar": pk_bar,

                        "text": "Level of 4"

                    }

                    waves.append({

                        "wave": 4,

                        "type": "bos",

                        "val": c_curr["close"],

                        "bar": i,

                        "time": c_curr["time"]

                    })

                    state = 4



            elif state == 4:

                if bullish_2rtr and wave_4_break_idx is not None and i > wave_4_break_idx:

                    lows_5 = [candles[j]["low"] for j in range(wave_4_break_idx, i + 1)]

                    if lows_5:

                        trough_3_val = min(lows_5)

                        trough_3_idx = wave_4_break_idx + lows_5.index(trough_3_val)

                        wave_5_idx = trough_3_idx

                        waves.append({

                            "wave": 5,

                            "type": "trough",

                            "val": trough_3_val,

                            "bar": trough_3_idx,

                            "time": candles[trough_3_idx]["time"]

                        })

                    else:

                        wave_5_idx = i

                        waves.append({

                            "wave": 5,

                            "type": "trough",

                            "val": c_curr["close"],

                            "bar": i,

                            "time": c_curr["time"]

                        })

                    state = 5

                    break



        is_invalidated = False

        if state == 5:

            for j in range(wave_5_idx, n):

                if candles[j]["high"] > anchor_val:

                    is_invalidated = True

                    break



        completed = (state == 5 and level_3 is not None and level_4 is not None and not is_invalidated)

        if box_bot is not None and anchor_val < box_bot - buffer:

            completed = False

        return {

            "completed": completed,

            "anchor_idx": anchor_idx,

            "anchor_val": anchor_val,

            "anchor_time": candles[anchor_idx]["time"],

            "level_3": level_3,

            "level_4": level_4,

            "wave_5_idx": wave_5_idx,

            "wave_5_time": candles[wave_5_idx]["time"] if wave_5_idx else None,

            "waves": waves,

            "is_invalidated": is_invalidated

        }





def is_valid_tap_approach(box: Dict, candles: List[Dict], idx: int) -> bool:
    """
    Validates that a zone is tapped (candle intersects the zone boundary).
    Directional approach rules (Demand from above / Supply from below - MTF-003)
    have been removed per user instruction.
    """
    b_top = max(box.get("top", 0), box.get("bottom", 0))
    b_bot = min(box.get("top", 0), box.get("bottom", 0))
    c = candles[idx]
    return c["low"] <= b_top and c["high"] >= b_bot


def find_tapped_htf_box(

    target_time: int,

    ltf_candles: List[Dict],

    htf_boxes: List[Dict],

    htf_sec: int = 900

) -> Tuple[Optional[Dict], Optional[int]]:

    """

    Finds if any HTF box is tapped by the target candle or within its HTF parent bar.

    Enforces that Demand zones can only be tapped from upside, and Supply zones can only be tapped from downside.

    Returns (tapped_box, tap_ltf_index).

    """

    if not htf_boxes or not ltf_candles:

        return None, None



    if target_time <= 0:

        target_time = ltf_candles[-1]["time"]



    import bisect

    times = [c["time"] for c in ltf_candles]

    pos = bisect.bisect_left(times, target_time)

    if pos >= len(ltf_candles):

        target_idx = len(ltf_candles) - 1

    elif pos == 0:

        target_idx = 0

    else:

        target_idx = pos if abs(times[pos] - target_time) < abs(times[pos - 1] - target_time) else pos - 1



    if target_idx is None:

        return None, None



    # Step 1: Check if targeted candle itself tapped any HTF zone from the valid side

    c_target = ltf_candles[target_idx]

    c_target_time = c_target["time"]



    for b in htf_boxes:

        if not is_htf_box_active(b, c_target_time):

            continue

        b_left = b.get("left") or b.get("created_time") or 0

        b_right = (b.get("mitigated_time") or b.get("right") or 9999999999) if (b.get("is_mitigated") or b.get("is_broken")) else 9999999999



        if b_left <= c_target_time <= b_right:

            if is_valid_tap_approach(b, ltf_candles, target_idx):
                # Cycle State Machine: Trace back up to 120 candles to anchor to the initial tap
                initial_tap_idx = target_idx
                b_top = max(b.get("top", 0), b.get("bottom", 0))
                b_bot = min(b.get("top", 0), b.get("bottom", 0))
                for back_i in range(target_idx - 1, max(-1, target_idx - 120), -1):
                    c_prev = ltf_candles[back_i]
                    if c_prev["high"] >= b_bot and c_prev["low"] <= b_top:
                        initial_tap_idx = back_i
                    elif is_valid_tap_approach(b, ltf_candles, initial_tap_idx):
                        break
                return b, initial_tap_idx



    # Step 2: If target_time was HTF candle open time, search LTF candles in [target_time, target_time + htf_sec)

    max_step = max(1, htf_sec // 60)

    for idx in range(target_idx, min(len(ltf_candles), target_idx + max_step)):

        c = ltf_candles[idx]

        c_time = c["time"]

        if c_time >= target_time + htf_sec:

            break



        for b in htf_boxes:

            if not is_htf_box_active(b, c_time):

                continue

            b_left = b.get("left") or b.get("created_time") or 0

            b_right = (b.get("mitigated_time") or b.get("right") or 9999999999) if (b.get("is_mitigated") or b.get("is_broken")) else 9999999999



            if b_left <= c_time <= b_right:

                if is_valid_tap_approach(b, ltf_candles, idx):

                    return b, idx



    # Step 3: Check immediate surrounding candles [target_idx - 5, target_idx + 5]

    for idx in range(max(0, target_idx - 5), min(len(ltf_candles), target_idx + 6)):

        c = ltf_candles[idx]

        c_time = c["time"]



        for b in htf_boxes:

            if not is_htf_box_active(b, c_time):

                continue

            b_left = b.get("left") or b.get("created_time") or 0

            b_right = (b.get("mitigated_time") or b.get("right") or 9999999999) if (b.get("is_mitigated") or b.get("is_broken")) else 9999999999



            if b_left <= c_time <= b_right:

                if is_valid_tap_approach(b, ltf_candles, idx):

                    return b, idx



    return None, None





def candle_touches_level(c: Dict, lvl_top: float, lvl_bot: float) -> bool:

    """Checks if candle range overlaps level bounds (Level Top >= Candle Low and Level Bottom <= Candle High)."""

    return c.get("high", 0) >= lvl_bot and c.get("low", 0) <= lvl_top





def find_nearest_htf_liquidity(

    entry_price: float,

    is_bullish: bool,

    htf_candles: Optional[List[Dict]] = None,

    htf_boxes: Optional[List[Dict]] = None,

    entry_time: Optional[int] = None

) -> Optional[float]:

    """

    Finds the nearest HTF Liquidity Point (swing high / opposing supply for buy;

    swing low / opposing demand for sell).

    """

    candidates = []



    # 1. Opposing HTF zones

    if htf_boxes:

        for b in htf_boxes:

            b_top = max(b.get("top", 0), b.get("bottom", 0))

            b_bot = min(b.get("top", 0), b.get("bottom", 0))

            if is_bullish and not b.get("is_bullish", True):  # Opposing supply zone

                if b_bot > entry_price:

                    candidates.append(b_bot)

            elif not is_bullish and b.get("is_bullish", True):  # Opposing demand zone

                if b_top < entry_price:

                    candidates.append(b_top)



    # 2. Significant HTF Swing Pivots in recent 48 hours

    if htf_candles and len(htf_candles) >= 5:

        max_time = entry_time if entry_time else float("inf")

        min_time = max_time - 172800  # 48 hours

        recent_htf = [c for c in htf_candles if min_time <= c.get("time", 0) <= max_time]

        if len(recent_htf) >= 5:

            for i in range(2, len(recent_htf) - 2):

                c = recent_htf[i]

                if is_bullish:

                    if (c["high"] > recent_htf[i-1]["high"] and c["high"] > recent_htf[i-2]["high"] and

                        c["high"] > recent_htf[i+1]["high"] and c["high"] > recent_htf[i+2]["high"]):

                        if c["high"] > entry_price:

                            candidates.append(c["high"])

                else:

                    if (c["low"] < recent_htf[i-1]["low"] and c["low"] < recent_htf[i-2]["low"] and

                        c["low"] < recent_htf[i+1]["low"] and c["low"] < recent_htf[i+2]["low"]):

                        if c["low"] < entry_price:

                            candidates.append(c["low"])



    if not candidates:

        return None



    return min(candidates) if is_bullish else max(candidates)





def compute_15m_atr(

    entry_time: int,

    trade_candles: List[Dict],

    htf_candles: Optional[List[Dict]] = None,

    htf_sec: int = 900,

    period: int = 14

) -> float:

    """

    Computes 15M Average True Range (14-period) up to entry_time.

    Provides dynamic 0.5 * ATR_15M cushion to protect against rapid stop-out wick sweeps.

    """

    # Priority A: If htf_candles is already 15M (htf_sec == 900)

    if htf_candles and htf_sec == 900:

        past_htf = [c for c in htf_candles if c.get("time", 0) <= entry_time]

        if len(past_htf) >= 2:

            trs = [

                max(

                    past_htf[i]["high"] - past_htf[i]["low"],

                    abs(past_htf[i]["high"] - past_htf[i-1]["close"]),

                    abs(past_htf[i]["low"] - past_htf[i-1]["close"])

                )

                for i in range(1, len(past_htf))

            ]

            if trs:

                recent = trs[-period:]

                return sum(recent) / len(recent)



    # Priority B: Resample trade_candles into 15m bars up to entry_time

    past_ltf = [c for c in trade_candles if c.get("time", 0) <= entry_time]

    if past_ltf:

        bars = {}

        for c in past_ltf:

            b_time = (c["time"] // 900) * 900

            if b_time not in bars:

                bars[b_time] = {"open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}

            else:

                bars[b_time]["high"] = max(bars[b_time]["high"], c["high"])

                bars[b_time]["low"] = min(bars[b_time]["low"], c["low"])

                bars[b_time]["close"] = c["close"]



        sorted_bars = [bars[k] for k in sorted(bars.keys())]

        if len(sorted_bars) >= 2:

            trs = [

                max(

                    sorted_bars[i]["high"] - sorted_bars[i]["low"],

                    abs(sorted_bars[i]["high"] - sorted_bars[i-1]["close"]),

                    abs(sorted_bars[i]["low"] - sorted_bars[i-1]["close"])

                )

                for i in range(1, len(sorted_bars))

            ]

            if trs:

                recent = trs[-period:]

                return sum(recent) / len(recent)



    ref_price = trade_candles[-1]["close"] if trade_candles else (htf_candles[-1]["close"] if htf_candles else 100.0)

    return ref_price * 0.0010





def scan_ltf_trade_entry(

    trade_candles: List[Dict],

    cutoff_time: Optional[int],

    is_bullish: bool,

    active_levels: List[Dict],

    htf_candles: Optional[List[Dict]] = None,

    htf_boxes: Optional[List[Dict]] = None,

    htf_box: Optional[Dict] = None,

    htf_sec: int = 900

) -> Optional[Dict[str, Any]]:

    """

    Scans post-cutoff candles for the FIRST valid retest of any active level:

    - Retest Boundary Check: Retest level and candlestick pattern must touch within or at HTF zone boundary.

    - Demand: Bullish Engulfing or Morning Star touching any qualified level.

    - Supply: Bearish Engulfing or Evening Star touching any qualified level.

    - Touch: Any 1 of 3 candles in Star, or any 1 of 2 candles in Engulfing touches level.

    - Stop Loss: 2 ticks away from pattern extreme low (buy) or high (sell).

    - Take Profit: Nearest HTF liquidity point.

    - Risk/Reward Filter: Minimum 2.5R required. If < 2.5R, trade is skipped.

    - Locks after first tested level (1 trade per zone cycle).

    """

    if not trade_candles or cutoff_time is None or not active_levels:

        return None



    # HTF Zone Boundary Constraints (Strict Zone Retest Requirement)

    box_top = None

    box_bot = None

    ref_p = trade_candles[0]["close"] if trade_candles else 100.0

    buffer = ref_p * 0.0005

    if htf_box:

        box_top = max(htf_box.get("top", 0), htf_box.get("bottom", 0))

        box_bot = min(htf_box.get("top", 0), htf_box.get("bottom", 0))

        buffer = box_top * 0.0005



    # Filter active levels to only those within or touching HTF zone boundary

    filtered_levels = []

    for lvl in active_levels:

        lvl_name = clean_box_name(lvl.get("text") or lvl.get("name") or "")

        if "A+" in lvl_name.upper():

            continue  # Filter out A+ (Dual CHoCH) per optimization

        # Only allow demand/bullish levels for BUY, and supply/bearish levels for SELL

        if lvl.get("is_bullish") != is_bullish:

            continue

        lvl_top = max(lvl.get("top", 0), lvl.get("bottom", 0))

        lvl_bot = min(lvl.get("top", 0), lvl.get("bottom", 0))

        if htf_box:

            if is_bullish:

                if lvl_bot > box_top + buffer:

                    continue  # Discard levels floating above Demand zone

            else:

                if lvl_top < box_bot - buffer:

                    continue  # Discard levels floating below Supply zone

        filtered_levels.append(lvl)



    if not filtered_levels:

        return None



    start_idx = None

    for idx, c in enumerate(trade_candles):

        if c.get("time", 0) >= cutoff_time:

            start_idx = idx

            break



    if start_idx is None:

        return None



    for i in range(start_idx, len(trade_candles)):

        if i < 1:

            continue

        c_curr = trade_candles[i]

        c_prev = trade_candles[i - 1]

        c_prev2 = trade_candles[i - 2] if i >= 2 else None



        pattern_name = None

        pattern_candles = []



        # 1. Check Engulfing (2-Candle)

        if is_bullish:

            if is_valid_bullish_engulfing(c_prev, c_curr) or (

                c_curr["close"] > c_curr["open"] and

                c_prev["close"] <= c_prev["open"] + 1.0 and

                c_curr["close"] >= c_prev["open"]

            ):

                pattern_name = "Bullish Engulfing"

                pattern_candles = [c_prev, c_curr]

        else:

            if is_valid_bearish_engulfing(c_prev, c_curr) or (

                c_curr["close"] < c_curr["open"] and

                c_prev["close"] >= c_prev["open"] - 1.0 and

                c_curr["close"] <= c_prev["open"]

            ):

                pattern_name = "Bearish Engulfing"

                pattern_candles = [c_prev, c_curr]



        # 2. Check Star (3-Candle)

        if not pattern_name and c_prev2 is not None:

            c1_b = abs(c_prev2["close"] - c_prev2["open"])

            c2_b = abs(c_prev["close"] - c_prev["open"])

            c3_b = abs(c_curr["close"] - c_curr["open"])

            is_star_c2 = (c2_b < c1_b) and (c2_b < c3_b)



            if is_bullish:

                c1_red = c_prev2["close"] < c_prev2["open"]

                c3_green = c_curr["close"] > c_curr["open"]

                c3_deep = c_curr["close"] >= (c_prev2["open"] + c_prev2["close"]) / 2.0

                if c1_red and c3_green and is_star_c2 and c3_deep:

                    pattern_name = "Morning Star"

                    pattern_candles = [c_prev2, c_prev, c_curr]

            else:

                c1_green = c_prev2["close"] > c_prev2["open"]

                c3_red = c_curr["close"] < c_curr["open"]

                c3_deep = c_curr["close"] <= (c_prev2["open"] + c_prev2["close"]) / 2.0

                if c1_green and c3_red and is_star_c2 and c3_deep:

                    pattern_name = "Evening Star"

                    pattern_candles = [c_prev2, c_prev, c_curr]



        if not pattern_name:

            continue



        # Check Candlestick Pattern Boundary: must touch within or at HTF zone boundary

        if htf_box:

            if is_bullish:

                pattern_low = min(c["low"] for c in pattern_candles)

                if pattern_low > box_top + buffer:

                    continue  # Pattern floating in mid-air above zone

            else:

                pattern_high = max(c["high"] for c in pattern_candles)

                if pattern_high < box_bot - buffer:

                    continue  # Pattern floating in mid-air below zone



        # Check if ANY candle of the pattern touches ANY filtered active level

        matched_level = None

        for lvl in filtered_levels:

            lvl_top = max(lvl["top"], lvl["bottom"])

            lvl_bot = min(lvl["top"], lvl["bottom"])

            if any(candle_touches_level(c, lvl_top, lvl_bot) for c in pattern_candles):

                matched_level = lvl

                break



        if not matched_level:

            continue



        # Valid pattern touching active level found!

        entry_price = c_curr["close"]

        dec = 5 if entry_price < 50 else (3 if entry_price < 1000 else 2)



        # Pattern 2 Optimization: 0.5 * ATR_15M Cushion to absorb rapid liquidity spike sweeps

        atr_15m = compute_15m_atr(

            entry_time=c_curr["time"],

            trade_candles=trade_candles,

            htf_candles=htf_candles,

            htf_sec=htf_sec,

            period=14

        )

        cushion = round(0.5 * atr_15m, dec)

        min_tick = round(entry_price * 0.0002, dec)

        sl_cushion = max(cushion, min_tick)



        if is_bullish:

            extreme = min(c["low"] for c in pattern_candles)

            sl_price = round(extreme - sl_cushion, dec)

            risk = round(entry_price - sl_price, dec)

        else:

            extreme = max(c["high"] for c in pattern_candles)

            sl_price = round(extreme + sl_cushion, dec)

            risk = round(sl_price - entry_price, dec)



        if risk <= 0:

            continue



        if htf_sec >= 14400:

            # 4H Timeframe Rule: Book Fixed 3.0 RR

            rr = 3.0

            reward = round(risk * 3.0, dec)

            tp_price = round(entry_price + reward if is_bullish else entry_price - reward, dec)

            is_executed = True

        else:

            # Other Timeframes (1H, 15M) Rule: Target Nearest Liquidity (Minimum 2.5 RR, skip if < 2.5 RR)

            htf_tp = find_nearest_htf_liquidity(entry_price, is_bullish, htf_candles, htf_boxes, c_curr.get("time"))

            if not htf_tp:

                continue  # No opposing liquidity pool found -> skip this pattern



            reward = round(abs(htf_tp - entry_price), dec)

            rr = round(reward / risk, 2)

            tp_price = round(htf_tp, dec)

            is_executed = (rr >= 2.5)



        return {

            "id": f"trade_{c_curr['time']}",

            "action": "BUY" if is_bullish else "SELL",

            "time": c_curr["time"],

            "entry_price": entry_price,

            "sl_price": sl_price,

            "tp_price": tp_price,

            "risk": risk,

            "reward": reward,

            "rr": rr,

            "level_name": clean_box_name(matched_level.get("text") or matched_level.get("name") or "Level"),

            "pattern_name": pattern_name,

            "executed": is_executed,

            "status": "EXECUTED" if is_executed else "SKIPPED_RR_BELOW_2_5"

        }



    return None





def compute_ltf_approach_structure(

    target_time: int,

    ltf_candles: List[Dict],

    htf_boxes: List[Dict],

    htf_sec: int = 900,

    htf_candles: Optional[List[Dict]] = None,

    override_tap_time: Optional[int] = None,

    override_box: Optional[Dict] = None

) -> Dict:

    """

    Computes localized LTF market structure triggered exclusively when price taps an HTF zone.

    Executes the Race Condition between:

      - 5-Wave Internal Structure (starting from the zone extreme)

      - External CHoCH / Dual CHoCH

    Whichever completes first, draws the levels of that pathway on the LTF chart:

      - If 5-Wave completes first: draws 'Level of 3' and 'Level of 4'.

      - If CHoCH / Dual CHoCH occurs first: draws CHoCH / Dual CHoCH levels (QML, RBS, SBR, TJL1, TJL2, A+).

    """

    if not ltf_candles or len(ltf_candles) < 25 or not htf_boxes:

        return {"lines": [], "boxes": [], "labels": [], "tap_info": None}



    if override_tap_time is not None and override_tap_time > 0:
        times = [c["time"] for c in ltf_candles]
        import bisect
        pos = bisect.bisect_left(times, override_tap_time)
        tap_idx = min(len(ltf_candles) - 1, max(0, pos))
        matched_box = override_box if override_box is not None else (htf_boxes[0] if htf_boxes else None)
    else:
        matched_box, tap_idx = find_tapped_htf_box(target_time, ltf_candles, htf_boxes, htf_sec)

    if matched_box is None or tap_idx is None:

        # Zero math, completely clean LTF

        return {"lines": [], "boxes": [], "labels": [], "tap_info": None}



    # Lookback window before tapping candle (40 bars captures preceding approach structure cleanly)

    lookback_pre = 120 if htf_sec >= 14400 else 80
    start_idx = max(0, tap_idx - lookback_pre)

    

    # Trade reaction window: extended up to 240 bars after tap (or end of ltf_candles)

    # allowing sufficient room for 5-wave internal structures and CHoCH reactions to complete

    end_idx = min(len(ltf_candles), tap_idx + 240)

    trade_candles = ltf_candles[start_idx:end_idx]



    if len(trade_candles) < 10:

        return {"lines": [], "boxes": [], "labels": [], "tap_info": None}



    tap_in_slice = tap_idx - start_idx

    tap_actual_time = ltf_candles[tap_idx]["time"]

    is_bullish = matched_box.get("is_bullish", True)

    box_top = max(matched_box.get("top", 0), matched_box.get("bottom", 0))

    box_bot = min(matched_box.get("top", 0), matched_box.get("bottom", 0))

    buffer = box_top * 0.0005



    # 1. Run HTFEngine on the localized slice to find BOS, CHoCH, Dual CHoCH and their levels

    engine = HTFEngine(

        lookback_bars=len(trade_candles),

        show_bos=True,

        show_choch=True,

        show_dual_choch=True,

        show_triple_choch=True,

        show_tjl_boxes=True,

        tjl_extend=True

    )

    structure_out = engine.run(trade_candles)

    raw_lines = structure_out.get("lines", [])

    raw_boxes = structure_out.get("boxes", [])



    def _line_dir(line):
        if line.get("direction"):
            return line["direction"]
        c = line.get("color", "")
        if c in ("#26a69a", "#10b981", "#00E676"):
            return "bullish"
        if c in ("#ef5350", "#ef4444", "#FF5252"):
            return "bearish"
        lid = line.get("id", "")
        if "bull" in lid:
            return "bullish"
        if "bear" in lid:
            return "bearish"
        return "bullish"

    # Pre-Tap Approach Qualification:

    # Demand zone requires price approaching with bearish BOS/CHoCH on LTF

    # Pre-tap approach BOS/CHoCH requirement (MTF-002) removed per user instruction.
    has_approach_bos = True

    # 2. Check 5-Wave Internal Structure strictly adhering to the tapped zone direction:

    # Demand tap -> Bullish internal 5-wave reaction

    # Supply tap -> Bearish internal 5-wave reaction

    res_5w = detect_internal_5_waves(trade_candles, tap_in_slice, is_bullish, htf_box=matched_box)



    w5_time = res_5w["wave_5_time"] if res_5w["completed"] else float('inf')



    # 3. Check earliest post-tap CHoCH / Dual CHoCH adhering strictly to zone direction:

    # Demand tap -> Bullish CHoCH only (ignore bearish CHoCH)

    # Supply tap -> Bearish CHoCH only (ignore bullish CHoCH)

    earliest_choch_time = float('inf')

    earliest_choch_type = "CHoCH"

    earliest_choch_bar = None

    expected_direction = "bullish" if is_bullish else "bearish"



    for l in raw_lines:

        if "CHoCH" in l.get("type", ""):

            # Strictly filter by zone polarity

            if _line_dir(l) != expected_direction:

                continue

            l_x2 = l.get("x2", 0)

            if l_x2 >= tap_actual_time:

                # Strict Zone Entry Check for CHoCH:

                # The reversal structure must form directly from the zone tap extreme

                candles_between = [c for c in trade_candles if tap_actual_time <= c["time"] <= l_x2]

                if candles_between:

                    if is_bullish:

                        trough_low = min(c["low"] for c in candles_between)

                        if trough_low > box_top + buffer:

                            continue  # Formed far away from zone extreme

                    else:

                        peak_high = max(c["high"] for c in candles_between)

                        if peak_high < box_bot - buffer:

                            continue  # Formed far away from zone extreme



                if l_x2 < earliest_choch_time:

                    earliest_choch_time = l_x2

                    earliest_choch_type = l.get("type", "CHoCH")

                    for b_i, c in enumerate(trade_candles):

                        if c["time"] == l_x2:

                            earliest_choch_bar = b_i

                            break



    # 4. Evaluate Race Condition: Which happened first?

    winner_pathway = "NONE"

    cutoff_time = None

    if w5_time < float('inf') or earliest_choch_time < float('inf'):

        if w5_time < earliest_choch_time:

            winner_pathway = "5-Wave (Internal)"

            cutoff_time = w5_time

        else:

            winner_pathway = f"{earliest_choch_type} (External)"

            cutoff_time = earliest_choch_time



    # Format parent HTF box (clearly distinguish parent HTF zone from localized LTF entry levels)

    raw_htf_name = clean_box_name(matched_box.get("text") or matched_box.get("name") or "HTF Zone")

    htf_label = f"HTF {raw_htf_name}" if not raw_htf_name.upper().startswith("HTF") else raw_htf_name

    box_clean = {

        "id": matched_box.get("id", "tapped_htf_zone"),

        "top": max(matched_box.get("top", 0), matched_box.get("bottom", 0)),

        "bottom": min(matched_box.get("top", 0), matched_box.get("bottom", 0)),

        "left": ltf_candles[start_idx]["time"],

        "right": ltf_candles[min(len(ltf_candles)-1, end_idx)]["time"],

        "color": matched_box.get("color", "rgba(59, 130, 246, 0.20)"),

        "borderColor": matched_box.get("borderColor", "#3b82f6"),

        "text": htf_label,

        "is_bullish": is_bullish

    }



    selected_boxes = [box_clean]

    selected_lines = []

    selected_labels = []



    # Format breakout lines (stop marking structure after cutoff)

    for l in raw_lines:

        if cutoff_time is not None and l.get("x2", 0) > cutoff_time:

            continue

        line_type = l.get("type", "BOS")

        direction = l.get("direction", "bullish")



        if "Triple" in line_type:

            color = "#a855f7"

        elif "Dual" in line_type:

            color = "#f59e0b"

        elif "CHoCH" in line_type:

            color = "#10b981" if direction == "bullish" else "#ef4444"

        else:

            color = "#26a69a" if direction == "bullish" else "#ef5350"



        selected_lines.append({

            "id": l.get("id", f"ltf_line_{l.get('x1')}"),

            "type": line_type,

            "direction": direction,

            "x1": l.get("x1"),

            "x2": l.get("x2"),

            "y1": l.get("y1"),

            "y2": l.get("y2", l.get("y1")),

            "color": color,

            "style": "solid",

            "width": 1.5

        })



    # 5. Populate levels: Draw levels of whichever pathway won the race

    seen_boxes = {(box_clean["text"], round(box_clean["top"], 5) if box_clean["top"] < 50 else round(box_clean["top"], 1), round(box_clean["bottom"], 5) if box_clean["bottom"] < 50 else round(box_clean["bottom"], 1))}



    if winner_pathway == "5-Wave (Internal)":

        # Draw levels of 5-Wave Internal Structure (Level of 3 and Level of 4)

        if res_5w.get("completed"):

            l3 = res_5w["level_3"]

            l4 = res_5w["level_4"]



            box_l3 = {

                "id": "box_internal_level_3",

                "top": max(l3["top"], l3["bottom"]),

                "bottom": min(l3["top"], l3["bottom"]),

                "left": l3["time"],

                "right": trade_candles[-1]["time"],

                "color": "rgba(38, 166, 154, 0.20)" if is_bullish else "rgba(239, 83, 80, 0.20)",

                "borderColor": "#26a69a" if is_bullish else "#ef5350",

                "text": "Level of 3",

                "is_bullish": is_bullish

            }



            box_l4 = {

                "id": "box_internal_level_4",

                "top": max(l4["top"], l4["bottom"]),

                "bottom": min(l4["top"], l4["bottom"]),

                "left": l4["time"],

                "right": trade_candles[-1]["time"],

                "color": "rgba(38, 166, 154, 0.20)" if is_bullish else "rgba(239, 83, 80, 0.20)",

                "borderColor": "#26a69a" if is_bullish else "#ef5350",

                "text": "Level of 4",

                "is_bullish": is_bullish

            }



            for b_cand in [box_l3, box_l4]:

                k = (b_cand["text"], round(b_cand["top"], 5) if b_cand["top"] < 50 else round(b_cand["top"], 1), round(b_cand["bottom"], 5) if b_cand["bottom"] < 50 else round(b_cand["bottom"], 1))

                if k not in seen_boxes:

                    seen_boxes.add(k)

                    selected_boxes.append(b_cand)



        # Add subtle wave markers for tracked internal waves

        for w in res_5w.get("waves", []):

            selected_labels.append({

                "id": f"wave_{w['wave']}",

                "x": w["time"],

                "y": w["val"],

                "text": f"W{w['wave']}",

                "color": "#000000"

            })



    elif winner_pathway != "NONE":

        # External CHoCH / Dual CHoCH won the race: Draw levels of CHoCH / Dual CHoCH formed up to cutoff

        # Allowed LTF CHoCH entry levels: QML, SBR, RBS, Double Top, Double Bottom

        allowed_ltf_choch_levels = {"QML", "SBR", "RBS", "DOUBLE TOP", "DOUBLE BOTTOM"}

        for idx, b in enumerate(raw_boxes):

            if cutoff_time is not None and b.get("left", 0) > cutoff_time:

                continue

            b_name = clean_box_name(b.get("text") or b.get("name") or "Level")

            if b_name.upper() not in allowed_ltf_choch_levels:

                continue

            b_bull = b.get("is_bullish", True)

            top_val = max(b.get("top", 0), b.get("bottom", 0))

            bot_val = min(b.get("top", 0), b.get("bottom", 0))



            k = (b_name, round(top_val, 5) if top_val < 50 else round(top_val, 1), round(bot_val, 5) if bot_val < 50 else round(bot_val, 1))

            if k not in seen_boxes:

                seen_boxes.add(k)

                selected_boxes.append({

                    "id": b.get("id", f"ltf_level_{idx}"),

                    "top": top_val,

                    "bottom": bot_val,

                    "left": b.get("left", trade_candles[0]["time"]),

                    "right": b.get("right", trade_candles[-1]["time"]),

                    "color": b.get("color", "rgba(38, 166, 154, 0.20)" if b_bull else "rgba(239, 83, 80, 0.20)"),

                    "borderColor": b.get("borderColor", "#26a69a" if b_bull else "#ef5350"),

                    "text": b_name,

                    "is_bullish": b_bull

                })



    else:

        # Race in progress (neither completed):

        # Show wave markers if waves are in progress

        for w in res_5w.get("waves", []):

            selected_labels.append({

                "id": f"wave_{w['wave']}",

                "x": w["time"],

                "y": w["val"],

                "text": f"W{w['wave']}",

                "color": "#000000"

            })



    # 6. Scan for Trade Entry at Active Levels post-cutoff

    active_entry_levels = [b for b in selected_boxes if not str(b.get("text", "")).upper().startswith("HTF")]

    trade_result = scan_ltf_trade_entry(

        trade_candles=trade_candles,

        cutoff_time=cutoff_time,

        is_bullish=is_bullish,

        active_levels=active_entry_levels,

        htf_candles=htf_candles,

        htf_boxes=htf_boxes,

        htf_box=matched_box,

        htf_sec=htf_sec

    )



    selected_markers = []

    selected_signals = []



    if trade_result:

        if trade_result.get("executed"):

            selected_signals.append(trade_result)

            

            # Add visual Entry, SL, and TP lines on LTF chart

            t_time = trade_result["time"]

            t_right = trade_candles[-1]["time"]

            selected_lines.append({

                "id": f"trade_entry_{t_time}",

                "type": f"ENTRY ({trade_result['action']})",

                "direction": "bullish" if is_bullish else "bearish",

                "x1": t_time,

                "x2": t_right,

                "y1": trade_result["entry_price"],

                "y2": trade_result["entry_price"],

                "color": "#3b82f6",

                "style": "solid",

                "width": 2

            })

            selected_lines.append({

                "id": f"trade_sl_{t_time}",

                "type": "SL",

                "direction": "bearish" if is_bullish else "bullish",

                "x1": t_time,

                "x2": t_right,

                "y1": trade_result["sl_price"],

                "y2": trade_result["sl_price"],

                "color": "#ef4444",

                "style": "solid",

                "width": 1.5

            })

            selected_lines.append({

                "id": f"trade_tp_{t_time}",

                "type": f"TP ({trade_result['rr']}R)",

                "direction": "bullish" if is_bullish else "bearish",

                "x1": t_time,

                "x2": t_right,

                "y1": trade_result["tp_price"],

                "y2": trade_result["tp_price"],

                "color": "#10b981",

                "style": "solid",

                "width": 1.5

            })



            # Add Arrow Marker on entry candle

            selected_markers.append({

                "time": t_time,

                "position": "belowBar" if is_bullish else "aboveBar",

                "color": "#10b981" if is_bullish else "#ef4444",

                "shape": "arrowUp" if is_bullish else "arrowDown",

                "text": f"{trade_result['action']} ({trade_result['pattern_name']} @ {trade_result['level_name']}) {trade_result['rr']}R"

            })



    return {

        "lines": selected_lines,

        "boxes": selected_boxes,

        "labels": selected_labels,

        "markers": selected_markers,

        "signals": selected_signals,

        "trade_logic": trade_result,

        "tap_info": {

            "tap_time": tap_actual_time,

            "start_time": ltf_candles[start_idx]["time"],

            "tap_idx": tap_idx,

            "start_idx": start_idx,

            "box_name": htf_label,

            "winner_pathway": winner_pathway,

            "cutoff_time": cutoff_time,

            "w5_time": w5_time if w5_time < float('inf') else None,

            "choch_time": earliest_choch_time if earliest_choch_time < float('inf') else None,

            "waves_count": len(res_5w.get("waves", [])),

            "trade": trade_result

        }

    }

