import unittest
from rule_traceability_logger import (
    RuleEvaluationLogger,
    RuleStatus,
    RULE_REGISTRY
)

class TestRuleTraceabilityLogger(unittest.TestCase):
    def setUp(self):
        self.logger = RuleEvaluationLogger()

    def test_registry_contains_mandatory_rules(self):
        mandatory_keys = [
            "HTF-001", "HTF-002", "HTF-003", "HTF-004", "HTF-005", "HTF-006",
            "ZONE-001", "ZONE-002", "ZONE-003", "MTF-001", "MTF-004",
            "LTF-001", "CANDLE-001", "CANDLE-002", "RISK-001", "RISK-002",
            "RISK-003", "RISK-004", "RISK-005", "RISK-006", "RISK-007",
            "MGMT-001", "MGMT-002"
        ]
        for key in mandatory_keys:
            self.assertIn(key, RULE_REGISTRY)
            self.assertTrue(RULE_REGISTRY[key].mandatory)
        self.assertFalse(RULE_REGISTRY["MTF-002"].mandatory)
        self.assertFalse(RULE_REGISTRY["MTF-003"].mandatory)

    def test_context_rejection_on_mandatory_failure(self):
        ctx = self.logger.create_context("setup_001", "BTCUSDT", "15m", "1m", 1793860000)
        ctx.record_rule("ZONE-001", RuleStatus.PASS, "Qualifying TJL1 level")
        ctx.record_rule("RISK-002", RuleStatus.FAIL, "R:R 2.14 below 2.50 floor")
        
        can_exec, reason = ctx.can_execute()
        self.assertFalse(can_exec)
        self.assertIn("RISK-002", reason)
        self.assertEqual(ctx.rejection_reason, "[RISK-002] Minimum 2.50:1 R:R Floor (3.0R on 4H): R:R 2.14 below 2.50 floor")

    def test_context_passes_when_all_pass(self):
        ctx = self.logger.create_context("setup_002", "BTCUSDT", "15m", "1m", 1793860000)
        ctx.record_rule("ZONE-001", RuleStatus.PASS, "Qualifying TJL1 level")
        ctx.record_rule("MTF-002", RuleStatus.PASS, "Clean bearish approach into demand")
        ctx.record_rule("RISK-002", RuleStatus.PASS, "R:R 2.85 >= 2.50")
        
        can_exec, reason = ctx.can_execute()
        self.assertTrue(can_exec)
        self.assertIsNone(reason)

    def test_logger_summary_stats(self):
        ctx1 = self.logger.create_context("s1", "BTCUSDT", "15m", "1m", 100)
        ctx1.record_rule("ZONE-001", RuleStatus.PASS)
        ctx1.record_rule("RISK-002", RuleStatus.FAIL, "Low RR")
        self.logger.log_context_completion(ctx1)

        ctx2 = self.logger.create_context("s2", "BTCUSDT", "15m", "1m", 200)
        ctx2.record_rule("ZONE-001", RuleStatus.PASS)
        ctx2.record_rule("RISK-002", RuleStatus.PASS, "Good RR")
        ctx2.is_executed = True
        self.logger.log_context_completion(ctx2)

        summary = self.logger.get_summary_report()
        self.assertEqual(summary["total_evaluated_setups"], 2)
        self.assertEqual(summary["executed_trades"], 1)
        self.assertEqual(summary["rejected_setups"], 1)
        self.assertEqual(summary["rule_statistics"]["ZONE-001"]["PASS"], 2)
        self.assertEqual(summary["rule_statistics"]["RISK-002"]["FAIL"], 1)
        self.assertEqual(summary["rule_statistics"]["RISK-002"]["PASS"], 1)

if __name__ == "__main__":
    unittest.main()
