"""
Backtest October 2026 Data on BTCUSDT across all 3 Timeframes
============================================================
Evaluates performance for 2026-10-01 00:00:00 UTC to 2026-10-31 23:59:00 UTC
with the updated rules (MTF-002 and MTF-003 removed, 120-candle cycle state machine active).
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Any

from faithful_backtest_engine import FaithfulBacktestEngine
from rule_traceability_logger import RuleEvaluationLogger

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def run_single_tf(htf: str, ltf: str, start_ts: int, end_ts: int) -> Dict[str, Any]:
    print(f"\n{'='*60}")
    print(f"RUNNING BTCUSDT {htf.upper()} -> {ltf.upper()} (OCTOBER 2026)")
    print(f"{'='*60}")
    
    t0 = time.time()
    logger_inst = RuleEvaluationLogger()
    engine = FaithfulBacktestEngine(
        symbol="BTCUSDT",
        htf_tf=htf,
        ltf_tf=ltf,
        initial_balance=1000.0,
        risk_pct=0.01,
        maker_fee=0.0002,
        taker_fee=0.0005,
        slippage_pct=0.0005,
        logger_instance=logger_inst
    )
    
    res = engine.run_backtest(start_ts=start_ts, end_ts=end_ts)
    elapsed = time.time() - t0
    res["execution_time_seconds"] = round(elapsed, 2)
    
    m = res["metrics"]
    print(f"[{htf.upper()}->{ltf.upper()}] Completed in {elapsed:.1f}s")
    print(f"  Trades: {m['total_trades']} (Wins: {m['wins']}, Losses: {m['losses']})")
    print(f"  Win Rate: {m['win_rate_pct']}% | Profit Factor: {m['profit_factor']}")
    print(f"  Net PnL: ${m['net_pnl_usd']:+.2f} | Net R: {m['net_r']:+.2f}R | Max DD: {m['max_drawdown_pct']}%")
    print(f"  Final Balance: ${res['final_balance']:.2f} (from $1,000.00)")
    
    return res


def run_unified_portfolio(all_trades: List[Dict]) -> Dict[str, Any]:
    print(f"\n{'='*60}")
    print(f"RUNNING UNIFIED PORTFOLIO SIMULATION (OCTOBER 2026)")
    print(f"{'='*60}")
    
    sorted_trades = sorted(all_trades, key=lambda x: x["placed_time"])
    cur_bal = 1000.0
    peak_bal = 1000.0
    max_dd = 0.0
    active_until = 0
    executed = []
    
    current_day = ""
    daily_start_bal = cur_bal
    daily_loss = 0.0
    
    for t in sorted_trades:
        t_open = t["placed_time"]
        t_exit = t["exit_time"]
        
        # Anti-cannibalization: max 1 position
        if t_open < active_until:
            continue
            
        dt_utc = datetime.fromtimestamp(t_open, timezone.utc)
        day_str = dt_utc.strftime("%Y-%m-%d")
        if day_str != current_day:
            current_day = day_str
            daily_start_bal = cur_bal
            daily_loss = 0.0
            
        # Circuit breaker
        if daily_start_bal > 0 and daily_loss <= -0.10 * daily_start_bal:
            continue
            
        active_until = t_exit
        risk_dist = t["risk_distance"]
        if risk_dist <= 0:
            continue
            
        pos_size = (cur_bal * 0.01) / risk_dist
        pos_size = max(0.001, round(pos_size, 3))
        
        entry_fee = pos_size * t["entry_price"] * 0.0002
        exit_fee = pos_size * t["exit_price"] * (0.0002 if t["exit_reason"] == "TP" else 0.0005)
        
        is_buy = (t["action"] == "BUY")
        if is_buy:
            gross = (t["exit_price"] - t["entry_price"]) * pos_size
        else:
            gross = (t["entry_price"] - t["exit_price"]) * pos_size
            
        pnl = gross - entry_fee - exit_fee
        pnl_r = pnl / (cur_bal * 0.01) if cur_bal > 0 else 0.0
        
        cur_bal += pnl
        daily_loss += pnl
        if cur_bal > peak_bal:
            peak_bal = cur_bal
        dd = ((peak_bal - cur_bal) / peak_bal) * 100.0 if peak_bal > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            
        executed.append({
            **t,
            "portfolio_pnl_usd": round(pnl, 2),
            "portfolio_pnl_r": round(pnl_r, 2),
            "portfolio_balance_after": round(cur_bal, 2)
        })
        
    wins = [x for x in executed if x["outcome"] == "WIN"]
    losses = [x for x in executed if x["outcome"] == "LOSS"]
    wr = (len(wins) / len(executed) * 100.0) if executed else 0.0
    gp = sum(x["portfolio_pnl_usd"] for x in wins)
    gl = abs(sum(x["portfolio_pnl_usd"] for x in losses))
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)
    net_r = sum(x["portfolio_pnl_r"] for x in executed)
    
    print(f"[UNIFIED PORTFOLIO RESULTS]")
    print(f"  Trades: {len(executed)} (Wins: {len(wins)}, Losses: {len(losses)})")
    print(f"  Win Rate: {wr:.2f}% | Profit Factor: {pf:.2f}")
    print(f"  Net Compounded PnL: ${cur_bal - 1000.0:+.2f} | Net R: {net_r:+.2f}R")
    print(f"  Max Compounded Drawdown: {max_dd:.2f}%")
    print(f"  Final Balance: ${cur_bal:.2f} (from $1,000.00)")
    
    return {
        "total_trades": len(executed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(wr, 2),
        "profit_factor": round(pf, 2),
        "net_pnl_usd": round(cur_bal - 1000.0, 2),
        "net_r": round(net_r, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "final_balance": round(cur_bal, 2),
        "trades": executed
    }


def main():
    start_dt = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    
    print(f"Backtesting October 2026: {start_dt} to {end_dt}")
    print(f"Timestamps: {start_ts} -> {end_ts}")
    
    res_4h_5m = run_single_tf("4h", "5m", start_ts, end_ts)
    res_1h_1m = run_single_tf("1h", "1m", start_ts, end_ts)
    res_15m_1m = run_single_tf("15m", "1m", start_ts, end_ts)
    
    all_trades = (
        res_4h_5m.get("trades", []) +
        res_1h_1m.get("trades", []) +
        res_15m_1m.get("trades", [])
    )
    
    unified_res = run_unified_portfolio(all_trades)
    
    combined_output = {
        "metadata": {
            "symbol": "BTCUSDT",
            "market": "Binance Futures (USDT-M)",
            "period": "October 2026",
            "start_date": "2026-10-01 00:00:00 UTC",
            "end_date": "2026-10-31 23:59:59 UTC",
            "starting_balance": 1000.0,
            "risk_per_trade_pct": 1.0,
            "rules_modified": [
                "MTF-002 removed (no approach BOS/CHoCH required)",
                "MTF-003 removed (any directional tap allowed)",
                "MTF-004 active (120-candle reaction cycle state machine)"
            ]
        },
        "timeframe_4h_5m": res_4h_5m,
        "timeframe_1h_1m": res_1h_1m,
        "timeframe_15m_1m": res_15m_1m,
        "unified_portfolio": unified_res
    }
    
    out_file = os.path.join(OUTPUT_DIR, "oct_2026_backtest_results.json")
    with open(out_file, "w") as f:
        json.dump(combined_output, f, indent=2)
    print(f"\n[DONE] Saved October 2026 backtest results to: {out_file}")


if __name__ == "__main__":
    main()
