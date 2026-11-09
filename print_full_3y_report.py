import json

d = json.load(open('data/forex_gold_3years_8pairs_backtest.json', 'r', encoding='utf-8'))

print("=== PORTFOLIO SUMMARY ===")
p = d['portfolio_summary']
print(f"Total Trades: {p['total_trades']}, Wins: {p['wins']}, Losses: {p['losses']}")
print(f"Win Rate: {p['win_rate_pct']}%, Net R: {p['net_r']}R, Profit Factor: {p['profit_factor']}")
print(f"Flat Balance: ${p['flat_final_balance']}, Comp Balance: ${p['comp_final_balance']}, MaxDD: {p['comp_max_dd_pct']}%")

print("\n=== BY YEAR PERIOD ===")
for k, v in d['by_year_period'].items():
    print(f"{k:<30} | Trades: {v['total_trades']:<4} | WinRate: {v['win_rate_pct']:>5.2f}% | Net R: {v['net_r']:>+8.2f}R | PF: {v['profit_factor']:>4.2f} | MaxDD: {v['comp_max_dd_pct']:>5.2f}%")

print("\n=== BY CALENDAR YEAR ===")
for k, v in d['by_calendar_year'].items():
    print(f"{k:<10} | Trades: {v['total_trades']:<4} | WinRate: {v['win_rate_pct']:>5.2f}% | Net R: {v['net_r']:>+8.2f}R | PF: {v['profit_factor']:>4.2f} | MaxDD: {v['comp_max_dd_pct']:>5.2f}%")

print("\n=== BY SESSION ===")
for k, v in d['by_session'].items():
    print(f"{k:<35} | Trades: {v['total_trades']:<4} | WinRate: {v['win_rate_pct']:>5.2f}% | Net R: {v['net_r']:>+8.2f}R | PF: {v['profit_factor']:>4.2f} | MaxDD: {v['comp_max_dd_pct']:>5.2f}%")

print("\n=== BY SYMBOL ===")
for k, v in d['by_symbol'].items():
    print(f"{k:<10} | Trades: {v['total_trades']:<4} | WinRate: {v['win_rate_pct']:>5.2f}% | Net R: {v['net_r']:>+8.2f}R | PF: {v['profit_factor']:>4.2f} | MaxDD: {v['comp_max_dd_pct']:>5.2f}%")

print("\n=== BY TIMEFRAME ===")
for k, v in d['by_timeframe'].items():
    print(f"{k:<10} | Trades: {v['total_trades']:<4} | WinRate: {v['win_rate_pct']:>5.2f}% | Net R: {v['net_r']:>+8.2f}R | PF: {v['profit_factor']:>4.2f} | MaxDD: {v['comp_max_dd_pct']:>5.2f}%")

print("\n=== BY LEVEL CATEGORY ===")
for k, v in d['by_level_category'].items():
    print(f"{k:<32} | Trades: {v['total_trades']:<4} | WinRate: {v['win_rate_pct']:>5.2f}% | Net R: {v['net_r']:>+8.2f}R | PF: {v['profit_factor']:>4.2f}")

print("\n=== LOSS FORENSICS ===")
print(json.dumps(d['loss_forensics'], indent=2))
