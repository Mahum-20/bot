import json

d = json.load(open('data/forex_gold_1year_backtest_oct2025_oct2026.json', 'r', encoding='utf-8'))
p = d['portfolio_summary']
print("=== OPTIMIZED 1-YEAR RESULTS (A+ ELIMINATED & 0.5*ATR_15M CUSHION) ===")
print(f"Total Trades: {p['total_trades']}, Wins: {p['wins']}, Losses: {p['losses']}")
print(f"Win Rate: {p['win_rate_pct']}%, Net R: {p['net_r']:+.2f}R, Profit Factor: {p['profit_factor']:.2f}")
print(f"Flat Balance: ${p['flat_final_balance']}, Comp Balance: ${p['comp_final_balance']}, MaxDD: {p['comp_max_dd_pct']}%")

print("\nBY SYMBOL:")
for sym, m in d['by_symbol'].items():
    print(f"{sym:<8} | Trades: {m['total_trades']:<4} | WinRate: {m['win_rate_pct']:>5.2f}% | Net R: {m['net_r']:>+7.2f}R | PF: {m['profit_factor']:>4.2f} | MaxDD: {m['comp_max_dd_pct']:>5.2f}%")

print("\nBY LEVEL CATEGORY:")
for cat, m in d['by_level_category'].items():
    print(f"{cat:<32} | Trades: {m['total_trades']:<4} | WinRate: {m['win_rate_pct']:>5.2f}% | Net R: {m['net_r']:>+7.2f}R | PF: {m['profit_factor']:>4.2f}")
