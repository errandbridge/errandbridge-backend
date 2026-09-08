from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from models import User

PHONE_SIGNUP_EMAIL_DOMAIN = "phone-auth.errandbridge.com"


# Auth flows should only load the columns they actually need. This keeps
# signup/login resilient when production DB migrations lag behind newer profile
# columns added to the ORM model.
AUTH_SAFE_USER_COLUMNS = (
    User.id,
    User.user_uuid,
    User.email,
    User.password_hash,
    User.first_name,
    User.last_name,
    User.phone,
    User.is_email_verified,
    User.email_otp_hash,
    User.email_otp_expires_at,
    User.email_otp_last_sent_at,
    User.email_otp_attempts,
    User.address_line1,
    User.address_line2,
    User.city,
    User.state,
    User.postal_code,
    User.country,
    User.id_verification_status,
    User.address_verification_status,
    User.is_pilot,
    User.must_change_password,
    User.profile_image_url,
)

AUTH_SAFE_USER_LOAD_OPTIONS = (load_only(*AUTH_SAFE_USER_COLUMNS),)


def auth_safe_user_select():
    return select(User).options(*AUTH_SAFE_USER_LOAD_OPTIONS)


def auth_safe_user_by_email_query(email: str):
    normalized = (email or "").strip().lower()
    return auth_safe_user_select().where(func.lower(User.email) == normalized)


def normalize_phone_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_phone_for_storage(value: str | None) -> str:
    raw = str(value or "").strip()
    digits = normalize_phone_digits(raw)
    if not digits:
        return ""
    return f"+{digits}" if raw.startswith("+") else digits


def is_phone_identifier(value: str | None) -> bool:
    raw = str(value or "").strip()
    return "@" not in raw and len(normalize_phone_digits(raw)) >= 7


def build_phone_alias_email(phone: str, role: str = "client") -> str:
    normalized_role = (role or "client").strip().lower() or "client"
    normalized_phone = normalize_phone_digits(phone)
    return f"phone-{normalized_role}-{normalized_phone}@{PHONE_SIGNUP_EMAIL_DOMAIN}"


def is_phone_alias_email(email: str | None) -> bool:
    normalized = (email or "").strip().lower()
    return normalized.endswith(f"@{PHONE_SIGNUP_EMAIL_DOMAIN}")


def _phone_lookup_expression():
    return func.replace(
        func.replace(
            func.replace(
                func.replace(
                    func.replace(
                        func.replace(func.coalesce(User.phone, ""), " ", ""),
                        "-",
                        "",
                    ),
                    "(",
                    "",
                ),
                ")",
                "",
            ),
            ".",
            "",
        ),
        "+",
        "",
    )


def auth_safe_user_by_phone_query(phone: str):
    normalized = normalize_phone_digits(phone)
    return auth_safe_user_select().where(_phone_lookup_expression() == normalized)
