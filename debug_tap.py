import bisect
from faithful_backtest_engine import FaithfulBacktestEngine, is_qualifying_htf_zone, is_htf_box_active
from htf_engine import HTFEngine
from ltf_approach_engine import compute_ltf_approach_structure

engine = FaithfulBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m")

start_idx = bisect.bisect_left(engine.ltf_times, engine.c_htf[200]["time"])

for i in range(start_idx, start_idx + 200):
    c_curr = engine.c_ltf[i]
    c_time = c_curr["time"]
    h_idx = bisect.bisect_right(engine.htf_times, c_time - engine.htf_sec)
    htf_subset = engine.c_htf[:h_idx]
    htf_engine = HTFEngine(lookback_bars=len(htf_subset), show_tjl_boxes=True, tjl_extend=True)
    raw_boxes = htf_engine.run(htf_subset).get("boxes", [])
    cached_htf_boxes = [b for b in raw_boxes if is_qualifying_htf_zone(b)]
    for b in cached_htf_boxes:
        b["confirmed_formation_time"] = b.get("left", 0)

    # find a tapped box
    for b in cached_htf_boxes:
        b_top = max(b.get("top", 0), b.get("bottom", 0))
        b_bot = min(b.get("top", 0), b.get("bottom", 0))
        if b_bot <= c_curr["high"] and c_curr["low"] <= b_top:
            print(f"Candle {i} tapped box: {b.get('text')} top={b_top} bot={b_bot} candle={c_curr['low']}-{c_curr['high']}")
            ltf_history_slice = engine.c_ltf[max(0, i - 500):i + 1]
            htf_history_slice = engine.c_htf[:h_idx]
            res = compute_ltf_approach_structure(
                target_time=c_time,
                ltf_candles=ltf_history_slice,
                htf_boxes=[b],
                htf_sec=engine.htf_sec,
                htf_candles=htf_history_slice
            )
            print("compute_ltf_approach_structure keys:", res.keys())
            print("tap_info:", res.get("tap_info"))
            exit(0)
