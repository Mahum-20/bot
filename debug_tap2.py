import bisect
from faithful_backtest_engine import FaithfulBacktestEngine, is_qualifying_htf_zone
from htf_engine import HTFEngine

engine = FaithfulBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m")
start_idx = bisect.bisect_left(engine.ltf_times, engine.c_htf[200]["time"])
c_curr = engine.c_ltf[start_idx]
c_time = c_curr["time"]
h_idx = bisect.bisect_right(engine.htf_times, c_time - engine.htf_sec)
htf_subset = engine.c_htf[:h_idx]
htf_engine = HTFEngine(lookback_bars=len(htf_subset), show_tjl_boxes=True, tjl_extend=True)
raw_boxes = htf_engine.run(htf_subset).get("boxes", [])
qualifying = [b for b in raw_boxes if is_qualifying_htf_zone(b)]
print(f"h_idx: {h_idx}, raw_boxes: {len(raw_boxes)}, qualifying: {len(qualifying)}")
for b in qualifying:
    print(f"box text={b.get('text')} top={b.get('top')} bot={b.get('bottom')}")
print("LTF candles price range over next 500 bars:")
highs = [c['high'] for c in engine.c_ltf[start_idx:start_idx+500]]
lows = [c['low'] for c in engine.c_ltf[start_idx:start_idx+500]]
print(f"min low={min(lows)}, max high={max(highs)}")
