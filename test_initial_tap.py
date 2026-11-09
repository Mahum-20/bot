from test_as_supply import test_box, c_1m, c_1h, pkt
from ltf_approach_engine import compute_ltf_approach_structure
from datetime import datetime, timezone

# Tap at 15:25 PKT (10:25 UTC)
tap_ts = int(datetime(2026, 11, 4, 10, 25, tzinfo=timezone.utc).timestamp())

res = compute_ltf_approach_structure(
    target_time=tap_ts,
    ltf_candles=c_1m,
    htf_boxes=[test_box],
    htf_sec=3600,
    htf_candles=c_1h
)

tap_info = res.get("tap_info")
print(f"When target_time is initial tap at 15:25 PKT:")
print(f"  tap_info: {tap_info is not None}")
if tap_info:
    print("  winner_pathway:", tap_info.get("winner_pathway"))
    print("  has_approach_bos:", tap_info.get("has_approach_bos"))
    print("  boxes drawn count:", len(res.get("boxes", [])))
    for b in res.get("boxes", []):
        print("    Box:", b.get("text"), b.get("top"), b.get("bottom"))
    print("  trade:", tap_info.get("trade"))
