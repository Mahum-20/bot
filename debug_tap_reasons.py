from datetime import datetime, timezone
from test_specific_setup import c_1m, pkt
from diagnose_steps import the_box
from ltf_approach_engine import is_htf_box_active, is_valid_tap_approach

signal_ts = int(datetime(2026, 11, 4, 11, 14, tzinfo=timezone.utc).timestamp())
times = [c["time"] for c in c_1m]
import bisect
pos = bisect.bisect_left(times, signal_ts)
target_idx = pos

c_target = c_1m[target_idx]
c_target_time = c_target["time"]

print(f"Target candle time: {datetime.fromtimestamp(c_target_time, pkt)}")
print(f"1. is_htf_box_active(the_box, {c_target_time}): {is_htf_box_active(the_box, c_target_time)}")

b_left = the_box.get("left") or the_box.get("created_time") or 0
b_right = the_box.get("mitigated_time") if (the_box.get("is_mitigated") or the_box.get("is_broken")) else 9999999999
print(f"2. b_left <= c_target_time <= b_right: {b_left} <= {c_target_time} <= {b_right} -> {b_left <= c_target_time <= b_right}")

print(f"3. is_valid_tap_approach(the_box, c_1m, {target_idx}): {is_valid_tap_approach(the_box, c_1m, target_idx)}")

# Step 2 search:
htf_sec = 3600
max_step = max(1, htf_sec // 60)
print(f"Step 2 search range: {target_idx} to {target_idx + max_step}")
step2_taps = []
for idx in range(target_idx, min(len(c_1m), target_idx + max_step)):
    c = c_1m[idx]
    if is_valid_tap_approach(the_box, c_1m, idx):
        step2_taps.append(idx)
print(f"Step 2 taps: {step2_taps}")

# Step 3 search [target_idx - 5, target_idx + 5]
step3_taps = []
for idx in range(max(0, target_idx - 5), min(len(c_1m), target_idx + 6)):
    if is_valid_tap_approach(the_box, c_1m, idx):
        step3_taps.append(idx)
print(f"Step 3 taps: {step3_taps}")
