"""
Discord Webhook Notification Engine
===================================
Dispatches rich, real-time alert embeds to your Discord server for:
1. Trade Opened (Entry, SL, TP, Leverage, Margin, Risk $, Liq Price)
2. Take Profit Hit (R-gained, $ PnL, New Balance)
3. Stop Loss Hit ($ Loss, New Balance)
4. Factor 3 Drawdown Throttling Alert (Risk halved to 0.5%)
5. Daily Circuit Breaker Trip (Daily loss reached, trading halted)

Executes in background threads to guarantee zero latency on trading execution.
"""

import json
import logging
import os
import threading
import time
import urllib.request
from typing import Dict, Optional, Tuple

logger = logging.getLogger("DiscordNotifier")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "bot_config.json")

class DiscordNotifier:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or self._load_webhook_url()
        self.enabled = bool(self.webhook_url)

    def _load_webhook_url(self) -> str:
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as f:
                    cfg = json.load(f)
                    return cfg.get("discord_webhook_url", "").strip()
            except Exception as e:
                logger.error(f"Error loading bot_config.json: {e}")
        return os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    def set_webhook_url(self, url: str) -> None:
        self.webhook_url = url.strip()
        self.enabled = bool(self.webhook_url)
        # Update config file
        try:
            cfg = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r") as f:
                    cfg = json.load(f)
            cfg["discord_webhook_url"] = self.webhook_url
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
            logger.info("Updated Discord webhook URL in bot_config.json")
        except Exception as e:
            logger.error(f"Failed to save webhook URL to bot_config.json: {e}")

    def _send_payload(self, payload: Dict) -> bool:
        """Sends payload to Discord via HTTP POST."""
        if not self.webhook_url:
            logger.debug("Discord webhook not configured; skipping notification.")
            return False

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "InstitutionalTradingBot/1.0"
                }
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                return (200 <= resp.status < 300)
        except Exception as e:
            logger.warning(f"Failed to dispatch Discord alert: {e}")
            return False

    def _dispatch_async(self, payload: Dict):
        """Dispatches notification in a separate daemon thread to avoid blocking execution."""
        t = threading.Thread(target=self._send_payload, args=(payload,), daemon=True)
        t.start()

    def notify_trade_opened(self, pos: Dict):
        """Sends rich green embed card when a trade is opened."""
        side = pos.get("type", "BUY").upper()
        color = 0x2ECC71 if side == "BUY" else 0xE74C3C
        side_icon = "🟢 LONG" if side == "BUY" else "🔴 SHORT"

        embed = {
            "title": f"🚀 NEW POSITION OPENED: {pos.get('symbol')} ({side_icon})",
            "description": f"Target setup triggered on 1m confirmation within HTF structure.",
            "color": color,
            "fields": [
                {"name": "💰 Entry Price", "value": f"`${pos.get('entry_price', 0):,.4f}`", "inline": True},
                {"name": "🛑 Stop Loss", "value": f"`${pos.get('sl_price', 0):,.4f}`", "inline": True},
                {"name": "🎯 Take Profit", "value": f"`${pos.get('tp_price', 0):,.4f}`", "inline": True},
                {"name": "⚡ Leverage & Mode", "value": f"`{pos.get('recommended_leverage', 10)}x ISOLATED`", "inline": True},
                {"name": "📦 Position Size", "value": f"`{pos.get('position_size', 0):.4f} units`", "inline": True},
                {"name": "🔒 Required Margin", "value": f"`${pos.get('margin_required', 0):.2f}`", "inline": True},
                {"name": "🛡️ Dollar Risk", "value": f"`${pos.get('risk_dollars', 0):.2f}` ({pos.get('risk_pct', 0.01)*100:.1f}%)", "inline": True},
                {"name": "⚠️ Est. Liquidation", "value": f"`${pos.get('est_liquidation_price', 0):,.4f}`", "inline": True},
                {"name": "📊 Planned R:R", "value": f"`{pos.get('planned_rr', 2.85):.2f}:1`", "inline": True}
            ],
            "footer": {
                "text": f"Portfolio Engine • Capital Protected • {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
            }
        }
        self._dispatch_async({"embeds": [embed]})

    def notify_trade_closed(self, pos: Dict):
        """Sends embed card when a trade is closed."""
        outcome = pos.get("outcome", "").upper()
        pnl = pos.get("pnl_dollars", 0.0)
        r_gained = pos.get("r_gained", 0.0)
        
        if outcome == "TP" or pnl > 0:
            color = 0xF1C40F  # Gold
            title = f"🎯 TAKE PROFIT HIT: {pos.get('symbol')} (+{r_gained:.2f}R)"
            desc = f"Position completed successfully! Gains locked in."
        else:
            color = 0xE74C3C  # Red
            title = f"🛑 STOP LOSS HIT: {pos.get('symbol')} ({r_gained:.2f}R)"
            desc = f"Stop Loss protected capital cleanly. Defined risk maintained."

        embed = {
            "title": title,
            "description": desc,
            "color": color,
            "fields": [
                {"name": "💵 Realized PnL", "value": f"`{pnl:+.2f} USD`", "inline": True},
                {"name": "📈 R-Multiple", "value": f"`{r_gained:+.2f}R`", "inline": True},
                {"name": "🏦 Updated Balance", "value": f"`${pos.get('balance_after', 0):,.2f}`", "inline": True},
                {"name": "🚪 Exit Price", "value": f"`${pos.get('exit_price', 0):,.4f}`", "inline": True},
                {"name": "🏔️ Peak Equity", "value": f"`${pos.get('peak_equity_after', 0):,.2f}`", "inline": True},
                {"name": "⏱️ Outcome", "value": f"`{outcome}`", "inline": True}
            ],
            "footer": {
                "text": f"Trade Closed • {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
            }
        }
        self._dispatch_async({"embeds": [embed]})

    def notify_drawdown_throttled(self, peak_equity: float, current_balance: float, dd_pct: float):
        """Sends warning embed when Factor 3 Throttling triggers (risk halved to 0.5%)."""
        embed = {
            "title": "⚠️ DRAWDOWN THROTTLING ACTIVATED (FACTOR 3)",
            "description": f"Account drawdown has reached **{dd_pct:.2f}%** from peak equity (${peak_equity:,.2f}).",
            "color": 0xE67E22,  # Orange
            "fields": [
                {"name": "Current Equity", "value": f"`${current_balance:,.2f}`", "inline": True},
                {"name": "Peak Equity", "value": f"`${peak_equity:,.2f}`", "inline": True},
                {"name": "New Trade Risk", "value": "`0.50% (HALVED)`", "inline": True},
                {"name": "Recovery Target", "value": f"`>${peak_equity:,.2f}` (Restores to 1.0%)", "inline": True}
            ],
            "footer": {
                "text": "Risk Defense Active • Preservation Mode"
            }
        }
        self._dispatch_async({"embeds": [embed]})

    def notify_circuit_breaker_tripped(self, daily_loss_pct: float, consecutive_losses: int):
        """Sends emergency embed when Daily Circuit Breaker halts trading."""
        embed = {
            "title": "🚨 DAILY CIRCUIT BREAKER TRIPPED — TRADING HALTED",
            "description": (
                f"Daily risk threshold reached (**{daily_loss_pct:.2f}%** loss or "
                f"**{consecutive_losses}** consecutive losses today). All new entries are **FROZEN** "
                f"until 00:00 UTC to protect capital."
            ),
            "color": 0x992D22,  # Dark Red
            "fields": [
                {"name": "Daily Loss", "value": f"`-{abs(daily_loss_pct):.2f}%`", "inline": True},
                {"name": "Consecutive SLs", "value": f"`{consecutive_losses}`", "inline": True},
                {"name": "Status", "value": "`LOCKED (Cool-down)`", "inline": True},
                {"name": "Reset Time", "value": "`00:00 UTC`", "inline": True}
            ],
            "footer": {
                "text": "Institutional Kill Switch Engaged"
            }
        }
        self._dispatch_async({"embeds": [embed]})

    def send_test_message(self) -> Tuple[bool, str]:
        """Sends an immediate verification test message."""
        if not self.webhook_url:
            return False, "No Discord Webhook URL configured in bot_config.json."

        embed = {
            "title": "✅ Trading Bot Discord Integration Online",
            "description": "Your Discord webhook is successfully connected and receiving live real-time institutional alerts.",
            "color": 0x3498DB,  # Blue
            "fields": [
                {"name": "Account Risk", "value": "`1.0% Dynamic Compounding`", "inline": True},
                {"name": "Margin Mode", "value": "`🔒 ISOLATED (Never Cross)`", "inline": True},
                {"name": "Circuit Breaker", "value": "`Max -3.5% Daily Loss`", "inline": True},
                {"name": "Active Symbols", "value": "`BTC, HYPE, TAO, LTC, AVAX, NEAR, SUI, SOL`", "inline": False}
            ],
            "footer": {
                "text": f"Verified at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
            }
        }
        success = self._send_payload({"embeds": [embed]})
        if success:
            return True, "Test message successfully dispatched to Discord!"
        return False, "Failed to deliver message to Discord. Please check webhook URL validity."

discord_engine = DiscordNotifier()
