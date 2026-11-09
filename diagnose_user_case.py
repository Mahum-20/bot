import json
import urllib.request
from datetime import datetime, timezone, timedelta
from htf_engine import HTFEngine
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box, is_valid_tap_approach, is_htf_box_active

pkt = timezone(timedelta(hours=5))

# 1. Fetch 1H candles from Oct 1 to Nov 4 16:30 PKT (11:30 UTC)
end_dt = datetime(2026, 11, 4, 11, 30, tzinfo=timezone.utc)
start_dt = end_dt - timedelta(days=35)

def fetch_klines(symbol, interval, s_dt, e_dt):
    s_ts = int(s_dt.timestamp() * 1000)
    e_ts = int(e_dt.timestamp() * 1000)
    all_c = []
    cur = s_ts
    while cur < e_ts:
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
        cur = int(raw[-1][0]) + (60000 if interval == "1m" else 3600000)
    return all_c

c_1h = fetch_klines("BTCUSDT", "1h", start_dt, end_dt)
# Fetch 1m candles for Nov 4 (from 00:00 UTC to 12:00 UTC = 05:00 to 17:00 PKT)
c_1m = fetch_klines("BTCUSDT", "1m", datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc), datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc))

print(f"Loaded {len(c_1h)} 1H candles, {len(c_1m)} 1M candles")

# Run HTF engine on 1H
htf_eng = HTFEngine(lookback_bars=len(c_1h), show_tjl_boxes=True, tjl_extend=True)
boxes = htf_eng.run(c_1h).get("boxes", [])

# Find the 78593 - 78853 box
the_box = None
for b in boxes:
    if abs(b.get("top", 0) - 78853.5) < 10:
        the_box = b
        break

print("\n--- The HTF Box ---")
print(the_box)

# Check target tap time at 15:00 PKT (10:00 UTC)
tap_time_utc = int(datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc).timestamp())
print(f"\nTap Time: {datetime.fromtimestamp(tap_time_utc, pkt)} (UTC: {datetime.fromtimestamp(tap_time_utc, timezone.utc)})")

# Check if active
is_act = is_htf_box_active(the_box, tap_time_utc)
print(f"is_htf_box_active at tap_time: {is_act}")

# Check tap approach
# Find index in c_1m
m1_times = [c["time"] for c in c_1m]
import bisect
pos = bisect.bisect_left(m1_times, tap_time_utc)
print(f"Candle at tap: {datetime.fromtimestamp(c_1m[pos]['time'], pkt)} | O:{c_1m[pos]['open']} H:{c_1m[pos]['high']} L:{c_1m[pos]['low']} C:{c_1m[pos]['close']}")
is_valid_tap = is_valid_tap_approach(the_box, c_1m, pos)
print(f"is_valid_tap_approach: {is_valid_tap}")

# Now run compute_ltf_approach_structure at 16:14 PKT (11:14 UTC)
signal_time_utc = int(datetime(2026, 11, 4, 11, 14, tzinfo=timezone.utc).timestamp())
print(f"\nEvaluating compute_ltf_approach_structure at signal time: {datetime.fromtimestamp(signal_time_utc, pkt)}")

res = compute_ltf_approach_structure(
    target_time=signal_time_utc,
    ltf_candles=c_1m,
    htf_boxes=[the_box],
    htf_sec=3600,
    htf_candles=c_1h
)

tap_info = res.get("tap_info")
print(f"tap_info: {tap_info is not None}")
if tap_info:
    print("  box_name:", tap_info.get("box_name"))
    print("  is_bullish:", tap_info.get("is_bullish"))
    print("  trade:", tap_info.get("trade"))
