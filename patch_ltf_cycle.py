with open("ltf_approach_engine.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update find_tapped_htf_box to trace backward up to 120 candles
old_ret = '''            if is_valid_tap_approach(b, ltf_candles, target_idx):

                return b, target_idx'''

new_ret = '''            if is_valid_tap_approach(b, ltf_candles, target_idx):
                # Cycle State Machine: Trace back up to 120 candles to anchor to the initial tap
                initial_tap_idx = target_idx
                b_top = max(b.get("top", 0), b.get("bottom", 0))
                b_bot = min(b.get("top", 0), b.get("bottom", 0))
                for back_i in range(target_idx - 1, max(-1, target_idx - 120), -1):
                    c_prev = ltf_candles[back_i]
                    if c_prev["high"] >= b_bot and c_prev["low"] <= b_top:
                        initial_tap_idx = back_i
                    elif is_valid_tap_approach(b, ltf_candles, initial_tap_idx):
                        break
                return b, initial_tap_idx'''

assert old_ret in code, "old_ret not found"
code = code.replace(old_ret, new_ret)

# 2. Update compute_ltf_approach_structure definition to accept override_tap_time and override_box
old_def = '''def compute_ltf_approach_structure(

    target_time: int,

    ltf_candles: List[Dict],

    htf_boxes: List[Dict],

    htf_sec: int = 900,

    htf_candles: Optional[List[Dict]] = None

) -> Dict:'''

new_def = '''def compute_ltf_approach_structure(

    target_time: int,

    ltf_candles: List[Dict],

    htf_boxes: List[Dict],

    htf_sec: int = 900,

    htf_candles: Optional[List[Dict]] = None,

    override_tap_time: Optional[int] = None,

    override_box: Optional[Dict] = None

) -> Dict:'''

assert old_def in code, "old_def not found"
code = code.replace(old_def, new_def)

# 3. Update call in compute_ltf_approach_structure
old_match = '''    matched_box, tap_idx = find_tapped_htf_box(target_time, ltf_candles, htf_boxes, htf_sec)'''

new_match = '''    if override_tap_time is not None and override_tap_time > 0:
        times = [c["time"] for c in ltf_candles]
        import bisect
        pos = bisect.bisect_left(times, override_tap_time)
        tap_idx = min(len(ltf_candles) - 1, max(0, pos))
        matched_box = override_box if override_box is not None else (htf_boxes[0] if htf_boxes else None)
    else:
        matched_box, tap_idx = find_tapped_htf_box(target_time, ltf_candles, htf_boxes, htf_sec)'''

assert old_match in code, "old_match not found"
code = code.replace(old_match, new_match)

with open("ltf_approach_engine.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully updated ltf_approach_engine.py with Cycle State Machine backward trace and override_tap_time!")
