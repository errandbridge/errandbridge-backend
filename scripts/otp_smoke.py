#!/usr/bin/env python3
"""OTP-only smoke test for ErrandBridge.

This script validates OTP generation + confirmation via the REST API and
supports delivery mode selection (email/SMS, code/link/both).

Usage examples:
  ERRANDBRIDGE_BASE_URL=http://localhost:8001 \
    OTP_CHANNEL=email OTP_MODE=code \
    DATABASE_URL=postgresql://postgres:postgres@localhost:5433/errandbridge \
    /path/to/python scripts/otp_smoke.py
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import psycopg2
import requests
from dotenv import load_dotenv


DEFAULT_BASE_URL = "http://localhost:8001"


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    otp_channel: str
    otp_mode: str
    email: str
    password: str
    first_name: str
    last_name: str
    phone: str


def _load_config() -> SmokeConfig:
    base_url = os.getenv("ERRANDBRIDGE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    otp_channel = os.getenv("OTP_CHANNEL", "email").strip().lower()
    otp_mode = os.getenv("OTP_MODE", "code").strip().lower()
    ts = int(time.time())
    email = os.getenv("OTP_TEST_EMAIL", f"otp_smoke_{ts}@example.com")
    password = os.getenv("OTP_TEST_PASSWORD", "TestPassword123!")
    first_name = os.getenv("OTP_TEST_FIRST_NAME", "OTP")
    last_name = os.getenv("OTP_TEST_LAST_NAME", "Smoke")
    phone = os.getenv("OTP_TEST_PHONE", "+15550001111")

    return SmokeConfig(
        base_url=base_url,
        otp_channel=otp_channel,
        otp_mode=otp_mode,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )


def _load_db_url() -> str:
    backend_env = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(backend_env)
    return os.getenv("DATABASE_URL", "")


def _normalize_db_url(db_url: str) -> dict[str, Any]:
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    # Handle asyncpg prefix
    clean = db_url.replace("postgresql+asyncpg://", "postgresql://")
    parts = clean.split("?", 1)[0]

    if not parts.startswith("postgresql://"):
        raise RuntimeError(f"Unsupported DATABASE_URL: {db_url}")

    _, rest = parts.split("postgresql://", 1)
    user_pass, host_db = rest.split("@", 1)
    user, password = user_pass.split(":", 1)
    host_port, db_name = host_db.split("/", 1)
    host, port = host_port.split(":", 1)
    if host == "db":
        host = "localhost"
    return {
        "user": user,
        "password": password,
        "host": host,
        "port": int(port),
        "dbname": db_name,
    }


def _fetch_otp_hash(db_cfg: dict[str, Any], email: str) -> str:
    with psycopg2.connect(**db_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email_otp_hash FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
            if not row or not row[0]:
                raise RuntimeError("OTP hash not found in database")
            return row[0]


def _hash_code(code: str, pepper: str) -> str:
    import hashlib
    import hmac

    msg = code.encode("utf-8")
    key = pepper.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _bruteforce_code(otp_hash: str, pepper: str) -> str:
    for i in range(0, 1000000):
        code = f"{i:06d}"
        if _hash_code(code, pepper) == otp_hash:
            return code
    raise RuntimeError("Unable to brute-force OTP code")


def main() -> int:
    cfg = _load_config()
    db_url = os.getenv("DATABASE_URL") or _load_db_url()
    db_cfg = _normalize_db_url(db_url)
    otp_pepper = os.getenv("OTP_PEPPER", "dev-otp-pepper-change-me")

    print(f"[otp-smoke] base_url={cfg.base_url}")
    print(f"[otp-smoke] channel={cfg.otp_channel} mode={cfg.otp_mode}")

    signup_payload = {
        "email": cfg.email,
        "password": cfg.password,
        "first_name": cfg.first_name,
        "last_name": cfg.last_name,
        "phone": cfg.phone,
        "otp_delivery_channel": cfg.otp_channel,
        "otp_delivery_mode": cfg.otp_mode,
    }
    res = requests.post(f"{cfg.base_url}/auth/signup", json=signup_payload, timeout=15)
    if res.status_code not in (200, 409):
        raise RuntimeError(f"Signup failed: {res.status_code} {res.text}")

    otp_hash = _fetch_otp_hash(db_cfg, cfg.email)
    otp_code = _bruteforce_code(otp_hash, otp_pepper)
    print(f"[otp-smoke] otp_code={otp_code}")

    confirm_payload = {"email": cfg.email, "code": otp_code}
    confirm_res = requests.post(
        f"{cfg.base_url}/auth/confirm",
        json=confirm_payload,
        timeout=15,
    )
    if confirm_res.status_code != 200:
        raise RuntimeError(f"Confirm failed: {confirm_res.status_code} {confirm_res.text}")

    print("[otp-smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())