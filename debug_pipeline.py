import bisect
from faithful_backtest_engine import FaithfulBacktestEngine, is_qualifying_htf_zone, is_htf_box_active
from htf_engine import HTFEngine
from ltf_approach_engine import compute_ltf_approach_structure

engine = FaithfulBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m")
print(f"Total 4H candles: {len(engine.c_htf)}, Total 5M candles: {len(engine.c_ltf)}")

# Let's inspect active boxes and taps over the first 5000 5m candles
last_computed_htf_time = None
cached_htf_boxes = []

counts = {
    "htf_eval": 0,
    "active_boxes": 0,
    "available_boxes": 0,
    "tapped_boxes": 0,
    "has_tap_info": 0,
    "trade_executed": 0
}

start_idx = bisect.bisect_left(engine.ltf_times, engine.c_htf[200]["time"])
end_idx = start_idx + 10000

for i in range(start_idx, min(end_idx, len(engine.c_ltf))):
    c_curr = engine.c_ltf[i]
    c_time = c_curr["time"]

    h_idx = bisect.bisect_right(engine.htf_times, c_time - engine.htf_sec)
    if h_idx < 25:
        continue

    latest_closed_htf = engine.c_htf[h_idx - 1]
    htf_close_time = latest_closed_htf["time"]

    if last_computed_htf_time != htf_close_time:
        last_computed_htf_time = htf_close_time
        htf_subset = engine.c_htf[:h_idx]
        htf_engine = HTFEngine(lookback_bars=len(htf_subset), show_tjl_boxes=True, tjl_extend=True)
        raw_boxes = htf_engine.run(htf_subset).get("boxes", [])
        cached_htf_boxes = [b for b in raw_boxes if is_qualifying_htf_zone(b)]
        for b in cached_htf_boxes:
            b_left = b.get("confirmed_formation_time") or b.get("left") or b.get("start_time") or b.get("time") or 0
            b["confirmed_formation_time"] = b_left
        counts["htf_eval"] += 1

    active_htf_boxes = [
        b for b in cached_htf_boxes
        if is_htf_box_active(b, c_time) and c_time >= b.get("confirmed_formation_time", 0)
    ]
    if not active_htf_boxes:
        continue
    counts["active_boxes"] += 1

    # check tap
    recent_ltf_slice = engine.c_ltf[max(0, i - 19):i + 1]
    tapped = []
    for b in active_htf_boxes:
        b_top = max(b.get("top", 0), b.get("bottom", 0))
        b_bot = min(b.get("top", 0), b.get("bottom", 0))
        if any(bar["high"] >= b_bot and bar["low"] <= b_top for bar in recent_ltf_slice):
            tapped.append(b)

    if not tapped:
        continue
    counts["tapped_boxes"] += 1

    ltf_history_slice = engine.c_ltf[max(0, i - 500):i + 1]
    htf_history_slice = engine.c_htf[:h_idx]
    res = compute_ltf_approach_structure(
        target_time=c_time,
        ltf_candles=ltf_history_slice,
        htf_boxes=tapped,
        htf_sec=engine.htf_sec,
        htf_candles=htf_history_slice
    )
    tap_info = res.get("tap_info")
    if tap_info:
        counts["has_tap_info"] += 1
        tr = tap_info.get("trade")
        if tr:
            print(f"Bar {i} (time={c_time}): tap_info status={tr.get('status')}, executed={tr.get('executed')}, reason={tr.get('reason')}")
            if tr.get("executed"):
                counts["trade_executed"] += 1

print("Counts:", counts)
