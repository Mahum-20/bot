import unittest
from rule_traceability_logger import RuleEvaluationLogger, RuleStatus, RULE_REGISTRY
from faithful_backtest_engine import FaithfulBacktestEngine

class TestFaithfulBacktestEngine(unittest.TestCase):
    def setUp(self):
        self.custom_logger = RuleEvaluationLogger()
        # Initialize engine on 15m->1m with custom logger
        self.engine = FaithfulBacktestEngine(
            symbol="BTCUSDT",
            htf_tf="15m",
            ltf_tf="1m",
            initial_balance=1000.0,
            risk_pct=0.01,
            logger_instance=self.custom_logger
        )

    def test_negative_case_a_plus_setup_rejection(self):
        """Negative Test: A+ (Dual CHoCH) setup MUST be rejected per Rule RISK-005."""
        ctx = self.custom_logger.create_context("test_aplus", "BTCUSDT", "15m", "1m", 100000)
        ctx.record_rule("ZONE-001", RuleStatus.PASS, "Tapped level")
        ctx.record_rule("RISK-005", RuleStatus.FAIL, "A+ setup eliminated by institutional rule")
        
        can_exec, reason = ctx.can_execute()
        self.assertFalse(can_exec)
        self.assertIn("RISK-005", reason)

    def test_negative_case_low_rr_rejection(self):
        """Negative Test: Planned R:R below 2.50:1 floor MUST be rejected per Rule RISK-002."""
        ctx = self.custom_logger.create_context("test_low_rr", "BTCUSDT", "15m", "1m", 100000)
        ctx.record_rule("ZONE-001", RuleStatus.PASS, "Tapped level")
        ctx.record_rule("RISK-002", RuleStatus.FAIL, "RR 2.15 < 2.50 floor")
        
        can_exec, reason = ctx.can_execute()
        self.assertFalse(can_exec)
        self.assertIn("RISK-002", reason)

    def test_negative_case_candle_pattern_missing(self):
        """Negative Test: Missing candlestick reversal pattern MUST be rejected per Rule CANDLE-002."""
        ctx = self.custom_logger.create_context("test_no_pattern", "BTCUSDT", "15m", "1m", 100000)
        ctx.record_rule("CANDLE-002", RuleStatus.FAIL, "No reversal pattern confirmed")
        
        can_exec, reason = ctx.can_execute()
        self.assertFalse(can_exec)
        self.assertIn("CANDLE-002", reason)

    def test_negative_case_duplicate_zone_trade_rejection(self):
        """Negative Test: Duplicate trade on same zone ID MUST be rejected per Rule RISK-003."""
        reg_key = "BTCUSDT_15m_TJL1_75000_75500_1000"
        self.engine.zone_single_trade_registry.add(reg_key)
        self.assertIn(reg_key, self.engine.zone_single_trade_registry)
        
        ctx = self.custom_logger.create_context("test_dup", "BTCUSDT", "15m", "1m", 100000)
        ctx.record_rule("RISK-003", RuleStatus.FAIL, "Level already traded")
        can_exec, reason = ctx.can_execute()
        self.assertFalse(can_exec)

    def test_positive_case_all_mandatory_rules_pass(self):
        """Positive Test: Trade executes when all mandatory conditions pass."""
        ctx = self.custom_logger.create_context("test_pass", "BTCUSDT", "15m", "1m", 100000)
        ctx.record_rule("ZONE-001", RuleStatus.PASS)
        ctx.record_rule("ZONE-002", RuleStatus.PASS)
        ctx.record_rule("ZONE-003", RuleStatus.PASS)
        ctx.record_rule("MTF-001", RuleStatus.PASS)
        ctx.record_rule("MTF-002", RuleStatus.PASS)
        ctx.record_rule("MTF-003", RuleStatus.PASS)
        ctx.record_rule("LTF-001", RuleStatus.PASS)
        ctx.record_rule("CANDLE-001", RuleStatus.PASS)
        ctx.record_rule("CANDLE-002", RuleStatus.PASS)
        ctx.record_rule("RISK-001", RuleStatus.PASS)
        ctx.record_rule("RISK-002", RuleStatus.PASS)
        ctx.record_rule("RISK-003", RuleStatus.PASS)
        ctx.record_rule("RISK-004", RuleStatus.PASS)
        ctx.record_rule("RISK-005", RuleStatus.PASS)
        ctx.record_rule("RISK-006", RuleStatus.PASS)
        ctx.record_rule("RISK-007", RuleStatus.PASS)
        ctx.record_rule("MGMT-001", RuleStatus.PASS)
        ctx.record_rule("MGMT-002", RuleStatus.PASS)
        
        can_exec, reason = ctx.can_execute()
        self.assertTrue(can_exec)
        self.assertIsNone(reason)

    def test_position_sizing_compounded_1_percent(self):
        """Rule RISK-006: 1% risk compounding verified."""
        self.engine.balance = 1000.0
        risk_dollars = self.engine.balance * self.engine.risk_pct
        self.assertEqual(risk_dollars, 10.0)

        # Compound to 1500
        self.engine.balance = 1500.0
        risk_dollars = self.engine.balance * self.engine.risk_pct
        self.assertEqual(risk_dollars, 15.0)

if __name__ == "__main__":
    unittest.main()
