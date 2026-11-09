import json, datetime

files = [
    'data/btcusdt_4h_1y_oct2025_oct2026.json',
    'data/btcusdt_1h_1y_oct2025_oct2026.json',
    'data/btcusdt_15m_1y_oct2025_oct2026.json',
    'data/btcusdt_5m_1y_oct2025_oct2026.json',
    'data/btcusdt_1m_1y_oct2025_oct2026.json'
]

for fpath in files:
    with open(fpath, 'r') as f:
        candles = json.load(f)
    t_start = candles[0]['time']
    t_end = candles[-1]['time']
    dt_start = datetime.datetime.fromtimestamp(t_start, datetime.timezone.utc)
    dt_end = datetime.datetime.fromtimestamp(t_end, datetime.timezone.utc)
    print(f"{fpath}: {len(candles)} candles | {dt_start.strftime('%Y-%m-%d %H:%M')} to {dt_end.strftime('%Y-%m-%d %H:%M')}")
