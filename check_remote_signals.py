import requests
import json
import datetime

url = "http://127.0.0.1:8000/api/chart_signals?symbol=BTCUSDT&timeframe=15m"
try:
    res = requests.get(url, timeout=30)
    data = res.json()
    markers = data.get("markers", [])
    signals = data.get("signals", [])
    print(f"Total markers: {len(markers)}, Total signals: {len(signals)}")
    
    # Print recent markers (last 20)
    print("\n--- Recent Markers ---")
    for m in markers[-20:]:
        t = m.get("time", 0)
        dt_utc = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        dt_pkt = dt_utc + datetime.timedelta(hours=5)
        print(f"UTC: {dt_utc.strftime('%Y-%m-%d %H:%M:%S')} | PKT: {dt_pkt.strftime('%Y-%m-%d %H:%M:%S')} | Shape: {m.get('shape')} | Text: {m.get('text')} | Pos: {m.get('position')}")
        
    print("\n--- Recent Signals ---")
    for s in signals[-10:]:
        t = s.get("time", 0)
        dt_utc = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        dt_pkt = dt_utc + datetime.timedelta(hours=5)
        print(f"UTC: {dt_utc.strftime('%Y-%m-%d %H:%M:%S')} | PKT: {dt_pkt.strftime('%Y-%m-%d %H:%M:%S')} | Type: {s.get('type')} | Price: {s.get('price')} | SL: {s.get('sl')} | TP: {s.get('tp')}")

except Exception as e:
    print(f"Error: {e}")
