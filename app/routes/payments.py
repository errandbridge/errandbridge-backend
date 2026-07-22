import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any, Literal, NamedTuple, Optional

try:
    import stripe
except ImportError:  # pragma: no cover - handled in environments without stripe installed
    stripe = None
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from database import AsyncSessionLocal
from models import (
    Errand,
    ErrandEvent,
    PromoCode,
    User,
    ClientSubscription,
    StripeCheckoutSession,
)
from auth import decode_access_token
from notification_utils import notify_pilot_tip
from promo_code_service import (
    normalize_promo_code,
    validate_promo_code_for_user,
)

from business_metrics import (
    observe_stripe_checkout_session,
    observe_stripe_verify_session,
    observe_stripe_webhook,
    observe_stripe_webhook_signature_invalid,
)

payments_router = APIRouter(prefix="/payments", tags=["payments"])
webhooks_router = APIRouter(prefix="/webhooks", tags=["payments"])
router = payments_router

_PAYMENT_CONFIRMED_TYPES = {"checkout.session.completed", "payment_intent.succeeded"}
_PAYMENT_FAILED_TYPES = {"payment_intent.payment_failed", "checkout.session.expired"}
_DEFAULT_SUCCESS_URL = "https://www.errandbridge.com/payment/success"
_DEFAULT_CANCEL_URL = "https://www.errandbridge.com/payment/cancel"
_DEFAULT_PROD_RETURN_ORIGINS = {
    "https://www.errandbridge.com",
    "https://errandbridge.com",
}
_DEFAULT_LOCAL_RETURN_ORIGINS = {
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
    # Common Ionic dev server
    "http://localhost:8100",
    "http://127.0.0.1:8100",
    # Android emulator host mapping (dev server)
    "http://10.0.2.2",
    "http://10.0.2.2:3000",
    "http://10.0.2.2:3001",
    "http://10.0.2.2:3002",
    "http://10.0.2.2:3003",
}
_DEFAULT_CURRENCY = "gbp"
_MIN_AMOUNT_CENTS = 50
_TIP_KIND = "tip"

# Reduce the price model by 20% across the board (non-tip, non-subscription).
_PRICE_MODEL_MULTIPLIER = 0.8
_SUPPORTED_CHECKOUT_CURRENCIES = {"usd", "gbp", "eur", "ngn", "aed", "cad"}
_PRICING_REGION_KEY_TO_COUNTRY_CODE = {
    "ng": "NG",
    "uk": "GB",
    "us": "US",
    "eu": "EU",
}
_COUNTRY_NAME_TO_CODE = {
    "nigeria": "NG",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",
    "united states": "US",
    "usa": "US",
    "canada": "CA",
    "france": "FR",
    "germany": "DE",
    "italy": "IT",
    "spain": "ES",
    "portugal": "PT",
    "netherlands": "NL",
    "belgium": "BE",
    "austria": "AT",
    "finland": "FI",
    "ireland": "IE",
    "greece": "GR",
    "poland": "PL",
    "united arab emirates": "AE",
    "uae": "AE",
}
_EUR_COUNTRY_CODES = {
    "AT",
    "BE",
    "CY",
    "DE",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PT",
    "SI",
    "SK",
    "PL",
}
_COUNTRY_CODE_TO_LABEL = {
    "NG": "Nigeria",
    "GB": "United Kingdom",
    "US": "United States",
    "CA": "Canada",
    "AE": "United Arab Emirates",
    "EU": "Europe",
}


class PaymentRoute(NamedTuple):
    provider: str
    currency: str
    country_code: Optional[str]
    country_label: Optional[str]
    payment_method_family: str


def _env_csv(name: str) -> list[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _normalize_checkout_currency(value: str | None) -> str:
    currency = str(value or "").strip().lower()
    return currency if currency in _SUPPORTED_CHECKOUT_CURRENCIES else _DEFAULT_CURRENCY


def _normalize_country_code(value: str | None) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    aliases = {
        "UK": "GB",
    }
    raw = aliases.get(raw, raw)
    if raw == "EUROPE":
        return "EU"
    if len(raw) == 2 and raw.isalpha():
        return raw
    return None


def _normalize_country_name(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _country_code_from_country_name(value: str | None) -> str | None:
    normalized = _normalize_country_name(value)
    if not normalized:
        return None
    if normalized in _COUNTRY_NAME_TO_CODE:
        return _COUNTRY_NAME_TO_CODE[normalized]
    for country_name, code in _COUNTRY_NAME_TO_CODE.items():
        if country_name in normalized:
            return code
    return None


def _country_code_from_metadata(metadata: dict[str, Any]) -> str | None:
    if not isinstance(metadata, dict):
        return None

    direct_code = (
        metadata.get("country_code")
        or metadata.get("countryCode")
        or metadata.get("payment_country_code")
        or metadata.get("client_country_code")
    )
    normalized_direct = _normalize_country_code(direct_code)
    if normalized_direct:
        return normalized_direct

    region_key = str(metadata.get("pricing_region_key") or metadata.get("pricingRegionKey") or "").strip().lower()
    if region_key and region_key in _PRICING_REGION_KEY_TO_COUNTRY_CODE:
        return _PRICING_REGION_KEY_TO_COUNTRY_CODE[region_key]

    return _country_code_from_country_name(
        metadata.get("country") or metadata.get("country_name") or metadata.get("client_country_name")
    )


def _route_currency_for_country_code(country_code: str | None, fallback_currency: str) -> str:
    if not country_code:
        return fallback_currency
    if country_code == "NG":
        return "ngn"
    if country_code == "GB":
        return "gbp"
    if country_code == "US":
        return "usd"
    if country_code == "CA":
        return "cad"
    if country_code == "AE":
        return "aed"
    if country_code == "EU" or country_code in _EUR_COUNTRY_CODES:
        return "eur"
    return fallback_currency


def _resolve_payment_route(
    *,
    country_code: str | None = None,
    country: str | None = None,
    currency: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PaymentRoute:
    resolved_country_code = (
        _normalize_country_code(country_code)
        or _country_code_from_country_name(country)
        or _country_code_from_metadata(metadata or {})
    )
    resolved_currency = _route_currency_for_country_code(
        resolved_country_code,
        _normalize_checkout_currency(currency),
    )
    country_label = _COUNTRY_CODE_TO_LABEL.get(resolved_country_code)
    if not country_label and resolved_country_code in _EUR_COUNTRY_CODES:
        country_label = "Europe"
    payment_method_family = "stripe_cards" if resolved_country_code == "NG" else "stripe_dynamic"
    return PaymentRoute(
        provider="stripe",
        currency=resolved_currency,
        country_code=resolved_country_code,
        country_label=country_label,
        payment_method_family=payment_method_family,
    )


def _normalize_origin(value: str | None) -> str | None:
    """Normalize an Origin-like value to '<scheme>://<host[:port]>' or None."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw or raw == "null":
        return None
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return None

    # Stripe should only ever redirect to http(s) URLs.
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _allowed_return_origins() -> set[str]:
    """Allowlist for frontend origins we will use for Stripe return URLs.

    Notes:
    - PAYMENTS_ALLOWED_ORIGINS is authoritative (it replaces built-in defaults).
    - OAUTH_ALLOWED_ORIGINS / CORS_ALLOW_ORIGINS are treated as additive when
      PAYMENTS_ALLOWED_ORIGINS is not set.
    - We keep a built-in set of localhost origins so CRA port fallbacks
      (:3001-:3003) don't silently break Stripe redirects during local dev.
    """

    env_name = (os.getenv("ENV") or os.getenv("BACKEND_ENVIRONMENT") or "").strip().lower()
    is_local_like = env_name in {"local", "dev", "development", "test"} or env_name.startswith("dev")

    payments_override = _env_csv("PAYMENTS_ALLOWED_ORIGINS")
    if payments_override:
        normalized = {_normalize_origin(o) for o in payments_override}
        resolved = {o for o in normalized if o}
        # Fail-safe: if the env var is present but invalid, don't lock out local
        # Stripe redirects.
        default_origins = _DEFAULT_LOCAL_RETURN_ORIGINS if is_local_like else _DEFAULT_PROD_RETURN_ORIGINS
        return resolved or set(default_origins)

    oauth_origins = _env_csv("OAUTH_ALLOWED_ORIGINS")
    cors_origins = _env_csv("CORS_ALLOW_ORIGINS")

    # Local/dev: treat env origins as additive so CRA can bump ports without
    # requiring developers to keep CORS_ALLOW_ORIGINS in sync with every port.
    if is_local_like:
        raw_origins: list[str] = []
        raw_origins.extend(oauth_origins)
        raw_origins.extend(cors_origins)
        normalized = {_normalize_origin(o) for o in raw_origins}
        resolved = {o for o in normalized if o}
        return set(_DEFAULT_PROD_RETURN_ORIGINS) | set(_DEFAULT_LOCAL_RETURN_ORIGINS) | resolved

    # Non-local: keep strict allowlist behavior.
    raw_origins = oauth_origins or cors_origins
    if not raw_origins:
        return set(_DEFAULT_PROD_RETURN_ORIGINS)
    normalized = {_normalize_origin(o) for o in raw_origins}
    return {o for o in normalized if o}


def _resolve_frontend_origin(request: Request | None) -> str | None:
    if request is None:
        return None
    origin = _normalize_origin(request.headers.get("origin"))
    if not origin:
        # Some clients omit Origin (e.g. server-to-server). As a best-effort,
        # try Referer and strip to its origin.
        ref = (request.headers.get("referer") or "").strip()
        try:
            parsed = urlparse(ref)
        except Exception:  # noqa: BLE001
            parsed = None
        if parsed and parsed.scheme and parsed.netloc:
            origin = _normalize_origin(f"{parsed.scheme}://{parsed.netloc}")

    if not origin:
        return None

    allowed = _allowed_return_origins()
    return origin if origin in allowed else None


def _parse_fx_rates_to_ngn() -> dict[str, float]:
    """Parse FX rates mapping currency->NGN rate.

    Env format: "USD:1500,GBP:1900,EUR:1650,AED:410,NGN:1"
    The rate means: 1 unit of <currency major> equals <rate> NGN major.
    """
    raw = (os.getenv("FX_TO_NGN_RATES") or "").strip()
    rates: dict[str, float] = {"NGN": 1.0}
    if not raw:
        return rates
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for part in parts:
        if ":" not in part:
            continue
        cur, val = part.split(":", 1)
        cur = (cur or "").strip().upper()
        try:
            rate = float(val)
        except ValueError:
            continue
        if cur and rate > 0:
            rates[cur] = rate
    return rates


def _currency_minor_per_major(currency: str) -> int:
    """Return how many minor units per 1 major unit for currency."""
    cur = (currency or "").strip().upper()
    # Zero-decimal currencies: add more as needed.
    if cur in {"JPY", "KRW"}:
        return 1
    return 100


def _compute_ngn_major(amount_total_minor: int | None, currency: str | None) -> int | None:
    """Compute canonical NGN major (rounded) from Stripe amount_total minor units."""
    if amount_total_minor is None:
        return None
    cur = (currency or "").strip().upper()
    if not cur:
        return None
    minor_per_major = _currency_minor_per_major(cur)
    if minor_per_major <= 0:
        return None

    amount_major = float(amount_total_minor) / float(minor_per_major)
    rates = _parse_fx_rates_to_ngn()
    rate = rates.get(cur)
    if rate is None:
        # No known FX rate; refuse to guess.
        return None
    return int(round(amount_major * float(rate)))


class CheckoutSessionRequest(BaseModel):
    amount_cents: Optional[int] = Field(default=None, ge=_MIN_AMOUNT_CENTS)
    currency: str = Field(default=_DEFAULT_CURRENCY, min_length=3, max_length=3)
    country_code: Optional[str] = Field(default=None, min_length=2, max_length=2)
    country: Optional[str] = None
    description: Optional[str] = None
    customer_email: Optional[str] = None
    reference_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    mode: Optional[Literal["payment", "subscription"]] = None
    plan: Optional[str] = None
    promo_code: Optional[str] = None


class CheckoutSessionResponse(BaseModel):
    session_id: str
    url: Optional[str] = None


class QuoteRequest(BaseModel):
    """Read-only pricing quote for a pending checkout.

    This endpoint is deliberately Stripe-independent so the frontend can display
    promo discounts and totals that match what Stripe will charge.
    """

    ui_amount_cents: int = Field(ge=_MIN_AMOUNT_CENTS)
    currency: str = Field(default=_DEFAULT_CURRENCY, min_length=3, max_length=3)
    country_code: Optional[str] = Field(default=None, min_length=2, max_length=2)
    country: Optional[str] = None
    promo_code: Optional[str] = None
    kind: Optional[str] = None


class QuoteResponse(BaseModel):
    ui_amount_cents: int
    final_amount_cents: int
    currency: str
    provider: str = "stripe"
    country_code: Optional[str] = None
    promo_code: Optional[str] = None
    promo_percent_off: Optional[int] = None
    price_model_multiplier: float = _PRICE_MODEL_MULTIPLIER


class VerifySessionRequest(BaseModel):
    session_id: str


class VerifySessionResponse(BaseModel):
    paid: bool
    status: Optional[str] = None
    payment_status: Optional[str] = None
    mode: Optional[str] = None
    customer_email: Optional[str] = None
    amount_total: Optional[int] = None
    currency: Optional[str] = None
    subscription_id: Optional[str] = None
    kind: Optional[str] = None
    errand_id: Optional[int] = None
    tip_errand_id: Optional[int] = None


class PaymentsHealthResponse(BaseModel):
        configured: bool
        subscription_configured: bool
        provider: str = "stripe"


class MySubscriptionResponse(BaseModel):
    active: bool
    status: Optional[str] = None
    plan: str = "plus"
    cancel_at_period_end: bool = False
    current_period_end: Optional[datetime] = None
    stripe_subscription_id: Optional[str] = None


def _get_metadata(data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata") or {}
    if isinstance(metadata, dict):
        return metadata
    return {}


def _parse_errand_id(metadata: dict[str, Any]) -> Optional[int]:
    errand_id = metadata.get("errand_id") or metadata.get("errandId") or metadata.get("errand")
    if errand_id is None:
        return None
    try:
        return int(errand_id)
    except (TypeError, ValueError):
        return None


def _parse_tip_errand_id(metadata: dict[str, Any]) -> Optional[int]:
    errand_id = (
        metadata.get("tip_errand_id")
        or metadata.get("tipErrandId")
        or metadata.get("tip_errand")
        or metadata.get("tipErrand")
    )
    if errand_id is None:
        return None
    try:
        return int(errand_id)
    except (TypeError, ValueError):
        return None


def _parse_checkout_kind(metadata: dict[str, Any]) -> str:
    raw = (
        metadata.get("kind")
        or metadata.get("checkout_kind")
        or metadata.get("payment_kind")
        or metadata.get("type")
        or "payment"
    )
    kind = str(raw).strip().lower()
    return kind or "payment"


def _parse_user_id(metadata: dict[str, Any]) -> Optional[int]:
    raw = metadata.get("user_id") or metadata.get("userId") or metadata.get("uid")
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


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


async def _resolve_user_id_from_request(request: Request) -> Optional[int]:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    token = _extract_bearer(header)
    user_id = decode_access_token(token) if token else None
    try:
        return int(user_id) if user_id else None
    except Exception:
        return None


def _apply_percent_discount(amount_cents: int, percent_off: int) -> int:
    try:
        cents = int(amount_cents)
        pct = int(percent_off)
    except Exception:
        return amount_cents
    if cents <= 0:
        return cents
    if pct <= 0:
        return cents
    if pct >= 100:
        return _MIN_AMOUNT_CENTS

    discounted = int(round(cents * (100 - pct) / 100.0))
    return max(_MIN_AMOUNT_CENTS, discounted)


def _apply_price_model_multiplier(amount_cents: int, multiplier: float) -> int:
    """Apply a global price-model multiplier with safety rails."""
    try:
        cents = int(amount_cents)
        m = float(multiplier)
    except Exception:
        return amount_cents
    if cents <= 0:
        return cents
    if not (m > 0):
        return cents
    adjusted = int(round(cents * m))
    return max(_MIN_AMOUNT_CENTS, adjusted)


def _event_payload(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "to_dict"):
        return event.to_dict()
    return json.loads(json.dumps(event))


def _ensure_stripe_ready() -> None:
    secret_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret_key:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stripe secret key not configured")
    if stripe is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stripe SDK not installed")
    stripe.api_key = secret_key


def _build_success_url(frontend_origin: str | None = None) -> str:
    # Explicit override wins (keeps current production behavior).
    explicit = (os.getenv("STRIPE_SUCCESS_URL") or "").strip()
    raw_success = explicit or ""
    if not raw_success and frontend_origin:
        raw_success = f"{frontend_origin.rstrip('/')}/payment/success"
    raw_success = raw_success or _DEFAULT_SUCCESS_URL

    if "{CHECKOUT_SESSION_ID}" in raw_success:
        return raw_success
    separator = "&" if "?" in raw_success else "?"
    return f"{raw_success}{separator}session_id={{CHECKOUT_SESSION_ID}}"


def _build_cancel_url(frontend_origin: str | None = None) -> str:
    explicit = (os.getenv("STRIPE_CANCEL_URL") or "").strip()
    if explicit:
        return explicit
    if frontend_origin:
        return f"{frontend_origin.rstrip('/')}/payment/cancel"
    return _DEFAULT_CANCEL_URL


def _resolve_checkout_mode(payload: CheckoutSessionRequest) -> str:
    if payload.mode == "subscription":
        return "subscription"
    plan = (payload.plan or payload.metadata.get("plan") or "").strip().lower()
    if plan in {"plus", "errandbridge_plus", "errandbridge-plus", "subscription"}:
        return "subscription"
    return "payment"


def _subscription_price_id() -> str:
    price_id = (os.getenv("STRIPE_PLUS_PRICE_ID") or os.getenv("STRIPE_SUBSCRIPTION_PRICE_ID") or "").strip()
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe subscription price ID not configured",
        )
    return price_id


@payments_router.get("/health", response_model=PaymentsHealthResponse)
async def payments_health():
    """Non-sensitive payment readiness probe.

    This is safe to call from the frontend to decide whether to show/enable
    Stripe Checkout actions. It deliberately avoids returning any secret values.
    """
    secret_key = bool((os.getenv("STRIPE_SECRET_KEY") or "").strip())
    sdk_ready = stripe is not None
    configured = secret_key and sdk_ready
    subscription_configured = bool((os.getenv("STRIPE_PLUS_PRICE_ID") or os.getenv("STRIPE_SUBSCRIPTION_PRICE_ID") or "").strip())
    return PaymentsHealthResponse(
        configured=configured,
        subscription_configured=subscription_configured,
    )


@payments_router.post("/quote", response_model=QuoteResponse)
async def quote_checkout(payload: QuoteRequest, request: Request):
    """Quote the final amount that will be charged at Stripe checkout.

    Notes:
    - Standard (non-tip) payments apply a global 0.8 multiplier server-side.
      The frontend compensates by sending amount/0.8, so the multiplier nets out
      to the UI amount before promo discounts are applied.
    - Promo discount is applied after the multiplier in the checkout endpoint.
      Under the compensation scheme, final = discount(ui_amount).
    """

    route = _resolve_payment_route(
        country_code=payload.country_code,
        country=payload.country,
        currency=payload.currency,
    )
    ui_amount_cents = int(payload.ui_amount_cents)
    currency = route.currency
    kind = (payload.kind or "payment").strip().lower() or "payment"

    final_amount_cents = ui_amount_cents
    promo_code_out: Optional[str] = None
    promo_percent_off: Optional[int] = None

    promo_raw = payload.promo_code
    if promo_raw:
        canonical = normalize_promo_code(promo_raw)
        if not canonical:
            raise HTTPException(status_code=400, detail="Invalid promo code")

        user_id = await _resolve_user_id_from_request(request)
        async with AsyncSessionLocal() as db:
            try:
                promo = await validate_promo_code_for_user(
                    db,
                    code=canonical,
                    user_id=user_id,
                )
            except ValueError as e:
                msg = str(e)
                # Preserve semantics: some promos are user-tied.
                if "login required" in msg.lower():
                    raise HTTPException(status_code=401, detail=msg) from e
                raise HTTPException(status_code=400, detail=msg) from e

        promo_percent_off = int(promo.percent_off or 0)
        promo_code_out = promo.code
        # Under the client compensation scheme, multiplier nets out to ui_amount.
        # Promo discount is then applied, matching create_checkout_session.
        final_amount_cents = _apply_percent_discount(ui_amount_cents, promo_percent_off)

    # Tips do not get the global multiplier in checkout-session, but quote remains
    # based on the UI amount to keep the contract simple.
    if kind == _TIP_KIND:
        final_amount_cents = ui_amount_cents if promo_percent_off is None else final_amount_cents

    return QuoteResponse(
        ui_amount_cents=ui_amount_cents,
        final_amount_cents=int(final_amount_cents),
        currency=currency,
        provider=route.provider,
        country_code=route.country_code,
        promo_code=promo_code_out,
        promo_percent_off=promo_percent_off,
    )


@payments_router.get("/subscription/me", response_model=MySubscriptionResponse)
async def my_subscription(request: Request):
    user_id = await _resolve_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    async with AsyncSessionLocal() as db:
        sub = await db.scalar(
            select(ClientSubscription)
            .where(
                ClientSubscription.user_id == int(user_id),
                ClientSubscription.plan == "plus",
            )
            .order_by(ClientSubscription.id.desc())
        )

    status_val = (sub.status if sub else None) or None
    active = bool(status_val in {"active", "trialing"})

    return MySubscriptionResponse(
        active=active,
        status=status_val,
        plan="plus",
        cancel_at_period_end=bool(getattr(sub, "cancel_at_period_end", False)) if sub else False,
        current_period_end=getattr(sub, "current_period_end", None) if sub else None,
        stripe_subscription_id=getattr(sub, "stripe_subscription_id", None) if sub else None,
    )


@payments_router.post("/checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(payload: CheckoutSessionRequest, request: Request):
    try:
        _ensure_stripe_ready()
    except HTTPException:
        # Stripe misconfiguration is a Tier-1 go-live blocker.
        observe_stripe_checkout_session(result="error", mode="unknown", kind="unknown")
        raise

    frontend_origin = _resolve_frontend_origin(request)

    metadata: dict[str, Any] = dict(payload.metadata or {})
    route = _resolve_payment_route(
        country_code=payload.country_code,
        country=payload.country,
        currency=payload.currency,
        metadata=metadata,
    )
    checkout_mode = _resolve_checkout_mode(payload)
    currency = route.currency
    requested_currency = _normalize_checkout_currency(payload.currency)

    # Best-effort: associate Stripe sessions with an authenticated user.
    user_id = await _resolve_user_id_from_request(request)
    if user_id:
        metadata.setdefault("user_id", str(user_id))
    metadata.setdefault("payment_provider", route.provider)
    metadata.setdefault("payment_currency", currency)
    metadata.setdefault("payment_method_family", route.payment_method_family)
    if route.country_code:
        metadata.setdefault("payment_country_code", route.country_code)
    if route.country_label:
        metadata.setdefault("payment_country_label", route.country_label)
    if requested_currency != currency:
        metadata.setdefault("client_requested_currency", requested_currency)
    normalized_client_country_code = _normalize_country_code(payload.country_code)
    if normalized_client_country_code:
        metadata.setdefault("client_country_code", normalized_client_country_code)
    if payload.country:
        metadata.setdefault("client_country_name", str(payload.country).strip())

    # Keep 'kind' low-cardinality: payment | tip | subscription.
    kind = "subscription" if checkout_mode == "subscription" else _parse_checkout_kind(metadata)

    session_kwargs: dict[str, Any] = {
        "success_url": _build_success_url(frontend_origin),
        "cancel_url": _build_cancel_url(frontend_origin),
        "mode": checkout_mode,
        "client_reference_id": payload.reference_id,
        "customer_email": payload.customer_email,
        "metadata": metadata,
    }

    # Local debugging: Stripe receipt-on-return depends on these URLs pointing back
    # to the SAME origin that initiated checkout (so sessionStorage snapshots exist).
    try:
        env_name = (os.getenv("ENV") or os.getenv("BACKEND_ENVIRONMENT") or "").strip().lower()
        if env_name == "local":
            raw_origin = request.headers.get("origin")
            raw_referer = request.headers.get("referer")
            print(
                "[PAYMENTS] checkout-session "
                f"origin={raw_origin!r} referer={raw_referer!r} "
                f"resolved_origin={frontend_origin!r} "
                f"success_url={session_kwargs.get('success_url')!r} "
                f"cancel_url={session_kwargs.get('cancel_url')!r}",
                flush=True,
            )
    except Exception:
        pass

    if checkout_mode == "subscription":
        if not user_id:
            raise HTTPException(status_code=401, detail="Missing bearer token")

        metadata.setdefault("kind", "subscription")
        metadata.setdefault("plan", "plus")

        # Prevent duplicate Plus checkouts for already-active subscribers.
        async with AsyncSessionLocal() as db:
            existing = await db.scalar(
                select(ClientSubscription).where(
                    ClientSubscription.user_id == int(user_id),
                    ClientSubscription.plan == "plus",
                    ClientSubscription.status.in_(["active", "trialing"]),
                )
            )
            if existing:
                raise HTTPException(status_code=409, detail="Already subscribed")

        price_id = _subscription_price_id()
        session_kwargs.update(
            {
                "line_items": [{"price": price_id, "quantity": 1}],
                "subscription_data": {"metadata": metadata},
            }
        )
    else:
        if payload.amount_cents is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="amount_cents is required")

        amount_cents = int(payload.amount_cents)
        metadata_to_use: dict[str, Any] = dict(metadata or {})

        # Tip validation (customer-initiated, post-completion)
        kind = _parse_checkout_kind(metadata_to_use)
        if kind == _TIP_KIND:
            tip_errand_id = _parse_tip_errand_id(metadata_to_use) or _parse_errand_id(metadata_to_use)
            if not tip_errand_id:
                raise HTTPException(status_code=400, detail="Missing tip_errand_id")

            user_id = await _resolve_user_id_from_request(request)
            if not user_id:
                raise HTTPException(status_code=401, detail="Missing bearer token")

            async with AsyncSessionLocal() as db:
                errand = await db.get(Errand, int(tip_errand_id))
                if not errand:
                    raise HTTPException(status_code=404, detail="Errand not found")
                if int(errand.user_id) != int(user_id):
                    raise HTTPException(status_code=403, detail="You do not own this errand")

                status_key = (errand.status or "").strip().lower()
                if status_key not in {"completed", "accepted"}:
                    raise HTTPException(
                        status_code=400,
                        detail="Tips are only available after the errand is completed.",
                    )
                if not getattr(errand, "pilot_id", None):
                    raise HTTPException(
                        status_code=400,
                        detail="This errand does not have an assigned Pilot.",
                    )
                if getattr(errand, "tip_paid_at", None) is not None:
                    raise HTTPException(
                        status_code=400,
                        detail="A tip has already been sent for this errand.",
                    )

        # Global price-model reduction applies to standard payments, but never to tips.
        if kind != _TIP_KIND:
            amount_cents = _apply_price_model_multiplier(amount_cents, _PRICE_MODEL_MULTIPLIER)
            metadata_to_use.setdefault("price_model_multiplier", str(_PRICE_MODEL_MULTIPLIER))

        promo_raw = payload.promo_code
        if promo_raw:
            canonical = normalize_promo_code(promo_raw)
            if not canonical:
                raise HTTPException(status_code=400, detail="Invalid promo code")

            user_id = await _resolve_user_id_from_request(request)
            async with AsyncSessionLocal() as db:
                try:
                    promo = await validate_promo_code_for_user(
                        db,
                        code=canonical,
                        user_id=user_id,
                    )
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e

            promo_percent_off = int(promo.percent_off or 0)
            amount_cents = _apply_percent_discount(amount_cents, promo_percent_off)
            metadata_to_use["promo_code"] = promo.code
            metadata_to_use["promo_percent_off"] = str(promo_percent_off)

        if kind == _TIP_KIND and not payload.description:
            description = "ErrandBridge tip"
        else:
            description = payload.description or "ErrandBridge payment"
        session_kwargs.update(
            {
                "line_items": [
                    {
                        "price_data": {
                            "currency": currency,
                            "unit_amount": amount_cents,
                            "product_data": {"name": description},
                        },
                        "quantity": 1,
                    }
                ],
                "payment_intent_data": {"metadata": metadata_to_use},
                "metadata": metadata_to_use,
            }
        )

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except Exception as exc:  # noqa: BLE001
        observe_stripe_checkout_session(result="error", mode=checkout_mode, kind=kind)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Stripe session creation failed") from exc

    observe_stripe_checkout_session(result="ok", mode=checkout_mode, kind=kind)

    # Best-effort local persistence for entitlement enforcement / reconciliation.
    try:
        async with AsyncSessionLocal() as db:
            existing = await db.scalar(
                select(StripeCheckoutSession).where(
                    StripeCheckoutSession.stripe_session_id == str(session.id)
                )
            )
            if not existing:
                db.add(
                    StripeCheckoutSession(
                        stripe_session_id=str(session.id),
                        user_id=int(user_id) if user_id else None,
                        kind=str(kind or "payment"),
                        mode=str(getattr(session, "mode", None) or checkout_mode),
                        paid=False,
                        currency=(getattr(session, "currency", None) or None),
                        amount_total_minor=getattr(session, "amount_total", None),
                        stripe_customer_id=getattr(session, "customer", None),
                        stripe_subscription_id=getattr(session, "subscription", None),
                    )
                )
                await db.commit()
    except Exception:
        pass

    return CheckoutSessionResponse(session_id=session.id, url=session.url)


@payments_router.post("/verify-session", response_model=VerifySessionResponse)
async def verify_checkout_session(payload: VerifySessionRequest):
    try:
        _ensure_stripe_ready()
    except HTTPException:
        observe_stripe_verify_session(result="error", paid=False, kind="unknown")
        raise

    try:
        session = stripe.checkout.Session.retrieve(payload.session_id, expand=["subscription"])
    except Exception as exc:  # noqa: BLE001
        observe_stripe_verify_session(result="error", paid=False, kind="unknown")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Stripe session lookup failed") from exc

    subscription = getattr(session, "subscription", None)
    subscription_id = getattr(subscription, "id", None) if subscription else None
    subscription_status = getattr(subscription, "status", None) if subscription else None

    paid = session.payment_status == "paid"
    if session.mode == "subscription" and subscription_status in {"active", "trialing"}:
        paid = True

    # Capture Stripe metadata (if present) so the frontend can distinguish a normal
    # checkout from a post-completion tip.
    try:
        metadata = getattr(session, "metadata", None) or {}
        metadata = metadata if isinstance(metadata, dict) else {}
    except Exception:
        metadata = {}

    kind = "subscription" if session.mode == "subscription" else _parse_checkout_kind(metadata)
    errand_id = _parse_errand_id(metadata) if kind != _TIP_KIND else None
    tip_errand_id = _parse_tip_errand_id(metadata) if kind == _TIP_KIND else None

    response = VerifySessionResponse(
        paid=paid,
        status=session.status,
        payment_status=session.payment_status,
        mode=session.mode,
        customer_email=getattr(getattr(session, "customer_details", None), "email", None),
        amount_total=session.amount_total,
        currency=session.currency,
        subscription_id=subscription_id,
        kind=kind,
        errand_id=errand_id,
        tip_errand_id=tip_errand_id,
    )

    observe_stripe_verify_session(result="ok", paid=bool(paid), kind=kind)

    # Best-effort persistence of session/subscription state for entitlement enforcement.
    try:
        metadata_user_id = _parse_user_id(metadata)
        async with AsyncSessionLocal() as db:
            sess_row = await db.scalar(
                select(StripeCheckoutSession).where(
                    StripeCheckoutSession.stripe_session_id == str(session.id)
                )
            )
            if not sess_row:
                sess_row = StripeCheckoutSession(stripe_session_id=str(session.id))
                db.add(sess_row)

            sess_row.user_id = sess_row.user_id or (int(metadata_user_id) if metadata_user_id else None)
            sess_row.kind = str(kind or sess_row.kind or "payment")
            sess_row.mode = str(session.mode or sess_row.mode or "payment")
            sess_row.paid = bool(paid)
            sess_row.amount_total_minor = session.amount_total
            sess_row.currency = session.currency
            sess_row.stripe_customer_id = getattr(session, "customer", None) or sess_row.stripe_customer_id
            sess_row.stripe_subscription_id = subscription_id or sess_row.stripe_subscription_id

            if session.mode == "subscription" and subscription_id and metadata_user_id:
                sub_row = await db.scalar(
                    select(ClientSubscription).where(
                        ClientSubscription.stripe_subscription_id == str(subscription_id)
                    )
                )
                if not sub_row:
                    sub_row = ClientSubscription(
                        user_id=int(metadata_user_id),
                        provider="stripe",
                        plan="plus",
                    )
                    db.add(sub_row)

                sub_row.user_id = int(metadata_user_id)
                sub_row.status = str(subscription_status or "unknown")
                sub_row.stripe_customer_id = (
                    getattr(subscription, "customer", None)
                    or getattr(session, "customer", None)
                    or sub_row.stripe_customer_id
                )
                sub_row.stripe_subscription_id = str(subscription_id)
                sub_row.cancel_at_period_end = bool(getattr(subscription, "cancel_at_period_end", False))

                period_end = getattr(subscription, "current_period_end", None)
                if isinstance(period_end, int):
                    sub_row.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)

            await db.commit()
    except Exception:
        pass

    # Persist Stripe-verified payment data onto the referenced errand (if provided).
    # The frontend should set metadata.errand_id when creating the Checkout Session.
    if paid:
        # Best-effort persistence of Stripe-verified metadata.
        try:
            if kind == _TIP_KIND and tip_errand_id:
                async with AsyncSessionLocal() as db:
                    errand = await db.get(Errand, int(tip_errand_id))
                    if errand and getattr(errand, "tip_paid_at", None) is None:
                        # Safety check: ensure the Stripe customer email matches the errand owner.
                        customer_email = (
                            getattr(getattr(session, "customer_details", None), "email", None)
                            or getattr(session, "customer_email", None)
                            or ""
                        ).strip().lower()

                        owner_email = ""
                        try:
                            owner = await db.get(User, int(errand.user_id))
                            owner_email = (owner.email or "").strip().lower() if owner else ""
                        except Exception:
                            owner_email = ""

                        if customer_email and owner_email and customer_email != owner_email:
                            # Do not persist tips to an unrelated errand.
                            return response

                        amount_total_minor = session.amount_total
                        currency = session.currency
                        if isinstance(amount_total_minor, int) and currency:
                            if hasattr(errand, "tip_amount_total_minor"):
                                errand.tip_amount_total_minor = amount_total_minor
                            if hasattr(errand, "tip_currency"):
                                errand.tip_currency = currency
                            if hasattr(errand, "tip_paid_at"):
                                errand.tip_paid_at = datetime.now(timezone.utc)
                            if hasattr(errand, "tip_stripe_session_id"):
                                errand.tip_stripe_session_id = session.id
                            if hasattr(errand, "tip"):
                                minor_per_major = _currency_minor_per_major(currency)
                                errand.tip = float(amount_total_minor) / float(minor_per_major)

                            note = f"stripe_session={session.id} tip={amount_total_minor} {currency}"
                            db.add(
                                ErrandEvent(
                                    errand_id=errand.id,
                                    event_type="tip_confirmed",
                                    old_status=errand.status,
                                    new_status=errand.status,
                                    note=note,
                                    user_id=errand.user_id,
                                )
                            )
                            db.add(errand)
                            await db.commit()

                            # Notify pilot (best-effort; do not fail verification if messaging fails).
                            try:
                                await notify_pilot_tip(
                                    db,
                                    errand=errand,
                                    amount_total_minor=amount_total_minor,
                                    currency=currency,
                                    trigger="stripe_verify",
                                )
                            except Exception:
                                pass

            elif errand_id:
                async with AsyncSessionLocal() as db:
                    errand = await db.get(Errand, int(errand_id))
                    if errand:
                        if hasattr(errand, "payment_amount_total_minor"):
                            errand.payment_amount_total_minor = session.amount_total
                        if hasattr(errand, "payment_currency"):
                            errand.payment_currency = session.currency
                        if hasattr(errand, "payment_amount_ngn_major"):
                            errand.payment_amount_ngn_major = _compute_ngn_major(
                                session.amount_total,
                                session.currency,
                            )
                        db.add(errand)

                        promo_code_raw = metadata.get("promo_code") if isinstance(metadata, dict) else None
                        if promo_code_raw:
                            canonical = normalize_promo_code(str(promo_code_raw))
                            if canonical:
                                promo = await db.scalar(select(PromoCode).where(PromoCode.code == canonical))
                                if promo and not promo.redeemed_at:
                                    if promo.user_id is None or int(promo.user_id) == int(errand.user_id):
                                        promo.redeemed_count = int(promo.redeemed_count or 0) + 1
                                        promo.redeemed_at = datetime.now(timezone.utc)
                                        promo.redeemed_errand_id = int(errand.id)
                                        db.add(promo)

                        await db.commit()
        except Exception:
            # Do not block the customer flow if persistence fails; webhook can catch up later.
            pass

    return response


async def _handle_stripe_webhook(request: Request, *, endpoint: str):
    payload = await request.body()
    signature_header = request.headers.get("stripe-signature")
    webhook_secret = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()

    try:
        if webhook_secret and signature_header:
            if stripe is None:
                raise HTTPException(status_code=500, detail="Stripe SDK not installed")
            try:
                event = stripe.Webhook.construct_event(payload, signature_header, webhook_secret)
            except Exception as exc:  # noqa: BLE001
                observe_stripe_webhook_signature_invalid()
                observe_stripe_webhook(endpoint=endpoint, result="invalid", event_type=None, kind="unknown")
                raise HTTPException(status_code=400, detail="Invalid Stripe payload") from exc
        else:
            event = json.loads(payload.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        observe_stripe_webhook(endpoint=endpoint, result="invalid", event_type=None, kind="unknown")
        raise HTTPException(status_code=400, detail="Invalid Stripe payload") from exc

    event_data = _event_payload(event)
    event_type = event_data.get("type")
    data_object = (event_data.get("data") or {}).get("object") or {}
    metadata = _get_metadata(data_object)

    kind = _parse_checkout_kind(metadata)
    errand_id = _parse_errand_id(metadata) if kind != _TIP_KIND else None
    tip_errand_id = _parse_tip_errand_id(metadata) if kind == _TIP_KIND else None

    target_errand_id = tip_errand_id if kind == _TIP_KIND else errand_id

    # We count the webhook as "ok" once parsed; downstream DB errors are tracked separately.
    observe_stripe_webhook(endpoint=endpoint, result="received", event_type=event_type, kind=kind)

    # Subscription reconciliation (no errand_id involved).
    if kind == "subscription" or (event_type or "").startswith("customer.subscription."):
        metadata_user_id = _parse_user_id(metadata)
        subscription_id = data_object.get("subscription") or data_object.get("id")
        subscription_status = data_object.get("status")
        cancel_at_period_end = data_object.get("cancel_at_period_end")
        current_period_end = data_object.get("current_period_end")
        stripe_customer_id = data_object.get("customer")

        # For checkout.session events, fetch the expanded subscription when possible.
        if (event_type or "") == "checkout.session.completed" and subscription_id and stripe is not None:
            try:
                _ensure_stripe_ready()
                full_session = stripe.checkout.Session.retrieve(
                    data_object.get("id"),
                    expand=["subscription"],
                )
                sub_obj = getattr(full_session, "subscription", None)
                if sub_obj is not None:
                    subscription_status = getattr(sub_obj, "status", None) or subscription_status
                    cancel_at_period_end = getattr(sub_obj, "cancel_at_period_end", None)
                    current_period_end = getattr(sub_obj, "current_period_end", None)
                    stripe_customer_id = getattr(sub_obj, "customer", None) or stripe_customer_id
            except Exception:
                pass

        if metadata_user_id and subscription_id:
            async with AsyncSessionLocal() as db:
                sub_row = await db.scalar(
                    select(ClientSubscription).where(
                        ClientSubscription.stripe_subscription_id == str(subscription_id)
                    )
                )
                if not sub_row:
                    sub_row = ClientSubscription(
                        user_id=int(metadata_user_id),
                        provider="stripe",
                        plan="plus",
                    )
                    db.add(sub_row)

                sub_row.user_id = int(metadata_user_id)
                if subscription_status:
                    sub_row.status = str(subscription_status)
                if stripe_customer_id:
                    sub_row.stripe_customer_id = str(stripe_customer_id)
                sub_row.stripe_subscription_id = str(subscription_id)
                if cancel_at_period_end is not None:
                    sub_row.cancel_at_period_end = bool(cancel_at_period_end)
                if isinstance(current_period_end, int):
                    sub_row.current_period_end = datetime.fromtimestamp(current_period_end, tz=timezone.utc)

                # Track checkout-session completion too, when the webhook object is a checkout session.
                session_id = data_object.get("id")
                if session_id:
                    sess_row = await db.scalar(
                        select(StripeCheckoutSession).where(
                            StripeCheckoutSession.stripe_session_id == str(session_id)
                        )
                    )
                    if not sess_row:
                        sess_row = StripeCheckoutSession(stripe_session_id=str(session_id))
                        db.add(sess_row)
                    sess_row.user_id = sess_row.user_id or int(metadata_user_id)
                    sess_row.kind = "subscription"
                    sess_row.mode = "subscription"
                    sess_row.stripe_customer_id = stripe_customer_id or sess_row.stripe_customer_id
                    sess_row.stripe_subscription_id = str(subscription_id)

                    payment_status = data_object.get("payment_status")
                    sess_row.paid = bool(payment_status == "paid" or (sub_row.status in {"active", "trialing"}))

                await db.commit()

        observe_stripe_webhook(endpoint=endpoint, result="processed", event_type=event_type, kind="subscription")
        return {"received": True}

    try:
        if target_errand_id:
            async with AsyncSessionLocal() as session_db:
                errand = await session_db.get(Errand, int(target_errand_id))
                if errand:
                    amount_total = data_object.get("amount_total")
                    currency = data_object.get("currency")

                if kind == _TIP_KIND:
                    event_label = (
                        "tip_confirmed"
                        if event_type in _PAYMENT_CONFIRMED_TYPES
                        else "tip_failed"
                        if event_type in _PAYMENT_FAILED_TYPES
                        else "stripe_event"
                    )

                    note = f"stripe_event={event_data.get('id')} type={event_type}"
                    if isinstance(amount_total, int) and currency:
                        note = f"{note} tip={amount_total} {currency}"

                    # Only persist on confirmed events.
                    if event_type in _PAYMENT_CONFIRMED_TYPES:
                        # Idempotency: do nothing if already recorded.
                        if getattr(errand, "tip_paid_at", None) is None and isinstance(amount_total, int) and currency:
                            if hasattr(errand, "tip_amount_total_minor"):
                                errand.tip_amount_total_minor = amount_total
                            if hasattr(errand, "tip_currency"):
                                errand.tip_currency = currency
                            if hasattr(errand, "tip_paid_at"):
                                errand.tip_paid_at = datetime.now(timezone.utc)
                            if hasattr(errand, "tip_stripe_session_id"):
                                errand.tip_stripe_session_id = data_object.get("id") or event_data.get("id")
                            if hasattr(errand, "tip"):
                                minor_per_major = _currency_minor_per_major(currency)
                                errand.tip = float(amount_total) / float(minor_per_major)
                            session_db.add(errand)

                    session_db.add(
                        ErrandEvent(
                            errand_id=errand.id,
                            event_type=event_label,
                            old_status=errand.status,
                            new_status=errand.status,
                            note=note,
                            user_id=errand.user_id,
                        )
                    )

                    await session_db.commit()

                    if (
                        event_type in _PAYMENT_CONFIRMED_TYPES
                        and getattr(errand, "tip_paid_at", None) is not None
                        and isinstance(amount_total, int)
                        and currency
                    ):
                        try:
                            await notify_pilot_tip(
                                session_db,
                                errand=errand,
                                amount_total_minor=amount_total,
                                currency=currency,
                                trigger="stripe_webhook",
                            )
                        except Exception:
                            pass

                    observe_stripe_webhook(endpoint=endpoint, result="processed", event_type=event_type, kind=kind)
                    return {"received": True}

                # Default behavior: persist payment metadata + log Stripe events.
                if isinstance(amount_total, int) and currency:
                    if hasattr(errand, "payment_amount_total_minor"):
                        errand.payment_amount_total_minor = amount_total
                    if hasattr(errand, "payment_currency"):
                        errand.payment_currency = currency
                    if hasattr(errand, "payment_amount_ngn_major"):
                        errand.payment_amount_ngn_major = _compute_ngn_major(amount_total, currency)
                    session_db.add(errand)

                event_label = (
                    "payment_confirmed"
                    if event_type in _PAYMENT_CONFIRMED_TYPES
                    else "payment_failed"
                    if event_type in _PAYMENT_FAILED_TYPES
                    else "stripe_event"
                )
                note = f"stripe_event={event_data.get('id')} type={event_type}"
                session_db.add(
                    ErrandEvent(
                        errand_id=errand.id,
                        event_type=event_label,
                        old_status=errand.status,
                        new_status=errand.status,
                        note=note,
                        user_id=errand.user_id,
                    )
                )

                if event_type in _PAYMENT_CONFIRMED_TYPES:
                    promo_code_raw = metadata.get("promo_code")
                    if promo_code_raw:
                        canonical = normalize_promo_code(str(promo_code_raw))
                        if canonical:
                            promo = await session_db.scalar(
                                select(PromoCode).where(PromoCode.code == canonical)
                            )
                            if promo and not promo.redeemed_at:
                                if promo.user_id is None or int(promo.user_id) == int(errand.user_id):
                                    promo.redeemed_count = int(promo.redeemed_count or 0) + 1
                                    promo.redeemed_at = datetime.now(timezone.utc)
                                    promo.redeemed_errand_id = int(errand.id)
                                    session_db.add(promo)

                await session_db.commit()

                observe_stripe_webhook(endpoint=endpoint, result="processed", event_type=event_type, kind=kind)

    except HTTPException:
        observe_stripe_webhook(endpoint=endpoint, result="error", event_type=event_type, kind=kind)
        raise
    except Exception:
        observe_stripe_webhook(endpoint=endpoint, result="error", event_type=event_type, kind=kind)
        raise

    return {"received": True}


@webhooks_router.post("/stripe")
async def stripe_webhook(request: Request):
    return await _handle_stripe_webhook(request, endpoint="webhooks_stripe")


@payments_router.post("/webhook")
async def stripe_payments_webhook(request: Request):
    return await _handle_stripe_webhook(request, endpoint="payments_webhook")
