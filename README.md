# TopG Institutional Trading Bot

An algorithmic trading bot implementing TopG institutional market structure rules, multi-timeframe confirmation, and automated risk management across crypto (Binance) and multi-asset pairs.

---

## Architecture Overview

```
                      +---------------------------------------+
                      |       Binance Live Feed / REST        |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |         HTF Structure Engine          |
                      | (Rolling 500-Candle FIFO Lookback)    |
                      |   - TJL1 & TJL2 Breakout Zones        |
                      |   - QML & RBS / SBR Structural Levels |
                      |   - Double Tops & Double Bottoms      |
                      |   - Key Institutional Levels (L3, L4) |
                      |   - Invalidation (2 Closes Beyond)    |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |       LTF Approach & Cycle Engine     |
                      |  - Outside-In Zone Tap Detection      |
                      |  - 120-Candle Reaction Cycle State    |
                      |  - Immutable Zone Trade Registry Lock |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |       Price Action Confirmation       |
                      |  - Bullish / Bearish Engulfing        |
                      |  - Morning / Evening Star             |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |       Portfolio Risk & Execution      |
                      |  - Profile RR (4H 3R | 1H/15M >= 2.5R)|
                      |  - Dynamic 1% Account Risk Sizing     |
                      |  - 1-Trade-Per-Zone Permanent Lock    |
                      |  - 3.5% Daily Drawdown Breaker (3 Ls) |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |        FastAPI Live Web Server        |
                      |  - Real-Time WebSocket Streaming      |
                      |  - Interactive TradingView Dashboard  |
                      |  - Automated Discord Trade Alerts     |
                      +---------------------------------------+
```

---

## Key Features & Rules

1. **Strict 500-Candle Rolling Window (`ZONE-003`)**:
   - Mirrors TradingView's lookback boundary (`startLookbackBar = math.max(0, last_bar_index - 500)`).
   - Old, unmitigated structures from months prior are automatically evicted to prevent zombie trades.

2. **Zone Invalidation & Expiration**:
   - Zones breached by 2 consecutive candle closes beyond their boundary are marked broken and permanently deleted.

3. **Immutable 1-Trade-Per-Zone Registry (`RISK-003`)**:
   - Every zone is uniquely keyed by its formation timestamp and price bounds (`f"{type}_{left}_{top}_{bottom}"`).
   - Prevents repeated re-entries on failing levels.

4. **120-Candle Reaction Window**:
   - Once price taps an active zone from the valid approach direction, the bot monitors for an LTF reversal pattern within 120 candles.

5. **Risk & Capital Preservation**:
   - Profile-specific Risk-to-Reward targets: Fixed 3R for 4H/M5; opposing liquidity target with >= 2.5R floor for 1H/M5 and 15M/M1.
   - Dynamic 1% account risk sizing with minimum viable lot protection.
   - 3.5% daily drawdown limit and 3 consecutive losses circuit breaker.
   - Intrabar stop-loss and take-profit monitoring with slippage and fee accounting.

---

## File Structure

```
├── server.py                        # FastAPI live server, WebSocket streaming, trade loop
├── htf_engine.py                    # Higher Timeframe market structure engine
├── ltf_approach_engine.py           # Zone tap detection & reaction cycle state machine
├── ltf_engine.py                    # Lower timeframe price action processing
├── pattern_scanner.py               # Candlestick reversal pattern detection
├── portfolio_risk_manager.py        # Position sizing, drawdown circuit breakers
├── binance_live_executor.py         # Live Binance order dispatch & trade lifecycle
├── binance_feed.py                  # Real-time Binance Kline WebSockets
├── timeframe_allocation_manager.py  # Multi-timeframe performance allocation
├── faithful_backtest_engine.py      # Backtest simulator with 1:1 live parity
├── rule_traceability_logger.py      # Granular rule evaluation logger
├── bot_config.json                  # Runtime risk limits & bot configuration
├── static/                          # Web dashboard (HTML, CSS, JS, TradingView Charts)
├── requirements.txt                 # Python dependencies
└── STRATEGY_SPECIFICATION.md        # Complete strategy & rule specification
```

---

## Setup & Installation

### 1. Requirements
- Python 3.10+
- Binance API Key & Secret (optional for Paper Trading)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Live Bot
```bash
python server.py
```
Open `http://localhost:8000` to view the live trading dashboard.

### 4. Run Unit Tests & Backtests
```bash
# Run unit test suite
python -m unittest test_rule_traceability.py test_faithful_backtest_engine.py

# Run backtest
python run_oct_2026_backtest.py
```

---

## License
MIT
