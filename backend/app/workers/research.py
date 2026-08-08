"""Dataset building and reproducible, leakage-aware model training tasks."""

import hashlib
import io
import platform
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import joblib
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.object_storage import download_bytes, upload_bytes
from backend.app.models.job import Job
from backend.app.models.data_catalog import DataVersion, FactorResearchRun, FeatureSnapshot
from backend.app.models.research import Dataset, Experiment, ModelVersion, PredictionRun, SealedEvaluation
from quant_core import fetch_stock_data, generate_demo_stock_data
from quant_core.ml import FEATURES, build_training_frame, economic_metrics, three_way_research_split
from quant_core.validation import fit_time_ordered_sigmoid, probability_diagnostics
from backend.app.services.research_gates import factor_gate_snapshot, validate_factor_dataset_gate


class TaskCanceled(RuntimeError):
    """Raised at a safe cancellation checkpoint."""


def _build_estimator(algorithm: str, parameters: dict):
    """Construct one of the reviewed, deterministic platform estimators."""
    if algorithm == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(random_state=42, **parameters)
    if algorithm == "random_forest":
        return RandomForestClassifier(random_state=42, n_jobs=-1, **parameters)
    if algorithm == "logistic_regression":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(random_state=42, **parameters),
        )
    raise ValueError(f"Unsupported training algorithm: {algorithm}")


def _check_cancel(job_id: UUID) -> None:
    with SyncSessionFactory() as session:
        job = session.get(Job, job_id)
        if job and job.status == "cancel_requested":
            job.status = "canceled"
            job.completed_at = datetime.now(UTC)
            session.commit()
            raise TaskCanceled("Task canceled by user")


def _fail(job_id: UUID, entity, message: str) -> None:
    with SyncSessionFactory() as session:
        job = session.get(Job, job_id)
        record = session.get(type(entity), entity.id)
        if job:
            job.status = "canceled" if job.status in {"cancel_requested", "canceled"} else "failed"
            job.error_message = message[:2000]
            job.completed_at = datetime.now(UTC)
            job.lease_expires_at = None
        if record:
            record.status = "failed"
            record.error_message = message[:2000]
        session.commit()


def build_dataset(job_id: str) -> dict:
    jid = UUID(job_id)
    with SyncSessionFactory() as session:
        job = session.get(Job, jid)
        dataset = session.get(Dataset, UUID(job.payload["dataset_id"])) if job else None
        if not job or not dataset:
            raise LookupError("Dataset task does not exist")
        job.status, job.progress, job.started_at = "running", 10, datetime.now(UTC)
        job.attempt += 1; job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=15)
        dataset.status = "running"
        session.commit()
        spec = dict(dataset.specification)
    try:
        if spec["data_source"] == "feature_snapshot":
            result, feature_columns, source_metadata = _dataset_from_feature_snapshot(
                dataset.id, dataset.project_id, spec
            )
        else:
            frames = []
            for index, symbol in enumerate(spec["symbols"]):
                _check_cancel(jid)
                if spec["data_source"] == "demo":
                    data = generate_demo_stock_data(
                        pd.Timestamp(spec["start_date"]).date(), pd.Timestamp(spec["end_date"]).date(), seed=42 + index
                    )
                else:
                    data = fetch_stock_data(symbol, spec["start_date"].replace("-", ""), spec["end_date"].replace("-", ""))
                frames.append(build_training_frame(data, symbol, spec["horizon"]))
            result = pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"])
            feature_columns = FEATURES
            source_metadata = {"mode": "legacy_fetch", "data_source": spec["data_source"]}
        _check_cancel(jid)
        research_split = three_way_research_split(
            result["date"],
            training_fraction=float(spec.get("training_fraction", 0.55)),
            tuning_fraction=float(spec.get("tuning_fraction", 0.25)),
            n_tuning_splits=int(spec.get("tuning_folds", 3)),
            purge_days=int(spec["horizon"]),
            embargo_days=int(spec["horizon"]),
        )
        buffer = io.BytesIO()
        result.to_parquet(buffer, index=False)
        payload = buffer.getvalue()
        content_hash = hashlib.sha256(payload).hexdigest()
        uri = upload_bytes(f"datasets/{dataset.id}/{content_hash[:12]}/features.parquet", payload, "application/vnd.apache.parquet")
        metadata = {
            "schema_version": 2,
            "content_sha256": content_hash,
            "features": feature_columns,
            "label": "future_return > 0",
            "horizon": spec["horizon"],
            "symbols": spec["symbols"],
            "date_min": str(pd.to_datetime(result.date).min().date()),
            "date_max": str(pd.to_datetime(result.date).max().date()),
            "created_at": datetime.now(UTC).isoformat(),
            "source": source_metadata,
            "research_protocol": {
                "kind": "train_tune_sealed_v1",
                "training_fraction": float(spec.get("training_fraction", 0.55)),
                "tuning_fraction": float(spec.get("tuning_fraction", 0.25)),
                "sealed_fraction": round(1-float(spec.get("training_fraction", 0.55))-float(spec.get("tuning_fraction", 0.25)), 6),
                "tuning_folds": int(spec.get("tuning_folds", 3)),
                "purge_days": int(spec["horizon"]),
                "embargo_days": int(spec["horizon"]),
                "training": {"start": research_split.training_start, "end": research_split.training_end, "rows": int(len(research_split.training_index))},
                "tuning": {"start": research_split.tuning_start, "end": research_split.tuning_end, "rows": int(sum(len(fold.test_index) for fold in research_split.tuning_folds))},
                "sealed": {"start": research_split.sealed_start, "end": research_split.sealed_end, "rows": int(len(research_split.sealed_index)), "status": "locked"},
            },
        }
        with SyncSessionFactory() as session:
            job, record = session.get(Job, jid), session.get(Dataset, dataset.id)
            record.status, record.row_count, record.feature_count = "ready", len(result), len(feature_columns)
            record.artifact_uri, record.metadata_snapshot = uri, metadata
            job.status, job.progress = "succeeded", 100
            job.result_summary = {"dataset_id": str(record.id), "rows": len(result), "content_sha256": content_hash}
            job.completed_at = datetime.now(UTC); job.lease_expires_at = None
            session.commit()
        return {"dataset_id": str(dataset.id), "artifact_uri": uri, "content_sha256": content_hash}
    except Exception as exc:
        _fail(jid, dataset, str(exc))
        raise


def _dataset_from_feature_snapshot(dataset_id: UUID, project_id: UUID, spec: dict) -> tuple[pd.DataFrame, list[str], dict]:
    """Merge a versioned feature snapshot with labels derived from its exact market-data parent."""
    snapshot_id = UUID(str(spec["feature_snapshot_id"]))
    with SyncSessionFactory() as session:
        snapshot = session.get(FeatureSnapshot, snapshot_id)
        if not snapshot or snapshot.project_id != project_id or snapshot.status != "ready":
            raise LookupError("Ready feature snapshot does not exist in this project")
        version = session.get(DataVersion, snapshot.data_version_id)
        if not version or version.project_id != project_id or version.status != "ready" or version.layer != "standardized":
            raise LookupError("Feature snapshot has no ready standardized parent")
        factor_run = session.get(FactorResearchRun, UUID(str(spec["factor_research_id"])))
        if not factor_run or factor_run.project_id != project_id:
            raise LookupError("Factor research gate does not exist in this project")
        feature_columns = validate_factor_dataset_gate(
            snapshot_id=snapshot.id,
            horizon=int(spec["horizon"]),
            training_fraction=float(spec.get("training_fraction", 0.55)),
            run_snapshot_id=factor_run.snapshot_id,
            run_status=factor_run.status,
            run_parameters=factor_run.parameters,
            run_metrics=factor_run.metrics,
            selected_feature_slugs=factor_run.selected_feature_slugs,
        )
        gate = factor_gate_snapshot(
            run_id=factor_run.id,
            snapshot_id=snapshot.id,
            parameters=dict(factor_run.parameters or {}),
            metrics=dict(factor_run.metrics or {}),
            selected=feature_columns,
        )
        snapshot_uri, version_uri = snapshot.artifact_uri, version.artifact_uri
        snapshot_hash, version_hash = snapshot.content_sha256, version.content_sha256
        lineage = dict(snapshot.lineage or {})
    features = pd.read_parquet(io.BytesIO(download_bytes(snapshot_uri)))
    market = pd.read_parquet(io.BytesIO(download_bytes(version_uri)))
    for frame in (features, market):
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["symbol"] = frame["symbol"].astype(str)
    missing_features = [column for column in feature_columns if column not in features.columns]
    if missing_features:
        raise ValueError(f"Approved factors are missing from snapshot: {', '.join(missing_features)}")
    universe_applied = "universe_member" in features.columns
    if universe_applied:
        features = features[features["universe_member"].fillna(False)].copy()
    features = features[["date", "symbol", *feature_columns]].copy()
    horizon = int(spec["horizon"])
    market = market.sort_values(["symbol", "date"])
    market["future_return"] = market.groupby("symbol")["close"].shift(-horizon) / market["close"] - 1
    market["label"] = (market["future_return"] > 0).where(market["future_return"].notna())
    labels = market[["date", "symbol", "future_return", "label"]]
    result = features.merge(labels, on=["date", "symbol"], how="inner")
    result = result.replace([float("inf"), float("-inf")], pd.NA)
    result = result.dropna(subset=[*feature_columns, "future_return", "label"])
    if result.empty:
        raise ValueError("No trainable rows remain after feature warm-up and label horizon")
    result["label"] = result["label"].astype(int)
    result = result.sort_values(["date", "symbol"]).reset_index(drop=True)
    return result, feature_columns, {
        "mode": "feature_snapshot",
        "feature_snapshot_id": str(snapshot_id),
        "feature_snapshot_sha256": snapshot_hash,
        "data_version_id": str(snapshot.data_version_id),
        "data_version_sha256": version_hash,
        "lineage": lineage,
        "dynamic_universe": {"applied": universe_applied, **dict(lineage.get("dynamic_universe") or {})},
        "factor_gate": gate,
        "dataset_id": str(dataset_id),
    }


def train_experiment(job_id: str) -> dict:
    jid = UUID(job_id)
    with SyncSessionFactory() as session:
        job = session.get(Job, jid)
        experiment = session.get(Experiment, UUID(job.payload["experiment_id"])) if job else None
        dataset = session.get(Dataset, experiment.dataset_id) if experiment else None
        if not job or not experiment or not dataset or dataset.status != "ready":
            raise LookupError("Experiment or ready dataset does not exist")
        job.status, job.progress, job.started_at = "running", 10, datetime.now(UTC)
        job.attempt += 1; job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=15)
        experiment.status = "running"
        session.commit()
        uri, params, algorithm, exp_id = dataset.artifact_uri, dict(experiment.parameters), experiment.algorithm, experiment.id
        dataset_snapshot = dict(dataset.metadata_snapshot or {})
        horizon = int(dataset.specification.get("horizon", 5))
        feature_columns = list(dataset_snapshot.get("features") or FEATURES)
    try:
        frame = pd.read_parquet(io.BytesIO(download_bytes(uri))).sort_values(["date", "symbol"]).reset_index(drop=True)
        _check_cancel(jid)
        protocol = dict(dataset_snapshot.get("research_protocol") or {})
        split = three_way_research_split(
            frame.date,
            training_fraction=float(protocol.get("training_fraction", dataset.specification.get("training_fraction", 0.55))),
            tuning_fraction=float(protocol.get("tuning_fraction", dataset.specification.get("tuning_fraction", 0.25))),
            n_tuning_splits=int(protocol.get("tuning_folds", dataset.specification.get("tuning_folds", 3))),
            purge_days=horizon,
            embargo_days=horizon,
        )
        folds = list(split.tuning_folds)
        fold_metrics, prediction_frames = [], []
        for fold in folds:
            _check_cancel(jid)
            train, test = frame.iloc[fold.train_index], frame.iloc[fold.test_index]
            model = fit_time_ordered_sigmoid(
                lambda: _build_estimator(algorithm, params),
                train[feature_columns], train["label"], train["date"], purge_days=horizon,
            )
            pred, prob = model.predict(test[feature_columns]), model.predict_proba(test[feature_columns])[:, 1]
            raw_prob = model.raw_predict_proba(test[feature_columns])[:, 1]
            fold_calibration = probability_diagnostics(test.label, prob, raw_probability=raw_prob)
            fold_metrics.append({
                "fold": fold.fold, "train_start": fold.train_start, "train_end": fold.train_end,
                "test_start": fold.test_start, "test_end": fold.test_end,
                "train_rows": len(train), "test_rows": len(test),
                "roc_auc": round(float(roc_auc_score(test.label, prob)), 6),
                "balanced_accuracy": round(float(balanced_accuracy_score(test.label, pred)), 6),
                "brier_score": fold_calibration["brier_score"],
                "expected_calibration_error": fold_calibration["expected_calibration_error"],
            })
            scored = test[["date", "symbol", "future_return", "label"]].copy()
            scored["prediction"], scored["raw_probability"], scored["probability"] = pred, raw_prob, prob
            prediction_frames.append(scored)
        predictions = pd.concat(prediction_frames, ignore_index=True)
        y_true, y_pred, probability = predictions.label, predictions.prediction, predictions.probability
        metrics = {
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 6),
            "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 6),
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 6),
            "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 6),
            "roc_auc": round(float(roc_auc_score(y_true, probability)), 6),
            "calibration": probability_diagnostics(y_true, probability, raw_probability=predictions.raw_probability),
            "train_rows": int(fold_metrics[-1]["train_rows"]), "test_rows": len(predictions),
            "split": "three_way_purged_walk_forward", "evaluation_scope": "tuning_oos",
            "sealed_status": "locked", "purge_days": horizon, "embargo_days": horizon,
            "research_split": protocol or {
                "kind": "train_tune_sealed_v1",
                "training": {"start": split.training_start, "end": split.training_end},
                "tuning": {"start": split.tuning_start, "end": split.tuning_end},
                "sealed": {"start": split.sealed_start, "end": split.sealed_end, "status": "locked"},
            },
            "folds": fold_metrics,
            **economic_metrics(predictions, horizon=horizon),
        }
        explanation=permutation_importance(
            model,
            test[feature_columns],
            test["label"],
            n_repeats=5,
            random_state=42,
            scoring="balanced_accuracy",
        )
        metrics["feature_importance"]=[
            {
                "feature":feature,
                "importance_mean":round(float(importance_mean),8),
                "importance_std":round(float(importance_std),8),
            }
            for feature,importance_mean,importance_std in sorted(
                zip(feature_columns,explanation.importances_mean,explanation.importances_std),
                key=lambda item:item[1],
                reverse=True,
            )
        ]
        development = frame.iloc[split.development_index]
        final_model = fit_time_ordered_sigmoid(
            lambda: _build_estimator(algorithm, params),
            development[feature_columns], development["label"], development["date"], purge_days=horizon,
        )
        reproducibility = {
            "schema_version": 1, "random_seed": 42, "dataset": dataset_snapshot,
            "algorithm": algorithm, "parameters": params, "features": feature_columns,
            "python_version": platform.python_version(), "sklearn_version": sklearn.__version__,
            "trained_at": datetime.now(UTC).isoformat(),
            "fit_scope": "training_plus_tuning_only",
            "fit_end": split.tuning_end,
            "sealed_start": split.sealed_start,
        }
        output = io.BytesIO()
        joblib.dump({"model": final_model, "features": feature_columns, "metrics": metrics, "reproducibility": reproducibility}, output)
        model_payload = output.getvalue()
        reproducibility["model_sha256"] = hashlib.sha256(model_payload).hexdigest()
        model_id = uuid4()
        model_uri = upload_bytes(f"models/{model_id}/{reproducibility['model_sha256'][:12]}/model.joblib", model_payload, "application/octet-stream")
        prediction_output = io.BytesIO()
        predictions.to_parquet(prediction_output, index=False)
        prediction_payload = prediction_output.getvalue()
        prediction_hash = hashlib.sha256(prediction_payload).hexdigest()
        prediction_uri = upload_bytes(
            f"models/{model_id}/{prediction_hash[:12]}/oos_predictions.parquet",
            prediction_payload,
            "application/vnd.apache.parquet",
        )
        reproducibility["prediction_sha256"] = prediction_hash
        with SyncSessionFactory() as session:
            job, record = session.get(Job, jid), session.get(Experiment, exp_id)
            record.status, record.metrics, record.reproducibility = "succeeded", metrics, reproducibility
            session.add(ModelVersion(
                id=model_id, experiment_id=exp_id, name=record.name, algorithm=record.algorithm,
                artifact_uri=model_uri, prediction_artifact_uri=prediction_uri,
                metrics=metrics, reproducibility=reproducibility, stage="candidate",
            ))
            job.status, job.progress = "succeeded", 100
            job.result_summary = {"experiment_id": str(exp_id), "model_id": str(model_id), **{k: v for k, v in metrics.items() if not isinstance(v, list)}}
            job.completed_at = datetime.now(UTC); job.lease_expires_at = None
            session.commit()
        return {"model_id": str(model_id), "metrics": metrics}
    except Exception as exc:
        _fail(jid, experiment, str(exc))
        raise


def evaluate_sealed_model(job_id: str) -> dict:
    """Open the final holdout exactly once for the dataset's selected model."""
    jid = UUID(job_id)
    with SyncSessionFactory() as session:
        job = session.get(Job, jid)
        evaluation = session.get(SealedEvaluation, UUID(job.payload["sealed_evaluation_id"])) if job else None
        model = session.get(ModelVersion, evaluation.model_id) if evaluation else None
        experiment = session.get(Experiment, model.experiment_id) if model else None
        dataset = session.get(Dataset, evaluation.dataset_id) if evaluation else None
        if not job or not evaluation or not model or not experiment or not dataset or dataset.status != "ready":
            raise LookupError("Sealed evaluation resources do not exist")
        job.status, job.progress, job.started_at = "running", 10, datetime.now(UTC)
        job.attempt += 1; job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=15)
        evaluation.status = "running"
        session.commit()
        evaluation_id = evaluation.id
    try:
        frame = pd.read_parquet(io.BytesIO(download_bytes(dataset.artifact_uri))).sort_values(["date", "symbol"]).reset_index(drop=True)
        bundle = joblib.load(io.BytesIO(download_bytes(model.artifact_uri)))
        features = list(bundle["features"])
        protocol = dict((dataset.metadata_snapshot or {}).get("research_protocol") or {})
        horizon = int(dataset.specification.get("horizon", 5))
        split = three_way_research_split(
            frame.date,
            training_fraction=float(protocol.get("training_fraction", dataset.specification.get("training_fraction", 0.55))),
            tuning_fraction=float(protocol.get("tuning_fraction", dataset.specification.get("tuning_fraction", 0.25))),
            n_tuning_splits=int(protocol.get("tuning_folds", dataset.specification.get("tuning_folds", 3))),
            purge_days=horizon,
            embargo_days=horizon,
        )
        sealed = frame.iloc[split.sealed_index].copy()
        estimator = bundle["model"]
        sealed["prediction"] = estimator.predict(sealed[features])
        sealed["raw_probability"] = (
            estimator.raw_predict_proba(sealed[features])[:, 1]
            if hasattr(estimator, "raw_predict_proba") else estimator.predict_proba(sealed[features])[:, 1]
        )
        sealed["probability"] = estimator.predict_proba(sealed[features])[:, 1]
        metrics = {
            "evaluation_scope": "final_sealed_holdout",
            "sealed_start": split.sealed_start,
            "sealed_end": split.sealed_end,
            "sealed_rows": int(len(sealed)),
            "accuracy": round(float(accuracy_score(sealed.label, sealed.prediction)), 6),
            "balanced_accuracy": round(float(balanced_accuracy_score(sealed.label, sealed.prediction)), 6),
            "precision": round(float(precision_score(sealed.label, sealed.prediction, zero_division=0)), 6),
            "recall": round(float(recall_score(sealed.label, sealed.prediction, zero_division=0)), 6),
            "roc_auc": round(float(roc_auc_score(sealed.label, sealed.probability)), 6),
            "calibration": probability_diagnostics(
                sealed.label, sealed.probability, raw_probability=sealed.raw_probability
            ),
            **economic_metrics(sealed, horizon=horizon),
        }
        output = io.BytesIO()
        sealed[["date", "symbol", "future_return", "label", "prediction", "raw_probability", "probability"]].to_parquet(output, index=False)
        payload = output.getvalue()
        content_hash = hashlib.sha256(payload).hexdigest()
        uri = upload_bytes(
            f"sealed-evaluations/{evaluation_id}/{content_hash[:12]}/predictions.parquet",
            payload,
            "application/vnd.apache.parquet",
        )
        with SyncSessionFactory() as session:
            job = session.get(Job, jid)
            record = session.get(SealedEvaluation, evaluation_id)
            registered_model = session.get(ModelVersion, model.id)
            record.status, record.metrics = "succeeded", metrics
            record.artifact_uri, record.content_sha256 = uri, content_hash
            registered_model.metrics = {
                **dict(registered_model.metrics or {}),
                "sealed_status": "opened",
                "sealed_evaluation": {"id": str(record.id), **metrics, "content_sha256": content_hash},
            }
            job.status, job.progress = "succeeded", 100
            job.result_summary = {"sealed_evaluation_id": str(record.id), "model_id": str(model.id), **metrics}
            job.completed_at = datetime.now(UTC); job.lease_expires_at = None
            session.commit()
        return job.result_summary
    except Exception as exc:
        _fail(jid, evaluation, str(exc))
        raise


def run_batch_prediction(job_id: str) -> dict:
    """Score an immutable feature snapshot with a registered model artifact."""
    jid=UUID(job_id)
    with SyncSessionFactory() as session:
        job=session.get(Job,jid)
        prediction=session.get(PredictionRun,UUID(job.payload["prediction_id"])) if job else None
        model=session.get(ModelVersion,prediction.model_id) if prediction else None
        experiment=session.get(Experiment,model.experiment_id) if model else None
        snapshot=session.get(FeatureSnapshot,prediction.feature_snapshot_id) if prediction else None
        if not job or not prediction or not model or not experiment or not snapshot:
            raise LookupError("Prediction task resources do not exist")
        if (
            prediction.project_id!=job.project_id
            or snapshot.project_id!=job.project_id
            or experiment.project_id!=job.project_id
        ):
            raise PermissionError("Prediction resources cross project boundary")
        job.status,job.progress,job.started_at="running",10,datetime.now(UTC)
        job.attempt+=1;job.lease_expires_at=datetime.now(UTC)+timedelta(minutes=15)
        prediction.status="running"
        session.commit()
        model_uri,snapshot_uri=model.artifact_uri,snapshot.artifact_uri
        prediction_id=prediction.id
    try:
        bundle=joblib.load(io.BytesIO(download_bytes(model_uri)))
        feature_columns=list(bundle["features"])
        estimator=bundle["model"]
        frame=pd.read_parquet(io.BytesIO(download_bytes(snapshot_uri))).sort_values(["date","symbol"])
        missing=set(feature_columns).difference(frame.columns)
        if missing:raise ValueError(f"Feature snapshot is incompatible with model: {sorted(missing)}")
        score_frame=frame.dropna(subset=feature_columns).copy()
        if score_frame.empty:raise ValueError("Feature snapshot has no scoreable rows")
        _check_cancel(jid)
        score_frame["prediction"]=estimator.predict(score_frame[feature_columns])
        if hasattr(estimator,"predict_proba"):
            score_frame["probability"]=estimator.predict_proba(score_frame[feature_columns])[:,1]
            if hasattr(estimator,"raw_predict_proba"):
                score_frame["raw_probability"]=estimator.raw_predict_proba(score_frame[feature_columns])[:,1]
        else:
            score_frame["probability"]=score_frame["prediction"].astype(float)
        output=score_frame[["date","symbol","prediction","probability"]]
        payload_buffer=io.BytesIO();output.to_parquet(payload_buffer,index=False);payload=payload_buffer.getvalue()
        digest=hashlib.sha256(payload).hexdigest()
        artifact_uri=upload_bytes(
            f"predictions/{prediction_id}/{digest[:12]}/predictions.parquet",
            payload,
            "application/vnd.apache.parquet",
        )
        summary={
            "prediction_id":str(prediction_id),
            "rows":len(output),
            "positive_rate":round(float(output["prediction"].mean()),6),
            "mean_probability":round(float(output["probability"].mean()),6),
            "content_sha256":digest,
        }
        with SyncSessionFactory() as session:
            current_job=session.get(Job,jid);current=session.get(PredictionRun,prediction_id)
            current.status="succeeded";current.artifact_uri=artifact_uri;current.row_count=len(output);current.summary=summary
            current_job.status="succeeded";current_job.progress=100;current_job.result_summary=summary
            current_job.completed_at=datetime.now(UTC);current_job.lease_expires_at=None
            session.commit()
        return summary
    except Exception as exc:
        _fail(jid,prediction,str(exc))
        raise
