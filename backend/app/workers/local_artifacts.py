"""Verified worker-local cache and resumable task directory helpers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from backend.app.core.config import get_settings
from backend.app.infrastructure.object_storage import download_file, sha256_file


def worker_data_root() -> Path:
    root = get_settings().worker_data_dir.expanduser().resolve()
    for name in ("cache", "checkpoints", "staging", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def cached_artifact(uri: str, expected_sha256: str | None, suffix: str = ".parquet") -> Path:
    """Return a verified immutable local copy, downloading only when needed."""

    key = expected_sha256 or hashlib.sha256(uri.encode("utf-8")).hexdigest()
    target = worker_data_root() / "cache" / f"{key}{suffix}"
    if target.exists() and (not expected_sha256 or sha256_file(target) == expected_sha256):
        return target
    download_file(uri, target)
    if expected_sha256 and sha256_file(target) != expected_sha256:
        target.unlink(missing_ok=True)
        raise ValueError("Downloaded artifact SHA-256 does not match its immutable data version")
    return target


def promote_cached_artifact(
    source: str | Path,
    expected_sha256: str,
    suffix: str = ".parquet",
) -> Path:
    """Make a verified generated artifact immediately reusable by later jobs."""

    source_path = Path(source)
    if sha256_file(source_path) != expected_sha256:
        raise ValueError("Generated artifact SHA-256 changed before cache promotion")
    target = worker_data_root() / "cache" / f"{expected_sha256}{suffix}"
    if target.exists() and sha256_file(target) == expected_sha256:
        return target
    temporary = target.with_name(f".{target.name}.partial")
    temporary.unlink(missing_ok=True)
    try:
        os.link(source_path, temporary)
    except OSError:
        shutil.copy2(source_path, temporary)
    temporary.replace(target)
    return target


def task_checkpoint_dir(task_id: str, fingerprint: str) -> Path:
    """Create a path scoped to an immutable task/fingerprint pair."""

    safe_task = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_")
    safe_fingerprint = "".join(ch for ch in fingerprint if ch.isalnum())[:24]
    if not safe_task or not safe_fingerprint:
        raise ValueError("Invalid checkpoint identity")
    path = worker_data_root() / "checkpoints" / safe_task / safe_fingerprint
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else dict(default)
    return json.loads(path.read_text(encoding="utf-8"))
