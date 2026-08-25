"""Bounded-memory, resumable factor snapshot materialization."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.services.factors import compute_factor


PIPELINE_VERSION = "feature_registry_partitioned_v3"


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class MaterializationResult:
    output_path: Path
    row_count: int
    feature_columns: list[str]
    profile: dict
    resumed_partitions: int
    computed_partitions: int


def definition_fingerprint(data_sha256: str, definitions: Iterable) -> str:
    payload = {
        "pipeline": PIPELINE_VERSION,
        "data_sha256": data_sha256,
        "definitions": [
            {
                "id": str(item.id),
                "slug": item.slug,
                "version": item.version,
                "implementation": item.implementation,
                "parameters": item.parameters,
            }
            for item in definitions
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite(value):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 8)


def _column_stats(values: pd.Series, non_finite_replaced: int) -> dict:
    numeric = values.dropna().to_numpy(dtype="float64", copy=False)
    if numeric.size:
        total = float(numeric.sum(dtype=np.float64))
        square_total = float(np.square(numeric, dtype=np.float64).sum(dtype=np.float64))
        minimum, maximum = float(numeric.min()), float(numeric.max())
    else:
        total = square_total = 0.0
        minimum = maximum = None
    return {
        "rows": int(len(values)),
        "valid": int(numeric.size),
        "sum": total,
        "sum_squares": square_total,
        "min": minimum,
        "max": maximum,
        "non_finite_replaced": int(non_finite_replaced),
    }


def _merge_stats(partitions: list[dict], feature_columns: list[str]) -> dict:
    profile: dict[str, dict] = {}
    for feature in feature_columns:
        rows = sum(part[feature]["rows"] for part in partitions)
        valid = sum(part[feature]["valid"] for part in partitions)
        total = sum(part[feature]["sum"] for part in partitions)
        squares = sum(part[feature]["sum_squares"] for part in partitions)
        minima = [part[feature]["min"] for part in partitions if part[feature]["min"] is not None]
        maxima = [part[feature]["max"] for part in partitions if part[feature]["max"] is not None]
        mean = total / valid if valid else None
        if valid > 1 and mean is not None:
            variance = max(0.0, (squares - valid * mean * mean) / (valid - 1))
            std = math.sqrt(variance)
        else:
            std = None
        profile[feature] = {
            "missing_rate": round(1 - valid / rows, 6) if rows else None,
            "mean": _finite(mean),
            "std": _finite(std),
            "min": _finite(min(minima)) if minima else None,
            "max": _finite(max(maxima)) if maxima else None,
            "non_finite_replaced": sum(
                part[feature]["non_finite_replaced"] for part in partitions
            ),
        }
    return profile


def _valid_completed_partition(checkpoint_dir: Path, item: dict) -> bool:
    path = checkpoint_dir / str(item.get("file", ""))
    return (
        path.is_file()
        and bool(item.get("sha256"))
        and isinstance(item.get("stats"), dict)
        and _sha256_file(path) == item["sha256"]
        and int(pq.ParquetFile(path).metadata.num_rows) == int(item.get("rows", -1))
    )


def _write_partition(
    group: pd.DataFrame,
    definitions: list,
    metadata_columns: list[str],
    path: Path,
) -> tuple[dict[str, dict], int]:
    output = group[metadata_columns].reset_index(drop=True).copy()
    stats: dict[str, dict] = {}
    for definition in definitions:
        values = compute_factor(group, definition.implementation, definition.parameters)
        if not isinstance(values, pd.Series):
            raise ValueError(f"Factor {definition.slug} did not produce a single column")
        values = pd.to_numeric(values.reindex(group.index), errors="coerce")
        non_finite = int(np.isinf(values).sum())
        values = values.replace([np.inf, -np.inf], np.nan).astype("float32")
        output[definition.slug] = values.to_numpy(copy=False)
        stats[definition.slug] = _column_stats(values, non_finite)

    temporary = path.with_name(f".{path.name}.partial")
    output.to_parquet(temporary, index=False, compression="snappy")
    temporary.replace(path)
    return stats, len(output)


def _merge_partitions(checkpoint_dir: Path, ordered: list[dict], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.partial")
    temporary.unlink(missing_ok=True)
    writer = None
    rows = 0
    try:
        for item in ordered:
            parquet = pq.ParquetFile(checkpoint_dir / item["file"])
            for batch in parquet.iter_batches(batch_size=65536):
                table = pa.Table.from_batches([batch])
                if writer is None:
                    writer = pq.ParquetWriter(temporary, table.schema, compression="snappy")
                writer.write_table(table)
                rows += table.num_rows
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        raise ValueError("Feature materialization produced no rows")
    temporary.replace(output_path)
    return rows


def materialize_partitioned_snapshot(
    source_path: Path,
    output_path: Path,
    checkpoint_dir: Path,
    definitions: list,
    fingerprint: str,
    dynamic_universe: dict,
    progress: Callable[[float], None] | None = None,
) -> MaterializationResult:
    """Compute all factors one symbol at a time with durable checkpoints."""

    frame = pd.read_parquet(source_path)
    required = {"date", "symbol"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Standardized data is missing required columns: {sorted(missing)}")
    frame.sort_values(["symbol", "date"], inplace=True)
    frame["symbol"] = frame["symbol"].astype(str)
    feature_columns = [item.slug for item in definitions]
    if len(feature_columns) != len(set(feature_columns)):
        raise ValueError("Feature snapshot contains duplicate factor slugs")
    metadata_columns = [
        item for item in ("date", "symbol", "universe_member", "universe_rank")
        if item in frame.columns
    ]
    symbols = list(frame["symbol"].drop_duplicates())
    manifest_path = checkpoint_dir / "manifest.json"
    manifest = _read_json(
        manifest_path,
        {
            "pipeline": PIPELINE_VERSION,
            "fingerprint": fingerprint,
            "feature_columns": feature_columns,
            "completed": {},
        },
    )
    if (
        manifest.get("pipeline") != PIPELINE_VERSION
        or manifest.get("fingerprint") != fingerprint
        or manifest.get("feature_columns") != feature_columns
    ):
        raise ValueError("Checkpoint manifest does not match the immutable task fingerprint")

    completed: dict[str, dict] = dict(manifest.get("completed") or {})
    ordered: list[dict] = []
    resumed = computed = 0
    grouped = frame.groupby("symbol", sort=False, observed=True)
    for index, symbol in enumerate(symbols):
        key = str(symbol)
        existing = completed.get(key)
        if existing and _valid_completed_partition(checkpoint_dir, existing):
            item = existing
            resumed += 1
        else:
            group = grouped.get_group(symbol)
            token = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
            filename = f"part-{index:05d}-{token}.parquet"
            part_path = checkpoint_dir / filename
            stats, rows = _write_partition(group, definitions, metadata_columns, part_path)
            item = {
                "file": filename,
                "rows": rows,
                "sha256": _sha256_file(part_path),
                "stats": stats,
            }
            completed[key] = item
            manifest["completed"] = completed
            _atomic_json(manifest_path, manifest)
            computed += 1
        ordered.append(item)
        if progress:
            progress(10 + 70 * (index + 1) / max(1, len(symbols)))

    if progress:
        progress(84)
    row_count = _merge_partitions(checkpoint_dir, ordered, output_path)
    partition_stats = [item["stats"] for item in ordered]
    features = _merge_stats(partition_stats, feature_columns)
    warnings = [
        {
            "code": "non_finite_replaced",
            "feature": slug,
            "count": values["non_finite_replaced"],
            "message": "非有限因子值已转为空值",
        }
        for slug, values in features.items()
        if values["non_finite_replaced"]
    ]
    profile = {
        "features": features,
        "date_min": str(pd.to_datetime(frame["date"]).min().date()),
        "date_max": str(pd.to_datetime(frame["date"]).max().date()),
        "dynamic_universe": dynamic_universe,
        "warnings": warnings,
        "materialization": {
            "pipeline": PIPELINE_VERSION,
            "partitions": len(ordered),
            "resumed_partitions": resumed,
            "computed_partitions": computed,
        },
    }
    del frame
    if progress:
        progress(90)
    return MaterializationResult(
        output_path=output_path,
        row_count=row_count,
        feature_columns=feature_columns,
        profile=profile,
        resumed_partitions=resumed,
        computed_partitions=computed,
    )
