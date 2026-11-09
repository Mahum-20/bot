"""
Download 3-Year Historical Data for 8 Major Forex & Metals Pairs from Dukascopy
================================================================================
Symbols:
  1. XAUUSD (Gold)
  2. EURUSD
  3. GBPUSD
  4. USDJPY
  5. USDCAD
  6. AUDUSD
  7. NZDUSD
  8. GBPJPY

Timeframes:
  - 4h (from 2023-05-01)
  - 1h (from 2023-07-01)
  - 15m (from 2023-09-01)
  - 5m (from 2023-09-20)
  - 1m (from 2023-10-01 to 2026-11-01)
"""
import os
import sys
import json
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from dukascopy_python import fetch_candles, TimeUnit, OfferSide

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SYMBOLS = [
    ("XAUUSD", "XAU-USD"),
    ("EURUSD", "EUR-USD"),
    ("GBPUSD", "GBP-USD"),
    ("USDJPY", "USD-JPY"),
    ("USDCAD", "USD-CAD"),
    ("AUDUSD", "AUD-USD"),
    ("NZDUSD", "NZD-USD"),
    ("GBPJPY", "GBP-JPY")
]

TF_CONFIG = [
    # (tf_str, interval, TimeUnit, start_date)
    ("4h", 4, TimeUnit.HOUR, datetime(2023, 5, 1, tzinfo=timezone.utc)),
    ("1h", 1, TimeUnit.HOUR, datetime(2023, 7, 1, tzinfo=timezone.utc)),
    ("15m", 15, TimeUnit.MINUTE, datetime(2023, 9, 1, tzinfo=timezone.utc)),
    ("5m", 5, TimeUnit.MINUTE, datetime(2023, 9, 20, tzinfo=timezone.utc)),
    ("1m", 1, TimeUnit.MINUTE, datetime(2023, 10, 1, tzinfo=timezone.utc)),
]

END_DATE = datetime(2026, 11, 1, tzinfo=timezone.utc)

def download_task(item):
    sym_clean, duka_sym, tf_str, interval, time_unit, start_date = item
    out_file = os.path.join(DATA_DIR, f"{sym_clean.lower()}_{tf_str}_3y_2023_2026.json")
    
    if os.path.exists(out_file) and os.path.getsize(out_file) > 5000:
        return f"[EXISTS] {sym_clean}_{tf_str} ({os.path.getsize(out_file)/1024/1024:.1f} MB)"

    t0 = time.time()
    try:
        raw_candles = list(fetch_candles(
            instrument=duka_sym,
            interval=interval,
            time_unit=time_unit,
            offer_side=OfferSide.BID,
            start=start_date,
            end=END_DATE
        ))
    except Exception as e:
        return f"[ERROR] {sym_clean}_{tf_str}: {e}"

    if not raw_candles:
        return f"[EMPTY] {sym_clean}_{tf_str} returned no candles"

    formatted = []
    for c in raw_candles:
        formatted.append({
            "time": int(c.timestamp.timestamp()),
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": float(c.volume)
        })

    formatted.sort(key=lambda x: x["time"])
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f)

    elapsed = time.time() - t0
    size_mb = os.path.getsize(out_file) / (1024 * 1024)
    return f"[DONE] {sym_clean}_{tf_str}: {len(formatted)} candles ({size_mb:.2f} MB) in {elapsed:.1f}s"

def main():
    print("=" * 70)
    print(" DUKASCOPY 3-YEAR MULTI-ASSET DOWNLOADER (8 PAIRS)")
    print("=" * 70)
    
    tasks = []
    # Queue HTF tasks first (quick), then 1m tasks
    for tf_str, interval, time_unit, start_date in TF_CONFIG:
        for sym_clean, duka_sym in SYMBOLS:
            tasks.append((sym_clean, duka_sym, tf_str, interval, time_unit, start_date))

    print(f"Total download tasks: {len(tasks)}")
    t_start = time.time()
    
    # Run with 6 worker threads
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(download_task, task): task for task in tasks}
        completed = 0
        for fut in as_completed(futures):
            completed += 1
            res = fut.result()
            print(f"[{completed}/{len(tasks)}] {res}", flush=True)

    print(f"\nAll downloads completed in {time.time() - t_start:.1f} seconds.")

if __name__ == "__main__":
    main()
