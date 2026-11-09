from test_pit_h1 import c_1h_pit, the_box, pkt
from test_specific_setup import c_1m
from datetime import datetime, timezone
from ltf_approach_engine import compute_ltf_approach_structure, is_valid_tap_approach

times_1m = [c["time"] for c in c_1m]
import bisect

# Let's run a bar-by-bar simulation of the Cycle State Machine on Nov 4:
# From 15:00 to 17:00 PKT (10:00 to 12:00 UTC)
start_idx = bisect.bisect_left(times_1m, int(datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc).timestamp()))
end_idx = bisect.bisect_left(times_1m, int(datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc).timestamp()))

zone_cycles = {} # b_id -> {"initial_tap_time": int, "initial_tap_idx": int, "box": b}
trades_found = []

ltf_sec = 60
max_cycle_seconds = 120 * ltf_sec # 120 candles window

b_top = max(the_box["top"], the_box["bottom"])
b_bot = min(the_box["top"], the_box["bottom"])
b_id = "tjl2_nov2"

for i in range(start_idx, end_idx):
    c_curr = c_1m[i]
    c_time = c_curr["time"]
    t_pkt = datetime.fromtimestamp(c_time, pkt).strftime("%H:%M")

    # 1. Clean up expired cycles
    if b_id in zone_cycles:
        if c_time - zone_cycles[b_id]["initial_tap_time"] > max_cycle_seconds:
            print(f"[{t_pkt}] Cycle expired for {b_id}")
            del zone_cycles[b_id]

    # 2. Check for new tap to open cycle
    is_touching = (c_curr["high"] >= b_bot and c_curr["low"] <= b_top)
    if b_id not in zone_cycles and is_touching:
        # Check valid approach
        if is_valid_tap_approach(the_box, c_1m, i):
            zone_cycles[b_id] = {
                "initial_tap_time": c_time,
                "initial_tap_idx": i,
                "box": the_box
            }
            print(f"[{t_pkt}] OPENED REACTION CYCLE for {the_box['text']} (anchor: {c_time})")

    # 3. If in active cycle, evaluate setup
    if b_id in zone_cycles:
        init_tap = zone_cycles[b_id]["initial_tap_time"]
        res = compute_ltf_approach_structure(
            target_time=init_tap,
            ltf_candles=c_1m[:i + 1],
            htf_boxes=[the_box],
            htf_sec=3600,
            htf_candles=c_1h_pit
        )
        tap_info = res.get("tap_info")
        if tap_info and tap_info.get("trade"):
            tr = tap_info["trade"]
            if tr.get("executed") and tr.get("time") == c_time:
                trades_found.append((t_pkt, tr))
                print(f"[{t_pkt}] >>> TRADE EXECUTED! Action={tr['action']}, Entry={tr['entry_price']}, SL={tr['sl_price']}, TP={tr['tp_price']}, RR={tr['rr']}R, Level={tr['level_name']}")
                # Close cycle
                del zone_cycles[b_id]

print(f"\nTotal trades executed by Cycle State Machine: {len(trades_found)}")
