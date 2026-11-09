from faithful_backtest_engine import FaithfulBacktestEngine
import bisect

e = FaithfulBacktestEngine('BTCUSDT', '4h', '5m')
start_ts = e.c_htf[200]["time"]
end_ts = e.c_ltf[-1]["time"]
ltf_start_idx = bisect.bisect_left(e.ltf_times, start_ts)
ltf_end_idx = bisect.bisect_right(e.ltf_times, end_ts)

print(f"Looping from {ltf_start_idx} to {ltf_end_idx} (total {ltf_end_idx - ltf_start_idx} bars)")

cycles_opened = 0
for i in range(ltf_start_idx, ltf_start_idx + 1000):
    c_curr = e.c_ltf[i]
    c_time = c_curr["time"]
    h_idx = bisect.bisect_right(e.htf_times, c_time - e.htf_sec)
    if h_idx < 25:
        continue
    # let's see how many active boxes
