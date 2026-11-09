"""
DEPRECATED: LTFEngine legacy module.
====================================
This module previously contained Fair Value Gap (FVG) detection from early
iterations of 'LTF Buy & Sell SL TP.pine'.

The canonical TopG institutional strategy does NOT use FVG.
All zone tap reactions, outside-in approach verification, 120-candle reaction cycles,
and candlestick reversal confirmations are canonically implemented in `ltf_approach_engine.py`.

This file is maintained strictly as a backwards-compatibility shim.
"""

import warnings
from typing import List, Dict, Optional
from ltf_approach_engine import compute_ltf_approach_structure, scan_ltf_trade_entry


class LTFEngine:
    """
    Deprecated bridge to ltf_approach_engine.py.
    Retained solely for backwards compatibility with any legacy imports.
    """
    def __init__(self,
                 lookback_bars: int = 500,
                 use_wick_break: bool = True,
                 show_choch_fvg: bool = False,
                 show_reversal_signals: bool = False,
                 min_rr: float = 3.0,
                 sl_prop_percent: float = 0.0012,
                 htf_tap_required: bool = True,
                 **kwargs):
        self.lookback_bars = lookback_bars
        self.use_wick_break = use_wick_break
        self.show_choch_fvg = False  # FVG explicitly disabled
        self.show_reversal_signals = show_reversal_signals
        self.min_rr = min_rr
        self.sl_prop_percent = sl_prop_percent
        self.htf_tap_required = htf_tap_required

    def run(self, candles: List[Dict], htf_zones: List[Dict] = None, tap_bar_idx: Optional[int] = None) -> Dict:
        """
        Delegates structure computation directly to the canonical ltf_approach_engine.
        """
        if not candles:
            return {"lines": [], "labels": [], "boxes": [], "signals": [], "markers": []}

        target_time = candles[-1]["time"]
        return compute_ltf_approach_structure(
            target_time=target_time,
            ltf_candles=candles,
            htf_boxes=htf_zones or []
        )
