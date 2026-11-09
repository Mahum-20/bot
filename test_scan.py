import json
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box
from htf_engine import HTFEngine

c_4h = json.load(open('data/btcusdt_4h_1y_oct2025_oct2026.json'))
c_5m = json.load(open('data/btcusdt_5m_1y_oct2025_oct2026.json'))
boxes = HTFEngine(lookback_bars=len(c_4h), show_tjl_boxes=True, tjl_extend=True).run(c_4h)['boxes']

# Let's find trades using run_strict_oct_backtest logic first to see what trades it finds
print("Scanning with full candles (original approach)...")
found = []
for i in range(1000, 3000):
    c = c_5m[i]
    c_time = c["time"]
    for b in boxes:
        b_top = max(b.get("top", 0), b.get("bottom", 0))
        b_bot = min(b.get("top", 0), b.get("bottom", 0))
        if c["high"] >= b_bot and c["low"] <= b_top:
            res = compute_ltf_approach_structure(c_time, c_5m, boxes, 14400, c_4h)
            tap_info = res.get("tap_info")
            if tap_info and tap_info.get("trade"):
                tr = tap_info["trade"]
                if tr.get("executed"):
                    found.append((i, c_time, tr))
                    print(f"Tap at bar {i} ({c_time}) -> Trade at {tr['time']}, action={tr['action']}, entry={tr['entry_price']}, sl={tr['sl_price']}, tp={tr['tp_price']}")
            break
    if len(found) >= 3:
        break
