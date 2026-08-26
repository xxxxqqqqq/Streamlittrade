"""MinIO/阿里云OSS兼容对象存储适配器。"""

import hashlib
from io import BytesIO
from pathlib import Path
import time
from urllib.parse import urlsplit

from minio import Minio

from backend.app.core.config import get_settings


def _create_client() -> Minio:
    settings = get_settings()
    parsed = urlsplit(settings.object_storage_endpoint)
    endpoint = parsed.netloc or parsed.path
    return Minio(
        endpoint,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        secure=parsed.scheme == "https",
    )


object_storage = _create_client()


def _bucket_and_name(uri: str) -> tuple[str, str]:
    prefix = "s3://"
    if not uri.startswith(prefix):
        raise ValueError("仅支持s3://产物地址")
    return tuple(uri[len(prefix):].split("/", 1))  # type: ignore[return-value]


def _retry(operation):
    attempts = max(1, get_settings().object_storage_retry_attempts)
    for attempt in range(attempts):
        try:
            return operation()
        except Exception:
            if attempt + 1 >= attempts:
                raise
            time.sleep(min(8.0, 0.5 * (2**attempt)))


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def upload_bytes(object_name: str, content: bytes, content_type: str) -> str:
    """上传任意二进制产物并返回稳定的S3 URI。"""
    bucket = get_settings().object_storage_bucket

    def operation():
        if not object_storage.bucket_exists(bucket):
            # minio-init通常已经建桶；这里仍保留幂等兜底以提高Worker可恢复性。
            object_storage.make_bucket(bucket)
        object_storage.put_object(
            bucket,
            object_name,
            BytesIO(content),
            length=len(content),
            content_type=content_type,
        )

    _retry(operation)
    return f"s3://{bucket}/{object_name}"


def upload_file(object_name: str, path: str | Path, content_type: str) -> str:
    """Stream a local file to object storage without duplicating it in RAM."""

    bucket = get_settings().object_storage_bucket

    def operation():
        if not object_storage.bucket_exists(bucket):
            object_storage.make_bucket(bucket)
        object_storage.fput_object(bucket, object_name, str(path), content_type=content_type)

    _retry(operation)
    return f"s3://{bucket}/{object_name}"


def upload_json(object_name: str, content: bytes) -> str:
    return upload_bytes(object_name, content, "application/json; charset=utf-8")


def download_bytes(uri: str) -> bytes:
    """读取平台自身生成的S3 URI。"""
    bucket, object_name = _bucket_and_name(uri)
    def operation():
        response = object_storage.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close(); response.release_conn()

    return _retry(operation)


def stream_bytes(uri: str, chunk_size: int = 1024 * 1024):
    """Stream a platform artifact without buffering it in the API process.

    Dataset downloads can be hundreds of megabytes.  Returning ``bytes`` is
    still useful to worker code that needs an in-memory artifact, but HTTP
    endpoints should use this iterator so the browser receives data as soon
    as MinIO starts responding.
    """
    bucket, object_name = _bucket_and_name(uri)

    def operation():
        return object_storage.get_object(bucket, object_name)

    response = _retry(operation)
    content_length = response.headers.get("Content-Length")

    def chunks():
        try:
            yield from response.stream(chunk_size)
        finally:
            response.close()
            response.release_conn()

    return chunks(), content_length


def download_file(uri: str, destination: str | Path) -> Path:
    """Download atomically to local SSD so interrupted transfers are harmless."""

    bucket, object_name = _bucket_and_name(uri)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.partial")

    def operation():
        partial.unlink(missing_ok=True)
        object_storage.fget_object(bucket, object_name, str(partial))

    _retry(operation)
    partial.replace(target)
    return target
