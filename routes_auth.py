from __future__ import annotations

import os
import asyncio
import secrets
from typing import Optional, Literal, Any
from urllib.parse import urlencode
from urllib.parse import urlparse

import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException, status, Form, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func

import httpx
from email_validator import EmailNotValidError, validate_email
from jose import jwt as jose_jwt
from jose import JWTError

from auth import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    is_email_confirmation_disabled,
    verify_password,
)
from auth_user_query import (
    AUTH_SAFE_USER_LOAD_OPTIONS,
    auth_safe_user_by_email_query,
    auth_safe_user_by_phone_query,
    build_phone_alias_email,
    is_phone_alias_email,
    is_phone_identifier,
    normalize_phone_for_storage,
)
from admin_utils import admin_emails
from database import get_db
from models import Errand, ErrandAttachment, User
from otp import generate_numeric_code, hash_code, now_ts
from emailer import send_email
from sms_sender import send_sms

router = APIRouter(prefix="/auth", tags=["auth"])
login_router = APIRouter(prefix="/login", tags=["login"])
tso_router = APIRouter(prefix="/tso", tags=["tso"])

OtpChannel = Literal["email", "sms"]
OtpMode = Literal["code", "link", "both"]
DEFAULT_OTP_CHANNEL: OtpChannel = "email"
DEFAULT_OTP_MODE: OtpMode = "code"


def _is_production_env() -> bool:
    env = (
        os.getenv("ENV")
        or os.getenv("BACKEND_ENVIRONMENT")
        or os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or ""
    ).strip().lower()

    if env in {"prod", "production"}:
        return True

    # If ENV isn't set but we're clearly running in AWS, treat it as production-like
    # for the purpose of redacting internal error messages.
    if not env and bool(os.getenv("AWS_EXECUTION_ENV")):
        return True

    return False


def _raise_db_unavailable(exc: Exception | None = None) -> None:
    """Raise an HTTP error appropriate for database connectivity/auth issues."""
    # In production we avoid leaking internal DB details.
    if _is_production_env():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again shortly.",
        )

    # Non-prod: keep the detail to speed up debugging.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc) if exc else "Database unavailable",
    )


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, min_length=3, max_length=32)
    role: Optional[str] = Field(default="client")

    # Verification onboarding (v1)
    id_collected_offline: bool = False
    address_line1: Optional[str] = Field(default=None, min_length=1, max_length=200)
    address_line2: Optional[str] = Field(default=None, max_length=200)
    city: Optional[str] = Field(default=None, min_length=1, max_length=100)
    state: Optional[str] = Field(default=None, min_length=1, max_length=100)
    postal_code: Optional[str] = Field(default=None, min_length=1, max_length=30)
    country: Optional[str] = Field(default=None, min_length=2, max_length=80)

    otp_delivery_channel: OtpChannel = Field(default=DEFAULT_OTP_CHANNEL)
    otp_delivery_mode: OtpMode = Field(default=DEFAULT_OTP_MODE)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role: Optional[str] = Field(default="client")


class LoginCodeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    link_token: str = Field(
        ...,
        alias="token",
        min_length=10,
        description=(
            "Short-lived signed login link token. The token must be a JWT signed by the backend "
            "with audience 'login-link' and either a user id in 'sub' or an identifier/email claim."
        ),
    )
    role: Optional[str] = Field(default="client")
    otp_delivery_channel: OtpChannel = Field(default=DEFAULT_OTP_CHANNEL)
    otp_delivery_mode: OtpMode = Field(default=DEFAULT_OTP_MODE)


class LoginCodeRequestData(BaseModel):
    deliveryChannel: str
    maskedDestination: str
    expiresInSeconds: int


class LoginCodeRequestResponse(BaseModel):
    status: str = "SUCCESS"
    code: int = 0
    message: str = "Code sent"
    data: LoginCodeRequestData
    timestamp: str
    error: Optional[str] = None
    path: str


class LoginCodeVerifyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    link_token: str = Field(..., alias="token", min_length=10)
    code: str = Field(..., min_length=4, max_length=10)
    role: Optional[str] = Field(default="client")


class LoginCodeVerifyData(BaseModel):
    sessionToken: str
    refreshToken: str
    userUuid: str = Field(..., description="Stable public UUID for mapping data to this user. Not a replacement for Bearer authentication.")
    expiresInSeconds: int
    tokenType: str = "bearer"


class LoginCodeVerifyResponse(BaseModel):
    status: str = "SUCCESS"
    code: int = 0
    message: str = "Code verified"
    data: LoginCodeVerifyData
    timestamp: str
    error: Optional[str] = None
    path: str


class GoogleAuthRequest(BaseModel):
    credential: str = Field(..., min_length=10)
    role: Optional[str] = Field(default="client")
    allow_pilot_signup: bool = Field(default=False)


class OAuthFlowStatus(BaseModel):
    enabled: bool
    configured: bool
    origin_allowed: bool = True
    reason: Optional[str] = None


class GoogleOAuthStatus(BaseModel):
    redirect: OAuthFlowStatus
    token: OAuthFlowStatus


class AppleOAuthStatus(BaseModel):
    redirect: OAuthFlowStatus


class OAuthStatusResponse(BaseModel):
    origin: str
    role: str
    google: GoogleOAuthStatus
    apple: AppleOAuthStatus


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: int
    user_uuid: str = Field(..., description="Stable public UUID for mapping data to this user. Not a replacement for Bearer authentication.")
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    is_email_verified: bool = False
    is_admin: bool = False


class MeResponse(BaseModel):
    user_id: int
    user_uuid: str = Field(..., description="Stable public UUID for mapping data to this user. Not a replacement for Bearer authentication.")
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    is_email_verified: bool = False
    is_admin: bool = False
    transparency: dict = Field(default_factory=dict)


class ConfirmRequest(BaseModel):
    email: str = Field(..., min_length=1)
    code: str = Field(..., min_length=4, max_length=10)


class ConfirmResponse(BaseModel):
    ok: bool = True


class ResendRequest(BaseModel):
    email: str = Field(..., min_length=1)
    otp_delivery_channel: OtpChannel = Field(default=DEFAULT_OTP_CHANNEL)
    otp_delivery_mode: OtpMode = Field(default=DEFAULT_OTP_MODE)


class PasswordResetStartRequest(BaseModel):
    email: str = Field(..., min_length=1)
    otp_delivery_channel: OtpChannel = Field(default=DEFAULT_OTP_CHANNEL)
    otp_delivery_mode: OtpMode = Field(default=DEFAULT_OTP_MODE)


class PasswordResetConfirmRequest(BaseModel):
    email: str = Field(..., min_length=1)
    code: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=8)


class PasswordChangeStartResponse(BaseModel):
    ok: bool = True


class PasswordResetStartResponse(BaseModel):
    ok: bool = True


class PasswordResetConfirmResponse(BaseModel):
    ok: bool = True


class PasswordChangeConfirmRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=8)


class PasswordChangeConfirmResponse(BaseModel):
    ok: bool = True


class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, min_length=3, max_length=32)


class UpdateProfileResponse(BaseModel):
    ok: bool = True
    user_id: int
    user_uuid: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None


class DeactivateAccountResponse(BaseModel):
    ok: bool = True
    user_id: int
    user_uuid: str
    email: EmailStr
    message: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class EmailStatusResponse(BaseModel):
    smtp_configured: bool
    graph_configured: bool
    ses_api_enabled: bool
    delivery_mode: str


class EmailHealthResponse(BaseModel):
    graph_ok: bool
    graph_detail: Optional[str] = None
    smtp_ok: Optional[bool] = None
    smtp_detail: Optional[str] = None
    delivery_mode: str


class EmailTestRequest(BaseModel):
    to_email: EmailStr
    subject: Optional[str] = "ErrandBridge email test"
    body_text: Optional[str] = "This is a test email from the ErrandBridge backend."


class EmailTestResponse(BaseModel):
    delivered: bool
    provider: str
    detail: Optional[str] = None


class SmsStatusResponse(BaseModel):
    twilio_configured: bool
    twilio_dependency: bool
    default_country_code: Optional[str] = None


class AdminDiagnosticsResponse(BaseModel):
    email: EmailStr
    exists: bool
    is_email_verified: bool = False
    is_admin: bool = False
    user_id: Optional[int] = None
    user_uuid: Optional[str] = None


def _public_user_uuid(user: User) -> str:
    value = getattr(user, "user_uuid", None)
    if value:
        return str(value)
    # Test/dummy objects may not include the new column. Real DB rows are
    # backfilled by migration 019 and new rows get a generated UUID.
    return f"00000000-0000-0000-0000-{int(getattr(user, 'id', 0)):012d}"


def _mask_email(email: str) -> str:
    """Return a minimally-masked email for UX messages."""
    v = (email or "").strip()
    if "@" not in v:
        return ""
    local, domain = v.split("@", 1)
    if len(local) <= 2:
        return f"{local[:1]}***@{domain}"
    return f"{local[:2]}***@{domain}"


def _normalize_email_identifier(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a valid email address or phone number")

    try:
        validated = validate_email(candidate, check_deliverability=False)
    except EmailNotValidError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a valid email address or phone number")

    return str(validated.normalized).strip().lower()


def _build_otp_link(email: str, code: str) -> str | None:
    base = (os.getenv("OTP_VERIFICATION_LINK_BASE_URL") or "").strip()
    if not base:
        return None
    query = urlencode({"email": email, "code": code})
    return f"{base.rstrip('/')}/?{query}"


def _normalize_otp_options(channel: OtpChannel, mode: OtpMode) -> tuple[OtpChannel, OtpMode]:
    resolved_channel: OtpChannel = channel if channel in ("email", "sms") else DEFAULT_OTP_CHANNEL
    resolved_mode: OtpMode = mode if mode in ("code", "link", "both") else DEFAULT_OTP_MODE
    if resolved_mode in ("link", "both") and not (os.getenv("OTP_VERIFICATION_LINK_BASE_URL") or "").strip():
        resolved_mode = "code"
    return resolved_channel, resolved_mode


@router.get("/email-status", response_model=EmailStatusResponse)
async def email_status() -> EmailStatusResponse:
    smtp_host = (os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER") or "").strip()
    smtp_user = (os.getenv("SMTP_USERNAME") or "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_from = (os.getenv("SMTP_FROM") or "").strip()
    smtp_auth_mode = (os.getenv("SMTP_AUTH_MODE") or "login").strip().lower()
    if smtp_auth_mode == "none":
        smtp_configured = bool(smtp_host and smtp_from)
    else:
        smtp_configured = bool(smtp_host and smtp_user and smtp_pass and smtp_from)

    ses_api_enabled = False

    graph_tenant = (os.getenv("GRAPH_TENANT_ID") or "").strip()
    graph_client = (os.getenv("GRAPH_CLIENT_ID") or "").strip()
    graph_secret = (os.getenv("GRAPH_CLIENT_SECRET") or "").strip()
    graph_sender = (os.getenv("GRAPH_SENDER") or "").strip()
    graph_configured = bool(graph_tenant and graph_client and graph_secret and graph_sender)

    if graph_configured:
        delivery_mode = "graph"
    elif smtp_configured:
        delivery_mode = "smtp"
    else:
        delivery_mode = "stdout"

    return EmailStatusResponse(
        smtp_configured=smtp_configured,
        graph_configured=graph_configured,
        ses_api_enabled=ses_api_enabled,
        delivery_mode=delivery_mode,
    )


@router.get("/email-health", response_model=EmailHealthResponse)
async def email_health() -> EmailHealthResponse:
    from emailer import graph_health_check, smtp_health_check, HealthResult

    async def _run_with_timeout(func, timeout_seconds: float):
        try:
            return await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return HealthResult(ok=False, provider="timeout", detail="health_check_timeout")
        except Exception as exc:
            return HealthResult(ok=False, provider="exception", detail=str(exc))

    graph_timeout = float(os.getenv("GRAPH_HEALTH_TIMEOUT_SECONDS") or os.getenv("GRAPH_TIMEOUT_SECONDS") or "10")
    smtp_timeout = float(os.getenv("SMTP_HEALTH_TIMEOUT_SECONDS") or os.getenv("SMTP_TIMEOUT_SECONDS") or "15")

    graph_result = await _run_with_timeout(graph_health_check, timeout_seconds=max(1.0, graph_timeout))
    smtp_result = await _run_with_timeout(smtp_health_check, timeout_seconds=max(1.0, smtp_timeout))

    status_result = await email_status()
    if status_result.graph_configured:
        delivery_mode = "graph"
    elif status_result.smtp_configured:
        delivery_mode = "smtp"
    else:
        delivery_mode = "stdout"
    return EmailHealthResponse(
        graph_ok=graph_result.ok,
        graph_detail=graph_result.detail,
        smtp_ok=smtp_result.ok,
        smtp_detail=smtp_result.detail,
        delivery_mode=delivery_mode,
    )


@router.get("/email-health-quick", response_model=EmailStatusResponse)
async def email_health_quick() -> EmailStatusResponse:
    """Return email configuration status without network calls.

    Useful for fast diagnostics when provider health checks are slow or blocked.
    """
    return await email_status()


@router.post("/email-test", response_model=EmailTestResponse)
async def email_test(
    payload: EmailTestRequest,
    x_admin_diagnostics_key: Optional[str] = Header(default=None, alias="X-Admin-Diagnostics-Key"),
) -> EmailTestResponse:
    expected_key = (os.getenv("ADMIN_DIAGNOSTICS_KEY") or "").strip()
    if not expected_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Diagnostics disabled")
    if x_admin_diagnostics_key != expected_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    from emailer import _graph_enabled, _send_via_graph

    subject = payload.subject or "ErrandBridge email test"
    body_text = payload.body_text or "This is a test email from the ErrandBridge backend."

    if _graph_enabled():
        result = await asyncio.to_thread(
            _send_via_graph,
            to_email=payload.to_email,
            subject=subject,
            body_text=body_text,
        )
    else:
        result = await asyncio.to_thread(
            send_email,
            to_email=payload.to_email,
            subject=subject,
            body_text=body_text,
        )
    return EmailTestResponse(
        delivered=result.delivered,
        provider=result.provider,
        detail=result.detail,
    )


@router.get("/sms-status", response_model=SmsStatusResponse)
async def sms_status() -> SmsStatusResponse:
    from sms_sender import Client as TwilioClient, _twilio_enabled

    default_country = (os.getenv("TWILIO_DEFAULT_COUNTRY_CODE") or "").strip() or None
    return SmsStatusResponse(
        twilio_configured=_twilio_enabled(),
        twilio_dependency=TwilioClient is not None,
        default_country_code=default_country,
    )


@router.get("/admin-diagnostics", response_model=AdminDiagnosticsResponse)
async def admin_diagnostics(
    email: EmailStr,
    x_admin_diagnostics_key: Optional[str] = Header(default=None, alias="X-Admin-Diagnostics-Key"),
    db: AsyncSession = Depends(get_db),
) -> AdminDiagnosticsResponse:
    expected_key = (os.getenv("ADMIN_DIAGNOSTICS_KEY") or "").strip()
    if not expected_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Diagnostics disabled")
    if x_admin_diagnostics_key != expected_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    user = await _get_user_by_email(db, email)

    if not user:
        return AdminDiagnosticsResponse(email=email, exists=False)

    admin_list = {addr.strip().lower() for addr in admin_emails() if addr.strip()}
    return AdminDiagnosticsResponse(
        email=email,
        exists=True,
        is_email_verified=bool(user.is_email_verified),
        is_admin=user.email.lower() in admin_list,
        user_id=user.id,
        user_uuid=_public_user_uuid(user),
    )


def _build_otp_body(*, email: str, code: str, purpose: str, mode: OtpMode) -> tuple[str, str | None]:
    link = _build_otp_link(email, code)
    if mode in ("link", "both") and not link:
        mode = "code"

    if mode == "code":
        body = (
            f"Your security code is:\n\n{code}\n\n"
            "It expires in 10 minutes."
        )
    elif mode == "link":
        body = (
            f"Use this link to complete {purpose}:\n\n{link}\n\n"
            "It expires in 10 minutes."
        )
    else:
        body = (
            f"Your security code is:\n\n{code}\n\n"
            f"Or use this link to complete {purpose}:\n\n{link}\n\n"
            "It expires in 10 minutes."
        )

    return body, link


async def _send_otp_for_user(
    db: AsyncSession,
    user: User,
    *,
    purpose: str,
    channel: OtpChannel = DEFAULT_OTP_CHANNEL,
    mode: OtpMode = DEFAULT_OTP_MODE,
    smoke_env: str | None = None,
) -> None:
    """Generate/send OTP and store hash/expiry in the user's OTP fields.

    NOTE: We reuse the existing users.email_otp_* columns for multiple purposes.
    That means any new OTP invalidates previous ones (good for security).
    """

    last_sent = int(user.email_otp_last_sent_at or 0)
    if now_ts() - last_sent < 30:
        # Too soon; silently ignore to avoid oracle behavior.
        return

    channel, mode = _normalize_otp_options(channel, mode)
    if channel == "sms" and not user.phone:
        channel = "email"

    smoke_code = _smoke_otp_code(smoke_env)
    code = smoke_code or generate_numeric_code(6)
    user.email_otp_hash = hash_code(code)
    user.email_otp_expires_at = now_ts() + int(10 * 60)
    user.email_otp_last_sent_at = now_ts()
    user.email_otp_attempts = 0
    await db.commit()

    body_text, link = _build_otp_body(email=user.email, code=code, purpose=purpose, mode=mode)

    if channel == "sms":
        try:
            result = await asyncio.to_thread(
                send_sms,
                to_number=user.phone,
                body_text=body_text,
            )
            if not result.delivered:
                print(f"[OTP_SMS] Send failed for {purpose}: {result.detail}")
                channel = "email"
        except HTTPException:
            raise
        except Exception as e:
            print(f"[OTP_SMS] Send failed for {purpose}: {e}")
            channel = "email"
        if channel == "sms":
            return

    try:
        result = await asyncio.to_thread(
            send_email,
            to_email=user.email,
            subject="Your ErrandBridge security code",
            body_text=(
                f"{body_text}\n\n"
                f"If you did not request a {purpose}, you can ignore this message."
            ),
        )
        if result.provider == "stdout":
            if channel != "sms" and user.phone:
                async def _dispatch_stdout_sms_fallback() -> None:
                    try:
                        fallback = await asyncio.to_thread(
                            send_sms,
                            to_number=user.phone,
                            body_text=body_text,
                        )
                        if not fallback.delivered:
                            print(f"[OTP_SMS] Stdout fallback send failed for {purpose}: {fallback.detail}")
                    except Exception as sms_error:
                        print(f"[OTP_SMS] Stdout fallback send failed for {purpose}: {sms_error}")

                asyncio.create_task(_dispatch_stdout_sms_fallback())
            return
        if not result.delivered:
            print(f"[OTP_EMAIL] Send failed for {purpose}: {result.detail}")
            if channel != "sms" and user.phone:
                async def _dispatch_sms_fallback() -> None:
                    try:
                        fallback = await asyncio.to_thread(
                            send_sms,
                            to_number=user.phone,
                            body_text=body_text,
                        )
                        if not fallback.delivered:
                            print(f"[OTP_SMS] Fallback send failed for {purpose}: {fallback.detail}")
                    except Exception as sms_error:
                        print(f"[OTP_SMS] Fallback send failed for {purpose}: {sms_error}")

                asyncio.create_task(_dispatch_sms_fallback())
                return
            user.email_otp_last_sent_at = 0
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Email delivery is unavailable. Please try again later.",
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[OTP_EMAIL] Email send failed for {purpose}: {e}")
        if channel != "sms" and user.phone:
            async def _dispatch_sms_fallback() -> None:
                try:
                    fallback = await asyncio.to_thread(
                        send_sms,
                        to_number=user.phone,
                        body_text=body_text,
                    )
                    if not fallback.delivered:
                        print(f"[OTP_SMS] Fallback send failed for {purpose}: {fallback.detail}")
                except Exception as sms_error:
                    print(f"[OTP_SMS] Fallback send failed for {purpose}: {sms_error}")

            asyncio.create_task(_dispatch_sms_fallback())
            return
        user.email_otp_last_sent_at = 0
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery is unavailable. Please try again later.",
        )


def _smoke_otp_code(env_var: str | None) -> str | None:
    if not env_var:
        return None
    allow_flag = (os.getenv("ALLOW_SMOKE_OTPS") or "").strip().lower()
    if allow_flag not in ("1", "true", "yes"):
        return None

    # Never allow fixed/smoke OTPs outside explicit local/dev/test environments.
    # This protects prod even if ALLOW_SMOKE_OTPS accidentally gets set.
    env = (
        os.getenv("ENV")
        or os.getenv("BACKEND_ENVIRONMENT")
        or os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("NODE_ENV")
        or "local"
    ).strip().lower()
    if env not in ("local", "dev", "development", "test", "testing"):
        return None

    smoke_code = (os.getenv(env_var) or "").strip()
    return smoke_code or None


def _check_otp(user: User, code: str) -> None:
    if not user.email_otp_hash or not user.email_otp_expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending code")

    if now_ts() > int(user.email_otp_expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code expired")

    attempts = int(user.email_otp_attempts or 0)
    if attempts >= 8:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")

    expected = user.email_otp_hash
    if hash_code(code) != expected:
        user.email_otp_attempts = attempts + 1
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")


def _clear_otp(user: User) -> None:
    user.email_otp_hash = None
    user.email_otp_expires_at = None
    user.email_otp_last_sent_at = None
    user.email_otp_attempts = 0


def _build_auth_response(user: User, *, is_email_verified: Optional[bool] = None) -> AuthResponse:
    is_admin = user.email.lower() in admin_emails()
    return AuthResponse(
        access_token=create_access_token(user_id=user.id),
        refresh_token=create_refresh_token(user_id=user.id),
        user_id=user.id,
        user_uuid=_public_user_uuid(user),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        is_email_verified=bool(user.is_email_verified) if is_email_verified is None else is_email_verified,
        is_admin=is_admin,
    )


async def _get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    normalized = (email or "").strip().lower()
    if not normalized:
        return None

    # Case-insensitive lookup to tolerate legacy rows stored with mixed-case emails.
    res = await db.execute(auth_safe_user_by_email_query(normalized))
    return res.scalars().first()


async def _get_user_by_phone(db: AsyncSession, phone: str) -> Optional[User]:
    normalized = normalize_phone_for_storage(phone)
    if not normalized:
        return None

    res = await db.execute(auth_safe_user_by_phone_query(normalized))
    return res.scalars().first()


async def _get_user_by_identifier(db: AsyncSession, identifier: str) -> Optional[User]:
    raw = (identifier or "").strip()
    if not raw:
        return None
    if is_phone_identifier(raw):
        return await _get_user_by_phone(db, raw)
    return await _get_user_by_email(db, raw)


def _resolve_signup_identity(payload: SignupRequest, role: str) -> tuple[str, Optional[str], str]:
    raw_identifier = (payload.email or "").strip()
    raw_phone = (payload.phone or "").strip()

    if is_phone_identifier(raw_identifier):
        normalized_phone = normalize_phone_for_storage(raw_phone or raw_identifier)
        if not normalized_phone:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid phone number")
        return build_phone_alias_email(normalized_phone, role=role), normalized_phone, "phone"

    normalized_email = _normalize_email_identifier(raw_identifier)

    normalized_phone = normalize_phone_for_storage(raw_phone) or None
    return normalized_email, normalized_phone, "email"


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _normalize_role(role: Optional[str]) -> str:
    normalized = (role or "client").strip().lower()
    if normalized not in {"client", "pilot"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role. Use client or pilot.")
    return normalized


def _derive_names_from_email(email: str) -> tuple[str, str]:
    base = email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
    if not base:
        return "Customer", ""
    parts = [part for part in base.split() if part]
    first = parts[0].title() if parts else "Customer"
    last = " ".join(part.title() for part in parts[1:]) if len(parts) > 1 else ""
    return first, last


def _verify_google_credential(credential: str) -> dict:
    raw_client_ids = (
        os.getenv("GOOGLE_OAUTH_CLIENT_IDS")
        or os.getenv("GOOGLE_CLIENT_IDS")
        or ""
    ).strip()
    client_ids = [client_id.strip() for client_id in raw_client_ids.split(",") if client_id.strip()]
    legacy_client_id = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    if legacy_client_id:
        client_ids.append(legacy_client_id)
    client_ids = list(dict.fromkeys(client_ids))
    if not client_ids:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google sign-in is not configured",
        )
    try:
        import importlib

        google_id_token = importlib.import_module("google.oauth2.id_token")
        google_requests = importlib.import_module("google.auth.transport.requests")

        audience = client_ids if len(client_ids) > 1 else client_ids[0]
        info = google_id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience,
        )
    except ModuleNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google sign-in dependency is missing",
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credential")

    if not info.get("email"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google account missing email")
    if info.get("email_verified") is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email is not verified")
    return info


def _allowed_oauth_origins() -> set[str]:
    # Prefer explicit OAUTH_ALLOWED_ORIGINS; fall back to CORS_ALLOW_ORIGINS.
    raw = (os.getenv("OAUTH_ALLOWED_ORIGINS") or os.getenv("CORS_ALLOW_ORIGINS") or "").strip()
    values = [v.strip().rstrip("/") for v in raw.split(",") if v.strip()]
    allowed = set(values)
    if allowed and not _is_production_env():
        # Local Google OAuth popup testing should keep working even when a
        # developer copies production OAUTH_ALLOWED_ORIGINS into their .env.
        allowed.update({"http://localhost:3000", "http://127.0.0.1:3000"})
    return allowed


def _oauth_origin_status(origin: str) -> tuple[str, bool, str]:
    normalized_origin = (origin or "").strip().rstrip("/")
    if not normalized_origin:
        return "", False, "Missing origin"

    parsed = urlparse(normalized_origin)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return normalized_origin, False, "Invalid origin"

    allowed = _allowed_oauth_origins()
    if allowed and normalized_origin not in allowed:
        return normalized_origin, False, "Origin is not allowed"

    return normalized_origin, True, ""


def _validate_frontend_origin(origin: str) -> str:
    origin = (origin or "").strip().rstrip("/")
    if not origin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing origin")
    parsed = urlparse(origin)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid origin")
    allowed = _allowed_oauth_origins()
    if allowed and origin not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Origin is not allowed")
    return origin


def _google_oauth_token_config_status() -> tuple[bool, str]:
    raw_client_ids = (
        os.getenv("GOOGLE_OAUTH_CLIENT_IDS")
        or os.getenv("GOOGLE_CLIENT_IDS")
        or ""
    ).strip()
    client_ids = [client_id.strip() for client_id in raw_client_ids.split(",") if client_id.strip()]
    legacy_client_id = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    if legacy_client_id:
        client_ids.append(legacy_client_id)

    if not client_ids:
        return False, "Google sign-in is not configured"

    return True, ""


def _google_oauth_redirect_config_status(*, role: str) -> tuple[bool, str]:
    try:
        _google_oauth_config(role=role)
    except HTTPException as exc:
        return False, str(exc.detail)
    return True, ""


def _apple_oauth_redirect_config_status(*, role: str) -> tuple[bool, str]:
    client_id, redirect_uri = _apple_oauth_config(role=role)
    team_id = (os.getenv("APPLE_TEAM_ID") or "").strip()
    key_id = (os.getenv("APPLE_KEY_ID") or "").strip()
    private_key = _apple_private_key()
    if not (client_id and redirect_uri and team_id and key_id and private_key):
        return False, "Apple sign-in is not configured"
    return True, ""


def _build_oauth_flow_status(*, configured: bool, origin_allowed: bool, reason: str = "") -> OAuthFlowStatus:
    enabled = bool(configured and origin_allowed)
    return OAuthFlowStatus(
        enabled=enabled,
        configured=bool(configured),
        origin_allowed=bool(origin_allowed),
        reason=(None if enabled else (reason or None)),
    )


def _create_oauth_state(
    *,
    provider: str,
    origin: str,
    role: str,
    popup: bool,
    nonce: str | None = None,
    allow_pilot_signup: bool | None = None,
    native_redirect_uri: str | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "aud": "oauth-state",
        "iat": now,
        "exp": now + 10 * 60,
        "provider": provider,
        "origin": origin,
        "role": role,
        "popup": bool(popup),
    }
    if nonce:
        payload["nonce"] = nonce
    if allow_pilot_signup is not None:
        payload["allow_pilot_signup"] = bool(allow_pilot_signup)
    if native_redirect_uri:
        payload["native_redirect_uri"] = native_redirect_uri
    return jose_jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_oauth_state(state: str) -> dict[str, Any]:
    try:
        data = jose_jwt.decode(state, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], audience="oauth-state")
        if not isinstance(data, dict):
            raise ValueError("Invalid state")
        return data
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired state")


def _validate_native_redirect_uri(value: str | None) -> str:
    uri = (value or "").strip()
    if not uri:
        return ""
    parsed = urlparse(uri)
    if parsed.scheme != "errandbridge" or parsed.netloc != "auth":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid native redirect URI")
    return uri


_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


async def _get_jwks(jwks_url: str) -> dict[str, Any]:
    # Cache for 15 minutes (keys rarely change; this avoids extra latency).
    now = time.time()
    cached = _JWKS_CACHE.get(jwks_url)
    if cached and (now - cached[0]) < 15 * 60:
        return cached[1]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        jwks = resp.json()
        if not isinstance(jwks, dict) or "keys" not in jwks:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid JWKS response")
        _JWKS_CACHE[jwks_url] = (now, jwks)
        return jwks


async def _verify_oidc_id_token(
    *,
    id_token: str,
    jwks_url: str,
    audience: str,
    issuer: str,
    nonce: str | None = None,
) -> dict[str, Any]:
    if not id_token or len(id_token) < 10:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing id_token")
    try:
        header = jose_jwt.get_unverified_header(id_token)
        kid = header.get("kid")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid id_token")

    jwks = await _get_jwks(jwks_url)
    keys = jwks.get("keys") or []
    key = next((k for k in keys if k.get("kid") == kid), None)
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown token key")
    try:
        claims = jose_jwt.decode(
            id_token,
            key,
            algorithms=[key.get("alg") or "RS256"],
            audience=audience,
            issuer=issuer,
        )
        if nonce and claims.get("nonce") != nonce:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token nonce")
        return claims
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid id_token")


def _api_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _login_code_session_minutes() -> int:
    raw = (os.getenv("LOGIN_CODE_SESSION_MINUTES") or "60").strip()
    try:
        minutes = int(raw)
    except ValueError:
        minutes = 60
    return max(5, min(minutes, 24 * 60))


def _decode_login_link_token(link_token: str) -> dict[str, Any]:
    try:
        data = jose_jwt.decode(
            link_token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            audience="login-link",
        )
        if not isinstance(data, dict):
            raise ValueError("Invalid link token")
        return data
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired link token")


async def _get_user_from_login_link_token(db: AsyncSession, link_token: str) -> User:
    data = _decode_login_link_token(link_token)
    subject = str(data.get("sub") or "").strip()
    identifier = str(
        data.get("identifier")
        or data.get("email")
        or data.get("phone")
        or ""
    ).strip()

    user: User | None = None
    if subject:
        try:
            user_id = int(subject)
        except ValueError:
            user_id = None
        if user_id is not None:
            user = await db.get(User, user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
        else:
            user = await _get_user_by_identifier(db, subject)

    if not user and identifier:
        user = await _get_user_by_identifier(db, identifier)

    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired link token")
    return user


def _assert_user_role_allowed(user: User, role: str) -> None:
    if role == "pilot" and not user.is_pilot:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not registered as a pilot",
        )


def _login_code_destination(user: User, requested_channel: OtpChannel) -> tuple[OtpChannel, str | None]:
    channel: OtpChannel = requested_channel if requested_channel in ("email", "sms") else DEFAULT_OTP_CHANNEL
    if channel == "sms" and not user.phone:
        channel = "email"
    if channel == "sms":
        phone = str(user.phone or "")
        return channel, ("***" if len(phone) <= 4 else f"***{phone[-4:]}")
    return channel, _mask_email(user.email)


@tso_router.post("/request-code", response_model=LoginCodeRequestResponse)
@login_router.post("/request-code", response_model=LoginCodeRequestResponse)
async def login_request_code(
    payload: LoginCodeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginCodeRequestResponse:
    """Request a one-time access code using the link token."""
    role = _normalize_role(payload.role)
    user = await _get_user_from_login_link_token(db, payload.link_token)
    _assert_user_role_allowed(user, role)

    if not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified")

    delivery_channel, masked_destination = _login_code_destination(user, payload.otp_delivery_channel)
    await _send_otp_for_user(
        db,
        user,
        purpose="login",
        channel=delivery_channel,
        mode=payload.otp_delivery_mode,
        smoke_env="SMOKE_LOGIN_OTP",
    )
    return LoginCodeRequestResponse(
        status="SUCCESS",
        code=0,
        message="Code sent",
        data={
            "deliveryChannel": delivery_channel,
            "maskedDestination": masked_destination,
            "expiresInSeconds": 10 * 60,
        },
        timestamp=_api_timestamp(),
        error=None,
        path=request.url.path,
    )


@tso_router.post("/verify", response_model=LoginCodeVerifyResponse)
@login_router.post("/verify", response_model=LoginCodeVerifyResponse)
async def login_verify_code(
    payload: LoginCodeVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginCodeVerifyResponse:
    """Verify the code and obtain a time-limited session token."""
    role = _normalize_role(payload.role)
    user = await _get_user_from_login_link_token(db, payload.link_token)
    _assert_user_role_allowed(user, role)

    if not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified")

    try:
        _check_otp(user, payload.code)
    except HTTPException as e:
        if e.detail == "Invalid code":
            await db.commit()
        raise

    _clear_otp(user)
    await db.commit()

    session_minutes = _login_code_session_minutes()
    session_token = create_access_token(user_id=user.id, expires_minutes=session_minutes)
    refresh_token = create_refresh_token(user_id=user.id)
    return LoginCodeVerifyResponse(
        status="SUCCESS",
        code=0,
        message="Code verified",
        data={
            "sessionToken": session_token,
            "refreshToken": refresh_token,
            "userUuid": _public_user_uuid(user),
            "expiresInSeconds": session_minutes * 60,
            "tokenType": "bearer",
        },
        timestamp=_api_timestamp(),
        error=None,
        path=request.url.path,
    )


async def _get_or_create_oauth_user(
    *,
    db: AsyncSession,
    email: str,
    role: str,
    first_name: str | None,
    last_name: str | None,
    allow_pilot_signup: bool = False,
) -> User:
    role = _normalize_role(role)
    email = (email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider account missing email")

    user = await _get_user_by_email(db, email)
    if user:
        if role == "pilot" and not user.is_pilot:
            if allow_pilot_signup:
                user.is_pilot = True
            else:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is not registered as a pilot")
        if not user.is_email_verified:
            user.is_email_verified = True
        return user

    if role == "pilot" and not allow_pilot_signup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pilot sign-up is not enabled for this sign-in attempt",
        )

    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    if not fn and not ln:
        fn, ln = _derive_names_from_email(email)

    random_password = secrets.token_urlsafe(32)
    user = User(
        email=email,
        password_hash=hash_password(random_password),
        first_name=fn or "Customer",
        last_name=ln or "",
        is_email_verified=True,
        is_pilot=(role == "pilot"),
        address_verification_status=("pending_manual" if role == "pilot" else "pending"),
        id_verification_status=("pending" if role == "pilot" else "pending"),
    )
    db.add(user)
    return user


def _oauth_popup_result_html(*, origin: str, ok: bool, provider: str, access_token: str = "", error: str = "", native_redirect_uri: str = "") -> str:
    safe_origin = origin.replace("\"", "")
    payload = {
        "type": "errandbridge_oauth_result",
        "ok": bool(ok),
        "provider": provider,
        "access_token": access_token or "",
        "error": error or "",
    }
    native_redirect_url = ""
    if native_redirect_uri:
        separator = "&" if "?" in native_redirect_uri else "?"
        native_redirect_url = native_redirect_uri + separator + urlencode({
            "ok": "1" if ok else "0",
            "provider": provider,
            "access_token": access_token or "",
            "error": error or "",
        })
    # This page is served from the API domain; it posts a message back to the frontend origin.
    return """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Sign-in complete</title>
  </head>
  <body style=\"font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; padding: 24px;\">
        <div id=\"status\" style=\"font-size: 18px; font-weight: 600;\">Completing sign-in…</div>
        <div id=\"detail\" style=\"margin-top: 8px; color: #444;\"></div>
        <button id=\"close\" style=\"margin-top: 16px; padding: 10px 14px; border-radius: 10px; border: 1px solid #ddd; background: #fff; cursor: pointer;\">
            Close window
        </button>
    <script>
      (function () {
        var targetOrigin = """ + json.dumps(safe_origin) + """;
        var payload = """ + json.dumps(payload) + """;
        var nativeRedirectUrl = """ + json.dumps(native_redirect_url) + """;
                try {
                    var statusEl = document.getElementById('status');
                    var detailEl = document.getElementById('detail');
                    var closeBtn = document.getElementById('close');
                    if (statusEl) {
                        statusEl.textContent = payload.ok ? 'Sign-in complete.' : 'Sign-in failed.';
                    }
                    if (detailEl) {
                        detailEl.textContent = payload.ok
                            ? 'You can return to ErrandBridge.'
                            : (payload.error || 'Please try again.');
                    }
                    if (closeBtn) {
                        closeBtn.addEventListener('click', function () {
                            try { window.close(); } catch (e) { /* ignore */ }
                        });
                    }
                } catch (e) {
                    // ignore
                }
        if (nativeRedirectUrl) {
          try {
            window.location.href = nativeRedirectUrl;
          } catch (e) {
            // fall back to postMessage below
          }
        }
        try {
          if (window.opener && typeof window.opener.postMessage === 'function') {
            window.opener.postMessage(payload, targetOrigin);
          }
        } catch (e) {
          // ignore
        }
                setTimeout(function () {
                    try { window.close(); } catch (e) { /* ignore */ }
                }, 120);
      })();
    </script>
  </body>
</html>"""


def _apple_private_key() -> str:
    key = (os.getenv("APPLE_PRIVATE_KEY") or "").strip()
    if not key:
        return ""

    # Allow either the PEM contents directly or a path to the downloaded .p8 file.
    candidate = os.path.expanduser(key)
    if os.path.isfile(candidate):
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                key = fh.read().strip()
        except OSError:
            return ""

    # GitHub Secrets often store multiline values with literal \n.
    if "\\n" in key and "\n" not in key:
        key = key.replace("\\n", "\n")
    return key


def _apple_client_secret(*, client_id: str) -> str:
    team_id = (os.getenv("APPLE_TEAM_ID") or "").strip()
    key_id = (os.getenv("APPLE_KEY_ID") or "").strip()
    client_id = (client_id or "").strip()
    private_key = _apple_private_key()
    if not (team_id and key_id and client_id and private_key):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Apple sign-in is not configured")

    now = int(time.time())
    # Apple allows up to 6 months; keep it short-lived.
    exp = now + 15 * 60
    headers = {"kid": key_id}
    payload = {
        "iss": team_id,
        "iat": now,
        "exp": exp,
        "aud": "https://appleid.apple.com",
        "sub": client_id,
    }
    try:
        return jose_jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to generate Apple client secret")


def _apple_oauth_config(*, role: str) -> tuple[str, str]:
    """Return the Apple OAuth client_id + redirect_uri for the requested role.

    Defaults to APPLE_CLIENT_ID / APPLE_REDIRECT_URI for customers.
    Pilots can optionally override via APPLE_PILOT_CLIENT_ID / APPLE_PILOT_REDIRECT_URI.
    """

    role = _normalize_role(role)
    if role == "pilot":
        client_id = (
            os.getenv("APPLE_PILOT_CLIENT_ID")
            or os.getenv("APPLE_CLIENT_ID")
            or ""
        ).strip()
        redirect_uri = (
            os.getenv("APPLE_PILOT_REDIRECT_URI")
            or os.getenv("APPLE_REDIRECT_URI")
            or ""
        ).strip()
    else:
        client_id = (os.getenv("APPLE_CLIENT_ID") or "").strip()
        redirect_uri = (os.getenv("APPLE_REDIRECT_URI") or "").strip()
    return client_id, redirect_uri


def _google_oauth_config(*, role: str) -> tuple[str, str, str]:
    """Return Google OAuth redirect-flow config for the requested role.

    Defaults to GOOGLE_OAUTH_* (or legacy GOOGLE_* aliases).
    Pilots can optionally override via GOOGLE_OAUTH_PILOT_*.
    """

    role = _normalize_role(role)
    if role == "pilot":
        client_id = (
            os.getenv("GOOGLE_OAUTH_PILOT_CLIENT_ID")
            or os.getenv("GOOGLE_OAUTH_CLIENT_ID")
            or os.getenv("GOOGLE_CLIENT_ID")
            or ""
        ).strip()
        client_secret = (
            os.getenv("GOOGLE_OAUTH_PILOT_CLIENT_SECRET")
            or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
            or os.getenv("GOOGLE_CLIENT_SECRET")
            or ""
        ).strip()
        redirect_uri = (
            os.getenv("GOOGLE_OAUTH_PILOT_REDIRECT_URI")
            or os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
            or os.getenv("GOOGLE_REDIRECT_URI")
            or ""
        ).strip()
    else:
        client_id = (
            os.getenv("GOOGLE_OAUTH_CLIENT_ID")
            or os.getenv("GOOGLE_CLIENT_ID")
            or ""
        ).strip()
        client_secret = (
            os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
            or os.getenv("GOOGLE_CLIENT_SECRET")
            or ""
        ).strip()
        redirect_uri = (
            os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
            or os.getenv("GOOGLE_REDIRECT_URI")
            or ""
        ).strip()
    if not (client_id and client_secret and redirect_uri):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google OAuth is not configured")
    return client_id, client_secret, redirect_uri


async def _verify_google_id_token(*, id_token: str, audience: str, nonce: str | None) -> dict[str, Any]:
    # Google may use either issuer value.
    last_error: HTTPException | None = None
    for issuer in ("https://accounts.google.com", "accounts.google.com"):
        try:
            return await _verify_oidc_id_token(
                id_token=id_token,
                jwks_url="https://www.googleapis.com/oauth2/v3/certs",
                audience=audience,
                issuer=issuer,
                nonce=nonce,
            )
        except HTTPException as e:
            last_error = e
            continue
    raise last_error or HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid id_token")


@router.get("/oauth/status", response_model=OAuthStatusResponse)
async def oauth_status(
    origin: str = Query(..., description="Frontend origin"),
    role: Optional[str] = Query(default="client"),
) -> OAuthStatusResponse:
    role = _normalize_role(role)
    normalized_origin, origin_allowed, origin_reason = _oauth_origin_status(origin)

    google_redirect_configured, google_redirect_reason = _google_oauth_redirect_config_status(role=role)
    google_token_configured, google_token_reason = _google_oauth_token_config_status()
    apple_redirect_configured, apple_redirect_reason = _apple_oauth_redirect_config_status(role=role)

    return OAuthStatusResponse(
        origin=normalized_origin,
        role=role,
        google=GoogleOAuthStatus(
            redirect=_build_oauth_flow_status(
                configured=google_redirect_configured,
                origin_allowed=origin_allowed,
                reason=origin_reason if not origin_allowed else google_redirect_reason,
            ),
            token=_build_oauth_flow_status(
                configured=google_token_configured,
                origin_allowed=True,
                reason=google_token_reason,
            ),
        ),
        apple=AppleOAuthStatus(
            redirect=_build_oauth_flow_status(
                configured=apple_redirect_configured,
                origin_allowed=origin_allowed,
                reason=origin_reason if not origin_allowed else apple_redirect_reason,
            ),
        ),
    )


@router.get("/oauth/apple/start")
async def apple_oauth_start(
    origin: str = Query(..., description="Frontend origin"),
    role: Optional[str] = Query(default="client"),
    popup: bool = Query(default=True),
    mode: Optional[str] = Query(default=None),
    allow_pilot_signup: bool = Query(default=False),
    native_redirect_uri: Optional[str] = Query(default=None),
) -> Response:
    origin = _validate_frontend_origin(origin)
    native_redirect_uri = _validate_native_redirect_uri(native_redirect_uri)
    role = _normalize_role(role)
    client_id, redirect_uri = _apple_oauth_config(role=role)
    if not (client_id and redirect_uri):
        if popup:
            return HTMLResponse(
                content=_oauth_popup_result_html(origin=origin, ok=False, provider="apple", error="Apple sign-in is not configured"),
                status_code=status.HTTP_200_OK,
            )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Apple sign-in is not configured")

    nonce = secrets.token_urlsafe(18)
    state = _create_oauth_state(
        provider="apple",
        origin=origin,
        role=role,
        popup=popup,
        nonce=nonce,
        allow_pilot_signup=(allow_pilot_signup if role == "pilot" else None),
        native_redirect_uri=native_redirect_uri or None,
    )
    params = {
        "response_type": "code",
        "response_mode": "form_post",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "name email",
        "state": state,
        "nonce": nonce,
    }
    url = f"https://appleid.apple.com/auth/authorize?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.post("/oauth/apple/callback")
async def apple_oauth_callback(
    request: Request,
    code: str = Form(default=""),
    state: str = Form(default=""),
    user: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    data = _decode_oauth_state(state)
    if data.get("provider") != "apple":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid provider state")
    origin = _validate_frontend_origin(str(data.get("origin") or ""))
    role = _normalize_role(str(data.get("role") or "client"))
    nonce = (data.get("nonce") or "").strip() or None
    allow_pilot_signup = bool(data.get("allow_pilot_signup"))
    native_redirect_uri = _validate_native_redirect_uri(data.get("native_redirect_uri"))

    client_id, redirect_uri = _apple_oauth_config(role=role)

    try:
        client_secret = _apple_client_secret(client_id=client_id)
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://appleid.apple.com/auth/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            resp.raise_for_status()
            token_payload = resp.json()
            id_token = token_payload.get("id_token") or ""
            claims = await _verify_oidc_id_token(
                id_token=id_token,
                jwks_url="https://appleid.apple.com/auth/keys",
                audience=client_id,
                issuer="https://appleid.apple.com",
                nonce=nonce,
            )

        email = (claims.get("email") or "").strip().lower()
        first_name = ""
        last_name = ""
        # Apple sends name only once via the `user` form field.
        if user:
            try:
                user_obj = json.loads(user)
                name = (user_obj.get("name") or {}) if isinstance(user_obj, dict) else {}
                first_name = (name.get("firstName") or "").strip()
                last_name = (name.get("lastName") or "").strip()
            except Exception:
                pass

        app_user = await _get_or_create_oauth_user(
            db=db,
            email=email,
            role=role,
            first_name=first_name,
            last_name=last_name,
            allow_pilot_signup=(allow_pilot_signup if role == "pilot" else False),
        )
        await db.commit()
        await db.refresh(app_user)
        access_token = create_access_token(user_id=app_user.id)
        return HTMLResponse(
            content=_oauth_popup_result_html(origin=origin, ok=True, provider="apple", access_token=access_token, native_redirect_uri=native_redirect_uri),
            status_code=status.HTTP_200_OK,
        )
    except HTTPException as e:
        return HTMLResponse(
            content=_oauth_popup_result_html(origin=origin, ok=False, provider="apple", error=str(e.detail), native_redirect_uri=native_redirect_uri),
            status_code=status.HTTP_200_OK,
        )
    except Exception:
        return HTMLResponse(
            content=_oauth_popup_result_html(origin=origin, ok=False, provider="apple", error="Apple sign-in failed", native_redirect_uri=native_redirect_uri),
            status_code=status.HTTP_200_OK,
        )


@router.get("/oauth/google/start")
async def google_oauth_start(
    origin: str = Query(..., description="Frontend origin"),
    role: Optional[str] = Query(default="client"),
    popup: bool = Query(default=True),
    mode: Optional[str] = Query(default=None),
    allow_pilot_signup: bool = Query(default=False),
    native_redirect_uri: Optional[str] = Query(default=None),
) -> Response:
    origin = _validate_frontend_origin(origin)
    native_redirect_uri = _validate_native_redirect_uri(native_redirect_uri)
    role = _normalize_role(role)
    try:
        client_id, _client_secret, redirect_uri = _google_oauth_config(role=role)
    except HTTPException as e:
        if popup:
            return HTMLResponse(
                content=_oauth_popup_result_html(origin=origin, ok=False, provider="google", error=str(e.detail)),
                status_code=status.HTTP_200_OK,
            )
        raise

    nonce = secrets.token_urlsafe(18)
    state = _create_oauth_state(
        provider="google",
        origin=origin,
        role=role,
        popup=popup,
        nonce=nonce,
        allow_pilot_signup=(allow_pilot_signup if role == "pilot" else None),
        native_redirect_uri=native_redirect_uri or None,
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        # Keep the experience predictable in popup flows.
        "prompt": "select_account",
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/oauth/google/callback")
async def google_oauth_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    data = _decode_oauth_state(state)
    if data.get("provider") != "google":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid provider state")
    origin = _validate_frontend_origin(str(data.get("origin") or ""))
    role = _normalize_role(str(data.get("role") or "client"))
    nonce = (data.get("nonce") or "").strip() or None
    allow_pilot_signup = bool(data.get("allow_pilot_signup"))
    native_redirect_uri = _validate_native_redirect_uri(data.get("native_redirect_uri"))

    if error:
        message = (error_description or error or "Google sign-in failed").strip()
        return HTMLResponse(
            content=_oauth_popup_result_html(origin=origin, ok=False, provider="google", error=message, native_redirect_uri=native_redirect_uri),
            status_code=status.HTTP_200_OK,
        )
    if not code:
        return HTMLResponse(
            content=_oauth_popup_result_html(origin=origin, ok=False, provider="google", error="Missing authorization code", native_redirect_uri=native_redirect_uri),
            status_code=status.HTTP_200_OK,
        )

    client_id, client_secret, redirect_uri = _google_oauth_config(role=role)
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            resp.raise_for_status()
            token_payload = resp.json()
            id_token = token_payload.get("id_token") or ""
            claims = await _verify_google_id_token(id_token=id_token, audience=client_id, nonce=nonce)

        email = (claims.get("email") or "").strip().lower()
        if claims.get("email_verified") is False:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email is not verified")
        first_name = (claims.get("given_name") or "").strip()
        last_name = (claims.get("family_name") or "").strip()

        app_user = await _get_or_create_oauth_user(
            db=db,
            email=email,
            role=role,
            first_name=first_name,
            last_name=last_name,
            allow_pilot_signup=(allow_pilot_signup if role == "pilot" else False),
        )
        await db.commit()
        await db.refresh(app_user)
        access_token = create_access_token(user_id=app_user.id)
        return HTMLResponse(
            content=_oauth_popup_result_html(origin=origin, ok=True, provider="google", access_token=access_token, native_redirect_uri=native_redirect_uri),
            status_code=status.HTTP_200_OK,
        )
    except HTTPException as e:
        return HTMLResponse(
            content=_oauth_popup_result_html(origin=origin, ok=False, provider="google", error=str(e.detail), native_redirect_uri=native_redirect_uri),
            status_code=status.HTTP_200_OK,
        )
    except Exception:
        return HTMLResponse(
            content=_oauth_popup_result_html(origin=origin, ok=False, provider="google", error="Google sign-in failed", native_redirect_uri=native_redirect_uri),
            status_code=status.HTTP_200_OK,
        )

@router.post("/signup", response_model=AuthResponse)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    import os
    from database import DATABASE_URL, _redact_database_url
    disable_email_confirmation = is_email_confirmation_disabled()
    role = _normalize_role(payload.role)
    email, normalized_phone, identifier_kind = _resolve_signup_identity(payload, role)

    print(f"[SIGNUP] Signup attempt for: {email}", flush=True)
    print(f"[SIGNUP] Database URL being used: {_redact_database_url(DATABASE_URL)}", flush=True)
    print(f"[SIGNUP] ENV={os.getenv('ENV')}", flush=True)
    try:
        existing = (
            await _get_user_by_phone(db, normalized_phone)
            if identifier_kind == "phone"
            else await _get_user_by_email(db, email)
        )
        phone_owner = await _get_user_by_phone(db, normalized_phone) if normalized_phone else None
        print(f"[SIGNUP] Email lookup result - existing user: {existing}", flush=True)
    except Exception as e:
        print(f"[SIGNUP] Error during email lookup: {e}", flush=True)
        _raise_db_unavailable(e)

    if phone_owner and (not existing or phone_owner.id != existing.id):
        if phone_owner.is_pilot != (role == "pilot"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number already registered for a different account type")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number already registered")

    first_name = (payload.first_name or "").strip()
    last_name = (payload.last_name or "").strip()
    if not first_name or not last_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="First and last name are required for signup.",
        )

    if existing:
        if existing.is_pilot != (role == "pilot"):
            conflict_label = "Phone number" if identifier_kind == "phone" else "Email"
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{conflict_label} already registered for a different account type")
        if not existing.is_email_verified:
            if disable_email_confirmation:
                existing.is_email_verified = True
                existing.email_otp_hash = None
                existing.email_otp_expires_at = None
                existing.email_otp_last_sent_at = None
                existing.email_otp_attempts = 0
                await db.commit()
                return _build_auth_response(existing, is_email_verified=True)
            await _send_otp_for_user(
                db,
                existing,
                purpose="signup confirmation",
                channel=("sms" if identifier_kind == "phone" else payload.otp_delivery_channel),
                mode=payload.otp_delivery_mode,
                smoke_env="SMOKE_OTP_CODE",
            )
            return _build_auth_response(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Phone number already registered" if identifier_kind == "phone" else "Email already registered"),
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        first_name=first_name,
        last_name=last_name,
        phone=normalized_phone,
        id_verification_method=("offline" if payload.id_collected_offline else None),
        id_verification_status=("pending" if payload.id_collected_offline else "pending"),
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        country=payload.country,
        address_verification_status=("pending" if any([
            payload.address_line1,
            payload.city,
            payload.state,
            payload.postal_code,
            payload.country,
        ]) else "pending"),
        is_email_verified=disable_email_confirmation,
        is_pilot=(role == "pilot"),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    if not disable_email_confirmation:
        await _send_otp_for_user(
            db,
            user,
            purpose="signup confirmation",
            channel=("sms" if identifier_kind == "phone" else payload.otp_delivery_channel),
            mode=payload.otp_delivery_mode,
            smoke_env="SMOKE_OTP_CODE",
        )

    # Signup now returns a token but the account is unverified until /auth/confirm succeeds.
    return _build_auth_response(user)


@router.post("/swagger-login", include_in_schema=False)
async def swagger_login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """Dedicated login endpoint for Swagger UI's Authorize button."""
    payload = LoginRequest(email=form_data.username, password=form_data.password)
    auth_response = await login(payload=payload, db=db)
    return {"access_token": auth_response.token, "token_type": "bearer"}


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    disable_email_confirmation = is_email_confirmation_disabled()
    identifier = (payload.email or "").strip()
    role = _normalize_role(payload.role)
    print(f"[AUTH] Login attempt for: {identifier}", flush=True)
    try:
        user = await _get_user_by_identifier(db, identifier)
        print(f"[AUTH] User lookup result: {user}", flush=True)
    except Exception as e:
        print(f"[AUTH] Error during user lookup: {e}", flush=True)
        _raise_db_unavailable(e)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    try:
        password_ok = verify_password(payload.password, user.password_hash)
    except Exception as e:
        print(f"[AUTH] Error verifying password for {payload.email}: {e}", flush=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    # Block login for unverified users (should always pass now)
    if not disable_email_confirmation and not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox or resend the confirmation code.",
        )

    if role == "pilot" and not user.is_pilot:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not registered as a pilot",
        )

    return _build_auth_response(user)


@router.post("/google", response_model=AuthResponse)
async def google_auth(payload: GoogleAuthRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    role = _normalize_role(payload.role)
    info = _verify_google_credential(payload.credential)

    email = str(info.get("email", "")).strip().lower()
    given_name = (info.get("given_name") or "").strip()
    family_name = (info.get("family_name") or "").strip()
    try:
        user = await _get_or_create_oauth_user(
            db=db,
            email=email,
            role=role,
            first_name=given_name,
            last_name=family_name,
            allow_pilot_signup=(payload.allow_pilot_signup if role == "pilot" else False),
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        print(f"[AUTH] Google auth user lookup failed: {e}", flush=True)
        _raise_db_unavailable(e)

    if role == "pilot":
        current_address_status = (user.address_verification_status or "").strip().lower()
        if not current_address_status or current_address_status == "pending":
            user.address_verification_status = "pending_manual"
        if not user.id_verification_status:
            user.id_verification_status = "pending"

    await db.commit()
    await db.refresh(user)

    return _build_auth_response(user)


@router.post("/refresh", response_model=AuthResponse)
async def refresh_session(payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """Exchange a valid refresh token for a fresh access token and refresh token."""
    user_id = decode_refresh_token(payload.refresh_token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = await db.get(User, int(user_id), options=AUTH_SAFE_USER_LOAD_OPTIONS)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    if not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified")

    return _build_auth_response(user)


@router.get("/me", response_model=MeResponse)
async def me(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user = await db.get(User, user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
    except Exception as e:
        print(f"[AUTH] /me failed to load user: {e}", flush=True)
        _raise_db_unavailable(e)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified")

    admin_emails_raw = os.getenv("ADMIN_EMAILS", "")
    admin_emails = {e.strip().lower() for e in admin_emails_raw.split(",") if e.strip()}
    is_admin = user.email.lower() in admin_emails

    # Transparency metrics (scoped to the signed-in user)
    # - completed_errands: count of this user's errands with terminal status
    # - documents_handled: total attachments uploaded across all errands
    #
    # IMPORTANT: Use COUNT queries rather than selecting ORM entities.
    # Selecting mapped entities pulls *all mapped columns*; if prod DB migrations
    # lag the code (missing newly-added columns), it can 500 the entire login flow.
    completed_count = 0
    docs_count = 0
    try:
        completed_statuses = {"completed", "accepted", "delivered"}
        completed_q = await db.execute(
            select(func.count(Errand.id)).where(
                Errand.user_id == user_id,
                Errand.status.in_(completed_statuses),
            )
        )
        completed_count = int(completed_q.scalar() or 0)

        docs_q = await db.execute(
            select(func.count(ErrandAttachment.id))
            .select_from(ErrandAttachment)
            .join(Errand, Errand.id == ErrandAttachment.errand_id)
            .where(Errand.user_id == user_id)
        )
        docs_count = int(docs_q.scalar() or 0)
    except Exception as e:
        # Never fail the /auth/me endpoint because of optional metrics.
        # Keep details in logs for follow-up (migration/schema alignment).
        print(f"[AUTH] /me transparency metrics error: {e}", flush=True)
        completed_count = 0
        docs_count = 0

    return MeResponse(
        user_id=user.id,
        user_uuid=_public_user_uuid(user),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        address_line1=user.address_line1,
        address_line2=user.address_line2,
        city=user.city,
        state=user.state,
        postal_code=user.postal_code,
        country=user.country,
        is_email_verified=bool(user.is_email_verified),
        is_admin=is_admin,
        transparency={
            "completed_errands": int(completed_count),
            "documents_handled": int(docs_count),
        },
    )


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change user's password (requires current password)"""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.get(User, user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Verify current password
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    # Update to new password
    user.password_hash = hash_password(payload.new_password)
    await db.commit()

    return {"ok": True, "message": "Password changed successfully"}


@router.post("/deactivate", response_model=DeactivateAccountResponse)
async def deactivate_account(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> DeactivateAccountResponse:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.get(User, user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    random_suffix = secrets.token_hex(4)
    anonymized_email = f"deleted+{user.id}-{random_suffix}@errandbridge.com"
    anonymized_password = hash_password(secrets.token_urlsafe(32))

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            email=anonymized_email,
            password_hash=anonymized_password,
            first_name="Deleted",
            last_name="User",
            phone=None,
            is_email_verified=False,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            postal_code=None,
            country=None,
            date_of_birth=None,
            profile_image_url=None,
            street_address=None,
            state_province=None,
            vehicle_type=None,
            vehicle_make=None,
            vehicle_model=None,
            vehicle_year=None,
            license_plate=None,
            insurance_provider=None,
            insurance_expiry=None,
            rating=None,
        )
    )
    await db.commit()

    return DeactivateAccountResponse(
        ok=True,
        user_id=user.id,
        user_uuid=_public_user_uuid(user),
        email=anonymized_email,
        message="Account deactivated and profile anonymized.",
    )


@router.patch("/profile", response_model=UpdateProfileResponse)
async def update_profile(
    payload: UpdateProfileRequest,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> UpdateProfileResponse:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.get(User, user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified")

    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            first_name=payload.first_name,
            last_name=payload.last_name,
            phone=payload.phone,
        )
    )
    await db.commit()

    user = await db.get(User, user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
    return UpdateProfileResponse(
        ok=True,
        user_id=user.id,
        user_uuid=_public_user_uuid(user),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
    )


    user.street_address = None
    user.state_province = None
    user.vehicle_type = None
    user.vehicle_make = None
    user.vehicle_model = None
    user.vehicle_year = None
    user.license_plate = None
    user.insurance_provider = None
    user.insurance_expiry = None
    user.password_hash = hash_password(secrets.token_urlsafe(18))

    await db.commit()

    return {
        "ok": True,
        "message": "Account deactivated and profile data removed.",
        "user_id": user.id,
    }



@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_email(payload: ConfirmRequest, db: AsyncSession = Depends(get_db)) -> ConfirmResponse:
    disable_email_confirmation = is_email_confirmation_disabled()
    user = await _get_user_by_identifier(db, payload.email)
    if not user:
        # Don't leak which emails exist.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

    if disable_email_confirmation:
        if not user.is_email_verified:
            user.is_email_verified = True
            user.email_otp_hash = None
            user.email_otp_expires_at = None
            user.email_otp_last_sent_at = None
            user.email_otp_attempts = 0
            await db.commit()
        return ConfirmResponse(ok=True)

    if user.is_email_verified:
        return ConfirmResponse(ok=True)

    try:
        _check_otp(user, payload.code)
    except HTTPException as e:
        if e.detail == "Invalid code":
            await db.commit()
        raise

    user.is_email_verified = True
    user.email_otp_hash = None
    user.email_otp_expires_at = None
    user.email_otp_last_sent_at = None
    user.email_otp_attempts = 0
    await db.commit()

    return ConfirmResponse(ok=True)


@router.post("/resend-confirmation", response_model=ConfirmResponse)
async def resend_confirmation(payload: ResendRequest, db: AsyncSession = Depends(get_db)) -> ConfirmResponse:
    disable_email_confirmation = is_email_confirmation_disabled()
    if disable_email_confirmation:
        return ConfirmResponse(ok=True)
    user = await _get_user_by_identifier(db, payload.email)
    # Always return OK (avoid user enumeration)
    if not user or user.is_email_verified:
        return ConfirmResponse(ok=True)

    last_sent = int(user.email_otp_last_sent_at or 0)
    if now_ts() - last_sent < 30:
        # Too soon
        return ConfirmResponse(ok=True)

    await _send_otp_for_user(
        db,
        user,
        purpose="confirmation",
        channel=payload.otp_delivery_channel,
        mode=payload.otp_delivery_mode,
        smoke_env="SMOKE_OTP_CODE",
    )

    return ConfirmResponse(ok=True)


@router.post("/password-reset/start", response_model=PasswordResetStartResponse)
async def password_reset_start(
    payload: PasswordResetStartRequest,
    db: AsyncSession = Depends(get_db),
) -> PasswordResetStartResponse:
    """Start password reset by emailing an OTP.

    This endpoint is intentionally user-enumeration safe.
    """
    user = await _get_user_by_identifier(db, payload.email)
    if not user:
        # Always OK to avoid leaking whether an email exists.
        return PasswordResetStartResponse(ok=True)

    await _send_otp_for_user(
        db,
        user,
        purpose="password reset",
        channel=payload.otp_delivery_channel,
        mode=payload.otp_delivery_mode,
        smoke_env="SMOKE_PASSWORD_RESET_OTP",
    )
    return PasswordResetStartResponse(ok=True)


@router.post("/password-reset/confirm", response_model=PasswordResetConfirmResponse)
async def password_reset_confirm(
    payload: PasswordResetConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> PasswordResetConfirmResponse:
    """Confirm password reset by verifying OTP and setting new password."""
    user = await _get_user_by_identifier(db, payload.email)
    # Enumeration-safe-ish: use same error for unknown users.
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

    try:
        _check_otp(user, payload.code)
    except HTTPException as e:
        # Persist attempt increments when code is invalid.
        if e.detail == "Invalid code":
            await db.commit()
        raise

    user.password_hash = hash_password(payload.new_password)
    # If the user can receive/verify OTP at this email, we can safely mark the email as verified.
    if not user.is_email_verified:
        user.is_email_verified = True
    _clear_otp(user)
    await db.commit()

    return PasswordResetConfirmResponse(ok=True)


@router.post("/password-change/start", response_model=PasswordChangeStartResponse)
async def password_change_start(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> PasswordChangeStartResponse:
    """Start password change (logged-in) by emailing an OTP."""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.get(User, user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified")

    await _send_otp_for_user(db, user, purpose="password change", smoke_env="SMOKE_PASSWORD_CHANGE_OTP")
    return PasswordChangeStartResponse(ok=True)


@router.post("/password-change/confirm", response_model=PasswordChangeConfirmResponse)
async def password_change_confirm(
    payload: PasswordChangeConfirmRequest,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> PasswordChangeConfirmResponse:
    """Confirm password change (logged-in) by verifying OTP and setting new password."""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified")

    try:
        _check_otp(user, payload.code)
    except HTTPException as e:
        if e.detail == "Invalid code":
            await db.commit()
        raise

    user.password_hash = hash_password(payload.new_password)
    _clear_otp(user)
    await db.commit()

    return PasswordChangeConfirmResponse(ok=True)
