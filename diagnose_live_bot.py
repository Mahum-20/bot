import asyncio
import json
import time
from server import (
    fetch_klines_paginated,
    HTFEngine,
    compute_ltf_approach_structure,
    is_qualifying_htf_zone,
    is_htf_box_active,
    ZONE_SINGLE_TRADE_REGISTRY,
    timeframe_allocation_engine,
    portfolio_risk_engine,
    INTERVAL_SECONDS
)

symbols = ["BTCUSDT", "SOLUSDT", "PAXGUSDT"]

for symbol in symbols:
    print(f"\n=================== DIAGNOSTIC FOR {symbol} ===================")
    allowed_profiles = timeframe_allocation_engine.get_allowed_execution_profiles(symbol)
    for prof in allowed_profiles:
        htf_tf = prof["htf"]
        ltf_tf = prof["ltf"]
        
        # 1. Fetch candles
        recent_htf = fetch_klines_paginated(symbol, htf_tf, 1000, "futures")
        recent_ltf = fetch_klines_paginated(symbol, ltf_tf, 1000, "futures")
        
        if not recent_htf or not recent_ltf:
            print(f"[{symbol} {htf_tf}->{ltf_tf}] Failed to fetch candles.")
            continue
            
        closed_ltf = recent_ltf[:-1]
        latest_closed_ltf_time = closed_ltf[-1]["time"]
        current_price = closed_ltf[-1]["close"]
        
        # 2. Run HTF Engine
        htf_engine = HTFEngine(lookback_bars=len(recent_htf), show_tjl_boxes=True, tjl_extend=True)
        htf_res = htf_engine.run(recent_htf)
        raw_boxes = [b for b in htf_res.get("boxes", []) if is_qualifying_htf_zone(b)]
        
        for b in raw_boxes:
            b_left = b.get("confirmed_formation_time") or b.get("left") or b.get("start_time") or b.get("time") or 0
            b["confirmed_formation_time"] = b_left
            if "mitigated_time" not in b:
                b["mitigated_time"] = b.get("right")
                
        active_boxes = [
            b for b in raw_boxes
            if is_htf_box_active(b, latest_closed_ltf_time) and latest_closed_ltf_time >= b.get("confirmed_formation_time", 0)
        ]
        
        available_boxes = []
        for b in active_boxes:
            b_id = b.get("id") or f"{b.get('text')}_{b.get('top')}_{b.get('bottom')}_{b.get('confirmed_formation_time', 0)}"
            reg_key = f"{symbol}_{htf_tf}_{b_id}"
            if reg_key not in ZONE_SINGLE_TRADE_REGISTRY:
                available_boxes.append(b)
                
        print(f"\n--- {htf_tf} -> {ltf_tf} --- Current Price: {current_price}")
        print(f"Total raw boxes: {len(raw_boxes)}, Active unmitigated: {len(active_boxes)}, Available: {len(available_boxes)}")
        
        # Find nearest boxes
        nearest = []
        for b in available_boxes:
            top = max(b.get("top", 0), b.get("bottom", 0))
            bot = min(b.get("top", 0), b.get("bottom", 0))
            mid = (top + bot) / 2.0
            dist = abs(mid - current_price)
            nearest.append((dist, b))
        nearest.sort(key=lambda x: x[0])
        
        print("Top 3 Nearest Available Zones:")
        for dist, b in nearest[:3]:
            top = max(b.get("top", 0), b.get("bottom", 0))
            bot = min(b.get("top", 0), b.get("bottom", 0))
            pos = "INSIDE" if bot <= current_price <= top else ("ABOVE (Supply)" if bot > current_price else "BELOW (Demand)")
            print(f"  • {b.get('text')} [{bot:.2f} - {top:.2f}] | Pos: {pos} | Dist: {dist:.2f} ({dist/current_price*100:.2f}%)")
            
        # Check tap in last 20 bars
        recent_check = closed_ltf[-20:]
        tapped_boxes = []
        for b in available_boxes:
            b_top = max(b.get("top", 0), b.get("bottom", 0))
            b_bot = min(b.get("top", 0), b.get("bottom", 0))
            if any(c["high"] >= b_bot and c["low"] <= b_top for c in recent_check):
                tapped_boxes.append(b)
                
        if not tapped_boxes:
            print(f"  Status: Price has NOT tapped any active {htf_tf} zone in the last 20 {ltf_tf} bars.")
        else:
            print(f"  Status: Price TAPPED {len(tapped_boxes)} zones: {[b.get('text') for b in tapped_boxes]}")
            htf_sec_val = INTERVAL_SECONDS.get(htf_tf.lower(), 900)
            res = compute_ltf_approach_structure(
                target_time=latest_closed_ltf_time,
                ltf_candles=closed_ltf,
                htf_boxes=available_boxes,
                htf_sec=htf_sec_val,
                htf_candles=recent_htf
            )
            tap_info = res.get("tap_info")
            if not tap_info:
                print("  LTF Approach: No tap_info returned.")
            elif not tap_info.get("trade"):
                print("  LTF Approach: Tapped, but NO executed candlestick confirmation pattern formed on latest bar.")
            else:
                tr = tap_info["trade"]
                tr_time = tr.get("time")
                ltf_sec_val = INTERVAL_SECONDS.get(ltf_tf.lower(), 60)
                time_diff = abs(tr_time - latest_closed_ltf_time)
                print(f"  Trade found: {tr.get('action')} @ {tr.get('entry_price')} | Pattern: {tr.get('pattern_name')} | Age diff: {time_diff}s (allowed: {ltf_sec_val}s)")
