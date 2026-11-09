import re

with open("ltf_approach_engine.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update lines 54-62
old_1 = """    box_top = max(htf_box.get("top", 0), htf_box.get("bottom", 0)) if htf_box else None
    box_bot = min(htf_box.get("top", 0), htf_box.get("bottom", 0)) if htf_box else None
    buffer = max(5.0, round(box_top * 0.0005, 2)) if box_top else 40.0

    def is_breakout_above(close_val, peak_val):
        buf = max(1.0, peak_val * 0.00002)
        return close_val > (peak_val + buf)

    def is_breakout_below(close_val, trough_val):
        buf = max(1.0, trough_val * 0.00002)
        return close_val < (trough_val - buf)"""

new_1 = """    box_top = max(htf_box.get("top", 0), htf_box.get("bottom", 0)) if htf_box else None
    box_bot = min(htf_box.get("top", 0), htf_box.get("bottom", 0)) if htf_box else None
    ref_p = box_top or (candles[0]["close"] if candles else 100.0)
    buffer = (box_top * 0.0005) if box_top else (ref_p * 0.0005)

    def is_breakout_above(close_val, peak_val):
        buf = peak_val * 0.00002
        return close_val > (peak_val + buf)

    def is_breakout_below(close_val, trough_val):
        buf = trough_val * 0.00002
        return close_val < (trough_val - buf)"""

code = code.replace(old_1.replace("\r\n", "\n").replace("\n", "\r\n"), new_1.replace("\r\n", "\n").replace("\n", "\r\n"))
if new_1.replace("\r\n", "\n") not in code.replace("\r\n", "\n"):
    code = code.replace(old_1.replace("\r\n", "\n"), new_1.replace("\r\n", "\n"))

# 2. Update lines 692-696
old_2 = """    box_top = None
    box_bot = None
    buffer = 40.0
    if htf_box:
        box_top = max(htf_box.get("top", 0), htf_box.get("bottom", 0))
        box_bot = min(htf_box.get("top", 0), htf_box.get("bottom", 0))
        buffer = max(5.0, round(box_top * 0.0005, 2))"""

new_2 = """    box_top = None
    box_bot = None
    ref_p = candles[0]["close"] if candles else 100.0
    buffer = ref_p * 0.0005
    if htf_box:
        box_top = max(htf_box.get("top", 0), htf_box.get("bottom", 0))
        box_bot = min(htf_box.get("top", 0), htf_box.get("bottom", 0))
        buffer = box_top * 0.0005"""

code = code.replace(old_2.replace("\r\n", "\n").replace("\n", "\r\n"), new_2.replace("\r\n", "\n").replace("\n", "\r\n"))
if new_2.replace("\r\n", "\n") not in code.replace("\r\n", "\n"):
    code = code.replace(old_2.replace("\r\n", "\n"), new_2.replace("\r\n", "\n"))

# 3. Update lines 804-835
old_3 = """        # Valid pattern touching active level found!
        entry_price = c_curr["close"]
        tick_buf = max(0.5, round(entry_price * 0.0002, 2))

        if is_bullish:
            extreme = min(c["low"] for c in pattern_candles)
            sl_price = round(extreme - tick_buf, 2)
            risk = round(entry_price - sl_price, 2)
        else:
            extreme = max(c["high"] for c in pattern_candles)
            sl_price = round(extreme + tick_buf, 2)
            risk = round(sl_price - entry_price, 2)

        if risk <= 0:
            continue

        # Target: Opposite HTF level (or fixed 3.0R)
        htf_tp = find_opposing_htf_level(entry_price, is_bullish, htf_boxes, c_curr["time"])
        if htf_tp is None:
            reward = round(risk * 3.0, 2)
            tp_price = round(entry_price + reward if is_bullish else entry_price - reward, 2)
            rr = 3.0
        else:
            reward = round(abs(htf_tp - entry_price), 2)
            rr = round(reward / risk, 2)
            tp_price = htf_tp"""

new_3 = """        # Valid pattern touching active level found!
        entry_price = c_curr["close"]
        tick_buf = entry_price * 0.0002

        if is_bullish:
            extreme = min(c["low"] for c in pattern_candles)
            sl_price = extreme - tick_buf
            risk = entry_price - sl_price
        else:
            extreme = max(c["high"] for c in pattern_candles)
            sl_price = extreme + tick_buf
            risk = sl_price - entry_price

        if risk <= 0:
            continue

        # Target: Opposite HTF level (or fixed 3.0R)
        htf_tp = find_opposing_htf_level(entry_price, is_bullish, htf_boxes, c_curr["time"])
        if htf_tp is None:
            reward = risk * 3.0
            tp_price = entry_price + reward if is_bullish else entry_price - reward
            rr = 3.0
        else:
            reward = abs(htf_tp - entry_price)
            rr = reward / risk
            tp_price = htf_tp"""

code = code.replace(old_3.replace("\r\n", "\n").replace("\n", "\r\n"), new_3.replace("\r\n", "\n").replace("\n", "\r\n"))
if new_3.replace("\r\n", "\n") not in code.replace("\r\n", "\n"):
    code = code.replace(old_3.replace("\r\n", "\n"), new_3.replace("\r\n", "\n"))

# 4. Update line 895
old_4 = 'buffer = max(5.0, round(box_top * 0.0005, 2))'
new_4 = 'buffer = box_top * 0.0005'
code = code.replace(old_4, new_4)

# 5. Update deduplication keys round(..., 1) -> round(..., 5) if < 50
old_5 = 'round(box_clean["top"], 1), round(box_clean["bottom"], 1)'
new_5 = 'round(box_clean["top"], 5) if box_clean["top"] < 50 else round(box_clean["top"], 1), round(box_clean["bottom"], 5) if box_clean["bottom"] < 50 else round(box_clean["bottom"], 1)'
code = code.replace(old_5, new_5)

old_6 = 'round(b_cand["top"], 1), round(b_cand["bottom"], 1)'
new_6 = 'round(b_cand["top"], 5) if b_cand["top"] < 50 else round(b_cand["top"], 1), round(b_cand["bottom"], 5) if b_cand["bottom"] < 50 else round(b_cand["bottom"], 1)'
code = code.replace(old_6, new_6)

old_7 = 'round(top_val, 1), round(bot_val, 1)'
new_7 = 'round(top_val, 5) if top_val < 50 else round(top_val, 1), round(bot_val, 5) if bot_val < 50 else round(bot_val, 1)'
code = code.replace(old_7, new_7)

with open("ltf_approach_engine.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully updated ltf_approach_engine.py for all asset classes!")
