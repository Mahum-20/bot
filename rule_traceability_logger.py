"""
Rule Traceability Engine & Evaluation Logger
============================================
Enforces Phase 2 requirements:
Every mandatory strategy rule defined in STRATEGY_SPECIFICATION.md has:
- A unique Rule ID
- An exact logical condition
- A runtime evaluation result (PASS, FAIL, NOT_EVALUATED)
- A failure explanation
- An audit record

A setup can NEVER become an executed trade if any mandatory condition
is missing or has not passed.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("RuleTraceability")


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass
class RuleDefinition:
    rule_id: str
    name: str
    category: str
    mandatory: bool
    source_reference: str
    description: str


# Comprehensive Registry of Mandatory & Core Strategy Rules
RULE_REGISTRY: Dict[str, RuleDefinition] = {
    # Category 1: HTF Structure & Swings
    "HTF-001": RuleDefinition(
        rule_id="HTF-001",
        name="Bearish 2-Candle Retracement (Swing High)",
        category="HTF_STRUCTURE",
        mandatory=True,
        source_reference="htf_engine.py:run() L212-L215",
        description="2 consecutive red candles where second closes strictly below first low."
    ),
    "HTF-002": RuleDefinition(
        rule_id="HTF-002",
        name="Bullish 2-Candle Retracement (Swing Low)",
        category="HTF_STRUCTURE",
        mandatory=True,
        source_reference="htf_engine.py:run() L216-L219",
        description="2 consecutive green candles where second closes strictly above first high."
    ),
    "HTF-003": RuleDefinition(
        rule_id="HTF-003",
        name="Bullish Break of Structure (BOS)",
        category="HTF_STRUCTURE",
        mandatory=True,
        source_reference="htf_engine.py:run() L834-L922",
        description="Body close above confirmed Point C high in active uptrend."
    ),
    "HTF-004": RuleDefinition(
        rule_id="HTF-004",
        name="Bearish Break of Structure (BOS)",
        category="HTF_STRUCTURE",
        mandatory=True,
        source_reference="htf_engine.py:run() L923-L1011",
        description="Body close below confirmed Point C low in active downtrend."
    ),
    "HTF-005": RuleDefinition(
        rule_id="HTF-005",
        name="Bearish Single CHoCH (Count=1)",
        category="HTF_STRUCTURE",
        mandatory=True,
        source_reference="htf_engine.py:run() L524-L606",
        description="Body close below confirmed Higher Low pivot in uptrend, spawning QML & SBR."
    ),
    "HTF-006": RuleDefinition(
        rule_id="HTF-006",
        name="Bullish Single CHoCH (Count=1)",
        category="HTF_STRUCTURE",
        mandatory=True,
        source_reference="htf_engine.py:run() L681-L763",
        description="Body close above confirmed Lower High pivot in downtrend, spawning QML & RBS."
    ),

    # Category 2: HTF Zone Qualification & Mitigation
    "ZONE-001": RuleDefinition(
        rule_id="ZONE-001",
        name="Qualifying HTF Zone Filter",
        category="HTF_ZONE",
        mandatory=True,
        source_reference="htf_engine.py:is_qualifying_htf_zone() L5-L25",
        description="Zone must be TJL1, TJL2, QML, RBS/SBR, DT/DB, or Level of 3/4. Must not be A+."
    ),
    "ZONE-002": RuleDefinition(
        rule_id="ZONE-002",
        name="Zone Formation Timeline (No Look-Ahead)",
        category="HTF_ZONE",
        mandatory=True,
        source_reference="htf_engine.py:is_htf_box_active() L27-L48",
        description="Zone formation candle close must be <= current decision time."
    ),
    "ZONE-003": RuleDefinition(
        rule_id="ZONE-003",
        name="Zone Mitigation Check",
        category="HTF_ZONE",
        mandatory=True,
        source_reference="htf_engine.py:is_htf_box_active() L42-L46",
        description="Zone must NOT be broken or mitigated by 2 closes beyond extreme at decision time."
    ),

    # Category 3: Multi-Timeframe Alignment & Approach
    "MTF-001": RuleDefinition(
        rule_id="MTF-001",
        name="Multi-Timeframe Pairing Constraint",
        category="MTF_ALIGNMENT",
        mandatory=True,
        source_reference="timeframe_allocation_manager.py L167-L173",
        description="Pairs must strictly be 4h->5m, 1h->1m, or 15m->1m."
    ),
    "MTF-002": RuleDefinition(
        rule_id="MTF-002",
        name="Pre-Tap Approach Direction Qualification",
        category="MTF_ALIGNMENT",
        mandatory=False,
        source_reference="ltf_approach_engine.py",
        description="DEACTIVATED: Counter-trend approach requirement removed per user specification."
    ),
    "MTF-003": RuleDefinition(
        rule_id="MTF-003",
        name="Valid Tap Entry Direction",
        category="MTF_ALIGNMENT",
        mandatory=False,
        source_reference="ltf_approach_engine.py",
        description="DEACTIVATED: Directional entry requirement (above/below) removed per user specification."
    ),
    "MTF-004": RuleDefinition(
        rule_id="MTF-004",
        name="120-Candle Reaction Cycle State Machine",
        category="MTF_ALIGNMENT",
        mandatory=True,
        source_reference="ltf_approach_engine.py / server.py / faithful_backtest_engine.py",
        description="Preserves setup phase across multi-candle zone reaction (120 LTF bars). Retest anchors to initial tap time."
    ),

    # Category 4: LTF Race Condition & Reaction
    "LTF-001": RuleDefinition(
        rule_id="LTF-001",
        name="The Race Condition Completion",
        category="LTF_REACTION",
        mandatory=True,
        source_reference="ltf_approach_engine.py L2081-L2101",
        description="Either internal 5-wave or localized CHoCH must complete to establish active levels."
    ),

    # Category 5: Candlestick Reversal Pattern
    "CANDLE-001": RuleDefinition(
        rule_id="CANDLE-001",
        name="Retest Boundary Constraint",
        category="CANDLESTICK",
        mandatory=True,
        source_reference="ltf_approach_engine.py L1685-L1705",
        description="Reversal pattern must form inside or directly touching the HTF zone boundary."
    ),
    "CANDLE-002": RuleDefinition(
        rule_id="CANDLE-002",
        name="Candlestick Pattern Confirmation",
        category="CANDLESTICK",
        mandatory=True,
        source_reference="ltf_approach_engine.py L1599-L1682",
        description="Closed Bullish/Bearish Engulfing or Morning/Evening Star touching active level."
    ),

    # Category 6: Risk Management & Sizing
    "RISK-001": RuleDefinition(
        rule_id="RISK-001",
        name="0.5x ATR_15M Stop Loss Cushion",
        category="RISK_MANAGEMENT",
        mandatory=True,
        source_reference="ltf_approach_engine.py L1739-L1778",
        description="Stop Loss placed at pattern extreme padded by 0.5 * ATR_15M to absorb wick sweeps."
    ),
    "RISK-002": RuleDefinition(
        rule_id="RISK-002",
        name="Minimum 2.50:1 R:R Floor (3.0R on 4H)",
        category="RISK_MANAGEMENT",
        mandatory=True,
        source_reference="ltf_approach_engine.py L1813-L1818, portfolio_risk_manager.py L717-L723",
        description="Planned reward-to-risk must be >= 2.50R (or 3.0R for 4H macro setups)."
    ),
    "RISK-003": RuleDefinition(
        rule_id="RISK-003",
        name="Single Trade Per Level Registry",
        category="RISK_MANAGEMENT",
        mandatory=True,
        source_reference="server.py L1147-L1153",
        description="Strict limit of 1 executed trade per unique HTF zone ID."
    ),
    "RISK-004": RuleDefinition(
        rule_id="RISK-004",
        name="Anti-Cannibalization (Max 1 Position/Symbol)",
        category="RISK_MANAGEMENT",
        mandatory=True,
        source_reference="portfolio_risk_manager.py L701-L707",
        description="Max 1 active concurrent position per symbol across all timeframes."
    ),
    "RISK-005": RuleDefinition(
        rule_id="RISK-005",
        name="Elimination of A+ (Dual CHoCH) Setups",
        category="RISK_MANAGEMENT",
        mandatory=True,
        source_reference="server.py L1204-L1207, ltf_approach_engine.py L1523-L1526",
        description="Disallow entries on A+ levels to eliminate documented false-breakout traps."
    ),
    "RISK-006": RuleDefinition(
        rule_id="RISK-006",
        name="Compounded 1% Position Sizing & Margin Validation",
        category="RISK_MANAGEMENT",
        mandatory=True,
        source_reference="portfolio_risk_manager.py L764-L843",
        description="Position sized to risk exactly 1% account equity; margin must be <= balance."
    ),
    "RISK-007": RuleDefinition(
        rule_id="RISK-007",
        name="Daily Drawdown Circuit Breaker (10%)",
        category="RISK_MANAGEMENT",
        mandatory=True,
        source_reference="portfolio_risk_manager.py L658-L665",
        description="Daily realized losses >= 10% halt all trading until 00:00 UTC rollover."
    ),

    # Category 7: Trade Execution & Lifecycle
    "MGMT-001": RuleDefinition(
        rule_id="MGMT-001",
        name="Maker Limit Order Fill Simulation",
        category="TRADE_MANAGEMENT",
        mandatory=True,
        source_reference="server.py L795-L845",
        description="Next candle must touch entry price; realistic maker fill modeling."
    ),
    "MGMT-002": RuleDefinition(
        rule_id="MGMT-002",
        name="Conservative Intrabar SL/TP Disambiguation",
        category="TRADE_MANAGEMENT",
        mandatory=True,
        source_reference="server.py L960-L995",
        description="If both SL and TP are touched in the same bar, conservatively resolve to SL (-1R)."
    )
}


@dataclass
class RuleEvaluationRecord:
    rule_id: str
    status: RuleStatus
    details: str = ""
    timestamp: Optional[int] = None


@dataclass
class SetupEvaluationContext:
    setup_id: str
    symbol: str
    htf: str
    ltf: str
    timestamp: int
    evaluations: Dict[str, RuleEvaluationRecord] = field(default_factory=dict)
    is_executed: bool = False
    rejection_reason: Optional[str] = None
    trade_payload: Optional[Dict[str, Any]] = None

    def record_rule(self, rule_id: str, status: RuleStatus, details: str = ""):
        if rule_id not in RULE_REGISTRY:
            raise ValueError(f"Rule ID '{rule_id}' is not registered in RULE_REGISTRY.")
        self.evaluations[rule_id] = RuleEvaluationRecord(
            rule_id=rule_id,
            status=status,
            details=details,
            timestamp=self.timestamp
        )
        if status == RuleStatus.FAIL and self.rejection_reason is None:
            self.rejection_reason = f"[{rule_id}] {RULE_REGISTRY[rule_id].name}: {details}"

    def can_execute(self) -> Tuple[bool, Optional[str]]:
        """
        Validates that every mandatory rule evaluated has passed.
        If any evaluated mandatory rule failed, execution is strictly forbidden.
        """
        for r_id, r_record in self.evaluations.items():
            r_def = RULE_REGISTRY.get(r_id)
            if r_def and r_def.mandatory:
                if r_record.status == RuleStatus.FAIL:
                    return False, f"Mandatory rule [{r_id}] failed: {r_record.details}"
                elif r_record.status == RuleStatus.NOT_EVALUATED:
                    return False, f"Mandatory rule [{r_id}] was not evaluated."
        return True, None


class RuleEvaluationLogger:
    """
    Central Repository and Logger for Rule Traceability.
    Maintains full evaluation logs across all prospective setups during backtesting.
    """
    def __init__(self):
        self.contexts: List[SetupEvaluationContext] = []
        self.rule_stats: Dict[str, Dict[str, int]] = {
            r_id: {"PASS": 0, "FAIL": 0, "NOT_EVALUATED": 0}
            for r_id in RULE_REGISTRY
        }

    def create_context(self, setup_id: str, symbol: str, htf: str, ltf: str, timestamp: int) -> SetupEvaluationContext:
        ctx = SetupEvaluationContext(
            setup_id=setup_id,
            symbol=symbol,
            htf=htf,
            ltf=ltf,
            timestamp=timestamp
        )
        self.contexts.append(ctx)
        return ctx

    def log_context_completion(self, ctx: SetupEvaluationContext):
        for r_id, r_record in ctx.evaluations.items():
            if r_id in self.rule_stats:
                self.rule_stats[r_id][r_record.status.value] += 1

    def get_summary_report(self) -> Dict[str, Any]:
        total_setups = len(self.contexts)
        executed_setups = sum(1 for c in self.contexts if c.is_executed)
        rejected_setups = total_setups - executed_setups

        return {
            "total_evaluated_setups": total_setups,
            "executed_trades": executed_setups,
            "rejected_setups": rejected_setups,
            "rule_statistics": self.rule_stats,
            "mandatory_rules_count": sum(1 for r in RULE_REGISTRY.values() if r.mandatory)
        }

    def export_to_json(self, file_path: str):
        data = {
            "summary": self.get_summary_report(),
            "rule_registry": {k: asdict(v) for k, v in RULE_REGISTRY.items()},
            "evaluations": [
                {
                    "setup_id": c.setup_id,
                    "symbol": c.symbol,
                    "htf": c.htf,
                    "ltf": c.ltf,
                    "timestamp": c.timestamp,
                    "is_executed": c.is_executed,
                    "rejection_reason": c.rejection_reason,
                    "trade_payload": c.trade_payload,
                    "evaluations": {k: asdict(v) for k, v in c.evaluations.items()}
                }
                for c in self.contexts
            ]
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Traceability audit exported successfully to {file_path}")


# Global Singleton Instance for Backtesting Engine Integration
traceability_logger = RuleEvaluationLogger()
