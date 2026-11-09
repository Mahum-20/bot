import json
from datetime import datetime, timezone, timedelta
from test_pit_h1 import c_1h_pit, the_box, pkt
from test_specific_setup import c_1m
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box

# Candle 16:00 PKT (11:00 UTC)
ts_1600 = int(datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc).timestamp())
times_1m = [c["time"] for c in c_1m]
import bisect
idx_1600 = bisect.bisect_left(times_1m, ts_1600)

# Check find_tapped_htf_box at 16:00 PKT
matched_b, tap_idx = find_tapped_htf_box(ts_1600, c_1m[:idx_1600 + 1], [the_box], 3600)
print(f"At 16:00 PKT: matched_b={matched_b is not None}, tap_idx={tap_idx}")
if tap_idx is not None:
    print(f"  tap time: {datetime.fromtimestamp(c_1m[tap_idx]['time'], pkt)}")

res = compute_ltf_approach_structure(
    target_time=ts_1600,
    ltf_candles=c_1m[:idx_1600 + 1],
    htf_boxes=[the_box],
    htf_sec=3600,
    htf_candles=c_1h_pit
)
print(f"At 16:00 PKT tap_info: {res.get('tap_info') is not None}")
if res.get('tap_info'):
    print(f"  winner_pathway: {res['tap_info'].get('winner_pathway')}")
    print(f"  trade: {res['tap_info'].get('trade')}")
