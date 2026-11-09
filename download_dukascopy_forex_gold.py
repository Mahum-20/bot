"""
Download 1-Year Forex & Gold historical data from Dukascopy Bank ECN Feed
========================================================================
Downloads:
  - EUR-USD
  - GBP-USD
  - XAU-USD
Timeframes: 4h, 1h, 15m, 5m, 1m
Format: [{"time": int, "open": float, "high": float, "low": float, "close": float, "volume": float}]
"""
import os
import sys
import json
import time
from datetime import datetime, timezone

from dukascopy_python import fetch_candles, TimeUnit, OfferSide

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SYMBOLS = [
    ("EURUSD", "EUR-USD"),
    ("GBPUSD", "GBP-USD"),
    ("XAUUSD", "XAU-USD")
]

TF_CONFIG = [
    # (tf_str, interval, TimeUnit, start_date)
    ("4h", 4, TimeUnit.HOUR, datetime(2025, 5, 1, tzinfo=timezone.utc)),
    ("1h", 1, TimeUnit.HOUR, datetime(2025, 7, 1, tzinfo=timezone.utc)),
    ("15m", 15, TimeUnit.MINUTE, datetime(2025, 9, 1, tzinfo=timezone.utc)),
    ("5m", 5, TimeUnit.MINUTE, datetime(2025, 9, 20, tzinfo=timezone.utc)),
    ("1m", 1, TimeUnit.MINUTE, datetime(2025, 9, 30, tzinfo=timezone.utc)),
]

END_DATE = datetime(2026, 10, 2, tzinfo=timezone.utc)

def main():
    for sym_clean, duka_sym in SYMBOLS:
        print(f"\n==========================================")
        print(f"  Downloading {sym_clean} ({duka_sym})")
        print(f"==========================================")
        for tf_str, interval, time_unit, start_date in TF_CONFIG:
            out_file = os.path.join(DATA_DIR, f"{sym_clean.lower()}_{tf_str}_1y_oct2025_oct2026.json")
            if os.path.exists(out_file) and os.path.getsize(out_file) > 1000:
                print(f"[EXISTS] {sym_clean}_{tf_str} already exists ({os.path.getsize(out_file)/1024:.1f} KB), skipping.")
                continue

            print(f"[FETCHING] {sym_clean} {tf_str} from {start_date.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')}...", flush=True)
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
                print(f"[ERROR] Failed to fetch {sym_clean} {tf_str}: {e}")
                continue

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
            print(f"[DONE] Saved {len(formatted)} candles to {os.path.basename(out_file)} ({os.path.getsize(out_file)/1024/1024:.2f} MB) in {elapsed:.1f}s", flush=True)

if __name__ == "__main__":
    main()
