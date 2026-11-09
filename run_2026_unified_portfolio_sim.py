"""
Unified 2026 Multi-Asset Portfolio Simulation (Binance Futures + Exness Forex & Gold)
=====================================================================================
Period: January 1, 2026 00:00:00 UTC to October 31, 2026 23:59:59 UTC (10 Months)
Starting Balance: $1,000.00
Risk: 1.0% Compounded Per Trade

Assets (10 Total):
  - Binance Futures:
      1. BTCUSDT
      2. SOLUSDT
      3. PAXGUSDT (Gold Futures on Binance)
  - Exness Forex & Metals:
      4. EURUSD
      5. GBPUSD
      6. USDJPY
      7. USDCAD
      8. AUDUSD
      9. NZDUSD
      10. GBPJPY

Timeframe Matrix:
  - 4h HTF -> 5m LTF (Fixed 3.0R TP)
  - 1h HTF -> 1m LTF (Nearest HTF Liquidity TP >= 2.5R)
  - 15m HTF -> 1m LTF (Nearest HTF Liquidity TP >= 2.5R)

Production Engine Rules Enforced:
  - Causal HTF Zone Formation & Strict 2-Close Mitigation
  - 1 Trade Per HTF Level (Consumed Zones)
  - Candlestick Confirmation (Bullish/Bearish Engulfing or Morning/Evening Star)
  - A+ (Dual CHoCH) ELIMINATED
  - 0.5 * ATR_15M Stop Loss Cushion
  - Anti-Cannibalization (Max 1 concurrent open trade per symbol)
  - Factor 3 Drawdown Throttling (Halves risk to 0.5% if drawdown >= 8.0%)
  - Exchange Commissions & Adverse Slippage
"""
import os
import sys
import json
import time
import math
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from universal_multi_asset_backtest import UniversalBacktestEngine

SYMBOLS = [
    # Binance Futures
    "BTCUSDT", "SOLUSDT", "PAXGUSDT",
    # Exness Forex & Metals
    "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "NZDUSD", "GBPJPY"
]

TIMEFRAME_MATRIX = [
    {"htf": "4h", "ltf": "5m", "fixed_rr": 3.0, "min_rr": 3.0},
    {"htf": "1h", "ltf": "1m", "fixed_rr": None, "min_rr": 2.5},
    {"htf": "15m", "ltf": "1m", "fixed_rr": None, "min_rr": 2.5}
]

def _worker_run(item):
    symbol, htf_name, ltf_name, fixed_rr, min_rr, start_ts, end_ts = item
    
    # Specific commission / slippage per venue
    if symbol in ["BTCUSDT", "SOLUSDT", "PAXGUSDT"]:
        maker_fee = 0.0002
        taker_fee = 0.0005
        slippage = 0.0005
    else:
        maker_fee = 0.0001
        taker_fee = 0.0002
        slippage = 0.0001

    engine = UniversalBacktestEngine(
        symbols=symbol,
        initial_balance=1000.0,
        risk_per_trade_pct=0.01,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        slippage_pct=slippage
    )
    trades = engine.run_pair(
        symbol=symbol,
        htf_name=htf_name,
        ltf_name=ltf_name,
        start_ts=start_ts,
        end_ts=end_ts,
        fixed_rr=fixed_rr,
        min_rr=min_rr
    )
    for t in trades:
        t["exchange"] = "Binance Futures" if symbol in ["BTCUSDT", "SOLUSDT", "PAXGUSDT"] else "Exness"
        dt = datetime.fromtimestamp(t["entry_time"], timezone.utc)
        t["month_str"] = dt.strftime("%Y-%m")
        t["month_name"] = dt.strftime("%B %Y")
    return symbol, f"{htf_name}_{ltf_name}", trades

def simulate_portfolio_execution(raw_trades: list, initial_balance: float = 1000.0, throttle_enabled: bool = True):
    # Sort strictly chronologically by entry_time
    raw_trades.sort(key=lambda x: x["entry_time"])

    # Active positions simulation
    active_positions = []  # list of open trades
    executed_trades = []
    
    balance = initial_balance
    peak_balance = initial_balance
    max_dd_pct = 0.0
    max_dd_dollars = 0.0

    # Equity curve tracking
    equity_curve = [{"time": raw_trades[0]["entry_time"] if raw_trades else 0, "balance": balance, "dd_pct": 0.0}]

    for trade in raw_trades:
        e_time = trade["entry_time"]
        sym = trade["symbol"]

        # Step 1: Close out any positions whose exit_time <= current entry_time
        still_open = []
        for pos in active_positions:
            if pos["exit_time"] <= e_time:
                # Position concluded! Realize PnL
                pos_risk_dollars = pos["allocated_risk_dollars"]
                pnl_r = pos["pnl_r"]
                
                # Deduct transaction fee / slippage
                fee_mult = 0.0006 if pos["exchange"] == "Binance Futures" else 0.0002
                fee_cost = pos["entry_price"] * fee_mult * (pos_risk_dollars / pos["risk"]) if pos["risk"] > 0 else 0
                
                if pos["outcome"] == "WIN":
                    net_profit = (pos_risk_dollars * pnl_r) - fee_cost
                else:
                    net_profit = (-pos_risk_dollars) - fee_cost

                balance += net_profit
                pos["realized_pnl_dollars"] = round(net_profit, 2)
                pos["portfolio_balance_after"] = round(balance, 2)
                
                if balance > peak_balance:
                    peak_balance = balance
                
                dd_dollars = peak_balance - balance
                dd_pct = (dd_dollars / peak_balance * 100.0) if peak_balance > 0 else 0.0
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct
                    max_dd_dollars = dd_dollars

                pos["peak_balance_at_exit"] = round(peak_balance, 2)
                pos["drawdown_pct_at_exit"] = round(dd_pct, 2)
                executed_trades.append(pos)
                equity_curve.append({"time": pos["exit_time"], "balance": round(balance, 2), "dd_pct": round(dd_pct, 2)})
            else:
                still_open.append(pos)
        active_positions = still_open

        # Step 2: Risk Management Gatekeepers
        # Rule A: Anti-Cannibalization (Max 1 position per symbol at a time)
        symbol_already_open = any(p["symbol"] == sym for p in active_positions)
        if symbol_already_open:
            trade["status"] = "REJECTED_SYMBOL_ALREADY_OPEN"
            continue

        # Rule B: Max Concurrent Portfolio Positions (e.g. 5 concurrent slots)
        if len(active_positions) >= 5:
            trade["status"] = "REJECTED_MAX_SLOTS_REACHED"
            continue

        # Rule C: Factor 3 Drawdown Throttling
        current_dd = (peak_balance - balance) / peak_balance if peak_balance > 0 else 0.0
        if throttle_enabled and current_dd >= 0.08:
            risk_pct = 0.005  # Halved to 0.5%
            trade["throttled"] = True
        else:
            risk_pct = 0.010  # Standard 1.0%
            trade["throttled"] = False

        # Allocate Risk
        trade_risk_dollars = balance * risk_pct
        trade["allocated_risk_dollars"] = trade_risk_dollars
        trade["portfolio_balance_at_entry"] = round(balance, 2)
        active_positions.append(trade)

    # Close remaining positions at end
    for pos in active_positions:
        pos_risk_dollars = pos["allocated_risk_dollars"]
        pnl_r = pos["pnl_r"]
        fee_mult = 0.0006 if pos["exchange"] == "Binance Futures" else 0.0002
        fee_cost = pos["entry_price"] * fee_mult * (pos_risk_dollars / pos["risk"]) if pos["risk"] > 0 else 0
        if pos["outcome"] == "WIN":
            net_profit = (pos_risk_dollars * pnl_r) - fee_cost
        else:
            net_profit = (-pos_risk_dollars) - fee_cost
        balance += net_profit
        pos["realized_pnl_dollars"] = round(net_profit, 2)
        pos["portfolio_balance_after"] = round(balance, 2)
        if balance > peak_balance:
            peak_balance = balance
        dd_pct = ((peak_balance - balance) / peak_balance * 100.0) if peak_balance > 0 else 0.0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_dollars = peak_balance - balance
        executed_trades.append(pos)
        equity_curve.append({"time": pos["exit_time"], "balance": round(balance, 2), "dd_pct": round(dd_pct, 2)})

    executed_trades.sort(key=lambda x: x["exit_time"])
    return executed_trades, balance, max_dd_pct, max_dd_dollars, equity_curve

def main():
    print("=" * 80)
    print(" 2026 UNIFIED MULTI-ASSET PORTFOLIO SIMULATION (10 ASSETS)")
    print(" Binance: BTCUSDT, SOLUSDT, PAXGUSDT | Exness: 7 Major FX Pairs")
    print(" Period: 2026-01-01 to 2026-10-31 | Start Balance: $1,000.00 | Risk: 1% Compounded")
    print("=" * 80)

    start_ts = int(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp())

    tasks = []
    for sym in SYMBOLS:
        for cfg in TIMEFRAME_MATRIX:
            tasks.append((sym, cfg["htf"], cfg["ltf"], cfg["fixed_rr"], cfg["min_rr"], start_ts, end_ts))

    print(f"Running {len(tasks)} tasks across 8 CPU worker processes...", flush=True)
    t0 = time.time()

    all_raw_trades = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_worker_run, task): task for task in tasks}
        completed = 0
        for fut in as_completed(futures):
            completed += 1
            sym, tf_str, trades = fut.result()
            all_raw_trades.extend(trades)
            print(f"[{completed:2d}/{len(tasks)}] {sym:<8} {tf_str:<6}: {len(trades):3d} raw trade signals", flush=True)

    print(f"\nAll trade generation completed in {time.time()-t0:.1f}s. Total candidate signals: {len(all_raw_trades)}")

    # Execute Portfolio Simulation with strict slot & risk management
    print("\nExecuting chronological Portfolio Risk Manager simulation...", flush=True)
    executed_trades, final_balance, max_dd_pct, max_dd_dollars, equity_curve = simulate_portfolio_execution(
        all_raw_trades, initial_balance=1000.0, throttle_enabled=True
    )

    print(f"Executed Trades after portfolio concurrency & slot filters: {len(executed_trades)}")

    # Month by month aggregation
    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    month_data = []
    
    # We will track month start and end balances
    current_b = 1000.0
    for m in months:
        m_trades = [t for t in executed_trades if t.get("month_str") == m]
        m_start = current_b
        m_wins = len([t for t in m_trades if t["outcome"] == "WIN"])
        m_losses = len([t for t in m_trades if t["outcome"] == "LOSS"])
        m_pnl_r = sum(t.get("pnl_r", 0) for t in m_trades)
        m_pnl_dollars = sum(t.get("realized_pnl_dollars", 0) for t in m_trades)
        
        # Calculate monthly peak and max drawdown within the month
        m_peak = m_start
        m_max_dd = 0.0
        running_b = m_start
        for t in m_trades:
            running_b += t.get("realized_pnl_dollars", 0)
            if running_b > m_peak:
                m_peak = running_b
            dd = (m_peak - running_b) / m_peak * 100.0 if m_peak > 0 else 0.0
            if dd > m_max_dd:
                m_max_dd = dd

        m_end = m_start + m_pnl_dollars
        m_roi = ((m_end - m_start) / m_start * 100.0) if m_start > 0 else 0.0
        current_b = m_end
        
        dt_obj = datetime.strptime(m, "%Y-%m")
        month_data.append({
            "month": m,
            "month_name": dt_obj.strftime("%B %Y"),
            "trades": len(m_trades),
            "wins": m_wins,
            "losses": m_losses,
            "win_rate": round(m_wins / len(m_trades) * 100.0, 2) if m_trades else 0.0,
            "net_r": round(m_pnl_r, 2),
            "start_balance": round(m_start, 2),
            "end_balance": round(m_end, 2),
            "profit_dollars": round(m_pnl_dollars, 2),
            "monthly_roi_pct": round(m_roi, 2),
            "monthly_max_dd_pct": round(m_max_dd, 2)
        })

    # Summary by Symbol
    sym_summary = {}
    for s in SYMBOLS:
        s_trades = [t for t in executed_trades if t["symbol"] == s]
        s_wins = len([t for t in s_trades if t["outcome"] == "WIN"])
        s_losses = len([t for t in s_trades if t["outcome"] == "LOSS"])
        s_pnl_r = sum(t.get("pnl_r", 0) for t in s_trades)
        s_pnl_dollars = sum(t.get("realized_pnl_dollars", 0) for t in s_trades)
        s_wr = (s_wins / len(s_trades) * 100.0) if s_trades else 0.0
        venue = "Binance Futures" if s in ["BTCUSDT", "SOLUSDT", "PAXGUSDT"] else "Exness"
        sym_summary[s] = {
            "venue": venue,
            "trades": len(s_trades),
            "wins": s_wins,
            "losses": s_losses,
            "win_rate": round(s_wr, 2),
            "net_r": round(s_pnl_r, 2),
            "realized_profit": round(s_pnl_dollars, 2)
        }

    # Summary by Level Category
    cat_summary = {}
    for c in ["Double Top/Bottom (Single CHoCH)", "TJL2 (BOS)", "TJL1 (BOS)", "QML (Single CHoCH)", "SBR / RBS (Dual CHoCH)", "A+ (Dual CHoCH)"]:
        c_trades = [t for t in executed_trades if t.get("level_category") == c]
        c_wins = len([t for t in c_trades if t["outcome"] == "WIN"])
        c_losses = len([t for t in c_trades if t["outcome"] == "LOSS"])
        c_wr = (c_wins / len(c_trades) * 100.0) if c_trades else 0.0
        c_r = sum(t.get("pnl_r", 0) for t in c_trades)
        cat_summary[c] = {
            "trades": len(c_trades),
            "wins": c_wins,
            "losses": c_losses,
            "win_rate": round(c_wr, 2),
            "net_r": round(c_r, 2)
        }

    out = {
        "config": {
            "start_date": "2026-01-01",
            "end_date": "2026-10-31",
            "initial_balance": 1000.0,
            "final_balance": round(final_balance, 2),
            "total_net_profit": round(final_balance - 1000.0, 2),
            "total_roi_pct": round((final_balance - 1000.0) / 1000.0 * 100.0, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "max_drawdown_dollars": round(max_dd_dollars, 2),
            "total_trades": len(executed_trades),
            "wins": len([t for t in executed_trades if t["outcome"] == "WIN"]),
            "losses": len([t for t in executed_trades if t["outcome"] == "LOSS"]),
            "overall_win_rate": round(len([t for t in executed_trades if t["outcome"] == "WIN"]) / len(executed_trades) * 100.0, 2) if executed_trades else 0.0,
            "overall_net_r": round(sum(t.get("pnl_r", 0) for t in executed_trades), 2)
        },
        "monthly_breakdown": month_data,
        "by_symbol": sym_summary,
        "by_level_category": cat_summary,
        "executed_trades": executed_trades
    }

    out_file = os.path.join(BASE_DIR, "data", "unified_2026_portfolio_simulation.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\n[SAVED] Full report saved to: {out_file}")

    csv_file = os.path.join(BASE_DIR, "data", "unified_2026_portfolio_trades.csv")
    pd.DataFrame(executed_trades).to_csv(csv_file, index=False)
    print(f"[SAVED] Trades CSV saved to: {csv_file}")

    print("\n" + "=" * 80)
    print(" MONTH-BY-MONTH PORTFOLIO RETURNS (Jan 2026 - Oct 2026)")
    print("=" * 80)
    for m in month_data:
        print(f"{m['month_name']:<15} | Trades: {m['trades']:<3} | WinRate: {m['win_rate']:>5.2f}% | Net R: {m['net_r']:>+6.2f}R | Start: ${m['start_balance']:>9.2f} | End: ${m['end_balance']:>9.2f} | Monthly ROI: {m['monthly_roi_pct']:>+6.2f}% | Max DD: {m['monthly_max_dd_pct']:>5.2f}%")

    print("\n" + "=" * 80)
    print(" PORTFOLIO OVERALL TOTALS")
    print("=" * 80)
    cfg = out["config"]
    print(f"Initial Capital:    $1,000.00")
    print(f"Final Balance:      ${cfg['final_balance']:,.2f} ({cfg['total_roi_pct']:+,.2f}%)")
    print(f"Max Portfolio DD:   {cfg['max_drawdown_pct']:.2f}% (${cfg['max_drawdown_dollars']:,.2f})")
    print(f"Total Trades:       {cfg['total_trades']} (Wins: {cfg['wins']}, Losses: {cfg['losses']}, WinRate: {cfg['overall_win_rate']}%)")
    print(f"Total Net R:        {cfg['overall_net_r']:+.2f}R")

if __name__ == "__main__":
    main()
