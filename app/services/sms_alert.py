import os

try:
    from twilio.rest import Client  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Client = None


def _normalize_phone_number(raw_number: str) -> str:
    cleaned = "".join(ch for ch in raw_number.strip() if ch not in "()-. ")
    if not cleaned:
        return ""
    if cleaned.startswith("00"):
        return f"+{cleaned[2:]}"
    if cleaned.startswith("+"):
        return cleaned
    default_country = (
        (os.getenv("TWILIO_DEFAULT_COUNTRY_CODE") or "").strip().lstrip("+")
    )
    if cleaned.startswith("0") and default_country:
        return f"+{default_country}{cleaned.lstrip('0')}"
    if default_country:
        return f"+{default_country}{cleaned}"
    return cleaned


def send_sms_alert(to_number: str, message: str) -> bool:
    account_sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    auth_token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    from_number = (os.getenv("TWILIO_FROM_NUMBER") or "").strip()
    messaging_service_sid = (os.getenv("TWILIO_MESSAGING_SERVICE_SID") or "").strip()
    if not (account_sid and auth_token and (from_number or messaging_service_sid)):
        print("[SMS] Twilio credentials not set. Skipping SMS send.")
        return False
    if Client is None:
        print("[SMS] Twilio dependency missing. Skipping SMS send.")
        return False

    normalized_number = _normalize_phone_number(to_number)
    if not normalized_number:
        print("[SMS] Invalid phone number provided. Skipping SMS send.")
        return False

    try:
        client = Client(account_sid, auth_token)
        if messaging_service_sid:
            client.messages.create(
                body=message,
                messaging_service_sid=messaging_service_sid,
                to=normalized_number,
            )
        else:
            client.messages.create(
                body=message,
                from_=from_number,
                to=normalized_number,
            )
        print(f"[SMS] Alert sent to {normalized_number}")
        return True
    except Exception as e:
        print(f"[SMS] Failed to send SMS: {e}")
        return False
