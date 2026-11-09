import json
from datetime import datetime, timezone

with open("data/faithful_btc_1y_backtest_results.json") as f:
    data = json.load(f)

trades = data["unified_portfolio"]["trades"]
print(f"Total Unified Trades: {len(trades)}")
for idx, t in enumerate(trades, 1):
    open_dt = datetime.fromtimestamp(t["open_time"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    exit_dt = datetime.fromtimestamp(t["exit_time"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"{idx}. {t['htf'].upper()}->{t['ltf'].upper()} | {t['action']} | Open: {open_dt} @ {t['entry_price']:.2f} | Exit: {exit_dt} @ {t['exit_price']:.2f} | Reason: {t['exit_reason']} | PnL: {t['pnl_r']}R (${t['compounded_pnl_usd']}) | Bal After: ${t['compounded_balance_after']} | Level: {t.get('level_name')} | Pattern: {t.get('pattern_name')}")
