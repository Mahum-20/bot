import json
from datetime import datetime, timezone
from htf_engine import HTFEngine

with open('data/btc_1m_oct2026.json') as f:
    candles_1m = json.load(f)

test_targets = [
    (15676, "11-10 21:16 (Demand Tap)"),
    (9468, "07-10 13:48 (Demand Tap)"),
    (1710, "02-10 04:30 (Supply Tap)"),
    (8762, "07-10 02:02 (Supply Tap)")
]

for tap_idx, label in test_targets:
    tap_actual_time = candles_1m[tap_idx]["time"]
    for pre_bars in [35, 45]:
        start_idx = max(0, tap_idx - pre_bars)
        end_idx = min(len(candles_1m), tap_idx + 240)
        trade_candles = candles_1m[start_idx:end_idx]

        engine = HTFEngine(lookback_bars=len(trade_candles), show_bos=True, show_choch=True, show_dual_choch=True, show_triple_choch=True, show_tjl_boxes=True, tjl_extend=True)
        out = engine.run(trade_candles)
        lines = out.get("lines", [])

        pre_lines = [l for l in lines if l['x2'] <= tap_actual_time]
        print(f"\n{label} with pre_bars={pre_bars}:")
        for l in pre_lines:
            t1 = datetime.fromtimestamp(l['x1'], timezone.utc).strftime('%H:%M')
            t2 = datetime.fromtimestamp(l['x2'], timezone.utc).strftime('%H:%M')
            print(f"  {l['type']} ({l['direction']}) from {t1} to {t2}")
