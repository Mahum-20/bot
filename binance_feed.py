import asyncio
import json
import logging
import requests
import websockets
from typing import List, Dict, Callable, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Binance API Endpoints
BINANCE_SPOT_REST = "https://api.binance.com/api/v3/klines"
BINANCE_SPOT_WS   = "wss://stream.binance.com:9443/ws"

BINANCE_FUTURES_REST = "https://fapi.binance.com/fapi/v1/klines"
BINANCE_FUTURES_WS   = "wss://fstream.binance.com/ws"

def fetch_klines(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 1000, market_type: str = "futures") -> List[Dict]:
    """
    Fetch historical OHLCV kline data from Binance API (Futures or Spot).
    Returns a list of candle dicts: {'time', 'open', 'high', 'low', 'close', 'volume'}
    """
    rest_url = BINANCE_FUTURES_REST if market_type.lower() == "futures" else BINANCE_SPOT_REST
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": min(limit, 1000)
    }
    logging.info(f"Fetching {limit} historical {interval} candles for {symbol} ({market_type.upper()}) from Binance...")
    
    for attempt in range(1, 4):
        try:
            resp = requests.get(rest_url, params=params, timeout=10)
            resp.raise_for_status()
            raw_data = resp.json()
            
            candles = []
            for item in raw_data:
                candles.append({
                    "time": int(item[0] // 1000),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                })
            logging.info(f"Fetched {len(candles)} historical candles for {symbol} ({market_type.upper()}).")
            return candles
        except Exception as e:
            logging.warning(f"Fetch attempt {attempt} failed: {e}")
            if attempt < 3:
                import time
                time.sleep(2)
            else:
                raise e

def fetch_klines_range(symbol: str = "BTCUSDT", interval: str = "5m", start_time_s: int = 0, end_time_s: int = 0, market_type: str = "futures") -> List[Dict]:
    """
    Fetch OHLCV kline data from Binance API within a specific timestamp window [start_time_s, end_time_s].
    Handles windows that exceed 1000 candles with pagination.
    """
    rest_url = BINANCE_FUTURES_REST if market_type.lower() == "futures" else BINANCE_SPOT_REST
    all_candles = []
    current_start = start_time_s * 1000
    end_ms = end_time_s * 1000

    while True:
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": 1000
        }
        raw_data = None
        for attempt in range(1, 4):
            try:
                resp = requests.get(rest_url, params=params, timeout=10)
                resp.raise_for_status()
                raw_data = resp.json()
                break
            except Exception as e:
                logging.warning(f"Range fetch attempt {attempt} failed: {e}")
                if attempt < 3:
                    import time
                    time.sleep(1)
                else:
                    break

        if not raw_data:
            break

        chunk = []
        for item in raw_data:
            chunk.append({
                "time": int(item[0] // 1000),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
            })
        all_candles.extend(chunk)

        if len(raw_data) < 1000:
            break
        # Next chunk starts after last candle open time
        current_start = int(raw_data[-1][0]) + 1
        if current_start >= end_ms:
            break

    # Deduplicate and sort
    seen = set()
    cleaned = []
    for c in all_candles:
        t = c.get("time")
        if t and t not in seen:
            seen.add(t)
            cleaned.append(c)
    cleaned.sort(key=lambda x: x["time"])
    return cleaned

def fetch_klines_paginated(symbol: str = "BTCUSDT", interval: str = "1h", total_candles: int = 10000, market_type: str = "futures") -> List[Dict]:
    """
    Fetch up to total_candles historical OHLCV kline data from Binance API using endTime pagination.
    Returns a sorted, deduplicated list of candle dicts across months of historical data.
    """
    rest_url = BINANCE_FUTURES_REST if market_type.lower() == "futures" else BINANCE_SPOT_REST
    all_candles = []
    end_time = None
    target_fetch = max(1000, total_candles)
    
    logging.info(f"Fetching {target_fetch} historical {interval} candles for {symbol} ({market_type.upper()}) via paginated Binance REST API...")
    
    while len(all_candles) < target_fetch:
        fetch_count = min(1000, target_fetch - len(all_candles))
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": fetch_count
        }
        if end_time:
            params["endTime"] = end_time

        fetched_chunk = False
        for attempt in range(1, 4):
            try:
                resp = requests.get(rest_url, params=params, timeout=10)
                resp.raise_for_status()
                raw_data = resp.json()
                if not raw_data:
                    fetched_chunk = True
                    break

                chunk = []
                for item in raw_data:
                    chunk.append({
                        "time": int(item[0] // 1000),
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5]),
                    })
                
                if not chunk:
                    fetched_chunk = True
                    break

                all_candles.extend(chunk)
                end_time = (raw_data[0][0]) - 1  # 1 ms before oldest candle in chunk
                fetched_chunk = True
                break
            except Exception as e:
                logging.warning(f"Paginated fetch attempt {attempt} failed: {e}")
                if attempt < 3:
                    import time
                    time.sleep(1)
                else:
                    break

        if not fetched_chunk or not raw_data or len(raw_data) < 10:
            break

    # Deduplicate and sort chronologically ascending
    seen = set()
    cleaned = []
    for c in all_candles:
        t = c.get("time")
        if t and t not in seen:
            seen.add(t)
            cleaned.append(c)
    cleaned.sort(key=lambda x: x["time"])
    logging.info(f"Successfully loaded {len(cleaned)} historical candles for {symbol} ({interval}).")
    return cleaned



class BinanceWebsocketClient:
    """
    Connects to Binance WebSocket (Futures or Spot) for real-time kline updates.
    Calls `on_candle_update(candle_dict, is_closed)` on each stream tick.
    """
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "1h", market_type: str = "futures", on_candle_update: Optional[Callable] = None):
        self.symbol = symbol.lower()
        self.interval = interval
        self.market_type = market_type.lower()
        self.on_candle_update = on_candle_update
        self._running = False

    async def start(self):
        self._running = True
        base_ws = BINANCE_FUTURES_WS if self.market_type == "futures" else BINANCE_SPOT_WS
        ws_endpoint = f"{base_ws}/{self.symbol}@kline_{self.interval}"
        logging.info(f"Connecting to Binance {self.market_type.upper()} WebSocket: {ws_endpoint}")
        
        while self._running:
            try:
                async with websockets.connect(ws_endpoint) as ws:
                    logging.info(f"Connected to Binance {self.market_type.upper()} WS stream for {self.symbol.upper()} ({self.interval}).")
                    while self._running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if "k" in data:
                            k = data["k"]
                            candle = {
                                "time": int(k["t"] // 1000),
                                "open": float(k["o"]),
                                "high": float(k["h"]),
                                "low": float(k["l"]),
                                "close": float(k["c"]),
                                "volume": float(k["v"]),
                            }
                            is_closed = k["x"] # True if candle is closed
                            if self.on_candle_update:
                                if asyncio.iscoroutinefunction(self.on_candle_update):
                                    await self.on_candle_update(candle, is_closed)
                                else:
                                    self.on_candle_update(candle, is_closed)
            except Exception as e:
                logging.error(f"Binance WS error: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3)

    def stop(self):
        self._running = False
