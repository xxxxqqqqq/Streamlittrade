"""Point-in-time universe and economically motivated factor contracts."""

import unittest

import numpy as np
import pandas as pd

from backend.app.schemas.data_catalog import DynamicUniversePolicy, FeatureCreate, SyncCreate
from backend.app.services.factors import compute_factor, factor_library_payload
from backend.app.services.universe import apply_dynamic_universe


class UniverseContractTests(unittest.TestCase):
    def market_frame(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        rows = []
        for symbol, scale in (("000001", 3.0), ("000002", 2.0), ("000003", 1.0)):
            for index, date in enumerate(dates):
                close = 10 + index * .1
                rows.append({
                    "date": date, "symbol": symbol, "open": close, "high": close + 1,
                    "low": close - 1, "close": close, "volume": 1000 * scale,
                })
        return pd.DataFrame(rows)

    def test_dynamic_universe_is_point_in_time_and_capacity_bounded(self):
        frame = self.market_frame()
        policy = {
            "enabled": True, "min_history_days": 5, "min_price": 3,
            "liquidity_lookback": 3, "min_avg_turnover": 0, "max_members": 2,
        }
        baseline, report = apply_dynamic_universe(frame, policy)
        changed = frame.copy()
        last_date = changed["date"].max()
        changed.loc[(changed["date"] == last_date) & (changed["symbol"] == "000003"), "volume"] = 1e12
        revised, _ = apply_dynamic_universe(changed, policy)

        earlier = baseline["date"] < last_date
        self.assertTrue(baseline.loc[earlier, "universe_member"].equals(revised.loc[earlier, "universe_member"]))
        self.assertLessEqual(int(baseline.groupby("date")["universe_member"].sum().max()), 2)
        self.assertFalse(report["uses_future_data"])

    def test_sync_policy_is_validated_and_versionable(self):
        request = SyncCreate(
            source_id="00000000-0000-0000-0000-000000000001",
            symbols=["000001", "000002", "000003"],
            start_date="2020-01-01", end_date="2024-01-01",
            universe_policy=DynamicUniversePolicy(max_members=3),
        )
        self.assertTrue(request.universe_policy.enabled)
        self.assertEqual(request.universe_policy.max_members, 3)

    def test_economic_factor_library_has_behavioral_quality_and_liquidity_proxies(self):
        library = {item["implementation"]: item for item in factor_library_payload()}
        for name in (
            "short_term_reversal", "relative_strength_12_1", "trend_quality",
            "drawdown", "liquidity_trend", "turnover_stability", "volume_price_confirmation",
        ):
            self.assertIn(name, library)
            FeatureCreate(name=name, slug=name, implementation=name, parameters={"window": 20})
        self.assertEqual(library["trend_quality"]["family"], "quality")
        self.assertEqual(library["short_term_reversal"]["family"], "behavioral")

    def test_new_factors_use_only_trailing_price_volume_history(self):
        length = 80
        frame = pd.DataFrame({
            "open": np.linspace(10, 20, length), "high": np.linspace(11, 21, length),
            "low": np.linspace(9, 19, length), "close": np.linspace(10, 20, length),
            "volume": np.linspace(1000, 3000, length),
        })
        for implementation in (
            "short_term_reversal", "trend_quality", "drawdown", "liquidity_trend",
            "turnover_stability", "volume_price_confirmation",
        ):
            values = compute_factor(frame, implementation, {"window": 20})
            self.assertEqual(len(values), length)
            self.assertTrue(values.notna().any(), implementation)

    def test_suspended_zero_volume_does_not_create_infinite_factor_values(self):
        length = 30
        frame = pd.DataFrame({
            "open": np.linspace(10, 12, length), "high": np.linspace(11, 13, length),
            "low": np.linspace(9, 11, length), "close": np.linspace(10, 12, length),
            "volume": [1000] * 20 + [0] + [1000] * 9,
        })

        values = compute_factor(frame, "volume_price_confirmation", {"window": 20})

        self.assertFalse(np.isinf(values).any())
        self.assertTrue(pd.isna(values.iloc[20]))


if __name__ == "__main__":
    unittest.main()
