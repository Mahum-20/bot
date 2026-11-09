from faithful_backtest_engine import FaithfulBacktestEngine, is_qualifying_htf_zone
from htf_engine import HTFEngine

engine = FaithfulBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m")
htf_engine = HTFEngine(lookback_bars=len(engine.c_htf), show_tjl_boxes=True, tjl_extend=True)
res = htf_engine.run(engine.c_htf)
boxes = res.get("boxes", [])
qualifying = [b for b in boxes if is_qualifying_htf_zone(b)]
print("First box keys and values:")
for k, v in qualifying[0].items():
    print(f"  {k}: {v}")
