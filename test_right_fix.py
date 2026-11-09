import json
import urllib.request
from htf_engine import HTFEngine, is_qualifying_htf_zone, is_htf_box_active
from ltf_approach_engine import is_valid_tap_approach

def fetch_binance_candles(symbol, interval, limit=500):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = json.loads(urllib.request.urlopen(req).read().decode())
    return [{
        "time": int(k[0] // 1000),
        "open": float(k[1]),
        "high": float(k[2]),
        "low": float(k[3]),
        "close": float(k[4]),
        "volume": float(k[5])
    } for k in raw]

symbol = "SOLUSDT"
htf_candles = fetch_binance_candles(symbol, "4h", 200)
ltf_candles = fetch_binance_candles(symbol, "5m", 200)

engine = HTFEngine(lookback_bars=len(htf_candles), show_tjl_boxes=True, tjl_extend=True)
res = engine.run(htf_candles)
boxes = [b for b in res.get("boxes", []) if is_qualifying_htf_zone(b)]

cur_time = ltf_candles[-1]["time"]

print("--- Testing SOL 4h Boxes ---")
for b in boxes:
    b_left = b.get("left") or 0
    b_right_old = b.get("right") or 9999999999
    b_right_new = b.get("mitigated_time") if (b.get("is_mitigated") or b.get("is_broken")) else 9999999999
    
    top = max(b.get("top", 0), b.get("bottom", 0))
    bot = min(b.get("top", 0), b.get("bottom", 0))
    
    # Check if current candle or recent candle touches
    touches = any(c["high"] >= bot and c["low"] <= top for c in ltf_candles[-5:])
    if touches:
        print(f"Box {b.get('text')} [{bot}-{top}]: touches recent candles!")
        print(f"  Old right check: {b_left} <= {cur_time} <= {b_right_old} -> {b_left <= cur_time <= b_right_old}")
        print(f"  New right check: {b_left} <= {cur_time} <= {b_right_new} -> {b_left <= cur_time <= b_right_new}")
        print(f"  is_valid_tap_approach: {is_valid_tap_approach(b, ltf_candles, len(ltf_candles)-1)}")
