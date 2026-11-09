import json
from datetime import datetime, timezone
from ltf_approach_engine import compute_ltf_approach_structure
from htf_engine import HTFEngine
from pattern_scanner import (
    is_valid_bullish_engulfing,
    is_valid_bearish_engulfing,
    is_valid_morning_star,
    is_valid_evening_star
)
from mtf_micro_engine import is_morning_star, is_evening_star

with open('data/btc_1m_oct2026.json') as f:
    candles_1m = json.load(f)

with open('data/btc_15m_oct2026.json') as f:
    candles_15m = json.load(f)

htf_engine = HTFEngine(lookback_bars=len(candles_15m))
htf_out = htf_engine.run(candles_15m)
htf_boxes = htf_out.get('boxes', [])

def candle_touches_level(c, lvl_top, lvl_bot):
    return c['high'] >= lvl_bot and c['low'] <= lvl_top

def find_nearest_htf_liquidity(entry_price, is_bullish, htf_candles, htf_boxes):
    candidates = []
    # 1. Significant HTF Swing Pivots (5-bar fractal on 15m)
    for i in range(2, len(htf_candles) - 2):
        c = htf_candles[i]
        c_prev1 = htf_candles[i-1]
        c_prev2 = htf_candles[i-2]
        c_next1 = htf_candles[i+1]
        c_next2 = htf_candles[i+2]
        if is_bullish:
            if (c['high'] > c_prev1['high'] and c['high'] > c_prev2['high'] and
                c['high'] > c_next1['high'] and c['high'] > c_next2['high']):
                if c['high'] > entry_price:
                    candidates.append(c['high'])
        else:
            if (c['low'] < c_prev1['low'] and c['low'] < c_prev2['low'] and
                c['low'] < c_next1['low'] and c['low'] < c_next2['low']):
                if c['low'] < entry_price:
                    candidates.append(c['low'])

    # 2. Opposing HTF Boxes (Supply zones for Buy, Demand zones for Sell)
    for b in htf_boxes:
        b_top = max(b.get('top', 0), b.get('bottom', 0))
        b_bot = min(b.get('top', 0), b.get('bottom', 0))
        if is_bullish and not b.get('is_bullish', True): # Opposing supply zone
            if b_bot > entry_price:
                candidates.append(b_bot)
        elif not is_bullish and b.get('is_bullish', True): # Opposing demand zone
            if b_top < entry_price:
                candidates.append(b_top)

    if not candidates:
        return None

    if is_bullish:
        return min(candidates)
    else:
        return max(candidates)

def evaluate_trade_for_tap(target_time):
    res = compute_ltf_approach_structure(target_time, candles_1m, htf_boxes, 900)
    tap_info = res.get('tap_info')
    if not tap_info:
        return None, "NO_QUALIFIED_TAP"

    cutoff_time = tap_info.get('cutoff_time')
    if not cutoff_time:
        return None, "NO_CUTOFF"

    active_levels = []
    for b in res.get('boxes', []):
        if not b.get('text', '').upper().startswith('HTF'):
            active_levels.append(b)

    # Determine polarity
    is_bullish = 'DEMAND' in tap_info.get('box_name', '').upper() or 'TJL' in tap_info.get('box_name', '').upper()
    for b in htf_boxes:
        if b.get('text') == tap_info.get('box_name') or b.get('name') == tap_info.get('box_name'):
            is_bullish = b.get('is_bullish', is_bullish)
            break

    # Find candles after cutoff
    start_idx = None
    for idx, c in enumerate(candles_1m):
        if c['time'] >= cutoff_time:
            start_idx = idx
            break

    if start_idx is None:
        return None, "NO_POST_CUTOFF_CANDLES"

    search_end = min(len(candles_1m), start_idx + 180)

    for i in range(start_idx, search_end):
        if i < 2:
            continue
        c_curr = candles_1m[i]
        c_prev = candles_1m[i-1]
        c_prev2 = candles_1m[i-2]

        pattern_name = None
        pattern_candles = []

        # 1. Check Bullish / Bearish Engulfing
        if is_bullish:
            # Check standard engulfing or body engulfing
            if is_valid_bullish_engulfing(c_prev, c_curr) or (
                c_curr['close'] > c_curr['open'] and
                c_prev['close'] <= c_prev['open'] + 1.0 and
                c_curr['close'] >= c_prev['open']
            ):
                pattern_name = "Bullish Engulfing"
                pattern_candles = [c_prev, c_curr]
        else:
            if is_valid_bearish_engulfing(c_prev, c_curr) or (
                c_curr['close'] < c_curr['open'] and
                c_prev['close'] >= c_prev['open'] - 1.0 and
                c_curr['close'] <= c_prev['open']
            ):
                pattern_name = "Bearish Engulfing"
                pattern_candles = [c_prev, c_curr]

        # 2. Check Morning / Evening Star
        if not pattern_name:
            if is_bullish:
                c1_b = abs(c_prev2['close'] - c_prev2['open'])
                c2_b = abs(c_prev['close'] - c_prev['open'])
                c3_b = abs(c_curr['close'] - c_curr['open'])
                is_star_c2 = (c2_b < c1_b) and (c2_b < c3_b)
                c1_red = c_prev2['close'] < c_prev2['open']
                c3_green = c_curr['close'] > c_curr['open']
                c3_deep = c_curr['close'] >= (c_prev2['open'] + c_prev2['close']) / 2.0
                if c1_red and c3_green and is_star_c2 and c3_deep:
                    pattern_name = "Morning Star"
                    pattern_candles = [c_prev2, c_prev, c_curr]
            else:
                c1_b = abs(c_prev2['close'] - c_prev2['open'])
                c2_b = abs(c_prev['close'] - c_prev['open'])
                c3_b = abs(c_curr['close'] - c_curr['open'])
                is_star_c2 = (c2_b < c1_b) and (c2_b < c3_b)
                c1_green = c_prev2['close'] > c_prev2['open']
                c3_red = c_curr['close'] < c_curr['open']
                c3_deep = c_curr['close'] <= (c_prev2['open'] + c_prev2['close']) / 2.0
                if c1_green and c3_red and is_star_c2 and c3_deep:
                    pattern_name = "Evening Star"
                    pattern_candles = [c_prev2, c_prev, c_curr]

        if not pattern_name:
            continue

        # Check if any candle of pattern touches any active level
        matched_level = None
        for lvl in active_levels:
            lvl_top = max(lvl['top'], lvl['bottom'])
            lvl_bot = min(lvl['top'], lvl['bottom'])
            if any(candle_touches_level(c, lvl_top, lvl_bot) for c in pattern_candles):
                matched_level = lvl
                break

        if not matched_level:
            continue

        # Calculate trade parameters
        entry_price = c_curr['close']
        tick_buf = max(0.5, round(entry_price * 0.0002, 2))

        if is_bullish:
            extreme = min(c['low'] for c in pattern_candles)
            sl_price = round(extreme - tick_buf, 2)
            risk = round(entry_price - sl_price, 2)
        else:
            extreme = max(c['high'] for c in pattern_candles)
            sl_price = round(extreme + tick_buf, 2)
            risk = round(sl_price - entry_price, 2)

        if risk <= 0:
            continue

        htf_tp = find_nearest_htf_liquidity(entry_price, is_bullish, candles_15m, htf_boxes)
        if not htf_tp:
            # Fallback 2.5R
            reward = round(risk * 2.5, 2)
            htf_tp = round(entry_price + reward if is_bullish else entry_price - reward, 2)
            rr = 2.5
        else:
            reward = round(abs(htf_tp - entry_price), 2)
            rr = round(reward / risk, 2)

        is_executed = rr >= 2.5

        trade_info = {
            "action": "BUY" if is_bullish else "SELL",
            "time": c_curr['time'],
            "time_str": datetime.fromtimestamp(c_curr['time'], timezone.utc).strftime('%H:%M'),
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": htf_tp,
            "risk": risk,
            "reward": reward,
            "rr": rr,
            "level_name": matched_level.get('text', 'Level'),
            "pattern_name": pattern_name,
            "executed": is_executed,
            "status": "EXECUTED" if is_executed else "SKIPPED_RR_BELOW_2_5"
        }
        return trade_info, "SUCCESS"

    return None, "NO_RETEST_FOUND"

test_cases = [
    ('11-10 21:16 Demand', 1791753360),
    ('07-10 13:48 Demand', 1791380880),
    ('02-10 04:30 Supply', 1790915400)
]

for label, t in test_cases:
    trade, status = evaluate_trade_for_tap(t)
    print(f"\n==================== {label} ====================")
    print(f"Status: {status}")
    if trade:
        print(f"  Action: {trade['action']} at {trade['time_str']}")
        print(f"  Pattern: {trade['pattern_name']} touching {trade['level_name']}")
        print(f"  Entry: {trade['entry_price']} | SL: {trade['sl_price']} | TP: {trade['tp_price']}")
        print(f"  Risk: {trade['risk']} | Reward: {trade['reward']} | R:R: {trade['rr']} R")
        print(f"  Execution: {trade['status']}")
