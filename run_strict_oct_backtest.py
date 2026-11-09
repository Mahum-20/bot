import json
import os
import math
from datetime import datetime, timezone
import pandas as pd
from ltf_approach_engine import compute_ltf_approach_structure
from htf_engine import HTFEngine

def simulate_strict_pair(htf_name, ltf_name, htf_candles, ltf_candles, htf_sec, start_ts=1790812800, fixed_rr=3.0):
    print(f"\n==================================================================")
    print(f"RUNNING STRICT AUDITED SIMULATION: HTF {htf_name.upper()} -> LTF {ltf_name.upper()} (Fixed RR: {fixed_rr}R)")
    print(f"==================================================================")

    # 1. Run HTFEngine
    htf_engine = HTFEngine(lookback_bars=len(htf_candles), show_tjl_boxes=True, tjl_extend=True)
    htf_out = htf_engine.run(htf_candles)
    htf_boxes = htf_out.get('boxes', [])

    trades = []
    active_trade = None
    
    # State tracking per box:
    # 'IN_CYCLE' means price tapped this box, we are tracking or have traded it.
    # A box only resets to 'READY' after price has completely moved outside its boundaries.
    box_state = {}     # b_key -> 'READY' or 'LOCKED'
    box_last_tap = {}  # b_key -> timestamp

    for idx, c in enumerate(ltf_candles):
        c_time = c['time']
        if c_time < start_ts:
            continue

        c_high = c['high']
        c_low = c['low']

        # -------------------------------------------------------------
        # 1. Manage Active Open Trade
        # -------------------------------------------------------------
        if active_trade:
            # A trade can only be exited after price has actually reached past its entry time!
            if c_time > active_trade['entry_time']:
                is_bullish = (active_trade['action'] == 'BUY')
                tp = active_trade['tp_price']
                sl = active_trade['sl_price']

                hit_tp = (c_high >= tp) if is_bullish else (c_low <= tp)
                hit_sl = (c_low <= sl) if is_bullish else (c_high >= sl)

                if hit_tp and hit_sl:
                    # Conservative intra-bar execution: if open was closer to SL, SL hit first
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

            # Strictly 1 trade at a time: cannot enter a new trade while one is already active or pending entry
            if active_trade:
                continue

        # -------------------------------------------------------------
        # 2. Update Zone States (Exit detection)
        # -------------------------------------------------------------
        for b in htf_boxes:
            b_key = f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}"
            b_top = max(b.get('top', 0), b.get('bottom', 0))
            b_bot = min(b.get('top', 0), b.get('bottom', 0))

            is_inside = (c_high >= b_bot and c_low <= b_top)
            if not is_inside:
                # Price has completely moved outside the box boundaries, unlocks for future cycles
                if box_state.get(b_key) == 'LOCKED' and (c_time - box_last_tap.get(b_key, 0) >= 3600):
                    box_state[b_key] = 'READY'

        # -------------------------------------------------------------
        # 3. Check for New Zone Tap & Retest Trade
        # -------------------------------------------------------------
        for b in htf_boxes:
            b_key = f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}"
            b_name = b.get('text') or b.get('name') or 'HTF Zone'
            b_top = max(b.get('top', 0), b.get('bottom', 0))
            b_bot = min(b.get('top', 0), b.get('bottom', 0))

            # Tap condition
            if c_high >= b_bot and c_low <= b_top:
                state = box_state.get(b_key, 'READY')
                if state == 'READY':
                    # Lock this box so only 1 trade per cycle is allowed
                    box_state[b_key] = 'LOCKED'
                    box_last_tap[b_key] = c_time

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
                        # Valid executed trade found on this cycle
                        if tr.get('executed') and tr.get('time') >= c_time:
                            risk = tr['risk']
                            is_bull = (tr['action'] == 'BUY')
                            if fixed_rr is not None:
                                planned_tp = round(tr['entry_price'] + fixed_rr * risk if is_bull else tr['entry_price'] - fixed_rr * risk, 2)
                                planned_reward = round(fixed_rr * risk, 2)
                                planned_rr = fixed_rr
                            else:
                                planned_tp = tr['tp_price']
                                planned_reward = tr['reward']
                                planned_rr = tr['rr']

                            active_trade = {
                                "id": f"{htf_name}_{tr['time']}",
                                "htf": htf_name,
                                "ltf": ltf_name,
                                "action": tr["action"],
                                "entry_time": tr["time"],
                                "entry_price": tr["entry_price"],
                                "sl_price": tr["sl_price"],
                                "tp_price": planned_tp,
                                "risk": risk,
                                "reward": planned_reward,
                                "rr": planned_rr,
                                "pattern_name": tr["pattern_name"],
                                "level_name": tr["level_name"],
                                "box_name": b_name,
                                "tap_time": c_time,
                                "winner_pathway": tap_info.get("winner_pathway", "Structure")
                            }
                            break # Found active trade; exit box search

    # If trade remained open at the very end of month
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

    print(f"Strict executed trades on {htf_name.upper()} -> {ltf_name.upper()}: {len(trades)}")
    return trades

def compute_metrics(trades_list, initial_capital=10000.0, risk_pct=0.01):
    if not trades_list:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "net_pnl_r": 0.0, "final_capital": initial_capital, "net_profit_dollar": 0.0,
            "return_pct": 0.0, "profit_factor": 0.0, "max_drawdown_r": 0.0,
            "max_drawdown_dollar": 0.0, "max_drawdown_pct": 0.0, "avg_rr": 0.0,
            "avg_win_r": 0.0, "avg_loss_r": 0.0, "max_consecutive_losses": 0
        }

    sorted_trades = sorted(trades_list, key=lambda x: x['entry_time'])
    wins = [t for t in sorted_trades if t['pnl_r'] > 0]
    losses = [t for t in sorted_trades if t['pnl_r'] <= 0]
    win_rate = (len(wins) / len(sorted_trades)) * 100.0 if sorted_trades else 0.0

    gross_profit_r = sum(t['pnl_r'] for t in wins)
    gross_loss_r = abs(sum(t['pnl_r'] for t in losses))
    net_pnl_r = gross_profit_r - gross_loss_r
    profit_factor = (gross_profit_r / gross_loss_r) if gross_loss_r > 0 else (99.0 if gross_profit_r > 0 else 0.0)
    avg_rr = (sum(t['rr'] for t in sorted_trades) / len(sorted_trades)) if sorted_trades else 0.0
    avg_win_r = (gross_profit_r / len(wins)) if wins else 0.0
    avg_loss_r = (gross_loss_r / len(losses)) if losses else 0.0

    # Max consecutive losses
    max_cons_losses = 0
    cur_cons_losses = 0
    for t in sorted_trades:
        if t['pnl_r'] <= 0:
            cur_cons_losses += 1
            if cur_cons_losses > max_cons_losses:
                max_cons_losses = cur_cons_losses
        else:
            cur_cons_losses = 0

    # Capital simulation
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
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "profit_factor": round(profit_factor, 2),
        "max_consecutive_losses": max_cons_losses,
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

    # 1. Simulate 3 pairs with strict cycle and single-position rules
    t_15m = simulate_strict_pair('15m', '1m', c_15m, c_1m, 900)
    t_1h = simulate_strict_pair('1h', '1m', c_1h, c_1m, 3600)
    t_4h = simulate_strict_pair('4h', '5m', c_4h, c_5m, 14400)

    m_15m = compute_metrics(t_15m)
    m_1h = compute_metrics(t_1h)
    m_4h = compute_metrics(t_4h)

    # 2. Combined Portfolio
    all_trades = t_15m + t_1h + t_4h
    m_comb = compute_metrics(all_trades)

    # Save to files
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

    with open('data/october_2026_strict_audited_trades.json', 'w') as f:
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
    df.to_csv('data/october_2026_strict_audited_trades.csv', index=False)

    print("\n" + "="*85)
    print("STRICT AUDITED PERFORMANCE REPORT (OCTOBER 2026)")
    print("="*85)
    print(f"{'Metric':<32} | {'15m -> 1m':<13} | {'1h -> 1m':<13} | {'4h -> 5m':<13} | {'COMBINED TOTAL':<14}")
    print("-"*85)
    print(f"{'Total Executed Trades':<32} | {m_15m['total_trades']:<13} | {m_1h['total_trades']:<13} | {m_4h['total_trades']:<13} | {m_comb['total_trades']:<14}")
    print(f"{'Winning Trades':<32} | {m_15m['wins']:<13} | {m_1h['wins']:<13} | {m_4h['wins']:<13} | {m_comb['wins']:<14}")
    print(f"{'Losing Trades':<32} | {m_15m['losses']:<13} | {m_1h['losses']:<13} | {m_4h['losses']:<13} | {m_comb['losses']:<14}")
    print(f"{'Win Rate (%)':<32} | {m_15m['win_rate']:<12}% | {m_1h['win_rate']:<12}% | {m_4h['win_rate']:<12}% | {m_comb['win_rate']:<13}%")
    print(f"{'Average Planned R:R':<32} | {m_15m['avg_rr']:<11}R | {m_1h['avg_rr']:<11}R | {m_4h['avg_rr']:<11}R | {m_comb['avg_rr']:<12}R")
    print(f"{'Average Win (R)':<32} | +{m_15m['avg_win_r']:<11}R | +{m_1h['avg_win_r']:<11}R | +{m_4h['avg_win_r']:<11}R | +{m_comb['avg_win_r']:<12}R")
    print(f"{'Gross Profit (R)':<32} | +{m_15m['gross_profit_r']:<11}R | +{m_1h['gross_profit_r']:<11}R | +{m_4h['gross_profit_r']:<11}R | +{m_comb['gross_profit_r']:<12}R")
    print(f"{'Gross Loss (R)':<32} | -{m_15m['gross_loss_r']:<11}R | -{m_1h['gross_loss_r']:<11}R | -{m_4h['gross_loss_r']:<11}R | -{m_comb['gross_loss_r']:<12}R")
    print(f"{'Net PnL (R)':<32} | {m_15m['net_pnl_r']:<11}R | {m_1h['net_pnl_r']:<11}R | {m_4h['net_pnl_r']:<11}R | {m_comb['net_pnl_r']:<12}R")
    print(f"{'Profit Factor':<32} | {m_15m['profit_factor']:<13} | {m_1h['profit_factor']:<13} | {m_4h['profit_factor']:<13} | {m_comb['profit_factor']:<14}")
    print(f"{'Max Consecutive Losses':<32} | {m_15m['max_consecutive_losses']:<13} | {m_1h['max_consecutive_losses']:<13} | {m_4h['max_consecutive_losses']:<13} | {m_comb['max_consecutive_losses']:<14}")
    print(f"{'Net Profit on $10k (1% risk)':<32} | +${m_15m['net_profit_dollar']:<10} | +${m_1h['net_profit_dollar']:<10} | +${m_4h['net_profit_dollar']:<10} | +${m_comb['net_profit_dollar']:<11}")
    print(f"{'Account Return (%)':<32} | +{m_15m['return_pct']:<12}% | +{m_1h['return_pct']:<12}% | +{m_4h['return_pct']:<12}% | +{m_comb['return_pct']:<13}%")
    print(f"{'Max Drawdown (R)':<32} | -{m_15m['max_drawdown_r']:<11}R | -{m_1h['max_drawdown_r']:<11}R | -{m_4h['max_drawdown_r']:<11}R | -{m_comb['max_drawdown_r']:<12}R")
    print(f"{'Max Drawdown (%)':<32} | {m_15m['max_drawdown_pct']:<12}% | {m_1h['max_drawdown_pct']:<12}% | {m_4h['max_drawdown_pct']:<12}% | {m_comb['max_drawdown_pct']:<13}%")
    print(f"{'Max Drawdown ($ on $10k)':<32} | -${m_15m['max_drawdown_dollar']:<10} | -${m_1h['max_drawdown_dollar']:<10} | -${m_4h['max_drawdown_dollar']:<10} | -${m_comb['max_drawdown_dollar']:<11}")
    print("="*85)

if __name__ == "__main__":
    main()
