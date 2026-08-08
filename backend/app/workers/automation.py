"""Auditable latest-snapshot to reviewable paper-order proposal worker."""

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import joblib
import pandas as pd

from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.object_storage import download_bytes
from backend.app.models.data_catalog import DataVersion, FeatureSnapshot
from backend.app.models.identity import AuditLog
from backend.app.models.job import Job
from backend.app.models.operations import PaperAutomationRun, PaperAutomationSchedule
from backend.app.models.paper import PaperAccount, PaperOrder, PaperPosition
from backend.app.models.research import ModelVersion
from backend.app.services.paper_automation import build_target_portfolio, next_business_day


def run_paper_automation(job_id: str) -> dict:
    jid = UUID(job_id)
    with SyncSessionFactory() as session:
        job = session.get(Job, jid)
        run = session.get(PaperAutomationRun, UUID(job.payload["paper_automation_run_id"])) if job else None
        schedule = session.get(PaperAutomationSchedule, run.schedule_id) if run else None
        account = session.get(PaperAccount, run.account_id) if run else None
        model = session.get(ModelVersion, run.model_id) if run else None
        snapshot = session.get(FeatureSnapshot, run.feature_snapshot_id) if run else None
        version = session.get(DataVersion, snapshot.data_version_id) if snapshot else None
        if not all((job, run, schedule, account, model, snapshot, version)):
            raise LookupError("Paper automation resources do not exist")
        boundaries = (job.project_id, schedule.project_id, account.project_id, snapshot.project_id, version.project_id)
        if any(project_id != run.project_id for project_id in boundaries):
            raise PermissionError("Paper automation resources cross project boundary")
        if account.status != "active" or model.stage != "production" or snapshot.status != "ready" or version.status != "ready":
            raise ValueError("Paper automation requires active account, production model and ready immutable data")
        job.status, job.progress, job.started_at = "running", 10, datetime.now(UTC)
        job.attempt += 1
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=15)
        run.status = "running"
        session.commit()
        run_id, owner_id, account_id = run.id, schedule.owner_id, account.id
        config = {"top_n": schedule.top_n, "threshold": schedule.probability_threshold, "gross_exposure": schedule.gross_exposure}
        positions = {item.symbol: item for item in session.query(PaperPosition).filter(PaperPosition.account_id == account.id).all()}
        cash, risk_limits = float(account.cash), dict(account.risk_limits or {})
        model_uri, snapshot_uri, market_uri = model.artifact_uri, snapshot.artifact_uri, version.artifact_uri
        hashes = {"model": (model.reproducibility or {}).get("model_sha256"), "snapshot": snapshot.content_sha256, "data": version.content_sha256}
        ids = {"model_id": str(model.id), "model_version": model.version, "snapshot_id": str(snapshot.id), "data_version_id": str(version.id)}
    try:
        bundle = joblib.load(io.BytesIO(download_bytes(model_uri)))
        estimator, features = bundle["model"], list(bundle["features"])
        if not hasattr(estimator, "raw_predict_proba"):
            raise ValueError("Production model artifact lacks the required time-ordered probability calibration")
        feature_frame = pd.read_parquet(io.BytesIO(download_bytes(snapshot_uri)))
        market_frame = pd.read_parquet(io.BytesIO(download_bytes(market_uri)))
        missing = set(features).difference(feature_frame.columns)
        if missing:
            raise ValueError(f"Feature snapshot is incompatible with model: {sorted(missing)}")
        feature_frame["date"] = pd.to_datetime(feature_frame["date"])
        market_frame["date"] = pd.to_datetime(market_frame["date"])
        signal_timestamp = feature_frame["date"].max()
        score = feature_frame.loc[feature_frame["date"] == signal_timestamp].copy()
        if "universe_member" in score.columns:
            score = score.loc[score["universe_member"].fillna(False).astype(bool)]
        score = score.dropna(subset=features)
        if score.empty:
            raise ValueError("Latest snapshot date has no scoreable universe members")
        score["probability"] = estimator.predict_proba(score[features])[:, 1]
        if hasattr(estimator, "raw_predict_proba"):
            score["raw_probability"] = estimator.raw_predict_proba(score[features])[:, 1]
        market_day = market_frame.loc[market_frame["date"] == signal_timestamp, ["symbol", "close"]].dropna()
        prices = {str(row.symbol): float(row.close) for row in market_day.itertuples() if float(row.close) > 0}
        signals = [
            {"symbol": str(row.symbol), "probability": round(float(row.probability), 8), **({"raw_probability": round(float(row.raw_probability), 8)} if hasattr(row, "raw_probability") else {})}
            for row in score.sort_values(["probability", "symbol"], ascending=[False, True]).itertuples()
            if str(row.symbol) in prices
        ]
        equity = cash + sum(item.quantity * prices.get(symbol, float(item.last_price)) for symbol, item in positions.items())
        max_position_ratio = min(float(risk_limits.get("max_position_ratio", 0.30)), 1.0)
        targets = build_target_portfolio(signals, prices, equity, threshold=config["threshold"], top_n=config["top_n"], gross_exposure=config["gross_exposure"], max_position_ratio=max_position_ratio)
        signal_date = signal_timestamp.date()
        trade_date = next_business_day(signal_date)
        target_quantities = {item["symbol"]: item["target_quantity"] for item in targets}
        proposals = []
        for symbol in sorted(set(positions).union(target_quantities)):
            current = positions[symbol].quantity if symbol in positions else 0
            delta = target_quantities.get(symbol, 0) - current
            if delta and symbol in prices:
                proposals.append((0 if delta < 0 else 1, symbol, "sell" if delta < 0 else "buy", abs(delta)))
        proposals.sort()
        order_ids: list[str] = []
        with SyncSessionFactory() as session:
            current_job, current_run = session.get(Job, jid), session.get(PaperAutomationRun, run_id)
            for _, symbol, side, quantity in proposals:
                order = PaperOrder(id=uuid4(), account_id=account_id, symbol=symbol, side=side, quantity=quantity, snapshot_price=Decimal(str(round(prices[symbol], 4))), status="proposed", trade_date=trade_date, source="model_automation", message=f"信号日 {signal_date.isoformat()}；拟成交日 {trade_date.isoformat()}；待人工复核")
                session.add(order)
                order_ids.append(str(order.id))
            lineage = {**ids, "hashes": hashes, "features": features, "probability": {"calibrated": True, "method": "time_ordered_sigmoid"}, "selection": {**config, "max_position_ratio": max_position_ratio, "lot_size": 100}, "signal_date": signal_date.isoformat(), "intended_trade_date": trade_date.isoformat(), "execution_policy": "proposal_only_manual_review"}
            current_run.status, current_run.signal_date, current_run.intended_trade_date = "succeeded", signal_date, trade_date
            current_run.signals, current_run.targets, current_run.order_ids, current_run.lineage = signals[:100], targets, order_ids, lineage
            summary = {"run_id": str(run_id), "signal_date": signal_date.isoformat(), "intended_trade_date": trade_date.isoformat(), "selected": len(targets), "proposed_orders": len(order_ids)}
            current_job.status, current_job.progress, current_job.result_summary = "succeeded", 100, summary
            current_job.completed_at, current_job.lease_expires_at = datetime.now(UTC), None
            session.add(AuditLog(actor_id=owner_id, action="paper_automation.proposed", resource_type="paper_automation_run", resource_id=str(run_id), details=summary))
            session.commit()
        return summary
    except Exception as exc:
        with SyncSessionFactory() as session:
            current_job, current_run = session.get(Job, jid), session.get(PaperAutomationRun, run_id)
            if current_job:
                current_job.status, current_job.error_message, current_job.completed_at, current_job.lease_expires_at = "failed", str(exc), datetime.now(UTC), None
            if current_run:
                current_run.status, current_run.error_message = "failed", str(exc)
            session.commit()
        raise
