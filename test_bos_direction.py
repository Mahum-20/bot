import json
from ltf_approach_engine import find_tapped_htf_box
from htf_engine import HTFEngine

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

with open("data/btcusdt_4h_1y_oct2025_oct2026.json") as f:
    c_4h = json.load(f)
with open("data/btcusdt_5m_1y_oct2025_oct2026.json") as f:
    c_5m = json.load(f)

htf_engine = HTFEngine(lookback_bars=len(c_4h), show_tjl_boxes=True, tjl_extend=True)
boxes = htf_engine.run(c_4h).get("boxes", [])

taps_with_approach_bos = 0
total_taps = 0

for i in range(1000, 5000, 10):
    c = c_5m[i]
    box, tap_idx = find_tapped_htf_box(c["time"], c_5m, boxes, 14400)
    if box:
        total_taps += 1
        start_idx = max(0, tap_idx - 40)
        end_idx = min(len(c_5m), tap_idx + 240)
        trade_candles = c_5m[start_idx:end_idx]
        tap_actual_time = c_5m[tap_idx]["time"]
        is_bullish = box.get("is_bullish", True)
        expected_approach_dir = "bearish" if is_bullish else "bullish"
        
        eng = HTFEngine(lookback_bars=len(trade_candles), show_bos=True, show_choch=True, show_dual_choch=True)
        raw_lines = eng.run(trade_candles).get("lines", [])
        pre_lines = [l for l in raw_lines if l.get("x2", 0) <= tap_actual_time]
        has_bos = any(_line_dir(l) == expected_approach_dir and ("BOS" in l.get("type", "") or "CHoCH" in l.get("type", "")) for l in pre_lines)
        if has_bos:
            taps_with_approach_bos += 1

print(f"Total taps checked: {total_taps}, Taps with approach BOS: {taps_with_approach_bos}")
