from datetime import datetime, timezone
from test_specific_setup import c_1m, c_1h, pkt
from ltf_approach_engine import compute_ltf_approach_structure
import copy
from diagnose_steps import the_box

test_box = copy.deepcopy(the_box)
test_box["text"] = "TJL2"
test_box["is_bullish"] = False
test_box["level_type"] = "supply"

signal_ts = int(datetime(2026, 11, 4, 11, 14, tzinfo=timezone.utc).timestamp()) # 16:14 PKT

res = compute_ltf_approach_structure(
    target_time=signal_ts,
    ltf_candles=c_1m,
    htf_boxes=[test_box],
    htf_sec=3600,
    htf_candles=c_1h
)

tap_info = res.get("tap_info")
print(f"When treated as TJL2 Supply:")
print(f"  tap_info: {tap_info is not None}")
if tap_info:
    print("  winner_pathway:", tap_info.get("winner_pathway"))
    print("  has_approach_bos:", tap_info.get("has_approach_bos"))
    print("  trade:", tap_info.get("trade"))
    if not tap_info.get("trade"):
        print("  trade is None! Why?")
        # let's inspect trade detection
