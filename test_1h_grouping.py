import json
from datetime import datetime, timezone

# Let's inspect what happens to the 15 trades if we apply the immutable zone lock
trades = json.load(open('data/oct_2026_backtest_results.json'))['timeframe_1h_1m']['trades']

# Let's group trades by their underlying level
# Trade 1 & 2: Double Bottom around 83150-83188 (formed Oct 08 / Oct 11)
# Trade 3: Double Bottom at 80813
# Trade 4: TJL1 at 82389
# Trade 5: TJL1 at 82594
# Trade 6, 7, 8: TJL1 at 82854-82982
# Trade 9: Double Bottom at 80809
# Trade 10, 11, 12, 13, 14: Double Bottom at 80316-80645
# Trade 15: Double Bottom at 79875
print("Grouped Analysis of 1H Trades:")
print("Trades 6, 7, 8 are 3 trades on ONE SINGLE TJL1 level.")
print("Trades 10, 11, 12, 13, 14 are 5 trades on ONE SINGLE Double Bottom level.")
print("Trades 1, 2 are 2 trades on ONE SINGLE Double Bottom level.")
