from faithful_backtest_engine import FaithfulBacktestEngine

engine = FaithfulBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m")
# Let's inspect cycles opened during the backtest
start_idx = 2000
for i in range(len(engine.c_ltf)):
    c = engine.c_ltf[i]
    # let's see how many cycles opened
