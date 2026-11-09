"""
Binance Futures Exchange Filter Manager
========================================
Manages price precision (tickSize), quantity precision (stepSize),
and minNotional requirements for the 8 locked portfolio coins.
Prevents Binance API error -1111 (Precision over max defined) and LOT_SIZE rejections.
"""

import math
import logging
from typing import Dict, Tuple, Optional
import urllib.request
import json

logger = logging.getLogger("ExchangeFilterManager")

# Hardcoded fallback filters for all 20 locked portfolio coins based on Binance USDT-M Futures specs
DEFAULT_SYMBOL_FILTERS = {
    "BTCUSDT": {"tick_size": 0.10, "price_precision": 2, "step_size": 0.001, "qty_precision": 3, "min_qty": 0.001, "min_notional": 50.0},
    "ETHUSDT": {"tick_size": 0.01, "price_precision": 2, "step_size": 0.001, "qty_precision": 3, "min_qty": 0.001, "min_notional": 20.0},
    "BCHUSDT": {"tick_size": 0.01, "price_precision": 2, "step_size": 0.001, "qty_precision": 3, "min_qty": 0.001, "min_notional": 20.0},
    "LINKUSDT": {"tick_size": 0.001, "price_precision": 3, "step_size": 0.01, "qty_precision": 2, "min_qty": 0.01, "min_notional": 20.0},
    "BNBUSDT": {"tick_size": 0.01, "price_precision": 3, "step_size": 0.01, "qty_precision": 2, "min_qty": 0.01, "min_notional": 5.0},
    "ALGOUSDT": {"tick_size": 0.00001, "price_precision": 6, "step_size": 0.1, "qty_precision": 1, "min_qty": 0.1, "min_notional": 5.0},
    "DOGEUSDT": {"tick_size": 0.00001, "price_precision": 6, "step_size": 1.0, "qty_precision": 0, "min_qty": 1.0, "min_notional": 5.0},
    "RUNEUSDT": {"tick_size": 0.0001, "price_precision": 4, "step_size": 1.0, "qty_precision": 0, "min_qty": 1.0, "min_notional": 5.0},
    "SOLUSDT": {"tick_size": 0.01, "price_precision": 4, "step_size": 0.01, "qty_precision": 2, "min_qty": 0.01, "min_notional": 5.0},
    "AVAXUSDT": {"tick_size": 0.001, "price_precision": 4, "step_size": 1.0, "qty_precision": 0, "min_qty": 1.0, "min_notional": 5.0},
    "NEARUSDT": {"tick_size": 0.001, "price_precision": 4, "step_size": 1.0, "qty_precision": 0, "min_qty": 1.0, "min_notional": 5.0},
    "INJUSDT": {"tick_size": 0.001, "price_precision": 6, "step_size": 0.1, "qty_precision": 1, "min_qty": 0.1, "min_notional": 5.0},
    "APTUSDT": {"tick_size": 0.0001, "price_precision": 5, "step_size": 0.1, "qty_precision": 1, "min_qty": 0.1, "min_notional": 5.0},
    "SUIUSDT": {"tick_size": 0.0001, "price_precision": 6, "step_size": 0.1, "qty_precision": 1, "min_qty": 0.1, "min_notional": 5.0},
    "TIAUSDT": {"tick_size": 0.0001, "price_precision": 7, "step_size": 1.0, "qty_precision": 0, "min_qty": 1.0, "min_notional": 5.0},
    "WUSDT": {"tick_size": 0.000001, "price_precision": 7, "step_size": 0.1, "qty_precision": 1, "min_qty": 0.1, "min_notional": 5.0},
    "TAOUSDT": {"tick_size": 0.01, "price_precision": 2, "step_size": 0.001, "qty_precision": 3, "min_qty": 0.001, "min_notional": 5.0},
    "ZROUSDT": {"tick_size": 0.0001, "price_precision": 7, "step_size": 0.1, "qty_precision": 1, "min_qty": 0.1, "min_notional": 5.0},
    "HYPEUSDT": {"tick_size": 0.001, "price_precision": 5, "step_size": 0.01, "qty_precision": 2, "min_qty": 0.01, "min_notional": 5.0},
    "PUMPUSDT": {"tick_size": 0.000001, "price_precision": 7, "step_size": 1.0, "qty_precision": 0, "min_qty": 1.0, "min_notional": 5.0},
    "LTCUSDT": {"tick_size": 0.01, "price_precision": 2, "step_size": 0.001, "qty_precision": 3, "min_qty": 0.001, "min_notional": 5.0}
}

class ExchangeFilterManager:
    def __init__(self):
        self.filters: Dict[str, Dict] = dict(DEFAULT_SYMBOL_FILTERS)
        try:
            self.fetch_live_exchange_filters()
        except Exception as e:
            logger.debug(f"Init filter sync notice: {e}")

    def fetch_live_exchange_filters(self) -> bool:
        """Attempts to sync live rules from Binance Futures /fapi/v1/exchangeInfo."""
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                for s in data.get("symbols", []):
                    sym = s.get("symbol")
                    if sym in self.filters:
                        tick_size = 0.01
                        step_size = 0.001
                        min_qty = 0.001
                        min_notional = 5.0
                        
                        for f in s.get("filters", []):
                            ftype = f.get("filterType")
                            if ftype == "PRICE_FILTER":
                                tick_size = float(f.get("tickSize", tick_size))
                            elif ftype == "LOT_SIZE":
                                step_size = float(f.get("stepSize", step_size))
                                min_qty = float(f.get("minQty", min_qty))
                            elif ftype == "MIN_NOTIONAL":
                                min_notional = float(f.get("notional", min_notional))
                        
                        price_precision = max(0, int(round(-math.log10(tick_size)))) if tick_size < 1 else 0
                        qty_precision = max(0, int(round(-math.log10(step_size)))) if step_size < 1 else 0

                        self.filters[sym] = {
                            "tick_size": tick_size,
                            "price_precision": price_precision,
                            "step_size": step_size,
                            "qty_precision": qty_precision,
                            "min_qty": min_qty,
                            "min_notional": min_notional
                        }
            logger.info("Successfully refreshed Binance exchange filters from API.")
            return True
        except Exception as e:
            logger.warning(f"Could not refresh live filters from Binance ({e}), continuing with robust cached filters.")
            return False

    def get_filter(self, symbol: str) -> Dict:
        return self.filters.get(symbol.upper(), DEFAULT_SYMBOL_FILTERS.get("BTCUSDT"))

    def clamp_quantity(self, symbol: str, quantity: float) -> float:
        """
        Clamps quantity down to exact stepSize multiple (Floor rounding).
        Never rounds up to prevent account margin overflows.
        """
        filt = self.get_filter(symbol)
        step = filt["step_size"]
        prec = filt["qty_precision"]
        
        if step <= 0:
            return quantity
        # Floor to step_size
        clamped = math.floor(quantity / step) * step
        if prec == 0:
            return float(int(round(clamped)))
        return round(clamped, prec)

    def format_quantity(self, symbol: str, quantity: float) -> str:
        """Returns Binance-compliant string representation of clamped quantity."""
        clamped = self.clamp_quantity(symbol, quantity)
        filt = self.get_filter(symbol)
        prec = filt["qty_precision"]
        if prec == 0:
            return str(int(round(clamped)))
        return f"{clamped:.{prec}f}"

    def clamp_price(self, symbol: str, price: float) -> float:
        """Rounds price to nearest tickSize multiple."""
        filt = self.get_filter(symbol)
        tick = filt["tick_size"]
        prec = filt["price_precision"]
        
        if tick <= 0:
            return price
        clamped = round(price / tick) * tick
        if prec == 0:
            return float(int(round(clamped)))
        return round(clamped, prec)

    def format_price(self, symbol: str, price: float) -> str:
        """Returns Binance-compliant string representation of clamped price."""
        clamped = self.clamp_price(symbol, price)
        filt = self.get_filter(symbol)
        prec = filt["price_precision"]
        if prec == 0:
            return str(int(round(clamped)))
        return f"{clamped:.{prec}f}"

    def validate_order(self, symbol: str, quantity: float, price: float) -> Tuple[bool, str, float, float]:
        """
        Normalizes quantity and price and verifies minimum notional ($5) and minimum quantity.
        Returns: (is_valid, error_msg, clamped_qty, clamped_price)
        """
        filt = self.get_filter(symbol)
        clamped_qty = self.clamp_quantity(symbol, quantity)
        clamped_price = self.clamp_price(symbol, price)

        if clamped_qty < filt["min_qty"]:
            return (
                False,
                f"Calculated quantity ({clamped_qty}) is below Binance minimum required quantity ({filt['min_qty']}) for {symbol}.",
                clamped_qty,
                clamped_price
            )

        notional = clamped_qty * clamped_price
        if notional < filt["min_notional"]:
            return (
                False,
                f"Calculated order notional (${notional:.2f}) is below Binance minimum notional threshold (${filt['min_notional']:.2f}) for {symbol}.",
                clamped_qty,
                clamped_price
            )

        return True, "", clamped_qty, clamped_price

exchange_filter_engine = ExchangeFilterManager()
