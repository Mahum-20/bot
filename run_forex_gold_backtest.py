"""
Forex (EURUSD, GBPUSD) & Gold (XAUUSD) 1-Year Backtest Execution Script
=======================================================================
Period: 2025-10-01 to 2026-10-01
Data Source: Dukascopy Bank ECN Feed (Raw Institutional Quotes)
Strategy: Exact Live TopG Bot Logic
  - 4h -> 5m (Fixed 3.0R)
  - 1h -> 1m (Opposing HTF Liquidity TP >= 2.5R)
  - 15m -> 1m (Opposing HTF Liquidity TP >= 2.5R)
Constraints:
  - 1% Compound & Flat Risk ($1,000 Initial Capital)
  - Zero Lookahead & Causal Formation
  - Strict 2-close zone mitigation
  - Strict 1 trade per level
  - Candlestick pattern confirmation
"""
import os
import sys
import json
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from universal_multi_asset_backtest import UniversalBacktestEngine

def main():
    symbols = ["EURUSD", "GBPUSD", "XAUUSD"]
    print(f"Starting 1-Year Backtest on Forex & Gold: {symbols}")
    print("Period: 2025-10-01 to 2026-10-01")
    print("Risk per trade: 1.0% | Initial Balance: $1,000.00")
    print("-" * 60)

    engine = UniversalBacktestEngine(
        symbols=symbols,
        initial_balance=1000.0,
        risk_per_trade_pct=0.01,
        maker_fee=0.0001,  # Typical ECN spread/comm
        taker_fee=0.0002,
        slippage_pct=0.0001
    )

    t0 = time.time()
    results = engine.run_all(
        symbols=symbols,
        start_date="2025-10-01",
        end_date="2026-10-01"
    )
    elapsed = time.time() - t0
    print(f"\n[COMPLETE] Backtest finished in {elapsed:.2f} seconds.")

    # Save summary and trade logs
    out_json = os.path.join(BASE_DIR, "data", "forex_gold_1year_backtest_oct2025_oct2026.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[SAVED] Results JSON saved to: {out_file if 'out_file' in locals() else out_json}")

    # Export CSV of trades
    import pandas as pd
    trades = results.get("all_trades", [])
    if trades:
        csv_file = os.path.join(BASE_DIR, "data", "forex_gold_1year_trades.csv")
        df = pd.DataFrame(trades)
        df.to_csv(csv_file, index=False)
        print(f"[SAVED] Trades CSV saved to: {csv_file}")

    # Print summary table
    p_sum = results["portfolio_summary"]
    print("\n" + "=" * 70)
    print(" PORTFOLIO SUMMARY (EURUSD + GBPUSD + XAUUSD)")
    print("=" * 70)
    print(f"Total Trades:       {p_sum['total_trades']}")
    print(f"Wins / Losses:      {p_sum['wins']} / {p_sum['losses']}")
    print(f"Win Rate:           {p_sum['win_rate_pct']:.2f}%")
    print(f"Net PnL (R):        {p_sum['net_r']:+.2f}R")
    print(f"Profit Factor:      {p_sum['profit_factor']:.2f}")
    print(f"Max Drawdown:       {p_sum['comp_max_dd_pct']:.2f}% (${p_sum['comp_max_dd_dollars']:.2f})")
    print(f"Flat Balance:       ${p_sum['flat_final_balance']:.2f} ({p_sum['flat_roi_pct']:+.2f}%)")
    print(f"Compounded Balance: ${p_sum['comp_final_balance']:.2f} ({p_sum['comp_roi_pct']:+.2f}%)")
    print("=" * 70)

    print("\n--- PERFORMANCE BY SYMBOL ---")
    for sym, m in results["by_symbol"].items():
        print(f"{sym:<8} | Trades: {m['total_trades']:<4} | WinRate: {m['win_rate_pct']:>5.2f}% | Net R: {m['net_r']:>+7.2f}R | PF: {m['profit_factor']:>4.2f} | MaxDD: {m['comp_max_dd_pct']:>5.2f}% | Comp Final: ${m['comp_final_balance']:>10.2f}")

    print("\n--- PERFORMANCE BY TIMEFRAME ---")
    for tf, m in results["by_timeframe"].items():
        print(f"{tf:<8} | Trades: {m['total_trades']:<4} | WinRate: {m['win_rate_pct']:>5.2f}% | Net R: {m['net_r']:>+7.2f}R | PF: {m['profit_factor']:>4.2f} | MaxDD: {m['comp_max_dd_pct']:>5.2f}% | Comp Final: ${m['comp_final_balance']:>10.2f}")

    print("\n--- PERFORMANCE BY LEVEL CATEGORY ---")
    for cat, m in results["by_level_category"].items():
        print(f"{cat:<32} | Trades: {m['total_trades']:<4} | WinRate: {m['win_rate_pct']:>5.2f}% | Net R: {m['net_r']:>+7.2f}R | PF: {m['profit_factor']:>4.2f}")

if __name__ == "__main__":
    main()
