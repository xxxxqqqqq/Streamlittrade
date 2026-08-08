"""Live-trading safety policy and an intentionally disabled broker boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


POLICY_VERSION = "paper_stability_v1"


def evaluate_paper_stability(stats: dict[str, Any]) -> dict[str, Any]:
    requirements = {
        "successful_runs": (int(stats.get("successful_runs", 0)), 20, "gte"),
        "observation_days": (int(stats.get("observation_days", 0)), 30, "gte"),
        "success_rate": (float(stats.get("success_rate", 0)), 0.95, "gte"),
        "unreviewed_proposals": (int(stats.get("unreviewed_proposals", 0)), 0, "eq"),
        "open_critical_alerts": (int(stats.get("open_critical_alerts", 0)), 0, "eq"),
        "production_model_reliable": (bool(stats.get("production_model_reliable", False)), True, "eq"),
        "credential_reference_valid": (bool(stats.get("credential_reference_valid", False)), True, "eq"),
        "dry_run_only": (bool(stats.get("dry_run_only", False)), True, "eq"),
    }
    checks = {}
    for name, (actual, required, operator) in requirements.items():
        passed = actual >= required if operator == "gte" else actual == required
        checks[name] = {"passed": passed, "actual": actual, "required": required, "operator": operator}
    return {"eligible": all(item["passed"] for item in checks.values()), "checks": checks, "policy_version": POLICY_VERSION}


class LiveTradingDisabled(RuntimeError):
    pass


class BrokerAdapter(Protocol):
    def preview(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
    def submit(self, orders: list[dict[str, Any]]) -> None: ...


@dataclass(frozen=True)
class DisabledBrokerAdapter:
    """Canonical adapter used until a provider is selected and separately implemented."""

    provider: str

    def preview(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**order, "provider": self.provider, "dry_run": True, "transmitted": False} for order in orders]

    def submit(self, orders: list[dict[str, Any]]) -> None:
        raise LiveTradingDisabled("Real broker submission is not implemented or authorized")


def broker_adapter(provider: str) -> BrokerAdapter:
    return DisabledBrokerAdapter(provider=provider)
