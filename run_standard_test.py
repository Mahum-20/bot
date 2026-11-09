"""
Standard Realtime-Equivalent Replay Tester
===========================================
Simulates exact live-bot execution bar-by-bar across HTF + LTF combinations:
  - 4h HTF  -> 5m LTF: Fixed 3.0 RR
  - 1h HTF  -> 1m LTF: Nearest Liquidity (Min 2.5 RR Floor, skip if < 2.5 RR)
  - 15m HTF -> 1m LTF: Nearest Liquidity (Min 2.5 RR Floor, skip if < 2.5 RR)

Rules Enforced:
  1. Valid Zone Tap Approach: Demand tapped from upside, Supply tapped from downside.
  2. Strict Zone Entry Requirement: LTF reversal structure must originate from zone tap extreme.
  3. Retest Boundary Check: Retest level & confirming candle pattern must touch within/at HTF zone boundary.
  4. User Target Rule:
     - 4H: Fixed 3.0 RR
     - 1H & 15M: Target Nearest Liquidity (Opposing zone / swing pivot). If RR < 2.5R, skip trade.
  5. Single Active Position: No overlapping trade entry until active trade hits SL or TP.
"""

import sys, os
sys.path.append(os.getcwd())
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
from htf_engine import HTFEngine
import ltf_approach_engine

def run_standard_replay(
    htf_name: str,
    ltf_name: str,
    c_htf: List[Dict],
    c_ltf: List[Dict],
    htf_sec: int,
    min_rr: float = 2.5,
    fixed_rr: Optional[float] = None,
    start_ts: int = 1790812800, # Oct 1, 2026 00:00 UTC
    end_ts: int = 1793491200    # Oct 31, 2026 23:59 UTC
) -> Dict:
    # 1. Map HTF Zones
    htf_engine = HTFEngine(lookback_bars=len(c_htf), show_tjl_boxes=True, tjl_extend=True, start_marking_time=start_ts)
    htf_boxes = htf_engine.run(c_htf).get('boxes', [])

    trades = []
    skipped_trades = []
    active_trade = None

    box_state = {}     # b_key -> 'READY' or 'LOCKED'
    box_last_tap = {}  # b_key -> timestamp

    # Chronological Bar-by-Bar Replay
    for c in c_ltf:
        c_time = c['time']
        if c_time < start_ts or c_time > end_ts:
            continue

        c_high = c['high']
        c_low = c['low']

        # ------------------------------------------------------------------
        # Step 1: Manage Active Position (Exits via SL or TP)
        # ------------------------------------------------------------------
        if active_trade:
            if c_time > active_trade['entry_time']:
                is_bull = (active_trade['action'] == 'BUY')
                tp = active_trade['tp_price']
                sl = active_trade['sl_price']

                hit_tp = (c_high >= tp) if is_bull else (c_low <= tp)
                hit_sl = (c_low <= sl) if is_bull else (c_high >= sl)

                if hit_tp and hit_sl:
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

        # ------------------------------------------------------------------
        # Step 2: Unlock HTF Zones when price moves completely outside
        # ------------------------------------------------------------------
        for b in htf_boxes:
            b_key = f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}"
            b_top = max(b.get('top', 0), b.get('bottom', 0))
            b_bot = min(b.get('top', 0), b.get('bottom', 0))
            if not (c_high >= b_bot and c_low <= b_top):
                if box_state.get(b_key) == 'LOCKED' and (c_time - box_last_tap.get(b_key, 0) >= 3600):
                    box_state[b_key] = 'READY'

        # ------------------------------------------------------------------
        # Step 3: Check New HTF Zone Taps & LTF Confirmation
        # ------------------------------------------------------------------
        for b in htf_boxes:
            b_key = f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}"
            b_top = max(b.get('top', 0), b.get('bottom', 0))
            b_bot = min(b.get('top', 0), b.get('bottom', 0))

            if c_high >= b_bot and c_low <= b_top:
                if box_state.get(b_key, 'READY') == 'READY':
                    box_state[b_key] = 'LOCKED'
                    box_last_tap[b_key] = c_time

                    res = ltf_approach_engine.compute_ltf_approach_structure(
                        target_time=c_time,
                        ltf_candles=c_ltf,
                        htf_boxes=htf_boxes,
                        htf_sec=htf_sec,
                        htf_candles=c_htf
                    )
                    tap_info = res.get('tap_info')
                    if tap_info and tap_info.get('trade'):
                        tr = tap_info['trade']
                        if tr.get('time') >= c_time:
                            entry_p = tr['entry_price']
                            sl_p = tr['sl_price']
                            risk = tr['risk']
                            is_bull = (tr['action'] == 'BUY')

                            # Determine TP and RR according to timeframe rule
                            if fixed_rr is not None or htf_sec >= 14400:
                                chosen_rr = fixed_rr if fixed_rr is not None else 3.0
                                planned_tp = round(entry_p + chosen_rr * risk if is_bull else entry_p - chosen_rr * risk, 2)
                                planned_rr = chosen_rr
                                planned_reward = round(chosen_rr * risk, 2)
                            else:
                                planned_tp = tr['tp_price']
                                planned_rr = tr['rr']
                                planned_reward = tr['reward']

                            # Check RR Filter (Skip if RR < min_rr)
                            if planned_rr < min_rr:
                                skipped_trades.append({
                                    "time": tr['time'],
                                    "action": tr['action'],
                                    "entry_price": entry_p,
                                    "tp_price": planned_tp,
                                    "rr": planned_rr,
                                    "reason": f"RR {planned_rr}R < minimum {min_rr}R"
                                })
                                continue

                            active_trade = {
                                "id": f"{htf_name}_{tr['time']}",
                                "htf": htf_name,
                                "ltf": ltf_name,
                                "action": tr["action"],
                                "entry_time": tr["time"],
                                "entry_price": entry_p,
                                "sl_price": sl_p,
                                "tp_price": planned_tp,
                                "risk": risk,
                                "reward": planned_reward,
                                "rr": planned_rr,
                                "pattern_name": tr["pattern_name"],
                                "level_name": tr["level_name"],
                                "box_name": b.get('text') or 'HTF Zone'
                            }
                            break

    # If trade remained open at end of month
    if active_trade:
        final_c = c_ltf[-1]
        active_trade['exit_time'] = final_c['time']
        active_trade['exit_price'] = final_c['close']
        active_trade['exit_reason'] = 'OPEN_AT_END'
        is_bull = (active_trade['action'] == 'BUY')
        raw_r = ((final_c['close'] - active_trade['entry_price']) if is_bull else (active_trade['entry_price'] - final_c['close'])) / active_trade['risk']
        active_trade['outcome'] = 'WIN' if raw_r > 0 else 'LOSS'
        active_trade['pnl_r'] = round(raw_r, 2)
        trades.append(active_trade)

    return {
        "htf": htf_name,
        "ltf": ltf_name,
        "executed_trades": trades,
        "skipped_trades": skipped_trades
    }

def compute_metrics(trades_list, initial_capital=1000.0):
    if not trades_list:
        return {"total": 0, "wins": 0, "losses": 0, "wr": 0.0, "net_r": 0.0, "pf": 0.0, "max_dd_r": 0.0}

    wins = [t for t in trades_list if t['pnl_r'] > 0]
    losses = [t for t in trades_list if t['pnl_r'] <= 0]
    wr = len(wins) / len(trades_list) * 100
    gp = sum(t['pnl_r'] for t in wins)
    gl = abs(sum(t['pnl_r'] for t in losses))
    net_r = gp - gl
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0)

    cum_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    for t in sorted(trades_list, key=lambda x: x['entry_time']):
        cum_r += t['pnl_r']
        if cum_r > peak_r: peak_r = cum_r
        dd = peak_r - cum_r
        if dd > max_dd_r: max_dd_r = dd

    return {
        "total": len(trades_list),
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(wr, 1),
        "net_r": round(net_r, 2),
        "pf": round(pf, 2),
        "max_dd_r": round(max_dd_r, 2)
    }

def run_capital_simulation(trades_list, initial_capital=1000.0):
    sorted_trades = sorted(trades_list, key=lambda x: x['entry_time'])
    weeks = [
        ("Week 1 (Oct 01 - Oct 07)", 1790812800, 1791417599),
        ("Week 2 (Oct 08 - Oct 14)", 1791417600, 1792022399),
        ("Week 3 (Oct 15 - Oct 21)", 1792022400, 1792627199),
        ("Week 4 (Oct 22 - Oct 28)", 1792627200, 1793231999),
        ("Week 5 (Oct 29 - Oct 31)", 1793232000, 1793491200)
    ]

    out = {}
    for risk_pct in [0.01, 0.02, 0.03]:
        r_key = f"{int(risk_pct*100)}pct"
        # Compounding
        bal = initial_capital
        peak = initial_capital
        max_dd_d = 0.0
        max_dd_p = 0.0
        week_data = []

        for w_label, w_start, w_end in weeks:
            w_trades = [t for t in sorted_trades if w_start <= t['entry_time'] <= w_end]
            w_start_bal = bal
            w_wins = len([t for t in w_trades if t['pnl_r'] > 0])
            w_losses = len([t for t in w_trades if t['pnl_r'] <= 0])
            w_net_r = sum(t['pnl_r'] for t in w_trades)

            for t in w_trades:
                risk_d = bal * risk_pct
                pnl_d = t['pnl_r'] * risk_d
                bal += pnl_d
                if bal > peak: peak = bal
                dd_d = peak - bal
                dd_p = dd_d / peak * 100 if peak > 0 else 0
                if dd_d > max_dd_d: max_dd_d = dd_d
                if dd_p > max_dd_p: max_dd_p = dd_p

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

        tot_profit = bal - initial_capital
        tot_roi = (tot_profit / initial_capital * 100)
        
        # Fixed Dollar Risk (non-compounding)
        f_bal = initial_capital
        f_peak = initial_capital
        f_max_dd_d = 0.0
        f_max_dd_p = 0.0
        d_risk = initial_capital * risk_pct
        for t in sorted_trades:
            pnl_d = t['pnl_r'] * d_risk
            f_bal += pnl_d
            if f_bal > f_peak: f_peak = f_bal
            dd_d = f_peak - f_bal
            dd_p = dd_d / f_peak * 100 if f_peak > 0 else 0
            if dd_d > f_max_dd_d: f_max_dd_d = dd_d
            if dd_p > f_max_dd_p: f_max_dd_p = dd_p

        f_profit = f_bal - initial_capital
        f_roi = (f_profit / initial_capital * 100)

        out[r_key] = {
            "compounding": {
                "final_balance": round(bal, 2),
                "net_profit": round(tot_profit, 2),
                "total_roi": round(tot_roi, 2),
                "max_drawdown_dollar": round(max_dd_d, 2),
                "max_drawdown_pct": round(max_dd_p, 2),
                "weeks": week_data
            },
            "fixed": {
                "final_balance": round(f_bal, 2),
                "net_profit": round(f_profit, 2),
                "total_roi": round(f_roi, 2),
                "max_drawdown_dollar": round(f_max_dd_d, 2),
                "max_drawdown_pct": round(f_max_dd_p, 2)
            }
        }
    return out

if __name__ == '__main__':
    with open('data/btc_15m_oct2026_full.json') as f: c_15m = json.load(f)
    with open('data/btc_1h_oct2026_full.json') as f: c_1h = json.load(f)
    with open('data/btc_4h_oct2026_full.json') as f: c_4h = json.load(f)
    with open('data/btc_1m_oct2026_full.json') as f: c_1m = json.load(f)
    with open('data/btc_5m_oct2026_full.json') as f: c_5m = json.load(f)

    print("======================================================================")
    print("STANDARD REPLAY TEST: 4H FIXED 3RR | 1H & 15M NEAREST LIQUIDITY (MIN 2.5 RR)")
    print("======================================================================")
    # 4H: Fixed 3RR
    r_4h = run_standard_replay('4h', '5m', c_4h, c_5m, 14400, min_rr=2.5, fixed_rr=3.0)
    # 1H & 15M: Nearest Liquidity (Min 2.5 RR)
    r_1h = run_standard_replay('1h', '1m', c_1h, c_1m, 3600, min_rr=2.5, fixed_rr=None)
    r_15m = run_standard_replay('15m', '1m', c_15m, c_1m, 900, min_rr=2.5, fixed_rr=None)

    m_4h = compute_metrics(r_4h['executed_trades'])
    m_1h = compute_metrics(r_1h['executed_trades'])
    m_15m = compute_metrics(r_15m['executed_trades'])
    all_trades = r_4h['executed_trades'] + r_1h['executed_trades'] + r_15m['executed_trades']
    m_comb = compute_metrics(all_trades)

    cap_4h = run_capital_simulation(r_4h['executed_trades'])
    cap_1h = run_capital_simulation(r_1h['executed_trades'])
    cap_15m = run_capital_simulation(r_15m['executed_trades'])
    cap_comb = run_capital_simulation(all_trades)

    print(f"\n4H -> 5M (Fixed 3RR) : Executed={m_4h['total']}, Wins={m_4h['wins']}, Losses={m_4h['losses']}, WR={m_4h['wr']}%, Net={m_4h['net_r']}R, MaxDD=-{m_4h['max_dd_r']}R, PF={m_4h['pf']}")
    print(f"1H -> 1M (Nearest Liq): Executed={m_1h['total']}, Wins={m_1h['wins']}, Losses={m_1h['losses']}, WR={m_1h['wr']}%, Net={m_1h['net_r']}R, MaxDD=-{m_1h['max_dd_r']}R, PF={m_1h['pf']}")
    print(f"15M-> 1M (Nearest Liq): Executed={m_15m['total']}, Wins={m_15m['wins']}, Losses={m_15m['losses']}, WR={m_15m['wr']}%, Net={m_15m['net_r']}R, MaxDD=-{m_15m['max_dd_r']}R, PF={m_15m['pf']}")
    print(f"COMBINED TOTAL        : Executed={m_comb['total']}, Wins={m_comb['wins']}, Losses={m_comb['losses']}, WR={m_comb['wr']}%, Net={m_comb['net_r']}R, MaxDD=-{m_comb['max_dd_r']}R, PF={m_comb['pf']}")

    # Clean formatted trades for logging
    clean_trades = []
    for t in sorted(all_trades, key=lambda x: x['entry_time']):
        clean_trades.append({
            "id": t['id'],
            "htf": t['htf'],
            "ltf": t['ltf'],
            "action": t['action'],
            "entry_time": datetime.fromtimestamp(t['entry_time'], timezone.utc).strftime('%Y-%m-%d %H:%M'),
            "exit_time": datetime.fromtimestamp(t['exit_time'], timezone.utc).strftime('%Y-%m-%d %H:%M'),
            "entry_price": t['entry_price'],
            "sl_price": t['sl_price'],
            "tp_price": t['tp_price'],
            "risk": t['risk'],
            "reward": t['reward'],
            "rr": t['rr'],
            "outcome": t['outcome'],
            "pnl_r": t['pnl_r'],
            "level_name": t['level_name'],
            "box_name": t['box_name']
        })

    with open('data/standard_replay_october_trades.json', 'w') as f:
        json.dump({
            "metrics": {
                "4h": m_4h, "1h": m_1h, "15m": m_15m, "combined": m_comb
            },
            "capital": {
                "4h": cap_4h, "1h": cap_1h, "15m": cap_15m, "combined": cap_comb
            },
            "trades": clean_trades
        }, f, indent=2)

    print("\nResults successfully saved to data/standard_replay_october_trades.json")
