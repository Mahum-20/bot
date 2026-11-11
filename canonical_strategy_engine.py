"""
Canonical Strategy Engine (Single Authoritative Source of Truth)
================================================================
Unifies Live Autonomous Execution, Historical Backtesting, and
Dashboard Visual Signaling under the exact same decision pipeline:

1. Rolling 500-candle FIFO HTF Market Structure (HTFEngine).
2. Point-in-time Qualifying HTF Zones (ZONE-001, ZONE-002, ZONE-003).
3. 120-Candle Reaction Cycle State Machine (MTF-004).
4. Localized 5-Wave Internal Structure vs. CHoCH Race Condition (LTF-001).
5. Intermediate Entry-Level Generation (Level of 3/4 or QML/TJL).
6. First Zone-Boundary Retest with Candlestick Reversal Confirmation (CANDLE-001, CANDLE-002).
7. Institutional 0.5x ATR_15M Stop Loss Cushion (RISK-001).
8. Profile-Specific Target Models:
   - 4H -> 5M: Fixed 3.0:1 R:R
   - 1H -> 1M: Opposing HTF Liquidity Pool (Floor >= 2.50:1 R:R)
   - 15M -> 1M: Opposing HTF Liquidity Pool (Floor >= 2.50:1 R:R)
9. Atomic One-Trade-Per-Zone Registry (RISK-003).
"""

import logging
from typing import List, Dict, Optional, Tuple, Any, Set
from htf_engine import HTFEngine, is_htf_box_active
from ltf_approach_engine import compute_ltf_approach_structure, is_valid_tap_approach
from zone_trade_registry import zone_trade_registry, ZoneTradeRegistry
from htf_level_lifecycle_manager import htf_level_lifecycle_manager

logger = logging.getLogger("CanonicalStrategyEngine")

VALID_TIMEFRAME_PAIRS = {
    ("4h", "5m"),
    ("1h", "1m"),
    ("15m", "1m")
}

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


def get_target_ltf(htf_tf: str) -> Optional[str]:
    tf = (htf_tf or "").lower()
    if tf in ("15m", "m15"):
        return "1m"
    elif tf in ("1h", "h1"):
        return "1m"
    elif tf in ("4h", "h4"):
        return "5m"
    return None


class CanonicalStrategyEngine:
    """
    Authoritative single-source decision engine consumed by:
    - server.py live execution monitor
    - faithful_backtest_engine.py chronological simulator
    - mtf_strategy.py chart signaling & dashboard APIs
    """
    def __init__(self, registry: Optional[ZoneTradeRegistry] = None):
        self.registry = registry or zone_trade_registry

    @staticmethod
    def get_seconds(tf: str) -> int:
        tf_clean = (tf or "15m").lower()
        if tf_clean in INTERVAL_SECONDS:
            return INTERVAL_SECONDS[tf_clean]
        if tf_clean.endswith("m"):
            return int(tf_clean[:-1]) * 60
        if tf_clean.endswith("h"):
            return int(tf_clean[:-1]) * 3600
        if tf_clean.endswith("d"):
            return int(tf_clean[:-1]) * 86400
        return 900

    def evaluate_cycle_step(
        self,
        symbol: str,
        htf_tf: str,
        ltf_tf: str,
        current_ltf_candle: Dict,
        closed_ltf_candles: List[Dict],
        closed_htf_candles: List[Dict],
        active_htf_boxes: List[Dict],
        zone_cycles: Dict[str, Dict],
        is_live: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates one closed LTF bar in strict chronological order.
        Manages 120-candle reaction cycles and produces trade signals.
        
        Guarantees:
        - Point-in-time integrity: no data beyond current_ltf_candle['time'].
        - 120-candle reaction window enforcement.
        - Canonical race condition and intermediate levels.
        - Profile-specific target models (4H fixed 3R vs 1H/15M opposing liquidity >= 2.5R).
        """
        c_time = current_ltf_candle["time"]
        ltf_sec = self.get_seconds(ltf_tf)
        htf_sec = self.get_seconds(htf_tf)
        max_cycle_seconds = 120 * ltf_sec

        # 1. Clean up expired reaction cycles (> 120 candles from initial tap)
        expired_keys = [
            k for k, cyc in zone_cycles.items()
            if (c_time - cyc["initial_tap_time"]) > max_cycle_seconds
        ]
        for k in expired_keys:
            del zone_cycles[k]

        # 2. Check for new zone taps from outside to open reaction cycles
        curr_idx = len(closed_ltf_candles) - 1
        for b in active_htf_boxes:
            b_name = b.get("text") or b.get("name") or "Level"
            b_left = b.get("left") or b.get("created_time") or 0
            b_top = max(b.get("top", 0), b.get("bottom", 0))
            b_bot = min(b.get("top", 0), b.get("bottom", 0))
            b_id = f"{b_name}_{b_left}_{b_top:.2f}_{b_bot:.2f}"
            reg_key = self.registry.get_zone_key(symbol, htf_tf, b_id)

            # Skip if zone has already been locked/traded or invalidated (Rules RISK-003, ZONE-003)
            if self.registry.is_zone_locked(reg_key):
                continue
            can_trade, _ = htf_level_lifecycle_manager.is_box_tradable(symbol, htf_tf, b)
            if not can_trade:
                continue

            if reg_key not in zone_cycles:
                c_high = current_ltf_candle.get("high", 0.0)
                c_low = current_ltf_candle.get("low", 0.0)
                if c_high >= b_bot and c_low <= b_top:
                    if is_valid_tap_approach(b, closed_ltf_candles, curr_idx):
                        zone_cycles[reg_key] = {
                            "symbol": symbol,
                            "htf_tf": htf_tf,
                            "initial_tap_time": c_time,
                            "initial_tap_idx": curr_idx,
                            "box": b,
                            "reg_key": reg_key
                        }
                        logger.info(f"[{symbol} {htf_tf}->{ltf_tf}] Opened 120-candle reaction cycle for {b_name} at {c_time}")

        if not zone_cycles:
            return None

        # 3. Process active cycles for trade confirmation on current bar
        matching_cycles = [
            (k, cyc) for k, cyc in zone_cycles.items()
            if cyc.get("symbol") == symbol and cyc.get("htf_tf") == htf_tf
        ]
        if not matching_cycles:
            return None

        # Localized LTF history slice (500 bars lookback up to current bar)
        ltf_slice = closed_ltf_candles[max(0, curr_idx - 500):curr_idx + 1]

        for reg_key, cyc in matching_cycles:
            init_tap_time = cyc["initial_tap_time"]
            target_box = cyc["box"]

            res = compute_ltf_approach_structure(
                target_time=init_tap_time,
                ltf_candles=ltf_slice,
                htf_boxes=active_htf_boxes,
                htf_sec=htf_sec,
                htf_candles=closed_htf_candles,
                override_tap_time=init_tap_time,
                override_box=target_box,
                as_of_time=c_time
            )

            tap_info = res.get("tap_info")
            if not tap_info:
                continue

            # Check A+ setup elimination (Rule RISK-005)
            box_name = str(tap_info.get("box_name", "")).upper()
            if "A+" in box_name:
                continue

            tr = tap_info.get("trade")
            if not tr or not tr.get("executed"):
                continue

            # Signal Latency / Real-Time Check:
            # Signal MUST fire on the latest closed candle (or within 1 bar latency)
            tr_time = tr.get("time")
            if abs(tr_time - c_time) > ltf_sec:
                continue

            # Enrich trade signal payload
            tr["reg_key"] = reg_key
            tr["symbol"] = symbol
            tr["htf_tf"] = htf_tf
            tr["ltf_tf"] = ltf_tf
            tr["box_name"] = box_name
            for ts_k in [
                "h4_formation_time", "h4_tap_time", "historical_bos_time",
                "structural_anchor_time", "reversal_confirmation_time",
                "entry_levels_time", "retest_time", "entry_confirmation_time",
                "winning_pathway"
            ]:
                if ts_k not in tr and ts_k in tap_info:
                    tr[ts_k] = tap_info[ts_k]

            # Enforce target model parity verification
            req_rr = 3.0 if htf_sec >= 14400 else 2.5
            if tr.get("rr", 0.0) < req_rr:
                continue

            # Close cycle upon trade generation
            del zone_cycles[reg_key]
            return tr

        return None


# Global singleton instance
canonical_engine = CanonicalStrategyEngine()
