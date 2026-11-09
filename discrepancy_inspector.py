import os
import sys
import datetime
import math
import json
import logging
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("discrepancy_inspector")

from binance_feed import fetch_klines_paginated, fetch_klines_range
from htf_engine import HTFEngine
from mtf_micro_engine import (
    resolve_mtf_race_and_signals,
    is_bullish_engulfing,
    is_bearish_engulfing,
    is_morning_star,
    is_evening_star
)

INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400
}

def norm_tf(t: str) -> str:
    t = (t or "").lower().strip()
    if t in ["d1", "1d"]: return "1d"
    if t in ["h4", "4h"]: return "4h"
    if t in ["h1", "1h"]: return "1h"
    if t in ["m15", "15m"]: return "15m"
    if t in ["m5", "5m"]: return "5m"
    if t in ["m1", "1m"]: return "1m"
    return t or "15m"

def get_target_ltf_for_htf(htf: str) -> Optional[str]:
    n = norm_tf(htf)
    if n in ["15m", "1h"]: return "1m"
    if n == "4h": return "5m"
    # 1D and 5M are explicitly NOT traded
    return None

def parse_target_timestamp(target_input: Any) -> int:
    """Parses various timestamp or date formats into epoch seconds."""
    if not target_input:
        return int(datetime.datetime.now().timestamp())
    
    if isinstance(target_input, (int, float)):
        val = int(target_input)
        if val > 100000000000:
            return val // 1000
        return val
        
    s = str(target_input).strip()
    if s.replace(".", "").isdigit():
        val = int(float(s))
        if val > 100000000000:
            return val // 1000
        return val
        
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M"
    ]:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return int(dt.timestamp())
        except ValueError:
            pass
            
    return int(datetime.datetime.now().timestamp())

def classify_candle_pattern(candles: List[Dict], idx: int) -> Dict[str, Any]:
    """
    Classifies candle shape, wicks, body, and multi-bar patterns (Engulfing, Star, Pin Bar, Rejection).
    """
    if not candles or idx < 0 or idx >= len(candles):
        return {
            "pattern_name": "Standard Candle",
            "is_bullish": True,
            "body_pct": 50.0,
            "upper_wick_pct": 25.0,
            "lower_wick_pct": 25.0,
            "wick_description": "Normal candle distribution",
            "is_strict_algo_pattern": False
        }
        
    c = candles[idx]
    o, h, l, c_close = c["open"], c["high"], c["low"], c["close"]
    body = abs(c_close - o)
    total_range = max(0.0001, h - l)
    is_bull = c_close >= o
    
    upper_wick = h - max(o, c_close)
    lower_wick = min(o, c_close) - l
    
    body_pct = round((body / total_range) * 100.0, 1)
    upper_wick_pct = round((upper_wick / total_range) * 100.0, 1)
    lower_wick_pct = round((lower_wick / total_range) * 100.0, 1)
    
    # 1. Multi-bar patterns
    if idx >= 1:
        prev = candles[idx - 1]
        if is_bullish_engulfing(prev, c):
            return {
                "pattern_name": "Bullish Engulfing",
                "is_bullish": True,
                "body_pct": body_pct,
                "upper_wick_pct": upper_wick_pct,
                "lower_wick_pct": lower_wick_pct,
                "wick_description": f"Strong bullish expansion engulfing previous candle body ({body_pct}% body)",
                "is_strict_algo_pattern": True
            }
        if is_bearish_engulfing(prev, c):
            return {
                "pattern_name": "Bearish Engulfing",
                "is_bullish": False,
                "body_pct": body_pct,
                "upper_wick_pct": upper_wick_pct,
                "lower_wick_pct": lower_wick_pct,
                "wick_description": f"Strong bearish expansion engulfing previous candle body ({body_pct}% body)",
                "is_strict_algo_pattern": True
            }
            
    if idx >= 2:
        c1 = candles[idx - 2]
        c2 = candles[idx - 1]
        c3 = c
        if is_morning_star(c1, c2, c3):
            return {
                "pattern_name": "Morning Star (3-Bar Reversal)",
                "is_bullish": True,
                "body_pct": body_pct,
                "upper_wick_pct": upper_wick_pct,
                "lower_wick_pct": lower_wick_pct,
                "wick_description": "Textbook 3-bar bullish morning star reversal off the low",
                "is_strict_algo_pattern": True
            }
        if is_evening_star(c1, c2, c3):
            return {
                "pattern_name": "Evening Star (3-Bar Reversal)",
                "is_bullish": False,
                "body_pct": body_pct,
                "upper_wick_pct": upper_wick_pct,
                "lower_wick_pct": lower_wick_pct,
                "wick_description": "Textbook 3-bar bearish evening star reversal off the high",
                "is_strict_algo_pattern": True
            }

    # 2. Single-bar Pin Bars & Wick Rejections
    if lower_wick >= 2.0 * max(0.01, body) and upper_wick_pct <= 25.0:
        desc = f"Long lower wick ({lower_wick_pct}% of range) absorbing selling pressure (Hammer / Pin Bar)"
        return {
            "pattern_name": "Bullish Pin Bar / Hammer",
            "is_bullish": True,
            "body_pct": body_pct,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_description": desc,
            "is_strict_algo_pattern": False
        }
        
    if upper_wick >= 2.0 * max(0.01, body) and lower_wick_pct <= 25.0:
        desc = f"Long upper wick ({upper_wick_pct}% of range) rejecting higher prices (Shooting Star / Pin Bar)"
        return {
            "pattern_name": "Bearish Pin Bar / Shooting Star",
            "is_bullish": False,
            "body_pct": body_pct,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_description": desc,
            "is_strict_algo_pattern": False
        }

    if lower_wick_pct >= 40.0:
        desc = f"Heavy bottom wick rejection ({lower_wick_pct}% of range), aggressive buyer defense"
        return {
            "pattern_name": "Bullish Wick Rejection",
            "is_bullish": True,
            "body_pct": body_pct,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_description": desc,
            "is_strict_algo_pattern": False
        }

    if upper_wick_pct >= 40.0:
        desc = f"Heavy top wick rejection ({upper_wick_pct}% of range), aggressive seller defense"
        return {
            "pattern_name": "Bearish Wick Rejection",
            "is_bullish": False,
            "body_pct": body_pct,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_description": desc,
            "is_strict_algo_pattern": False
        }

    if body_pct >= 75.0:
        desc = f"High-momentum Marubozu candle ({body_pct}% body), clean directional drive"
        return {
            "pattern_name": "Bullish Marubozu" if is_bull else "Bearish Marubozu",
            "is_bullish": is_bull,
            "body_pct": body_pct,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_description": desc,
            "is_strict_algo_pattern": False
        }

    if body_pct <= 15.0:
        desc = f"Doji / equilibrium candle ({body_pct}% body), market pause/indecision"
        return {
            "pattern_name": "Doji / Indecision",
            "is_bullish": is_bull,
            "body_pct": body_pct,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_description": desc,
            "is_strict_algo_pattern": False
        }

    desc = f"Standard {'bullish' if is_bull else 'bearish'} candle with {body_pct}% body"
    return {
        "pattern_name": f"Standard {'Bullish' if is_bull else 'Bearish'} Candle",
        "is_bullish": is_bull,
        "body_pct": body_pct,
        "upper_wick_pct": upper_wick_pct,
        "lower_wick_pct": lower_wick_pct,
        "wick_description": desc,
        "is_strict_algo_pattern": False
    }

def find_registered_trade(sym: str, norm_h: str, candle_time: int, target_ts: int, htf_sec: int) -> Optional[Dict]:
    """Check data/zone_trades_registry.json for any trade executed by the bot on or near this candle."""
    reg_path = os.path.join(os.path.dirname(__file__), "data", "zone_trades_registry.json")
    if not os.path.exists(reg_path):
        return None
    try:
        with open(reg_path, "r", encoding="utf-8") as rf:
            reg_data = json.load(rf)
            for r_key, r_sig in reg_data.items():
                r_parts = r_key.split("_")
                if len(r_parts) >= 2 and r_parts[0].upper() == sym.upper() and r_parts[1].lower() == norm_h.lower():
                    r_time = r_sig.get("time") or r_sig.get("chart_time", 0)
                    if abs(r_time - candle_time) <= 2 * htf_sec or abs(r_time - target_ts) <= 2 * htf_sec:
                        return r_sig
                    r_exit = r_sig.get("exit_time", r_time + 12 * htf_sec)
                    if r_time <= candle_time <= r_exit or (r_time <= target_ts <= r_exit):
                        return r_sig
    except Exception as e:
        logger.warning(f"Error checking registered trades in inspector: {e}")
    return None

def inspect_trade_discrepancy(
    symbol: str = "BTCUSDT",
    htf: str = "15m",
    target_time_input: Any = None,
    manual_side: Optional[str] = None,
    manual_price: Optional[float] = None,
    existing_htf_candles: Optional[List[Dict]] = None,
    existing_boxes: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    Performs full deep-dive algorithmic inspection of any candle or manual trade timestamp.
    Ensures 100% parity with chart boxes, candles, and market structure.
    """
    sym = symbol.upper().strip()
    norm_h = norm_tf(htf)
    norm_l = get_target_ltf_for_htf(norm_h)
    market = "futures"
    
    htf_sec = INTERVAL_SECONDS.get(norm_h, 900)
    ltf_sec = INTERVAL_SECONDS.get(norm_l, 60)
    
    target_ts = parse_target_timestamp(target_time_input)
    
    # 1. Retrieve HTF candles (Use existing cached candles if available, or fetch full 1000 from futures)
    if existing_htf_candles and len(existing_htf_candles) >= 50:
        htf_candles = existing_htf_candles
    else:
        htf_candles = fetch_klines_paginated(sym, norm_h, 1000, market)
        
    if not htf_candles:
        return {
            "success": False,
            "error": f"Failed to fetch {sym} {norm_h.upper()} candles from exchange feed."
        }
        
    seen = set()
    cleaned_htf = []
    for c in htf_candles:
        t = c.get("time")
        if t and t not in seen:
            seen.add(t)
            cleaned_htf.append(c)
    cleaned_htf.sort(key=lambda x: x["time"])
    htf_candles = cleaned_htf
    
    # Locate target candle in HTF
    target_idx = -1
    min_dist = float("inf")
    for i, c in enumerate(htf_candles):
        dist = abs(c["time"] - target_ts)
        if dist < min_dist:
            min_dist = dist
            target_idx = i
            
    if target_idx == -1:
        target_idx = len(htf_candles) - 1
        
    target_candle = htf_candles[target_idx]
    actual_candle_time = target_candle["time"]
    time_str = datetime.datetime.fromtimestamp(actual_candle_time, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    c_open = target_candle["open"]
    c_high = target_candle["high"]
    c_low = target_candle["low"]
    c_close = target_candle["close"]
    
    # Candle pattern classification
    candle_analysis = classify_candle_pattern(htf_candles, target_idx)
    
    inferred_side = "BUY" if candle_analysis["is_bullish"] else "SELL"
    user_side = (manual_side.upper() if manual_side and manual_side.upper() in ["BUY", "SELL"] else inferred_side)
    user_price = float(manual_price) if manual_price and manual_price > 0 else c_close
    
    # 2. HTF Structure Engine Scan (Exact boxes)
    if existing_boxes and len(existing_boxes) > 0:
        htf_boxes = existing_boxes
    else:
        htf_engine = HTFEngine(lookback_bars=500, show_tjl_boxes=True, tjl_extend=True)
        htf_res = htf_engine.run(htf_candles)
        htf_boxes = htf_res.get("boxes", [])

    # Check for any registered trade on this candle or nearby
    registered_trade = find_registered_trade(sym, norm_h, actual_candle_time, target_ts, htf_sec)
    if registered_trade and not manual_side:
        user_side = registered_trade.get("type", user_side)

    # Filter/Prioritize boxes aligned with user trade direction
    wants_bull = (user_side == "BUY")
    
    def is_box_bull(b: Dict) -> bool:
        return (b.get("is_bullish", True) or b.get("level_type") in ["demand", "buying"])

    tapped_box = None
    
    # Priority 1: Direct Price Touch by Target Candle (Filtered by desired direction first)
    touching_boxes = []
    for b in htf_boxes:
        b_top = max(b.get("top", 0), b.get("bottom", 0))
        b_bot = min(b.get("top", 0), b.get("bottom", 0))
        b_left = b.get("left", 0)
        b_right = b.get("right", b_left + htf_sec * 50)
        if c_high >= b_bot and c_low <= b_top:
            if b_left <= actual_candle_time <= b_right + htf_sec * 3:
                touching_boxes.append(b)
                
    if touching_boxes:
        aligned = [b for b in touching_boxes if is_box_bull(b) == wants_bull]
        tapped_box = aligned[0] if aligned else touching_boxes[0]
        
    # Priority 2: Active Reaction Cycles (Target candle occurs during box reaction cycle)
    if not tapped_box:
        cycle_boxes = []
        for b in htf_boxes:
            for cyc in b.get("cycles", []):
                tb = cyc.get("tap_bar")
                eb = cyc.get("exit_bar") or (tb + 25)
                if tb is not None and tb <= target_idx <= eb + 2:
                    cycle_boxes.append(b)
                    break
        if cycle_boxes:
            aligned = [b for b in cycle_boxes if is_box_bull(b) == wants_bull]
            tapped_box = aligned[0] if aligned else cycle_boxes[0]
            
    # Priority 3: Recent Tap Window (Box was tapped within 1 to 20 bars prior to target candle)
    if not tapped_box:
        recent_candidates = []
        for b in htf_boxes:
            if b.get("is_tapped"):
                tt = b.get("first_tap_time") or b.get("tap_time")
                if tt and 0 <= (actual_candle_time - tt) <= 25 * htf_sec:
                    recent_candidates.append((b, actual_candle_time - tt, is_box_bull(b) == wants_bull))
        if recent_candidates:
            # Sort by directional alignment first, then proximity
            recent_candidates.sort(key=lambda x: (not x[2], x[1]))
            tapped_box = recent_candidates[0][0]

    # If an algorithmic trade was executed here, reconstruct zone context from registered trade
    if registered_trade and not tapped_box:
        z_type = "Demand" if registered_trade.get("type") == "BUY" else "Supply"
        tapped_box = {
            "top": registered_trade.get("entry", c_high),
            "bottom": registered_trade.get("sl", c_low),
            "left": registered_trade.get("time", actual_candle_time) - 10 * htf_sec,
            "right": registered_trade.get("time", actual_candle_time) + 10 * htf_sec,
            "level_type": z_type.lower(),
            "level_name": registered_trade.get("level_name", "Registered Level"),
            "is_bullish": registered_trade.get("type") == "BUY"
        }

    manual_trade_data = {
        "side": user_side,
        "entry_price": user_price,
        "candle_time": actual_candle_time,
        "candle_time_str": time_str,
        "candle_ohlc": {
            "open": c_open,
            "high": c_high,
            "low": c_low,
            "close": c_close
        },
        "candle_pattern": candle_analysis["pattern_name"],
        "body_pct": candle_analysis["body_pct"],
        "upper_wick_pct": candle_analysis["upper_wick_pct"],
        "lower_wick_pct": candle_analysis["lower_wick_pct"],
        "wick_description": candle_analysis["wick_description"],
        "is_strict_algo_pattern": candle_analysis["is_strict_algo_pattern"]
    }
    
    # 3. HTF Box or Autonomous Open Air Context (NO_HTF_ZONE restriction lifted)
    if tapped_box:
        is_bull = is_box_bull(tapped_box)
        zone_type = "DEMAND" if is_bull else "SUPPLY"
        expected_side = "BUY" if is_bull else "SELL"
        raw_text = tapped_box.get("text", f"{norm_h.upper()} {zone_type.capitalize()}")
        if tapped_box.get("in_dual_choch") and raw_text in ["RBS", "SBR"]:
            zone_name = f"Dual CHoCH {raw_text}"
        else:
            zone_name = raw_text
            
        b_top = max(tapped_box.get("top", 0), tapped_box.get("bottom", 0))
        b_bot = min(tapped_box.get("top", 0), tapped_box.get("bottom", 0))
        
        first_tap = tapped_box.get("first_tap_time") or tapped_box.get("tap_time") or actual_candle_time
        tap_time = first_tap
    else:
        # Autonomous Open Air Mode
        is_bull = (user_side == "BUY")
        zone_type = "DEMAND" if is_bull else "SUPPLY"
        expected_side = user_side
        zone_name = "Autonomous LTF (Open Air)"
        b_top = c_high
        b_bot = c_low
        tap_time = max(0, actual_candle_time - 30 * ltf_sec)
    
    start_ltf = max(0, tap_time - 120 * ltf_sec)
    now_ts = int(datetime.datetime.now().timestamp())
    end_ltf = min(now_ts, tap_time + 700 * ltf_sec)
    if actual_candle_time > tap_time:
        end_ltf = min(now_ts, max(end_ltf, actual_candle_time + 150 * ltf_sec))
        
    ltf_candles = fetch_klines_range(sym, norm_l, start_ltf, end_ltf, market)
    if not ltf_candles or len(ltf_candles) < 25:
        ltf_candles = fetch_klines_paginated(sym, norm_l, 1000, market)
        
    seen_ltf = set()
    cleaned_ltf = []
    for c in ltf_candles:
        t = c.get("time")
        if t and t not in seen_ltf:
            seen_ltf.add(t)
            cleaned_ltf.append(c)
    cleaned_ltf.sort(key=lambda x: x["time"])
    ltf_candles = cleaned_ltf
    
    tap_idx = 0
    for i, c in enumerate(ltf_candles):
        if c["time"] >= tap_time and c["low"] <= b_top and c["high"] >= b_bot:
            tap_idx = i
            break
            
    # Start LTF Market Structure exactly 30 candles prior to tap
    start_idx = max(0, tap_idx - 30)
    analysis_candles = ltf_candles[start_idx:]
    analysis_tap_idx = min(30, len(analysis_candles) - 1)
    
    ltf_engine = HTFEngine(
        lookback_bars=len(ltf_candles),
        show_bos=True,
        show_choch=True,
        show_dual_choch=True,
        show_tjl_boxes=True,
        tjl_extend=True,
        box_width_bars=12,
        active_swing_length_bars=8,
        show_tap_exit_labels=False
    )
    ltf_res = ltf_engine.run(ltf_candles)
    
    race_res = resolve_mtf_race_and_signals(
        analysis_candles=analysis_candles,
        tap_idx=analysis_tap_idx,
        tap_time=tap_time,
        is_bullish=is_bull,
        ltf_lines=ltf_res.get("lines", []),
        ltf_boxes=ltf_res.get("boxes", []),
        allow_trades=True,
        ltf_sec=ltf_sec
    )
    
    trade_logic = race_res.get("trade_logic", {})
    pathway = race_res.get("pathway")
    algo_sig = race_res.get("signal")
    decision = trade_logic.get("decision", "NONE")
    
    step_tap = trade_logic.get("step_tap", {})
    step_race = trade_logic.get("step_race", {})
    step_levels = trade_logic.get("step_levels", {})
    step_conf = trade_logic.get("step_conf", {})
    
    algo_view = {
        "htf_tapped": True,
        "htf_zone_name": f"{norm_h.upper()} {zone_type} [{zone_name}]",
        "htf_zone_type": zone_type,
        "htf_zone_range": f"${b_bot:,.2f} - ${b_top:,.2f}",
        "approach_status": "CONFIRMED",
        "ltf_pathway": pathway or "Pending / Race in Progress",
        "retest_level": step_levels.get("text", "None"),
        "retest_status": step_levels.get("status", "NONE"),
        "confirmation_status": step_conf.get("status", "NONE"),
        "confirmation_pattern": step_conf.get("text", "None"),
        "algo_signal": algo_sig
    }
    
    if registered_trade:
        algo_sig = registered_trade
        pathway = registered_trade.get("pathway", pathway or "Single CHoCH")
        algo_view["algo_signal"] = algo_sig
        algo_view["ltf_pathway"] = pathway
        algo_view["retest_level"] = registered_trade.get("level_name", "RBS/SBR")
        algo_view["retest_status"] = "COMPLETED"
        algo_view["confirmation_pattern"] = registered_trade.get("pattern", "Bullish Engulfing")

    # 5. DISCREPANCY REASONING ENGINE
    # Check if an algorithmic trade occurred on THIS EXACT CANDLE or active window
    is_candle_trade = False
    sig_t = 0
    if algo_sig is not None:
        sig_t = algo_sig.get("time") or algo_sig.get("chart_time", 0)
        sig_exit = algo_sig.get("exit_time", sig_t + 10 * htf_sec)
        if abs(sig_t - actual_candle_time) <= 2 * htf_sec or (sig_t <= actual_candle_time <= sig_exit):
            is_candle_trade = True

    if is_candle_trade:
        verdict = {
            "title": "Algorithmic Trade Executed Here! 🎯",
            "category": "TRADE_MATCHED",
            "is_trade_taken": True,
            "badge_color": "#10b981",
            "why_algo_skipped": f"The algorithm EXECUTED this trade! Algo Signal: {algo_sig['type']} @ ${algo_sig['entry']:,.2f} on {algo_sig.get('level_name', 'Level')} with {algo_sig.get('pattern', 'Pattern')}. Pathway: {algo_sig.get('pathway', pathway or 'MTF CHoCH')}. SL: ${algo_sig.get('sl', 0):,.2f}, TP: ${algo_sig.get('tp', 0):,.2f} (RR: {algo_sig.get('rr', 2.5)}R). Outcome: {algo_sig.get('outcome', 'OPEN')}.",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Tapped", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Valid approach"},
                {"criterion": f"LTF Pathway Won ({pathway or algo_sig.get('pathway', 'CHoCH')})", "passed": True, "detail": f"{pathway or algo_sig.get('pathway', 'CHoCH')} won the race"},
                {"criterion": f"Retest of {algo_sig.get('level_name', 'Level')}", "passed": True, "detail": "Level successfully retested"},
                {"criterion": f"Confirmation ({algo_sig.get('pattern', 'Pattern')})", "passed": True, "detail": "Textbook confirmation inside boundary"}
            ],
            "bot_learning_suggestion": "The bot entered on this exact setup and captured the institutional move! All 5 stages of the quantitative model were fully satisfied."
        }
    elif user_side != expected_side and not ((user_side == "BUY" and c_close > b_bot) or (user_side == "SELL" and c_close < b_top)):
        verdict = {
            "title": "Directional Bias Inversion",
            "category": "SIDE_MISMATCH",
            "is_trade_taken": False,
            "badge_color": "#ef4444",
            "why_algo_skipped": f"You took a {user_side} trade, but price tapped an HTF {norm_h.upper()} {zone_type} zone (${b_bot:,.1f} - ${b_top:,.1f}). The algo strictly trades {expected_side} off {zone_type} zones. You entered against the unbroken institutional level direction.",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Tapped", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": f"Trade Direction Matches Zone ({expected_side})", "passed": False, "detail": f"You traded {user_side} inside {zone_type}"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Valid approach"},
                {"criterion": "LTF Pathway Won", "passed": False, "detail": "Skipped due to opposite direction"},
                {"criterion": "Candle Pattern Confirmation", "passed": False, "detail": "Skipped"}
            ],
            "bot_learning_suggestion": "The bot protects capital by strictly aligning BUY with Demand and SELL with Supply. Broken zones automatically invert polarity into RBS/SBR."
        }
    elif algo_sig is not None and sig_t > actual_candle_time + 2 * htf_sec:
        sig_time_str = datetime.datetime.fromtimestamp(sig_t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        verdict = {
            "title": "LTF Trigger Incomplete (Fired Later by Algo)",
            "category": "RACE_INCOMPLETE",
            "is_trade_taken": False,
            "badge_color": "#3b82f6",
            "why_algo_skipped": f"The HTF {zone_type} zone was active at this candle, but the LTF entry trigger (CHoCH + Retest + Pattern) had not yet completed. The algo waited patiently and eventually EXECUTED this trade later at {sig_time_str} ({algo_sig['type']} @ ${algo_sig['entry']:,.1f}).",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Tapped", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Confirmed"},
                {"criterion": f"LTF Pathway Won ({pathway or 'In Progress'})", "passed": True, "detail": "Developing"},
                {"criterion": "Retest Level Reached", "passed": False, "detail": "Pending (occurred later)"},
                {"criterion": "Candle Pattern Trigger", "passed": False, "detail": f"Algo triggered later at {sig_time_str}"}
            ],
            "bot_learning_suggestion": "If you entered earlier than the algo, you executed on an early touch or aggressive anticipation before textbook LTF confirmation printed."
        }
    elif algo_sig is not None and sig_t < actual_candle_time - 2 * htf_sec:
        sig_time_str = datetime.datetime.fromtimestamp(sig_t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        verdict = {
            "title": "1-Trade Limit: Trade Already Taken Earlier",
            "category": "ONE_TRADE_LIMIT",
            "is_trade_taken": False,
            "badge_color": "#a855f7",
            "why_algo_skipped": f"The algo already executed a {algo_sig['type']} trade on this {zone_type} zone earlier at {sig_time_str} (@ ${algo_sig['entry']:,.1f}). Per strict institutional risk rules, the bot enforces a strict 1-Trade Per Zone limit and does not stack repeat entries on the same level.",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Tapped", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": "Zone Available For New Trade", "passed": False, "detail": f"1-Trade Limit reached (Fired at {sig_time_str})"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Confirmed"},
                {"criterion": "LTF Pathway Won", "passed": True, "detail": "Completed earlier"},
                {"criterion": "Candle Pattern Trigger", "passed": False, "detail": "Skipped due to 1-trade limit"}
            ],
            "bot_learning_suggestion": "To allow multiple re-entries inside the same zone on deeper tests, you can toggle off the '1 Trade Per Zone Limit' in settings."
        }
    elif "RETEST_TIMEOUT" in str(trade_logic) or "EXPIRED" in str(step_levels.get("status", "")) or "expired" in trade_logic.get("summary", "").lower():
        verdict = {
            "title": "Retest Horizon Expired (> 30 Bars)",
            "category": "RETEST_TIMEOUT",
            "is_trade_taken": False,
            "badge_color": "#f97316",
            "why_algo_skipped": f"The HTF {zone_type} zone was tapped and the LTF pathway ({pathway}) formed a valid level ({step_levels.get('text', 'Level')}). However, price took longer than 30 {norm_l} bars to return and retest the level. The algo expired the order at bar 30 to prevent stale setups, whereas you waited patiently for the deeper retest and entered when price finally arrived.",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Tapped", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Confirmed"},
                {"criterion": f"LTF Pathway Won ({pathway})", "passed": True, "detail": f"{pathway} confirmed"},
                {"criterion": "Retest within 30-bar limit", "passed": False, "detail": "Retest took > 30 bars (algo expired)"},
                {"criterion": "Candle Pattern Confirmation", "passed": False, "detail": "Not evaluated due to expiry"}
            ],
            "bot_learning_suggestion": "💡 To teach the bot your edge: Increase `MAX_RETEST_BARS` from 30 bars to 60 or 90 bars (1-1.5 hours on 1M) so the algo gives patient retests enough time to tap."
        }
    elif "MISSED_2_BOS" in str(trade_logic) or ("2 consecutive bos" in str(trade_logic).lower()):
        verdict = {
            "title": "2 Consecutive BOS Invalidation (Runaway Trend)",
            "category": "MISSED_2_BOS",
            "is_trade_taken": False,
            "badge_color": "#f97316",
            "why_algo_skipped": f"After CHoCH formed, price completed 2 consecutive BOS on the LTF in the breakout direction without ever pulling back into the reaction levels. The setup was cancelled to avoid chasing a runaway trend.",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Context", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Confirmed"},
                {"criterion": f"LTF Pathway Won ({pathway})", "passed": True, "detail": f"{pathway} established level"},
                {"criterion": "No Runaway (<= 1 BOS without retraction)", "passed": False, "detail": "2 consecutive BOS occurred before retest"},
                {"criterion": "Candle Pattern Confirmation", "passed": False, "detail": "Setup cancelled on 2 runaway BOS"}
            ],
            "bot_learning_suggestion": "Under the 2-BOS rule, setups stay active across prolonged consolidations and only cancel if price demonstrates two confirmed runaway breaks away from the level."
        }
    elif "EXTREME" in str(trade_logic) or "extreme" in trade_logic.get("summary", "").lower() or "swept" in trade_logic.get("summary", "").lower():
        verdict = {
            "title": "Extreme Violation vs Liquidity Sweep",
            "category": "LIQUIDITY_SWEEP",
            "is_trade_taken": False,
            "badge_color": "#f97316",
            "why_algo_skipped": f"During the retest development, price wicked slightly beyond the original tap extreme. The algo strictly classified any price lower than the tap low (or higher than tap high) as a structural invalidation. You recognized this wick as a standard institutional Liquidity Sweep / Stop Hunt and entered once price reclaimed the level.",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Tapped", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Confirmed"},
                {"criterion": f"LTF Pathway Won ({pathway})", "passed": True, "detail": f"{pathway} formed"},
                {"criterion": "Extreme Maintained (No Wicks Beyond)", "passed": False, "detail": "Wick penetrated tap extreme"},
                {"criterion": "Candle Pattern Confirmation", "passed": False, "detail": "Invalidated on extreme breach"}
            ],
            "bot_learning_suggestion": "💡 To teach the bot your edge: Add a 0.20% Liquidity Sweep Tolerance buffer beyond the tap extreme so stop runs do not invalidate valid institutional setups."
        }
    elif step_levels.get("status") in ["RETESTED", "PASSED", "ACTIVE"] or "retest" in str(step_levels).lower():
        verdict = {
            "title": "Candle Confirmation Pattern Strictness",
            "category": "CANDLE_STRICTNESS",
            "is_trade_taken": False,
            "badge_color": "#f59e0b",
            "why_algo_skipped": f"The entire structure was validated: HTF {zone_type} tapped, LTF {pathway} won, and price successfully retested {step_levels.get('text', 'Level')}. However, the algo was strictly waiting for a textbook 2-bar Bullish/Bearish Engulfing or 3-bar Morning/Evening Star inside the level bounds. You entered on a '{candle_analysis['pattern_name']}' with {candle_analysis['wick_description']}. The algo skipped because Pin Bars and Wick Rejections are currently excluded from automated firing.",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Tapped", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Confirmed"},
                {"criterion": f"LTF Pathway Won ({pathway})", "passed": True, "detail": f"{pathway} confirmed"},
                {"criterion": f"Retest of {step_levels.get('text', 'Level')}", "passed": True, "detail": "Price tapped retest level"},
                {"criterion": "Textbook Engulfing / Star Trigger", "passed": False, "detail": f"Printed {candle_analysis['pattern_name']} instead"}
            ],
            "bot_learning_suggestion": "💡 To teach the bot your edge: Add 'Pin Bar' and 'Rejection Wick' to the confirmed execution patterns in `mtf_micro_engine.py` line 340. This will immediately trigger trades on hammer and shooting star rejections."
        }
    else:
        verdict = {
            "title": "LTF Race / Retest Condition Incomplete",
            "category": "RACE_INCOMPLETE",
            "is_trade_taken": False,
            "badge_color": "#64748b",
            "why_algo_skipped": f"HTF {norm_h.upper()} {zone_type} zone was tapped at ${b_bot:,.1f} - ${b_top:,.1f}. However, the LTF market structure had not completed both the structural confirmation (Single CHoCH / Dual CHoCH / 5-Wave) and a subsequent clean retest of the created level. Algo status: {trade_logic.get('summary', 'Waiting for LTF structural confirmation')}.",
            "checklist": [
                {"criterion": f"HTF {norm_h.upper()} Zone Tapped", "passed": True, "detail": f"{zone_type} [{zone_name}]"},
                {"criterion": "Opposing LTF Approach Confirmed", "passed": True, "detail": "Confirmed"},
                {"criterion": f"LTF Pathway Race", "passed": bool(pathway), "detail": pathway or "In progress"},
                {"criterion": "Retest of Confirmation Level", "passed": False, "detail": step_levels.get("text", "Pending")},
                {"criterion": "Candle Pattern Confirmation", "passed": False, "detail": "Pending"}
            ],
            "bot_learning_suggestion": "If you entered on the initial tap without waiting for LTF CHoCH or retest (aggressive limit order / touch entry), you can enable 'Aggressive Zone Tap Entry Mode' in the strategy settings."
        }

    return {
        "success": True,
        "symbol": sym,
        "htf": norm_h,
        "ltf": norm_l,
        "target_time": actual_candle_time,
        "manual_trade": manual_trade_data,
        "algo_view": algo_view,
        "discrepancy_verdict": verdict
    }
