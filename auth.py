from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

# MVP auth: JWT stored client-side (localStorage), sent via Authorization: Bearer <token>
#
# NOTE: bcrypt has a 72-byte password input limit.
# To avoid "password too long" runtime errors (common with password managers),
# we use PBKDF2-SHA256 for new passwords while still supporting bcrypt verification
# for any existing stored hashes.

PWD_CONTEXT = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)

# Support both names:
# - Local/dev uses JWT_SECRET_KEY (historical)
# - ECS task definition injects JWT_SECRET (strict-mode via SSM)
JWT_SECRET_KEY = os.getenv("JWT_SECRET") or os.getenv(
    "JWT_SECRET_KEY", "dev-secret-change-me"
)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "10080"))  # 7 days
JWT_REFRESH_EXPIRES_DAYS = int(os.getenv("JWT_REFRESH_EXPIRES_DAYS", "30"))


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def is_production_like_env() -> bool:
    env = (
        (
            os.getenv("ENV")
            or os.getenv("BACKEND_ENVIRONMENT")
            or os.getenv("ENVIRONMENT")
            or os.getenv("APP_ENV")
            or ""
        )
        .strip()
        .lower()
    )

    if env in {"prod", "production"}:
        return True

    return bool(
        os.getenv("AWS_EXECUTION_ENV")
        or os.getenv("ECS_CONTAINER_METADATA_URI_V4")
        or os.getenv("ECS_CONTAINER_METADATA_URI")
        or os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
        or os.getenv("AWS_CONTAINER_CREDENTIALS_FULL_URI")
    )


def is_email_confirmation_disabled() -> bool:
    raw = os.getenv("DISABLE_EMAIL_CONFIRMATION")
    if raw is not None:
        return _env_truthy(raw)

    # Safe-by-default: local/dev may skip email verification when not configured,
    # but prod-like environments must explicitly opt out.
    return not is_production_like_env()


def hash_password(password: str) -> str:
    return PWD_CONTEXT.hash(password or "")


def verify_password(password: str, password_hash: str) -> bool:
    return PWD_CONTEXT.verify(password or "", password_hash)


def create_access_token(*, user_id: int, expires_minutes: Optional[int] = None) -> str:
    now = datetime.now(timezone.utc)
    token_minutes = (
        JWT_EXPIRES_MINUTES if expires_minutes is None else int(expires_minutes)
    )
    exp = now + timedelta(minutes=token_minutes)
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": exp,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(*, user_id: int, expires_days: Optional[int] = None) -> str:
    now = datetime.now(timezone.utc)
    token_days = JWT_REFRESH_EXPIRES_DAYS if expires_days is None else int(expires_days)
    exp = now + timedelta(days=token_days)
    payload = {
        "sub": str(user_id),
        "typ": "refresh",
        "iat": int(now.timestamp()),
        "exp": exp,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        token_type = payload.get("typ")
        if token_type not in (None, "access"):
            return None
        sub = payload.get("sub")
        if not sub:
            return None
        return int(sub)
    except (JWTError, ValueError):
        return None


def decode_refresh_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("typ") != "refresh":
            return None
        sub = payload.get("sub")
        if not sub:
            return None
        return int(sub)
    except (JWTError, ValueError):
        return None
