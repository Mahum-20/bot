import json
import urllib.request
from datetime import datetime, timezone, timedelta
from htf_engine import HTFEngine

def get_klines(symbol, interval, limit=1000, end_ts=None):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    if end_ts:
        url += f"&endTime={end_ts}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read().decode())
    return [{"time": int(r[0]) // 1000, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])} for r in raw]

# Let's inspect all boxes from late Oct to Nov 5, 2026
c_1h = get_klines("BTCUSDT", "1h", 1000, int(datetime(2026, 11, 5, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000))
htf_eng = HTFEngine(lookback_bars=len(c_1h), show_tjl_boxes=True, tjl_extend=True)
res_htf = htf_eng.run(c_1h)
boxes = res_htf.get("boxes", [])

pkt = timezone(timedelta(hours=5))

print("=== All Boxes in Range (UTC+5 Times) ===")
for b in boxes:
    t_utc = datetime.fromtimestamp(b.get("left", 0), timezone.utc)
    t_pkt = t_utc.astimezone(pkt)
    if t_pkt.month == 11 or (t_pkt.month == 10 and t_pkt.day >= 25):
        print(f"ID: {b.get('id')} | Text: {b.get('text')} | PKT: {t_pkt} | UTC: {t_utc} | Top: {b.get('top')} | Bot: {b.get('bottom')} | Bull: {b.get('is_bullish')}")
