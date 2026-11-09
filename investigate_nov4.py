import json
import urllib.request
from datetime import datetime, timezone
from htf_engine import HTFEngine
from ltf_approach_engine import compute_ltf_approach_structure, is_htf_box_active, is_qualifying_htf_zone

def get_klines(symbol, interval, limit=1000, end_ts=None):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    if end_ts:
        url += f"&endTime={end_ts}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read().decode())
    return [{"time": int(r[0]) // 1000, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])} for r in raw]

# Nov 4, 2026 23:59:59 UTC
end_nov4_utc = int(datetime(2026, 11, 4, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

# Fetch 1H candles
c_1h = get_klines("BTCUSDT", "1h", 1000, end_nov4_utc)
print(f"Fetched {len(c_1h)} 1H candles up to {datetime.fromtimestamp(c_1h[-1]['time'], timezone.utc)}")

# Run HTF engine on 1H
htf_eng = HTFEngine(lookback_bars=len(c_1h), show_tjl_boxes=True, tjl_extend=True)
res_htf = htf_eng.run(c_1h)
boxes = res_htf.get("boxes", [])

print(f"\n--- HTF BOXES FORMED IN EARLY NOV 2026 ---")
for b in boxes:
    b_time = b.get("left", 0)
    dt_utc = datetime.fromtimestamp(b_time, timezone.utc)
    if dt_utc.year == 2026 and dt_utc.month == 11 and dt_utc.day in (1, 2, 3, 4):
        print(f"Box: {b.get('text')} | Time: {dt_utc} | Top: {b.get('top')} | Bot: {b.get('bottom')} | Bullish: {b.get('is_bullish')}")
