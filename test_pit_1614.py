import json
from datetime import datetime, timezone, timedelta
from test_pit_h1 import c_1h_pit, the_box, pkt
from test_specific_setup import c_1m
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box, is_htf_box_active, is_valid_tap_approach
from faithful_backtest_engine import FaithfulBacktestEngine

# Candle 16:14 PKT
signal_ts = int(datetime(2026, 11, 4, 11, 14, tzinfo=timezone.utc).timestamp())
print(f"Testing Point-in-Time Trade Evaluation at 16:14 PKT ({signal_ts}):")

# 1. Is the box active at 16:14 PKT?
is_act = is_htf_box_active(the_box, signal_ts)
print(f"1. is_htf_box_active: {is_act}")

# 2. Did price tap in recent 20 bars (server.py check)?
# Let's find index of 16:14 PKT in c_1m
times_1m = [c["time"] for c in c_1m]
import bisect
idx_1614 = bisect.bisect_left(times_1m, signal_ts)
recent_20 = c_1m[idx_1614 - 19 : idx_1614 + 1]
b_top = max(the_box["top"], the_box["bottom"])
b_bot = min(the_box["top"], the_box["bottom"])
tapped_recent = any(c["high"] >= b_bot and c["low"] <= b_top for c in recent_20)
print(f"2. Tapped in last 20 bars (server.py check): {tapped_recent}")

# 3. What does find_tapped_htf_box return?
matched_b, tap_idx = find_tapped_htf_box(signal_ts, c_1m, [the_box], 3600)
print(f"3. find_tapped_htf_box: matched_b={matched_b is not None}, tap_idx={tap_idx}")
if tap_idx is not None:
    print(f"   tap candle time: {datetime.fromtimestamp(c_1m[tap_idx]['time'], pkt)}")

# 4. What does compute_ltf_approach_structure return?
res = compute_ltf_approach_structure(
    target_time=signal_ts,
    ltf_candles=c_1m[:idx_1614 + 1],  # point-in-time: only candles up to 16:14!
    htf_boxes=[the_box],
    htf_sec=3600,
    htf_candles=c_1h_pit
)

tap_info = res.get("tap_info")
print(f"4. compute_ltf_approach_structure tap_info: {tap_info is not None}")
if tap_info:
    print(f"   winner_pathway: {tap_info.get('winner_pathway')}")
    print(f"   has_approach_bos: {tap_info.get('has_approach_bos')}")
    print(f"   trade: {tap_info.get('trade')}")
else:
    print("   tap_info is NONE! Let's see why!")
