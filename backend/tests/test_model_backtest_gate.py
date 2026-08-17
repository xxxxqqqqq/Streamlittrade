"""Model portfolio backtest governance helpers."""

import unittest

from backend.app.services.model_backtest_gate import (
    SEALED_DEFAULT_PORTFOLIO_PROTOCOL,
    prediction_window,
    sealed_portfolio_protocol,
)


class ModelBacktestGateTests(unittest.TestCase):
    def test_tuning_scope_uses_complete_research_boundary(self):
        metrics = {
            "evaluation_scope": "tuning_oos",
            "research_split": {"tuning": {"start": "2022-09-26", "end": "2024-06-11"}},
        }
        self.assertEqual(
            prediction_window(metrics, None, "tuning_oos"),
            ("2022-09-26", "2024-06-11"),
        )

    def test_sealed_scope_requires_successful_final_holdout(self):
        with self.assertRaisesRegex(ValueError, "尚未成功"):
            prediction_window({}, {"evaluation_scope": "failed"}, "sealed_oos")
        self.assertEqual(
            prediction_window({}, {
                "evaluation_scope": "final_sealed_holdout",
                "sealed_start": "2024-08-07",
                "sealed_end": "2025-12-03",
            }, "sealed_oos"),
            ("2024-08-07", "2025-12-03"),
        )

    def test_legacy_sealed_protocol_is_never_mislabelled_as_preregistered(self):
        legacy, source = sealed_portfolio_protocol({})
        self.assertEqual(legacy, SEALED_DEFAULT_PORTFOLIO_PROTOCOL)
        self.assertEqual(source, "legacy_default_not_preregistered")
        registered, source = sealed_portfolio_protocol({"portfolio_protocol": {"top_n": 12}})
        self.assertEqual(registered["top_n"], 12)
        self.assertEqual(source, "preregistered")


if __name__ == "__main__":
    unittest.main()
