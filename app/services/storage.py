from __future__ import annotations
import os
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Only import supabase if available
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


class StorageConfigurationError(RuntimeError):
    """Raised when the active deployment has no durable upload destination."""


class StorageWriteError(RuntimeError):
    """Raised when the configured storage destination cannot accept an upload."""


@dataclass(frozen=True)
class StorageConfig:
    driver: str  # "local", "s3", or "supabase"
    upload_dir: str
    s3_bucket: Optional[str]
    s3_region: Optional[str]
    s3_prefix: str
    supabase_url: Optional[str]
    supabase_key: Optional[str]


def get_storage_config() -> StorageConfig:
    driver = (os.getenv("STORAGE_DRIVER") or "local").strip().lower()
    
    # Check if supabase config is present; if so, auto-upgrade driver to supabase if it was local
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("REACT_APP_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and supabase_key and driver == "local":
        driver = "supabase"

    # For local storage, try to mirror the backend's default behavior: ./uploads
    # (relative to this file) when UPLOAD_DIR is not explicitly set.
    upload_dir = os.getenv("UPLOAD_DIR") or ""
    if not upload_dir:
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
    s3_bucket = os.getenv("S3_BUCKET")
    s3_region = os.getenv("AWS_REGION") or os.getenv("S3_REGION")
    s3_prefix = (os.getenv("S3_PREFIX") or "errandbridge").strip().strip("/")

    return StorageConfig(
        driver=driver,
        upload_dir=os.path.abspath(upload_dir),
        s3_bucket=s3_bucket,
        s3_region=s3_region,
        s3_prefix=s3_prefix,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
    )


def build_stored_filename(original_filename: str) -> str:
    # Keep existing behavior: random name + original suffix
    suffix = os.path.splitext(original_filename or "")[1][:16]
    return f"{secrets.token_urlsafe(16)}{suffix}"


def _s3_client(region: Optional[str]):
    if region:
        return boto3.client("s3", region_name=region)
    return boto3.client("s3")


def _supabase_client(cfg: StorageConfig):
    if not SUPABASE_AVAILABLE:
        raise StorageConfigurationError("Supabase python package is not installed.")
    if not cfg.supabase_url or not cfg.supabase_key:
        raise StorageConfigurationError("SUPABASE_URL and SUPABASE_KEY are required for supabase driver.")
    return create_client(cfg.supabase_url, cfg.supabase_key)


def s3_key(prefix: str, stored_filename: str) -> str:
    p = (prefix or "").strip().strip("/")
    if not p:
        return stored_filename
    return f"{p}/{stored_filename}"


def put_bytes(
    stored_filename: str, 
    content: bytes, 
    content_type: Optional[str] = None,
    bucket_name: Optional[str] = None
) -> Tuple[str, Optional[str]]:
    """Store bytes and return (driver, location).

    - driver: "local", "s3", or "supabase"
    - location: for local, filepath; for s3/supabase, object key
    """

    cfg = get_storage_config()

    if cfg.driver == "supabase":
        target_bucket = bucket_name or cfg.s3_bucket or "errandbridge-uploads"
        sb = _supabase_client(cfg)
        
        file_options = {}
        if content_type:
            file_options["content-type"] = content_type
            
        try:
            res = sb.storage.from_(target_bucket).upload(
                path=stored_filename,
                file=content,
                file_options=file_options
            )
            # Supabase API usually returns a dict if successful, otherwise it might raise an exception.
        except Exception as exc:
            raise StorageWriteError(f"Supabase storage upload failed: {str(exc)}") from exc
            
        return "supabase", stored_filename


    if cfg.driver == "s3":
        target_bucket = bucket_name or cfg.s3_bucket
        if not target_bucket:
            raise StorageConfigurationError(
                "Document storage is not configured. Set S3_BUCKET for S3 storage."
            )
        key = s3_key(cfg.s3_prefix, stored_filename)
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        try:
            _s3_client(cfg.s3_region).put_object(
                Bucket=target_bucket, Key=key, Body=content, **extra
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageWriteError(
                "Document storage could not accept the upload."
            ) from exc
        return "s3", key

    if os.getenv("VERCEL"):
        raise StorageConfigurationError(
            "Document uploads require S3 or Supabase storage in this hosted environment."
        )

    # local development fallback
    if not cfg.upload_dir:
        raise RuntimeError("UPLOAD_DIR is required for local storage")
    
    # If bucket is given, we can append it to the upload dir to organize files locally
    local_dir = cfg.upload_dir
    if bucket_name:
        local_dir = os.path.join(cfg.upload_dir, bucket_name)
        
    path = os.path.join(local_dir, stored_filename)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
    except OSError as exc:
        raise StorageConfigurationError(
            "The configured local upload directory is not writable. "
        ) from exc
    return "local", path


def get_local_path_from_attachment(stored_filename: str, upload_dir: str, bucket_name: Optional[str] = None) -> str:
    if bucket_name:
        return os.path.join(upload_dir, bucket_name, stored_filename)
    return os.path.join(upload_dir, stored_filename)


def presign_or_stream_key(
    key: str,
    filename: str,
    content_type: Optional[str] = None,
    expires_seconds: int = 60,
    bucket_name: Optional[str] = None
) -> str:
    """Generate a short-lived presigned URL for downloads."""

    cfg = get_storage_config()
    
    if cfg.driver == "supabase":
        target_bucket = bucket_name or cfg.s3_bucket or "errandbridge-uploads"
        sb = _supabase_client(cfg)
        
        # Determine if bucket is public or private. 
        # Actually, Supabase has create_signed_url for private and get_public_url for public.
        # But we can just use create_signed_url for everything safely, it works for public too!
        try:
            res = sb.storage.from_(target_bucket).create_signed_url(
                path=key, 
                expires_in=expires_seconds
            )
            return res.get('signedURL', res.get('signedUrl', ''))
        except Exception as e:
            raise RuntimeError(f"Could not generate signed URL from Supabase: {str(e)}")

    if cfg.driver != "s3":
        raise RuntimeError("presign_or_stream_key only valid for s3 or supabase storage")
        
    target_bucket = bucket_name or cfg.s3_bucket
    if not target_bucket:
        raise RuntimeError("STORAGE_DRIVER=s3 requires S3_BUCKET or bucket_name")

    params = {
        "Bucket": target_bucket,
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


def delete_object_if_exists(stored_filename: str, bucket_name: Optional[str] = None) -> None:
    cfg = get_storage_config()
    
    if cfg.driver == "supabase":
        target_bucket = bucket_name or cfg.s3_bucket or "errandbridge-uploads"
        sb = _supabase_client(cfg)
        try:
            sb.storage.from_(target_bucket).remove([stored_filename])
        except Exception:
            pass
        return

    if cfg.driver != "s3":
        # Local cleanup not implemented (best-effort); keep it simple.
        return
        
    target_bucket = bucket_name or cfg.s3_bucket
    if not target_bucket:
        return

    key = s3_key(cfg.s3_prefix, stored_filename)
    try:
        _s3_client(cfg.s3_region).delete_object(Bucket=target_bucket, Key=key)
    except ClientError:
        # Ignore cleanup errors
        return
