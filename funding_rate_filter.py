"""
Funding Rate & Basis Arbitrage Filter
====================================
Monitors Binance Futures Perpetual funding rates in real-time.
Prevents:
1. Long entries when funding rate >= +0.08% (+0.0008) per 8h (avoiding predatory carrying fees and long-squeeze flushes).
2. Short entries when funding rate <= -0.08% (-0.0008) per 8h (avoiding short carrying penalties and violent short squeezes).

Caches live rates via Binance /fapi/v1/premiumIndex with periodic background refresh.
"""

import time
import urllib.request
import json
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger("FundingRateFilter")

DEFAULT_MAX_POSITIVE_FUNDING = 0.0008   # +0.08% per 8h
DEFAULT_MAX_NEGATIVE_FUNDING = -0.0008  # -0.08% per 8h
CACHE_TTL_SECONDS = 300                 # 5 minutes cache

class FundingRateFilter:
    def __init__(
        self,
        enabled: bool = True,
        max_positive_rate: float = DEFAULT_MAX_POSITIVE_FUNDING,
        max_negative_rate: float = DEFAULT_MAX_NEGATIVE_FUNDING
    ):
        self.enabled = enabled
        self.max_positive_rate = max_positive_rate
        self.max_negative_rate = max_negative_rate
        self.cache: Dict[str, Dict] = {}
        self.last_fetch_time: float = 0.0

    def refresh_funding_rates(self, force: bool = False) -> Dict[str, float]:
        """Fetches live funding rates from Binance Futures API."""
        now = time.time()
        if not force and (now - self.last_fetch_time) < CACHE_TTL_SECONDS and self.cache:
            return {s: d["funding_rate"] for s, d in self.cache.items()}

        url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        req = urllib.request.Request(url, headers={"User-Agent": "TopG-Bot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode("utf-8"))
                for item in data:
                    sym = item.get("symbol")
                    rate_str = item.get("lastFundingRate")
                    next_time = item.get("nextFundingTime", 0)
                    if sym and rate_str is not None:
                        self.cache[sym] = {
                            "funding_rate": float(rate_str),
                            "next_funding_time": next_time,
                            "updated_at": now
                        }
                self.last_fetch_time = now
                logger.info(f"Refreshed funding rates for {len(self.cache)} symbols from Binance.")
        except Exception as e:
            logger.warning(f"Failed to refresh Binance funding rates: {e}. Using cached values.")

        return {s: d["funding_rate"] for s, d in self.cache.items()}

    def get_funding_rate(self, symbol: str) -> float:
        """Returns the latest funding rate for a symbol (default: 0.0001 = 0.01%)."""
        sym = symbol.upper()
        if not self.cache or (time.time() - self.last_fetch_time) >= CACHE_TTL_SECONDS:
            self.refresh_funding_rates()
        if sym in self.cache:
            return self.cache[sym]["funding_rate"]
        return 0.0001

    def is_funding_extreme(
        self,
        symbol: str,
        trade_type: str = "BUY",
        override_rate: Optional[float] = None
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Evaluates whether entering a trade would violate funding rate safety bounds.
        Returns: (is_blocked: bool, current_rate: float, reason: Optional[str])
        """
        if not self.enabled:
            return False, 0.0, None

        current_rate = override_rate if override_rate is not None else self.get_funding_rate(symbol)
        side = trade_type.upper()

        if side == "BUY" and current_rate >= self.max_positive_rate:
            pct = current_rate * 100.0
            thresh_pct = self.max_positive_rate * 100.0
            reason = (
                f"Funding Rate Filter ACTIVE: Long entry blocked on {symbol.upper()}. "
                f"Current funding rate ({pct:+.4f}%) exceeds maximum safe threshold ({thresh_pct:+.4f}%). "
                f"Carrying fees and long-squeeze risk too severe."
            )
            return True, current_rate, reason

        if side == "SELL" and current_rate <= self.max_negative_rate:
            pct = current_rate * 100.0
            thresh_pct = self.max_negative_rate * 100.0
            reason = (
                f"Funding Rate Filter ACTIVE: Short entry blocked on {symbol.upper()}. "
                f"Current funding rate ({pct:+.4f}%) is below minimum safe threshold ({thresh_pct:+.4f}%). "
                f"Short squeeze risk and carrying fees too severe."
            )
            return True, current_rate, reason

        return False, current_rate, None

funding_rate_engine = FundingRateFilter()
