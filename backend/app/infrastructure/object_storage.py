"""MinIO/阿里云OSS兼容对象存储适配器。"""

from io import BytesIO
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


def upload_bytes(object_name: str, content: bytes, content_type: str) -> str:
    """上传任意二进制产物并返回稳定的S3 URI。"""
    bucket = get_settings().object_storage_bucket
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
    return f"s3://{bucket}/{object_name}"


def upload_json(object_name: str, content: bytes) -> str:
    return upload_bytes(object_name, content, "application/json; charset=utf-8")


def download_bytes(uri: str) -> bytes:
    """读取平台自身生成的S3 URI。"""
    prefix = "s3://"
    if not uri.startswith(prefix):
        raise ValueError("仅支持s3://产物地址")
    bucket, object_name = uri[len(prefix):].split("/", 1)
    response = object_storage.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close(); response.release_conn()
