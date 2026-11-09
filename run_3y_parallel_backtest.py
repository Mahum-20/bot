"""
Parallel 3-Year Multi-Asset Backtest & Forensic Loss Analyzer
============================================================
Assets (8 Pairs):
  1. XAUUSD (Gold)
  2. EURUSD
  3. GBPUSD
  4. USDJPY
  5. USDCAD
  6. AUDUSD
  7. NZDUSD
  8. GBPJPY

Timeframes:
  - 4h HTF -> 5m LTF (Fixed 3.0R TP)
  - 1h HTF -> 1m LTF (Nearest HTF Liquidity TP >= 2.5R)
  - 15m HTF -> 1m LTF (Nearest HTF Liquidity TP >= 2.5R)

Period: 2023-11-01 to 2026-10-31 (3 Full Years)
"""
import os
import sys
import json
import time
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from universal_multi_asset_backtest import UniversalBacktestEngine, categorize_level

SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "NZDUSD", "GBPJPY"]

TIMEFRAME_MATRIX = [
    {"htf": "4h", "ltf": "5m", "fixed_rr": 3.0, "min_rr": 3.0},
    {"htf": "1h", "ltf": "1m", "fixed_rr": None, "min_rr": 2.5},
    {"htf": "15m", "ltf": "1m", "fixed_rr": None, "min_rr": 2.5}
]

def get_session(ts: int) -> str:
    hour = datetime.fromtimestamp(ts, timezone.utc).hour
    if 0 <= hour < 7:
        return "Asian (00:00 - 07:00 UTC)"
    elif 7 <= hour < 13:
        return "London (07:00 - 13:00 UTC)"
    elif 13 <= hour < 17:
        return "London/NY Overlap (13:00 - 17:00 UTC)"
    elif 17 <= hour < 21:
        return "New York (17:00 - 21:00 UTC)"
    else:
        return "Late/Off-Hours (21:00 - 00:00 UTC)"

def get_year_period(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, timezone.utc)
    if dt < datetime(2024, 11, 1, tzinfo=timezone.utc):
        return "Year 1 (Nov 2023 - Oct 2024)"
    elif dt < datetime(2025, 11, 1, tzinfo=timezone.utc):
        return "Year 2 (Nov 2024 - Oct 2025)"
    else:
        return "Year 3 (Nov 2025 - Oct 2026)"

def _worker_run(item):
    symbol, htf_name, ltf_name, fixed_rr, min_rr, start_ts, end_ts = item
    engine = UniversalBacktestEngine(
        symbols=symbol,
        initial_balance=1000.0,
        risk_per_trade_pct=0.01,
        maker_fee=0.0001,
        taker_fee=0.0002,
        slippage_pct=0.0001
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
        t["session"] = get_session(t["entry_time"])
        t["year_period"] = get_year_period(t["entry_time"])
        t["calendar_year"] = datetime.fromtimestamp(t["entry_time"], timezone.utc).year
        t["day_of_week"] = datetime.fromtimestamp(t["entry_time"], timezone.utc).strftime("%A")
    return symbol, f"{htf_name}_{ltf_name}", trades

def main():
    print("=" * 75)
    print(" 3-YEAR MULTI-ASSET FUTURES BACKTEST & LOSS FORENSICS (8 PAIRS)")
    print("=" * 75)
    start_date = "2023-11-01"
    end_date = "2026-10-31"
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    tasks = []
    for sym in SYMBOLS:
        for cfg in TIMEFRAME_MATRIX:
            tasks.append((sym, cfg["htf"], cfg["ltf"], cfg["fixed_rr"], cfg["min_rr"], start_ts, end_ts))

    print(f"Executing {len(tasks)} backtest jobs in parallel across CPU cores...")
    t0 = time.time()

    all_trades = []
    symbol_trades = defaultdict(list)
    tf_trades = defaultdict(list)

    # Use 8 parallel worker processes
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_worker_run, task): task for task in tasks}
        completed = 0
        for fut in as_completed(futures):
            completed += 1
            sym, tf_str, trades = fut.result()
            symbol_trades[sym].extend(trades)
            tf_trades[tf_str].extend(trades)
            all_trades.extend(trades)
            print(f"[{completed}/{len(tasks)}] {sym} {tf_str}: {len(trades)} trades", flush=True)

    elapsed = time.time() - t0
    print(f"\nAll simulation runs completed in {elapsed:.1f}s. Total trades: {len(all_trades)}")

    # Sort all trades chronologically
    all_trades.sort(key=lambda x: x["entry_time"])

    # Compute metrics function
    engine = UniversalBacktestEngine(initial_balance=1000.0, risk_per_trade_pct=0.01)
    
    # Save results
    out_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(out_dir, exist_ok=True)
    
    # 1. By Year
    year_map = defaultdict(list)
    for t in all_trades:
        year_map[t["year_period"]].append(t)
    by_year = {k: engine.compute_metrics(v) for k, v in sorted(year_map.items())}

    # 2. By Calendar Year
    cal_year_map = defaultdict(list)
    for t in all_trades:
        cal_year_map[str(t["calendar_year"])].append(t)
    by_cal_year = {k: engine.compute_metrics(v) for k, v in sorted(cal_year_map.items())}

    # 3. By Session
    session_map = defaultdict(list)
    for t in all_trades:
        session_map[t["session"]].append(t)
    by_session = {k: engine.compute_metrics(v) for k, v in sorted(session_map.items())}

    # 4. By Symbol
    by_sym = {sym: engine.compute_metrics(symbol_trades[sym]) for sym in SYMBOLS}

    # 5. By Timeframe
    by_tf = {k: engine.compute_metrics(v) for k, v in tf_trades.items()}

    # 6. By Level Category
    all_categories = [
        "TJL1 (BOS)", "TJL2 (BOS)", "QML (Single CHoCH)", 
        "Double Top/Bottom (Single CHoCH)", "A+ (Dual CHoCH)", "SBR / RBS (Dual CHoCH)"
    ]
    by_cat = {}
    for cat in all_categories:
        cat_trades = [t for t in all_trades if t.get("level_category") == cat]
        by_cat[cat] = engine.compute_metrics(cat_trades)

    # 7. Loss Forensics
    losing_trades = [t for t in all_trades if t["outcome"] == "LOSS"]
    total_losses = len(losing_trades)
    
    loss_by_session = defaultdict(int)
    loss_by_level = defaultdict(int)
    loss_by_day = defaultdict(int)
    loss_by_sym = defaultdict(int)
    rapid_stopouts = 0  # stopped out within 15 mins (quick rejection)

    for lt in losing_trades:
        loss_by_session[lt["session"]] += 1
        loss_by_level[lt["level_category"]] += 1
        loss_by_day[lt["day_of_week"]] += 1
        loss_by_sym[lt["symbol"]] += 1
        dur = lt.get("exit_time", 0) - lt.get("entry_time", 0)
        if dur <= 900:  # <= 15 minutes
            rapid_stopouts += 1

    forensics = {
        "total_losses": total_losses,
        "total_loss_rate_pct": round(total_losses / len(all_trades) * 100, 2) if all_trades else 0,
        "rapid_stopouts_under_15m": rapid_stopouts,
        "rapid_stopout_pct": round(rapid_stopouts / total_losses * 100, 2) if total_losses else 0,
        "losses_by_session": dict(loss_by_session),
        "losses_by_level": dict(loss_by_level),
        "losses_by_day": dict(loss_by_day),
        "losses_by_symbol": dict(loss_by_sym)
    }

    results = {
        "period": f"{start_date} to {end_date}",
        "portfolio_summary": engine.compute_metrics(all_trades),
        "by_symbol": by_sym,
        "by_year_period": by_year,
        "by_calendar_year": by_cal_year,
        "by_session": by_session,
        "by_timeframe": by_tf,
        "by_level_category": by_cat,
        "loss_forensics": forensics,
        "all_trades": all_trades
    }

    # Save outputs
    out_json = os.path.join(out_dir, "forex_gold_3years_8pairs_backtest.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[SAVED] Full 3-Year JSON saved to: {out_json}")

    csv_file = os.path.join(out_dir, "forex_gold_3years_8pairs_trades.csv")
    df = pd.DataFrame(all_trades)
    df.to_csv(csv_file, index=False)
    print(f"[SAVED] Trades CSV saved to: {csv_file}")

    print("\n" + "=" * 75)
    print(" PORTFOLIO 3-YEAR SUMMARY (8 ASSETS COMBINED)")
    print("=" * 75)
    p = results["portfolio_summary"]
    print(f"Total Trades:       {p['total_trades']}")
    print(f"Wins / Losses:      {p['wins']} / {p['losses']}")
    print(f"Win Rate:           {p['win_rate_pct']:.2f}%")
    print(f"Net PnL (R):        {p['net_r']:+.2f}R")
    print(f"Profit Factor:      {p['profit_factor']:.2f}")
    print(f"Max Drawdown:       {p['comp_max_dd_pct']:.2f}% (${p['comp_max_dd_dollars']:.2f})")
    print(f"Flat Balance:       ${p['flat_final_balance']:.2f} ({p['flat_roi_pct']:+.2f}%)")
    print(f"Compounded Balance: ${p['comp_final_balance']:.2f} ({p['comp_roi_pct']:+.2f}%)")

if __name__ == "__main__":
    main()
