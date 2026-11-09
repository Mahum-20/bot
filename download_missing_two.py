import os, json, time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dukascopy_python import fetch_candles, TimeUnit, OfferSide

start_date = datetime(2023, 10, 1, tzinfo=timezone.utc)
end_date = datetime(2026, 11, 1, tzinfo=timezone.utc)
data_dir = "data"

def fetch_pair(item):
    sym_clean, duka_sym = item
    out_file = os.path.join(data_dir, f"{sym_clean.lower()}_1m_3y_2023_2026.json")
    print(f"Starting {sym_clean} 1m download...", flush=True)
    t0 = time.time()
    raw = list(fetch_candles(duka_sym, 1, TimeUnit.MINUTE, OfferSide.BID, start_date, end_date))
    formatted = [{"time": int(c.timestamp.timestamp()), "open": float(c.open), "high": float(c.high), "low": float(c.low), "close": float(c.close), "volume": float(c.volume)} for c in raw]
    formatted.sort(key=lambda x: x["time"])
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f)
    elapsed = time.time() - t0
    return f"Completed {sym_clean}: {len(formatted)} candles in {elapsed:.1f}s ({os.path.getsize(out_file)/1024/1024:.1f} MB)"

pairs = [("NZDUSD", "NZD-USD"), ("GBPJPY", "GBP-JPY")]
with ThreadPoolExecutor(max_workers=2) as ex:
    futs = [ex.submit(fetch_pair, p) for p in pairs]
    for fut in as_completed(futs):
        print(fut.result(), flush=True)
