"""Pure numerical monitoring metrics shared by workers and tests."""

import numpy as np
import pandas as pd


def population_stability_index(reference: pd.Series, current: pd.Series) -> float:
    """Calculate PSI using reference quantiles and stable non-zero proportions."""
    reference_values = pd.to_numeric(reference, errors="coerce").dropna().to_numpy()
    current_values = pd.to_numeric(current, errors="coerce").dropna().to_numpy()
    if len(reference_values) < 2 or len(current_values) < 2:
        return 0.0
    edges = np.unique(np.quantile(reference_values, np.linspace(0, 1, 11)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    reference_hist = np.histogram(reference_values, bins=edges)[0] / len(
        reference_values
    )
    current_hist = np.histogram(current_values, bins=edges)[0] / len(current_values)
    reference_hist = np.clip(reference_hist, 1e-6, None)
    current_hist = np.clip(current_hist, 1e-6, None)
    return float(
        np.sum((current_hist - reference_hist) * np.log(current_hist / reference_hist))
    )


def standardized_mean_shift(reference: pd.Series, current: pd.Series) -> float:
    """Return absolute mean shift measured in reference standard deviations."""
    reference_numeric = pd.to_numeric(reference, errors="coerce")
    current_numeric = pd.to_numeric(current, errors="coerce")
    scale = float(reference_numeric.std())
    if not np.isfinite(scale) or scale < 1e-12:
        return 0.0
    return abs(float(current_numeric.mean() - reference_numeric.mean())) / scale

