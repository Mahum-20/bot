import json
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box
from htf_engine import HTFEngine

c_4h = json.load(open('data/btcusdt_4h_1y_oct2025_oct2026.json'))
c_5m = json.load(open('data/btcusdt_5m_1y_oct2025_oct2026.json'))
boxes = HTFEngine(lookback_bars=len(c_4h), show_tjl_boxes=True, tjl_extend=True).run(c_4h)['boxes']

matched_box, tap_idx = find_tapped_htf_box(c_5m[1643]['time'], c_5m, boxes, 14400)
print(f"matched_box: {matched_box.get('text') if matched_box else None}, tap_idx: {tap_idx}")

start_idx = max(0, tap_idx - 40)
end_idx = min(len(c_5m), tap_idx + 240)
trade_candles = c_5m[start_idx:end_idx]
tap_actual_time = c_5m[tap_idx]["time"]
is_bullish = matched_box.get("is_bullish", True)

eng = HTFEngine(lookback_bars=len(trade_candles), show_bos=True, show_choch=True, show_dual_choch=True)
raw_lines = eng.run(trade_candles).get("lines", [])

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

expected_approach_dir = "bearish" if is_bullish else "bullish"
pre_lines = [l for l in raw_lines if l.get("x2", 0) <= tap_actual_time]
has_approach_bos = any(_line_dir(l) == expected_approach_dir and ("BOS" in l.get("type", "") or "CHoCH" in l.get("type", "")) for l in pre_lines)
print(f"is_bullish: {is_bullish}, expected_approach_dir: {expected_approach_dir}")
print(f"pre_lines count: {len(pre_lines)}, has_approach_bos: {has_approach_bos}")
for l in raw_lines:
    print(f"  Line: type={l.get('type')} dir={_line_dir(l)} x1={l.get('x1')} x2={l.get('x2')} (tap={tap_actual_time})")
