import json
import os
import math
from datetime import datetime, timezone
import pandas as pd
from ltf_approach_engine import compute_ltf_approach_structure
from htf_engine import HTFEngine

def simulate_tf_pair(htf_name, ltf_name, htf_candles, ltf_candles, htf_sec, start_ts=1790812800):
    print(f"\nEvaluating {htf_name.upper()} -> {ltf_name.upper()}...")
    
    htf_engine = HTFEngine(lookback_bars=len(htf_candles), show_tjl_boxes=True, tjl_extend=True, start_marking_time=start_ts)
    htf_out = htf_engine.run(htf_candles)
    htf_boxes = htf_out.get('boxes', [])

    trades = []
    active_trade = None
    last_zone_tap = {} # box_name -> timestamp of last tap

    for idx, c in enumerate(ltf_candles):
        c_time = c['time']
        if c_time < start_ts:
            continue

        # 1. Manage active trade
        if active_trade:
            is_bullish = (active_trade['action'] == 'BUY')
            tp = active_trade['tp_price']
            sl = active_trade['sl_price']
            c_high = c['high']
            c_low = c['low']

            hit_tp = (c_high >= tp) if is_bullish else (c_low <= tp)
            hit_sl = (c_low <= sl) if is_bullish else (c_high >= sl)

            if hit_tp and hit_sl:
                # Conservative resolution: check which extreme was closer to candle open
                if abs(c['open'] - sl) <= abs(c['open'] - tp):
                    hit_tp = False
                else:
                    hit_sl = False

            if hit_tp:
                active_trade['exit_time'] = c_time
                active_trade['exit_price'] = tp
                active_trade['exit_reason'] = 'TP'
                active_trade['outcome'] = 'WIN'
                active_trade['pnl_r'] = active_trade['rr']
                trades.append(active_trade)
                active_trade = None
            elif hit_sl:
                active_trade['exit_time'] = c_time
                active_trade['exit_price'] = sl
                active_trade['exit_reason'] = 'SL'
                active_trade['outcome'] = 'LOSS'
                active_trade['pnl_r'] = -1.0
                trades.append(active_trade)
                active_trade = None

            if active_trade:
                continue

        # 2. Check for HTF zone taps
        for b in htf_boxes:
            b_name = b.get('text') or b.get('name') or 'HTF Zone'
            b_top = max(b.get('top', 0), b.get('bottom', 0))
            b_bot = min(b.get('top', 0), b.get('bottom', 0))

            if c['high'] >= b_bot and c['low'] <= b_top:
                last_tap = last_zone_tap.get(b_name, 0)
                # Zone tap cycle spacing (at least 2 hours between separate tap cycles on same box)
                if c_time - last_tap >= 7200:
                    last_zone_tap[b_name] = c_time

                    res = compute_ltf_approach_structure(
                        target_time=c_time,
                        ltf_candles=ltf_candles,
                        htf_boxes=htf_boxes,
                        htf_sec=htf_sec,
                        htf_candles=htf_candles
                    )
                    tap_info = res.get('tap_info')
                    if tap_info and tap_info.get('trade'):
                        tr = tap_info['trade']
                        if tr.get('executed') and tr.get('time') >= c_time:
                            active_trade = {
                                "id": f"{htf_name}_{tr['time']}",
                                "htf": htf_name,
                                "ltf": ltf_name,
                                "action": tr["action"],
                                "entry_time": tr["time"],
                                "entry_price": tr["entry_price"],
                                "sl_price": tr["sl_price"],
                                "tp_price": tr["tp_price"],
                                "risk": tr["risk"],
                                "reward": tr["reward"],
                                "rr": tr["rr"],
                                "pattern_name": tr["pattern_name"],
                                "level_name": tr["level_name"],
                                "box_name": b_name,
                                "tap_time": c_time,
                                "winner_pathway": tap_info.get("winner_pathway", "Structure")
                            }
                            break

    if active_trade:
        final_c = ltf_candles[-1]
        active_trade['exit_time'] = final_c['time']
        active_trade['exit_price'] = final_c['close']
        active_trade['exit_reason'] = 'OPEN_AT_END'
        is_bullish = (active_trade['action'] == 'BUY')
        raw_r = ((final_c['close'] - active_trade['entry_price']) if is_bullish else (active_trade['entry_price'] - final_c['close'])) / active_trade['risk']
        active_trade['outcome'] = 'WIN' if raw_r > 0 else 'LOSS'
        active_trade['pnl_r'] = round(raw_r, 2)
        trades.append(active_trade)

    return trades

def compute_metrics(trades_list, initial_capital=10000.0, risk_pct=0.01):
    if not trades_list:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "net_pnl_r": 0.0, "final_capital": initial_capital, "net_profit_dollar": 0.0,
            "return_pct": 0.0, "profit_factor": 0.0, "max_drawdown_r": 0.0,
            "max_drawdown_dollar": 0.0, "max_drawdown_pct": 0.0, "avg_rr": 0.0
        }

    # Sort trades chronologically by entry_time
    sorted_trades = sorted(trades_list, key=lambda x: x['entry_time'])

    wins = [t for t in sorted_trades if t['pnl_r'] > 0]
    losses = [t for t in sorted_trades if t['pnl_r'] <= 0]
    win_rate = (len(wins) / len(sorted_trades)) * 100.0 if sorted_trades else 0.0

    gross_profit_r = sum(t['pnl_r'] for t in wins)
    gross_loss_r = abs(sum(t['pnl_r'] for t in losses))
    net_pnl_r = gross_profit_r - gross_loss_r
    profit_factor = (gross_profit_r / gross_loss_r) if gross_loss_r > 0 else (99.0 if gross_profit_r > 0 else 0.0)
    avg_rr = (sum(t['rr'] for t in sorted_trades) / len(sorted_trades)) if sorted_trades else 0.0

    # Capital simulation
    # Fixed fractional risk: risk_pct of initial capital or compounding
    current_capital = initial_capital
    peak_capital = initial_capital
    max_dd_dollar = 0.0
    max_dd_pct = 0.0

    cum_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0

    for t in sorted_trades:
        dollar_risk = initial_capital * risk_pct
        trade_dollar_pnl = t['pnl_r'] * dollar_risk
        t['dollar_pnl'] = round(trade_dollar_pnl, 2)

        current_capital += trade_dollar_pnl
        t['capital_after'] = round(current_capital, 2)

        cum_r += t['pnl_r']
        t['cum_r'] = round(cum_r, 2)

        if cum_r > peak_r:
            peak_r = cum_r
        dd_r = peak_r - cum_r
        if dd_r > max_dd_r:
            max_dd_r = dd_r

        if current_capital > peak_capital:
            peak_capital = current_capital
        dd_dollar = peak_capital - current_capital
        dd_pct = (dd_dollar / peak_capital) * 100.0 if peak_capital > 0 else 0.0

        if dd_dollar > max_dd_dollar:
            max_dd_dollar = dd_dollar
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    net_profit_dollar = current_capital - initial_capital
    return_pct = (net_profit_dollar / initial_capital) * 100.0

    return {
        "total_trades": len(sorted_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 2),
        "gross_profit_r": round(gross_profit_r, 2),
        "gross_loss_r": round(gross_loss_r, 2),
        "net_pnl_r": round(net_pnl_r, 2),
        "avg_rr": round(avg_rr, 2),
        "profit_factor": round(profit_factor, 2),
        "initial_capital": initial_capital,
        "final_capital": round(current_capital, 2),
        "net_profit_dollar": round(net_profit_dollar, 2),
        "return_pct": round(return_pct, 2),
        "max_drawdown_r": round(max_dd_r, 2),
        "max_drawdown_dollar": round(max_dd_dollar, 2),
        "max_drawdown_pct": round(max_dd_pct, 2)
    }

def main():
    with open('data/btc_15m_oct2026_full.json') as f: c_15m = json.load(f)
    with open('data/btc_1h_oct2026_full.json') as f: c_1h = json.load(f)
    with open('data/btc_4h_oct2026_full.json') as f: c_4h = json.load(f)
    with open('data/btc_1m_oct2026_full.json') as f: c_1m = json.load(f)
    with open('data/btc_5m_oct2026_full.json') as f: c_5m = json.load(f)

    # 1. Simulate 3 pairs individually
    t_15m = simulate_tf_pair('15m', '1m', c_15m, c_1m, 900)
    t_1h = simulate_tf_pair('1h', '1m', c_1h, c_1m, 3600)
    t_4h = simulate_tf_pair('4h', '5m', c_4h, c_5m, 14400)

    m_15m = compute_metrics(t_15m)
    m_1h = compute_metrics(t_1h)
    m_4h = compute_metrics(t_4h)

    # 2. Combined Portfolio (merging all 3 combinations chronologically)
    all_trades = t_15m + t_1h + t_4h
    m_comb = compute_metrics(all_trades)

    # Save trades to JSON and CSV
    clean_trades = []
    for t in sorted(all_trades, key=lambda x: x['entry_time']):
        clean_trades.append({
            "id": t['id'],
            "htf": t['htf'],
            "ltf": t['ltf'],
            "pair": f"{t['htf'].upper()}->{t['ltf'].upper()}",
            "action": t['action'],
            "entry_time": datetime.fromtimestamp(t['entry_time'], timezone.utc).strftime('%Y-%m-%d %H:%M'),
            "exit_time": datetime.fromtimestamp(t['exit_time'], timezone.utc).strftime('%Y-%m-%d %H:%M'),
            "duration_mins": round((t['exit_time'] - t['entry_time']) / 60, 1),
            "entry_price": t['entry_price'],
            "sl_price": t['sl_price'],
            "tp_price": t['tp_price'],
            "risk": t['risk'],
            "reward": t['reward'],
            "rr": t['rr'],
            "pattern_name": t['pattern_name'],
            "level_name": t['level_name'],
            "box_name": t['box_name'],
            "exit_reason": t['exit_reason'],
            "outcome": t['outcome'],
            "pnl_r": t['pnl_r'],
            "dollar_pnl": t.get('dollar_pnl', 0.0),
            "cum_r": t.get('cum_r', 0.0),
            "capital_after": t.get('capital_after', 0.0)
        })

    with open('data/october_2026_backtest_all_3tf.json', 'w') as f:
        json.dump({
            "metrics": {
                "htf_15m_ltf_1m": m_15m,
                "htf_1h_ltf_1m": m_1h,
                "htf_4h_ltf_5m": m_4h,
                "combined_portfolio": m_comb
            },
            "trades": clean_trades
        }, f, indent=2)

    df = pd.DataFrame(clean_trades)
    df.to_csv('data/october_2026_backtest_all_3tf.csv', index=False)

    print("\n" + "="*80)
    print("OCTOBER 2026 COMPLETE PERFORMANCE REPORT (ALL 3 TIMEFRAMES)")
    print("="*80)
    print(f"{'Metric':<30} | {'15m -> 1m':<14} | {'1h -> 1m':<14} | {'4h -> 5m':<14} | {'COMBINED TOTAL':<14}")
    print("-"*80)
    print(f"{'Total Executed Trades':<30} | {m_15m['total_trades']:<14} | {m_1h['total_trades']:<14} | {m_4h['total_trades']:<14} | {m_comb['total_trades']:<14}")
    print(f"{'Winning Trades':<30} | {m_15m['wins']:<14} | {m_1h['wins']:<14} | {m_4h['wins']:<14} | {m_comb['wins']:<14}")
    print(f"{'Losing Trades':<30} | {m_15m['losses']:<14} | {m_1h['losses']:<14} | {m_4h['losses']:<14} | {m_comb['losses']:<14}")
    print(f"{'Win Rate (%)':<30} | {m_15m['win_rate']:<13}% | {m_1h['win_rate']:<13}% | {m_4h['win_rate']:<13}% | {m_comb['win_rate']:<13}%")
    print(f"{'Average Planned R:R':<30} | {m_15m['avg_rr']:<12}R | {m_1h['avg_rr']:<12}R | {m_4h['avg_rr']:<12}R | {m_comb['avg_rr']:<12}R")
    print(f"{'Gross Profit (R)':<30} | +{m_15m['gross_profit_r']:<13}R | +{m_1h['gross_profit_r']:<13}R | +{m_4h['gross_profit_r']:<13}R | +{m_comb['gross_profit_r']:<13}R")
    print(f"{'Gross Loss (R)':<30} | -{m_15m['gross_loss_r']:<13}R | -{m_1h['gross_loss_r']:<13}R | -{m_4h['gross_loss_r']:<13}R | -{m_comb['gross_loss_r']:<13}R")
    print(f"{'Net PnL (R)':<30} | {m_15m['net_pnl_r']:<13}R | {m_1h['net_pnl_r']:<13}R | {m_4h['net_pnl_r']:<13}R | {m_comb['net_pnl_r']:<13}R")
    print(f"{'Profit Factor':<30} | {m_15m['profit_factor']:<14} | {m_1h['profit_factor']:<14} | {m_4h['profit_factor']:<14} | {m_comb['profit_factor']:<14}")
    print(f"{'Net Return on $10k (1% risk)':<30} | +${m_15m['net_profit_dollar']:<12} | +${m_1h['net_profit_dollar']:<12} | +${m_4h['net_profit_dollar']:<12} | +${m_comb['net_profit_dollar']:<12}")
    print(f"{'Account Return (%)':<30} | +{m_15m['return_pct']:<13}% | +{m_1h['return_pct']:<13}% | +{m_4h['return_pct']:<13}% | +{m_comb['return_pct']:<13}%")
    print(f"{'Max Drawdown (R)':<30} | -{m_15m['max_drawdown_r']:<13}R | -{m_1h['max_drawdown_r']:<13}R | -{m_4h['max_drawdown_r']:<13}R | -{m_comb['max_drawdown_r']:<13}R")
    print(f"{'Max Drawdown (%)':<30} | {m_15m['max_drawdown_pct']:<13}% | {m_1h['max_drawdown_pct']:<13}% | {m_4h['max_drawdown_pct']:<13}% | {m_comb['max_drawdown_pct']:<13}%")
    print(f"{'Max Drawdown ($ on $10k)':<30} | -${m_15m['max_drawdown_dollar']:<12} | -${m_1h['max_drawdown_dollar']:<12} | -${m_4h['max_drawdown_dollar']:<12} | -${m_comb['max_drawdown_dollar']:<12}")
    print("="*80)

if __name__ == "__main__":
    main()
