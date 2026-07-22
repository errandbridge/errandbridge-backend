import os
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class StorageConfig:
    driver: str  # "local" or "s3"
    upload_dir: str
    s3_bucket: Optional[str]
    s3_region: Optional[str]
    s3_prefix: str


def get_storage_config() -> StorageConfig:
    driver = (os.getenv("STORAGE_DRIVER") or "local").strip().lower()
    # For local storage, try to mirror the backend's default behavior: ./uploads
    # (relative to this file) when UPLOAD_DIR is not explicitly set.
    upload_dir = os.getenv("UPLOAD_DIR") or ""
    if not upload_dir:
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
    s3_bucket = os.getenv("S3_BUCKET")
    s3_region = os.getenv("AWS_REGION") or os.getenv("S3_REGION")
    s3_prefix = (os.getenv("S3_PREFIX") or "errandbridge").strip().strip("/")

    return StorageConfig(
        driver=driver,
        upload_dir=upload_dir,
        s3_bucket=s3_bucket,
        s3_region=s3_region,
        s3_prefix=s3_prefix,
    )


def build_stored_filename(original_filename: str) -> str:
    # Keep existing behavior: random name + original suffix
    suffix = os.path.splitext(original_filename or "")[1][:16]
    return f"{secrets.token_urlsafe(16)}{suffix}"


def _s3_client(region: Optional[str]):
    # Region can be omitted if using env/role defaults.
    if region:
        return boto3.client("s3", region_name=region)
    return boto3.client("s3")


def s3_key(prefix: str, stored_filename: str) -> str:
    p = (prefix or "").strip().strip("/")
    if not p:
        return stored_filename
    return f"{p}/{stored_filename}"


def put_bytes(stored_filename: str, content: bytes, content_type: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Store bytes and return (driver, location).

    - driver: "local" or "s3"
    - location: for local, filepath; for s3, object key
    """

    cfg = get_storage_config()

    if cfg.driver == "s3":
        if not cfg.s3_bucket:
            raise RuntimeError("STORAGE_DRIVER=s3 requires S3_BUCKET")
        key = s3_key(cfg.s3_prefix, stored_filename)
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        _s3_client(cfg.s3_region).put_object(Bucket=cfg.s3_bucket, Key=key, Body=content, **extra)
        return "s3", key

    # local fallback
    if not cfg.upload_dir:
        raise RuntimeError("UPLOAD_DIR is required for local storage")
    path = os.path.join(cfg.upload_dir, stored_filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return "local", path


def get_local_path_from_attachment(stored_filename: str, upload_dir: str) -> str:
    return os.path.join(upload_dir, stored_filename)


def presign_or_stream_key(key: str, filename: str, content_type: Optional[str] = None, expires_seconds: int = 60) -> str:
    """Generate a short-lived presigned URL for S3 downloads."""

    cfg = get_storage_config()
    if cfg.driver != "s3":
        raise RuntimeError("presign_or_stream_key only valid for s3 storage")
    if not cfg.s3_bucket:
        raise RuntimeError("STORAGE_DRIVER=s3 requires S3_BUCKET")

    params = {
        "Bucket": cfg.s3_bucket,
        "Key": key,
        "ResponseContentDisposition": f'attachment; filename="{filename}"',
    }
    if content_type:
        params["ResponseContentType"] = content_type

    return _s3_client(cfg.s3_region).generate_presigned_url(
        ClientMethod="get_object",
        Params=params,
        ExpiresIn=max(10, int(expires_seconds)),
    )


def delete_object_if_exists(stored_filename: str) -> None:
    cfg = get_storage_config()
    if cfg.driver != "s3":
        # Local cleanup not implemented (best-effort); keep it simple.
        return
    if not cfg.s3_bucket:
        return

    key = s3_key(cfg.s3_prefix, stored_filename)
    try:
        _s3_client(cfg.s3_region).delete_object(Bucket=cfg.s3_bucket, Key=key)
    except ClientError:
        # Ignore cleanup errors
        return
