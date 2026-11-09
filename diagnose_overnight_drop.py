import json
from server import (
    fetch_klines_paginated,
    HTFEngine,
    compute_ltf_approach_structure,
    is_qualifying_htf_zone,
    is_htf_box_active,
    ZONE_SINGLE_TRADE_REGISTRY,
    INTERVAL_SECONDS
)

for symbol, htf_tf, ltf_tf in [("BTCUSDT", "15m", "1m"), ("BTCUSDT", "1h", "1m"), ("SOLUSDT", "15m", "1m"), ("SOLUSDT", "4h", "5m")]:
    recent_htf = fetch_klines_paginated(symbol, htf_tf, 1000, "futures")
    recent_ltf = fetch_klines_paginated(symbol, ltf_tf, 1000, "futures")
    if not recent_htf or not recent_ltf:
        continue
    closed_ltf = recent_ltf[:-1]
    latest_closed_ltf_time = closed_ltf[-1]["time"]
    current_p = closed_ltf[-1]["close"]

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

    recent_check = closed_ltf[-20:]
    tapped = []
    for b in available_boxes:
        b_top = max(b.get("top", 0), b.get("bottom", 0))
        b_bot = min(b.get("top", 0), b.get("bottom", 0))
        if any(c["high"] >= b_bot and c["low"] <= b_top for c in recent_check):
            tapped.append(b)

    print(f"\n==================== {symbol} {htf_tf}->{ltf_tf} (Price: {current_p}) ====================")
    print(f"Active unmitigated: {len(active_boxes)}, Available: {len(available_boxes)}, Tapped in last 20 bars: {len(tapped)}")
    if tapped:
        for tb in tapped:
            print(f"  Tapped box: {tb.get('text')} [{tb.get('bottom')} - {tb.get('top')}] (Bullish: {tb.get('is_bullish')})")

        htf_sec_val = INTERVAL_SECONDS.get(htf_tf.lower(), 900)
        res = compute_ltf_approach_structure(
            target_time=latest_closed_ltf_time,
            ltf_candles=closed_ltf,
            htf_boxes=available_boxes,
            htf_sec=htf_sec_val,
            htf_candles=recent_htf
        )
        tap_info = res.get("tap_info")
        print(f"  --> tap_info: {tap_info}")
        if tap_info:
            tr = tap_info.get("trade")
            print(f"  --> trade: {tr}")
            if tr:
                tr_time = tr.get("time")
                ltf_sec_val = INTERVAL_SECONDS.get(ltf_tf.lower(), 60)
                diff = abs(tr_time - latest_closed_ltf_time)
                print(f"  --> Age diff: {diff}s (allowed: {ltf_sec_val}s)")
                entry_p = tr["entry_price"]
                sl_p = tr["sl_price"]
                tp_p = tr["tp_price"]
                risk_d = abs(entry_p - sl_p)
                reward_d = abs(tp_p - entry_p)
                rr = reward_d / risk_d if risk_d > 0 else 0
                print(f"  --> Entry: {entry_p}, SL: {sl_p}, TP: {tp_p}, RR: {rr:.2f}R")
