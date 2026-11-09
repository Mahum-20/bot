import json
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box
from htf_engine import HTFEngine

with open("data/btcusdt_4h_1y_oct2025_oct2026.json") as f:
    c_4h = json.load(f)
with open("data/btcusdt_5m_1y_oct2025_oct2026.json") as f:
    c_5m = json.load(f)

# Run HTF engine on full 4H
htf_engine = HTFEngine(lookback_bars=len(c_4h), show_tjl_boxes=True, tjl_extend=True)
boxes = htf_engine.run(c_4h).get("boxes", [])

print(f"Total boxes: {len(boxes)}")

found_taps = 0
found_trades = 0

for i in range(1000, len(c_5m), 10):
    c = c_5m[i]
    box, tap_idx = find_tapped_htf_box(c["time"], c_5m, boxes, 14400)
    if box:
        found_taps += 1
        res = compute_ltf_approach_structure(c["time"], c_5m, boxes, 14400, c_4h)
        tap_info = res.get("tap_info")
        if tap_info and tap_info.get("trade"):
            found_trades += 1
            print(f"Candle {i}: Found trade! {tap_info['trade']}")
            if found_trades >= 5:
                break

print(f"Found taps: {found_taps}, Found trades: {found_trades}")
