from faithful_backtest_engine import FaithfulBacktestEngine, is_valid_tap_approach

e = FaithfulBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m")
# Let's inspect active boxes and touches
print(f"Loaded {len(e.c_htf)} 4H bars, {len(e.c_ltf)} 5M bars")
for i in range(2000, 3000):
    c = e.c_ltf[i]
    # check if any box touched
    # print when touched
