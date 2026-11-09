"""
Audit Backtest Engine (Event-Driven, Zero-Lookahead, Full Friction Accounting)
=============================================================================
Performs rigorous Point-in-Time backtesting of the Meyhem Quant / TopG MTF strategy:
1. Zero Lookahead Bias:
   - HTF structure updates strictly on closed HTF candles.
   - LTF approach, 5-wave Elliott, and candlestick reversals are evaluated strictly on closed LTF bars.
2. Full Execution Frictions:
   - VIP0 Binance USDT-M Futures Commissions (0.02% Maker, 0.05% Taker).
   - Market Stop-Loss Slippage (0.05% adverse).
   - Intra-bar collision protection (conservative SL-first priority).
   - 8-Hour Funding Rate debits for open positions.
3. Institutional Risk Integration:
   - Full PortfolioRiskManager state machine:
     * ISOLATED Margin locked.
     * Factor 3 Drawdown Throttling (3.0% -> 1.5% at >= 8% DD).
     * Daily Circuit Breakers (-10% daily loss).
     * Macroeconomic News Blackouts (CPI, FOMC, NFP +/- 2.5h).
     * Funding Rate Blackouts (+/- 0.08%).
     * Toxic hours session filter (01-03, 05-06, 18-21 UTC).
4. Walk-Forward Analysis (WFA):
   - In-Sample (70%): Jan 1, 2026 00:00 UTC -> Aug 31, 2026 23:59 UTC (Parameter Calibration).
   - Out-of-Sample (30%): Sep 1, 2026 00:00 UTC -> Oct 31, 2026 23:59 UTC (Blind Validation).
"""

import os
import sys
import json
import math
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

# Ensure project root in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from htf_engine import HTFEngine, is_qualifying_htf_zone, is_htf_box_active
from ltf_approach_engine import (
    clean_box_name,
    candle_touches_level,
    find_nearest_htf_liquidity,
    compute_ltf_approach_structure
)
from portfolio_risk_manager import PortfolioRiskManager, DEFAULT_CONFIG
from timeframe_allocation_manager import timeframe_allocation_engine
from macro_news_filter import macro_news_engine
from funding_rate_filter import funding_rate_engine

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

class AuditBacktestEngine:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        htf_tf: str = "4h",
        ltf_tf: str = "5m",
        initial_balance: float = 10000.0,
        maker_fee: float = 0.0002,   # 0.02%
        taker_fee: float = 0.0005,   # 0.05%
        slippage_pct: float = 0.0005 # 0.05%
    ):
        self.symbol = symbol.upper()
        self.htf_tf = htf_tf.lower()
        self.ltf_tf = ltf_tf.lower()
        self.initial_balance = initial_balance
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.slippage_pct = slippage_pct

        self.htf_sec = self._parse_tf_seconds(self.htf_tf)
        self.ltf_sec = self._parse_tf_seconds(self.ltf_tf)

        self.c_htf = self._load_candles(self.htf_tf)
        self.c_ltf = self._load_candles(self.ltf_tf)
        print(f"[INIT] Loaded {len(self.c_htf)} HTF ({self.htf_tf}) bars and {len(self.c_ltf)} LTF ({self.ltf_tf}) bars for {self.symbol}.")

    def _parse_tf_seconds(self, tf: str) -> int:
        if tf == "1m": return 60
        if tf == "5m": return 300
        if tf == "15m": return 900
        if tf == "1h": return 3600
        if tf == "4h": return 14400
        if tf == "1d": return 86400
        raise ValueError(f"Unsupported timeframe {tf}")

    def _load_candles(self, tf: str) -> List[Dict]:
        path = os.path.join(DATA_DIR, f"{self.symbol.lower()}_{tf}_2026_full.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing data file: {path}. Run scratch/download_btc_2026.py first.")
        with open(path, "r", encoding="utf-8") as f:
            candles = json.load(f)
        candles.sort(key=lambda x: x["time"])
        return candles

    def run_simulation(
        self,
        start_ts: int,
        end_ts: int,
        fixed_rr: Optional[float] = 3.0,
        min_rr: float = 2.0,
        sl_buffer_pct: float = 0.0012,
        use_sl_buffer: bool = True,
        use_drawdown_throttling: bool = True,
        enable_session_filter: bool = True
    ) -> Dict[str, Any]:
        """
        Executes a strictly point-in-time sequential simulation over [start_ts, end_ts].
        """
        # Disable single-tier lock for this asset test so chosen timeframe is permitted
        timeframe_allocation_engine.criteria["filters_enabled"] = False

        # Configure isolated risk manager
        cfg = dict(DEFAULT_CONFIG)
        cfg["initial_capital"] = self.initial_balance
        cfg["persist_journal"] = False
        cfg["drawdown_throttling_enabled"] = use_drawdown_throttling
        cfg["session_filter_enabled"] = enable_session_filter
        cfg["sl_buffer_enabled"] = use_sl_buffer
        cfg["sl_buffer_pct"] = sl_buffer_pct
        cfg["max_allowed_slippage_pct"] = self.slippage_pct

        risk_mgr = PortfolioRiskManager(initial_capital=self.initial_balance, config=cfg)

        # Slice relevant HTF and LTF candles up to end_ts
        htf_subset = [c for c in self.c_htf if c["time"] <= end_ts]
        ltf_subset = [c for c in self.c_ltf if start_ts <= c["time"] <= end_ts]
        if not ltf_subset:
            return {"trades": [], "metrics": {}}

        # Run HTFEngine to identify structural zones
        engine_htf = HTFEngine(lookback_bars=len(htf_subset), show_tjl_boxes=True, tjl_extend=True)
        htf_boxes = [b for b in engine_htf.run(htf_subset).get("boxes", []) if is_qualifying_htf_zone(b)]

        # State tracking
        active_trade: Optional[Dict] = None
        trades: List[Dict] = []
        skipped_trades: List[Dict] = []
        box_state: Dict[str, str] = {}
        box_last_tap: Dict[str, int] = {}

        total_commissions = 0.0
        total_funding_fees = 0.0
        last_funding_check_time = 0

        # Bar-by-bar sequential loop
        for idx, c in enumerate(ltf_subset):
            c_time = c["time"]
            c_high = c["high"]
            c_low = c["low"]

            # -------------------------------------------------------------
            # STEP 1: Manage Active Position (Exits, Fees, Slippage, Funding)
            # -------------------------------------------------------------
            if active_trade:
                # 8-Hour Funding Rate Deduction
                dt_utc = datetime.fromtimestamp(c_time, timezone.utc)
                if dt_utc.hour in [0, 8, 16] and dt_utc.minute == 0 and c_time > last_funding_check_time:
                    last_funding_check_time = c_time
                    funding_rate = funding_rate_engine.get_funding_rate(self.symbol)
                    notional = active_trade["position_size_usd"]
                    f_cost = notional * funding_rate if active_trade["action"] == "BUY" else -notional * funding_rate
                    total_funding_fees += f_cost
                    risk_mgr.balance -= f_cost

                # Exit evaluation (only after entry candle has closed)
                if c_time > active_trade["entry_time"]:
                    is_bull = (active_trade["action"] == "BUY")
                    tp = active_trade["tp_price"]
                    sl = active_trade["sl_price"]

                    hit_tp = (c_high >= tp) if is_bull else (c_low <= tp)
                    hit_sl = (c_low <= sl) if is_bull else (c_high >= sl)

                    # Conservative Intra-bar resolution: if both hit on same bar, SL triggers first
                    if hit_tp and hit_sl:
                        hit_tp = False

                    if hit_tp:
                        exit_price = tp
                        exit_fee = active_trade["position_size_usd"] * self.maker_fee
                        total_commissions += exit_fee
                        
                        raw_r = active_trade["rr"]
                        pnl_usd = active_trade["risk_usd"] * raw_r - exit_fee
                        
                        active_trade.update({
                            "exit_time": c_time,
                            "exit_price": exit_price,
                            "exit_reason": "TP",
                            "outcome": "WIN",
                            "pnl_r": raw_r,
                            "pnl_usd": round(pnl_usd, 2),
                            "exit_fee": round(exit_fee, 2),
                            "duration_bars": idx - active_trade["entry_idx"]
                        })
                        
                        risk_mgr.balance += pnl_usd
                        risk_mgr.peak_equity = max(risk_mgr.peak_equity, risk_mgr.balance)
                        trades.append(active_trade)
                        active_trade = None

                    elif hit_sl:
                        slip_mult = (1.0 - self.slippage_pct) if is_bull else (1.0 + self.slippage_pct)
                        exit_price = round(sl * slip_mult, 2)
                        exit_fee = active_trade["position_size_usd"] * self.taker_fee
                        total_commissions += exit_fee

                        actual_loss_pct = abs(exit_price - active_trade["entry_price"]) / active_trade["risk_distance"]
                        pnl_usd = -active_trade["risk_usd"] * actual_loss_pct - exit_fee
                        
                        active_trade.update({
                            "exit_time": c_time,
                            "exit_price": exit_price,
                            "exit_reason": "SL",
                            "outcome": "LOSS",
                            "pnl_r": -round(actual_loss_pct, 2),
                            "pnl_usd": round(pnl_usd, 2),
                            "exit_fee": round(exit_fee, 2),
                            "duration_bars": idx - active_trade["entry_idx"]
                        })

                        risk_mgr.balance += pnl_usd
                        trades.append(active_trade)
                        active_trade = None

                if active_trade:
                    continue

            # -------------------------------------------------------------
            # STEP 2: Unlock HTF Zones when price moves outside
            # -------------------------------------------------------------
            for b in htf_boxes:
                if not is_htf_box_active(b, c_time):
                    continue
                b_key = f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}"
                b_top = max(b.get("top", 0), b.get("bottom", 0))
                b_bot = min(b.get("top", 0), b.get("bottom", 0))

                if not (c_high >= b_bot and c_low <= b_top):
                    if box_state.get(b_key) == "LOCKED" and (c_time - box_last_tap.get(b_key, 0) >= 3600):
                        box_state[b_key] = "READY"

            # -------------------------------------------------------------
            # STEP 3: Check New HTF Zone Taps & LTF Reversal Structure
            # -------------------------------------------------------------
            for b in htf_boxes:
                if not is_htf_box_active(b, c_time):
                    continue
                b_key = f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}"
                b_name = b.get("text") or b.get("name") or "HTF Zone"
                b_top = max(b.get("top", 0), b.get("bottom", 0))
                b_bot = min(b.get("top", 0), b.get("bottom", 0))

                # Zone intersection
                if c_high >= b_bot and c_low <= b_top:
                    if box_state.get(b_key, "READY") == "READY":
                        box_state[b_key] = "LOCKED"
                        box_last_tap[b_key] = c_time

                        res = compute_ltf_approach_structure(
                            target_time=c_time,
                            ltf_candles=ltf_subset,
                            htf_boxes=htf_boxes,
                            htf_sec=self.htf_sec,
                            htf_candles=htf_subset
                        )
                        tap_info = res.get("tap_info")
                        if tap_info and tap_info.get("trade"):
                            tr = tap_info["trade"]
                            if tr.get("executed") and tr.get("time") >= c_time:
                                risk_dist = tr["risk"]
                                is_bull = (tr["action"] == "BUY")

                                if fixed_rr is not None:
                                    planned_rr = fixed_rr
                                    reward_dist = round(risk_dist * fixed_rr, 2)
                                    planned_tp = round(tr["entry_price"] + reward_dist if is_bull else tr["entry_price"] - reward_dist, 2)
                                else:
                                    planned_tp = tr["tp_price"]
                                    planned_rr = tr["rr"]
                                    reward_dist = tr["reward"]

                                if planned_rr < min_rr:
                                    skipped_trades.append({
                                        "time": tr["time"],
                                        "reason": f"RR {planned_rr}R < min_rr {min_rr}R"
                                    })
                                    continue

                                # -----------------------------------------------------
                                # Evaluate with Institutional Risk Engine
                                # -----------------------------------------------------
                                eval_res = risk_mgr.evaluate_new_trade(
                                    symbol=self.symbol,
                                    entry_price=tr["entry_price"],
                                    sl_price=tr["sl_price"],
                                    tp_price=planned_tp,
                                    planned_rr=planned_rr,
                                    trade_type=tr["action"],
                                    timestamp=tr["time"],
                                    timeframe=self.htf_tf
                                )

                                if not eval_res.get("allowed"):
                                    skipped_trades.append({
                                        "time": tr["time"],
                                        "reason": eval_res.get("reason", "Risk Manager Rejection")
                                    })
                                    continue

                                # Position approved
                                pos_size = eval_res["notional_value"]
                                risk_usd = eval_res["risk_dollars"]
                                entry_fee = pos_size * self.maker_fee
                                total_commissions += entry_fee
                                risk_mgr.balance -= entry_fee

                                active_trade = {
                                    "id": f"{self.htf_tf}_{tr['time']}",
                                    "symbol": self.symbol,
                                    "action": tr["action"],
                                    "entry_time": tr["time"],
                                    "entry_idx": idx,
                                    "entry_price": tr["entry_price"],
                                    "sl_price": tr["sl_price"],
                                    "tp_price": planned_tp,
                                    "risk_distance": risk_dist,
                                    "reward_distance": reward_dist,
                                    "rr": planned_rr,
                                    "position_size_usd": pos_size,
                                    "risk_usd": risk_usd,
                                    "entry_fee": round(entry_fee, 2),
                                    "is_throttled": risk_mgr.is_throttled(),
                                    "pattern_name": tr["pattern_name"],
                                    "box_name": b_name
                                }
                                break

        # Handle trade left open at end
        if active_trade:
            c_final = ltf_subset[-1]
            is_bull = (active_trade["action"] == "BUY")
            raw_r = ((c_final["close"] - active_trade["entry_price"]) if is_bull else (active_trade["entry_price"] - c_final["close"])) / active_trade["risk_distance"]
            exit_fee = active_trade["position_size_usd"] * self.maker_fee
            pnl_usd = active_trade["risk_usd"] * raw_r - exit_fee
            active_trade.update({
                "exit_time": c_final["time"],
                "exit_price": c_final["close"],
                "exit_reason": "OPEN_AT_END",
                "outcome": "WIN" if raw_r > 0 else "LOSS",
                "pnl_r": round(raw_r, 2),
                "pnl_usd": round(pnl_usd, 2),
                "exit_fee": round(exit_fee, 2),
                "duration_bars": len(ltf_subset) - 1 - active_trade["entry_idx"]
            })
            risk_mgr.balance += pnl_usd
            trades.append(active_trade)
            active_trade = None

        metrics = self._calculate_metrics(trades, skipped_mgr=skipped_trades, final_balance=risk_mgr.balance, total_fees=total_commissions + total_funding_fees)
        return {
            "trades": trades,
            "skipped": skipped_trades,
            "metrics": metrics,
            "final_balance": round(risk_mgr.balance, 2)
        }

    def _calculate_metrics(self, trades: List[Dict], skipped_mgr: List[Dict], final_balance: float, total_fees: float) -> Dict[str, Any]:
        n = len(trades)
        wins = [t for t in trades if t["outcome"] == "WIN"]
        losses = [t for t in trades if t["outcome"] == "LOSS"]

        if n == 0:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "gross_profit_usd": 0.0,
                "gross_loss_usd": 0.0,
                "net_pnl_usd": 0.0,
                "total_return_pct": 0.0,
                "total_r": 0.0,
                "max_drawdown_r": 0.0,
                "r_efficiency": 0.0,
                "max_drawdown_pct": 0.0,
                "total_fees_usd": round(total_fees, 2),
                "fee_drag_pct": 0.0,
                "rejections_count": len(skipped_mgr),
                "rejection_breakdown": {}
            }

        win_rate = (len(wins) / n) * 100.0
        gross_profit = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        net_pnl = sum(t["pnl_usd"] for t in trades)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        total_r = sum(t["pnl_r"] for t in trades)
        
        peak_r = 0.0
        cur_r = 0.0
        max_dd_r = 0.0

        equity_curve = [self.initial_balance]
        running_bal = self.initial_balance
        peak_bal = self.initial_balance
        max_dd_pct = 0.0

        for t in trades:
            cur_r += t["pnl_r"]
            peak_r = max(peak_r, cur_r)
            dd_r = peak_r - cur_r
            max_dd_r = max(max_dd_r, dd_r)

            running_bal += t["pnl_usd"]
            equity_curve.append(running_bal)
            peak_bal = max(peak_bal, running_bal)
            dd_pct = (peak_bal - running_bal) / peak_bal if peak_bal > 0 else 0.0
            max_dd_pct = max(max_dd_pct, dd_pct)

        r_eff = (total_r / max_dd_r) if max_dd_r > 0 else total_r
        total_return_pct = ((final_balance - self.initial_balance) / self.initial_balance) * 100.0
        fee_drag = (total_fees / gross_profit * 100.0) if gross_profit > 0 else 0.0

        rejection_breakdown = {}
        for s in skipped_mgr:
            r = s.get("reason", "Other")
            prefix = r.split(":")[0] if ":" in r else r
            rejection_breakdown[prefix] = rejection_breakdown.get(prefix, 0) + 1

        return {
            "total_trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "gross_profit_usd": round(gross_profit, 2),
            "gross_loss_usd": round(gross_loss, 2),
            "net_pnl_usd": round(net_pnl, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_r": round(total_r, 2),
            "max_drawdown_r": round(max_dd_r, 2),
            "r_efficiency": round(r_eff, 2),
            "max_drawdown_pct": round(max_dd_pct * 100.0, 2),
            "total_fees_usd": round(total_fees, 2),
            "fee_drag_pct": round(fee_drag, 2),
            "rejections_count": len(skipped_mgr),
            "rejection_breakdown": rejection_breakdown
        }

    def run_walk_forward_analysis(self) -> Dict[str, Any]:
        """
        Executes In-Sample (Jan-Aug 2026) Calibration & Out-of-Sample (Sep-Oct 2026) Validation.
        """
        in_sample_start = int(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        in_sample_end   = int(datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        out_sample_start= int(datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        out_sample_end  = int(datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp())

        print("\n" + "="*85)
        print("  STEP 1: IN-SAMPLE CALIBRATION (Jan 1, 2026 -> Aug 31, 2026 | 70% Dataset)")
        print("="*85)

        candidate_configs = [
            {"id": "Fixed 3.0R (Buffer 0.12%)", "fixed_rr": 3.0, "min_rr": 2.5, "use_buffer": True},
            {"id": "Fixed 2.5R (Buffer 0.12%)", "fixed_rr": 2.5, "min_rr": 2.5, "use_buffer": True},
            {"id": "Fixed 3.0R (No Buffer)",      "fixed_rr": 3.0, "min_rr": 2.5, "use_buffer": False},
            {"id": "Nearest Liq (Min 2.5R Floor)","fixed_rr": None, "min_rr": 2.5, "use_buffer": True}
        ]

        calibration_results = []
        best_cfg = None
        best_score = -9999999.0

        for cfg in candidate_configs:
            t0 = time.time()
            res = self.run_simulation(
                start_ts=in_sample_start,
                end_ts=in_sample_end,
                fixed_rr=cfg["fixed_rr"],
                min_rr=cfg["min_rr"],
                use_sl_buffer=cfg["use_buffer"]
            )
            elapsed = time.time() - t0
            m = res["metrics"]
            
            # Optimization score: prioritize highest Net R with sample size >= 10
            if m["total_trades"] >= 10:
                score = m["total_r"] * (m["profit_factor"] if m["profit_factor"] > 0 else 1.0)
            else:
                score = -999999.0
            cfg_res = {
                "config": cfg,
                "metrics": m,
                "score": score,
                "elapsed": elapsed
            }
            calibration_results.append(cfg_res)
            
            print(f"  -> [{cfg['id']:28s}] Trades: {m['total_trades']:2d} | WR: {m['win_rate_pct']:5.1f}% | PF: {m['profit_factor']:4.2f} | Net R: {m['total_r']:+6.1f}R | Net $: ${m['net_pnl_usd']:+8.2f} | MaxDD: {m['max_drawdown_pct']:4.1f}% | Time: {elapsed:.1f}s")

            if score > best_score:
                best_score = score
                best_cfg = cfg

        print("\n" + "="*85)
        print(f"  OPTIMAL IN-SAMPLE CONFIG SELECTED: {best_cfg['id']}")
        print("="*85)

        # -------------------------------------------------------------
        # STEP 2: OUT-OF-SAMPLE VALIDATION
        # -------------------------------------------------------------
        print("\n" + "="*85)
        print("  STEP 2: OUT-OF-SAMPLE BLIND AUDIT (Sep 1, 2026 -> Oct 31, 2026 | 30% Dataset)")
        print(f"  Enforcing calibrated parameter: {best_cfg['id']} (NO PARAMETER CHANGES)")
        print("="*85)

        t0 = time.time()
        oos_res = self.run_simulation(
            start_ts=out_sample_start,
            end_ts=out_sample_end,
            fixed_rr=best_cfg["fixed_rr"],
            min_rr=best_cfg["min_rr"],
            use_sl_buffer=best_cfg["use_buffer"]
        )
        oos_elapsed = time.time() - t0
        oos_m = oos_res["metrics"]

        # Walk-Forward Efficiency (WFE)
        is_best_m = next(c["metrics"] for c in calibration_results if c["config"]["id"] == best_cfg["id"])
        is_monthly_r = is_best_m["total_r"] / 8.0
        oos_monthly_r = oos_m["total_r"] / 2.0
        wfe = (oos_monthly_r / is_monthly_r) if is_monthly_r > 0 else (1.0 if oos_monthly_r > 0 else 0.0)

        print(f"  -> Out-of-Sample Results:")
        print(f"     Trades:          {oos_m['total_trades']}")
        print(f"     Win Rate:        {oos_m['win_rate_pct']}% ({oos_m['wins']}W / {oos_m['losses']}L)")
        print(f"     Profit Factor:   {oos_m['profit_factor']}")
        print(f"     Net PnL:         ${oos_m['net_pnl_usd']:+,.2f} ({oos_m['total_return_pct']:+.1f}%)")
        print(f"     Net R Generated: {oos_m['total_r']:+,.1f}R")
        print(f"     Max Drawdown:    {oos_m['max_drawdown_pct']}% ({oos_m['max_drawdown_r']}R)")
        print(f"     R-Efficiency:    {oos_m['r_efficiency']}")
        print(f"     Fees & Funding:  ${oos_m['total_fees_usd']:,.2f} (Fee Drag: {oos_m['fee_drag_pct']}%)")
        print(f"     Risk Rejections: {oos_m['rejections_count']}")
        print(f"     WFE Ratio:       {wfe:.2f} (Target >= 0.60)")
        print("="*85 + "\n")

        return {
            "calibration_results": calibration_results,
            "best_config": best_cfg,
            "in_sample_metrics": is_best_m,
            "out_of_sample_metrics": oos_m,
            "out_of_sample_trades": oos_res["trades"],
            "walk_forward_efficiency": round(wfe, 2)
        }

if __name__ == "__main__":
    engine = AuditBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m", initial_balance=10000.0)
    engine.run_walk_forward_analysis()
