"""
Zone Trade Registry (Persistent & Atomic)
=========================================
Guarantees strict single-trade-per-zone lifecycle protection (Rule RISK-003):
- Immutable registry lock survives application restarts.
- Thread-safe in-memory caching with atomic disk persistence.
- Handles atomic registration, execution, and rejection states.
"""

import os
import json
import logging
import threading
import tempfile
from typing import Dict, Any, Optional, Set

logger = logging.getLogger("ZoneTradeRegistry")

DEFAULT_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "zone_trades_registry.json"
)


class ZoneTradeRegistry:
    """
    Central authoritative registry managing the lifecycle of traded HTF zones.
    Enforces Rule RISK-003: Exactly 1 trade per qualifying zone reaction cycle.
    """
    def __init__(self, storage_path: str = DEFAULT_REGISTRY_PATH):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._registry: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        with self._lock:
            if os.path.exists(self.storage_path) and os.path.getsize(self.storage_path) > 0:
                try:
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._registry = data
                    elif isinstance(data, list):
                        # Backwards compatibility with list of keys
                        self._registry = {k: {"status": "EXECUTED", "time": 0} for k in data}
                    logger.info(f"Loaded {len(self._registry)} locked zones from {self.storage_path}")
                except Exception as e:
                    logger.error(f"Failed to load zone trades registry: {e}")
                    self._registry = {}
            else:
                self._registry = {}

    def _save_atomic(self):
        """Thread-safe atomic write to disk to prevent file corruption."""
        os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
        dir_name = os.path.dirname(os.path.abspath(self.storage_path))
        temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(self._registry, f, indent=2)
            os.replace(temp_path, self.storage_path)
        except Exception as e:
            logger.error(f"Failed to atomically persist zone registry: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def get_zone_key(self, symbol: str, htf_tf: str, box_id: str) -> str:
        sym = (symbol or "").upper()
        tf = (htf_tf or "").lower()
        return f"{sym}_{tf}_{box_id}"

    def is_zone_locked(self, zone_key: str) -> bool:
        """
        Returns True if the zone has already been traded or is currently pending execution.
        """
        with self._lock:
            entry = self._registry.get(zone_key)
            if not entry:
                return False
            status = entry.get("status", "").upper()
            return status in ("PENDING", "EXECUTED", "TRADED", "FILLED")

    def register_pending_trade(self, zone_key: str, trade_metadata: Dict[str, Any]) -> bool:
        """
        Atomically locks a zone as PENDING to prevent concurrent duplicate orders.
        Returns True if successfully locked, False if already locked.
        """
        with self._lock:
            entry = self._registry.get(zone_key)
            if entry and entry.get("status", "").upper() in ("PENDING", "EXECUTED", "TRADED", "FILLED"):
                logger.warning(f"Zone '{zone_key}' is already locked (status={entry.get('status')})")
                return False
            self._registry[zone_key] = {
                "status": "PENDING",
                "registered_at": trade_metadata.get("time"),
                "trade_id": trade_metadata.get("id"),
                "action": trade_metadata.get("action"),
                "entry_price": trade_metadata.get("entry_price") or trade_metadata.get("entry"),
                "sl_price": trade_metadata.get("sl_price") or trade_metadata.get("sl"),
                "tp_price": trade_metadata.get("tp_price") or trade_metadata.get("tp"),
                "pattern": trade_metadata.get("pattern_name") or trade_metadata.get("pattern"),
                "level": trade_metadata.get("level_name") or trade_metadata.get("level")
            }
            self._save_atomic()
            logger.info(f"Atomically registered pending trade on zone '{zone_key}'")
            return True

    def mark_trade_executed(self, zone_key: str, order_id: Optional[str] = None):
        """Marks the zone lock as permanently EXECUTED upon confirmed order placement."""
        with self._lock:
            if zone_key in self._registry:
                self._registry[zone_key]["status"] = "EXECUTED"
                if order_id:
                    self._registry[zone_key]["order_id"] = order_id
                self._save_atomic()
                logger.info(f"Zone '{zone_key}' marked as EXECUTED.")

    def release_rejected_zone(self, zone_key: str, reason: str = ""):
        """
        Releases the lock on a zone if order execution was rejected before fill
        (e.g., minimum lot risk breach, insufficient margin, or network failure),
        preventing the zone from being falsely locked as traded.
        """
        with self._lock:
            if zone_key in self._registry:
                entry = self._registry[zone_key]
                if entry.get("status") == "PENDING":
                    del self._registry[zone_key]
                    self._save_atomic()
                    logger.info(f"Released pending lock for zone '{zone_key}': {reason}")

    def get_all_locked_keys(self) -> Set[str]:
        with self._lock:
            return {
                k for k, v in self._registry.items()
                if v.get("status", "").upper() in ("PENDING", "EXECUTED", "TRADED", "FILLED")
            }

    def clear_for_backtest(self):
        """Clears registry in-memory for backtest isolation."""
        with self._lock:
            self._registry.clear()


# Global singleton instance
zone_trade_registry = ZoneTradeRegistry()
