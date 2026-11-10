"""
Portfolio Risk & Execution Manager
==================================
Strictly locks:
1. 8 Target Coins: BTC, HYPE, TAO, LTC, AVAX, NEAR, SUI, SOL.
2. Factor 3 (Drawdown Throttling):
   - Normal Risk = 1.0% of current equity.
   - If account drawdown from peak equity >= 8.0%, risk is automatically halved to 0.5%.
   - Risk restores back to 1.0% once equity achieves a new all-time high.
3. Max 8.0% Capital Allocation Limit:
   - Total open risk across all active trades at any one time cannot exceed 8.0% of balance.
   - Any trade that would breach the 8.0% ceiling is rejected.
4. ISOLATED Margin Mode Locked:
   - Never cross. Strict position-level collateral isolation.
5. Daily Circuit Breaker (Kill Switch):
   - Protects account from rogue days (Max -3.5% daily loss or 3 consecutive losses).
   - Automatically halts new entries until 00:00 UTC.
6. Exchange Filter & Precision Normalizer:
   - Clamps quantity to Binance stepSize and price to tickSize; enforces $5 minNotional.
7. Real-Time Discord Alerts:
   - Webhook notifications on entry, TP/SL, throttle, and circuit breaker trip.
8. Persistent Trade Journal:
   - Auto-saves and restores state from data/trade_journal.json across reboots.
"""

import os
import json
import time
import logging
import math
from typing import Dict, List, Optional, Tuple
from exchange_filter_manager import exchange_filter_engine
from discord_notifier import discord_engine
from macro_news_filter import macro_news_engine
from funding_rate_filter import funding_rate_engine
from binance_live_executor import binance_executor
from timeframe_allocation_manager import timeframe_allocation_engine

logger = logging.getLogger("PortfolioRiskManager")

JOURNAL_DIR = os.path.join(os.path.dirname(__file__), "data")
JOURNAL_PATH = os.path.join(JOURNAL_DIR, "trade_journal.json")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "bot_config.json")

# 1. LOCKED PRODUCTION ASSETS (20 Finalized Coins from Today's Top 50)
LOCKED_PORTFOLIO_COINS = [
    "BTCUSDT",
    "SOLUSDT",
    "PAXGUSDT"
]

# 2. RISK & ALLOCATION CONFIGURATION
DEFAULT_CONFIG = {
    "initial_capital": 0.0,
    "normal_risk_pct": 0.010,           # 1.0% (STRATEGY_SPECIFICATION.md)
    "throttled_risk_pct": 0.005,        # 0.5% (Throttled mode)
    "drawdown_throttling_enabled": True,# Factor 3 on/off switch
    "drawdown_throttle_threshold": 0.08,# 8.0%
    "max_open_capital_allocation": 0.20,# 20.0% max portfolio exposure
    "max_open_positions": 3,            # Max concurrent portfolio open trades (slots)
    "max_trades_per_symbol": 1,         # Strict anti-cannibalization per symbol
    "min_reward_to_risk": 2.50,         # 2.5:1 minimum R:R floor
    "margin_type": "ISOLATED",          # STRICTLY LOCKED: NEVER CROSS
    "maintenance_margin_rate": 0.005,   # 0.5% standard Binance MMR
    "max_allowed_leverage": 25,         # Hard ceiling on leverage
    "max_daily_loss_pct": 0.035,        # -3.5% daily net loss kill switch (STRATEGY_SPECIFICATION.md)
    "max_daily_consecutive_losses": 3,  # Max 3 consecutive losses kill switch
    "max_allowed_slippage_pct": 0.002,  # 0.20% max entry slippage
    "session_filter_enabled": False,     # 24/7 continuous trading (session filter removed)
    "blocked_utc_hours": [],  # 01:00-03:00, 05:00-06:00, 18:00-21:00 UTC
    "sl_buffer_enabled": True,          # Anti-wickout Stop Loss buffering
    "sl_buffer_pct": 0.0012,            # 0.12% buffer padding behind swing pivot
    "min_sl_distance_pct": 0.0020,      # 0.20% minimum SL distance floor
    "order_execution_type": "LIMIT",    # "LIMIT" (Post-Only GTX) or "MARKET"
    "persist_journal": True             # Save state to data/trade_journal.json
}

class PortfolioRiskManager:
    def __init__(self, initial_capital: float = 0.0, config: Optional[Dict] = None):
        self.config = {**DEFAULT_CONFIG}
        # Load user-configured risk parameters from bot_config.json
        self.load_risk_config()
        if config:
            self.config.update(config)

        # Enforce ISOLATED margin mode lock
        if self.config.get("margin_type", "").upper() != "ISOLATED":
            raise ValueError("Safety Violation: Only 'ISOLATED' margin mode is allowed. 'CROSSED' is strictly prohibited.")
        
        self.balance = float(initial_capital)
        self.peak_equity = float(initial_capital)
        self.locked_symbols = list(LOCKED_PORTFOLIO_COINS)
        
        self.active_positions: Dict[str, Dict] = {}
        self.trade_history: List[Dict] = []

        # Daily Circuit Breaker state (resets daily at 00:00 UTC)
        self.current_utc_day = time.strftime("%Y-%m-%d", time.gmtime())
        self.daily_start_balance = float(initial_capital)
        self.daily_realized_pnl = 0.0
        self.daily_consecutive_losses = 0
        self.circuit_breaker_active = False

        # Master Bot Execution Switch (ON by default)
        self.bot_enabled = True

        # Restore from disk journal if enabled
        if self.config.get("persist_journal", True):
            self._load_journal()

        logger.info(
            f"Initialized PortfolioRiskManager: Capital=${self.balance:.2f}, MarginMode=ISOLATED, "
            f"BotEnabled={self.bot_enabled}, NormalRisk={self.config['normal_risk_pct']*100:.2f}%, "
            f"MaxAlloc={self.config['max_open_capital_allocation']*100:.2f}%, "
            f"DD_Throttling={self.config['drawdown_throttling_enabled']}, "
            f"SessionFilter={self.config['session_filter_enabled']}, BlockedHours={self.config['blocked_utc_hours']}, "
            f"SL_Buffer={self.config['sl_buffer_enabled']}, OrderType={self.config['order_execution_type']}"
        )

    def load_risk_config(self):
        """Loads persistent risk parameters from bot_config.json."""
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "default_risk_pct" in data:
                        # Hard ceiling of 2.0% (0.02) to prevent accidental excessive risk
                        self.config["normal_risk_pct"] = max(0.001, min(0.02, float(data["default_risk_pct"])))
                    if "throttled_risk_pct" in data:
                        self.config["throttled_risk_pct"] = max(0.001, min(0.01, float(data["throttled_risk_pct"])))
                    if "max_daily_loss_pct" in data:
                        self.config["max_daily_loss_pct"] = max(0.01, min(0.05, float(data["max_daily_loss_pct"])))
                    if "max_daily_consecutive_losses" in data:
                        self.config["max_daily_consecutive_losses"] = max(1, min(5, int(data["max_daily_consecutive_losses"])))
                    if "max_allowed_leverage" in data:
                        self.config["max_allowed_leverage"] = max(1, min(25, int(data["max_allowed_leverage"])))
                    if "max_open_allocation_pct" in data:
                        self.config["max_open_capital_allocation"] = float(data["max_open_allocation_pct"])
                    if "drawdown_throttling_enabled" in data:
                        self.config["drawdown_throttling_enabled"] = bool(data["drawdown_throttling_enabled"])
                    if "drawdown_throttle_threshold" in data:
                        self.config["drawdown_throttle_threshold"] = float(data["drawdown_throttle_threshold"])
                    if "session_filter_enabled" in data:
                        self.config["session_filter_enabled"] = bool(data["session_filter_enabled"])
                    if "blocked_utc_hours" in data:
                        self.config["blocked_utc_hours"] = list(data["blocked_utc_hours"])
                    if "sl_buffer_enabled" in data:
                        self.config["sl_buffer_enabled"] = bool(data["sl_buffer_enabled"])
                    if "sl_buffer_pct" in data:
                        self.config["sl_buffer_pct"] = float(data["sl_buffer_pct"])
                    if "min_sl_distance_pct" in data:
                        self.config["min_sl_distance_pct"] = float(data["min_sl_distance_pct"])
                    if "max_open_positions" in data:
                        self.config["max_open_positions"] = int(data["max_open_positions"])
                    if "max_trades_per_symbol" in data:
                        self.config["max_trades_per_symbol"] = int(data["max_trades_per_symbol"])
                    if "order_execution_type" in data:
                        self.config["order_execution_type"] = str(data["order_execution_type"]).upper()
                    if "locked_portfolio_coins" in data and isinstance(data["locked_portfolio_coins"], list):
                        self.locked_symbols = [s.upper() for s in data["locked_portfolio_coins"]]
                    if "timeframe_allocation" in data and isinstance(data["timeframe_allocation"], dict):
                        timeframe_allocation_engine.criteria.update(data["timeframe_allocation"])
                    logger.info(
                        f"Loaded risk config: NormalRisk={self.config['normal_risk_pct']*100:.2f}%, "
                        f"MaxAlloc={self.config['max_open_capital_allocation']*100:.2f}%, "
                        f"MaxOpenPositions={self.config['max_open_positions']}, "
                        f"MaxTradesPerSymbol={self.config['max_trades_per_symbol']}, "
                        f"DD_Throttling={self.config['drawdown_throttling_enabled']}, "
                        f"SessionFilter={self.config['session_filter_enabled']}, "
                        f"SL_Buffer={self.config['sl_buffer_enabled']}, OrderType={self.config['order_execution_type']}"
                    )
            except Exception as e:
                logger.error(f"Error loading risk config: {e}")

    def update_risk_parameters(
        self,
        normal_risk_pct: Optional[float] = None,
        throttled_risk_pct: Optional[float] = None,
        max_daily_loss_pct: Optional[float] = None,
        max_daily_consecutive_losses: Optional[int] = None,
        max_open_capital_allocation: Optional[float] = None,
        drawdown_throttling_enabled: Optional[bool] = None,
        drawdown_throttle_threshold: Optional[float] = None,
        session_filter_enabled: Optional[bool] = None,
        blocked_utc_hours: Optional[List[int]] = None,
        sl_buffer_enabled: Optional[bool] = None,
        sl_buffer_pct: Optional[float] = None,
        order_execution_type: Optional[str] = None,
        max_open_positions: Optional[int] = None,
        max_trades_per_symbol: Optional[int] = None
    ) -> Dict:
        """Updates and persists risk parameters to bot_config.json."""
        if normal_risk_pct is not None:
            # Enforce hard ceiling of 2% even from API/dashboard
            self.config["normal_risk_pct"] = max(0.001, min(0.02, float(normal_risk_pct)))
        if throttled_risk_pct is not None:
            self.config["throttled_risk_pct"] = max(0.001, min(0.01, float(throttled_risk_pct)))
        if max_daily_loss_pct is not None:
            self.config["max_daily_loss_pct"] = max(0.01, min(0.05, float(max_daily_loss_pct)))
        if max_daily_consecutive_losses is not None:
            self.config["max_daily_consecutive_losses"] = max(1, min(5, int(max_daily_consecutive_losses)))
        if max_open_capital_allocation is not None:
            self.config["max_open_capital_allocation"] = max(0.01, min(0.50, float(max_open_capital_allocation)))
        if drawdown_throttling_enabled is not None:
            self.config["drawdown_throttling_enabled"] = bool(drawdown_throttling_enabled)
        if drawdown_throttle_threshold is not None:
            self.config["drawdown_throttle_threshold"] = max(0.02, min(0.30, float(drawdown_throttle_threshold)))
        if session_filter_enabled is not None:
            self.config["session_filter_enabled"] = bool(session_filter_enabled)
        if blocked_utc_hours is not None:
            self.config["blocked_utc_hours"] = [int(h) for h in blocked_utc_hours if 0 <= int(h) <= 23]
        if sl_buffer_enabled is not None:
            self.config["sl_buffer_enabled"] = bool(sl_buffer_enabled)
        if sl_buffer_pct is not None:
            self.config["sl_buffer_pct"] = max(0.0001, min(0.02, float(sl_buffer_pct)))
        if order_execution_type is not None:
            val = str(order_execution_type).upper()
            if val in ["LIMIT", "MARKET"]:
                self.config["order_execution_type"] = val
        if max_open_positions is not None:
            self.config["max_open_positions"] = max(1, min(20, int(max_open_positions)))
        if max_trades_per_symbol is not None:
            self.config["max_trades_per_symbol"] = max(1, min(5, int(max_trades_per_symbol)))

        cfg = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        cfg["default_risk_pct"] = self.config["normal_risk_pct"]
        cfg["throttled_risk_pct"] = self.config["throttled_risk_pct"]
        cfg["max_daily_loss_pct"] = self.config["max_daily_loss_pct"]
        cfg["max_daily_consecutive_losses"] = self.config["max_daily_consecutive_losses"]
        cfg["max_allowed_leverage"] = self.config.get("max_allowed_leverage", 25)
        cfg["max_open_allocation_pct"] = self.config["max_open_capital_allocation"]
        cfg["max_open_positions"] = self.config["max_open_positions"]
        cfg["max_trades_per_symbol"] = self.config["max_trades_per_symbol"]
        cfg["drawdown_throttling_enabled"] = self.config["drawdown_throttling_enabled"]
        cfg["drawdown_throttle_threshold"] = self.config["drawdown_throttle_threshold"]
        cfg["session_filter_enabled"] = self.config["session_filter_enabled"]
        cfg["blocked_utc_hours"] = self.config["blocked_utc_hours"]
        cfg["sl_buffer_enabled"] = self.config["sl_buffer_enabled"]
        cfg["sl_buffer_pct"] = self.config["sl_buffer_pct"]
        cfg["min_sl_distance_pct"] = self.config.get("min_sl_distance_pct", 0.0020)
        cfg["order_execution_type"] = self.config["order_execution_type"]

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            logger.info("Persisted updated risk parameters to bot_config.json")
        except Exception as e:
            logger.error(f"Failed to persist risk config: {e}")

        return {
            "normal_risk_pct": self.config["normal_risk_pct"],
            "throttled_risk_pct": self.config["throttled_risk_pct"],
            "max_open_capital_allocation": self.config["max_open_capital_allocation"],
            "max_open_positions": self.config["max_open_positions"],
            "max_trades_per_symbol": self.config["max_trades_per_symbol"],
            "drawdown_throttling_enabled": self.config["drawdown_throttling_enabled"],
            "drawdown_throttle_threshold": self.config["drawdown_throttle_threshold"],
            "session_filter_enabled": self.config["session_filter_enabled"],
            "blocked_utc_hours": self.config["blocked_utc_hours"],
            "sl_buffer_enabled": self.config["sl_buffer_enabled"],
            "sl_buffer_pct": self.config["sl_buffer_pct"],
            "order_execution_type": self.config["order_execution_type"]
        }

    def toggle_bot(self, enabled: Optional[bool] = None) -> bool:
        """Toggles or sets the trading bot execution state."""
        if enabled is None:
            self.bot_enabled = not self.bot_enabled
        else:
            self.bot_enabled = bool(enabled)
        self._save_journal()
        logger.info(f"Bot master switch toggled: bot_enabled={self.bot_enabled}")
        return self.bot_enabled

    def _save_journal(self):
        """Persists current ledger to disk."""
        if not self.config.get("persist_journal", True):
            return
        try:
            os.makedirs(JOURNAL_DIR, exist_ok=True)
            data = {
                "balance": round(self.balance, 2),
                "peak_equity": round(self.peak_equity, 2),
                "daily_start_balance": round(self.daily_start_balance, 2),
                "daily_realized_pnl": round(self.daily_realized_pnl, 2),
                "daily_consecutive_losses": self.daily_consecutive_losses,
                "circuit_breaker_active": self.circuit_breaker_active,
                "bot_enabled": self.bot_enabled,
                "current_utc_day": self.current_utc_day,
                "active_positions": self.active_positions,
                "trade_history": self.trade_history[-200:],  # keep last 200 trades
                "last_updated": int(time.time())
            }
            with open(JOURNAL_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist trade journal: {e}")

    def _load_journal(self):
        """Loads persistent journal state from disk on startup."""
        if not os.path.exists(JOURNAL_PATH):
            return
        try:
            with open(JOURNAL_PATH, "r") as f:
                data = json.load(f)
                self.balance = float(data.get("balance", self.balance))
                self.peak_equity = float(data.get("peak_equity", self.peak_equity))
                self.active_positions = data.get("active_positions", {})
                self.trade_history = data.get("trade_history", [])
                
                # Check if same UTC day
                today = time.strftime("%Y-%m-%d", time.gmtime())
                self.bot_enabled = bool(data.get("bot_enabled", True))
                if data.get("current_utc_day") == today:
                    self.current_utc_day = today
                    self.daily_start_balance = float(data.get("daily_start_balance", self.balance))
                    self.daily_realized_pnl = float(data.get("daily_realized_pnl", 0.0))
                    self.daily_consecutive_losses = int(data.get("daily_consecutive_losses", 0))
                    self.circuit_breaker_active = bool(data.get("circuit_breaker_active", False))
                else:
                    self.current_utc_day = today
                    self.daily_start_balance = self.balance
                    self.daily_realized_pnl = 0.0
                    self.daily_consecutive_losses = 0
                    self.circuit_breaker_active = False

                logger.info(f"Restored journal state: Balance=${self.balance:.2f}, BotEnabled={self.bot_enabled}, ActivePositions={len(self.active_positions)}")
        except Exception as e:
            logger.error(f"Error loading trade journal: {e}")

    def sync_with_exchange_balance(self, exchange_balance: float):
        """Updates account balance with the real live Binance Futures wallet balance."""
        if exchange_balance >= 0.0:
            self.balance = float(exchange_balance)
            if self.peak_equity <= 0.0 or self.balance > self.peak_equity:
                self.peak_equity = self.balance
            if self.daily_start_balance <= 0.0:
                self.daily_start_balance = self.balance
            logger.info(f"Synchronized with live Binance Futures balance: ${self.balance:,.2f} USDT (Peak: ${self.peak_equity:,.2f})")
            if self.config.get("persist_journal", True):
                self._save_journal()

    def reset_account_state(self, new_balance: float = 0.0):
        """Resets balance, peak equity, active positions, and trade history to 0 / clean slate."""
        self.balance = float(new_balance)
        self.peak_equity = float(new_balance)
        self.daily_start_balance = float(new_balance)
        self.daily_realized_pnl = 0.0
        self.daily_losses_count = 0
        self.daily_consecutive_losses = 0
        self.circuit_breaker_active = False
        self.active_positions.clear()
        self.trade_history.clear()
        logger.info(f"Portfolio reset to clean slate. Balance=${self.balance:.2f}, History cleared.")
        if self.config.get("persist_journal", True):
            self._save_journal()

    def reload_journal(self) -> Dict:
        """Forces a reload of journal state from disk."""
        self._load_journal()
        return self.get_status()

    def import_sui_m5_trades(self, file_path: str = "m5_m1_1yr_raw_trades.json") -> Dict:
        """
        Compiles and imports verified SUI M5 trades into the trade ledger.
        Updates balance, peak equity, R-multiples, and persists to data/trade_journal.json.
        """
        resolved_path = file_path
        if not os.path.exists(resolved_path):
            base_dir = os.path.dirname(__file__)
            candidate = os.path.join(base_dir, file_path)
            if os.path.exists(candidate):
                resolved_path = candidate
            else:
                return {"success": False, "error": f"Trades file not found: {file_path}"}
        
        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                raw_trades = json.load(f)
            
            sui_trades = [t for t in raw_trades if t.get("symbol") == "SUIUSDT"]
            sui_trades.sort(key=lambda x: x["time"])
            
            initial_cap = self.config.get("initial_capital", 1000.0)
            cur_bal = initial_cap
            peak_eq = initial_cap
            journal_list = []
            
            for i, t in enumerate(sui_trades):
                sym = "SUIUSDT"
                side = t["type"]
                is_long = (side == "BUY")
                entry = float(t["entry_price"])
                sl = float(t["sl_price"])
                tp = float(t["tp_price"])
                rr = float(t["planned_rr"])
                outcome = "TP" if t.get("std_outcome") == "WIN" else "SL"
                r_gained = float(t.get("std_r_gained", 0.0))
                exit_p = tp if outcome == "TP" else sl
                
                # Factor 3 Drawdown Throttling
                dd_fraction = (peak_eq - cur_bal) / peak_eq if peak_eq > 0 else 0.0
                risk_pct = self.config["throttled_risk_pct"] if (self.config.get("drawdown_throttling_enabled", True) and dd_fraction >= self.config["drawdown_throttle_threshold"]) else self.config["normal_risk_pct"]
                risk_dollars = cur_bal * risk_pct
                price_risk = abs(entry - sl)
                raw_size = risk_dollars / price_risk if price_risk > 0 else 0.0
                
                valid, _, qty, clamped_entry = exchange_filter_engine.validate_order(sym, raw_size, entry)
                clamped_sl = exchange_filter_engine.clamp_price(sym, sl)
                clamped_tp = exchange_filter_engine.clamp_price(sym, tp)
                clamped_exit = exchange_filter_engine.clamp_price(sym, exit_p)
                
                lev, liq = self.compute_safe_isolated_leverage(clamped_entry, clamped_sl, is_long)
                notional = qty * clamped_entry
                margin_req = notional / lev if lev > 0 else 0.0
                
                pnl_dollars = risk_dollars * r_gained
                cur_bal += pnl_dollars
                if cur_bal > peak_eq:
                    peak_eq = cur_bal
                
                pos = {
                    "trade_id": f"SUI-M5-{i+1:03d}",
                    "symbol": sym,
                    "type": side,
                    "timeframe": "5m-1m",
                    "margin_type": "ISOLATED",
                    "entry_price": clamped_entry,
                    "exit_price": clamped_exit,
                    "sl_price": clamped_sl,
                    "tp_price": clamped_tp,
                    "planned_rr": rr,
                    "risk_pct": risk_pct,
                    "risk_dollars": round(risk_dollars, 2),
                    "position_size": qty,
                    "notional_value": round(notional, 2),
                    "sl_distance_pct": round((price_risk / clamped_entry) * 100.0, 2) if clamped_entry > 0 else 0.0,
                    "recommended_leverage": lev,
                    "margin_required": round(margin_req, 2),
                    "margin_pct_of_balance": round((margin_req / cur_bal) * 100.0, 2) if cur_bal > 0 else 0.0,
                    "est_liquidation_price": round(liq, 4),
                    "outcome": outcome,
                    "r_gained": round(r_gained, 2),
                    "pnl_dollars": round(pnl_dollars, 2),
                    "balance_after": round(cur_bal, 2),
                    "peak_equity_after": round(peak_eq, 2),
                    "pattern": t.get("pattern", "Reversal"),
                    "box_text": t.get("box_text", "QML"),
                    "open_time": t["time"],
                    "close_time": t["exit_time"],
                    "status": "CLOSED"
                }
                journal_list.append(pos)
            
            self.balance = cur_bal
            self.peak_equity = peak_eq
            self.daily_start_balance = cur_bal
            self.trade_history = journal_list
            self._save_journal()
            
            logger.info(f"Imported {len(journal_list)} SUI M5 trades into journal. Balance=${self.balance:.2f}, Peak=${self.peak_equity:.2f}")
            return {
                "success": True,
                "count": len(journal_list),
                "balance": round(self.balance, 2),
                "peak_equity": round(self.peak_equity, 2),
                "net_r": round(sum(p["r_gained"] for p in journal_list), 2),
                "win_rate": round(len([p for p in journal_list if p["outcome"] == "TP"]) / len(journal_list) * 100.0, 2)
            }
        except Exception as e:
            logger.error(f"Failed to import SUI M5 trades: {e}")
            return {"success": False, "error": str(e)}

    def check_and_reset_daily_stats(self):
        """Rolls over daily stats at 00:00 UTC."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self.current_utc_day:
            logger.info(f"UTC Day rollover from {self.current_utc_day} to {today}. Resetting daily circuit breaker stats.")
            self.current_utc_day = today
            self.daily_start_balance = self.balance
            self.daily_realized_pnl = 0.0
            self.daily_consecutive_losses = 0
            self.circuit_breaker_active = False
            self._save_journal()

    def reset_circuit_breaker(self):
        """Manual administrative reset of circuit breaker."""
        self.circuit_breaker_active = False
        self.daily_consecutive_losses = 0
        self._save_journal()
        logger.info("Admin reset circuit breaker.")

    def is_symbol_allowed(self, symbol: str) -> bool:
        return symbol.upper() in self.locked_symbols

    def is_session_toxic(self, timestamp: Optional[object] = None) -> Tuple[bool, str, int]:
        """
        Checks if the given or current UTC time falls in the low-volume/toxic hours window.
        Blocked windows:
        - Asian Session Drag: 01:00-03:00 UTC (hours 1, 2) & 05:00-06:00 UTC (hour 5)
        - Toxic Drift Window: 18:00-21:00 UTC (hours 18, 19, 20 - Late US Cash Close)
        """
        if not self.config.get("session_filter_enabled", False):
            return False, "", -1
        blocked = set(self.config.get("blocked_utc_hours", []))
        if not blocked:
            return False, "", -1

        from datetime import datetime, timezone
        if timestamp is not None:
            if isinstance(timestamp, (int, float)):
                t_sec = timestamp / 1000.0 if timestamp > 1e11 else float(timestamp)
                dt = datetime.fromtimestamp(t_sec, tz=timezone.utc)
            elif isinstance(timestamp, datetime):
                dt = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
            else:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        curr_hour = dt.hour
        blocked = set(self.config.get("blocked_utc_hours", [1, 2, 5, 18, 19, 20]))
        if curr_hour in blocked:
            if curr_hour in (18, 19, 20):
                sess_desc = "Late US Cash Close / Toxic Drift window (18:00-21:00 UTC)"
            elif curr_hour in (1, 2):
                sess_desc = "Asian Session Drag window (01:00-03:00 UTC)"
            else:
                sess_desc = "Asian Low-Volume Drag window (05:00-06:00 UTC)"

            reason = (
                f"Session Time Filter ACTIVE: Trading is halted during {sess_desc} at {curr_hour:02d}:00 UTC. "
                f"Trading automatically resumes during high-liquidity volume hours."
            )
            return True, reason, curr_hour

        return False, "", curr_hour

    def get_current_drawdown(self) -> Tuple[float, float]:
        dd_dollars = max(0.0, self.peak_equity - self.balance)
        dd_fraction = (dd_dollars / self.peak_equity) if self.peak_equity > 0 else 0.0
        return dd_dollars, dd_fraction

    def get_active_risk_percentage(self) -> float:
        if self.config.get("drawdown_throttling_enabled", True):
            _, dd_fraction = self.get_current_drawdown()
            if dd_fraction >= self.config["drawdown_throttle_threshold"]:
                return self.config["throttled_risk_pct"]
        return self.config["normal_risk_pct"]

    def is_throttled(self) -> bool:
        if not self.config.get("drawdown_throttling_enabled", True):
            return False
        _, dd_fraction = self.get_current_drawdown()
        return dd_fraction >= self.config["drawdown_throttle_threshold"]

    def get_current_open_risk(self) -> Tuple[float, float]:
        total_open_dollars = sum(pos["risk_dollars"] for pos in self.active_positions.values())
        total_open_fraction = (total_open_dollars / self.balance) if self.balance > 0 else 0.0
        return total_open_dollars, total_open_fraction

    def compute_safe_isolated_leverage(
        self,
        entry_price: float,
        sl_price: float,
        is_long: bool,
        target_leverage: Optional[int] = None
    ) -> Tuple[int, float]:
        """
        Dynamically calculates safe leverage for an ISOLATED position.
        Guarantees that isolated liquidation price is located safely beyond Stop Loss.
        Formula:
          For LONG: liq = entry * (1 - 1/L + MMR). We require liq <= sl_price * 0.99
          For SHORT: liq = entry * (1 + 1/L - MMR). We require liq >= sl_price * 1.01
        """
        price_risk = abs(entry_price - sl_price)
        sl_pct = price_risk / entry_price
        mmr = self.config.get("maintenance_margin_rate", 0.005)
        max_cap = self.config.get("max_allowed_leverage", 25)

        # Calculate exact mathematical upper bound on leverage so liquidation stays beyond SL:
        if is_long:
            denom = 1.0 + mmr - (sl_price / entry_price) * 0.99
        else:
            denom = (sl_price / entry_price) * 1.01 - 1.0 + mmr

        if denom > 0:
            max_safe_lev = math.floor(1.0 / denom)
        else:
            max_safe_lev = max_cap

        max_safe_lev = max(1, min(max_cap, max_safe_lev))

        # Base tier heuristic based on SL percentage distance
        if sl_pct <= 0.008:
            base_lev = 20
        elif sl_pct <= 0.015:
            base_lev = 15
        elif sl_pct <= 0.030:
            base_lev = 10
        elif sl_pct <= 0.050:
            base_lev = 5
        else:
            base_lev = 3

        base_lev = min(base_lev, max_safe_lev)

        # If higher target leverage requested (for small accounts to meet min size / margin)
        selected_lev = max(base_lev, target_leverage or 1)
        selected_lev = min(selected_lev, max_safe_lev)
        selected_lev = max(1, selected_lev)

        # Final verification: walk down leverage if liquidation is ever within SL
        while selected_lev > 1:
            if is_long:
                liq = entry_price * (1.0 - (1.0 / selected_lev) + mmr)
                if liq < sl_price * 0.99:
                    break
            else:
                liq = entry_price * (1.0 + (1.0 / selected_lev) - mmr)
                if liq > sl_price * 1.01:
                    break
            selected_lev -= 1

        selected_lev = max(1, selected_lev)
        if is_long:
            final_liq = entry_price * (1.0 - (1.0 / selected_lev) + mmr)
        else:
            final_liq = entry_price * (1.0 + (1.0 / selected_lev) - mmr)

        return selected_lev, final_liq

    def evaluate_new_trade(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        planned_rr: float,
        trade_type: str = "BUY",
        timestamp: Optional[object] = None,
        timeframe: Optional[str] = None,
        funding_rate_override: Optional[float] = None,
        session_filter_override: Optional[bool] = None,
        sl_buffer_override: Optional[bool] = None
    ) -> Dict:
        self.check_and_reset_daily_stats()
        sym_clean = symbol.upper()
        trade_dir = trade_type.upper()
        is_long = (trade_dir == "BUY")

        # -1. Master Bot Switch Check
        if not self.bot_enabled:
            return {
                "allowed": False,
                "reason": "Trading bot is currently PAUSED by admin."
            }

        # -0.5. Timeframe Allocation & Elimination Filter (5 Quant Criteria)
        if timeframe:
            tf_allowed, tf_reason = timeframe_allocation_engine.is_timeframe_allowed(sym_clean, timeframe)
            if not tf_allowed:
                return {
                    "allowed": False,
                    "reason": f"Timeframe Allocation Filter ACTIVE: {tf_reason}"
                }

        # 0. Circuit Breaker Check
        if self.circuit_breaker_active:
            return {
                "allowed": False,
                "reason": (
                    f"Daily Circuit Breaker ACTIVE: Daily loss limit reached "
                    f"({self.daily_realized_pnl:.2f} USD). Trading halted until 00:00 UTC."
                )
            }

        # 0.5. Macro Economic News Event Check (CPI / FOMC / NFP)
        is_news, ev_name, diff_h = macro_news_engine.is_macro_event_active(timestamp)
        if is_news:
            return {
                "allowed": False,
                "reason": f"Macro News Filter ACTIVE: Trading is paused during {ev_name} window ({diff_h:.1f}h from release)."
            }

        # 0.6. Funding Rate & Basis Arbitrage Filter (+0.08% / -0.08% threshold)
        is_funding_blocked, curr_funding, funding_reason = funding_rate_engine.is_funding_extreme(
            sym_clean, trade_dir, override_rate=funding_rate_override
        )
        if is_funding_blocked:
            return {
                "allowed": False,
                "reason": funding_reason
            }

        # 0.7. Toxic Hours & Low-Volume Session Filter (18-21 UTC, 01-03 UTC, 05 UTC)
        is_toxic, toxic_reason, _ = self.is_session_toxic(timestamp)
        if is_toxic and not session_filter_override:
            return {
                "allowed": False,
                "reason": toxic_reason
            }
        
        # 1. Locked Coin Check
        if not self.is_symbol_allowed(sym_clean):
            return {
                "allowed": False,
                "reason": f"Symbol '{sym_clean}' is not in the locked portfolio coins ({len(self.locked_symbols)} allowed)."
            }

        # 1.1 Max Trades Per Symbol Guard (Anti-Cannibalization)
        max_per_symbol = self.config.get("max_trades_per_symbol", 1)
        active_for_symbol = sum(1 for p in self.active_positions.values() if p.get("symbol") == sym_clean)
        if active_for_symbol >= max_per_symbol:
            return {
                "allowed": False,
                "reason": f"Anti-cannibalization breach: An active position already exists for '{sym_clean}' ({active_for_symbol}/{max_per_symbol} max allowed)."
            }

        # 1.2 Max Open Positions Guard (Portfolio Capacity / Slot Allocation)
        max_open = self.config.get("max_open_positions", 3)
        if len(self.active_positions) >= max_open:
            return {
                "allowed": False,
                "reason": f"Portfolio capacity limit reached: {len(self.active_positions)}/{max_open} max concurrent open positions occupied. Waiting for an active trade to hit TP/SL."
            }

        # 2. Minimum R:R Floor Check
        if planned_rr < self.config["min_reward_to_risk"]:
            return {
                "allowed": False,
                "reason": f"Planned R:R ({planned_rr:.2f}) is below the required 2.50:1 minimum threshold."
            }

        raw_price_risk = abs(entry_price - sl_price)
        if raw_price_risk <= 0:
            return {
                "allowed": False,
                "reason": "Invalid SL price: entry price equals SL price."
            }

        # Validate trade direction against SL
        if is_long and sl_price >= entry_price:
            return {
                "allowed": False,
                "reason": "Invalid BUY trade: Stop Loss must be strictly below Entry Price."
            }
        if not is_long and sl_price <= entry_price:
            return {
                "allowed": False,
                "reason": "Invalid SELL trade: Stop Loss must be strictly above Entry Price."
            }

        # Anti-Wickout Stop-Loss ATR Buffering
        use_sl_buffer = self.config.get("sl_buffer_enabled", True) if sl_buffer_override is None else sl_buffer_override
        effective_sl = sl_price
        effective_tp = tp_price

        if use_sl_buffer:
            buffer_pct = self.config.get("sl_buffer_pct", 0.0012)
            min_sl_dist = self.config.get("min_sl_distance_pct", 0.0020)
            buffered_dist = raw_price_risk + (entry_price * buffer_pct)
            effective_dist = max(buffered_dist, entry_price * min_sl_dist)

            if is_long:
                effective_sl = entry_price - effective_dist
                effective_tp = entry_price + (planned_rr * effective_dist)
            else:
                effective_sl = entry_price + effective_dist
                effective_tp = entry_price - (planned_rr * effective_dist)

        price_risk = abs(entry_price - effective_sl)

        # 3. Factor 3: Drawdown Throttling
        trade_risk_pct = self.get_active_risk_percentage()
        trade_risk_dollars = self.balance * trade_risk_pct

        # 4. Max 8% Capital Allocation Check
        current_open_dollars, current_open_pct = self.get_current_open_risk()
        projected_open_pct = current_open_pct + trade_risk_pct

        max_alloc_limit = self.config.get("max_open_capital_allocation", 0.20)
        if projected_open_pct > max_alloc_limit:
            return {
                "allowed": False,
                "reason": (
                    f"Capital allocation breach: Current open risk ({current_open_pct*100:.2f}%) + "
                    f"New trade risk ({trade_risk_pct*100:.2f}%) = {projected_open_pct*100:.2f}%, "
                    f"which exceeds the maximum {max_alloc_limit*100:.1f}% limit."
                )
            }

        # 5. Position Sizing
        raw_position_size = trade_risk_dollars / price_risk
        
        # 6. Binance Exchange Precision & Min Notional Validation
        filt = exchange_filter_engine.get_filter(sym_clean)
        min_qty = filt.get("min_qty", 0.001)
        min_notional = filt.get("min_notional", 5.0)
        step_size = filt.get("step_size", 0.001)
        qty_prec = filt.get("qty_precision", 3)

        clamped_entry = exchange_filter_engine.clamp_price(sym_clean, entry_price)
        clamped_sl = exchange_filter_engine.clamp_price(sym_clean, effective_sl)
        clamped_tp = exchange_filter_engine.clamp_price(sym_clean, effective_tp)

        # Minimum required quantity to meet Binance LOT_SIZE and MIN_NOTIONAL ($5)
        min_notional_qty = math.ceil(min_notional / clamped_entry / step_size) * step_size
        min_viable_qty = round(max(min_qty, min_notional_qty), qty_prec)

        target_lev = 1
        # Risk Budget Preservation (Rule RISK-006):
        # Never increase actual risk beyond permitted risk budget just to satisfy exchange minimums!
        if raw_position_size < min_viable_qty:
            effective_risk_dollars = min_viable_qty * price_risk
            # Allow at most 5% tolerance for lot rounding (e.g. $10.00 vs $10.50)
            if effective_risk_dollars > (trade_risk_dollars * 1.05):
                logger.warning(
                    f"Order rejected [{sym_clean}]: Sized quantity {raw_position_size:.4f} is below exchange "
                    f"minimum {min_viable_qty}. Forcing minimum would risk ${effective_risk_dollars:.2f}, "
                    f"exceeding permitted risk budget of ${trade_risk_dollars:.2f}."
                )
                return {
                    "allowed": False,
                    "reason": f"Required size ({raw_position_size:.4f}) is below exchange minimum ({min_viable_qty}). Rejected to prevent risk budget inflation.",
                    "code": "BELOW_MIN_LOT_RISK_BUDGET"
                }
            clamped_qty = min_viable_qty
            notional_value = clamped_qty * clamped_entry
        else:
            clamped_qty = exchange_filter_engine.clamp_quantity(sym_clean, raw_position_size)
            notional_value = clamped_qty * clamped_entry

        sl_distance_pct = (price_risk / clamped_entry) * 100.0

        # 7. Dynamic Safe Leverage & Isolated Liquidation Price Calculation
        # Guarantees that liquidation price is strictly located beyond Stop Loss
        recommended_leverage, est_liq_price = self.compute_safe_isolated_leverage(
            entry_price=clamped_entry,
            sl_price=clamped_sl,
            is_long=is_long,
            target_leverage=target_lev
        )

        # 8. Isolated Margin Required
        margin_required = notional_value / recommended_leverage
        margin_pct_of_balance = (margin_required / self.balance * 100.0) if self.balance > 0 else 0.0

        # Check that margin required is within account balance
        if self.balance > 0 and margin_required > self.balance:
            return {
                "allowed": False,
                "reason": (
                    f"Insufficient balance: Order requires ${margin_required:.2f} margin "
                    f"at {recommended_leverage}x leverage, but account balance is ${self.balance:.2f}."
                )
            }

        # 9. Full Binance Futures API Execution Payload (Isolated Mode Locked, Post-Only Limit Default)
        order_type = self.config.get("order_execution_type", "LIMIT").upper()
        binance_order_payload = {
            "symbol": sym_clean,
            "marginType": "ISOLATED",
            "leverage": recommended_leverage,
            "side": "BUY" if is_long else "SELL",
            "positionSide": "BOTH",
            "type": order_type,
            "timeInForce": "GTX" if order_type == "LIMIT" else None,
            "price": clamped_entry if order_type == "LIMIT" else None,
            "quantity": clamped_qty,
            "isolatedMargin": round(margin_required, 2),
            "entryPrice": clamped_entry,
            "stopLoss": {
                "type": "STOP_MARKET",
                "stopPrice": clamped_sl,
                "closePosition": True
            },
            "takeProfit": {
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": clamped_tp,
                "closePosition": True
            },
            "estLiquidationPrice": round(est_liq_price, 4)
        }

        return {
            "allowed": True,
            "symbol": sym_clean,
            "trade_type": trade_dir,
            "margin_type": "ISOLATED",
            "risk_pct": trade_risk_pct,
            "risk_dollars": round(trade_risk_dollars, 2),
            "position_size": clamped_qty,
            "notional_value": round(notional_value, 2),
            "sl_distance_pct": round(sl_distance_pct, 2),
            "recommended_leverage": recommended_leverage,
            "margin_required": round(margin_required, 2),
            "margin_pct_of_balance": round(margin_pct_of_balance, 2),
            "est_liquidation_price": round(est_liq_price, 4),
            "throttled": self.is_throttled(),
            "current_drawdown_pct": round(self.get_current_drawdown()[1] * 100.0, 2),
            "projected_open_risk_pct": round(projected_open_pct * 100.0, 2),
            "sl_buffered": use_sl_buffer,
            "effective_sl": clamped_sl,
            "effective_tp": clamped_tp,
            "order_execution_type": order_type,
            "binance_order_payload": binance_order_payload
        }

    def open_position(
        self,
        trade_id: str,
        symbol: str,
        trade_type: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        planned_rr: float,
        actual_execution_price: Optional[float] = None,
        timestamp: Optional[int] = None,
        timeframe: Optional[str] = None,
        sl_buffer_override: Optional[bool] = None
    ) -> Dict:
        self.check_and_reset_daily_stats()
        eval_result = self.evaluate_new_trade(
            symbol=symbol,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            planned_rr=planned_rr,
            trade_type=trade_type,
            timestamp=timestamp,
            timeframe=timeframe,
            sl_buffer_override=sl_buffer_override
        )
        if not eval_result["allowed"]:
            logger.warning(f"Trade rejected [{trade_id}]: {eval_result['reason']}")
            return eval_result

        # Slippage Guard Check
        exec_price = actual_execution_price or entry_price
        slippage_pct = abs(exec_price - entry_price) / entry_price
        if slippage_pct > self.config["max_allowed_slippage_pct"]:
            logger.warning(
                f"Slippage guard triggered for [{trade_id}]: planned={entry_price}, "
                f"actual={exec_price}, slippage={slippage_pct*100:.2f}% (max={self.config['max_allowed_slippage_pct']*100:.2f}%)"
            )

        # Dispatch to Binance Live / Paper Executor
        exec_res = binance_executor.execute_bracket_order(eval_result["binance_order_payload"])
        if not exec_res.get("success", False):
            logger.error(f"Binance order rejected [{trade_id}]: {exec_res.get('error')}")
            return {
                "allowed": False,
                "reason": f"Binance Order Execution Failed: {exec_res.get('error')}"
            }

        pos = {
            "trade_id": trade_id,
            "symbol": symbol.upper(),
            "type": trade_type.upper(),
            "margin_type": "ISOLATED",
            "entry_price": exec_price,
            "sl_price": eval_result["binance_order_payload"]["stopLoss"]["stopPrice"],
            "tp_price": eval_result["binance_order_payload"]["takeProfit"]["stopPrice"],
            "planned_rr": planned_rr,
            "risk_pct": eval_result["risk_pct"],
            "risk_dollars": eval_result["risk_dollars"],
            "position_size": eval_result["position_size"],
            "notional_value": eval_result["notional_value"],
            "sl_distance_pct": eval_result["sl_distance_pct"],
            "recommended_leverage": eval_result["recommended_leverage"],
            "margin_required": eval_result["margin_required"],
            "margin_pct_of_balance": eval_result["margin_pct_of_balance"],
            "est_liquidation_price": eval_result["est_liquidation_price"],
            "binance_order_payload": eval_result["binance_order_payload"],
            "binance_order_id": exec_res.get("order_id"),
            "sl_order_id": exec_res.get("sl_order_id"),
            "tp_order_id": exec_res.get("tp_order_id"),
            "execution_mode": exec_res.get("mode", "PAPER"),
            "order_state": "FILLED" if (exec_res.get("order_status") == "FILLED" or exec_res.get("mode") == "PAPER") else "PENDING_ENTRY",
            "order_type": exec_res.get("order_type", self.config.get("order_execution_type", "LIMIT")),
            "throttled_entry": eval_result["throttled"],
            "open_time": timestamp or int(time.time()),
            "status": "OPEN"
        }

        self.active_positions[trade_id] = pos
        self._save_journal()

        # Send real-time Discord notification
        discord_engine.notify_trade_opened(pos)

        logger.info(
            f"OPENED ISOLATED POSITION [{trade_id} {symbol} {trade_type}]: Lev={eval_result['recommended_leverage']}x, "
            f"Risk=${eval_result['risk_dollars']} ({eval_result['risk_pct']*100:.1f}%), "
            f"LiqEst=${eval_result['est_liquidation_price']}, Open={len(self.active_positions)}"
        )
        return {"allowed": True, "position": pos}

    def cancel_pending_position(self, trade_id: str, reason: str = "Unfilled limit order canceled") -> Dict:
        """Removes a pending entry order that was canceled/expired on Binance without executing."""
        if trade_id not in self.active_positions:
            return {"success": False, "error": f"Trade ID '{trade_id}' not found."}
        pos = self.active_positions.pop(trade_id)
        symbol = pos.get("symbol")
        binance_executor.cancel_all_open_orders(symbol)
        self._save_journal()
        logger.info(f"Discarded unfilled pending order [{trade_id} {symbol}]: {reason}. No trade recorded.")
        return {"success": True, "discarded_position": pos}

    def close_position(
        self,
        trade_id: str,
        outcome: str,
        r_gained: float,
        exit_price: float,
        timestamp: Optional[int] = None,
        pnl_override: Optional[float] = None
    ) -> Dict:
        self.check_and_reset_daily_stats()
        if trade_id not in self.active_positions:
            return {"success": False, "error": f"Trade ID '{trade_id}' not found in active positions."}

        pos = self.active_positions[trade_id]
        # Safeguard: If the position is still PENDING_ENTRY with zero fill, do NOT record as closed loss!
        if pos.get("order_state") == "PENDING_ENTRY" and (pnl_override is None or pnl_override == 0.0):
            return self.cancel_pending_position(trade_id, reason="Zero execution fill on exchange")

        was_throttled = self.is_throttled()
        pos = self.active_positions.pop(trade_id)
        risk_dollars = pos["risk_dollars"]
        pnl_dollars = pnl_override if pnl_override is not None else (r_gained * risk_dollars)

        # In LIVE mode, balance is determined directly by Binance exchange balance
        # In PAPER mode, simulate balance increment
        real_bal = None
        if binance_executor.api_key and binance_executor.api_secret and binance_executor.mode == "LIVE":
            try:
                real_bal = binance_executor.get_real_futures_balance()
            except Exception as e:
                logger.warning(f"Could not query live balance on close: {e}")

        if real_bal is not None:
            self.balance = real_bal
        else:
            self.balance += pnl_dollars

        if self.balance > self.peak_equity:
            self.peak_equity = self.balance

        # Update daily statistics
        self.daily_realized_pnl += pnl_dollars
        if r_gained < 0:
            self.daily_consecutive_losses += 1
        else:
            self.daily_consecutive_losses = 0

        # Check Daily Circuit Breaker Condition (Hard Daily Equity Loss Kill Switch)
        daily_loss_pct = (self.daily_realized_pnl / self.daily_start_balance) if self.daily_start_balance > 0 else 0.0
        consec_limit = self.config.get("max_daily_consecutive_losses", 3)
        trip_consec = (self.daily_consecutive_losses >= consec_limit)
        if daily_loss_pct <= -self.config["max_daily_loss_pct"] or trip_consec:
            if not self.circuit_breaker_active:
                self.circuit_breaker_active = True
                logger.warning(
                    f"DAILY CIRCUIT BREAKER TRIPPED! Daily Loss={daily_loss_pct*100:.2f}%, "
                    f"Consecutive Losses={self.daily_consecutive_losses}. Halting trading."
                )
                discord_engine.notify_circuit_breaker_tripped(daily_loss_pct * 100.0, self.daily_consecutive_losses)

        # Check Factor 3 Drawdown Throttling Transition
        now_throttled = self.is_throttled()
        if not was_throttled and now_throttled:
            _, dd_fraction = self.get_current_drawdown()
            logger.warning(f"FACTOR 3 DRAWDOWN THROTTLING TRIGGERED (-{dd_fraction*100:.2f}%). Risk halved to 0.5%.")
            discord_engine.notify_drawdown_throttled(self.peak_equity, self.balance, dd_fraction * 100.0)

        pos["status"] = "CLOSED"
        pos["close_time"] = timestamp or int(time.time())
        pos["exit_price"] = exit_price
        pos["outcome"] = outcome.upper()
        pos["r_gained"] = r_gained
        pos["pnl_dollars"] = round(pnl_dollars, 2)
        pos["balance_after"] = round(self.balance, 2)
        pos["peak_equity_after"] = round(self.peak_equity, 2)

        self.trade_history.append(pos)
        self._save_journal()

        # Immediately cancel any remaining open orders (SL/TP) for this symbol on Binance
        try:
            binance_executor.cancel_all_open_orders(pos["symbol"])
        except Exception as ce:
            logger.warning(f"Failed to cancel open orders on close for {pos['symbol']}: {ce}")

        # Send real-time Discord notification
        discord_engine.notify_trade_closed(pos)

        logger.info(
            f"CLOSED POSITION [{trade_id} {pos['symbol']}]: PnL=${pnl_dollars:+.2f} ({r_gained:+.2f}R), "
            f"New Balance=${self.balance:.2f}, Peak=${self.peak_equity:.2f}"
        )
        return {"success": True, "closed_position": pos, "new_balance": round(self.balance, 2)}

    def get_status(self) -> Dict:
        self.check_and_reset_daily_stats()
        # Automatically sync with real Binance balance if API credentials are configured
        if binance_executor.api_key and binance_executor.api_secret:
            now = time.time()
            last_sync = getattr(self, "_last_binance_sync", 0.0)
            if now - last_sync > 10.0:
                self._last_binance_sync = now
                real_bal = binance_executor.get_real_futures_balance()
                if real_bal is not None:
                    self.sync_with_exchange_balance(real_bal)

        dd_dollars, dd_fraction = self.get_current_drawdown()
        open_risk_dollars, open_risk_pct = self.get_current_open_risk()
        daily_loss_pct = (self.daily_realized_pnl / self.daily_start_balance * 100.0) if self.daily_start_balance > 0 else 0.0

        is_news, ev_name, diff_h = macro_news_engine.is_macro_event_active()
        next_event = macro_news_engine.get_next_macro_event()
        is_toxic, toxic_reason, cur_hour = self.is_session_toxic()

        return {
            "balance": round(self.balance, 2),
            "peak_equity": round(self.peak_equity, 2),
            "margin_mode": "ISOLATED",
            "bot_enabled": self.bot_enabled,
            "macro_filter_active": is_news,
            "macro_event_name": ev_name,
            "next_macro_event": next_event,
            "session_filter_enabled": self.config.get("session_filter_enabled", True),
            "session_filter_active": is_toxic,
            "session_filter_reason": toxic_reason,
            "current_utc_hour": cur_hour,
            "blocked_utc_hours": self.config.get("blocked_utc_hours", [1, 2, 5, 18, 19, 20]),
            "drawdown_dollars": round(dd_dollars, 2),
            "drawdown_pct": round(dd_fraction * 100.0, 2),
            "throttled": self.is_throttled(),
            "drawdown_throttling_enabled": self.config.get("drawdown_throttling_enabled", True),
            "current_trade_risk_pct": round(self.get_active_risk_percentage() * 100.0, 2),
            "normal_risk_pct": round(self.config["normal_risk_pct"] * 100.0, 2),
            "throttled_risk_pct": round(self.config["throttled_risk_pct"] * 100.0, 2),
            "drawdown_throttle_threshold_pct": round(self.config["drawdown_throttle_threshold"] * 100.0, 2),
            "open_risk_dollars": round(open_risk_dollars, 2),
            "open_risk_pct": round(open_risk_pct * 100.0, 2),
            "max_open_risk_limit_pct": round(self.config["max_open_capital_allocation"] * 100.0, 2),
            "circuit_breaker_active": self.circuit_breaker_active,
            "daily_realized_pnl": round(self.daily_realized_pnl, 2),
            "daily_loss_pct": round(daily_loss_pct, 2),
            "daily_consecutive_losses": self.daily_consecutive_losses,
            "discord_configured": bool(discord_engine.webhook_url),
            "active_positions_count": len(self.active_positions),
            "max_open_positions": self.config.get("max_open_positions", 3),
            "max_trades_per_symbol": self.config.get("max_trades_per_symbol", 1),
            "active_positions": list(self.active_positions.values()),
            "total_trades_completed": len(self.trade_history),
            "locked_coins": self.locked_symbols,
            "funding_filter_max_threshold_pct": round(funding_rate_engine.max_positive_rate * 100.0, 2),
            "funding_filter_min_threshold_pct": round(funding_rate_engine.max_negative_rate * 100.0, 2),
            "sl_buffer_enabled": self.config.get("sl_buffer_enabled", True),
            "sl_buffer_pct": round(self.config.get("sl_buffer_pct", 0.0012) * 100.0, 2),
            "min_sl_distance_pct": round(self.config.get("min_sl_distance_pct", 0.0020) * 100.0, 2),
            "order_execution_type": self.config.get("order_execution_type", "LIMIT"),
            "execution_mode": binance_executor.mode,
            "binance_connected": bool(binance_executor.api_key and binance_executor.api_secret),
            "binance_key_masked": f"{binance_executor.api_key[:6]}...{binance_executor.api_key[-4:]}" if binance_executor.api_key else ""
        }

portfolio_risk_engine = PortfolioRiskManager()
