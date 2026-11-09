import json
from datetime import datetime, timezone

# Load the exact qualified trades
with open('data/october_2026_strict_audited_trades.json') as f:
    strict_data = json.load(f)

trades = strict_data['trades']

with open('data/btc_1m_oct2026_full.json') as f: c_1m = json.load(f)
with open('data/btc_5m_oct2026_full.json') as f: c_5m = json.load(f)

m1_map = {c['time']: idx for idx, c in enumerate(c_1m)}
m5_map = {c['time']: idx for idx, c in enumerate(c_5m)}

# 1. Re-evaluate every trade with FIXED 3RR TP
re_evaluated_trades = []

for t in trades:
    htf = t['htf']
    ltf = t['ltf']
    is_bull = (t['action'] == 'BUY')
    entry_p = t['entry_price']
    sl_p = t['sl_price']
    risk = t['risk']
    fixed_tp = round(entry_p + 3.0 * risk if is_bull else entry_p - 3.0 * risk, 2)

    candles = c_1m if ltf == '1m' else c_5m
    time_map = m1_map if ltf == '1m' else m5_map

    dt = datetime.strptime(t['entry_time'], '%Y-%m-%d %H:%M')
    entry_ts = int(dt.replace(tzinfo=timezone.utc).timestamp())

    start_idx = time_map.get(entry_ts)
    if start_idx is None:
        for i, c in enumerate(candles):
            if c['time'] >= entry_ts:
                start_idx = i
                break
    if start_idx is None:
        continue

    exit_time = None
    exit_price = None
    exit_reason = None
    outcome = None
    pnl_r = None

    for i in range(start_idx + 1, len(candles)):
        c = candles[i]
        c_high = c['high']
        c_low = c['low']

        hit_tp = (c_high >= fixed_tp) if is_bull else (c_low <= fixed_tp)
        hit_sl = (c_low <= sl_p) if is_bull else (c_high >= sl_p)

        if hit_tp and hit_sl:
            if abs(c['open'] - sl_p) <= abs(c['open'] - fixed_tp):
                hit_tp = False
            else:
                hit_sl = False

        if hit_tp:
            exit_time = c['time']
            exit_price = fixed_tp
            exit_reason = 'TP'
            outcome = 'WIN'
            pnl_r = 3.0
            break
        elif hit_sl:
            exit_time = c['time']
            exit_price = sl_p
            exit_reason = 'SL'
            outcome = 'LOSS'
            pnl_r = -1.0
            break

    if outcome is None:
        final_c = candles[-1]
        exit_time = final_c['time']
        exit_price = final_c['close']
        exit_reason = 'OPEN_AT_END'
        raw_r = ((final_c['close'] - entry_p) if is_bull else (entry_p - final_c['close'])) / risk
        outcome = 'WIN' if raw_r > 0 else 'LOSS'
        pnl_r = round(raw_r, 2)

    re_evaluated_trades.append({
        "id": t['id'],
        "htf": htf,
        "ltf": ltf,
        "action": t['action'],
        "entry_time": t['entry_time'],
        "entry_ts": entry_ts,
        "exit_time": datetime.fromtimestamp(exit_time, timezone.utc).strftime('%Y-%m-%d %H:%M'),
        "exit_ts": exit_time,
        "entry_price": entry_p,
        "sl_price": sl_p,
        "tp_price": fixed_tp,
        "risk": risk,
        "rr": 3.0,
        "pattern_name": t['pattern_name'],
        "level_name": t['level_name'],
        "box_name": t['box_name'],
        "exit_reason": exit_reason,
        "outcome": outcome,
        "pnl_r": pnl_r
    })

# Calendar Weeks
# Week 1: Oct 01 - Oct 07
# Week 2: Oct 08 - Oct 14
# Week 3: Oct 15 - Oct 21
# Week 4: Oct 22 - Oct 28
# Week 5: Oct 29 - Oct 31
weeks = [
    ("Week 1 (Oct 01 - Oct 07)", 1790812800, 1791417599),
    ("Week 2 (Oct 08 - Oct 14)", 1791417600, 1792022399),
    ("Week 3 (Oct 15 - Oct 21)", 1792022400, 1792627199),
    ("Week 4 (Oct 22 - Oct 28)", 1792627200, 1793231999),
    ("Week 5 (Oct 29 - Oct 31)", 1793232000, 1793491199),
]

def analyze_tf(tf_name, trade_subset):
    sorted_trades = sorted(trade_subset, key=lambda x: x['entry_ts'])
    wins = [t for t in sorted_trades if t['pnl_r'] > 0]
    losses = [t for t in sorted_trades if t['pnl_r'] <= 0]
    net_r = sum(t['pnl_r'] for t in sorted_trades)
    wr = (len(wins) / len(sorted_trades) * 100) if sorted_trades else 0
    pf = (sum(t['pnl_r'] for t in wins) / abs(sum(t['pnl_r'] for t in losses))) if losses and sum(t['pnl_r'] for t in losses) != 0 else 99

    peak_r = 0
    cum_r = 0
    max_dd_r = 0
    for t in sorted_trades:
        cum_r += t['pnl_r']
        if cum_r > peak_r: peak_r = cum_r
        if (peak_r - cum_r) > max_dd_r: max_dd_r = peak_r - cum_r

    # Risk models: 1%, 2%, 3% compounding on $1,000 initial
    def run_account(risk_pct):
        bal = 1000.0
        peak_bal = 1000.0
        max_dd_dollar = 0.0
        max_dd_pct = 0.0

        week_data = []
        for w_label, w_start, w_end in weeks:
            w_trades = [t for t in sorted_trades if w_start <= t['entry_ts'] <= w_end]
            w_start_bal = bal
            w_wins = len([t for t in w_trades if t['pnl_r'] > 0])
            w_losses = len([t for t in w_trades if t['pnl_r'] <= 0])
            w_net_r = sum(t['pnl_r'] for t in w_trades)

            for t in w_trades:
                risk_dollar = bal * risk_pct
                pnl_dollar = t['pnl_r'] * risk_dollar
                bal += pnl_dollar

                if bal > peak_bal: peak_bal = bal
                dd_d = peak_bal - bal
                dd_p = (dd_d / peak_bal * 100) if peak_bal > 0 else 0
                if dd_d > max_dd_dollar: max_dd_dollar = dd_d
                if dd_p > max_dd_pct: max_dd_pct = dd_p

            w_profit = bal - w_start_bal
            w_roi = (w_profit / w_start_bal * 100) if w_start_bal > 0 else 0
            week_data.append({
                "week": w_label,
                "trades": len(w_trades),
                "wins": w_wins,
                "losses": w_losses,
                "net_r": round(w_net_r, 2),
                "start_balance": round(w_start_bal, 2),
                "profit_dollar": round(w_profit, 2),
                "end_balance": round(bal, 2),
                "return_pct": round(w_roi, 2)
            })

        total_profit = bal - 1000.0
        total_roi = (total_profit / 1000.0 * 100)
        return {
            "final_balance": round(bal, 2),
            "net_profit": round(total_profit, 2),
            "total_roi": round(total_roi, 2),
            "max_drawdown_dollar": round(max_dd_dollar, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "weeks": week_data
        }

    # Also fixed dollar risk (non-compounding $10, $20, $30 per trade)
    def run_account_fixed(risk_pct):
        bal = 1000.0
        peak_bal = 1000.0
        max_dd_dollar = 0.0
        max_dd_pct = 0.0
        dollar_risk = 1000.0 * risk_pct

        week_data = []
        for w_label, w_start, w_end in weeks:
            w_trades = [t for t in sorted_trades if w_start <= t['entry_ts'] <= w_end]
            w_start_bal = bal
            w_wins = len([t for t in w_trades if t['pnl_r'] > 0])
            w_losses = len([t for t in w_trades if t['pnl_r'] <= 0])
            w_net_r = sum(t['pnl_r'] for t in w_trades)

            for t in w_trades:
                pnl_dollar = t['pnl_r'] * dollar_risk
                bal += pnl_dollar

                if bal > peak_bal: peak_bal = bal
                dd_d = peak_bal - bal
                dd_p = (dd_d / peak_bal * 100) if peak_bal > 0 else 0
                if dd_d > max_dd_dollar: max_dd_dollar = dd_d
                if dd_p > max_dd_pct: max_dd_pct = dd_p

            w_profit = bal - w_start_bal
            w_roi = (w_profit / w_start_bal * 100) if w_start_bal > 0 else 0
            week_data.append({
                "week": w_label,
                "trades": len(w_trades),
                "wins": w_wins,
                "losses": w_losses,
                "net_r": round(w_net_r, 2),
                "start_balance": round(w_start_bal, 2),
                "profit_dollar": round(w_profit, 2),
                "end_balance": round(bal, 2),
                "return_pct": round(w_roi, 2)
            })

        total_profit = bal - 1000.0
        total_roi = (total_profit / 1000.0 * 100)
        return {
            "final_balance": round(bal, 2),
            "net_profit": round(total_profit, 2),
            "total_roi": round(total_roi, 2),
            "max_drawdown_dollar": round(max_dd_dollar, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "weeks": week_data
        }

    return {
        "tf": tf_name,
        "total_trades": len(sorted_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(wr, 2),
        "gross_profit_r": round(sum(t['pnl_r'] for t in wins), 2),
        "gross_loss_r": round(abs(sum(t['pnl_r'] for t in losses)), 2),
        "net_pnl_r": round(net_r, 2),
        "profit_factor": round(pf, 2),
        "max_drawdown_r": round(max_dd_r, 2),
        "compounding": {
            "1pct": run_account(0.01),
            "2pct": run_account(0.02),
            "3pct": run_account(0.03)
        },
        "fixed": {
            "1pct": run_account_fixed(0.01),
            "2pct": run_account_fixed(0.02),
            "3pct": run_account_fixed(0.03)
        }
    }

m15_res = analyze_tf("15m", [t for t in re_evaluated_trades if t['htf'] == '15m'])
h1_res = analyze_tf("1h", [t for t in re_evaluated_trades if t['htf'] == '1h'])
h4_res = analyze_tf("4h", [t for t in re_evaluated_trades if t['htf'] == '4h'])
comb_res = analyze_tf("combined", re_evaluated_trades)

results = {
    "m15": m15_res,
    "h1": h1_res,
    "h4": h4_res,
    "combined": comb_res
}

with open('data/fixed_3rr_week_by_week.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\n--- RESULTS READY ---")
for k, res in results.items():
    print(f"\n[{k.upper()}] Trades: {res['total_trades']}, Wins: {res['wins']}, Losses: {res['losses']}, WR: {res['win_rate']}%, Net: {res['net_pnl_r']:+}R, MaxDD: -{res['max_drawdown_r']}R")
    c1 = res['compounding']['1pct']
    c2 = res['compounding']['2pct']
    c3 = res['compounding']['3pct']
    print(f"  Compounding 1% -> Final: ${c1['final_balance']} ({c1['total_roi']:+}%), MaxDD: {c1['max_drawdown_pct']}% (-${c1['max_drawdown_dollar']})")
    print(f"  Compounding 2% -> Final: ${c2['final_balance']} ({c2['total_roi']:+}%), MaxDD: {c2['max_drawdown_pct']}% (-${c2['max_drawdown_dollar']})")
    print(f"  Compounding 3% -> Final: ${c3['final_balance']} ({c3['total_roi']:+}%), MaxDD: {c3['max_drawdown_pct']}% (-${c3['max_drawdown_dollar']})")

    f1 = res['fixed']['1pct']
    f2 = res['fixed']['2pct']
    f3 = res['fixed']['3pct']
    print(f"  Fixed Risk  1% -> Final: ${f1['final_balance']} ({f1['total_roi']:+}%), MaxDD: {f1['max_drawdown_pct']}% (-${f1['max_drawdown_dollar']})")
    print(f"  Fixed Risk  2% -> Final: ${f2['final_balance']} ({f2['total_roi']:+}%), MaxDD: {f2['max_drawdown_pct']}% (-${f2['max_drawdown_dollar']})")
    print(f"  Fixed Risk  3% -> Final: ${f3['final_balance']} ({f3['total_roi']:+}%), MaxDD: {f3['max_drawdown_pct']}% (-${f3['max_drawdown_dollar']})")
