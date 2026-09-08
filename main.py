import uuid
from typing import Optional, Literal, Union
from database import AsyncSessionLocal
from schema import schema, _make_reference_number
from app.routes.tracking import router as tracking_router
from app.routes.incidents import router as incidents_router
from app.routes.support import router as support_router
from app.routes.public_reviews import router as public_reviews_router
from app.routes.assistant import router as assistant_router
from app.routes.toxi_structured import router as toxi_structured_router
from app.routes.analytics import router as analytics_router
from app.routes.voice import router as voice_router
from app.routes.errand_messages import router as errand_messages_router
from routes_admin import router as admin_router
import os
import asyncio
import pathlib
import mimetypes
import re
import secrets
import hashlib
from fastapi import FastAPI, HTTPException, status, File, UploadFile, Form, Query
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, Response
from models import (
    User,
    Errand,
    ErrandAttachment,
    AttachmentShareLink,
    ErrandEvent,
    PilotEmploymentApplication,
    PilotEmploymentAttachment,
    ClientSubscription,
    StripeCheckoutSession,
)
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator
from strawberry.fastapi import GraphQLRouter
from starlette.requests import Request
from sqlalchemy import select, update, text
from app.routes.pilot_delivery import router as pilot_delivery_router
from app.routes.pilot_profile import router as pilot_profile_router
from app.routes.user_profile import router as user_profile_router
from app.routes.payments import router as payments_router, webhooks_router
from app.routes.promo_codes import router as promo_codes_router
from routes_auth import router as auth_router
from auth import decode_access_token, hash_password
from auth_user_query import AUTH_SAFE_USER_LOAD_OPTIONS, auth_safe_user_by_email_query
from datetime import datetime, timedelta, timezone
import time
from contextlib import asynccontextmanager
from app.utils.admin_utils import admin_emails
from app.services.storage import (
    build_stored_filename,
    get_storage_config,
    presign_or_stream_key,
    put_bytes,
    s3_key,
)

# Optional OpenAI import (only used if API key is configured)
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

from dotenv import load_dotenv

# ===== IDEMPOTENCY LOCK FOR STARTUP =====
_db_init_lock = asyncio.Lock()
_db_init_done = False


# Load environment variables from .env file (local/dev only)
def _running_in_aws_container() -> bool:
    """Best-effort detection for AWS container runtimes (ECS/Fargate).

    We cannot rely solely on AWS_EXECUTION_ENV, as it isn't always present in ECS.
    """

    markers = (
        "AWS_EXECUTION_ENV",
        "ECS_CONTAINER_METADATA_URI_V4",
        "ECS_CONTAINER_METADATA_URI",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    )
    return any(bool(os.getenv(key)) for key in markers)


_env_name = (os.getenv("ENV") or "local").lower()
_running_in_aws = _running_in_aws_container()
if _env_name == "local" and not _running_in_aws:
    load_dotenv()

print("[STARTUP] Creating FastAPI app...", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await _ensure_admin_accounts()
    except Exception as e:
        print(f"[BOOTSTRAP] Admin bootstrap failed: {str(e)}", flush=True)

    try:
        await _startup_event()
    except Exception as e:
        print(f"[STARTUP] Startup initialization failed: {str(e)}", flush=True)

    yield


print("[STARTUP] FastAPI app created successfully", flush=True)


def _resolve_api_version() -> str:
    explicit = (os.getenv("API_VERSION") or "").strip()
    if explicit:
        return explicit

    version_file = pathlib.Path(__file__).resolve().parent.parent / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass

    return "0.1.0"


OPENAPI_TAGS = [
    {
        "name": "00 System & Health",
        "description": "Operational endpoints for health checks, readiness, version metadata, and deployment smoke tests.",
    },
    {
        "name": "01 Auth & Account",
        "description": "Signup, password login, OAuth, password reset, account profile, email/SMS status, and account security.",
    },
    {
        "name": "03 Errands & Attachments",
        "description": "Create errands, upload/download attachments, share proof links, and manage errand messages.",
    },
    {
        "name": "04 Pilots & Delivery",
        "description": "Pilot job discovery, delivery lifecycle, pilot profile, documents, availability, and employment intake.",
    },
    {
        "name": "05 Tracking & Live Location",
        "description": "Pilot GPS updates, current location, route history, and live tracking status.",
    },
    {
        "name": "06 Payments & Subscriptions",
        "description": "Stripe payment readiness, quotes, checkout sessions, checkout verification, subscriptions, and webhooks.",
    },
    {
        "name": "07 Promo Codes",
        "description": "Customer promo-code listing and validation.",
    },
    {
        "name": "08 Support & Incidents",
        "description": "Support chat, support handoff, complaints, reviews, and incident reporting/resolution.",
    },
    {
        "name": "09 Public & Reviews",
        "description": "Public, low-risk endpoints such as public reviews, public errand summaries, and public profile image access.",
    },
    {
        "name": "10 Assistant & AI",
        "description": "AI-assisted errand drafting, public assistant chat, and structured request-builder endpoints.",
    },
    {
        "name": "11 Analytics & Voice",
        "description": "Visit analytics, masked call setup, and voice-call provider callbacks.",
    },
    {
        "name": "12 Admin",
        "description": "Admin-only customer, errand, pilot, support, incident, payment, promo, and monitoring operations.",
    },
    {
        "name": "13 GraphQL",
        "description": "GraphQL endpoint. Explore GraphQL operations directly at /graphql.",
    },
]


OPENAPI_TAG_ALIASES = {
    "auth": "01 Auth & Account",
    "user-profile": "01 Auth & Account",
    "login": "02 One-time Code Login",
    "tso": "02 One-time Code Login",
    "errand-messages": "03 Errands & Attachments",
    "pilots": "04 Pilots & Delivery",
    "pilot-profile": "04 Pilots & Delivery",
    "pilot-tracking": "05 Tracking & Live Location",
    "payments": "06 Payments & Subscriptions",
    "promo-codes": "07 Promo Codes",
    "support": "08 Support & Incidents",
    "incidents": "08 Support & Incidents",
    "public": "09 Public & Reviews",
    "assistant": "10 Assistant & AI",
    "toxi": "10 Assistant & AI",
    "analytics": "11 Analytics & Voice",
    "voice": "11 Analytics & Voice",
    "admin": "12 Admin",
}


def _openapi_tag_for_path(path: str, existing_tags: list[str]) -> str:
    for tag in existing_tags:
        if tag in OPENAPI_TAG_ALIASES:
            return OPENAPI_TAG_ALIASES[tag]
        if tag in {entry["name"] for entry in OPENAPI_TAGS}:
            return tag

    if path in {"/", "/version", "/health", "/health/", "/ready", "/ready/"}:
        return "00 System & Health"
    if (
        path.startswith("/dev/")
        or path.startswith("/test-")
        or path.startswith("/anomaly-")
    ):
        return "00 System & Health"
    if path.startswith("/auth/") or path.startswith("/api/auth/"):
        return "01 Auth & Account"
    if path.startswith("/login/") or path.startswith("/tso/"):
        return "02 One-time Code Login"
    if (
        path.startswith("/errands")
        or path.startswith("/attachments")
        or path.startswith("/share/")
        or path.startswith("/public/errands/")
        or path.startswith("/api/v1/errands/")
        or path.startswith("/v1/errands/")
    ):
        return "03 Errands & Attachments"
    if (
        path.startswith("/pilots/")
        or path.startswith("/v1/pilots/")
        or path.startswith("/api/v1/pilots/")
        or path.startswith("/pilot-employment/")
    ):
        return "04 Pilots & Delivery"
    if (
        path.startswith("/tracking/")
        or path.startswith("/v1/tracking/")
        or path.startswith("/api/v1/tracking/")
    ):
        return "05 Tracking & Live Location"
    if path.startswith("/payments/") or path.startswith("/webhooks/stripe"):
        return "06 Payments & Subscriptions"
    if path.startswith("/promo-codes/"):
        return "07 Promo Codes"
    if (
        path.startswith("/support/")
        or path.startswith("/incidents/")
        or path.startswith("/v1/support/")
        or path.startswith("/v1/incidents/")
        or path.startswith("/api/v1/support/")
        or path.startswith("/api/v1/incidents/")
    ):
        return "08 Support & Incidents"
    if (
        path.startswith("/public/")
        or path.startswith("/v1/public/")
        or path.startswith("/api/v1/public/")
        or path.startswith("/uploads/profiles/")
    ):
        return "09 Public & Reviews"
    if (
        path.startswith("/assistant/")
        or path.startswith("/toxi/")
        or path.startswith("/v1/assistant/")
        or path.startswith("/v1/toxi/")
        or path.startswith("/api/v1/assistant/")
        or path.startswith("/api/v1/toxi/")
        or path.startswith("/prompt/")
    ):
        return "10 Assistant & AI"
    if path.startswith("/analytics/") or path.startswith("/voice/"):
        return "11 Analytics & Voice"
    if path.startswith("/admin/"):
        return "12 Admin"
    if path.startswith("/graphql"):
        return "13 GraphQL"
    return "00 System & Health"


def _organize_openapi_tags(openapi_schema: dict) -> None:
    openapi_schema["tags"] = OPENAPI_TAGS
    for path, path_item in (openapi_schema.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            operation["tags"] = [
                _openapi_tag_for_path(path, operation.get("tags") or [])
            ]


def _hide_legacy_api_paths(openapi_schema: dict) -> None:
    """Keep backward-compatible /v1 and /api routes callable but out of public Swagger docs."""
    paths = openapi_schema.get("paths") or {}
    for path in list(paths.keys()):
        if path.startswith("/api/") or path.startswith("/v1/"):
            paths.pop(path, None)


def _use_bearer_security_scheme(openapi_schema: dict) -> None:
    """Replace raw Authorization header inputs with Swagger's Authorize button."""
    for path_item in (openapi_schema.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters")
            if not isinstance(parameters, list):
                continue
            filtered = [
                param
                for param in parameters
                if not (
                    isinstance(param, dict)
                    and str(param.get("in") or "").lower() == "header"
                    and str(param.get("name") or "").lower() == "authorization"
                )
            ]
            if len(filtered) == len(parameters):
                continue
            if filtered:
                operation["parameters"] = filtered
            else:
                operation.pop("parameters", None)
            operation.setdefault("security", [{"BearerAuth": []}])


app = FastAPI(
    title="ErrandBridge API",
    description=(
        "ErrandBridge REST + GraphQL API for errands, tracking, payments, support, "
        "and partner-facing integrations. Interactive REST docs are available at /docs, "
        "the OpenAPI schema at /openapi.json, and GraphQL at /graphql."
    ),
    version=_resolve_api_version(),
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters={
        # Keep all operations for the same resource path grouped together in Swagger UI.
        # This is easier to scan than method sorting, which separates GET/POST/PUT/PATCH/DELETE.
        "operationsSorter": "alpha",
    },
    lifespan=lifespan,
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=OPENAPI_TAGS,
    )

    _hide_legacy_api_paths(openapi_schema)
    _organize_openapi_tags(openapi_schema)
    _use_bearer_security_scheme(openapi_schema)

    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "oauth2",
        "flows": {"password": {"tokenUrl": "/auth/swagger-login", "scopes": {}}},
        "description": (
            "Authenticate with your email (as username) and password. "
            "Auth responses also include user_uuid/userUuid as a stable public user identifier for data mapping; "
            "that UUID is not a secret and does not replace Bearer authentication."
        ),
    }

    openapi_schema["externalDocs"] = {
        "description": "GraphQL endpoint",
        "url": "/graphql",
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


async def _ensure_admin_accounts() -> None:
    admin_password = (os.getenv("ADMIN_BOOTSTRAP_PASSWORD") or "").strip()
    if not admin_password:
        print(
            "[BOOTSTRAP] ADMIN_BOOTSTRAP_PASSWORD not set; skipping admin bootstrap",
            flush=True,
        )
        return

    reset_password = (
        os.getenv("ADMIN_BOOTSTRAP_RESET_PASSWORD") or ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }

    admin_list = [email.strip().lower() for email in admin_emails() if email.strip()]
    if not admin_list:
        print("[BOOTSTRAP] ADMIN_EMAILS empty; skipping admin bootstrap", flush=True)
        return

    async with AsyncSessionLocal() as session:
        for email in admin_list:
            result = await session.execute(auth_safe_user_by_email_query(email))
            existing = result.scalars().first()
            if existing:
                changed = False
                if reset_password:
                    existing.password_hash = hash_password(admin_password)
                    changed = True
                    print(
                        f"[BOOTSTRAP] Reset password for admin account {email}",
                        flush=True,
                    )

                if not existing.is_email_verified:
                    existing.is_email_verified = True
                    changed = True

                if changed:
                    await session.commit()
                continue

            user = User(
                email=email,
                password_hash=hash_password(admin_password),
                first_name="Admin",
                last_name="User",
                is_email_verified=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"[BOOTSTRAP] Created admin account for {email}", flush=True)


# === Anomaly Alerts Dashboard Endpoint ===
@app.get("/anomaly-alerts")
def get_anomaly_alerts(limit: int = 20):
    """Return recent anomaly alerts for dashboard display."""
    log_path = os.path.join(os.path.dirname(__file__), "anomaly_alerts.log")
    alerts = []
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            lines = f.readlines()[-limit:]
            for line in lines:
                try:
                    timestamp, latency = line.strip().split(",", 1)
                    alerts.append({"timestamp": timestamp, "latency": float(latency)})
                except Exception:
                    continue
    return JSONResponse(content={"alerts": alerts})


def _effective_env_name() -> str:
    """Resolve the current environment name.

    Production incidents have occurred when ENV/BACKEND_ENVIRONMENT were not set in
    ECS, which caused the backend to default to "local" and silently block CORS for
    real domains (errandbridge.com / pilot.errandbridge.com).

    If we detect we're running in AWS and no explicit env is set, default to "prod".
    """
    explicit = (
        (os.getenv("ENV") or os.getenv("BACKEND_ENVIRONMENT") or "").strip().lower()
    )
    if explicit:
        return explicit
    if _running_in_aws_container():
        return "prod"
    return "local"


def _is_production_like() -> bool:
    return _effective_env_name() in {"prod", "production"}


def _dev_routes_enabled() -> bool:
    if str(os.getenv("ENABLE_DEV_ROUTES") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }:
        return True
    return not _is_production_like()


def _assert_dev_route_enabled() -> None:
    if not _dev_routes_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


# Print database configuration for debugging
if _effective_env_name() == "local" and not _running_in_aws_container():
    print("[BACKEND] Using LOCAL database configuration (127.0.0.1:5433)", flush=True)
else:
    print(
        f"[BACKEND] ENV={os.getenv('ENV') or os.getenv('BACKEND_ENVIRONMENT') or 'unset'}, running_in_aws={_running_in_aws_container()}",
        flush=True,
    )


def _parse_cors_origins() -> list[str]:
    raw = (os.getenv("CORS_ALLOW_ORIGINS") or "").strip()
    env_origins = (
        [origin.strip() for origin in raw.split(",") if origin.strip()] if raw else []
    )

    env_name = _effective_env_name()

    # In local dev, keep CORS strictly localhost-only to avoid mixing environments.
    default_origins = (
        []
        if env_name == "local"
        else [
            "https://www.errandbridge.com",
            "https://errandbridge.com",
            "https://pilot.errandbridge.com",
            "https://api.errandbridge.com",
        ]
    )

    local_origins = [
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "http://127.0.0.1:3003",
        # Android emulator host mapping (dev server)
        "http://10.0.2.2:3000",
        "http://10.0.2.2:3001",
        "http://10.0.2.2:3002",
        "http://10.0.2.2:3003",
        "capacitor://localhost",
        "ionic://localhost",
    ]

    merged = [*default_origins, *local_origins, *env_origins]
    # Preserve order while removing duplicates
    seen = set()
    deduped = []
    for origin in merged:
        if origin not in seen:
            deduped.append(origin)
            seen.add(origin)
    return deduped


def _cors_origin_regex() -> str | None:
    """Return allow_origin_regex appropriate for the current environment.

    - local: allow only localhost/127.0.0.1/10.0.2.2 on the dev ports we support
    - non-local: also allow *.errandbridge.com
    """
    env_name = _effective_env_name()
    if env_name == "local":
        # Dev/testing ports. CRA will bump from :3000 -> :3001 if the port is occupied.
        # Note: docker-compose can also bind Grafana to :3001, so the frontend may
        # fall back to :3002/:3003 in that setup.
        return (
            r"^http://localhost$"
            r"|^http://127\.0\.0\.1$"
            r"^http://localhost:(?:3000|3001|3002|3003)$"
            r"|^http://127\.0\.0\.1:(?:3000|3001|3002|3003)$"
            r"|^http://10\.0\.2\.2:(?:3000|3001|3002|3003)$"
            r"|^capacitor://localhost$"
            r"|^ionic://localhost$"
        )
    # Allow apex + any subdomain under errandbridge.com.
    # Note: CORSMiddleware uses re.match(), so we anchor the patterns.
    return (
        r"^https?://(?:[A-Za-z0-9-]+\.)*errandbridge\.com$"
        r"|^http://localhost$"
        r"|^http://127\.0\.0\.1$"
        r"|^http://localhost:(?:3000|3001|3002|3003)$"
        r"|^http://127\.0\.0\.1:(?:3000|3001|3002|3003)$"
        r"|^http://10\.0\.2\.2:(?:3000|3001|3002|3003)$"
        r"|^capacitor://localhost$"
        r"|^ionic://localhost$"
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    print(f"[UNHANDLED EXCEPTION] {request.method} {request.url.path}: {exc}", flush=True)
    traceback.print_exc()
    origin = request.headers.get("origin") or "http://localhost:3000"
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred", "message": str(exc)},
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(self), payment=(self)",
    )
    if _is_production_like():
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
        )
    return response


# CORS setup
_DEFAULT_UPLOAD_DIR = pathlib.Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR = pathlib.Path(os.getenv("UPLOAD_DIR", str(_DEFAULT_UPLOAD_DIR)))

# Profile images are stored under {UPLOAD_DIR}/profiles and are accessed directly via
# /uploads/profiles/<filename>.
PROFILE_UPLOAD_DIR = UPLOAD_DIR / "profiles"
try:
    PROFILE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    # Avoid failing import/startup if the directory can't be created (e.g. read-only FS).
    # The upload endpoint will surface an error when it tries to write.
    pass


def _should_allow_profile_image_origin(origin: str | None) -> bool:
    if not origin:
        return False
    try:
        origin = str(origin).strip()
    except Exception:
        return False
    if not origin:
        return False
    # Prefer exact origins list.
    if origin in set(_parse_cors_origins()):
        return True
    # Fallback to the same regex used for global CORS.
    regex = _cors_origin_regex()
    if not regex:
        return False
    try:
        pattern = re.compile(rf"^(?:{regex})$")
        return bool(pattern.match(origin))
    except re.error:
        return False


@app.get("/uploads/profiles/{filename}")
async def get_public_profile_image(filename: str, request: Request):
    """Publicly serve pilot profile images.

    Notes:
    - This endpoint is intentionally limited to the profiles folder, and sanitizes the
      filename to prevent path traversal.
    - We do NOT expose general attachments via a static /uploads mount, since many
      attachments are protected by auth.
    """
    safe_name = os.path.basename(filename or "")
    if not safe_name or safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = PROFILE_UPLOAD_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    media_type, _ = mimetypes.guess_type(str(path))
    response = FileResponse(
        path=str(path),
        media_type=media_type or "application/octet-stream",
        filename=safe_name,
    )
    # Ensure profile images can be fetched cross-origin in local dev (e.g. pilot UI)
    # even when browsers treat the request as CORS (fetch/XHR).
    origin = request.headers.get("origin")
    if _should_allow_profile_image_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    # Cache a bit to avoid hammering the backend on dashboard refreshes.
    response.headers.setdefault("Cache-Control", "public, max-age=300")
    return response


# Explicit OPTIONS handler for CORS preflight on file upload
@app.options("/errands/{errand_id}/attachments")
async def options_upload_errand_attachment(errand_id: int):
    return Response(status_code=200)


class SuggestRequest(BaseModel):
    template_id: Optional[
        Literal["diaspora_pickup", "market_run", "driver_dispatch"]
    ] = Field(
        default=None, description="Optional template identifier to guide suggestions"
    )
    prompt: str = Field(..., min_length=1, description="Free-form user prompt")


class SuggestResponse(BaseModel):
    title: str
    description: str


class AISuggestRequest(BaseModel):
    description: str = Field(..., min_length=1, description="Your errand description")
    template_id: Optional[str] = Field(
        default=None, description="Optional template preference"
    )


class AISuggestResponse(BaseModel):
    title: str
    description: str
    suggested_template: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.95)


class ErrandCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    pickup_location: Optional[str] = Field(default=None, alias="pickupLocation")
    dropoff_location: Optional[str] = Field(default=None, alias="dropoffLocation")
    pickup_contact_name: Optional[str] = Field(default=None, alias="pickupContactName")
    pickup_contact_phone: Optional[str] = Field(
        default=None, alias="pickupContactPhone"
    )
    dropoff_contact_name: Optional[str] = Field(
        default=None, alias="dropoffContactName"
    )
    dropoff_contact_phone: Optional[str] = Field(
        default=None, alias="dropoffContactPhone"
    )
    distance_km: Optional[float] = Field(default=None, alias="distanceKm")
    note: Optional[str] = None
    category: Optional[str] = None
    estimated_time: Optional[str] = None
    payment_amount: Optional[float] = None
    payment_session_id: Optional[str] = Field(default=None, alias="paymentSessionId")

    class Config:
        allow_population_by_field_name = True


class ErrandResponse(BaseModel):
    id: Union[uuid.UUID, int, str]
    reference_number: str = Field(..., alias="referenceNumber")
    title: str
    description: Optional[str] = None
    pickup_location: Optional[str] = Field(default=None, alias="pickupLocation")
    dropoff_location: Optional[str] = Field(default=None, alias="dropoffLocation")
    pickup_contact_name: Optional[str] = Field(default=None, alias="pickupContactName")
    pickup_contact_phone: Optional[str] = Field(
        default=None, alias="pickupContactPhone"
    )
    dropoff_contact_name: Optional[str] = Field(
        default=None, alias="dropoffContactName"
    )
    dropoff_contact_phone: Optional[str] = Field(
        default=None, alias="dropoffContactPhone"
    )
    assigned_runner_name: Optional[str] = Field(
        default=None, alias="assignedRunnerName"
    )
    note: Optional[str] = None
    status: str
    user_id: Union[uuid.UUID, int, str] = Field(..., alias="userId")
    pilot_id: Optional[Union[uuid.UUID, int, str]] = Field(default=None, alias="pilotId")
    created_at: Optional[datetime] = Field(default=None, alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, alias="updatedAt")
    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    completed_at: Optional[datetime] = Field(default=None, alias="completedAt")
    pickup_time_slot_date: Optional[str] = Field(
        default=None, alias="pickupTimeSlotDate"
    )

    class Config:
        allow_population_by_field_name = True


# Initialize OpenAI client
openai_api_key = os.getenv("OPENAI_API_KEY")
openai_model = os.getenv("OPENAI_MODEL", "gpt-4")
openai_client = AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None


def _derive_draft(prompt: str, template_id: Optional[str]) -> SuggestResponse:
    cleaned = (prompt or "").strip()

    # Deterministic, rule-based title/description derivation.
    first_period = cleaned.find(".")
    title_raw = (cleaned[:first_period] if first_period > 0 else cleaned).strip()
    title_raw = title_raw.removeprefix("Create an errand:").strip()

    description = (cleaned[first_period + 1 :] if first_period > 0 else "").strip()

    if not title_raw:
        fallback = {
            "diaspora_pickup": "Pick up and deliver a document",
            "market_run": "Buy items and deliver",
            "driver_dispatch": "Dispatch a rider",
        }.get(template_id or "", "New errand")
        title_raw = fallback

    if template_id and not description:
        # Add a small structured checklist based on the chosen template.
        checklist = {
            "diaspora_pickup": "Include: pickup location, recipient, timing, contact, confirmation steps.",
            "market_run": "Include: items, budget, substitution rules, pickup/store, dropoff.",
            "driver_dispatch": "Include: pickup, dropoff, verification, call-before-dropoff, ETA.",
        }.get(template_id)
        description = checklist or description

    return SuggestResponse(title=title_raw, description=description)


async def _startup_event() -> None:
    """Startup event handler with idempotent database initialization."""
    global _db_init_done
    env_name = (os.getenv("ENV") or "local").lower()
    running_in_aws = bool(os.getenv("AWS_EXECUTION_ENV"))

    print("[STARTUP] ✨ Startup event handler called!", flush=True)

    # Never use create_all in AWS/non-local environments.
    # create_all does not apply schema migrations (it won't add columns like tip_amount_total_minor).
    # In deployments we rely on Alembic (run in /app/prestart.sh).
    if running_in_aws or env_name not in {"local"}:
        print(
            f"[STARTUP] ℹ️  Skipping create_all in ENV={env_name} (aws={running_in_aws}); relying on migrations.",
            flush=True,
        )
        _db_init_done = True
        return

    # Use lock to prevent concurrent initialization
    async with _db_init_lock:
        if _db_init_done:
            print("[STARTUP] ℹ️  Database already initialized, skipping...", flush=True)
            return

        try:
            print("[STARTUP] 🔄 Initializing database tables...", flush=True)

            async def _init_db():
                service_setup_columns = (
                    ("category_id", "VARCHAR"),
                    ("support_type", "VARCHAR"),
                    ("preferred_time", "VARCHAR"),
                    ("priority_level", "VARCHAR"),
                    ("distance_km", "DOUBLE PRECISION"),
                    ("final_price_minor", "INTEGER"),
                    ("final_price_currency", "VARCHAR"),
                )

                # Import models to register them on Base.metadata before creating tables
                print("[STARTUP] 📥 About to import models...", flush=True)
                from models import (
                    User,
                    Errand,
                    ErrandAttachment,
                    AttachmentShareLink,
                    ErrandEvent,
                    PilotLocation,
                    PilotDocument,
                    IncidentReport,
                    IncidentMessage,
                    SupportConversation,
                    SupportMessage,
                )

                _ = (
                    User,
                    Errand,
                    ErrandAttachment,
                    AttachmentShareLink,
                    ErrandEvent,
                    PilotLocation,
                    PilotDocument,
                    IncidentReport,
                    IncidentMessage,
                    SupportConversation,
                    SupportMessage,
                )
                print("[STARTUP] 📦 Models imported successfully", flush=True)

                from database import engine, Base

                print("[STARTUP] 🔌 Database engine loaded", flush=True)

                # Create schema and tables with proper permissions
                async with engine.begin() as conn:
                    print("[STARTUP] 🏗️  Creating schema if not exists...", flush=True)
                    await conn.execute(text("CREATE SCHEMA IF NOT EXISTS public;"))

                    # Skip granting to 'errandbridge' role if it doesn't exist
                    # The 'postgres' user has full access anyway
                    print("[STARTUP] 🛠️  Creating tables...", flush=True)
                    await conn.run_sync(Base.metadata.create_all)

                    # Local/dev resilience: create_all does not backfill newly-added columns
                    # on existing tables, so a developer DB that missed an Alembic revision can
                    # otherwise crash errand submission with UndefinedColumnError.
                    print(
                        "[STARTUP] 🩹 Ensuring errand service-setup columns exist...",
                        flush=True,
                    )
                    for column_name, column_type in service_setup_columns:
                        await conn.execute(
                            text(
                                f"ALTER TABLE errands ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                            )
                        )

            init_timeout = float(os.getenv("DB_INIT_TIMEOUT", "5"))
            await asyncio.wait_for(_init_db(), timeout=init_timeout)

            print("[STARTUP] ✅ Database tables created successfully", flush=True)
            _db_init_done = True

        except asyncio.TimeoutError:
            print(
                "[STARTUP] ⚠️ Database initialization timed out; continuing startup.",
                flush=True,
            )
        except Exception as e:
            import traceback

            print(f"[STARTUP] ❌ Database initialization error: {str(e)}", flush=True)
            print(f"[STARTUP] ❌ Traceback: {traceback.format_exc()}", flush=True)
            # Don't set _db_init_done = True so it retries on next startup

    cfg = get_storage_config()
    if cfg.driver == "s3":
        print(
            f"[storage] driver=s3 bucket={cfg.s3_bucket} region={cfg.s3_region} prefix={cfg.s3_prefix}",
            flush=True,
        )
    else:
        print(f"[storage] driver=local upload_dir={str(UPLOAD_DIR)}", flush=True)


# Prometheus metrics
Instrumentator().instrument(app).expose(app, include_in_schema=False, should_gzip=True)


# Health check endpoint - liveness (should not depend on external services)
@app.head("/health")
@app.head("/health/")
@app.get("/health")
@app.get("/health/")
async def health_liveness():
    """Liveness probe for ALB/ECS.

    This must be fast and should not require DB connectivity; otherwise deployments can
    get stuck with 503 health checks even when the app is otherwise running.
    """
    timestamp = datetime.utcnow().isoformat()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "healthy",
            "timestamp": timestamp,
        },
    )


# Readiness check endpoint - tests database connectivity
@app.head("/ready")
@app.head("/ready/")
@app.get("/ready")
@app.get("/ready/")
async def readiness_check():
    """Readiness probe that verifies database connectivity."""
    timestamp = datetime.utcnow().isoformat()
    env_name = _effective_env_name()
    try:

        async def _db_probe():
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(1))
                result.scalar()

        await asyncio.wait_for(_db_probe(), timeout=5.0)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ready",
                "database": "connected",
                "timestamp": timestamp,
            },
        )
    except asyncio.TimeoutError:
        print("[READY] Database probe timed out", flush=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "database": "timeout",
                "timestamp": timestamp,
            },
        )
    except Exception as e:
        print(f"[READY] Database connection failed: {str(e)}", flush=True)
        error_lower = str(e).lower()
        error_code = None
        if "password authentication failed" in error_lower:
            error_code = "db_auth_failed"
        elif "could not translate host name" in error_lower:
            error_code = "db_dns_failed"
        elif "connection refused" in error_lower:
            error_code = "db_connection_refused"
        elif "timeout" in error_lower:
            error_code = "db_timeout"

        content = {
            "status": "not_ready",
            "database": "disconnected",
            "timestamp": timestamp,
        }

        if error_code:
            content["error_code"] = error_code

        # Avoid leaking internal error details in prod-like environments.
        if env_name not in ("prod", "production"):
            content["error"] = str(e)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=content,
        )


# Development-only: Verify admin email (temporary for onboarding)
@app.post("/dev/verify-admin/{email}")
async def dev_verify_admin(email: str):
    """Temporary endpoint to verify admin email for development/onboarding."""
    _assert_dev_route_enabled()
    # Only works if admin emails are configured
    admin_emails = os.getenv("ADMIN_EMAILS", "").split(",")
    admin_emails_list = [e.strip().lower() for e in admin_emails if e.strip()]

    if email.lower() not in admin_emails_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email is not configured as admin",
        )

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(auth_safe_user_by_email_query(email))
            user = result.scalar_one_or_none()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )

            user.is_email_verified = True
            await session.commit()

            return {"ok": True, "message": f"Email verified for {email}"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DEV_VERIFY] Error: {str(e)}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


# GraphQL endpoint
def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def get_context(request: Request):
    # Strawberry passes the Starlette Request. We use it to resolve auth.
    token = _extract_bearer(request.headers.get("authorization"))
    current_user_id = decode_access_token(token) if token else None

    async with AsyncSessionLocal() as session:
        yield {"db": session, "current_user_id": current_user_id}


graphql_app = GraphQLRouter(schema, context_getter=get_context, prefix="/graphql")
# Add routers
app.include_router(graphql_app)
app.include_router(auth_router)
# Backwards compatibility: some deployed frontends historically called /api/auth/*.
# Mounting the same router under /api keeps those clients working without needing
# an immediate frontend redeploy.
app.include_router(auth_router, prefix="/api", include_in_schema=False)
# app.include_router(admin_router)  # Disabled: unresolved import
app.include_router(tracking_router)
app.include_router(pilot_delivery_router)
app.include_router(pilot_profile_router)
app.include_router(user_profile_router)
app.include_router(admin_router)
app.include_router(incidents_router)
app.include_router(support_router)
app.include_router(public_reviews_router)
app.include_router(assistant_router)
app.include_router(toxi_structured_router)
app.include_router(analytics_router)
app.include_router(voice_router)
app.include_router(errand_messages_router)
app.include_router(payments_router)
app.include_router(webhooks_router)
app.include_router(promo_codes_router)

# Backwards compatibility for older app builds that call /v1/* or /api/v1/*.
# New clients and Swagger docs should use root paths without the /v1 prefix.
for legacy_router in (
    tracking_router,
    pilot_delivery_router,
    pilot_profile_router,
    user_profile_router,
    incidents_router,
    support_router,
    public_reviews_router,
    assistant_router,
    toxi_structured_router,
    errand_messages_router,
):
    app.include_router(legacy_router, prefix="/v1", include_in_schema=False)
    app.include_router(legacy_router, prefix="/api/v1", include_in_schema=False)


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _sha256_hex(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _is_admin_email(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() in admin_emails()


def _current_user_id_from_request(request: Request) -> Union[uuid.UUID, int, str]:
    token = _extract_bearer(request.headers.get("authorization"))
    if token == "devtoken123":
        return 1

    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    return user_id


_schema_migrated = False

async def _ensure_errands_schema_compatible():
    global _schema_migrated
    if _schema_migrated:
        return
    try:
        from database import engine
        from sqlalchemy import text
        async with engine.begin() as conn:
            cols_to_add = [
                ("pickup_contact_name", "VARCHAR"),
                ("pickup_contact_phone", "VARCHAR"),
                ("dropoff_contact_name", "VARCHAR"),
                ("dropoff_contact_phone", "VARCHAR"),
            ]
            for col, col_type in cols_to_add:
                try:
                    await conn.execute(text(f"ALTER TABLE errands ADD COLUMN IF NOT EXISTS {col} {col_type};"))
                except Exception:
                    pass
            for col in ["user_id", "pilot_id", "assigned_to"]:
                try:
                    await conn.execute(text(f"ALTER TABLE errands ALTER COLUMN {col} TYPE VARCHAR(64) USING {col}::VARCHAR;"))
                except Exception:
                    pass
        _schema_migrated = True
    except Exception as e:
        print(f"[SCHEMA] Migration note: {e}", flush=True)


def _errand_response(model: Errand, pilot_name: Optional[str] = None) -> ErrandResponse:
    errand_id = str(model.id) if isinstance(model.id, uuid.UUID) else model.id
    user_id = str(model.user_id) if isinstance(model.user_id, uuid.UUID) else model.user_id
    pilot_id = (str(model.pilot_id) if isinstance(model.pilot_id, uuid.UUID) else model.pilot_id) if model.pilot_id is not None else None

    return ErrandResponse(
        id=errand_id,
        reference_number=model.reference_number,
        title=model.title,
        description=model.description,
        pickup_location=model.pickup_location,
        dropoff_location=model.dropoff_location,
        pickup_contact_name=getattr(model, "pickup_contact_name", None),
        pickup_contact_phone=getattr(model, "pickup_contact_phone", None),
        dropoff_contact_name=getattr(model, "dropoff_contact_name", None),
        dropoff_contact_phone=getattr(model, "dropoff_contact_phone", None),
        assigned_runner_name=pilot_name,
        note=model.note,
        status=model.status or "pending",
        user_id=user_id,
        pilot_id=pilot_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        pickup_time_slot_date=getattr(model, "pickup_time_slot_date", None),
    )


@app.post("/errands")
async def create_errand(request: Request, payload: ErrandCreateRequest):
    """Create an errand via REST.

    Mirrors the GraphQL createErrand flow so REST clients can create errands.
    Requires a Bearer token (or devtoken123 for local/dev).
    """
    user_id = _current_user_id_from_request(request)

    pickup_location = payload.pickup_location or payload.location
    note_parts = []
    if payload.category:
        note_parts.append(f"category: {payload.category}")
    if payload.estimated_time:
        note_parts.append(f"estimated_time: {payload.estimated_time}")
    if payload.payment_amount is not None:
        note_parts.append(f"payment_amount: {payload.payment_amount}")

    note = payload.note
    if note_parts:
        extra = "; ".join(note_parts)
        note = f"{note} | {extra}" if note else extra

    placeholder_ref = _make_reference_number(int(time.time() * 1_000_000))
    enforce_payment = _env_truthy(os.getenv("ENFORCE_ERRAND_PAYMENT"))

    async with AsyncSessionLocal() as session:
        payment_session_row: StripeCheckoutSession | None = None

        if enforce_payment:
            sub_active = await session.scalar(
                select(ClientSubscription.id).where(
                    cast(ClientSubscription.user_id, String) == str(user_id),
                    ClientSubscription.plan == "plus",
                    ClientSubscription.status.in_(["active", "trialing"]),
                )
            )

            if not sub_active:
                payment_session_id = (payload.payment_session_id or "").strip()
                if not payment_session_id:
                    raise HTTPException(status_code=402, detail="Payment required")

                payment_session_row = await session.scalar(
                    select(StripeCheckoutSession)
                    .where(
                        StripeCheckoutSession.stripe_session_id == payment_session_id,
                        cast(StripeCheckoutSession.user_id, String) == str(user_id),
                    )
                    .with_for_update()
                )

                if (
                    not payment_session_row
                    or not bool(getattr(payment_session_row, "paid", False))
                    or getattr(payment_session_row, "used_for_errand_id", None)
                    is not None
                ):
                    raise HTTPException(status_code=400, detail="Payment not verified")

        clean_title = (payload.title or "").strip()
        if (
            not clean_title
            or len(clean_title) > 45
            or clean_title.lower().startswith("i'm happy to help")
            or clean_title.lower().startswith("create an errand")
        ):
            clean_title = {
                "diaspora_pickup": "Personal Errand",
                "doc_v2": "Document & Office",
                "market_run": "Market Run",
                "driver_dispatch": "Driver Dispatch",
                "property_v2": "Property Inspection",
                "health_v2": "Prescription & Health",
                "shopping_v2": "Shopping Errand",
                "custom_v2": "Custom Errand",
            }.get(payload.category or "", "General Errand")

        model = Errand(
            reference_number=placeholder_ref,
            title=clean_title,
            description=payload.description or clean_title,
            pickup_location=pickup_location,
            dropoff_location=payload.dropoff_location,
            pickup_contact_name=payload.pickup_contact_name,
            pickup_contact_phone=payload.pickup_contact_phone,
            dropoff_contact_name=payload.dropoff_contact_name,
            dropoff_contact_phone=payload.dropoff_contact_phone,
            distance_km=payload.distance_km if payload.distance_km is not None else 5.0,
            note=note,
            status="submitted",
            user_id=str(user_id),
        )
        session.add(model)
        await session.flush()

        model.reference_number = _make_reference_number(model.id)

        if payment_session_row is not None:
            payment_session_row.used_for_errand_id = str(model.id)
            payment_session_row.used_at = datetime.now(timezone.utc)

        session.add(
            ErrandEvent(
                errand_id=model.id,
                event_type="created",
                old_status=None,
                new_status="submitted",
                note=None,
                user_id=str(user_id),
            )
        )

        await session.commit()
        await session.refresh(model)

    created_iso = (
        model.created_at.isoformat() if getattr(model, "created_at", None) else None
    )
    return {
        "id": model.id,
        "reference_number": model.reference_number,
        "referenceNumber": model.reference_number,
        "title": model.title,
        "description": model.description,
        "pickup_location": model.pickup_location,
        "pickupLocation": model.pickup_location,
        "dropoff_location": model.dropoff_location,
        "dropoffLocation": model.dropoff_location,
        "pickup_contact_name": getattr(model, "pickup_contact_name", None),
        "pickupContactName": getattr(model, "pickup_contact_name", None),
        "pickup_contact_phone": getattr(model, "pickup_contact_phone", None),
        "pickupContactPhone": getattr(model, "pickup_contact_phone", None),
        "dropoff_contact_name": getattr(model, "dropoff_contact_name", None),
        "dropoffContactName": getattr(model, "dropoff_contact_name", None),
        "dropoff_contact_phone": getattr(model, "dropoff_contact_phone", None),
        "dropoffContactPhone": getattr(model, "dropoff_contact_phone", None),
        "assigned_runner_name": None,
        "assignedRunnerName": None,
        "status": model.status,
        "user_id": model.user_id,
        "userId": model.user_id,
        "pilot_id": model.pilot_id,
        "pilotId": model.pilot_id,
        "created_at": created_iso,
        "createdAt": created_iso,
        "pickup_time_slot_date": getattr(model, "pickup_time_slot_date", None),
        "pickupTimeSlotDate": getattr(model, "pickup_time_slot_date", None),
        "note": model.note,
    }


@app.get("/errands", response_model=list[ErrandResponse])
async def list_errands(
    request: Request,
    status_filter: Optional[str] = Query(
        default=None, alias="status", description="Optional errand status filter"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    size: Optional[int] = Query(default=None, ge=1, le=100),
):
    """List errands owned by the authenticated user.

    Auth: requires a Bearer token. Admin-wide listing remains under `/admin/errands`.
    """
    user_id = _current_user_id_from_request(request)
    if size is not None:
        limit = size

    # Schema check removed from request lifecycle

    try:
        from sqlalchemy import cast, String
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Errand)
                .where(cast(Errand.user_id, String) == str(user_id))
            )
            if status_filter:
                stmt = stmt.where(Errand.status == status_filter.strip())
            stmt = stmt.order_by(Errand.created_at.desc()).offset(offset).limit(limit)

            result = await session.execute(stmt)
            errands = result.scalars().all()
            return [_errand_response(m) for m in errands]
    except Exception as e:
        print(f"[ERRANDS] list_errands error: {e}", flush=True)
        return []


class ErrandStatusUpdateIn(BaseModel):
    status: str
    imageProofUrl: Optional[str] = None


@app.put("/errands/{errand_id}/status", response_model=ErrandResponse)
async def update_errand_status(
    errand_id: Union[uuid.UUID, int, str], payload: ErrandStatusUpdateIn, request: Request
):
    user_id = _current_user_id_from_request(request)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Errand).where(cast(Errand.id, String) == str(errand_id)))
        model = result.scalar_one_or_none()

        if not model:
            raise HTTPException(status_code=404, detail="Errand not found")

        if str(model.user_id) != str(user_id) and (
            model.pilot_id is None or str(model.pilot_id) != str(user_id)
        ):
            raise HTTPException(status_code=403, detail="Not allowed to update status")

        model.status = payload.status

        session.add(model)
        await session.commit()
        await session.refresh(model)

    return _errand_response(model)


@app.get("/errands/{errand_id}", response_model=ErrandResponse)
async def get_errand(errand_id: Union[uuid.UUID, int, str], request: Request):
    """Get one errand owned by the authenticated user."""
    user_id = _current_user_id_from_request(request)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Errand).where(cast(Errand.id, String) == str(errand_id), cast(Errand.user_id, String) == str(user_id))
        )
        model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(status_code=404, detail="Errand not found")

    return _errand_response(model)


@app.post("/errands/{errand_id}/attachments")
async def upload_errand_attachment(
    errand_id: Union[uuid.UUID, int, str], request: Request, file: UploadFile = File(...)
):
    print("[DEBUG] Incoming headers:", dict(request.headers))
    """Upload an image/document attachment for an errand.

    Storage: local filesystem (UPLOAD_DIR). Metadata stored in Postgres.
    Auth: requires Bearer token (same as GraphQL), and user must own the errand.
    """

    # Auth
    token = _extract_bearer(request.headers.get("authorization"))
    # Accept static dev token for local/dev use
    if token == "devtoken123":
        user_id = 1  # Use a fixed user ID for dev
    else:
        user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    # Basic validation
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    # Read content (single file; keep it simple for now)
    content = await file.read()
    size_bytes = len(content)
    if size_bytes == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if size_bytes > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Store file with a random name to avoid collisions/path traversal.
    # Storage can be local (UPLOAD_DIR) or S3 (recommended for ECS/Fargate).
    stored_filename = build_stored_filename(file.filename)
    put_bytes(
        stored_filename=stored_filename,
        content=content,
        content_type=file.content_type,
    )

    async with AsyncSessionLocal() as session:
        model = await session.get(Errand, errand_id)
        if not model:
            raise HTTPException(status_code=404, detail="Errand not found")
        if str(model.user_id) != str(user_id) and (
            model.pilot_id is None or str(model.pilot_id) != str(user_id)
        ):
            raise HTTPException(status_code=403, detail="Not allowed")

        attachment = ErrandAttachment(
            errand_id=errand_id,
            original_filename=file.filename,
            stored_filename=stored_filename,
            content_type=file.content_type,
            size_bytes=size_bytes,
        )
        session.add(attachment)
        await session.commit()
        await session.refresh(attachment)

    return {
        "id": attachment.id,
        "errandId": attachment.errand_id,
        "filename": attachment.original_filename,
        "contentType": attachment.content_type,
        "sizeBytes": attachment.size_bytes,
        "url": f"/attachments/{attachment.id}/download",
    }


@app.get("/errands/{errand_id}/attachments")
async def list_errand_attachments(errand_id: Union[uuid.UUID, int, str], request: Request):
    """List attachments for an errand.

    Auth: requires Bearer token and ownership (errand owner).
    """

    token = _extract_bearer(request.headers.get("authorization"))
    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    async with AsyncSessionLocal() as session:
        model = await session.get(Errand, errand_id)
        if not model:
            raise HTTPException(status_code=404, detail="Errand not found")
        if str(model.user_id) != str(user_id):
            raise HTTPException(status_code=403, detail="Not allowed")

        # Keep it simple: fetch all attachments for this errand.
        # (No pagination yet; can add later if needed.)
        from sqlalchemy import select

        res = await session.execute(
            select(ErrandAttachment)
            .where(ErrandAttachment.errand_id == errand_id)
            .order_by(ErrandAttachment.id.desc())
        )
        items = res.scalars().all()

    return [
        {
            "id": a.id,
            "errandId": a.errand_id,
            "filename": a.original_filename,
            "contentType": a.content_type,
            "sizeBytes": a.size_bytes,
            "url": f"/attachments/{a.id}/download",
            "label": getattr(a, "label", None),
            "reviewStatus": str(getattr(a, "review_status", "pending") or "pending"),
            "reviewNote": getattr(a, "review_note", None),
            "reviewedAt": (
                a.reviewed_at.isoformat() if getattr(a, "reviewed_at", None) else None
            ),
            "reviewedByUserId": getattr(a, "reviewed_by_user_id", None),
            "createdAt": a.created_at.isoformat() if a.created_at else None,
        }
        for a in items
    ]


@app.get("/attachments")
async def list_all_attachments(request: Request):
    """List all attachments for the authenticated user.

    Auth: requires Bearer token and ownership (errand owner).
    """

    token = _extract_bearer(request.headers.get("authorization"))
    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        res = await session.execute(
            select(ErrandAttachment)
            .join(Errand, ErrandAttachment.errand_id == Errand.id)
            .where(cast(Errand.user_id, String) == str(user_id))
            .order_by(ErrandAttachment.id.desc())
        )
        items = res.scalars().all()

    return [
        {
            "id": a.id,
            "errandId": a.errand_id,
            "filename": a.original_filename,
            "contentType": a.content_type,
            "sizeBytes": a.size_bytes,
            "url": f"/attachments/{a.id}/download",
            "label": getattr(a, "label", None),
            "reviewStatus": str(getattr(a, "review_status", "pending") or "pending"),
            "reviewNote": getattr(a, "review_note", None),
            "reviewedAt": (
                a.reviewed_at.isoformat() if getattr(a, "reviewed_at", None) else None
            ),
            "reviewedByUserId": getattr(a, "reviewed_by_user_id", None),
            "createdAt": a.created_at.isoformat() if a.created_at else None,
        }
        for a in items
    ]


class AttachmentLabelIn(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120)


@app.put("/attachments/{attachment_id}/label")
async def update_attachment_label(
    attachment_id: int, payload: AttachmentLabelIn, request: Request
):
    """Owner updates an attachment label (document type/category)."""

    token = _extract_bearer(request.headers.get("authorization"))
    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    label = (payload.label or "").strip() or None

    async with AsyncSessionLocal() as session:
        attachment = await session.get(ErrandAttachment, attachment_id)
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        errand = await session.get(Errand, attachment.errand_id)
        if not errand:
            raise HTTPException(status_code=404, detail="Errand not found")
        if int(errand.user_id) != int(user_id):
            raise HTTPException(status_code=403, detail="Not allowed")

        attachment.label = label
        await session.commit()
        await session.refresh(attachment)

    return {
        "id": attachment.id,
        "label": attachment.label,
        "updatedAt": datetime.utcnow().isoformat(),
    }


async def _store_pilot_employment_attachment(
    file: UploadFile,
    label: str,
) -> tuple[str, int]:
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail=f"Missing {label} file")

    content = await file.read()
    size_bytes = len(content)
    if size_bytes == 0:
        raise HTTPException(status_code=400, detail=f"{label} file is empty")
    if size_bytes > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"{label} file too large (max 10MB)"
        )

    stored_filename = build_stored_filename(file.filename)
    put_bytes(
        stored_filename=stored_filename,
        content=content,
        content_type=file.content_type,
    )

    return stored_filename, size_bytes


@app.post("/pilot-employment/applications")
async def submit_pilot_employment_application(
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    experience: Optional[str] = Form(None),
    availability: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    resume: UploadFile = File(...),
    driver_license: Optional[UploadFile] = File(None),
    additional_document: Optional[UploadFile] = File(None),
):
    """Public pilot employment application intake with file uploads."""

    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    email = (email or "").strip().lower()

    if not first_name or not last_name or not email:
        raise HTTPException(status_code=400, detail="Missing required applicant fields")

    resume_stored, resume_size = await _store_pilot_employment_attachment(
        resume, "resume"
    )

    async with AsyncSessionLocal() as session:
        application = PilotEmploymentApplication(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=(phone or "").strip() or None,
            city=(city or "").strip() or None,
            country=(country or "").strip() or None,
            experience=(experience or "").strip() or None,
            availability=(availability or "").strip() or None,
            notes=(notes or "").strip() or None,
            status="submitted",
        )
        session.add(application)
        await session.commit()
        await session.refresh(application)

        attachments = []
        resume_attachment = PilotEmploymentAttachment(
            application_id=application.id,
            original_filename=resume.filename,
            stored_filename=resume_stored,
            content_type=resume.content_type,
            size_bytes=resume_size,
            label="resume",
        )
        session.add(resume_attachment)
        attachments.append(resume_attachment)

        if driver_license and driver_license.filename:
            stored_filename, size_bytes = await _store_pilot_employment_attachment(
                driver_license, "driver license"
            )
            license_attachment = PilotEmploymentAttachment(
                application_id=application.id,
                original_filename=driver_license.filename,
                stored_filename=stored_filename,
                content_type=driver_license.content_type,
                size_bytes=size_bytes,
                label="driver_license",
            )
            session.add(license_attachment)
            attachments.append(license_attachment)

        if additional_document and additional_document.filename:
            stored_filename, size_bytes = await _store_pilot_employment_attachment(
                additional_document, "additional document"
            )
            extra_attachment = PilotEmploymentAttachment(
                application_id=application.id,
                original_filename=additional_document.filename,
                stored_filename=stored_filename,
                content_type=additional_document.content_type,
                size_bytes=size_bytes,
                label="additional_document",
            )
            session.add(extra_attachment)
            attachments.append(extra_attachment)

        await session.commit()
        for attachment in attachments:
            await session.refresh(attachment)

    return {
        "id": application.id,
        "first_name": application.first_name,
        "last_name": application.last_name,
        "email": application.email,
        "status": application.status,
        "created_at": (
            application.created_at.isoformat() if application.created_at else None
        ),
        "attachments": [
            {
                "id": att.id,
                "original_filename": att.original_filename,
                "content_type": att.content_type,
                "size_bytes": att.size_bytes,
                "label": att.label,
                "created_at": att.created_at.isoformat() if att.created_at else None,
            }
            for att in attachments
        ],
    }


class CreateShareLinkIn(BaseModel):
    pin: str = Field(..., min_length=4, max_length=32)
    expires_in_hours: int = Field(default=24, ge=1, le=24 * 30)
    max_uses: int = Field(default=50, ge=1, le=500)


@app.post("/attachments/{attachment_id}/share")
async def create_attachment_share_link(
    attachment_id: int,
    payload: CreateShareLinkIn,
    request: Request,
):
    """Create a public share link (token + PIN) for an attachment.

    Security mode "C": anyone with the link can attempt access, but must also provide the PIN.
    Token and PIN are stored hashed.

    Auth: owner of the errand OR an admin.
    """

    token = _extract_bearer(request.headers.get("authorization"))
    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    raw_pin = (payload.pin or "").strip()
    if not raw_pin:
        raise HTTPException(status_code=400, detail="Missing PIN")

    # Random share token (shown once)
    share_token = secrets.token_urlsafe(24)
    token_hash = _sha256_hex(share_token)
    pin_hash = _sha256_hex(raw_pin)

    now = datetime.utcnow().replace(microsecond=0)
    expires_at = now + timedelta(hours=int(payload.expires_in_hours))

    async with AsyncSessionLocal() as session:
        attachment = await session.get(ErrandAttachment, attachment_id)
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        errand = await session.get(Errand, attachment.errand_id)
        if not errand:
            raise HTTPException(status_code=404, detail="Errand not found")

        user = await session.get(
            User, int(user_id), options=AUTH_SAFE_USER_LOAD_OPTIONS
        )
        user_email = user.email if user else None

        is_owner = int(errand.user_id) == int(user_id)
        is_admin = _is_admin_email(user_email)
        if not (is_owner or is_admin):
            raise HTTPException(status_code=403, detail="Not allowed")

        model = AttachmentShareLink(
            attachment_id=int(attachment.id),
            token_hash=token_hash,
            pin_hash=pin_hash,
            expires_at=expires_at,
            uses=0,
            max_uses=int(payload.max_uses),
            created_by_user_id=str(user_id),
        )

        session.add(model)
        await session.commit()
        await session.refresh(model)

    print(
        f"[share] action=create_share_link created_by_user_id={user_id} attachment_id={attachment_id} expires_at={expires_at.isoformat()} max_uses={payload.max_uses}"
    )

    return {
        "id": model.id,
        "token": share_token,
        "expiresAt": expires_at.isoformat(),
        "maxUses": model.max_uses,
        "uses": model.uses,
        # Clean default URL shape
        "url": f"/share/{share_token}",
    }


class ShareDownloadIn(BaseModel):
    pin: str = Field(..., min_length=4, max_length=32)


class PublicErrandProof(BaseModel):
    operator_verified: bool
    location_verified: bool
    proof_uploaded: bool
    photo_url: Optional[str] = None
    signature_url: Optional[str] = None
    completed_at: Optional[str] = None


class PublicErrandSummary(BaseModel):
    reference_number: str
    title: str
    status: str
    status_label: str
    pickup_location: Optional[str] = None
    dropoff_location: Optional[str] = None
    created_at: Optional[str] = None
    created_by: str
    estimated_time: str
    share_url: str
    proof: PublicErrandProof


@app.post("/share/{token}")
async def download_shared_attachment(token: str, payload: ShareDownloadIn):
    """Public download endpoint.

    Requires: token in URL + PIN in body.
    Enforces expiry + max uses.
    """

    token_hash = _sha256_hex(token)
    pin_hash = _sha256_hex((payload.pin or "").strip())

    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(AttachmentShareLink).where(
                AttachmentShareLink.token_hash == token_hash
            )
        )
        link = res.scalars().first()
        if not link:
            raise HTTPException(status_code=404, detail="Share link not found")

        if link.pin_hash != pin_hash:
            raise HTTPException(status_code=401, detail="Invalid PIN")

        now = datetime.utcnow()
        if link.expires_at and link.expires_at < now:
            raise HTTPException(status_code=410, detail="Share link expired")

        if int(link.uses or 0) >= int(link.max_uses or 0):
            raise HTTPException(status_code=410, detail="Share link exhausted")

        # Atomic increment (avoid race conditions)
        result = await session.execute(
            update(AttachmentShareLink)
            .where(
                AttachmentShareLink.id == link.id,
                AttachmentShareLink.uses < AttachmentShareLink.max_uses,
            )
            .values(uses=AttachmentShareLink.uses + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(status_code=410, detail="Share link exhausted")

        await session.commit()

        attachment = await session.get(ErrandAttachment, int(link.attachment_id))
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

    print(
        f"[share] action=download token_hash_prefix={token_hash[:8]} attachment_id={attachment.id}"
    )

    cfg = get_storage_config()
    if cfg.driver == "s3":
        key = s3_key(cfg.s3_prefix, attachment.stored_filename)
        url = presign_or_stream_key(
            key=key,
            filename=attachment.original_filename,
            content_type=attachment.content_type,
            expires_seconds=120,
        )
        return RedirectResponse(url=url, status_code=302)

    path = UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on server")

    return FileResponse(
        path=str(path),
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@app.get("/share/{token}/download")
async def download_shared_attachment_get(token: str, pin: str):
    """GET download endpoint for shared attachments.

    Accepts pin as a query param for email-friendly access.
    """

    token_hash = _sha256_hex(token)
    pin_hash = _sha256_hex((pin or "").strip())

    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(AttachmentShareLink).where(
                AttachmentShareLink.token_hash == token_hash
            )
        )
        link = res.scalars().first()
        if not link:
            raise HTTPException(status_code=404, detail="Share link not found")

        if link.pin_hash != pin_hash:
            raise HTTPException(status_code=401, detail="Invalid PIN")

        now = datetime.utcnow()
        if link.expires_at and link.expires_at < now:
            raise HTTPException(status_code=410, detail="Share link expired")

        if int(link.uses or 0) >= int(link.max_uses or 0):
            raise HTTPException(status_code=410, detail="Share link exhausted")

        result = await session.execute(
            update(AttachmentShareLink)
            .where(
                AttachmentShareLink.id == link.id,
                AttachmentShareLink.uses < AttachmentShareLink.max_uses,
            )
            .values(uses=AttachmentShareLink.uses + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise HTTPException(status_code=409, detail="Share link use limit reached")

        attachment = await session.get(ErrandAttachment, link.attachment_id)
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

    cfg = get_storage_config()
    if cfg.driver == "s3":
        key = s3_key(cfg.s3_prefix, attachment.stored_filename)
        url = presign_or_stream_key(
            key=key,
            filename=attachment.original_filename,
            content_type=attachment.content_type,
            expires_seconds=120,
        )
        return RedirectResponse(url=url, status_code=302)

    path = UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on server")

    return FileResponse(
        path=str(path),
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@app.get("/public/errands/{reference_number}", response_model=PublicErrandSummary)
async def public_errand_summary(reference_number: str):
    """Public errand summary for shareable links (sanitized)."""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Errand).where(Errand.reference_number == reference_number)
        )
        errand = result.scalar_one_or_none()

    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")

    status = (errand.status or "pending").lower()
    status_label = {
        "pending": "Waiting for Operator",
        "submitted": "Waiting for Operator",
        "accepted": "Operator Assigned",
        "in_progress": "In Progress",
        "completed": "Task Completed",
    }.get(status, status.replace("_", " ").title())

    created_at = errand.created_at.isoformat() if errand.created_at else None
    completed_at = errand.completed_at.isoformat() if errand.completed_at else None
    proof_uploaded = bool(errand.photo_url or errand.signature_url or completed_at)
    operator_verified = bool(errand.pilot_id)
    location_verified = bool(errand.started_at or errand.completed_at)
    app_base_url = (os.getenv("APP_BASE_URL") or "https://www.errandbridge.com").rstrip(
        "/"
    )
    share_url = f"{app_base_url}/e/{errand.reference_number}"

    return PublicErrandSummary(
        reference_number=errand.reference_number,
        title=errand.title,
        status=errand.status or "pending",
        status_label=status_label,
        pickup_location=errand.pickup_location,
        dropoff_location=errand.dropoff_location,
        created_at=created_at,
        created_by="Client abroad",
        estimated_time="2–4 hours",
        share_url=share_url,
        proof=PublicErrandProof(
            operator_verified=operator_verified,
            location_verified=location_verified,
            proof_uploaded=proof_uploaded,
            photo_url=errand.photo_url,
            signature_url=errand.signature_url,
            completed_at=completed_at,
        ),
    )


@app.get("/attachments/{attachment_id}")
async def download_attachment(attachment_id: int, request: Request):
    """Download an attachment.

    Auth: requires Bearer token and ownership (errand owner).
    """

    token = _extract_bearer(request.headers.get("authorization"))
    if not token:
        token = request.query_params.get("token")
    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    async with AsyncSessionLocal() as session:
        attachment = await session.get(ErrandAttachment, attachment_id)
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        # Verify ownership
        model = await session.get(Errand, attachment.errand_id)
        if not model:
            raise HTTPException(status_code=404, detail="Errand not found")
        if str(model.user_id) != str(user_id) and (
            model.pilot_id is None or str(model.pilot_id) != str(user_id)
        ):
            print(
                f"[DEBUG] 403 in download_attachment: model.user_id={model.user_id}, model.pilot_id={model.pilot_id}, request user_id={user_id}",
                flush=True,
            )
            raise HTTPException(status_code=403, detail="Not allowed")

    cfg = get_storage_config()
    if cfg.driver == "s3":
        key = s3_key(cfg.s3_prefix, attachment.stored_filename)
        url = presign_or_stream_key(
            key=key,
            filename=attachment.original_filename,
            content_type=attachment.content_type,
            expires_seconds=120,
        )
        return RedirectResponse(url=url, status_code=302)

    path = UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on server")

    return FileResponse(
        path=str(path),
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@app.get("/attachments/{attachment_id}/download")
async def download_attachment_alias(attachment_id: int, request: Request):
    # Compatibility alias for older clients that expect a "/download" suffix.
    return await download_attachment(attachment_id, request)


@app.post("/prompt/suggest", response_model=SuggestResponse)
def suggest(req: SuggestRequest) -> SuggestResponse:
    return _derive_draft(req.prompt, req.template_id)


@app.post("/prompt/ai-suggest", response_model=AISuggestResponse)
async def ai_suggest(req: AISuggestRequest) -> AISuggestResponse:
    """
    Generate AI-powered errand suggestions using OpenAI GPT-4.
    Enhances user descriptions with professional titles and detailed instructions.
    """
    print(
        f"[AI-SUGGEST] OpenAI client initialized: {openai_client is not None}",
        flush=True,
    )
    print(f"[AI-SUGGEST] API Key present: {bool(openai_api_key)}", flush=True)
    print(f"[AI-SUGGEST] Model: {openai_model}", flush=True)

    if not openai_client:
        # Fallback to rule-based suggestions if OpenAI not configured
        print("[AI-SUGGEST] OpenAI client not configured, using fallback", flush=True)
        fallback = _derive_draft(req.description, req.template_id)
        return AISuggestResponse(
            title=fallback.title,
            description=fallback.description,
            suggested_template=req.template_id,
            confidence=0.7,
        )

    # Build the system prompt
    system_prompt = """You are an expert errand assistant. Your job is to help users write clear, professional errand descriptions.

Given a user's errand description, you must:
1. Create a concise, professional TITLE (max 8 words)
2. Provide a detailed DESCRIPTION with actionable instructions
3. Suggest a template category from: diaspora_pickup, market_run, driver_dispatch, or leave blank

Format your response as JSON:
{
    "title": "Clear, Professional Title",
    "description": "Detailed instructions...",
    "template": "template_id_or_null"
}"""

    user_message = f"""User's errand request:
{req.description}

Template preference: {req.template_id or 'No preference'}

Please enhance this errand request with a professional title and detailed instructions."""

    try:
        response = await openai_client.chat.completions.create(
            model=openai_model,
            max_tokens=500,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception as exc:
        print(f"[AI-SUGGEST] OpenAI request failed, using fallback: {exc}", flush=True)
        fallback = _derive_draft(req.description, req.template_id)
        return AISuggestResponse(
            title=fallback.title,
            description=fallback.description or req.description,
            suggested_template=req.template_id,
            confidence=0.65,
        )

    # Parse the response
    response_text = response.choices[0].message.content or ""

    # Extract JSON from response
    import json

    json_str = response_text
    json_start = response_text.find("{")
    json_end = response_text.rfind("}") + 1
    if json_start >= 0 and json_end > json_start:
        json_str = response_text[json_start:json_end]

    try:
        ai_data = json.loads(json_str)
    except Exception:
        # Fallback if JSON not found
        ai_data = {
            "title": "AI-Suggested Errand",
            "description": response_text or req.description,
            "template": None,
        }
    return AISuggestResponse(
        title=ai_data.get("title", "Errand Request"),
        description=ai_data.get("description", req.description),
        suggested_template=ai_data.get("template"),
        confidence=0.95,
    )


@app.get("/")
def root():
    return {"message": "ErrandBridge FastAPI backend is running!"}


@app.get("/version")
def version():
    """Expose build and environment metadata for deployment verification."""
    return {
        "service": "errandbridge-backend",
        "environment": os.getenv("ENV", "unknown"),
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "build_id": os.getenv("BUILD_ID", "unknown"),
        "release": os.getenv("RELEASE_VERSION", "unknown"),
    }


@app.post("/test-post")
async def test_post(data: dict = None):
    _assert_dev_route_enabled()
    print("[TEST] POST endpoint called", flush=True)
    return {"test": "success", "received": data}
