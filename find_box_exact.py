import json
from datetime import datetime, timezone, timedelta
from test_specific_setup import c_1h, c_1m, boxes, pkt

target_time_utc = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc).timestamp()
print(f"Target formation time: {target_time_utc}")

found_boxes = []
for b in boxes:
    if abs(b.get("left", 0) - target_time_utc) < 7200:
        found_boxes.append(b)

print(f"Found {len(found_boxes)} boxes near target formation time:")
for b in found_boxes:
    print(" ", b)
