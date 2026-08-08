"""Statistical validation and probability-calibration primitives."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.base import BaseEstimator, ClassifierMixin
from scipy.stats import t as student_t


def benjamini_hochberg(p_values: dict[str, float | None]) -> dict[str, float | None]:
    """Control false discovery rate while preserving factor identifiers."""
    valid = sorted(
        ((key, float(value)) for key, value in p_values.items() if value is not None and isfinite(float(value))),
        key=lambda item: item[1],
    )
    adjusted: dict[str, float | None] = {key: None for key in p_values}
    running = 1.0
    count = len(valid)
    for rank_index in range(count - 1, -1, -1):
        key, value = valid[rank_index]
        rank = rank_index + 1
        running = min(running, value * count / rank)
        adjusted[key] = round(min(1.0, running), 10)
    return adjusted


def mean_significance(values) -> dict:
    """Two-sided one-sample t-test for a daily IC series."""
    sample = np.asarray(values, dtype=float)
    sample = sample[np.isfinite(sample)]
    observations = int(sample.size)
    if observations < 2:
        return {"observations": observations, "t_stat": None, "p_value": None}
    standard_deviation = float(sample.std(ddof=1))
    if standard_deviation == 0:
        return {"observations": observations, "t_stat": None, "p_value": None}
    t_stat = float(sample.mean() / (standard_deviation / np.sqrt(observations)))
    p_value = float(2 * student_t.sf(abs(t_stat), df=observations - 1))
    return {"observations": observations, "t_stat": round(t_stat, 8), "p_value": round(p_value, 10)}


def probability_diagnostics(y_true, probability, *, raw_probability=None, n_bins: int = 10) -> dict:
    """Return proper scoring rules and an auditable reliability diagram."""
    truth = np.asarray(y_true, dtype=int)
    calibrated = np.clip(np.asarray(probability, dtype=float), 1e-6, 1 - 1e-6)
    raw = calibrated if raw_probability is None else np.clip(np.asarray(raw_probability, dtype=float), 1e-6, 1 - 1e-6)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    indices = np.minimum(np.digitize(calibrated, edges[1:-1], right=True), n_bins - 1)
    bins = []
    ece = 0.0
    for index in range(n_bins):
        mask = indices == index
        if not mask.any():
            continue
        predicted = float(calibrated[mask].mean())
        observed = float(truth[mask].mean())
        weight = float(mask.mean())
        ece += weight * abs(predicted - observed)
        bins.append({
            "lower": round(float(edges[index]), 4),
            "upper": round(float(edges[index + 1]), 4),
            "count": int(mask.sum()),
            "mean_probability": round(predicted, 6),
            "observed_frequency": round(observed, 6),
        })
    return {
        "method": "time_ordered_sigmoid",
        "brier_score": round(float(brier_score_loss(truth, calibrated)), 6),
        "raw_brier_score": round(float(brier_score_loss(truth, raw)), 6),
        "log_loss": round(float(log_loss(truth, calibrated, labels=[0, 1])), 6),
        "raw_log_loss": round(float(log_loss(truth, raw, labels=[0, 1])), 6),
        "expected_calibration_error": round(float(ece), 6),
        "bins": bins,
    }


@dataclass
class SigmoidCalibratedEstimator(ClassifierMixin, BaseEstimator):
    """Pickle-safe estimator wrapper retaining raw and calibrated probabilities."""

    estimator: object
    calibrator: LogisticRegression

    @property
    def classes_(self):
        return np.array([0, 1])

    def raw_predict_proba(self, features):
        return self.estimator.predict_proba(features)

    def predict_proba(self, features):
        raw = np.clip(self.raw_predict_proba(features)[:, 1], 1e-6, 1 - 1e-6)
        log_odds = np.log(raw / (1 - raw)).reshape(-1, 1)
        calibrated = self.calibrator.predict_proba(log_odds)[:, 1]
        return np.column_stack([1 - calibrated, calibrated])

    def predict(self, features):
        return (self.predict_proba(features)[:, 1] >= .5).astype(int)

    def fit(self, features, labels):
        raise RuntimeError("Use fit_time_ordered_sigmoid to preserve the calibration boundary")


def fit_time_ordered_sigmoid(
    estimator_factory: Callable[[], object],
    features,
    labels,
    dates,
    *,
    calibration_fraction: float = .2,
    purge_days: int = 5,
) -> SigmoidCalibratedEstimator:
    """Learn a sigmoid on a later calibration slice, then refit the base on all input dates."""
    normalized = pd.to_datetime(pd.Series(dates)).dt.normalize()
    unique_dates = np.array(sorted(normalized.unique()))
    boundary = int(len(unique_dates) * (1 - calibration_fraction))
    fit_dates = unique_dates[: max(0, boundary - purge_days)]
    calibration_dates = unique_dates[boundary:]
    fit_mask = normalized.isin(fit_dates).to_numpy()
    calibration_mask = normalized.isin(calibration_dates).to_numpy()
    if fit_mask.sum() < 20 or calibration_mask.sum() < 20:
        raise ValueError("Not enough observations for time-ordered probability calibration")
    calibration_labels = np.asarray(labels)[calibration_mask]
    if np.unique(calibration_labels).size < 2:
        raise ValueError("Probability calibration slice must contain both classes")
    calibration_base = estimator_factory()
    calibration_base.fit(features.iloc[fit_mask], np.asarray(labels)[fit_mask])
    raw = np.clip(calibration_base.predict_proba(features.iloc[calibration_mask])[:, 1], 1e-6, 1 - 1e-6)
    log_odds = np.log(raw / (1 - raw)).reshape(-1, 1)
    calibrator = LogisticRegression(random_state=42, C=1.0, max_iter=500)
    calibrator.fit(log_odds, calibration_labels)
    final_base = estimator_factory()
    final_base.fit(features, labels)
    return SigmoidCalibratedEstimator(final_base, calibrator)
