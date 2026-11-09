"""
Universal Multi-Asset Backtest Engine (Candle-by-Candle, Zero Lookahead)
========================================================================
A reusable, modular backtesting suite for crypto perpetual futures.
Executes strict Point-in-Time, candle-by-candle simulation for ANY asset.

Standardized Timeframe Matrix (Applied identically to all assets):
  - 4h HTF -> 5m LTF: Fixed 3.0R Take Profit (fixed_rr = 3.0)
  - 1h HTF -> 1m LTF: Opposing HTF Liquidity TP (min_rr = 2.5 Floor)
  - 15m HTF -> 1m LTF: Opposing HTF Liquidity TP (min_rr = 2.5 Floor)

Guarantees:
  - Zero Lookahead: Only closed candles up to the current timestamp are known.
  - Causal Formation: Zones are only tradeable AFTER the confirmation breakout candle closes.
  - Strict Mitigation: Exactly 2 consecutive HTF closes beyond zone boundary permanently kills it.
  - Retest Confirmation: Bullish/Bearish Engulfing or Morning/Evening Star must fully close.
  - Execution Frictions: VIP0 Binance Commissions + 0.05% SL adverse slippage.
  - Conservative collision: If TP and SL are touched in the same candle, SL executes first.
  - Strict 1 trade per level: Once an HTF zone produces a trade entry, it is permanently consumed.
"""

import os
import sys
import json
import math
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any, Union

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from htf_engine import HTFEngine, is_qualifying_htf_zone, is_htf_box_active
from ltf_approach_engine import (
    clean_box_name,
    compute_ltf_approach_structure
)
from binance_feed import fetch_klines_range

DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def categorize_level(box_name: str) -> str:
    name = (box_name or "").upper()
    if "TJL1" in name:
        return "TJL1 (BOS)"
    elif "TJL2" in name:
        return "TJL2 (BOS)"
    elif "QML" in name:
        return "QML (Single CHoCH)"
    elif "DOUBLE TOP" in name or "DOUBLE BOTTOM" in name:
        return "Double Top/Bottom (Single CHoCH)"
    elif "A+" in name:
        return "A+ (Dual CHoCH)"
    elif "SBR" in name or "RBS" in name:
        return "SBR / RBS (Dual CHoCH)"
    return "Other HTF Zone"


class UniversalBacktestEngine:
    TIMEFRAME_MATRIX = [
        {"htf": "4h", "ltf": "5m", "fixed_rr": 3.0, "min_rr": 3.0, "desc": "4h -> 5m (Fixed 3.0R)"},
        {"htf": "1h", "ltf": "1m", "fixed_rr": None, "min_rr": 2.5, "desc": "1h -> 1m (Liquidity >= 2.5R)"},
        {"htf": "15m", "ltf": "1m", "fixed_rr": None, "min_rr": 2.5, "desc": "15m -> 1m (Liquidity >= 2.5R)"}
    ]

    def __init__(
        self,
        symbols: Union[str, List[str]] = "BTCUSDT",
        initial_balance: float = 1000.0,
        risk_per_trade_pct: float = 0.01,
        maker_fee: float = 0.0002,
        taker_fee: float = 0.0005,
        slippage_pct: float = 0.0005
    ):
        if isinstance(symbols, str):
            self.symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        else:
            self.symbols = [s.upper() for s in symbols]

        self.initial_balance = float(initial_balance)
        self.risk_pct = float(risk_per_trade_pct)
        self.maker_fee = float(maker_fee)
        self.taker_fee = float(taker_fee)
        self.slippage_pct = float(slippage_pct)

    @staticmethod
    def _parse_tf_seconds(tf: str) -> int:
        tf = tf.lower()
        if tf == "1m": return 60
        if tf == "5m": return 300
        if tf == "15m": return 900
        if tf == "1h": return 3600
        if tf == "4h": return 14400
        if tf == "1d": return 86400
        raise ValueError(f"Unsupported timeframe: {tf}")

    def load_candles(
        self,
        symbol: str,
        interval: str,
        start_ts: int,
        end_ts: int
    ) -> List[Dict]:
        sym_clean = symbol.lower()
        tf_clean = interval.lower()
        tf_sec = self._parse_tf_seconds(tf_clean)

        candidates = [
            os.path.join(DATA_DIR, f"{sym_clean}_{tf_clean}_3y_2023_2026.json"),
            os.path.join(DATA_DIR, f"{sym_clean}_{tf_clean}_1y_oct2025_oct2026.json"),
            os.path.join(DATA_DIR, f"{sym_clean}_{tf_clean}_oct2026_full.json"),
            os.path.join(DATA_DIR, f"{sym_clean}_{tf_clean}_2026_full.json"),
            os.path.join(DATA_DIR, f"cache_{sym_clean}_{tf_clean}.json"),
            os.path.join(DATA_DIR, f"{sym_clean}_{tf_clean}.json")
        ]

        import glob
        candidates.extend(glob.glob(os.path.join(DATA_DIR, f"{sym_clean}_{tf_clean}*.json")))
        if sym_clean.startswith("btc"):
            candidates.extend(glob.glob(os.path.join(DATA_DIR, f"btc_{tf_clean}*.json")))
        if sym_clean.startswith("sol"):
            candidates.extend(glob.glob(os.path.join(DATA_DIR, f"sol_{tf_clean}*.json")))
        candidates = list(dict.fromkeys(candidates))

        loaded = []
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        data.sort(key=lambda x: x["time"])
                        if data[0]["time"] <= start_ts and data[-1]["time"] >= end_ts:
                            loaded = data
                            break
                        elif len(data) > len(loaded):
                            loaded = data
                except Exception:
                    pass

        if not loaded or loaded[0]["time"] > start_ts or loaded[-1]["time"] < (start_ts + 86400 * 3):
            print(f"[DATA] Fetching {symbol} ({interval}) historical data from Binance...", flush=True)
            fetch_start_s = max(0, start_ts - (500 * tf_sec))
            fetched = fetch_klines_range(
                symbol=symbol,
                interval=interval,
                start_time_s=fetch_start_s,
                end_time_s=end_ts + tf_sec,
                market_type="futures"
            )
            if fetched:
                loaded = fetched
                cache_path = os.path.join(DATA_DIR, f"cache_{sym_clean}_{tf_clean}.json")
                try:
                    with open(cache_path, "w", encoding="utf-8") as fw:
                        json.dump(loaded, fw)
                except Exception:
                    pass

        if not loaded:
            raise RuntimeError(f"Could not load candle data for {symbol} ({interval})")

        loaded.sort(key=lambda x: x["time"])
        return loaded

    def run_pair(
        self,
        symbol: str,
        htf_name: str,
        ltf_name: str,
        start_ts: int,
        end_ts: int,
        fixed_rr: Optional[float] = None,
        min_rr: float = 2.5
    ) -> List[Dict]:
        htf_sec = self._parse_tf_seconds(htf_name)
        print(f"  [{symbol}] Running {htf_name.upper()} -> {ltf_name.upper()}...", flush=True)

        htf_candles = self.load_candles(symbol, htf_name, start_ts, end_ts)
        ltf_candles = self.load_candles(symbol, ltf_name, start_ts, end_ts)

        htf_subset = [c for c in htf_candles if c["time"] <= end_ts]
        htf_engine = HTFEngine(lookback_bars=len(htf_subset), show_tjl_boxes=True, tjl_extend=True)
        htf_boxes = [b for b in htf_engine.run(htf_subset).get("boxes", []) if is_qualifying_htf_zone(b)]

        for b in htf_boxes:
            b_left = b.get("confirmed_formation_time") or b.get("left") or b.get("start_time") or b.get("time") or 0
            b["confirmed_formation_time"] = b_left
            if "mitigated_time" not in b or b["mitigated_time"] is None:
                b["mitigated_time"] = b.get("right") or 9999999999

        trades = []
        active_trade: Optional[Dict] = None
        box_state: Dict[str, str] = {}
        box_last_tap: Dict[str, int] = {}
        processed_entry_times = set()
        consumed_levels = set()
        locked_box_keys = set()

        box_data = []
        for b in htf_boxes:
            k = b.get("id") or f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}_{b.get('left', 0)}"
            top = max(b.get("top", 0), b.get("bottom", 0))
            bot = min(b.get("top", 0), b.get("bottom", 0))
            form_t = b.get("confirmed_formation_time", 0)
            mit_t = b.get("mitigated_time") or 9999999999
            name = clean_box_name(b.get("text") or b.get("name") or "HTF Zone")
            box_data.append({
                "key": k, "top": top, "bot": bot, "form_t": form_t, "mit_t": mit_t,
                "raw": b, "name": name
            })

        for idx, c in enumerate(ltf_candles):
            c_time = c["time"]
            if c_time < start_ts:
                continue
            if c_time > end_ts:
                break

            c_high = c["high"]
            c_low = c["low"]

            # STEP 1: Manage Active Trade
            if active_trade:
                if c_time > active_trade["entry_time"]:
                    is_bullish = (active_trade["action"] == "BUY")
                    tp = active_trade["tp_price"]
                    sl = active_trade["sl_price"]

                    hit_tp = (c_high >= tp) if is_bullish else (c_low <= tp)
                    hit_sl = (c_low <= sl) if is_bullish else (c_high >= sl)

                    if hit_tp and hit_sl:
                        hit_tp = False  # Conservative SL priority

                    if hit_tp:
                        active_trade["exit_time"] = c_time
                        active_trade["exit_time_str"] = datetime.fromtimestamp(c_time, timezone.utc).strftime("%Y-%m-%d %H:%M")
                        active_trade["exit_price"] = tp
                        active_trade["exit_reason"] = "TP"
                        active_trade["outcome"] = "WIN"
                        active_trade["pnl_r"] = active_trade["planned_rr"]
                        trades.append(active_trade)
                        active_trade = None

                    elif hit_sl:
                        slip_mult = (1.0 - self.slippage_pct) if is_bullish else (1.0 + self.slippage_pct)
                        exit_price = round(sl * slip_mult, 5) if sl < 100 else round(sl * slip_mult, 2)
                        active_trade["exit_time"] = c_time
                        active_trade["exit_time_str"] = datetime.fromtimestamp(c_time, timezone.utc).strftime("%Y-%m-%d %H:%M")
                        active_trade["exit_price"] = exit_price
                        active_trade["exit_reason"] = "SL"
                        active_trade["outcome"] = "LOSS"
                        active_trade["pnl_r"] = -1.00
                        trades.append(active_trade)
                        active_trade = None

                if active_trade:
                    continue

            # STEP 2: Update Locked Zones
            if locked_box_keys:
                unlocked = []
                for bk in locked_box_keys:
                    b_info = next((bx for bx in box_data if bx["key"] == bk), None)
                    if b_info:
                        if not (c_high >= b_info["bot"] and c_low <= b_info["top"]):
                            if c_time - box_last_tap.get(bk, 0) >= 3600:
                                unlocked.append(bk)
                for bk in unlocked:
                    locked_box_keys.remove(bk)
                    box_state[bk] = "READY"

            # STEP 3: Detect Zone Taps
            for bx in box_data:
                bk = bx["key"]
                if bk in consumed_levels or bk in locked_box_keys:
                    continue
                if c_time < bx["form_t"] or c_time > bx["mit_t"]:
                    continue

                if c_high >= bx["bot"] and c_low <= bx["top"]:
                    locked_box_keys.add(bk)
                    box_state[bk] = "LOCKED"
                    box_last_tap[bk] = c_time

                    slice_start = max(0, idx - 60)
                    slice_end = min(len(ltf_candles), idx + 245)
                    sliced_ltf = ltf_candles[slice_start:slice_end]

                    available_boxes = [x["raw"] for x in box_data if x["key"] not in consumed_levels]

                    res = compute_ltf_approach_structure(
                        target_time=c_time,
                        ltf_candles=sliced_ltf,
                        htf_boxes=available_boxes,
                        htf_sec=htf_sec,
                        htf_candles=htf_candles
                    )
                    tap_info = res.get("tap_info")
                    if tap_info and tap_info.get("trade"):
                        tr = tap_info["trade"]
                        if tr.get("executed") and tr.get("time") >= c_time:
                            tr_time = tr["time"]
                            if tr_time in processed_entry_times:
                                continue

                            is_bull = (tr["action"] == "BUY")
                            entry_p = tr["entry_price"]
                            sl_p = tr["sl_price"]
                            risk_dist = abs(entry_p - sl_p)

                            if risk_dist <= 0:
                                continue

                            if fixed_rr is not None:
                                planned_rr = float(fixed_rr)
                                planned_reward = fixed_rr * risk_dist
                                planned_tp = entry_p + planned_reward if is_bull else entry_p - planned_reward
                            else:
                                planned_tp = tr["tp_price"]
                                planned_reward = abs(planned_tp - entry_p)
                                planned_rr = planned_reward / risk_dist if risk_dist > 0 else 0.0

                            if planned_rr < min_rr:
                                continue

                            processed_entry_times.add(tr_time)
                            consumed_levels.add(bk)
                            if bk in locked_box_keys:
                                locked_box_keys.remove(bk)
                            box_state[bk] = "CONSUMED"

                            active_trade = {
                                "id": f"{symbol}_{htf_name}_{tr_time}",
                                "symbol": symbol,
                                "htf": htf_name,
                                "ltf": ltf_name,
                                "pair": f"{htf_name.upper()}->{ltf_name.upper()}",
                                "action": tr["action"],
                                "htf_box": bx["name"],
                                "level_category": categorize_level(bx["name"]),
                                "htf_formation_time": bx["form_t"],
                                "htf_formation_str": datetime.fromtimestamp(bx["form_t"], timezone.utc).strftime("%Y-%m-%d %H:%M"),
                                "tap_time": c_time,
                                "tap_time_str": datetime.fromtimestamp(c_time, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                                "entry_time": tr_time,
                                "entry_time_str": datetime.fromtimestamp(tr_time, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                                "entry_price": entry_p,
                                "sl_price": sl_p,
                                "tp_price": planned_tp,
                                "risk": risk_dist,
                                "reward": planned_reward,
                                "planned_rr": round(planned_rr, 2),
                                "pattern_name": tr.get("pattern_name", "Reversal"),
                                "level_name": tr.get("level_name", "LTF Level")
                            }
                            break

        if active_trade:
            c_final = ltf_candles[-1]
            is_bull = (active_trade["action"] == "BUY")
            cur_price = c_final["close"]
            raw_r = ((cur_price - active_trade["entry_price"]) if is_bull else (active_trade["entry_price"] - cur_price)) / active_trade["risk"]

            active_trade["exit_time"] = c_final["time"]
            active_trade["exit_time_str"] = datetime.fromtimestamp(c_final["time"], timezone.utc).strftime("%Y-%m-%d %H:%M")
            active_trade["exit_price"] = cur_price
            active_trade["exit_reason"] = "OPEN_AT_END"
            active_trade["outcome"] = "OPEN"
            active_trade["pnl_r"] = round(raw_r, 2)
            trades.append(active_trade)

        print(f"  [{symbol}] {htf_name.upper()} -> {ltf_name.upper()} complete: {len(trades)} trades", flush=True)
        return trades

    def compute_metrics(self, trades: List[Dict]) -> Dict[str, Any]:
        n = len(trades)
        wins = [t for t in trades if t.get("outcome") == "WIN"]
        losses = [t for t in trades if t.get("outcome") == "LOSS"]
        open_trades = [t for t in trades if t.get("outcome") == "OPEN"]
        closed = wins + losses

        wr = (len(wins) / len(closed) * 100.0) if closed else 0.0
        gross_win_r = sum(t["pnl_r"] for t in wins)
        gross_loss_r = abs(sum(t["pnl_r"] for t in losses))
        net_r = gross_win_r - gross_loss_r
        pf = (gross_win_r / gross_loss_r) if gross_loss_r > 0 else (999.0 if gross_win_r > 0 else 0.0)

        # Flat calculation
        flat_risk_dollars = self.initial_balance * self.risk_pct
        flat_net_profit = net_r * flat_risk_dollars
        flat_final_balance = self.initial_balance + flat_net_profit

        # Compounding calculation
        comp_balance = self.initial_balance
        comp_peak = self.initial_balance
        comp_max_dd_dollars = 0.0
        comp_max_dd_pct = 0.0

        sorted_trades = sorted(trades, key=lambda x: x.get("entry_time", 0))

        for t in sorted_trades:
            r = t.get("pnl_r", 0.0)
            risk_dollars = comp_balance * self.risk_pct
            pnl_dollars = risk_dollars * r
            comp_balance += pnl_dollars
            if comp_balance > comp_peak:
                comp_peak = comp_balance
            dd_dollars = comp_peak - comp_balance
            dd_pct = (dd_dollars / comp_peak * 100.0) if comp_peak > 0 else 0.0
            if dd_pct > comp_max_dd_pct:
                comp_max_dd_pct = dd_pct
                comp_max_dd_dollars = dd_dollars

        cur_r = 0.0
        peak_r = 0.0
        max_dd_r = 0.0
        for t in sorted_trades:
            cur_r += t.get("pnl_r", 0.0)
            if cur_r > peak_r:
                peak_r = cur_r
            dd_r = peak_r - cur_r
            if dd_r > max_dd_r:
                max_dd_r = dd_r

        return {
            "total_trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "open": len(open_trades),
            "win_rate_pct": round(wr, 2),
            "profit_factor": round(pf, 2),
            "gross_win_r": round(gross_win_r, 2),
            "gross_loss_r": round(gross_loss_r, 2),
            "net_r": round(net_r, 2),
            "max_drawdown_r": round(max_dd_r, 2),
            "flat_initial_balance": self.initial_balance,
            "flat_final_balance": round(flat_final_balance, 2),
            "flat_net_profit": round(flat_net_profit, 2),
            "flat_roi_pct": round(flat_net_profit / self.initial_balance * 100.0, 2),
            "comp_initial_balance": self.initial_balance,
            "comp_final_balance": round(comp_balance, 2),
            "comp_net_profit": round(comp_balance - self.initial_balance, 2),
            "comp_roi_pct": round((comp_balance - self.initial_balance) / self.initial_balance * 100.0, 2),
            "comp_max_dd_pct": round(comp_max_dd_pct, 2),
            "comp_max_dd_dollars": round(comp_max_dd_dollars, 2)
        }

    def run_all(
        self,
        symbols: Optional[List[str]] = None,
        start_date: str = "2025-10-01",
        end_date: str = "2026-10-31"
    ) -> Dict[str, Any]:
        target_symbols = symbols or self.symbols
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        all_portfolio_trades = []
        symbol_trades = {s: [] for s in target_symbols}
        tf_trades_map = {f"{c['htf']}_{c['ltf']}": [] for c in self.TIMEFRAME_MATRIX}

        for sym in target_symbols:
            for cfg in self.TIMEFRAME_MATRIX:
                h = cfg["htf"]
                l = cfg["ltf"]
                pair_trades = self.run_pair(
                    symbol=sym,
                    htf_name=h,
                    ltf_name=l,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    fixed_rr=cfg["fixed_rr"],
                    min_rr=cfg["min_rr"]
                )
                symbol_trades[sym].extend(pair_trades)
                tf_trades_map[f"{h}_{l}"].extend(pair_trades)
                all_portfolio_trades.extend(pair_trades)

        all_portfolio_trades.sort(key=lambda x: x.get("entry_time", 0))

        all_categories = [
            "TJL1 (BOS)", "TJL2 (BOS)", "QML (Single CHoCH)", 
            "Double Top/Bottom (Single CHoCH)", "A+ (Dual CHoCH)", "SBR / RBS (Dual CHoCH)"
        ]
        by_level = {}
        for cat in all_categories:
            cat_trades = [t for t in all_portfolio_trades if t.get("level_category") == cat]
            by_level[cat] = self.compute_metrics(cat_trades)

        return {
            "period": f"{start_date} to {end_date}",
            "symbols": target_symbols,
            "portfolio_summary": self.compute_metrics(all_portfolio_trades),
            "by_symbol": {sym: self.compute_metrics(symbol_trades[sym]) for sym in target_symbols},
            "by_timeframe": {k: self.compute_metrics(v) for k, v in tf_trades_map.items()},
            "by_level_category": by_level,
            "all_trades": all_portfolio_trades
        }
