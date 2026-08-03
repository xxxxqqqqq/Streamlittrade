"""Asynchronous model drift monitoring tasks."""

import io
from datetime import UTC, datetime, timedelta
from uuid import UUID

import joblib
import pandas as pd

from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.object_storage import download_bytes
from backend.app.models.data_catalog import FeatureSnapshot
from backend.app.models.job import Job
from backend.app.models.operations import AlertEvent, DriftRun
from backend.app.models.research import ModelVersion
from quant_core.monitoring import population_stability_index, standardized_mean_shift


def _fail(job_id: UUID, run_id: UUID, message: str) -> None:
    with SyncSessionFactory() as session:
        job, run = session.get(Job, job_id), session.get(DriftRun, run_id)
        if job:
            job.status = "failed"
            job.error_message = message[:2000]
            job.completed_at = datetime.now(UTC)
            job.lease_expires_at = None
        if run:
            run.status = "failed"
            run.error_message = message[:2000]
        session.commit()


def run_drift_monitor(job_id: str) -> dict:
    """Compare model inputs and score distributions across immutable snapshots."""
    jid = UUID(job_id)
    with SyncSessionFactory() as session:
        job = session.get(Job, jid)
        run = (
            session.get(DriftRun, UUID(job.payload["drift_run_id"])) if job else None
        )
        model = session.get(ModelVersion, run.model_id) if run else None
        baseline = (
            session.get(FeatureSnapshot, run.baseline_snapshot_id) if run else None
        )
        current = (
            session.get(FeatureSnapshot, run.current_snapshot_id) if run else None
        )
        if not job or not run or not model or not baseline or not current:
            raise LookupError("Drift monitoring resources do not exist")
        if (
            run.project_id != job.project_id
            or baseline.project_id != job.project_id
            or current.project_id != job.project_id
        ):
            raise PermissionError("Drift monitoring resources cross project boundary")
        job.status, job.progress, job.started_at = "running", 10, datetime.now(UTC)
        job.attempt += 1
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=15)
        run.status = "running"
        session.commit()
        run_id = run.id
        model_uri = model.artifact_uri
        baseline_uri, current_uri = baseline.artifact_uri, current.artifact_uri
    try:
        bundle = joblib.load(io.BytesIO(download_bytes(model_uri)))
        estimator, features = bundle["model"], list(bundle["features"])
        reference = pd.read_parquet(io.BytesIO(download_bytes(baseline_uri)))
        observed = pd.read_parquet(io.BytesIO(download_bytes(current_uri)))
        missing_reference = set(features).difference(reference.columns)
        missing_current = set(features).difference(observed.columns)
        if missing_reference or missing_current:
            raise ValueError(
                f"Incompatible snapshot features: baseline={sorted(missing_reference)}, "
                f"current={sorted(missing_current)}"
            )
        feature_metrics = []
        for feature in features:
            feature_metrics.append(
                {
                    "feature": feature,
                    "psi": round(
                        population_stability_index(
                            reference[feature], observed[feature]
                        ),
                        6,
                    ),
                    "mean_shift_std": round(
                        standardized_mean_shift(
                            reference[feature], observed[feature]
                        ),
                        6,
                    ),
                    "missing_rate_delta": round(
                        abs(
                            float(observed[feature].isna().mean())
                            - float(reference[feature].isna().mean())
                        ),
                        6,
                    ),
                }
            )
        reference_score_frame = reference.dropna(subset=features)
        current_score_frame = observed.dropna(subset=features)
        reference_prob = pd.Series(
            estimator.predict_proba(reference_score_frame[features])[:, 1]
        )
        current_prob = pd.Series(
            estimator.predict_proba(current_score_frame[features])[:, 1]
        )
        score_psi = population_stability_index(reference_prob, current_prob)
        max_feature_psi = max((item["psi"] for item in feature_metrics), default=0.0)
        max_mean_shift = max(
            (item["mean_shift_std"] for item in feature_metrics), default=0.0
        )
        if max_feature_psi >= 0.25 or score_psi >= 0.25 or max_mean_shift >= 2:
            level = "critical"
        elif max_feature_psi >= 0.1 or score_psi >= 0.1 or max_mean_shift >= 1:
            level = "warning"
        else:
            level = "none"
        metrics = {
            "reference_rows": len(reference),
            "current_rows": len(observed),
            "feature_count": len(features),
            "max_feature_psi": round(max_feature_psi, 6),
            "max_mean_shift_std": round(max_mean_shift, 6),
            "score_psi": round(score_psi, 6),
            "reference_mean_probability": round(float(reference_prob.mean()), 6),
            "current_mean_probability": round(float(current_prob.mean()), 6),
            "features": sorted(
                feature_metrics, key=lambda item: item["psi"], reverse=True
            ),
            "thresholds": {
                "warning_psi": 0.1,
                "critical_psi": 0.25,
                "warning_mean_shift_std": 1.0,
                "critical_mean_shift_std": 2.0,
            },
        }
        with SyncSessionFactory() as session:
            job, run = session.get(Job, jid), session.get(DriftRun, run_id)
            run.status, run.alert_level, run.metrics = "succeeded", level, metrics
            job.status, job.progress = "succeeded", 100
            job.result_summary = {
                "drift_run_id": str(run_id),
                "alert_level": level,
                "max_feature_psi": metrics["max_feature_psi"],
                "score_psi": metrics["score_psi"],
            }
            job.completed_at = datetime.now(UTC)
            job.lease_expires_at = None
            if level != "none":
                session.add(
                    AlertEvent(
                        project_id=run.project_id,
                        drift_run_id=run.id,
                        code="MODEL_INPUT_DRIFT",
                        severity=level,
                        title="生产模型输入分布发生漂移",
                        message=(
                            f"最大特征 PSI={metrics['max_feature_psi']}, "
                            f"预测分数 PSI={metrics['score_psi']}"
                        ),
                        details=metrics,
                    )
                )
            session.commit()
        return metrics
    except Exception as exc:
        _fail(jid, run_id, str(exc))
        raise
