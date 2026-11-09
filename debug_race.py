from test_as_supply import test_box, c_1m, c_1h, signal_ts, pkt
from ltf_approach_engine import find_tapped_htf_box, detect_internal_5_waves
from htf_engine import HTFEngine
from datetime import datetime

matched_box, tap_idx = find_tapped_htf_box(signal_ts, c_1m, [test_box], 3600)
print(f"matched_box text: {matched_box.get('text')}, tap_idx: {tap_idx}")
tap_actual_time = c_1m[tap_idx]["time"]
print(f"tap_actual_time: {datetime.fromtimestamp(tap_actual_time, pkt)}")

lookback_pre = 80
start_idx = max(0, tap_idx - lookback_pre)
end_idx = min(len(c_1m), tap_idx + 240)
trade_candles = c_1m[start_idx:end_idx]
tap_in_slice = tap_idx - start_idx

# Check 5 waves
res_5w = detect_internal_5_waves(trade_candles, tap_in_slice, False, htf_box=matched_box)
print("5-wave completed:", res_5w.get("completed"))

# Check CHoCH in HTFEngine
eng = HTFEngine(lookback_bars=len(trade_candles), show_bos=True, show_choch=True, show_dual_choch=True)
structure_out = eng.run(trade_candles)
raw_lines = structure_out.get("lines", [])

def _line_dir(line):
    if line.get("direction"): return line["direction"]
    c = line.get("color", "")
    if c in ("#26a69a", "#10b981", "#00E676"): return "bullish"
    if c in ("#ef5350", "#ef4444", "#FF5252"): return "bearish"
    lid = line.get("id", "")
    if "bull" in lid: return "bullish"
    if "bear" in lid: return "bearish"
    return "bullish"

pre_lines = [l for l in raw_lines if l.get("x2", 0) <= tap_actual_time]
print(f"Pre-lines count: {len(pre_lines)}")
has_approach_bos = any(_line_dir(l) == "bullish" and ("BOS" in l.get("type", "") or "CHoCH" in l.get("type", "")) for l in pre_lines)
print(f"has_approach_bos (Bullish into Supply): {has_approach_bos}")

# Post tap CHoCH
print(f"\nLines found in trade_candles slice ({len(raw_lines)} total):")
for idx, l in enumerate(raw_lines):
    t1 = datetime.fromtimestamp(l.get('x1', 0), pkt).strftime('%H:%M')
    t2 = datetime.fromtimestamp(l.get('x2', 0), pkt).strftime('%H:%M')
    print(f"  Line {idx}: type={l.get('type')} dir={_line_dir(l)} x1={t1} x2={t2} y1={l.get('y1')}")
