import json
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box
from htf_engine import HTFEngine

with open("data/btcusdt_4h_1y_oct2025_oct2026.json") as f:
    c_4h = json.load(f)
with open("data/btcusdt_5m_1y_oct2025_oct2026.json") as f:
    c_5m = json.load(f)

htf_engine = HTFEngine(lookback_bars=len(c_4h), show_tjl_boxes=True, tjl_extend=True)
boxes = htf_engine.run(c_4h).get("boxes", [])

taps_inspected = 0
for i in range(1000, len(c_5m), 20):
    c = c_5m[i]
    box, tap_idx = find_tapped_htf_box(c["time"], c_5m, boxes, 14400)
    if box:
        taps_inspected += 1
        res = compute_ltf_approach_structure(c["time"], c_5m, boxes, 14400, c_4h)
        tap_info = res.get("tap_info")
        print(f"--- Tap {taps_inspected} at candle {i} (time={c['time']}) ---")
        if tap_info:
            print("  box_name:", tap_info.get("box_name"))
            print("  is_bullish:", tap_info.get("is_bullish"))
            print("  has_approach_bos:", tap_info.get("has_approach_bos"))
            print("  approach_bos_dir:", tap_info.get("approach_bos_dir"))
            print("  trade:", tap_info.get("trade"))
        else:
            print("  tap_info is None")
        if taps_inspected >= 5:
            break
