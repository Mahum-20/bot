import json
import urllib.request
from datetime import datetime, timezone, timedelta
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box
from htf_engine import HTFEngine

pkt = timezone(timedelta(hours=5))

def get_klines_range(symbol, interval, start_dt, end_dt):
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    all_c = []
    cur_start = start_ts
    while cur_start < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={cur_start}&endTime={end_ts}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            raw = json.loads(resp.read().decode())
        if not raw:
            break
        for r in raw:
            all_c.append({
                "time": int(r[0]) // 1000,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5])
            })
        cur_start = int(raw[-1][0]) + 60000
    return all_c

# 1H candles up to Nov 4 20:00 PKT (15:00 UTC)
c_1h = get_klines_range("BTCUSDT", "1h", datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc))

# 1M candles around Nov 4 14:00 PKT to 18:00 PKT (09:00 to 13:00 UTC)
# Let's also check if user meant 15:00 UTC or 15:00 PKT, so fetch 08:00 UTC to 20:00 UTC
start_1m = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)
end_1m = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)
c_1m = get_klines_range("BTCUSDT", "1m", start_1m, end_1m)

print(f"Fetched {len(c_1h)} 1H candles and {len(c_1m)} 1M candles")

# Run HTF engine on 1H
htf_eng = HTFEngine(lookback_bars=len(c_1h), show_tjl_boxes=True, tjl_extend=True)
boxes = htf_eng.run(c_1h).get("boxes", [])

# Find the box tjl2_954
target_box = None
for b in boxes:
    if b.get("id") == "tjl2_954":
        target_box = b
        break

print("Target Box:", target_box)
