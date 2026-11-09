from faithful_backtest_engine import FaithfulBacktestEngine
import time

t0 = time.time()
engine = FaithfulBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m")
res = engine.run_backtest()
t1 = time.time()
print(f"4H->5M finished in {t1 - t0:.1f}s")
print(f"Total trades: {len(res['trades'])}")
for t in res['trades']:
    print(f"Trade {t['action']} at {t['open_time']} (exit {t['exit_time']}): outcome={t['outcome']}, pnl_r={t['pnl_r']}, pnl_usd=${t['pnl_usd']}")
