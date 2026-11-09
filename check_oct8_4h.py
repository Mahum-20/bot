import json
from datetime import datetime, timezone
from htf_engine import HTFEngine

with open('data/btc_4h_oct2026_full.json') as f:
    c_4h = json.load(f)

# Find 4H candle for Oct 08 12:00
for c in c_4h:
    dt = datetime.fromtimestamp(c['time'], timezone.utc)
    if dt.month == 10 and dt.day == 8:
        print(f"4H Candle {dt.strftime('%Y-%m-%d %H:%M')}: Open={c['open']}, High={c['high']}, Low={c['low']}, Close={c['close']}")

engine = HTFEngine(lookback_bars=min(500, len(c_4h)), show_tjl_boxes=True, tjl_extend=True)
out = engine.run(c_4h)
boxes = out.get('boxes', [])

print("\n--- 4H Boxes around 81k - 83k ---")
for b in boxes:
    top = max(b['top'], b['bottom'])
    bot = min(b['top'], b['bottom'])
    if 80000 <= top <= 85000:
        print(f"Box: {b.get('text')} | Top: {top} | Bottom: {bot} | is_bullish: {b.get('is_bullish')}")
