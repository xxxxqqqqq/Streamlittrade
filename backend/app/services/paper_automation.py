"""Pure policy helpers for the model-to-paper automation boundary."""

from __future__ import annotations

from datetime import date, timedelta
from math import floor
from typing import Any


def snapshot_feature_slugs(lineage: dict[str, Any] | None) -> set[str]:
    definitions = dict(lineage or {}).get("definitions") or []
    return {
        str(item.get("slug"))
        for item in definitions
        if isinstance(item, dict) and item.get("slug")
    }


def snapshot_supports_features(lineage: dict[str, Any] | None, required: list[str]) -> bool:
    return set(required).issubset(snapshot_feature_slugs(lineage))


def next_business_day(signal_date: date) -> date:
    candidate = signal_date + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def build_target_portfolio(
    signals: list[dict[str, Any]],
    prices: dict[str, float],
    equity: float,
    *,
    threshold: float,
    top_n: int,
    gross_exposure: float,
    max_position_ratio: float,
    lot_size: int = 100,
) -> list[dict[str, Any]]:
    """Select by calibrated probability and convert edge weights to board lots."""
    eligible = sorted(
        (
            item for item in signals
            if float(item["probability"]) >= threshold and float(prices.get(str(item["symbol"]), 0)) > 0
        ),
        key=lambda item: (-float(item["probability"]), str(item["symbol"])),
    )[:top_n]
    if not eligible or equity <= 0:
        return []
    edges = [max(float(item["probability"]) - threshold, 1e-9) for item in eligible]
    edge_total = sum(edges)
    targets: list[dict[str, Any]] = []
    for item, edge in zip(eligible, edges):
        symbol = str(item["symbol"])
        price = float(prices[symbol])
        weight = min(gross_exposure * edge / edge_total, max_position_ratio)
        quantity = floor((equity * weight / price) / lot_size) * lot_size
        if quantity <= 0:
            continue
        targets.append({
            "symbol": symbol,
            "probability": round(float(item["probability"]), 8),
            "price": round(price, 4),
            "target_weight": round(quantity * price / equity, 8),
            "target_quantity": quantity,
        })
    return targets
