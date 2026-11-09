from test_pit_h1 import c_1h_pit, the_box, pkt
from test_specific_setup import c_1m
from datetime import datetime, timezone

times_1m = [c["time"] for c in c_1m]
import bisect
idx_1614 = bisect.bisect_left(times_1m, int(datetime(2026, 11, 4, 11, 14, tzinfo=timezone.utc).timestamp()))

b_top = max(the_box["top"], the_box["bottom"])
b_bot = min(the_box["top"], the_box["bottom"])

# Let's inspect how to find the initial tap from 16:14:
# Search backward within the last 120 bars (2 hours) for the earliest candle that tapped the zone from outside
earliest_tap_idx = idx_1614
lookback_window = min(idx_1614, 120)

for j in range(idx_1614, idx_1614 - lookback_window, -1):
    c = c_1m[j]
    if c["high"] >= b_bot and c["low"] <= b_top:
        earliest_tap_idx = j

print(f"At 16:14, looking backward found earliest tap at index {earliest_tap_idx}:")
print(f"Time: {datetime.fromtimestamp(c_1m[earliest_tap_idx]['time'], pkt)}")
