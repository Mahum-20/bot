import logging
from typing import List, Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# HTF to LTF Mapping Rule:
# Strictly restricted to 3 active trading combinations:
# 1. HTF 15m -> LTF 1m
# 2. HTF 1h  -> LTF 1m
# 3. HTF 4h  -> LTF 5m
# (1D and 5M HTFs are explicitly NOT traded)
HTF_TO_LTF_MAP = {
    "15m": "1m",
    "m15": "1m",
    "1h": "1m",
    "h1": "1m",
    "4h": "5m",
    "h4": "5m"
}

def get_target_ltf(htf_interval: str) -> Optional[str]:
    """Returns the corresponding LTF interval for the given HTF timeframe, or None if unsupported or trading is disabled."""
    return HTF_TO_LTF_MAP.get(htf_interval.lower() if htf_interval else "")

def is_valid_bullish_engulfing(c1: Dict, c2: Dict) -> bool:
    """
    Bullish Engulfing (Aligned 1:1 with Reversal Candlestick Patterns.pine):
    - 1st Candle: Red (bearish) or Doji (close <= open).
    - 2nd Candle: Green (bullish, close > open).
    - High Condition: The high of the 2nd candle must be higher than the high of the 1st candle.
    - Body Condition: The close of the 2nd candle must be at or above the open of the 1st candle.
    """
    is_red_or_doji_1 = c1["close"] <= c1["open"]
    is_green_2 = c2["close"] > c2["open"]
    high_cond = c2["high"] > c1["high"]
    body_cond = c2["close"] >= c1["open"]
    return is_red_or_doji_1 and is_green_2 and high_cond and body_cond

def is_valid_bearish_engulfing(c1: Dict, c2: Dict) -> bool:
    """
    Bearish Engulfing (Aligned 1:1 with Reversal Candlestick Patterns.pine):
    - 1st Candle: Green (bullish) or Doji (close >= open).
    - 2nd Candle: Red (bearish, close < open).
    - Low Condition: The low of the 2nd candle must be lower than the low of the 1st candle.
    - Body Condition: The close of the 2nd candle must be at or below the open of the 1st candle.
    """
    is_green_or_doji_1 = c1["close"] >= c1["open"]
    is_red_2 = c2["close"] < c2["open"]
    low_cond = c2["low"] < c1["low"]
    body_cond = c2["close"] <= c1["open"]
    return is_green_or_doji_1 and is_red_2 and low_cond and body_cond

def is_non_doji(c: Dict, min_body_ratio: float = 0.25) -> bool:
    """Checks that the candle body is substantial (not a Doji)."""
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    body = abs(c["close"] - c["open"])
    return (body / rng) >= min_body_ratio

def is_valid_morning_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
    """
    Morning Star:
    - 1st Candle: Red (bearish) with a big body (must not be a Doji).
    - 2nd Candle: Body strictly smaller than both 1st and 3rd candles, and lower wick dips below lows of 1st and 3rd candles.
    - 3rd Candle: Green (bullish) with a mid-sized or large body (must not be a Doji).
    """
    is_red_1 = (c1["close"] < c1["open"]) and is_non_doji(c1, 0.25)
    c1_body = abs(c1["close"] - c1["open"])
    c2_body = abs(c2["close"] - c2["open"])
    c3_body = abs(c3["close"] - c3["open"])
    smaller_body_2 = (c2_body < c1_body) and (c2_body < c3_body)
    wick_dip_2 = (c2["low"] < c1["low"]) and (c2["low"] < c3["low"])
    is_green_3 = (c3["close"] > c3["open"]) and is_non_doji(c3, 0.25)
    return is_red_1 and smaller_body_2 and wick_dip_2 and is_green_3

def is_valid_evening_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
    """
    Evening Star:
    - 1st Candle: Green (bullish) with a big body (must not be a Doji).
    - 2nd Candle: Body strictly smaller than both 1st and 3rd candles, and upper wick extends higher than highs of 1st and 3rd candles.
    - 3rd Candle: Red (bearish) with a mid-sized or large body (must not be a Doji).
    """
    is_green_1 = (c1["close"] > c1["open"]) and is_non_doji(c1, 0.25)
    c1_body = abs(c1["close"] - c1["open"])
    c2_body = abs(c2["close"] - c2["open"])
    c3_body = abs(c3["close"] - c3["open"])
    smaller_body_2 = (c2_body < c1_body) and (c2_body < c3_body)
    wick_peak_2 = (c2["high"] > c1["high"]) and (c2["high"] > c3["high"])
    is_red_3 = (c3["close"] < c3["open"]) and is_non_doji(c3, 0.25)
    return is_green_1 and smaller_body_2 and wick_peak_2 and is_red_3

# In-memory cache for historical closed tap-to-exit windows
# Key: (symbol, ltf_interval, tap_time, exit_time, is_bullish, first_only, box_id, b_top, b_bot) -> List[label dicts]
_CYCLE_LABELS_CACHE: Dict[Tuple, List[Dict]] = {}

def scan_cycle_engulfing(
    ltf_candles: List[Dict],
    is_bullish: bool,
    b_top: Optional[float] = None,
    b_bot: Optional[float] = None,
    first_only: bool = False,
    box_id: str = ""
) -> List[Dict]:
    """
    Entry pattern scanning is currently dropped awaiting user redefinition.
    Returns empty list.
    """
    return []

def get_engulfing_labels_for_cycle(
    symbol: str,
    ltf_interval: str,
    tap_time: int,
    exit_time: int,
    is_bullish: bool,
    b_top: Optional[float] = None,
    b_bot: Optional[float] = None,
    box_id: str = "",
    market_type: str = "futures",
    first_only: bool = False,
    is_closed_cycle: bool = True,
    fetch_fn = None
) -> List[Dict]:
    """
    Retrieves engulfing pattern labels for a tap-to-exit window,
    starting scanning from the exact moment of zone tap on LTF,
    leveraging an in-memory cache for historical completed cycles.
    """
    cache_key = (symbol.upper(), ltf_interval.lower(), tap_time, exit_time, is_bullish, first_only, box_id, b_top, b_bot)
    if is_closed_cycle and cache_key in _CYCLE_LABELS_CACHE:
        return _CYCLE_LABELS_CACHE[cache_key]

    if fetch_fn is None:
        from binance_feed import fetch_klines_range
        fetch_fn = fetch_klines_range

    ltf_candles = fetch_fn(
        symbol=symbol,
        interval=ltf_interval,
        start_time_s=tap_time,
        end_time_s=exit_time,
        market_type=market_type
    )

    labels = scan_cycle_engulfing(
        ltf_candles,
        is_bullish=is_bullish,
        b_top=b_top,
        b_bot=b_bot,
        first_only=first_only,
        box_id=box_id
    )

    if is_closed_cycle:
        _CYCLE_LABELS_CACHE[cache_key] = labels

    return labels
