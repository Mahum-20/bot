with open("faithful_backtest_engine.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add zone_cycles to __init__
old_init = """        # Single trade per level registry (Rules RISK-003 & ZONE-001)
        self.zone_single_trade_registry = set()"""

new_init = """        # Single trade per level registry (Rules RISK-003 & ZONE-001)
        self.zone_single_trade_registry = set()

        # Cycle State Machine: 120-candle reaction cycles (First Tap vs Retest)
        self.zone_cycles = {}"""

assert old_init in code, "old_init not found"
code = code.replace(old_init, new_init)

# 2. Reset zone_cycles at the start of run_backtest
old_rb = """        active_position: Optional[Dict] = None
        pending_order: Optional[Dict] = None
        trades: List[Dict] = []"""

new_rb = """        active_position: Optional[Dict] = None
        pending_order: Optional[Dict] = None
        trades: List[Dict] = []
        self.zone_cycles = {}"""

assert old_rb in code, "old_rb not found"
code = code.replace(old_rb, new_rb)

# 3. Replace lines 309-335 with Cycle State Machine evaluation
old_eval = """            # Quick check if any box is tapped by recent LTF candles (last 20 bars)
            recent_ltf_slice = self.c_ltf[max(0, i - 19):i + 1]
            tapped_boxes = []
            for b in available_boxes:
                b_top = max(b.get("top", 0), b.get("bottom", 0))
                b_bot = min(b.get("top", 0), b.get("bottom", 0))
                if any(bar["high"] >= b_bot and bar["low"] <= b_top for bar in recent_ltf_slice):
                    tapped_boxes.append(b)

            if not tapped_boxes:
                continue

            # Run localized LTF approach structure (Rules MTF-002, MTF-003, LTF-001)
            ltf_history_slice = self.c_ltf[max(0, i - 500):i + 1]
            htf_history_slice = self.c_htf[:h_idx]

            res = compute_ltf_approach_structure(
                target_time=c_time,
                ltf_candles=ltf_history_slice,
                htf_boxes=available_boxes,
                htf_sec=self.htf_sec,
                htf_candles=htf_history_slice
            )

            tap_info = res.get("tap_info")
            if not tap_info:
                continue"""

new_eval = """            # Cycle State Machine: Manage 120-candle reaction cycles per zone
            max_cycle_seconds = 120 * self.ltf_sec

            # 1. Clean up expired cycles (> 120 candles)
            expired_keys = [k for k, cyc in self.zone_cycles.items() if (c_time - cyc["initial_tap_time"]) > max_cycle_seconds]
            for k in expired_keys:
                del self.zone_cycles[k]

            # 2. Check for new taps from outside to open reaction cycles
            for b in available_boxes:
                b_id = b.get("id") or f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}_{b.get('confirmed_formation_time', 0)}"
                reg_key = f"{self.symbol}_{self.htf_tf}_{b_id}"
                if reg_key not in self.zone_cycles:
                    b_top = max(b.get("top", 0), b.get("bottom", 0))
                    b_bot = min(b.get("top", 0), b.get("bottom", 0))
                    if c_curr["high"] >= b_bot and c_curr["low"] <= b_top:
                        if is_valid_tap_approach(b, self.c_ltf, i):
                            self.zone_cycles[reg_key] = {
                                "initial_tap_time": c_time,
                                "initial_tap_idx": i,
                                "box": b
                            }

            if not self.zone_cycles:
                continue

            # Run localized LTF approach structure for active cycles (Rules MTF-002, MTF-003, LTF-001)
            ltf_history_slice = self.c_ltf[max(0, i - 500):i + 1]
            htf_history_slice = self.c_htf[:h_idx]

            cycle_handled = False
            for reg_key, cyc in list(self.zone_cycles.items()):
                init_tap = cyc["initial_tap_time"]
                target_b = cyc["box"]

                res = compute_ltf_approach_structure(
                    target_time=init_tap,
                    ltf_candles=ltf_history_slice,
                    htf_boxes=[target_b],
                    htf_sec=self.htf_sec,
                    htf_candles=htf_history_slice,
                    override_tap_time=init_tap,
                    override_box=target_b
                )

                tap_info = res.get("tap_info")
                if not tap_info:
                    continue"""

assert old_eval in code, "old_eval not found"
code = code.replace(old_eval, new_eval)

# 4. On order placement, close the cycle and break cycle loop
old_order = """            # Lock zone in registry (Rule RISK-003)
            matched_b = tap_info.get("box", {})
            b_id = matched_b.get("id") or f"{matched_b.get('text')}_{matched_b.get('top')}_{matched_b.get('bottom')}_{matched_b.get('confirmed_formation_time', 0)}"
            reg_key = f"{self.symbol}_{self.htf_tf}_{b_id}"
            self.zone_single_trade_registry.add(reg_key)"""

new_order = """            # Lock zone in registry and close cycle (Rule RISK-003)
            matched_b = tap_info.get("box", {})
            b_id = matched_b.get("id") or f"{matched_b.get('text')}_{matched_b.get('top')}_{matched_b.get('bottom')}_{matched_b.get('confirmed_formation_time', 0)}"
            reg_key = f"{self.symbol}_{self.htf_tf}_{b_id}"
            self.zone_single_trade_registry.add(reg_key)
            if reg_key in self.zone_cycles:
                del self.zone_cycles[reg_key]
            cycle_handled = True"""

assert old_order in code, "old_order not found"
code = code.replace(old_order, new_order)

with open("faithful_backtest_engine.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully updated faithful_backtest_engine.py with Cycle State Machine!")
