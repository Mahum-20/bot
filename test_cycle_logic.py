from test_pit_h1 import c_1h_pit, the_box, pkt
from test_specific_setup import c_1m
from datetime import datetime, timezone
from ltf_approach_engine import compute_ltf_approach_structure, is_valid_tap_approach

times_1m = [c["time"] for c in c_1m]
import bisect

# User's scenario:
# 15:25 PKT: Initial tap
ts_1525 = int(datetime(2026, 11, 4, 10, 25, tzinfo=timezone.utc).timestamp())
# 16:14 PKT: Bearish Engulfing retest
ts_1614 = int(datetime(2026, 11, 4, 11, 14, tzinfo=timezone.utc).timestamp())

idx_1525 = bisect.bisect_left(times_1m, ts_1525)
idx_1614 = bisect.bisect_left(times_1m, ts_1614)

print(f"Cycle opens at 15:25 PKT (index {idx_1525})")
print(f"Candles elapsed between 15:25 and 16:14: {idx_1614 - idx_1525} candles (well within 120-candle window)")

# Now at 16:14 PKT, evaluate with initial_tap_time = ts_1525:
res = compute_ltf_approach_structure(
    target_time=ts_1525,  # Anchored to cycle initial_tap_time!
    ltf_candles=c_1m[:idx_1614 + 1],
    htf_boxes=[the_box],
    htf_sec=3600,
    htf_candles=c_1h_pit
)

tap_info = res.get("tap_info")
print("\nEvaluation at 16:14 PKT with initial_tap_time anchored to 15:25 PKT:")
print(f"  winner_pathway: {tap_info.get('winner_pathway') if tap_info else None}")
tr = tap_info.get("trade") if tap_info else None
print(f"  trade: {tr}")
if tr:
    dt_entry = datetime.fromtimestamp(tr['time'], pkt)
    print(f"  Trade Entry Time: {dt_entry.strftime('%H:%M PKT')} | Action: {tr['action']} | Level: {tr['level_name']} | RR: {tr['rr']}R")
