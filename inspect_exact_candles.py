import urllib.request
import json
from datetime import datetime, timezone, timedelta

pkt = timezone(timedelta(hours=5))

# Let's inspect 1M candles around 15:00 to 16:30 on Nov 4 (both UTC and PKT)
# If 15:00 is PKT -> 10:00 UTC
# If 15:00 is UTC -> 15:00 UTC
def fetch_1m(start_dt, count=120):
    start_ts = int(start_dt.timestamp() * 1000)
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&startTime={start_ts}&limit={count}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read().decode())
    return [{"time": int(r[0]) // 1000, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in raw]

# Let's check both possibilities:
# Case 1: 15:00 UTC
c_utc = fetch_1m(datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc), 90)
# Case 2: 15:00 PKT (10:00 UTC)
c_pkt = fetch_1m(datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc), 90)

print("=== Checking Case 1: 15:00 UTC ===")
for c in c_utc:
    t_dt = datetime.fromtimestamp(c["time"], timezone.utc)
    if t_dt.minute in (30, 31, 34, 40, 41, 42, 14): # user mentioned 15:30, 15:31, 15:34, 15:40, 16:14
        print(f"UTC {t_dt.strftime('%H:%M')} | O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']}")

print("\n=== Checking Case 2: 15:00 PKT (10:00 UTC) ===")
for c in c_pkt:
    t_pkt = datetime.fromtimestamp(c["time"], timezone.utc).astimezone(pkt)
    if t_pkt.minute in (30, 31, 34, 40, 41, 42, 14):
        print(f"PKT {t_pkt.strftime('%H:%M')} | O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']}")
