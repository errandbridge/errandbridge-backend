from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3


@dataclass(frozen=True)
class WormConfig:
    bucket: str
    prefix: str
    retention_days: int
    region: Optional[str]


def _config() -> WormConfig | None:
    bucket = (os.getenv("VOICE_WORM_BUCKET") or "").strip()
    if not bucket:
        return None
    prefix = (os.getenv("VOICE_WORM_PREFIX") or "voice-worm").strip().strip("/")
    retention_days = int((os.getenv("VOICE_WORM_RETENTION_DAYS") or "365").strip())
    region = (os.getenv("AWS_REGION") or os.getenv("S3_REGION") or "").strip() or None
    return WormConfig(
        bucket=bucket, prefix=prefix, retention_days=retention_days, region=region
    )


def _client(region: Optional[str]):
    if region:
        return boto3.client("s3", region_name=region)
    return boto3.client("s3")


def store_worm_json(*, key_suffix: str, payload: dict) -> Optional[str]:
    cfg = _config()
    if cfg is None:
        return None

    safe_suffix = key_suffix.lstrip("/")
    key = f"{cfg.prefix}/{safe_suffix}" if cfg.prefix else safe_suffix
    retain_until = datetime.now(timezone.utc) + timedelta(days=cfg.retention_days)

    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    _client(cfg.region).put_object(
        Bucket=cfg.bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=retain_until,
    )
    return key


def store_worm_bytes(
    *, key_suffix: str, content: bytes, content_type: str
) -> Optional[str]:
    cfg = _config()
    if cfg is None:
        return None

    safe_suffix = key_suffix.lstrip("/")
    key = f"{cfg.prefix}/{safe_suffix}" if cfg.prefix else safe_suffix
    retain_until = datetime.now(timezone.utc) + timedelta(days=cfg.retention_days)

    _client(cfg.region).put_object(
        Bucket=cfg.bucket,
        Key=key,
        Body=content,
        ContentType=content_type,
        ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=retain_until,
    )
    return key
