import json
from ltf_approach_engine import find_tapped_htf_box
from htf_engine import HTFEngine

with open("data/btcusdt_4h_1y_oct2025_oct2026.json") as f:
    c_4h = json.load(f)
with open("data/btcusdt_5m_1y_oct2025_oct2026.json") as f:
    c_5m = json.load(f)

htf_engine = HTFEngine(lookback_bars=len(c_4h), show_tjl_boxes=True, tjl_extend=True)
boxes = htf_engine.run(c_4h).get("boxes", [])

for i in range(1000, len(c_5m), 20):
    c = c_5m[i]
    box, tap_idx = find_tapped_htf_box(c["time"], c_5m, boxes, 14400)
    if box:
        print(f"Candle {i}: tap_idx={tap_idx}")
        start_idx = max(0, tap_idx - 40)
        end_idx = min(len(c_5m), tap_idx + 240)
        trade_candles = c_5m[start_idx:end_idx]
        tap_actual_time = c_5m[tap_idx]["time"]
        
        eng = HTFEngine(lookback_bars=len(trade_candles), show_bos=True, show_choch=True, show_dual_choch=True)
        res = eng.run(trade_candles)
        raw_lines = res.get("lines", [])
        print(f"tap_actual_time = {tap_actual_time}")
        for idx, l in enumerate(raw_lines):
            print(f"Line {idx}: type={l.get('type')} dir={l.get('direction')} x1={l.get('x1')} x2={l.get('x2')}")
        break
