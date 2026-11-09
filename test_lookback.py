import json
from htf_engine import HTFEngine

with open("data/btcusdt_5m_1y_oct2025_oct2026.json") as f:
    c_5m = json.load(f)

# Test 40 bars vs 120 bars vs 200 bars lookback
for lookback in [40, 80, 120, 200]:
    bos_count = 0
    for i in range(500, 1500, 50):
        slice_c = c_5m[i - lookback : i]
        eng = HTFEngine(lookback_bars=len(slice_c), show_bos=True, show_choch=True)
        lines = eng.run(slice_c).get("lines", [])
        if any("BOS" in l.get("type", "") or "CHoCH" in l.get("type", "") for l in lines):
            bos_count += 1
    print(f"Lookback {lookback} bars: {bos_count} / 20 slices had BOS/CHoCH")
