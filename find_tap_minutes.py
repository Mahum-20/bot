from test_specific_setup import c_1m, pkt
from datetime import datetime

print("Candles between 15:00 and 16:20 PKT:")
for c in c_1m:
    t_pkt = datetime.fromtimestamp(c["time"], pkt)
    # Check if inside or near box (78593.3 to 78853.5)
    if c["high"] >= 78593.3 and c["low"] <= 78853.5:
        print(f"Inside box: {t_pkt.strftime('%H:%M')} | O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']}")
