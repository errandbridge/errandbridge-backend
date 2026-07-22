from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time


def generate_numeric_code(length: int = 6) -> str:
    if length < 4 or length > 10:
        raise ValueError("length must be between 4 and 10")
    digits = "0123456789"
    return "".join(secrets.choice(digits) for _ in range(length))


def hash_code(code: str) -> str:
    # Server-side secret (pepper) so leaked DB hashes are less useful.
    pepper = os.getenv("OTP_PEPPER", "dev-otp-pepper-change-me")
    msg = (code or "").encode("utf-8")
    key = pepper.encode("utf-8")
    digest = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return digest


def now_ts() -> int:
    return int(time.time())
