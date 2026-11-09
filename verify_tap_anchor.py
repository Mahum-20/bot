import json
from datetime import datetime, timezone, timedelta
from test_pit_h1 import c_1h_pit, the_box, pkt
from test_specific_setup import c_1m
from ltf_approach_engine import compute_ltf_approach_structure

# Initial tap was at 15:25 PKT
tap_ts = int(datetime(2026, 11, 4, 10, 25, tzinfo=timezone.utc).timestamp())
times_1m = [c["time"] for c in c_1m]
import bisect
idx_1614 = bisect.bisect_left(times_1m, int(datetime(2026, 11, 4, 11, 14, tzinfo=timezone.utc).timestamp()))

# When target_time is the initial tap 15:25 PKT, but using only candles up to 16:14 PKT:
res = compute_ltf_approach_structure(
    target_time=tap_ts,
    ltf_candles=c_1m[:idx_1614 + 1],
    htf_boxes=[the_box],
    htf_sec=3600,
    htf_candles=c_1h_pit
)

tap_info = res.get("tap_info")
print("When target_time is anchored to initial tap (15:25 PKT):")
print(f"  tap_info exists: {tap_info is not None}")
if tap_info:
    print(f"  winner_pathway: {tap_info.get('winner_pathway')}")
    print(f"  trade: {tap_info.get('trade')}")
