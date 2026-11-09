import json
import urllib.request
from datetime import datetime, timezone

def fetch_binance_klines(symbol="BTCUSDT", interval="1h", start_str="2026-11-01 00:00:00", end_str="2026-11-05 00:00:00"):
    start_ts = int(datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
    
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={start_ts}&endTime={end_ts}&limit=1000"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as response:
            raw = json.loads(response.read().decode())
            candles = []
            for r in raw:
                candles.append({
                    "time": int(r[0]) // 1000,
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5])
                })
            return candles
    except Exception as e:
        print(f"Error fetching from Binance: {e}")
        return []

c_1h = fetch_binance_klines("BTCUSDT", "1h", "2026-11-01 00:00:00", "2026-11-05 23:59:59")
print(f"Fetched {len(c_1h)} 1H candles")
if c_1h:
    print(f"First 1H: {datetime.fromtimestamp(c_1h[0]['time'], timezone.utc)} | Last: {datetime.fromtimestamp(c_1h[-1]['time'], timezone.utc)}")
