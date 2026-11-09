import math
from typing import Dict, List, Optional, Any, Tuple


# =====================================================================
# CANDLESTICK PATTERNS LOGIC
# =====================================================================

def is_bullish_engulfing(c1: Dict, c2: Dict) -> bool:
    """
    Bullish Engulfing pattern:
    Previous candle is red (bearish). Current candle is green (bullish) and
    its body or range completely engulfs the previous candle.
    """
    c1_red = c1["close"] < c1["open"]
    c2_green = c2["close"] > c2["open"]
    body_engulfed = (c2["open"] <= c1["close"]) and (c2["close"] >= c1["open"])
    wick_engulfed = (c2["high"] >= c1["high"]) and (c2["low"] <= c1["low"])
    return c1_red and c2_green and (body_engulfed or (wick_engulfed and c2["close"] > c1["open"]))


def is_morning_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
    """
    Morning Star pattern:
    c1: Strong bearish (red) candle.
    c2: Star candle with body strictly smaller than both c1 and c3.
    c3: Strong bullish (green) candle closing above midpoint of c1.
    """
    c1_red = c1["close"] < c1["open"]
    c1_body = abs(c1["close"] - c1["open"])
    c2_body = abs(c2["close"] - c2["open"])
    c3_body = abs(c3["close"] - c3["open"])
    c3_green = c3["close"] > c3["open"]
    
    smaller_star = (c2_body < c1_body) and (c2_body < c3_body)
    deep_close = c3["close"] >= (c1["open"] + c1["close"]) / 2.0
    gap_down = min(c2["open"], c2["close"]) <= c1["close"]

    return c1_red and c3_green and smaller_star and deep_close and gap_down


def is_bearish_engulfing(c1: Dict, c2: Dict) -> bool:
    """
    Bearish Engulfing pattern:
    Previous candle is green (bullish). Current candle is red (bearish) and
    its body or range completely engulfs the previous candle.
    """
    c1_green = c1["close"] > c1["open"]
    c2_red = c2["close"] < c2["open"]
    body_engulfed = (c2["open"] >= c1["close"]) and (c2["close"] <= c1["open"])
    wick_engulfed = (c2["high"] >= c1["high"]) and (c2["low"] <= c1["low"])
    return c1_green and c2_red and (body_engulfed or (wick_engulfed and c2["close"] < c1["open"]))


def is_evening_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
    """
    Evening Star pattern:
    c1: Strong bullish (green) candle.
    c2: Star candle with body strictly smaller than both c1 and c3.
    c3: Strong bearish (red) candle closing below midpoint of c1.
    """
    c1_green = c1["close"] > c1["open"]
    c1_body = abs(c1["close"] - c1["open"])
    c2_body = abs(c2["close"] - c2["open"])
    c3_body = abs(c3["close"] - c3["open"])
    c3_red = c3["close"] < c3["open"]
    
    smaller_star = (c2_body < c1_body) and (c2_body < c3_body)
    deep_close = c3["close"] <= (c1["open"] + c1["close"]) / 2.0
    gap_up = max(c2["open"], c2["close"]) >= c1["close"]

    return c1_green and c3_red and smaller_star and deep_close and gap_up


def detect_candlestick_patterns(candles: List[Dict]) -> List[Dict]:
    """
    Scans a series of candles and identifies:
      - Bullish Engulfing
      - Bearish Engulfing
      - Morning Star
      - Evening Star
    Returns formatted pattern markers for chart display.
    """
    patterns = []
    n = len(candles)
    if n < 2:
        return patterns

    for i in range(1, n):
        c_curr = candles[i]
        c_prev = candles[i - 1]
        c_prev2 = candles[i - 2] if i >= 2 else None

        # 1. Bullish Engulfing
        if is_bullish_engulfing(c_prev, c_curr):
            patterns.append({
                "id": f"pat_bull_eng_{c_curr['time']}",
                "name": "Bullish Engulfing",
                "type": "bullish",
                "time": c_curr["time"],
                "price": c_curr["low"],
                "position": "belowBar",
                "color": "#10b981",
                "shape": "arrowUp",
                "text": "Bullish Engulfing"
            })
            continue

        # 2. Bearish Engulfing
        if is_bearish_engulfing(c_prev, c_curr):
            patterns.append({
                "id": f"pat_bear_eng_{c_curr['time']}",
                "name": "Bearish Engulfing",
                "type": "bearish",
                "time": c_curr["time"],
                "price": c_curr["high"],
                "position": "aboveBar",
                "color": "#ef4444",
                "shape": "arrowDown",
                "text": "Bearish Engulfing"
            })
            continue

        # 3. Morning Star
        if c_prev2 and is_morning_star(c_prev2, c_prev, c_curr):
            patterns.append({
                "id": f"pat_morning_star_{c_curr['time']}",
                "name": "Morning Star",
                "type": "bullish",
                "time": c_curr["time"],
                "price": min(c_prev2["low"], c_prev["low"], c_curr["low"]),
                "position": "belowBar",
                "color": "#22c55e",
                "shape": "circle",
                "text": "Morning Star"
            })
            continue

        # 4. Evening Star
        if c_prev2 and is_evening_star(c_prev2, c_prev, c_curr):
            patterns.append({
                "id": f"pat_evening_star_{c_curr['time']}",
                "name": "Evening Star",
                "type": "bearish",
                "time": c_curr["time"],
                "price": max(c_prev2["high"], c_prev["high"], c_curr["high"]),
                "position": "aboveBar",
                "color": "#f43f5e",
                "shape": "circle",
                "text": "Evening Star"
            })
            continue

    return patterns


# =====================================================================
# ENTRY CODE REMOVED PER USER INSTRUCTION
# Automated trade entries / signals disabled. Only HTF levels and candlestick patterns kept.
# =====================================================================

def resolve_mtf_race_and_signals(*args, **kwargs) -> Dict[str, Any]:
    """
    Entry code disabled per user instruction.
    Returns no automated trade entries, keeping only indicator levels and pattern detection.
    """
    return {
        "signal": None,
        "signals": [],
        "pathway": "NONE",
        "status": "ENTRY_CODE_DISABLED",
        "levels": [],
        "boxes": [],
        "lines": [],
        "labels": [],
        "trade_logic": {
            "decision": "NO_ENTRY",
            "badge": "INDICATOR ONLY",
            "color": "#64748b",
            "summary": "Automated trade entries disabled. Showing HTF levels and candlestick patterns only."
        }
    }
