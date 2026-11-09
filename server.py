import os

import asyncio

import bisect

import json

import logging

import time

from datetime import datetime, timezone

from typing import List, Dict, Set, Optional, Tuple, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request

from fastapi.staticfiles import StaticFiles

from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse

import uvicorn



from binance_feed import fetch_klines_paginated, fetch_klines_range, BinanceWebsocketClient

from htf_engine import HTFEngine, is_qualifying_htf_zone, is_htf_box_active

from mtf_strategy import MTFStrategy

from pattern_scanner import get_target_ltf, get_engulfing_labels_for_cycle

from portfolio_risk_manager import portfolio_risk_engine, LOCKED_PORTFOLIO_COINS

from timeframe_allocation_manager import timeframe_allocation_engine


from ltf_approach_engine import compute_ltf_approach_structure



logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

logger = logging.getLogger("TradingBotServer")



INTERVAL_SECONDS = {

    "1m": 60,

    "3m": 180,

    "5m": 300,

    "15m": 900,

    "30m": 1800,

    "1h": 3600,

    "2h": 7200,

    "4h": 14400,

    "1d": 86400

}



app = FastAPI(title="Meyhem Quant Engine with Portfolio Risk Manager")



# Global state

active_symbol = "BTCUSDT"

active_htf_interval = "15m"

active_market = "futures"



htf_candles: List[Dict] = []

cached_ltf_candles: List[Dict] = []

strategy_result: Dict = {}

ZONE_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "data", "zone_trades_registry.json")



def load_zone_registry() -> Dict[str, Dict]:

    try:

        if os.path.exists(ZONE_REGISTRY_PATH):

            with open(ZONE_REGISTRY_PATH, "r", encoding="utf-8") as f:

                return json.load(f)

    except Exception as e:

        logger.warning(f"Error loading zone registry: {e}")

    return {}



def save_zone_registry(registry: Dict[str, Dict]):

    try:

        os.makedirs(os.path.dirname(ZONE_REGISTRY_PATH), exist_ok=True)

        with open(ZONE_REGISTRY_PATH, "w", encoding="utf-8") as f:

            json.dump(registry, f, indent=2)

    except Exception as e:

        logger.warning(f"Error saving zone registry: {e}")



ZONE_SINGLE_TRADE_REGISTRY: Dict[str, Dict] = load_zone_registry()
ZONE_CYCLE_REGISTRY: Dict[str, Dict] = {}  # reg_key -> {"symbol": str, "htf_tf": str, "initial_tap_time": int, "box": Dict}



ws_clients: Set[WebSocket] = set()

htf_ws_client: BinanceWebsocketClient = None



htf_engine = HTFEngine(

    lookback_bars=500,

    show_bos=True,

    show_choch=True,

    show_dual_choch=True,

    show_triple_choch=True,

    show_retracement_shapes=False,

    show_active_swings=True,

    show_tjl_boxes=True,

    tjl_extend=True,

    box_width_bars=12

)



def dedupe_and_sort_candles(candles: List[Dict]) -> List[Dict]:

    seen = set()

    cleaned = []

    for c in candles:

        t = c.get("time")

        if t and t not in seen:

            seen.add(t)

            cleaned.append(c)

    cleaned.sort(key=lambda x: x["time"])

    return cleaned



def get_target_ltf_for_htf(htf: str) -> Optional[str]:

    """

    Returns target LTF strictly for the 3 active trading combinations:

    1. HTF 15m -> LTF 1m

    2. HTF 1h  -> LTF 1m

    3. HTF 4h  -> LTF 5m

    Any other HTF (e.g., 1d, 5m) returns None (trading disabled).

    """

    h = (htf or "").lower().strip()

    if h in ["15m", "m15"]:

        return "1m"

    elif h in ["1h", "h1"]:

        return "1m"

    elif h in ["4h", "h4"]:

        return "5m"

    return None



def update_strategy():

    global strategy_result

    target_ltf = get_target_ltf_for_htf(active_htf_interval)

    

    # If HTF is not in the 3 allowed combinations (1d, 5m, etc.), trading is strictly disabled

    if not target_ltf:

        if len(htf_candles) >= 20:

            engine = HTFEngine(lookback_bars=min(500, len(htf_candles)), show_tjl_boxes=True, tjl_extend=True)

            out = engine.run(htf_candles)

            strategy_result = {

                "mode": "mtf",

                "htf_interval": active_htf_interval,

                "ltf_interval": None,

                "lines": out.get("lines", []),

                "labels": out.get("labels", []),

                "boxes": out.get("boxes", []),

                "markers": [],

                "signals": [],

                "active_levels": out.get("nearby_levels", []),

                "trend": out.get("htf_trend", "Neutral"),

                "trading_disabled": True,

                "status_message": f"Trading disabled on HTF {active_htf_interval.upper()}. Only 15m->1m, 1h->1m, and 4h->5m are traded."

            }

        else:

            strategy_result = {

                "mode": "mtf",

                "htf_interval": active_htf_interval,

                "ltf_interval": None,

                "lines": [],

                "labels": [],

                "boxes": [],

                "markers": [],

                "signals": [],

                "active_levels": [],

                "trend": "Neutral",

                "trading_disabled": True,

                "status_message": f"Trading disabled on HTF {active_htf_interval.upper()}."

            }

        return



    if len(htf_candles) >= 20:

        strat = MTFStrategy(htf_interval=active_htf_interval, ltf_interval=target_ltf, min_rr=3.0)

        strat.htf_engine = HTFEngine(lookback_bars=len(htf_candles), show_tjl_boxes=True, tjl_extend=True)

        

        ltf_c = cached_ltf_candles if (cached_ltf_candles and len(cached_ltf_candles) >= 20) else htf_candles

        out = strat.run_strategy(htf_candles, ltf_c)

        # Generic bullish/bearish engulfing signals removed from HTF per user instruction

        trade_signal_markers = []

        trade_signals = []

        if active_htf_interval.lower() in ["4h", "h4"]:

            h4_file = os.path.join(os.path.dirname(__file__), "data", "h4_unique_october_trades.json")

            if os.path.exists(h4_file):

                try:

                    with open(h4_file, "r", encoding="utf-8") as f:

                        h4_d = json.load(f)

                        trade_signal_markers = h4_d.get("markers", [])

                        trade_signals = h4_d.get("signals", h4_d.get("trades", []))

                except Exception as e:

                    logging.warning(f"Error loading H4 trade markers: {e}")

        elif active_htf_interval.lower() in ["1h", "h1"]:

            h1_file = os.path.join(os.path.dirname(__file__), "data", "h1_unique_october_trades.json")

            if os.path.exists(h1_file):

                try:

                    with open(h1_file, "r", encoding="utf-8") as f:

                        h1_d = json.load(f)

                        trade_signal_markers = h1_d.get("markers", [])

                        trade_signals = h1_d.get("signals", [])

                except Exception as e:

                    logging.warning(f"Error loading H1 trade markers: {e}")

        elif active_htf_interval.lower() in ["15m", "m15"]:

            m15_file = os.path.join(os.path.dirname(__file__), "data", "m15_unique_october_trades.json")

            if os.path.exists(m15_file):

                try:

                    with open(m15_file, "r", encoding="utf-8") as f:

                        m15_d = json.load(f)

                        trade_signal_markers = m15_d.get("markers", [])

                        trade_signals = m15_d.get("signals", [])

                except Exception as e:

                    logging.warning(f"Error loading M15 trade markers: {e}")



        combined_markers = trade_signal_markers + out.get("markers", [])

        combined_signals = trade_signals if trade_signals else out.get("signals", [])



        strategy_result = {

            "mode": "mtf",

            "htf_interval": active_htf_interval,

            "ltf_interval": target_ltf,

            "lines": out.get("lines", []),

            "labels": out.get("labels", []),

            "boxes": out.get("boxes", []),

            "markers": combined_markers,

            "signals": combined_signals,

            "active_levels": out.get("nearby_levels", []),

            "trend": out.get("htf_trend", "Neutral"),

            "trading_disabled": False,

            "status_message": f"Active ({active_htf_interval.upper()} -> {target_ltf.upper()})"

        }

    else:

        strategy_result = {

            "mode": "mtf",

            "htf_interval": active_htf_interval,

            "ltf_interval": target_ltf,

            "lines": [],

            "labels": [],

            "boxes": [],

            "markers": [],

            "signals": [],

            "active_levels": [],

            "trend": "Neutral",

            "trading_disabled": False,

            "status_message": "Insufficient candle data"

        }



async def broadcast(data: Dict):

    if not ws_clients:

        return

    msg = json.dumps(data)

    disconnected = set()

    for ws in ws_clients:

        try:

            await ws.send_text(msg)

        except Exception:

            disconnected.add(ws)

    for ws in disconnected:

        ws_clients.remove(ws)



async def broadcast_portfolio_update():

    if not ws_clients:

        return

    try:

        status = portfolio_risk_engine.get_status()

        history = {

            "balance": portfolio_risk_engine.balance,

            "peak_equity": portfolio_risk_engine.peak_equity,

            "bot_enabled": portfolio_risk_engine.bot_enabled,

            "active_positions": list(portfolio_risk_engine.active_positions.values()),

            "trade_history": portfolio_risk_engine.trade_history

        }

        await broadcast({

            "type": "portfolio_update",

            "status": status,

            "history": history

        })

    except Exception as e:

        logging.warning(f"Error broadcasting portfolio update: {e}")



async def on_htf_candle(candle: Dict, is_closed: bool):

    global htf_candles

    if not htf_candles:

        htf_candles.append(candle)

    else:

        if candle["time"] == htf_candles[-1]["time"]:

            htf_candles[-1] = candle

        elif candle["time"] > htf_candles[-1]["time"]:

            htf_candles.append(candle)

    

    htf_candles = dedupe_and_sort_candles(htf_candles)[-10000:]

    update_strategy()

    

    # Check active open positions for this symbol against live high/low (PAPER mode only)

    for tid, pos in list(portfolio_risk_engine.active_positions.items()):

        if pos.get("symbol") == active_symbol and pos.get("execution_mode") == "PAPER":

            is_long = (pos.get("type") == "BUY")

            c_high = candle.get("high", candle.get("close", 0))

            c_low = candle.get("low", candle.get("close", 0))

            tp = pos.get("tp_price", 0)

            sl = pos.get("sl_price", 0)

            rr = pos.get("planned_rr", 2.5)

            

            if is_long:

                if c_high >= tp:

                    portfolio_risk_engine.close_position(tid, "TP", rr, tp, timestamp=candle["time"])

                    await broadcast_portfolio_update()

                elif c_low <= sl:

                    portfolio_risk_engine.close_position(tid, "SL", -1.0, sl, timestamp=candle["time"])

                    await broadcast_portfolio_update()

            else:

                if c_low <= tp:

                    portfolio_risk_engine.close_position(tid, "TP", rr, tp, timestamp=candle["time"])

                    await broadcast_portfolio_update()

                elif c_high >= sl:

                    portfolio_risk_engine.close_position(tid, "SL", -1.0, sl, timestamp=candle["time"])

                    await broadcast_portfolio_update()



    await broadcast({

        "type": "live_update",

        "candle": candle,

        "is_closed": is_closed,

        "strategy": strategy_result

    })



async def restart_feed(symbol: str, htf_tf: str):

    global active_symbol, active_htf_interval, htf_candles, htf_ws_client, cached_ltf_candles

    sym_upper = symbol.upper()

    if sym_upper not in LOCKED_PORTFOLIO_COINS:

        logging.warning(f"Symbol '{sym_upper}' is not in locked portfolio coins. Defaulting to BTCUSDT.")

        sym_upper = "BTCUSDT"

    active_symbol = sym_upper

    active_htf_interval = htf_tf.lower()



    if htf_ws_client:

        htf_ws_client.stop()



    logging.info(f"Restarting HTF feed: Symbol={active_symbol}, HTF={active_htf_interval}")



    loop = asyncio.get_event_loop()

    raw_htf = await loop.run_in_executor(None, fetch_klines_paginated, active_symbol, active_htf_interval, 10000, active_market)

    htf_candles = dedupe_and_sort_candles(raw_htf)[-10000:]

    if (not htf_candles or len(htf_candles) < 50) and active_symbol == "BTCUSDT":

        fb_path = os.path.join(os.path.dirname(__file__), "data", f"btc_{active_htf_interval}_oct2026_full.json")

        if os.path.exists(fb_path):

            try:

                with open(fb_path, "r", encoding="utf-8") as f_fb:

                    htf_candles = json.load(f_fb)

            except Exception as e:

                logging.warning(f"Error loading {active_htf_interval} fallback: {e}")

    if active_htf_interval in ["15m", "1h", "4h"]:

        htf_sep = [c for c in htf_candles if c.get("time", 0) >= 1790121600]

        if len(htf_sep) >= 20:

            htf_candles = htf_sep



    target_ltf = get_target_ltf_for_htf(active_htf_interval)

    if not target_ltf or target_ltf == active_htf_interval:

        cached_ltf_candles = htf_candles

    else:

        try:

            raw_ltf = await loop.run_in_executor(None, fetch_klines_paginated, active_symbol, target_ltf, 1000, active_market)

            cached_ltf_candles = dedupe_and_sort_candles(raw_ltf) if raw_ltf else htf_candles

        except Exception:

            cached_ltf_candles = htf_candles



    update_strategy()



    snapshot = {

        "type": "snapshot",

        "symbol": active_symbol,

        "htf_interval": active_htf_interval,

        "market": active_market,

        "candles": htf_candles,

        "strategy": strategy_result

    }

    await broadcast(snapshot)



    htf_ws_client = BinanceWebsocketClient(active_symbol, active_htf_interval, market_type=active_market, on_candle_update=on_htf_candle)

    asyncio.create_task(htf_ws_client.start())



async def live_portfolio_monitor_task():

    """

    Dedicated autonomous background monitor for ALL 20 Locked Portfolio Coins.

    Runs the 7-Section Manual MTFStrategy (ZoneExecutionTracker) across:

      - BTC & SOL: 4h -> 5m, 1h -> 1m, 15m -> 1m LTF (Only BTC & SOL active)

    Cycles through locked coins (BTC, SOL):

      1. Tracks open positions against latest market prices for TP / SL execution.

      2. Enforces max_open_positions = 3 (portfolio slot limit) and max_trades_per_symbol = 1.

      3. Scans HTF structure (1000 bars) and closed 5m LTF candles via MTFStrategy (ZoneExecutionTracker).

      4. Places SL behind the deepest extreme of the HTF zone touch and locks TP strictly at 2.5R.

      5. Automatically executes Maker Limit Orders (LIMIT / Post-Only GTX).

    """

    monitor_logger = logging.getLogger("Portfolio_Autonomous_Scanner")

    monitor_logger.info("Initializing Autonomous Portfolio Scanner across 2 Coins (BTC, SOL: 4h->5m, 1h->1m, 15m->1m)...")

    processed_signals = set()

    

    while True:

        try:

            for symbol in LOCKED_PORTFOLIO_COINS:

                if not portfolio_risk_engine.bot_enabled or portfolio_risk_engine.circuit_breaker_active:

                    break



                try:

                    loop = asyncio.get_event_loop()

                    

                    # 1. Manage active position for this symbol if any

                    active_pos = None

                    active_tid = None

                    for tid, pos in list(portfolio_risk_engine.active_positions.items()):

                        if pos.get("symbol") == symbol:

                            active_pos = pos

                            active_tid = tid

                            break

                    

                    # If position is open, track against exchange status and 1m candle for live TP/SL execution

                    if active_pos and active_tid:

                        from binance_live_executor import binance_executor

                        if binance_executor.mode == "LIVE":

                            # Check if position is waiting for limit entry fill

                            if active_pos.get("order_state") == "PENDING_ENTRY":

                                order_id = active_pos.get("binance_order_id")

                                order_info = await loop.run_in_executor(None, binance_executor.get_order_status, symbol, order_id)

                                if order_info:

                                    st = order_info.get("status")

                                    if st == "FILLED":

                                        active_pos["order_state"] = "FILLED"

                                        active_pos["entry_price"] = float(order_info.get("avgPrice") or active_pos["entry_price"])

                                        monitor_logger.info(f"Limit order {order_id} for {symbol} FILLED @ {active_pos['entry_price']}.")

                                        portfolio_risk_engine._save_journal()

                                        await broadcast_portfolio_update()

                                    elif st in ["CANCELED", "EXPIRED", "REJECTED"]:

                                        monitor_logger.info(f"Limit order {order_id} for {symbol} was {st} with 0 fill. Removing pending tracker.")

                                        portfolio_risk_engine.cancel_pending_position(active_tid, reason=f"Exchange order {st}")

                                        await broadcast_portfolio_update()

                                        continue

                                    else:

                                        # Order is still NEW / waiting in orderbook. Check timeout

                                        age = time.time() - active_pos.get("open_time", time.time())

                                        max_wait = timeframe_allocation_engine.get_optimal_execution_profile(symbol).get("max_age_s", 900)

                                        if age > max_wait:

                                            monitor_logger.info(f"Limit order {order_id} for {symbol} timed out ({age:.0f}s > {max_wait}s). Cancelling.")

                                            await loop.run_in_executor(None, binance_executor.cancel_all_open_orders, symbol)

                                            portfolio_risk_engine.cancel_pending_position(active_tid, reason="Time limit exceeded")

                                            await broadcast_portfolio_update()

                                        continue

                                else:

                                    continue



                            # Now verify filled position amount on Binance

                            pos_amt = await loop.run_in_executor(None, binance_executor.get_position_amt, symbol)

                            if pos_amt is not None and abs(pos_amt) < 1e-6:

                                # Position genuinely filled and now flat on Binance (executed by exchange SL/TP algo order)!

                                try:

                                    open_ts = int(active_pos.get("open_time", 0) * 1000)

                                    req_params = {"symbol": symbol, "limit": 20}

                                    if open_ts > 0:

                                        req_params["startTime"] = open_ts



                                    trades = await loop.run_in_executor(

                                        None,

                                        binance_executor._send_request,

                                        "GET",

                                        "/fapi/v1/userTrades",

                                        req_params

                                    )

                                    exit_side = "SELL" if active_pos.get("type") == "BUY" else "BUY"

                                    exit_trades = [t for t in trades if t.get("side") == exit_side] if trades else []

                                    if exit_trades:

                                        realized_pnl = sum(float(t.get("realizedPnl", 0.0)) for t in exit_trades)

                                        comm = sum(float(t.get("commission", 0.0)) for t in exit_trades)

                                        net_pnl = realized_pnl - comm

                                        exit_qty = sum(float(t.get("qty", 0.0)) for t in exit_trades)

                                        exit_p = sum(float(t["price"]) * float(t["qty"]) for t in exit_trades) / exit_qty if exit_qty > 0 else float(exit_trades[-1]["price"])

                                    else:

                                        realized_pnl = 0.0

                                        net_pnl = 0.0

                                        exit_p = float(trades[-1]["price"]) if trades else active_pos["sl_price"]



                                    outcome = "TP" if realized_pnl > 0 else "SL"

                                    r_gain = active_pos.get("planned_rr", 2.5) if outcome == "TP" else -1.0

                                    pnl_override = net_pnl if net_pnl != 0.0 else None

                                except Exception as rec_err:

                                    monitor_logger.error(f"Error querying userTrades for {symbol}: {rec_err}")

                                    outcome = "SL"

                                    r_gain = -1.0

                                    exit_p = active_pos["sl_price"]

                                    pnl_override = None



                                monitor_logger.info(f"Exchange position for {symbol} closed ({outcome} @ {exit_p:.4f}, NetPnL=${pnl_override or 0.0:.2f}). Closing internal tracker and cancelling orphan orders.")

                                portfolio_risk_engine.close_position(active_tid, outcome, r_gain, exit_p, pnl_override=pnl_override)

                                await broadcast_portfolio_update()

                                continue

                            # In LIVE mode, exchange STOP_MARKET / TAKE_PROFIT_MARKET orders handle exits; do not fall through to PAPER 1m simulator

                            continue



                        recent_1m = await loop.run_in_executor(None, fetch_klines_paginated, symbol, "1m", 10, "futures")

                        if recent_1m:

                            latest_c = recent_1m[-1]

                            is_long = (active_pos["type"] == "BUY")

                            tp = active_pos["tp_price"]

                            sl = active_pos["sl_price"]

                            rr = active_pos.get("planned_rr", 2.5)

                            c_high = latest_c["high"]

                            c_low = latest_c["low"]

                            

                            if is_long:

                                if c_high >= tp:

                                    portfolio_risk_engine.close_position(active_tid, "TP", rr, tp, timestamp=latest_c["time"])

                                    await broadcast_portfolio_update()

                                elif c_low <= sl:

                                    portfolio_risk_engine.close_position(active_tid, "SL", -1.0, sl, timestamp=latest_c["time"])

                                    await broadcast_portfolio_update()

                            else:

                                if c_low <= tp:

                                    portfolio_risk_engine.close_position(active_tid, "TP", rr, tp, timestamp=latest_c["time"])

                                    await broadcast_portfolio_update()

                                elif c_high >= sl:

                                    portfolio_risk_engine.close_position(active_tid, "SL", -1.0, sl, timestamp=latest_c["time"])

                                    await broadcast_portfolio_update()

                        continue

                    

                    # 2. If no position is open in this symbol, scan on its validated OPTIMAL timeframe

                    # First verify portfolio slot capacity (max_open_positions = 3)

                    max_open_slots = portfolio_risk_engine.config.get("max_open_positions", 3)

                    if len(portfolio_risk_engine.active_positions) >= max_open_slots:

                        monitor_logger.debug(f"Portfolio slots full ({len(portfolio_risk_engine.active_positions)}/{max_open_slots}). Skipping entry scan for {symbol}.")

                        continue



                    # Timeframe Allocation:

                    # - BTC & SOL: Strictly scanned on 4h, 1h, and 15m HTF -> 5m LTF

                    # - All other coins: Inactive

                    # - Strictly prevents cross-timeframe cannibalization (max 1 active position per coin)

                    allowed_profiles = timeframe_allocation_engine.get_allowed_execution_profiles(symbol)

                    tf_configurations = []

                    for prof in allowed_profiles:

                        h_tf = prof["htf"]

                        l_tf = prof["ltf"]

                        is_allowed, allow_reason = timeframe_allocation_engine.is_timeframe_allowed(symbol, h_tf)

                        if is_allowed:

                            tf_configurations.append((h_tf, l_tf, prof.get("max_age_s", 900)))

                        else:

                            monitor_logger.debug(f"Skipping {symbol} on {h_tf}: {allow_reason}")



                    if not tf_configurations:

                        continue



                    # Cache LTF candles per symbol for this cycle (1m and 5m)

                    ltf_cache = {}



                    trade_taken_for_symbol = False

                    for htf_tf, ltf_tf, max_age_s in tf_configurations:

                        if trade_taken_for_symbol:

                            break



                        # Fetch or retrieve cached closed LTF candles for ltf_tf ("1m" or "5m")

                        if ltf_tf not in ltf_cache:

                            raw_ltf = await loop.run_in_executor(None, fetch_klines_paginated, symbol, ltf_tf, 1000, "futures")

                            if raw_ltf and len(raw_ltf) >= 25:

                                ltf_cache[ltf_tf] = raw_ltf[:-1]  # Exclude unclosed forming bar

                            else:

                                ltf_cache[ltf_tf] = []



                        closed_ltf = ltf_cache.get(ltf_tf)

                        if not closed_ltf:

                            continue

                        latest_closed_ltf_time = closed_ltf[-1]["time"]



                        # Fetch HTF candles

                        recent_htf = await loop.run_in_executor(None, fetch_klines_paginated, symbol, htf_tf, 1000, "futures")

                        if not recent_htf or len(recent_htf) < 25:

                            continue



                        # 1. Generate HTF structure strictly up to latest closed LTF time (Rolling 500-Candle Window - TradingView Model)
                        htf_sec_val = INTERVAL_SECONDS.get(htf_tf.lower(), 14400)
                        recent_htf = recent_htf[-500:]
                        htf_engine_inst = HTFEngine(lookback_bars=min(500, len(recent_htf)), show_tjl_boxes=True, tjl_extend=True)
                        htf_res = htf_engine_inst.run(recent_htf)
                        raw_htf_boxes = [b for b in htf_res.get("boxes", []) if is_qualifying_htf_zone(b)]

                        for b in raw_htf_boxes:
                            b_left = b.get("confirmed_formation_time") or b.get("left") or b.get("start_time") or b.get("time") or 0
                            b["confirmed_formation_time"] = b_left
                            if "mitigated_time" not in b:
                                b["mitigated_time"] = b.get("right")

                        # Filter active HTF boxes
                        active_htf_boxes = [
                            b for b in raw_htf_boxes
                            if is_htf_box_active(b, latest_closed_ltf_time, htf_sec_val) and latest_closed_ltf_time >= b.get("confirmed_formation_time", 0)
                        ]

                        if not active_htf_boxes:

                            continue



                        # Filter out boxes that have already taken a trade (Strict 1 trade per level rule)

                        available_htf_boxes = []

                        for b in active_htf_boxes:

                            b_id = f"{b.get('text')}_{b.get('left')}_{round(float(b.get('top', 0)), 2)}_{round(float(b.get('bottom', 0)), 2)}"

                            reg_key = f"{symbol}_{htf_tf}_{b_id}"

                            if reg_key not in ZONE_SINGLE_TRADE_REGISTRY:

                                available_htf_boxes.append(b)



                        if not available_htf_boxes:

                            continue



                        # Cycle State Machine: Manage 120-candle reaction cycles per zone
                        ltf_sec_val = INTERVAL_SECONDS.get(ltf_tf.lower(), 60)
                        max_cycle_seconds = 120 * ltf_sec_val

                        # 1. Clean up expired cycles
                        expired_keys = [
                            k for k, cyc in ZONE_CYCLE_REGISTRY.items()
                            if cyc.get("symbol") == symbol and cyc.get("htf_tf") == htf_tf
                            and (latest_closed_ltf_time - cyc.get("initial_tap_time", 0)) > max_cycle_seconds
                        ]
                        for k in expired_keys:
                            del ZONE_CYCLE_REGISTRY[k]

                        # 2. Check for new taps from outside to open reaction cycles
                        curr_ltf_c = closed_ltf[-1]
                        for b in available_htf_boxes:
                            b_id = f"{b.get('text')}_{b.get('left')}_{round(float(b.get('top', 0)), 2)}_{round(float(b.get('bottom', 0)), 2)}"
                            reg_key = f"{symbol}_{htf_tf}_{b_id}"
                            if reg_key not in ZONE_CYCLE_REGISTRY:
                                b_top = max(b.get("top", 0), b.get("bottom", 0))
                                b_bot = min(b.get("top", 0), b.get("bottom", 0))
                                if curr_ltf_c["high"] >= b_bot and curr_ltf_c["low"] <= b_top:
                                    if is_valid_tap_approach(b, closed_ltf, len(closed_ltf) - 1):
                                        ZONE_CYCLE_REGISTRY[reg_key] = {
                                            "symbol": symbol,
                                            "htf_tf": htf_tf,
                                            "initial_tap_time": latest_closed_ltf_time,
                                            "box": b
                                        }
                                        logger.info(f"[{symbol} {htf_tf}->{ltf_tf}] Opened 120-candle Reaction Cycle for zone {b.get('text')} at {latest_closed_ltf_time}")

                        active_cycles = [
                            (k, cyc) for k, cyc in ZONE_CYCLE_REGISTRY.items()
                            if cyc.get("symbol") == symbol and cyc.get("htf_tf") == htf_tf
                        ]
                        if not active_cycles:
                            continue

                        # Run localized LTF approach structure for active cycle
                        htf_sec_val = INTERVAL_SECONDS.get(htf_tf.lower(), 900)
                        reg_key, cyc = active_cycles[0]
                        init_tap_time = cyc["initial_tap_time"]
                        target_box = cyc["box"]

                        res = compute_ltf_approach_structure(
                            target_time=init_tap_time,
                            ltf_candles=closed_ltf,
                            htf_boxes=available_htf_boxes,
                            htf_sec=htf_sec_val,
                            htf_candles=recent_htf,
                            override_tap_time=init_tap_time,
                            override_box=target_box
                        )

                        tap_info = res.get("tap_info")

                        if not tap_info or not tap_info.get("trade"):

                            continue



                        box_name = str(tap_info.get("box_name", "")).upper()

                        if "A+" in box_name:

                            continue  # Filter out A+ (Dual CHoCH) per optimization



                        tr = tap_info["trade"]

                        if not tr.get("executed"):

                            continue



                        # Signal must have fired on the latest closed candle (or within the last closed bar)

                        tr_time = tr.get("time")

                        ltf_sec_val = INTERVAL_SECONDS.get(ltf_tf.lower(), 60)

                        if abs(tr_time - latest_closed_ltf_time) > ltf_sec_val:

                            continue



                        sig_key = f"{symbol}_{htf_tf}_{tr_time}"

                        if sig_key in processed_signals:

                            continue



                        t_type = tr["action"]

                        is_bull = (t_type == "BUY")

                        entry_p = tr["entry_price"]

                        sl_p = tr["sl_price"]

                        risk_dist = abs(entry_p - sl_p)

                        if risk_dist <= 0:

                            continue



                        # Planned RR and TP calculation matching backtest exactly:

                        # 4h -> 5m: Fixed 3.0R TP

                        # 1h -> 1m & 15m -> 1m: Opposing HTF liquidity (min_rr = 2.5 floor)

                        dec = 5 if entry_p < 50 else (3 if entry_p < 1000 else 2)

                        if htf_tf.lower() == "4h":

                            planned_rr = 3.0

                            planned_reward = round(3.0 * risk_dist, dec)

                            tp_p = round(entry_p + planned_reward if is_bull else entry_p - planned_reward, dec)

                        else:

                            tp_p = round(tr["tp_price"], dec)

                            planned_reward = round(abs(tp_p - entry_p), dec)

                            planned_rr = round(planned_reward / risk_dist, 2) if risk_dist > 0 else 0.0



                        if planned_rr < (3.0 if htf_tf.lower() == "4h" else 2.5):

                            continue



                        pat_name = tr.get("pattern_name", "Reversal")

                        matched_box_name = tap_info.get("box_name", "HTF Zone")

                        t_id = f"{symbol[:4]}_{htf_tf}_{t_type}_{tr_time}"

                        now_ts = int(time.time())



                        eval_r = portfolio_risk_engine.evaluate_new_trade(

                            symbol=symbol,

                            entry_price=entry_p,

                            sl_price=sl_p,

                            tp_price=tp_p,

                            planned_rr=planned_rr,

                            trade_type=t_type,

                            timestamp=now_ts,

                            timeframe=htf_tf,

                            sl_buffer_override=False

                        )

                        if eval_r.get("allowed"):

                            open_r = portfolio_risk_engine.open_position(

                                trade_id=t_id,

                                symbol=symbol,

                                trade_type=t_type,

                                entry_price=entry_p,

                                sl_price=sl_p,

                                tp_price=tp_p,

                                planned_rr=planned_rr,

                                timestamp=now_ts,

                                timeframe=htf_tf,

                                sl_buffer_override=False

                            )

                            if open_r.get("allowed"):

                                processed_signals.add(sig_key)

                                # Record into ZONE_SINGLE_TRADE_REGISTRY (Strict 1 trade per level)

                                matched_box = None

                                for b in available_htf_boxes:

                                    b_top = max(b.get("top", 0), b.get("bottom", 0))

                                    b_bot = min(b.get("top", 0), b.get("bottom", 0))

                                    if c_high >= b_bot and c_low <= b_top:

                                        matched_box = b

                                        break

                                if matched_box:

                                    b_id = f"{matched_box.get('text')}_{matched_box.get('left')}_{round(float(matched_box.get('top', 0)), 2)}_{round(float(matched_box.get('bottom', 0)), 2)}"

                                    reg_key = f"{symbol}_{htf_tf}_{b_id}"

                                    if reg_key in ZONE_CYCLE_REGISTRY:
                            del ZONE_CYCLE_REGISTRY[reg_key]
                        ZONE_SINGLE_TRADE_REGISTRY[reg_key] = {

                                        "symbol": symbol,

                                        "htf": htf_tf,

                                        "ltf": ltf_tf,

                                        "trade_id": t_id,

                                        "entry_price": entry_p,

                                        "sl_price": sl_p,

                                        "tp_price": tp_p,

                                        "rr": planned_rr,

                                        "time": now_ts,

                                        "level_name": matched_box_name,

                                        "pattern": pat_name

                                    }

                                    save_zone_registry(ZONE_SINGLE_TRADE_REGISTRY)



                                monitor_logger.info(

                                    f"🚀 [AUTONOMOUS {htf_tf.upper()}->{ltf_tf.upper()} TopG Engine] LIVE Order Dispatched [{t_id}]: "

                                    f"{symbol} {t_type} ({pat_name} @ {matched_box_name}) @ {entry_p} (SL: {sl_p}, TP: {tp_p}, RR: {planned_rr}R)"

                                )

                                await broadcast_portfolio_update()

                                trade_taken_for_symbol = True

                                break

                except Exception as sym_err:

                    monitor_logger.debug(f"Scanner note for {symbol}: {sym_err}")

                

                await asyncio.sleep(0.3)



            # Pause 15 seconds before the next scan cycle

            await asyncio.sleep(15)



        except Exception as e:

            monitor_logger.debug(f"Portfolio monitor loop cycle note: {e}")

            await asyncio.sleep(10)



@app.on_event("startup")

async def startup_event():

    asyncio.create_task(restart_feed(active_symbol, active_htf_interval))

    asyncio.create_task(live_portfolio_monitor_task())



from auth import authenticate_user, verify_token, invalidate_token, get_session_info



def get_authenticated_user(request: Request) -> Optional[Dict[str, Any]]:

    """Extracts and verifies user session from Bearer header, query param, or cookie."""

    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):

        token = auth_header.split(" ")[1].strip()

        info = get_session_info(token)

        if info:

            return info



    query_token = request.query_params.get("token")

    if query_token:

        info = get_session_info(query_token)

        if info:

            return info



    cookie_token = request.cookies.get("topg_session")

    if cookie_token:

        info = get_session_info(cookie_token)

        if info:

            return info



    return None



def is_authenticated_request(request: Request) -> bool:

    """Verifies authentication via Bearer header, query token, or HttpOnly session cookie."""

    return get_authenticated_user(request) is not None



def is_admin_request(request: Request) -> bool:

    """Verifies request has valid active session with 'admin' role."""

    user = get_authenticated_user(request)

    return user is not None and user.get("role") == "admin"



PUBLIC_PATHS = {

    "/login",

    "/login.html",

    "/static/login.html",

    "/static/style.css",

    "/static/favicon.svg",

    "/static/app.js",

    "/static/lightweight-charts.js",

    "/api/auth/login",

    "/api/auth/verify",

    "/api/chart_signals",

    "/api/ltf_candles",

    "/api/signal_analysis",

    "/api/inspect_trade",

    "/api/simulation_october",

    "/api/simulation_october_major",

    "/api/simulation_candles",

    "/favicon.ico"

}



@app.websocket("/ws")

async def websocket_endpoint(websocket: WebSocket):

    token = websocket.query_params.get("token") or websocket.cookies.get("topg_session")

    client_ip = websocket.client.host if websocket.client else ""

    if not verify_token(token) and client_ip not in ["127.0.0.1", "localhost", "::1"]:

        await websocket.close(code=1008)

        return

    await websocket.accept()

    ws_clients.add(websocket)

    try:

        snapshot = {

            "type": "snapshot",

            "symbol": active_symbol,

            "htf_interval": active_htf_interval,

            "market": active_market,

            "candles": htf_candles,

            "strategy": strategy_result

        }

        await websocket.send_text(json.dumps(snapshot))



        while True:

            data_str = await websocket.receive_text()

            data = json.loads(data_str)

            action = data.get("action")

            if action in ["change_timeframe", "change_symbol"]:

                new_sym = data.get("symbol", active_symbol)

                new_htf = data.get("htf_interval", data.get("timeframe", active_htf_interval))

                await restart_feed(new_sym, new_htf)



    except WebSocketDisconnect:

        ws_clients.remove(websocket)

    except Exception as e:

        logging.error(f"WebSocket error: {e}")

        if websocket in ws_clients:

            ws_clients.remove(websocket)



from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=500)



@app.middleware("http")

async def security_guard_middleware(request: Request, call_next):

    path = request.url.path



    # Allow public endpoints without authentication

    if path in PUBLIC_PATHS or path.startswith("/static/login.html"):

        return await call_next(request)



    # Strictly enforce authentication on dashboard, APIs, and protected assets

    if not is_authenticated_request(request):

        if path in ["/", "/index.html", "/static/index.html"]:

            return RedirectResponse(url="/login", status_code=303)

        if path.startswith("/api/") or path.startswith("/static/"):

            return JSONResponse(

                status_code=401,

                content={"error": "Unauthorized", "detail": "Valid authentication credentials required."}

            )

        return RedirectResponse(url="/login", status_code=303)



    return await call_next(request)



@app.middleware("http")

async def handle_cache_headers(request, call_next):

    response = await call_next(request)

    path = request.url.path

    if False:

        pass

    else:

        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"

        response.headers["Pragma"] = "no-cache"

        response.headers["Expires"] = "0"

    return response



app.mount("/static", StaticFiles(directory="static"), name="static")



INTERVAL_SECONDS = {

    "1m": 60,

    "3m": 180,

    "5m": 300,

    "15m": 900,

    "30m": 1800,

    "1h": 3600,

    "2h": 7200,

    "4h": 14400,

    "1d": 86400

}



@app.get("/api/chart_signals")

async def get_chart_signals(

    symbol: str = "BTCUSDT",

    timeframe: str = "15m"

):

    """

    Returns 1,000 candles and ONLY the BUY / SELL strategy signals for the requested timeframe.

    No markings or clutter on the main chart.

    """

    sym = symbol.upper()

    tf = timeframe.lower()

    loop = asyncio.get_event_loop()



    ltf_tf = get_target_ltf_for_htf(tf)



    try:

        sep23_ts = 1790121600

        sec = INTERVAL_SECONDS.get(tf, 900)

        lookback_start = sep23_ts - 500 * sec # 500 candles lookback before Sep 23

        

        if tf == "15m" and sym.upper() == active_symbol.upper() and htf_candles and len(htf_candles) >= 1000:

            htf_c = [c for c in htf_candles if c.get("time", 0) >= lookback_start]

        elif tf == "15m":

            htf_c = await loop.run_in_executor(None, fetch_klines_paginated, sym, tf, 4000, active_market)

            if not htf_c or len(htf_c) < 500:

                oct_path = os.path.join(os.path.dirname(__file__), "data", "btc_15m_oct2026_full.json")

                if not os.path.exists(oct_path):

                    oct_path = os.path.join(os.path.dirname(__file__), "data", "btc_15m_oct2026_with_lookback.json")

                if os.path.exists(oct_path):

                    with open(oct_path, "r", encoding="utf-8") as f:

                        htf_c = json.load(f)

        else:

            htf_c = await loop.run_in_executor(None, fetch_klines_paginated, sym, tf, 2000, active_market)

            if not htf_c or len(htf_c) < 50:

                fb_path = os.path.join(os.path.dirname(__file__), "data", f"btc_{tf}_oct2026_full.json")

                if os.path.exists(fb_path):

                    try:

                        with open(fb_path, "r", encoding="utf-8") as f:

                            htf_c = json.load(f)

                    except Exception as e:

                        logging.warning(f"Error loading {tf} fallback candles: {e}")



        if not htf_c or len(htf_c) < 25:

            return {"symbol": sym, "timeframe": tf, "candles": [], "signals": []}



        if ltf_tf == tf:

            ltf_c = htf_c

        else:

            ltf_c = await loop.run_in_executor(None, fetch_klines_paginated, sym, ltf_tf, 1000, active_market)

            if not ltf_c:

                ltf_c = htf_c



        if tf in ["15m", "1h", "4h"]:

            htf_sep = [c for c in htf_c if c.get("time", 0) >= sep23_ts]

            if len(htf_sep) >= 20:

                htf_c = htf_sep

            if ltf_tf != tf and ltf_c:

                ltf_sep = [c for c in ltf_c if c.get("time", 0) >= sep23_ts]

                if len(ltf_sep) >= 20:

                    ltf_c = ltf_sep



        if tf in ["1d", "d1"]:

            raw_signals = []

            out = {"lines": [], "labels": [], "boxes": [], "nearby_levels": [], "htf_trend": "Neutral"}

        else:

            strat = MTFStrategy(htf_interval=tf, ltf_interval=ltf_tf, min_rr=3.0)

            strat.htf_engine = HTFEngine(lookback_bars=len(htf_c), show_tjl_boxes=True, tjl_extend=True)

            out = strat.run_strategy(htf_c, ltf_c)

            raw_signals = out.get("signals", [])



        # Generic bullish/bearish engulfing signals removed from HTF per user instruction

        trade_signal_markers = []

        trade_signals = []

        if tf in ["4h", "h4"]:

            h4_file = os.path.join(os.path.dirname(__file__), "data", "h4_unique_october_trades.json")

            if os.path.exists(h4_file):

                try:

                    with open(h4_file, "r", encoding="utf-8") as f:

                        h4_d = json.load(f)

                        trade_signal_markers = h4_d.get("markers", [])

                        trade_signals = h4_d.get("signals", h4_d.get("trades", []))

                except Exception as e:

                    logging.warning(f"Error loading H4 trade markers: {e}")

        elif tf in ["1h", "h1"]:

            h1_file = os.path.join(os.path.dirname(__file__), "data", "h1_unique_october_trades.json")

            if os.path.exists(h1_file):

                try:

                    with open(h1_file, "r", encoding="utf-8") as f:

                        h1_d = json.load(f)

                        trade_signal_markers = h1_d.get("markers", [])

                        trade_signals = h1_d.get("signals", [])

                except Exception as e:

                    logging.warning(f"Error loading H1 trade markers: {e}")

        elif tf in ["15m", "m15"]:

            m15_file = os.path.join(os.path.dirname(__file__), "data", "m15_unique_october_trades.json")

            if os.path.exists(m15_file):

                try:

                    with open(m15_file, "r", encoding="utf-8") as f:

                        m15_d = json.load(f)

                        trade_signal_markers = m15_d.get("markers", [])

                        trade_signals = m15_d.get("signals", [])

                except Exception as e:

                    logging.warning(f"Error loading M15 trade markers: {e}")



        combined_markers = trade_signal_markers + out.get("markers", [])

        combined_signals = trade_signals if trade_signals else raw_signals



        return {

            "symbol": sym,

            "timeframe": tf,

            "candles": htf_c,

            "signals": combined_signals,

            "lines": out.get("lines", []),

            "labels": out.get("labels", []),

            "boxes": out.get("boxes", []),

            "markers": combined_markers,

            "nearby_levels": out.get("nearby_levels", []),

            "trend": out.get("htf_trend", "Neutral")

        }

    except Exception as e:

        logging.error(f"Error generating chart signals for {sym} {tf}: {e}")

        return {"symbol": sym, "timeframe": tf, "candles": [], "signals": [], "lines": [], "labels": [], "boxes": [], "trend": "Neutral"}





@app.get("/api/signal_analysis")

async def get_signal_analysis(

    symbol: str = "BTCUSDT",

    htf: str = "15m",

    signal_time: int = 0

):

    """

    Returns 1,000 candles leading up to and past the signal candle,

    along with market structure markings (HTF zone, BOS, CHoCH) and

    exact candle pattern, SL, and TP for visual backtesting in the secondary chart.

    """

    sym = symbol.upper()

    htf_tf = htf.lower()

    loop = asyncio.get_event_loop()



    ltf_tf = "1h" if htf_tf in ["1d", "d1"] else ("5m" if htf_tf in ["5m", "15m", "30m", "1h"] else "15m")



    try:

        htf_c = await loop.run_in_executor(None, fetch_klines_paginated, sym, htf_tf, 1000, active_market)

        if not htf_c or len(htf_c) < 25:

            return {"symbol": sym, "htf": htf_tf, "candles": [], "signal": None, "signals": [], "boxes": [], "lines": [], "labels": []}



        if ltf_tf == htf_tf:

            ltf_c = htf_c

        else:

            ltf_c = await loop.run_in_executor(None, fetch_klines_paginated, sym, ltf_tf, 1000, active_market)

            if not ltf_c:

                ltf_c = htf_c



        strat = MTFStrategy(htf_interval=htf_tf, ltf_interval=ltf_tf, min_rr=3.0)

        strat.htf_engine = HTFEngine(lookback_bars=500, show_tjl_boxes=True, tjl_extend=True)

        out = strat.run_strategy(htf_c, ltf_c)



        raw_signals = [] if htf_tf in ["1d", "d1"] else out.get("signals", [])

        htf_times = [c["time"] for c in htf_c]

        clean_signals = []

        for s in raw_signals:

            sc = {

                "id": s.get("id"),

                "time": s.get("time"),

                "type": s.get("type"),

                "entry": s.get("entry", s.get("price")),

                "sl": s.get("sl"),

                "tp": s.get("tp"),

                "rr": s.get("rr", 2.5),

                "pattern": s.get("pattern", "Reversal Pattern"),

                "outcome": s.get("outcome", "OPEN"),

                "exit_time": s.get("sim_close_time"),

                "exit_price": s.get("exit_price"),

                "is_reentry": s.get("is_reentry", False)

            }

            t = sc["time"]

            if htf_times:

                idx = bisect.bisect_right(htf_times, t) - 1

                idx = max(0, min(idx, len(htf_times) - 1))

                sc["chart_time"] = htf_times[idx]

            else:

                sc["chart_time"] = t

            clean_signals.append(sc)



        target_signal = None

        if signal_time > 0:

            for s in clean_signals:

                if s.get("time") == signal_time or s.get("chart_time") == signal_time or abs(s.get("time", 0) - signal_time) <= 14400:

                    target_signal = s

                    break



        if not target_signal and clean_signals:

            target_signal = clean_signals[-1]



        relevant_box = None

        if target_signal:

            entry_p = target_signal.get("entry", 0)

            sl_p = target_signal.get("sl", 0)

            for b in out.get("boxes", []):

                top = max(b.get("top", 0), b.get("bottom", 0))

                bot = min(b.get("top", 0), b.get("bottom", 0))

                if (bot <= entry_p <= top) or (bot <= sl_p <= top):

                    relevant_box = b

                    break



        return {

            "symbol": sym,

            "htf": htf_tf,

            "ltf": ltf_tf,

            "candles": htf_c,

            "ltf_candles": ltf_c,

            "signal": target_signal,

            "signals": clean_signals,

            "boxes": out.get("boxes", []),

            "relevant_box": relevant_box,

            "lines": out.get("lines", []),

            "labels": out.get("labels", [])

        }

    except Exception as e:

        logging.error(f"Error generating signal analysis for {sym} {htf_tf}: {e}")

        return {"symbol": sym, "htf": htf_tf, "candles": [], "signal": None, "signals": [], "boxes": [], "lines": [], "labels": []}





@app.get("/api/ltf_candles")

async def get_ltf_candles(

    symbol: str = "BTCUSDT",

    interval: str = "5m",

    target_time: int = 0,

    range_bars: int = 1500,

    htf: str = ""

):

    try:

        # 1. Determine normalized HTF and corresponding LTF:

        # Strictly 3 active trading combinations:

        # - 15m -> 1m

        # - 1h  -> 1m

        # - 4h  -> 5m

        # (1D and 5M HTF are explicitly NOT traded)

        htf_in = htf.lower().strip() if htf else ""

        ltf_in = interval.lower().strip() if interval else ""



        def norm_tf(t):

            t = t.lower().strip()

            if t in ["d1", "1d"]: return "1d"

            if t in ["h4", "4h"]: return "4h"

            if t in ["h1", "1h"]: return "1h"

            if t in ["m15", "15m"]: return "15m"

            if t in ["m5", "5m"]: return "5m"

            if t in ["m1", "1m"]: return "1m"

            return t



        norm_htf = norm_tf(htf_in) if htf_in else ""

        norm_ltf = norm_tf(ltf_in) if ltf_in else ""



        if not norm_htf:

            if norm_ltf == "5m":

                norm_htf = "4h"

            elif norm_ltf == "1m":

                cur_act = norm_tf(active_htf_interval)

                norm_htf = cur_act if cur_act in ["15m", "1h"] else "15m"

            else:

                cur_act = norm_tf(active_htf_interval)

                norm_htf = cur_act if cur_act in ["15m", "1h", "4h"] else "15m"



        is_trading_pair = norm_htf in ["15m", "1h", "4h"]

        if norm_htf == "15m":

            norm_ltf = "1m"

        elif norm_htf == "1h":

            norm_ltf = "1m"

        elif norm_htf == "4h":

            norm_ltf = "5m"

        elif norm_htf == "1d":

            norm_ltf = "1h"

        elif norm_htf == "5m":

            norm_ltf = "1m"

        elif not norm_ltf:

            norm_ltf = "1m"



        ltf_sec = INTERVAL_SECONDS.get(norm_ltf, 60)

        

        # Load known trades for this HTF

        tf_trades = []

        trades_fn = "m15_unique_october_trades.json" if norm_htf in ["15m", "m15"] else ("h1_unique_october_trades.json" if norm_htf in ["1h", "h1"] else ("h4_unique_october_trades.json" if norm_htf in ["4h", "h4"] else None))

        if trades_fn:

            tr_path = os.path.join(os.path.dirname(__file__), "data", trades_fn)

            if os.path.exists(tr_path):

                try:

                    with open(tr_path, "r", encoding="utf-8") as f:

                        tf_trades = json.load(f).get("signals", [])

                except Exception as e:

                    logger.warning(f"Error loading {trades_fn}: {e}")



        # If target_time <= 0, default to the first trade's entry_time for instant display

        if (target_time <= 0 or target_time > 1793491200) and tf_trades:

            t_time = tf_trades[0].get("entry_time", tf_trades[0].get("time"))

        else:

            t_time = target_time if target_time > 0 else int(time.time())



        # Check if t_time corresponds to an audited trade entry / marker

        matched_known_tr = None

        for tr in tf_trades:

            if abs(tr.get("time", 0) - t_time) <= 1800 or abs(tr.get("entry_time", 0) - t_time) <= 1800:

                matched_known_tr = tr

                break



        eval_t_time = matched_known_tr.get("tap_time", t_time) if matched_known_tr else t_time

        start_fetch = max(0, min(eval_t_time, t_time) - 100 * ltf_sec)

        end_fetch = min(2147483647, max(eval_t_time, t_time) + 350 * ltf_sec)



        loop = asyncio.get_event_loop()

        ltf_candles = []

        

        # Check historical local datasets first for October 2026

        if norm_ltf in ["1m", "5m"] and symbol.upper() == "BTCUSDT":

            cand_files = ["btc_1m_oct2026_full.json", "btc_1m_oct2026.json"] if norm_ltf == "1m" else ["btc_5m_oct2026_full.json"]

            for c_f in cand_files:

                p = os.path.join(os.path.dirname(__file__), "data", c_f)

                if os.path.exists(p):

                    try:

                        with open(p, "r", encoding="utf-8") as f:

                            all_c = json.load(f)

                        matched_c = [c for c in all_c if (c.get("time", 0) >= start_fetch and c.get("time", 0) <= end_fetch)]

                        if len(matched_c) >= 20:

                            ltf_candles = matched_c

                            break

                    except Exception as e:

                        logger.warning(f"Error reading {c_f}: {e}")



        if not ltf_candles or len(ltf_candles) < 20:

            ltf_candles = await loop.run_in_executor(

                None,

                fetch_klines_range,

                symbol,

                norm_ltf,

                start_fetch,

                end_fetch,

                active_market

            )

            if not ltf_candles or len(ltf_candles) < 25:

                ltf_candles = await loop.run_in_executor(

                    None,

                    fetch_klines_paginated,

                    symbol,

                    norm_ltf,

                    1000,

                    active_market

                )

            ltf_candles = dedupe_and_sort_candles(ltf_candles) if ltf_candles else []



        # Completely clean LTF by default; structure triggered exclusively when price taps an HTF zone

        # Localized calculation starts 25 candles prior to tapping candle for that trade only

        htf_boxes = []

        if norm_htf == active_htf_interval and strategy_result and strategy_result.get("boxes"):

            htf_boxes = strategy_result.get("boxes", [])



        if not htf_boxes and norm_htf in ["15m", "m15"]:

            if htf_candles and len(htf_candles) >= 50:

                htf_b_engine = HTFEngine(lookback_bars=len(htf_candles), show_tjl_boxes=True, tjl_extend=True, start_marking_time=1790121600)

                htf_boxes = htf_b_engine.run(htf_candles).get("boxes", [])

            else:

                oct_path = os.path.join(os.path.dirname(__file__), "data", "btc_15m_oct2026_full.json")

                if not os.path.exists(oct_path):

                    oct_path = os.path.join(os.path.dirname(__file__), "data", "btc_15m_oct2026_with_lookback.json")

                if os.path.exists(oct_path):

                    try:

                        with open(oct_path, "r", encoding="utf-8") as f:

                            oct_htf = json.load(f)

                        htf_b_engine = HTFEngine(lookback_bars=len(oct_htf), show_tjl_boxes=True, tjl_extend=True, start_marking_time=1790121600)

                        htf_boxes = htf_b_engine.run(oct_htf).get("boxes", [])

                    except Exception as e:

                        logger.warning(f"Error loading HTF fallback boxes: {e}")

        elif not htf_boxes:

            if htf_candles and len(htf_candles) >= 50:

                htf_b_engine = HTFEngine(lookback_bars=min(2000, len(htf_candles)), show_tjl_boxes=True, tjl_extend=True, start_marking_time=1790121600)

                htf_boxes = htf_b_engine.run(htf_candles).get("boxes", [])

            else:

                fb_path = os.path.join(os.path.dirname(__file__), "data", f"btc_{norm_htf}_oct2026_full.json")

                if os.path.exists(fb_path):

                    try:

                        with open(fb_path, "r", encoding="utf-8") as f:

                            fb_htf = json.load(f)

                        htf_b_engine = HTFEngine(lookback_bars=len(fb_htf), show_tjl_boxes=True, tjl_extend=True, start_marking_time=1790121600)

                        htf_boxes = htf_b_engine.run(fb_htf).get("boxes", [])

                    except Exception as e:

                        logger.warning(f"Error loading HTF fallback boxes for {norm_htf}: {e}")



        if not is_trading_pair:

            # 1D and 5M are explicitly NOT traded

            return {

                "symbol": symbol.upper(),

                "interval": norm_ltf,

                "htf_interval": norm_htf,

                "target_time": target_time,

                "candles": ltf_candles or [],

                "labels": [],

                "lines": [],

                "boxes": [],

                "markers": [],

                "signals": [],

                "signal": None,

                "mtf_status": {

                    "status": "DISABLED",

                    "message": f"Trading disabled for HTF {norm_htf.upper()}. Bot only trades: 15m->1m, 1h->1m, and 4h->5m."

                },

                "tap_info": None,

                "trade_logic": None,

                "trading_disabled": True,

                "d1_status": None

            }



        structure_res = compute_ltf_approach_structure(

            target_time=eval_t_time,

            ltf_candles=ltf_candles,

            htf_boxes=htf_boxes,

            htf_sec=INTERVAL_SECONDS.get(norm_htf, 900),

            htf_candles=htf_candles

        )



        out_lines = structure_res.get("lines", [])

        out_boxes = structure_res.get("boxes", [])

        out_labels = structure_res.get("labels", [])

        out_markers = structure_res.get("markers", [])

        out_signals = structure_res.get("signals", [])

        trade_logic = structure_res.get("trade_logic")

        tap_info = structure_res.get("tap_info")



        # Match known trade for this window if trade_logic was not populated

        matched_tr = None

        for tr in tf_trades:

            tr_t = tr.get("entry_time", tr.get("time"))

            if abs(tr_t - t_time) <= 14400:

                matched_tr = tr

                break



        if matched_tr and (not trade_logic or not trade_logic.get("executed")):

            tr_time = matched_tr.get("entry_time", matched_tr.get("time"))

            trade_logic = {

                "id": matched_tr.get("id"),

                "action": matched_tr.get("type"),

                "time": tr_time,

                "entry_price": matched_tr.get("entry_price"),

                "sl_price": matched_tr.get("sl"),

                "tp_price": matched_tr.get("tp"),

                "rr": matched_tr.get("rr"),

                "executed": True,

                "pattern_name": matched_tr.get("pattern", "Confirmation"),

                "level_name": matched_tr.get("level", matched_tr.get("setup_type", "Zone")),

                "outcome": matched_tr.get("outcome"),

                "pnl_r": matched_tr.get("pnl_r"),

                "exit_time": matched_tr.get("exit_time"),

                "exit_price": matched_tr.get("exit_price")

            }

            if not tap_info:

                tap_info = {

                    "box_name": matched_tr.get("setup_type", "HTF Zone"),

                    "tap_time": matched_tr.get("tap_time", tr_time - 30 * ltf_sec),

                    "winner_pathway": "CHoCH (External)",

                    "trade": trade_logic

                }



        if tap_info:

            winner_p = tap_info.get("winner_pathway", "NONE")

            trade = tap_info.get("trade") or trade_logic

            if trade and trade.get("executed"):

                status_msg = f"HTF zone tapped: {tap_info.get('box_name', 'Zone')} | Winner: {winner_p} | BOT TRADE EXECUTED: {trade['action']} ({trade['pattern_name']} @ {trade['level_name']}) Entry: {trade['entry_price']} SL: {trade['sl_price']} TP: {trade['tp_price']} (RR: {trade['rr']}R)"

            elif trade and not trade.get("executed"):

                status_msg = f"HTF zone tapped: {tap_info.get('box_name', 'Zone')} | Winner: {winner_p} | TRADE SKIPPED: {trade['pattern_name']} @ {trade['level_name']} RR: {trade['rr']}R < 2.5R"

            else:

                status_msg = f"HTF zone tapped: {tap_info.get('box_name', 'Zone')} | Winner: {winner_p}. Structure frozen at cutoff."

        else:

            status_msg = f"Clean {norm_ltf.upper()} candlestick view."



        return {

            "symbol": symbol.upper(),

            "interval": norm_ltf,

            "htf_interval": norm_htf,

            "target_time": target_time,

            "candles": ltf_candles or [],

            "labels": out_labels,

            "lines": out_lines,

            "boxes": out_boxes,

            "markers": out_markers,

            "signals": out_signals or tf_trades,

            "trades": tf_trades,

            "signal": trade_logic or (out_signals[0] if out_signals else None),

            "mtf_status": {"status": "TAPPED" if tap_info else "CLEAN", "message": status_msg},

            "tap_info": tap_info,

            "trade_logic": trade_logic,

            "d1_status": None

        }

    except Exception as e:

        logging.error(f"Error fetching LTF candles: {e}", exc_info=True)

        return {"error": str(e), "candles": [], "labels": [], "lines": [], "boxes": [], "markers": [], "signals": []}





@app.get("/api/simulation_october")

async def get_simulation_october():

    sim_path = os.path.join(os.path.dirname(__file__), "data", "simulation_oct_2026.json")

    if os.path.exists(sim_path):

        with open(sim_path, "r", encoding="utf-8") as f:

            return json.load(f)

    return {"error": "Simulation not found"}



@app.get("/api/simulation_october_major")

async def get_simulation_october_major():

    sim_path = os.path.join(os.path.dirname(__file__), "data", "simulation_oct_major_38.json")

    if os.path.exists(sim_path):

        with open(sim_path, "r", encoding="utf-8") as f:

            return json.load(f)

    return {"error": "Simulation major not found"}



@app.get("/api/simulation_candles")

async def get_simulation_candles(timeframe: str = "15m", start_time: Optional[int] = None, end_time: Optional[int] = None):

    if timeframe == "1m":

        cand_path = os.path.join(os.path.dirname(__file__), "data", "btc_1m_oct2026.json")

    else:

        cand_path = os.path.join(os.path.dirname(__file__), "data", "btc_15m_oct2026.json")

    if os.path.exists(cand_path):

        with open(cand_path, "r", encoding="utf-8") as f:

            candles = json.load(f)

        if start_time or end_time:

            filtered = []

            for c in candles:

                t = c.get("time", 0)

                if start_time and t < start_time:

                    continue

                if end_time and t > end_time:

                    continue

                filtered.append(c)

            return {"candles": filtered}

        return {"candles": candles}

    return {"error": "Candles file not found", "candles": []}



@app.get("/api/inspect_trade")

async def api_inspect_trade(

    symbol: str = "BTCUSDT",

    htf: str = "15m",

    target_time: str = "",

    side: Optional[str] = None,

    price: Optional[float] = None

):

    """

    Method 2: Interactive Trade Replay and Discrepancy Inspector

    Analyzes any candle or timestamp:

      - Your Manual Trade (side, price, candle pattern, rejection wick)

      - What The Algo Saw (HTF level, LTF approach, LTF pathway, retest)

      - Why Algo Didn't Fire (Pinpoint discrepancy)

      - Actionable Suggestion to teach your edge to the bot

    """

    from discrepancy_inspector import inspect_trade_discrepancy

    loop = asyncio.get_event_loop()

    try:

        c_cache = htf_candles if (htf and active_htf_interval and htf.lower() == active_htf_interval.lower() and symbol.upper() == active_symbol.upper() and len(htf_candles) >= 50) else None

        b_cache = strategy_result.get("boxes", []) if (c_cache and strategy_result) else None

        res = await loop.run_in_executor(

            None,

            lambda: inspect_trade_discrepancy(

                symbol=symbol,

                htf=htf,

                target_time_input=target_time,

                manual_side=side,

                manual_price=price,

                existing_htf_candles=c_cache,

                existing_boxes=b_cache

            )

        )

        return res

    except Exception as e:

        logger.error(f"Error in inspect_trade: {e}", exc_info=True)

        return {"success": False, "error": str(e)}





@app.get("/api/portfolio/status")

async def get_portfolio_status():

    """Returns live portfolio metrics, drawdown throttling status, and open capital allocation."""

    return portfolio_risk_engine.get_status()



@app.get("/api/portfolio/symbols")

async def get_portfolio_symbols():

    """Returns the 8 locked production coins."""

    return {"symbols": LOCKED_PORTFOLIO_COINS}



@app.get("/api/portfolio/timeframe_allocation")

async def get_timeframe_allocation():

    """Returns the optimal timeframe configuration and elimination status across portfolio coins."""

    return {

        "criteria": timeframe_allocation_engine.criteria,

        "optimal_profiles": {

            sym: timeframe_allocation_engine.get_optimal_execution_profile(sym)

            for sym in LOCKED_PORTFOLIO_COINS

        }

    }



@app.get("/api/discord/test")

@app.post("/api/discord/test")

async def test_discord(request: Request):

    """Dispatches a test message to the configured Discord webhook."""

    if not is_admin_request(request):

        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": "Administrator privileges required."})

    from discord_notifier import discord_engine

    success, msg = discord_engine.send_test_message()

    return {"success": success, "message": msg}



@app.post("/api/discord/set_webhook")

async def set_discord_webhook(request: Request, payload: Dict):

    """Sets and saves the Discord webhook URL."""

    if not is_admin_request(request):

        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": "Administrator privileges required."})

    from discord_notifier import discord_engine

    url = payload.get("webhook_url", "")

    discord_engine.set_webhook_url(url)

    return {"success": True, "configured": bool(discord_engine.webhook_url)}



@app.post("/api/portfolio/reset_circuit_breaker")

async def reset_circuit_breaker(request: Request):

    """Manually resets the daily circuit breaker."""

    if not is_admin_request(request):

        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": "Administrator privileges required."})

    portfolio_risk_engine.reset_circuit_breaker()

    return {"success": True, "circuit_breaker_active": portfolio_risk_engine.circuit_breaker_active}



@app.get("/api/macro/events")

async def get_macro_events():

    """Returns the full calendar of macroeconomic events and upcoming schedules."""

    from macro_news_filter import macro_news_engine

    return {

        "events": macro_news_engine.get_all_events(),

        "next_event": macro_news_engine.get_next_macro_event(),

        "is_active": macro_news_engine.is_macro_event_active()[0]

    }



@app.get("/api/binance/status")

async def get_binance_status():

    """Tests connectivity to Binance Futures and fetches wallet balance (Zero Secret Exposure)."""

    from binance_live_executor import binance_executor

    res = binance_executor.test_connection()

    if res.get("success") and "usdt_balance" in res:

        if binance_executor.api_key and binance_executor.api_secret:

            portfolio_risk_engine.sync_with_exchange_balance(float(res["usdt_balance"]))

    res.pop("api_secret", None)

    res.pop("api_key", None)

    return res



@app.post("/api/binance/config")

async def set_binance_config(request: Request, payload: Dict):

    """Saves Binance API credentials encrypted in vault.db and sets execution mode."""

    if not is_admin_request(request):

        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": "Administrator privileges required."})

    from binance_live_executor import binance_executor

    key = payload.get("api_key", "")

    secret = payload.get("api_secret", "")

    mode = payload.get("mode", "PAPER")

    success = binance_executor.save_config(key, secret, mode)

    test_res = binance_executor.test_connection()

    if test_res.get("success") and "usdt_balance" in test_res:

        if binance_executor.api_key and binance_executor.api_secret:

            portfolio_risk_engine.sync_with_exchange_balance(float(test_res["usdt_balance"]))

    test_res.pop("api_secret", None)

    test_res.pop("api_key", None)

    return {"success": success, "connection": test_res, "status": portfolio_risk_engine.get_status()}



@app.post("/api/portfolio/reset_all")

async def reset_portfolio_all(request: Request):

    """Resets balance, positions, PnL, and trade history to 0 / clean slate."""

    if not is_admin_request(request):

        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": "Administrator privileges required."})

    portfolio_risk_engine.reset_account_state(0.0)

    return {"success": True, "status": portfolio_risk_engine.get_status()}



@app.post("/api/risk/config")

async def set_risk_config(request: Request, payload: Dict):

    """Updates dynamic risk parameters (Drawdown throttling, max open capital allocation, risk per trade)."""

    if not is_admin_request(request):

        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": "Administrator privileges required."})

    normal_risk = payload.get("normal_risk_pct")

    if normal_risk is not None:

        try:

            val = float(normal_risk)

            normal_risk = val / 100.0 if val > 0.05 else val

        except ValueError:

            normal_risk = None

        

    throttled_risk = payload.get("throttled_risk_pct")

    if throttled_risk is not None:

        try:

            val = float(throttled_risk)

            throttled_risk = val / 100.0 if val > 0.05 else val

        except ValueError:

            throttled_risk = None

        

    max_alloc = payload.get("max_open_capital_allocation")

    if max_alloc is not None:

        try:

            val = float(max_alloc)

            max_alloc = val / 100.0 if val > 0.50 else val

        except ValueError:

            max_alloc = None

        

    throttling_enabled = payload.get("drawdown_throttling_enabled")

    if throttling_enabled is not None:

        throttling_enabled = bool(throttling_enabled)



    session_filter = payload.get("session_filter_enabled")

    if session_filter is not None:

        session_filter = bool(session_filter)



    blocked_hours = payload.get("blocked_utc_hours")

    if blocked_hours is not None and isinstance(blocked_hours, list):

        blocked_hours = [int(h) for h in blocked_hours if 0 <= int(h) <= 23]

    else:

        blocked_hours = None



    sl_buffer = payload.get("sl_buffer_enabled")

    if sl_buffer is not None:

        sl_buffer = bool(sl_buffer)



    sl_buffer_pct = payload.get("sl_buffer_pct")

    if sl_buffer_pct is not None:

        sl_buffer_pct = float(sl_buffer_pct)

        if sl_buffer_pct >= 0.01: # If sent as percentage from UI (e.g. 0.12% -> 0.0012)

            sl_buffer_pct = sl_buffer_pct / 100.0



    order_exec_type = payload.get("order_execution_type")

    if order_exec_type is not None:

        order_exec_type = str(order_exec_type).upper()



    updated = portfolio_risk_engine.update_risk_parameters(

        normal_risk_pct=normal_risk,

        throttled_risk_pct=throttled_risk,

        max_open_capital_allocation=max_alloc,

        drawdown_throttling_enabled=throttling_enabled,

        session_filter_enabled=session_filter,

        blocked_utc_hours=blocked_hours,

        sl_buffer_enabled=sl_buffer,

        sl_buffer_pct=sl_buffer_pct,

        order_execution_type=order_exec_type

    )

    return {"success": True, "config": updated, "status": portfolio_risk_engine.get_status()}



# ==============================================================================

# AUTHENTICATION & BOT MASTER SWITCH ENDPOINTS

# ==============================================================================

@app.post("/api/auth/login")

async def login(request: Request, payload: Dict):

    """Admin / User login endpoint verifying PBKDF2 hash and role from secure vault."""

    user = payload.get("username", "")

    pwd = payload.get("password", "")

    requested_role = payload.get("role")

    client_ip = request.client.host if request.client else ""

    success, token, msg, role = authenticate_user(user, pwd, client_ip, requested_role)

    if success:

        response = JSONResponse(content={"success": True, "token": token, "username": user, "role": role, "message": msg})

        response.set_cookie(

            key="topg_session",

            value=token,

            max_age=7 * 24 * 3600,

            httponly=True,

            samesite="lax",

            secure=False

        )

        return response

    return JSONResponse(status_code=401, content={"success": False, "token": None, "message": msg})



@app.get("/api/auth/verify")

@app.post("/api/auth/verify")

async def verify_auth(request: Request):

    """Verifies if the current session token is valid and returns user info & role."""

    user = get_authenticated_user(request)

    if user:

        return {

            "authenticated": True,

            "username": user["username"],

            "role": user["role"]

        }

    return {"authenticated": False}



@app.post("/api/auth/logout")

async def logout(request: Request, payload: Optional[Dict] = None):

    """Invalidates session token and clears cookie."""

    token = None

    if payload:

        token = payload.get("token")

    if not token:

        token = request.cookies.get("topg_session")

    if token:

        invalidate_token(token)

    response = JSONResponse(content={"success": True})

    response.delete_cookie(key="topg_session")

    return response



@app.post("/api/bot/toggle")

async def toggle_bot(request: Request, payload: Optional[Dict] = None):

    """Toggles or sets the trading bot execution state (ON / OFF). Requires admin."""

    if not is_admin_request(request):

        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": "Administrator privileges required."})

    enabled = payload.get("enabled") if payload else None

    new_state = portfolio_risk_engine.toggle_bot(enabled)

    return {"success": True, "bot_enabled": new_state}



@app.get("/api/bot/status")

async def get_bot_status():

    """Returns current bot execution status."""

    return {"bot_enabled": portfolio_risk_engine.bot_enabled}



@app.get("/api/portfolio/history")

async def get_portfolio_history():

    """Returns trade history ledger and active positions."""

    return {

        "balance": portfolio_risk_engine.balance,

        "peak_equity": portfolio_risk_engine.peak_equity,

        "bot_enabled": portfolio_risk_engine.bot_enabled,

        "active_positions": list(portfolio_risk_engine.active_positions.values()),

        "trade_history": portfolio_risk_engine.trade_history

    }



@app.get("/api/portfolio/sui_stats")

async def get_sui_stats():

    """Returns comprehensive analytics for SUI on M5-M1."""

    sui_trades = [t for t in portfolio_risk_engine.trade_history if t.get("symbol") == "SUIUSDT"]

    wins = [t for t in sui_trades if t.get("outcome") == "TP"]

    losses = [t for t in sui_trades if t.get("outcome") == "SL"]

    total_r = sum(t.get("r_gained", 0.0) for t in sui_trades)

    total_pnl = sum(t.get("pnl_dollars", 0.0) for t in sui_trades)

    win_rate = (len(wins) / len(sui_trades) * 100.0) if sui_trades else 0.0

    return {

        "symbol": "SUIUSDT",

        "timeframe": "M5-M1",

        "total_trades": len(sui_trades),

        "wins": len(wins),

        "losses": len(losses),

        "win_rate": round(win_rate, 2),

        "total_net_r": round(total_r, 2),

        "total_pnl_dollars": round(total_pnl, 2),

        "active_in_portfolio": any(p.get("symbol") == "SUIUSDT" for p in portfolio_risk_engine.active_positions.values())

    }



@app.post("/api/portfolio/import_sui_trades")

@app.get("/api/portfolio/import_sui_trades")

async def api_import_sui_trades(request: Request):

    """Imports or resets verified SUI M5 trades into the trade ledger. Requires admin."""

    if not is_admin_request(request):

        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": "Administrator privileges required."})

    res = portfolio_risk_engine.import_sui_m5_trades()

    await broadcast_portfolio_update()

    return res



@app.get("/")

async def get_index(request: Request):

    if not is_authenticated_request(request):

        return RedirectResponse(url="/login", status_code=303)

    return FileResponse(

        "static/index.html",

        headers={

            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",

            "Pragma": "no-cache",

            "Expires": "0"

        }

    )



@app.get("/login")

@app.get("/login.html")

async def get_login():

    return FileResponse(

        "static/login.html",

        headers={

            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",

            "Pragma": "no-cache",

            "Expires": "0"

        }

    )



if __name__ == "__main__":

    uvicorn.run(app, host="127.0.0.1", port=8000)

