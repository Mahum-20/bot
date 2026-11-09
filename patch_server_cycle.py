with open("server.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add ZONE_CYCLE_REGISTRY
target_reg = "ZONE_SINGLE_TRADE_REGISTRY: Dict[str, Dict] = load_zone_registry()"
replacement_reg = """ZONE_SINGLE_TRADE_REGISTRY: Dict[str, Dict] = load_zone_registry()
ZONE_CYCLE_REGISTRY: Dict[str, Dict] = {}  # reg_key -> {"symbol": str, "htf_tf": str, "initial_tap_time": int, "box": Dict}"""

assert target_reg in code, "target_reg not found"
code = code.replace(target_reg, replacement_reg, 1)

# 2. Update lines 1161-1192 in server.py
old_block = """                        # Check if any available box is currently tapped by recent LTF candles (last 20 bars)
                        recent_check = closed_ltf[-20:]
                        is_tapped = False
                        for b in available_htf_boxes:
                            b_top = max(b.get("top", 0), b.get("bottom", 0))
                            b_bot = min(b.get("top", 0), b.get("bottom", 0))
                            if any(c["high"] >= b_bot and c["low"] <= b_top for c in recent_check):
                                is_tapped = True
                                break

                        if not is_tapped:
                            continue



                        # Run localized LTF approach and race condition

                        htf_sec_val = INTERVAL_SECONDS.get(htf_tf.lower(), 900)

                        res = compute_ltf_approach_structure(

                            target_time=latest_closed_ltf_time,

                            ltf_candles=closed_ltf,

                            htf_boxes=available_htf_boxes,

                            htf_sec=htf_sec_val,

                            htf_candles=recent_htf

                        )"""

new_block = """                        # Cycle State Machine: Manage 120-candle reaction cycles per zone
                        ltf_sec_val = INTERVAL_SECONDS.get(ltf_tf.lower(), 60)
                        max_cycle_seconds = 120 * ltf_sec_val

                        # 1. Clean up expired cycles
                        expired_keys = [
                            k for k, cyc in ZONE_CYCLE_REGISTRY.items()
                            if cyc.get("symbol") == symbol and cyc.get("htf_tf") == htf_tf
                            and (latest_closed_ltf_time - cyc.get("initial_tap_time", 0)) > max_cycle_seconds
                        ]
                        for k in expired_keys:
                            del ZONE_CYCLE_REGISTRY[k]

                        # 2. Check for new taps from outside to open reaction cycles
                        curr_ltf_c = closed_ltf[-1]
                        for b in available_htf_boxes:
                            b_id = b.get("id") or f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}_{b.get('confirmed_formation_time', 0)}"
                            reg_key = f"{symbol}_{htf_tf}_{b_id}"
                            if reg_key not in ZONE_CYCLE_REGISTRY:
                                b_top = max(b.get("top", 0), b.get("bottom", 0))
                                b_bot = min(b.get("top", 0), b.get("bottom", 0))
                                if curr_ltf_c["high"] >= b_bot and curr_ltf_c["low"] <= b_top:
                                    if is_valid_tap_approach(b, closed_ltf, len(closed_ltf) - 1):
                                        ZONE_CYCLE_REGISTRY[reg_key] = {
                                            "symbol": symbol,
                                            "htf_tf": htf_tf,
                                            "initial_tap_time": latest_closed_ltf_time,
                                            "box": b
                                        }
                                        logger.info(f"[{symbol} {htf_tf}->{ltf_tf}] Opened 120-candle Reaction Cycle for zone {b.get('text')} at {latest_closed_ltf_time}")

                        active_cycles = [
                            (k, cyc) for k, cyc in ZONE_CYCLE_REGISTRY.items()
                            if cyc.get("symbol") == symbol and cyc.get("htf_tf") == htf_tf
                        ]
                        if not active_cycles:
                            continue

                        # Run localized LTF approach structure for active cycle
                        htf_sec_val = INTERVAL_SECONDS.get(htf_tf.lower(), 900)
                        reg_key, cyc = active_cycles[0]
                        init_tap_time = cyc["initial_tap_time"]
                        target_box = cyc["box"]

                        res = compute_ltf_approach_structure(
                            target_time=init_tap_time,
                            ltf_candles=closed_ltf,
                            htf_boxes=[target_box],
                            htf_sec=htf_sec_val,
                            htf_candles=recent_htf,
                            override_tap_time=init_tap_time,
                            override_box=target_box
                        )"""

# Handle CRLF
if old_block not in code:
    old_block = old_block.replace("\n", "\r\n")
    new_block = new_block.replace("\n", "\r\n")

assert old_block in code, "old_block not found in server.py"
code = code.replace(old_block, new_block, 1)

# On trade execution in server.py, remove from ZONE_CYCLE_REGISTRY
old_trade_reg = """                        ZONE_SINGLE_TRADE_REGISTRY[reg_key] = {"""
new_trade_reg = """                        if reg_key in ZONE_CYCLE_REGISTRY:
                            del ZONE_CYCLE_REGISTRY[reg_key]
                        ZONE_SINGLE_TRADE_REGISTRY[reg_key] = {"""

if old_trade_reg not in code:
    old_trade_reg = old_trade_reg.replace("\n", "\r\n")
    new_trade_reg = new_trade_reg.replace("\n", "\r\n")

assert old_trade_reg in code, "old_trade_reg not found in server.py"
code = code.replace(old_trade_reg, new_trade_reg, 1)

with open("server.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully updated server.py with 120-candle Cycle State Machine!")
