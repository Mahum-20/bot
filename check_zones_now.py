import json
import urllib.request
from htf_engine import HTFEngine, is_qualifying_htf_zone, is_htf_box_active

def fetch_binance_candles(symbol, interval, limit=500):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = json.loads(urllib.request.urlopen(req).read().decode())
    candles = []
    for k in raw:
        candles.append({
            "time": int(k[0] // 1000),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5])
        })
    return candles

for sym in ["BTCUSDT", "SOLUSDT", "PAXGUSDT"]:
    print(f"\n====================== {sym} ======================")
    for tf in ["4h", "1h", "15m"]:
        htf_candles = fetch_binance_candles(sym, tf, 500)
        if not htf_candles:
            continue
        cur_p = htf_candles[-1]["close"]
        cur_time = htf_candles[-1]["time"]
        
        engine = HTFEngine(lookback_bars=len(htf_candles), show_tjl_boxes=True, tjl_extend=True)
        res = engine.run(htf_candles)
        boxes = res.get("boxes", [])
        
        # Qualify and check active
        valid_boxes = [b for b in boxes if is_qualifying_htf_zone(b)]
        for b in valid_boxes:
            b_left = b.get("confirmed_formation_time") or b.get("left") or b.get("start_time") or b.get("time") or 0
            b["confirmed_formation_time"] = b_left
            if "mitigated_time" not in b:
                b["mitigated_time"] = b.get("right")
                
        active_boxes = [
            b for b in valid_boxes 
            if is_htf_box_active(b, cur_time) and cur_time >= b.get("confirmed_formation_time", 0)
        ]
        
        print(f"\n--- {tf} (Current Price: {cur_p}) ---")
        print(f"Total Boxes: {len(boxes)}, Active Unmitigated (non-A+): {len(active_boxes)}")
        
        # Check nearest
        with_dist = []
        for b in active_boxes:
            top = max(b.get("top", 0), b.get("bottom", 0))
            bot = min(b.get("top", 0), b.get("bottom", 0))
            mid = (top + bot) / 2.0
            dist = abs(mid - cur_p)
            with_dist.append((dist, b, top, bot))
        with_dist.sort(key=lambda x: x[0])
        
        for dist, b, top, bot in with_dist[:3]:
            pos = "INSIDE" if bot <= cur_p <= top else ("ABOVE (Supply)" if bot > cur_p else "BELOW (Demand)")
            pct = (dist / cur_p) * 100.0
            print(f"  • {b.get('text')} [{bot:.2f} - {top:.2f}] | {pos} | Dist: {dist:.2f} ({pct:.2f}%)")
            
        # Check if latest candle or previous 10 candles tapped any box
        tapped = []
        for dist, b, top, bot in with_dist:
            if any(c["high"] >= bot and c["low"] <= top for c in htf_candles[-5:]):
                tapped.append(b.get('text'))
        if tapped:
            print(f"  --> RECENTLY TAPPED ZONES: {tapped}")
        else:
            print(f"  --> No active zone tapped in the last 5 candles.")
