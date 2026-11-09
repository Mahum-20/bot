import json
from datetime import datetime, timezone, timedelta
from test_specific_setup import c_1h, c_1m, boxes, pkt
from ltf_approach_engine import compute_ltf_approach_structure, find_tapped_htf_box
from htf_engine import HTFEngine

the_box = None
for b in boxes:
    if abs(b.get("top", 0) - 78853.5) < 10:
        the_box = b
        break

# Let's inspect what compute_ltf_approach_structure does for target_time = 16:14 PKT (11:14 UTC)
signal_ts = int(datetime(2026, 11, 4, 11, 14, tzinfo=timezone.utc).timestamp())
tap_ts = int(datetime(2026, 11, 4, 10, 25, tzinfo=timezone.utc).timestamp()) # 15:25 PKT

print("Box details:")
print(f"  text: {the_box.get('text')}")
print(f"  is_bullish: {the_box.get('is_bullish')}")
print(f"  top: {the_box.get('top')}, bottom: {the_box.get('bottom')}")
print(f"  left: {the_box.get('left')} ({datetime.fromtimestamp(the_box.get('left'), pkt)})")
print(f"  right: {the_box.get('right')} ({datetime.fromtimestamp(the_box.get('right'), pkt)})")
print(f"  is_mitigated: {the_box.get('is_mitigated')}")

# Run find_tapped_htf_box at signal_ts
matched_box, tap_idx = find_tapped_htf_box(signal_ts, c_1m, [the_box], 3600)
print(f"\nfind_tapped_htf_box at 16:14 PKT:")
print(f"  matched_box: {matched_box is not None}")
print(f"  tap_idx: {tap_idx}")
if tap_idx is not None:
    print(f"  tap candle time: {datetime.fromtimestamp(c_1m[tap_idx]['time'], pkt)}")

# Run compute_ltf_approach_structure
res = compute_ltf_approach_structure(
    target_time=signal_ts,
    ltf_candles=c_1m,
    htf_boxes=[the_box],
    htf_sec=3600,
    htf_candles=c_1h
)

tap_info = res.get("tap_info")
print("\ncompute_ltf_approach_structure result:")
print(f"  tap_info: {tap_info is not None}")
if tap_info:
    for k, v in tap_info.items():
        if k != "lines" and k != "boxes":
            print(f"    {k}: {v}")
