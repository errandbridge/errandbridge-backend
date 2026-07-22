from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from twilio.rest import Client  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Client = None


@dataclass(frozen=True)
class SmsResult:
    delivered: bool
    provider: str
    detail: str | None = None


def _twilio_enabled() -> bool:
    account_sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    auth_token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    from_number = (os.getenv("TWILIO_FROM_NUMBER") or "").strip()
    messaging_service_sid = (os.getenv("TWILIO_MESSAGING_SERVICE_SID") or "").strip()
    return bool(account_sid and auth_token and (from_number or messaging_service_sid))


def _normalize_phone_number(raw_number: str) -> str:
    cleaned = "".join(ch for ch in raw_number.strip() if ch not in "()-. ")
    if not cleaned:
        return ""
    if cleaned.startswith("00"):
        return f"+{cleaned[2:]}"
    if cleaned.startswith("+"):
        return cleaned
    default_country = (os.getenv("TWILIO_DEFAULT_COUNTRY_CODE") or "").strip().lstrip("+")
    if cleaned.startswith("0") and default_country:
        return f"+{default_country}{cleaned.lstrip('0')}"
    if default_country:
        return f"+{default_country}{cleaned}"
    return cleaned


def send_sms(*, to_number: str, body_text: str) -> SmsResult:
    if not _twilio_enabled():
        return SmsResult(delivered=False, provider="twilio", detail="missing_config")
    if Client is None:
        return SmsResult(delivered=False, provider="twilio", detail="missing_dependency")

    account_sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    auth_token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    from_number = (os.getenv("TWILIO_FROM_NUMBER") or "").strip()
    messaging_service_sid = (os.getenv("TWILIO_MESSAGING_SERVICE_SID") or "").strip()
    normalized_number = _normalize_phone_number(to_number)
    if not normalized_number:
        return SmsResult(delivered=False, provider="twilio", detail="invalid_phone")

    try:
        client = Client(account_sid, auth_token)
        if messaging_service_sid:
            client.messages.create(
                to=normalized_number,
                messaging_service_sid=messaging_service_sid,
                body=body_text,
            )
        else:
            client.messages.create(to=normalized_number, from_=from_number, body=body_text)
        return SmsResult(delivered=True, provider="twilio")
    except Exception as e:
        return SmsResult(delivered=False, provider="twilio", detail=f"twilio_send_failed: {e}")
