import json
import urllib.request
from datetime import datetime, timezone, timedelta
from htf_engine import HTFEngine

pkt = timezone(timedelta(hours=5))

# 1. Fetch 1H candles strictly up to Nov 4 16:00 PKT (11:00 UTC)
# This is the exact point-in-time candle available when the 16:14 trade occurred!
end_dt = datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc)
start_dt = end_dt - timedelta(days=35)

def fetch_klines(symbol, interval, s_dt, e_dt):
    s_ts = int(s_dt.timestamp() * 1000)
    e_ts = int(e_dt.timestamp() * 1000)
    all_c = []
    cur = s_ts
    while cur <= e_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={cur}&endTime={e_ts}&limit=1000"
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
        cur = int(raw[-1][0]) + 3600000
    return all_c

c_1h_pit = fetch_klines("BTCUSDT", "1h", start_dt, end_dt)
print(f"Loaded {len(c_1h_pit)} 1H candles strictly up to {datetime.fromtimestamp(c_1h_pit[-1]['time'], pkt)}")

htf_eng = HTFEngine(lookback_bars=len(c_1h_pit), show_tjl_boxes=True, tjl_extend=True)
res_htf = htf_eng.run(c_1h_pit)
boxes_pit = res_htf.get("boxes", [])

the_box = None
for b in boxes_pit:
    if abs(b.get("top", 0) - 78853.5) < 10:
        the_box = b
        break

print("\n--- Point-in-time Box at 16:00 PKT ---")
print(f"Text: {the_box.get('text')}")
print(f"Is Bullish: {the_box.get('is_bullish')}")
print(f"Level Type: {the_box.get('level_type')}")
print(f"Top: {the_box.get('top')}, Bottom: {the_box.get('bottom')}")
print(f"Left: {datetime.fromtimestamp(the_box.get('left'), pkt)}")
print(f"Right: {datetime.fromtimestamp(the_box.get('right'), pkt)}")
print(f"Is Mitigated: {the_box.get('is_mitigated')}")
