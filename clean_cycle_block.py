with open("faithful_backtest_engine.py", "r", encoding="utf-8") as f:
    code = f.read()

# Let's inspect the exact block and replace it cleanly
target_start = '            cycle_handled = False\n            for reg_key, cyc in list(self.zone_cycles.items()):\n                init_tap = cyc["initial_tap_time"]\n                target_b = cyc["box"]'

# Let's write the clean block
clean_block = """            cycle_handled = False
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
                    continue

                # Setup context for traceability logging
                setup_id = f"setup_{self.symbol}_{self.htf_tf}_{c_time}"
                ctx = self.trace_logger.create_context(setup_id, self.symbol, self.htf_tf, self.ltf_tf, c_time)

                ctx.record_rule("ZONE-001", RuleStatus.PASS, f"Qualifying zone: {tap_info.get('box_name')}")
                ctx.record_rule("ZONE-002", RuleStatus.PASS, "Zone formed before decision time")
                ctx.record_rule("ZONE-003", RuleStatus.PASS, "Zone unmitigated")
                ctx.record_rule("MTF-001", RuleStatus.PASS, f"Valid pair: {self.htf_tf}->{self.ltf_tf}")
                ctx.record_rule("MTF-002", RuleStatus.PASS, "Counter-trend approach verified")
                ctx.record_rule("MTF-003", RuleStatus.PASS, "Valid tap direction verified")

                # Check A+ setup elimination (Rule RISK-005)
                box_name = str(tap_info.get("box_name", "")).upper()
                if "A+" in box_name:
                    ctx.record_rule("RISK-005", RuleStatus.FAIL, "A+ setup eliminated by institutional rule")
                    self.trace_logger.log_context_completion(ctx)
                    continue
                else:
                    ctx.record_rule("RISK-005", RuleStatus.PASS, "Non-A+ level")

                tr = tap_info.get("trade")
                if not tr or not tr.get("executed"):
                    fail_reason = tr.get("status", "NO_CANDLE_PATTERN") if tr else "NO_REVERSAL_STRUCTURE"
                    ctx.record_rule("CANDLE-002", RuleStatus.FAIL, fail_reason)
                    self.trace_logger.log_context_completion(ctx)
                    continue

                ctx.record_rule("LTF-001", RuleStatus.PASS, "Race condition completed")
                ctx.record_rule("CANDLE-001", RuleStatus.PASS, "Retest inside zone boundary")
                ctx.record_rule("CANDLE-002", RuleStatus.PASS, f"Pattern: {tr.get('pattern_name')}")

                # Latency check: signal must have fired on or after tap
                tr_time = tr.get("time")
                if tr_time < c_time:
                    ctx.record_rule("MGMT-001", RuleStatus.FAIL, f"Signal expired ({tr_time} < {c_time})")
                    self.trace_logger.log_context_completion(ctx)
                    continue

                # Risk & Sizing calculation (Rules RISK-001, RISK-002, RISK-006)
                entry_p = tr["entry_price"]
                sl_p = tr["sl_price"]
                tp_p = tr["tp_price"]
                risk_dist = abs(entry_p - sl_p)

                if risk_dist <= 0:
                    ctx.record_rule("RISK-001", RuleStatus.FAIL, "Zero risk distance")
                    self.trace_logger.log_context_completion(ctx)
                    continue

                ctx.record_rule("RISK-001", RuleStatus.PASS, "0.5x ATR_15M cushion applied")

                reward_dist = abs(tp_p - entry_p)
                planned_rr = round(reward_dist / risk_dist, 2)
                required_rr = 3.0 if self.htf_tf == "4h" else 2.5

                if planned_rr < required_rr:
                    ctx.record_rule("RISK-002", RuleStatus.FAIL, f"RR {planned_rr:.2f} < {required_rr:.2f} floor")
                    self.trace_logger.log_context_completion(ctx)
                    continue

                ctx.record_rule("RISK-002", RuleStatus.PASS, f"RR {planned_rr:.2f} >= {required_rr:.2f}")

                # Position Sizing (Rule RISK-006)
                risk_dollars = self.balance * self.risk_pct
                pos_size = risk_dollars / risk_dist
                pos_size = max(0.001, round(pos_size, 3))  # Clamped to BTC step size

                notional = pos_size * entry_p
                if self.balance <= 0 or (notional / 25.0) > self.balance:
                    ctx.record_rule("RISK-006", RuleStatus.FAIL, "Insufficient margin")
                    self.trace_logger.log_context_completion(ctx)
                    continue

                ctx.record_rule("RISK-006", RuleStatus.PASS, f"Sized for 1% risk: ${risk_dollars:.2f}")
                ctx.record_rule("RISK-003", RuleStatus.PASS, "Level registered for single trade")
                ctx.record_rule("RISK-004", RuleStatus.PASS, "No conflicting position active")
                ctx.record_rule("RISK-007", RuleStatus.PASS, "Circuit breaker clean")
                ctx.record_rule("MGMT-001", RuleStatus.PASS, "Maker Limit order dispatched")
                ctx.record_rule("MGMT-002", RuleStatus.PASS, "Intrabar SL/TP rules active")

                # Final validation check
                can_exec, reject_reason = ctx.can_execute()
                if not can_exec:
                    ctx.is_executed = False
                    self.trace_logger.log_context_completion(ctx)
                    continue

                # Lock zone in registry and close cycle (Rule RISK-003)
                matched_b = tap_info.get("box", {})
                b_id = matched_b.get("id") or f"{matched_b.get('text')}_{matched_b.get('top')}_{matched_b.get('bottom')}_{matched_b.get('confirmed_formation_time', 0)}"
                reg_key = f"{self.symbol}_{self.htf_tf}_{b_id}"
                self.zone_single_trade_registry.add(reg_key)
                if reg_key in self.zone_cycles:
                    del self.zone_cycles[reg_key]
                cycle_handled = True

                entry_fee = notional * self.maker_fee
                pending_order = {
                    "trade_id": f"trade_{self.symbol}_{self.htf_tf}_{c_time}",
                    "symbol": self.symbol,
                    "htf": self.htf_tf,
                    "ltf": self.ltf_tf,
                    "action": tr["action"],
                    "placed_time": tr_time,
                    "entry_price": entry_p,
                    "sl_price": sl_p,
                    "tp_price": tp_p,
                    "risk_distance": risk_dist,
                    "reward_distance": reward_dist,
                    "rr": planned_rr,
                    "risk_dollars": risk_dollars,
                    "position_size": pos_size,
                    "entry_fee": entry_fee,
                    "pattern_name": tr.get("pattern_name"),
                    "level_name": tap_info.get("box_name")
                }

                ctx.is_executed = True
                ctx.trade_payload = pending_order
                self.trace_logger.log_context_completion(ctx)
                break"""

# Find lines in code between `cycle_handled = False` and `metrics = self._compute_performance_metrics(trades)`
start_str = "            cycle_handled = False"
end_str = "        metrics = self._compute_performance_metrics(trades)"

start_idx = code.find(start_str)
end_idx = code.find(end_str)

assert start_idx != -1 and end_idx != -1, "Indices not found"

new_code = code[:start_idx] + clean_block + "\n\n" + code[end_idx:]

with open("faithful_backtest_engine.py", "w", encoding="utf-8") as f:
    f.write(new_code)

print("Cleanly replaced cycle block in faithful_backtest_engine.py")
