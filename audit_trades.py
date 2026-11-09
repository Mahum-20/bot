import json
import bisect
from datetime import datetime, timezone

with open("data/oct_2026_backtest_results.json") as f:
    d = json.load(f)

with open("data/btcusdt_1m_1y_oct2025_oct2026.json") as f:
    m1_candles = json.load(f)

m1_times = [c["time"] for c in m1_candles]

def audit_trade_set(tf_key, label):
    trades = d[tf_key]["trades"]
    print(f"\n{'='*80}")
    print(f"AUDIT FOR {label} ({len(trades)} TRADES)")
    print(f"{'='*80}")
    
    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    
    # Calculate MFE (Max Favorable Excursion in R) for losses
    mfe_over_1r = 0
    mfe_over_2r = 0
    immediate_wicks = 0
    zone_blown_through = 0
    
    for i, t in enumerate(trades):
        t_open = t["open_time"]
        t_exit = t["exit_time"]
        entry = t["entry_price"]
        sl = t["sl_price"]
        tp = t["tp_price"]
        is_buy = (t["action"] == "BUY")
        risk_dist = abs(entry - sl)
        
        # Track 1m price during trade to find MFE
        idx1 = bisect.bisect_left(m1_times, t_open)
        idx2 = bisect.bisect_right(m1_times, t_exit)
        sub_candles = m1_candles[idx1:idx2]
        
        max_fav = 0.0
        for c in sub_candles:
            if is_buy:
                fav = c["high"] - entry
            else:
                fav = entry - c["low"]
            if fav > max_fav:
                max_fav = fav
        
        mfe_r = round(max_fav / risk_dist, 2) if risk_dist > 0 else 0.0
        
        if t["outcome"] == "LOSS":
            if mfe_r >= 2.0:
                mfe_over_2r += 1
            elif mfe_r >= 1.0:
                mfe_over_1r += 1
            else:
                immediate_wicks += 1
                
        dt_placed = datetime.fromtimestamp(t["placed_time"], timezone.utc).strftime("%Y-%m-%d %H:%M")
        dt_exit = datetime.fromtimestamp(t["exit_time"], timezone.utc).strftime("%Y-%m-%d %H:%M")
        
        print(f"[{i+1:02d}] {t['action']:<4} | Placed: {dt_placed} | Exit: {dt_exit} | {t['outcome']:<4} ({t['pnl_r']:+.2f}R) "
              f"| Entry: {entry:<8.1f} | SL: {sl:<8.1f} | TP: {tp:<8.1f} | Plan RR: {t['rr']:<4.1f}R | MFE: +{mfe_r:<4.2f}R "
              f"| Level: {t.get('level_name')} | Pattern: {t.get('pattern_name')}")
              
    print(f"\nLoss Diagnostics for {label}:")
    print(f"  Total Losses: {len(losses)}")
    print(f"  Losses that reached >= +2.0R profit before reversing into SL: {mfe_over_2r}")
    print(f"  Losses that reached >= +1.0R profit before reversing into SL: {mfe_over_1r}")
    print(f"  Immediate Wicks / Breakouts (< 1.0R profit): {immediate_wicks}")

audit_trade_set("timeframe_4h_5m", "4H -> 5M")
audit_trade_set("timeframe_1h_1m", "1H -> 1M")
audit_trade_set("timeframe_15m_1m", "15M -> 1M")
