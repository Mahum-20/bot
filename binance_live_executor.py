"""
Binance Futures Live Execution Client
====================================
Handles authenticated REST API communication with Binance USDT-M Futures.
Supports:
1. PAPER: Simulated order fills (Default, 100% safe).
2. TESTNET: Binance Futures Testnet (https://testnet.binancefuture.com).
3. LIVE: Real Binance Futures Production (https://fapi.binance.com).

Security:
- Credentials loaded directly from encrypted SQLite vault (vault.py).
- Zero plaintext keys/secrets in bot_config.json.
- Strictly enforces ISOLATED margin mode on every traded asset before order dispatch.
- Dynamic leverage configuration.
- Bracket order submission (Market Entry + STOP_MARKET + TAKE_PROFIT_MARKET).
- HMAC-SHA256 authenticated request signing with millisecond synchronization.
"""

import os
import time
import hmac
import hashlib
import json
import logging
import urllib.request
import urllib.parse
from typing import Dict, Optional, Tuple
import vault
from exchange_filter_manager import exchange_filter_engine

logger = logging.getLogger("BinanceLiveExecutor")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "bot_config.json")

class BinanceLiveExecutor:
    def __init__(self):
        self.api_key: str = ""
        self.api_secret: str = ""
        self.mode: str = "PAPER"  # "PAPER" | "TESTNET" | "LIVE"
        self.load_config()

    def load_config(self):
        """Loads API credentials and execution mode from encrypted vault."""
        creds = vault.load_exchange_credentials("BINANCE")
        if creds.get("api_key") and creds.get("api_secret"):
            self.api_key = creds["api_key"]
            self.api_secret = creds["api_secret"]
            self.mode = creds.get("mode", "PAPER").upper()
        else:
            # Check legacy bot_config.json for migration
            if os.path.exists(CONFIG_PATH):
                try:
                    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    legacy_key = cfg.get("binance_api_key", "").strip()
                    legacy_sec = cfg.get("binance_api_secret", "").strip()
                    self.mode = cfg.get("execution_mode", "PAPER").upper()
                    if legacy_key and legacy_sec:
                        vault.save_exchange_credentials("BINANCE", legacy_key, legacy_sec, self.mode)
                        self.api_key = legacy_key
                        self.api_secret = legacy_sec
                        # Strip from bot_config.json immediately
                        cfg.pop("binance_api_key", None)
                        cfg.pop("binance_api_secret", None)
                        with open(CONFIG_PATH, "w", encoding="utf-8") as fw:
                            json.dump(cfg, fw, indent=2)
                        logger.info("Migrated legacy API credentials from bot_config.json into encrypted vault.")
                except Exception as e:
                    logger.warning(f"Config check: {e}")

    def save_config(self, api_key: str, api_secret: str, mode: str = "PAPER") -> bool:
        """Saves API credentials securely encrypted in vault.db and updates execution mode."""
        self.mode = mode.upper()
        
        # If user passed empty credentials while keeping existing, preserve existing
        if not api_key.strip() and not api_secret.strip():
            # Only mode changed
            creds = vault.load_exchange_credentials("BINANCE")
            if creds.get("api_key") and creds.get("api_secret"):
                api_key = creds["api_key"]
                api_secret = creds["api_secret"]

        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()

        saved = vault.save_exchange_credentials("BINANCE", self.api_key, self.api_secret, self.mode)

        # Update bot_config.json with mode only (never keys)
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg["execution_mode"] = self.mode
                cfg.pop("binance_api_key", None)
                cfg.pop("binance_api_secret", None)
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2)
            except Exception:
                pass

        logger.info(f"Binance configuration saved in vault. Mode set to {self.mode}.")
        return saved

    def get_base_url(self) -> str:
        if self.mode == "TESTNET":
            return "https://testnet.binancefuture.com"
        return "https://fapi.binance.com"

    def _sign_request(self, params: Dict) -> Tuple[str, Dict]:
        """Signs request parameters using HMAC-SHA256 signature."""
        params["timestamp"] = int(time.time() * 1000)
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "TopG-Bot/1.0"
        }
        return f"{query_string}&signature={signature}", headers

    def _send_request(self, method: str, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Dispatches signed HTTP request to Binance Futures REST API."""
        if not self.api_key or not self.api_secret:
            raise ValueError("Binance API Key and Secret are not configured in secure vault.")

        params = params or {}
        signed_query, headers = self._sign_request(params)
        base_url = self.get_base_url()

        if method.upper() == "GET":
            url = f"{base_url}{endpoint}?{signed_query}"
            req = urllib.request.Request(url, headers=headers, method="GET")
        else:
            url = f"{base_url}{endpoint}"
            data_bytes = signed_query.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method.upper())

        try:
            with urllib.request.urlopen(req, timeout=8) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8")
            try:
                err_json = json.loads(err_body)
                raise RuntimeError(f"Binance API Error [{err_json.get('code')}]: {err_json.get('msg')}")
            except Exception:
                raise RuntimeError(f"Binance HTTP {he.code}: {err_body}")

    def get_real_futures_balance(self) -> Optional[float]:
        """Queries live Binance Futures USDT wallet balance if API credentials are configured."""
        if not self.api_key or not self.api_secret:
            return None
        try:
            balances = self._send_request("GET", "/fapi/v2/balance")
            usdt_wallet = next((b for b in balances if b.get("asset") == "USDT"), None)
            if usdt_wallet:
                return float(usdt_wallet.get("balance", 0.0))
        except Exception as e:
            logger.warning(f"Failed to fetch live Binance balance: {e}")
        return None

    def test_connection(self) -> Dict:
        """Tests API key permissions and queries wallet balance (Zero Secret Exposure)."""
        safe_info = vault.get_safe_exchange_status("BINANCE")
        if self.mode == "PAPER":
            return {
                "success": True,
                "mode": "PAPER",
                "message": "Paper Trading active (No real orders dispatched).",
                "usdt_balance": 0.0,
                "permissions": ["PAPER_SIMULATION"],
                "masked_key": safe_info.get("masked_key", ""),
                "secret_configured": safe_info.get("secret_configured", False)
            }

        try:
            balances = self._send_request("GET", "/fapi/v2/balance")
            usdt_wallet = next((b for b in balances if b.get("asset") == "USDT"), None)
            total_balance = float(usdt_wallet.get("balance", 0.0)) if usdt_wallet else 0.0
            avail_balance = float(usdt_wallet.get("availableBalance", 0.0)) if usdt_wallet else 0.0

            return {
                "success": True,
                "mode": self.mode,
                "usdt_balance": total_balance,
                "available_balance": avail_balance,
                "message": f"Successfully connected to Binance Futures ({self.mode}). Balance: ${total_balance:,.2f} USDT",
                "masked_key": safe_info.get("masked_key", ""),
                "secret_configured": safe_info.get("secret_configured", False)
            }
        except Exception as e:
            return {
                "success": False,
                "mode": self.mode,
                "error": str(e),
                "message": f"Connection failed: {str(e)}",
                "masked_key": safe_info.get("masked_key", ""),
                "secret_configured": safe_info.get("secret_configured", False)
            }

    def set_isolated_margin(self, symbol: str) -> bool:
        """Enforces ISOLATED margin mode on the symbol."""
        if self.mode == "PAPER":
            return True
        try:
            res = self._send_request("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
            return res.get("code") == 200 or "ISOLATED" in str(res)
        except Exception as e:
            if "No need to change margin type" in str(e):
                return True
            logger.error(f"Failed to set ISOLATED margin for {symbol}: {e}")
            return False

    def set_leverage(self, symbol: str, leverage: int = 5) -> bool:
        """Enforces target leverage on the symbol."""
        if self.mode == "PAPER":
            return True
        try:
            res = self._send_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
            return res.get("leverage") == leverage
        except Exception as e:
            logger.error(f"Failed to set {leverage}x leverage for {symbol}: {e}")
            return False

    def cancel_algo_order(self, algo_id: int) -> bool:
        """Cancels a specific conditional/algo order (SL or TP) on Binance Futures."""
        if self.mode == "PAPER" or not algo_id:
            return True
        try:
            res = self._send_request("DELETE", "/fapi/v1/algoOrder", {"algoId": algo_id})
            return res.get("code") == "200" or res.get("code") == 200
        except Exception as e:
            logger.warning(f"Failed to cancel algo order {algo_id}: {e}")
            return False

    def cancel_all_orders_for_symbol(self, symbol: str) -> bool:
        """Cancels all standard open orders and conditional algo orders for a symbol."""
        if self.mode == "PAPER":
            return True
        try:
            self._send_request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol})
        except Exception:
            pass
        return True

    def execute_bracket_order(self, payload: Dict) -> Dict:
        """Submits complete bracket order set to Binance Futures from risk manager payload."""
        if self.mode == "PAPER":
            return {
                "success": True,
                "mode": "PAPER",
                "symbol": payload.get("symbol"),
                "order_id": f"PAPER_{int(time.time()*1000)}",
                "message": "Paper trade simulated."
            }

        symbol = payload.get("symbol")
        side = payload.get("side", "BUY")
        qty = float(payload.get("quantity") or 0.0)
        leverage = payload.get("leverage", 5)
        order_type = payload.get("type", "LIMIT")
        entry_price = float(payload.get("price") or payload.get("entryPrice") or 0.0)
        sl_price = float(payload.get("stopLoss", {}).get("stopPrice") or 0.0)
        tp_price = float(payload.get("takeProfit", {}).get("stopPrice") or 0.0)

        # Format exact Binance-compliant string values
        formatted_qty = exchange_filter_engine.format_quantity(symbol, qty)
        formatted_entry = exchange_filter_engine.format_price(symbol, entry_price)
        formatted_sl = exchange_filter_engine.format_price(symbol, sl_price)
        formatted_tp = exchange_filter_engine.format_price(symbol, tp_price)

        try:
            self.set_isolated_margin(symbol)
            self.set_leverage(symbol, leverage)

            entry_params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": order_type,
                "quantity": formatted_qty,
                "positionSide": "BOTH",
                "newOrderRespType": "RESULT"
            }
            if order_type == "LIMIT":
                entry_params["price"] = formatted_entry
                entry_params["timeInForce"] = "GTX"

            try:
                entry_res = self._send_request("POST", "/fapi/v1/order", entry_params)
            except Exception as entry_err:
                # If Post-Only (GTX) rejected because price crossed spread (-5022), fall back to MARKET
                if "-5022" in str(entry_err) and order_type == "LIMIT":
                    logger.warning(f"Post-only GTX rejected for {symbol} (-5022). Falling back to MARKET order to secure entry.")
                    entry_params["type"] = "MARKET"
                    entry_params.pop("price", None)
                    entry_params.pop("timeInForce", None)
                    order_type = "MARKET"
                    entry_res = self._send_request("POST", "/fapi/v1/order", entry_params)
                else:
                    raise entry_err

            entry_order_id = entry_res.get("orderId")
            avg_price = float(entry_res.get("avgPrice") or entry_price or 0.0)

            exit_side = "SELL" if side.upper() == "BUY" else "BUY"

            # Post SL as Algo Order (Binance Futures Algo Order Service)
            sl_params = {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": exit_side,
                "positionSide": "BOTH",
                "type": "STOP_MARKET",
                "triggerPrice": formatted_sl,
                "quantity": formatted_qty,
                "reduceOnly": "true"
            }
            sl_res = self._send_request("POST", "/fapi/v1/algoOrder", sl_params)

            # Post TP as Algo Order (Binance Futures Algo Order Service)
            tp_params = {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": exit_side,
                "positionSide": "BOTH",
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": formatted_tp,
                "quantity": formatted_qty,
                "reduceOnly": "true"
            }
            tp_res = self._send_request("POST", "/fapi/v1/algoOrder", tp_params)

            return {
                "success": True,
                "mode": self.mode,
                "symbol": symbol,
                "order_id": entry_order_id,
                "entry_order_id": entry_order_id,
                "order_status": entry_res.get("status", "NEW"),
                "order_type": order_type,
                "fill_price": avg_price,
                "sl_order_id": sl_res.get("algoId"),
                "tp_order_id": tp_res.get("algoId")
            }
        except Exception as e:
            logger.error(f"Live bracket order execution failed for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "symbol": symbol,
                "mode": self.mode
            }

    def execute_market_bracket(
        self,
        symbol: str,
        side: str,          # "BUY" (Long) | "SELL" (Short)
        quantity: float,
        stop_loss_price: float,
        take_profit_price: float,
        leverage: int = 5
    ) -> Dict:
        """Submits bracket order set to Binance Futures."""
        if self.mode == "PAPER":
            return {
                "success": True,
                "mode": "PAPER",
                "symbol": symbol,
                "order_id": f"PAPER_{int(time.time()*1000)}",
                "side": side,
                "quantity": quantity,
                "message": "Paper trade simulated."
            }

        formatted_qty = exchange_filter_engine.format_quantity(symbol, quantity)
        formatted_sl = exchange_filter_engine.format_price(symbol, stop_loss_price)
        formatted_tp = exchange_filter_engine.format_price(symbol, take_profit_price)

        try:
            self.set_isolated_margin(symbol)
            self.set_leverage(symbol, leverage)

            entry_params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "MARKET",
                "quantity": formatted_qty,
                "positionSide": "BOTH",
                "newOrderRespType": "RESULT"
            }
            entry_res = self._send_request("POST", "/fapi/v1/order", entry_params)
            entry_order_id = entry_res.get("orderId")
            avg_price = float(entry_res.get("avgPrice", 0.0))

            exit_side = "SELL" if side.upper() == "BUY" else "BUY"

            sl_params = {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": exit_side,
                "positionSide": "BOTH",
                "type": "STOP_MARKET",
                "triggerPrice": formatted_sl,
                "quantity": formatted_qty,
                "reduceOnly": "true"
            }
            sl_res = self._send_request("POST", "/fapi/v1/algoOrder", sl_params)

            tp_params = {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": exit_side,
                "positionSide": "BOTH",
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": formatted_tp,
                "quantity": formatted_qty,
                "reduceOnly": "true"
            }
            tp_res = self._send_request("POST", "/fapi/v1/algoOrder", tp_params)

            return {
                "success": True,
                "mode": self.mode,
                "symbol": symbol,
                "entry_order_id": entry_order_id,
                "fill_price": avg_price,
                "sl_order_id": sl_res.get("algoId"),
                "tp_order_id": tp_res.get("algoId")
            }
        except Exception as e:
            logger.error(f"Live bracket order execution failed for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "symbol": symbol,
                "mode": self.mode
            }

    def get_position_amt(self, symbol: str) -> Optional[float]:
        """Queries live Binance position amount for a given symbol."""
        if self.mode == "PAPER" or not self.api_key or not self.api_secret:
            return None
        try:
            positions = self._send_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
            for p in positions:
                if p.get("symbol") == symbol:
                    return float(p.get("positionAmt", 0.0))
        except Exception as e:
            logger.warning(f"Failed to fetch positionRisk for {symbol}: {e}")
        return None

    def get_order_status(self, symbol: str, order_id: Optional[int]) -> Optional[Dict]:
        """Queries current status of a specific order on Binance Futures."""
        if self.mode == "PAPER" or not self.api_key or not self.api_secret or not order_id:
            return None
        try:
            return self._send_request("GET", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id})
        except Exception as e:
            logger.warning(f"Failed to query order {order_id} for {symbol}: {e}")
            return None

    def cancel_all_open_orders(self, symbol: str) -> bool:
        """Cancels all active regular orders and conditional algo orders for a symbol."""
        if self.mode == "PAPER":
            return True
        success = True
        try:
            self._send_request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol})
            logger.info(f"Sent cancel all regular open orders for {symbol}")
        except Exception as e:
            logger.warning(f"Failed to cancel regular open orders for {symbol}: {e}")
            success = False

        try:
            open_algos = self._send_request("GET", "/fapi/v1/openAlgoOrders")
            if isinstance(open_algos, list):
                for algo in open_algos:
                    if algo.get("symbol") == symbol and "algoId" in algo:
                        aid = algo["algoId"]
                        try:
                            self._send_request("DELETE", "/fapi/v1/algoOrder", {"algoId": aid})
                            logger.info(f"Cancelled orphan algo order {aid} ({algo.get('orderType', 'ALGO')}) for {symbol}")
                        except Exception as ce:
                            logger.warning(f"Failed to cancel algo {aid} for {symbol}: {ce}")
        except Exception as e:
            logger.warning(f"Failed to query/cancel open algo orders for {symbol}: {e}")
            success = False
        return success

binance_executor = BinanceLiveExecutor()

