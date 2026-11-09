import json
from faithful_backtest_engine import FaithfulBacktestEngine

engine = FaithfulBacktestEngine(symbol="BTCUSDT", htf_tf="4h", ltf_tf="5m")
# Let's inspect how many trades FaithfulBacktestEngine generates when tr_time >= c_time
print("Initialized FaithfulBacktestEngine")
