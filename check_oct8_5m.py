import json
from datetime import datetime, timezone

with open('data/btc_5m_oct2026_full.json') as f:
    c_5m = json.load(f)

# Find 5M candles from Oct 8 12:00 to 16:00
for c in c_5m:
    dt = datetime.fromtimestamp(c['time'], timezone.utc)
    if dt.month == 10 and dt.day == 8 and 12 <= dt.hour <= 16:
        print(f"5M Candle {dt.strftime('%H:%M')}: O={c['open']}, H={c['high']}, L={c['low']}, C={c['close']}")
