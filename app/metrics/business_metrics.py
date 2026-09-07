"""ErrandBridge business-event Prometheus metrics.

These metrics complement FastAPI request metrics from prometheus-fastapi-instrumentator.

Design goals:
- Low-cardinality labels only (never label by errand_id, user_id, email, etc.).
- Explicit counters for Tier-1 go-live events (payments/webhooks/uploads/tracking).
- Helpers that are safe to call from request paths.

All metrics are registered on the default prometheus_client registry and will be
exposed via the existing /metrics endpoint.
"""

from __future__ import annotations

import re
from typing import Optional

from prometheus_client import Counter

_LABEL_RE = re.compile(r"[^a-zA-Z0-9_\-]")


def _label(value: Optional[str], *, default: str = "unknown", max_len: int = 32) -> str:
    """Coerce a label value to a safe, bounded string."""
    raw = (str(value) if value is not None else "").strip().lower()
    if not raw:
        return default
    raw = _LABEL_RE.sub("_", raw)
    if len(raw) > max_len:
        raw = raw[:max_len]
    return raw or default


def _stripe_event_group(event_type: Optional[str]) -> str:
    """Bucket Stripe event types into a small set of groups."""
    et = (event_type or "").strip().lower()
    if et in {"checkout.session.completed", "payment_intent.succeeded"}:
        return "confirmed"
    if et in {"payment_intent.payment_failed", "checkout.session.expired"}:
        return "failed"
    return "other"


# ===== Payments / Stripe =====

EB_STRIPE_CHECKOUT_SESSION_TOTAL = Counter(
    "eb_stripe_checkout_session_total",
    "Stripe checkout-session results.",
    labelnames=["result", "mode", "kind"],
)

EB_STRIPE_VERIFY_SESSION_TOTAL = Counter(
    "eb_stripe_verify_session_total",
    "Stripe verify-session results.",
    labelnames=["result", "paid", "kind"],
)

EB_STRIPE_WEBHOOK_EVENTS_TOTAL = Counter(
    "eb_stripe_webhook_events_total",
    "Stripe webhook processing results.",
    labelnames=["endpoint", "result", "group", "kind"],
)

EB_STRIPE_WEBHOOK_SIGNATURE_INVALID_TOTAL = Counter(
    "eb_stripe_webhook_signature_invalid_total",
    "Stripe webhook signature verification failures (when webhook secret is configured).",
)


def observe_stripe_checkout_session(*, result: str, mode: str, kind: str) -> None:
    EB_STRIPE_CHECKOUT_SESSION_TOTAL.labels(
        result=_label(result),
        mode=_label(mode),
        kind=_label(kind),
    ).inc()


def observe_stripe_verify_session(*, result: str, paid: bool, kind: str) -> None:
    EB_STRIPE_VERIFY_SESSION_TOTAL.labels(
        result=_label(result),
        paid="true" if bool(paid) else "false",
        kind=_label(kind),
    ).inc()


def observe_stripe_webhook(
    *,
    endpoint: str,
    result: str,
    event_type: Optional[str],
    kind: str,
) -> None:
    EB_STRIPE_WEBHOOK_EVENTS_TOTAL.labels(
        endpoint=_label(endpoint),
        result=_label(result),
        group=_stripe_event_group(event_type),
        kind=_label(kind),
    ).inc()


def observe_stripe_webhook_signature_invalid() -> None:
    EB_STRIPE_WEBHOOK_SIGNATURE_INVALID_TOTAL.inc()


# ===== Uploads =====

EB_UPLOAD_ERRAND_ATTACHMENT_TOTAL = Counter(
    "eb_upload_errand_attachment_total",
    "Errand attachment upload results.",
    labelnames=["result", "driver"],
)

EB_UPLOAD_BYTES_TOTAL = Counter(
    "eb_upload_bytes_total",
    "Total bytes uploaded (by storage driver and scope).",
    labelnames=["driver", "scope"],
)


def observe_upload_errand_attachment(*, result: str, driver: str) -> None:
    EB_UPLOAD_ERRAND_ATTACHMENT_TOTAL.labels(
        result=_label(result),
        driver=_label(driver),
    ).inc()


def add_upload_bytes(*, driver: str, scope: str, size_bytes: int) -> None:
    try:
        n = int(size_bytes)
    except Exception:
        return
    if n <= 0:
        return
    EB_UPLOAD_BYTES_TOTAL.labels(driver=_label(driver), scope=_label(scope)).inc(n)


# ===== Tracking =====

EB_TRACKING_UPDATE_TOTAL = Counter(
    "eb_tracking_update_total",
    "Pilot tracking update results.",
    labelnames=["result", "reason"],
)

EB_TRACKING_DELAY_DETECTED_TOTAL = Counter(
    "eb_tracking_delay_detected_total",
    "Delay/stall detected events (from tracking).",
    labelnames=["trigger"],
)


def observe_tracking_update(*, result: str, reason: str = "") -> None:
    EB_TRACKING_UPDATE_TOTAL.labels(
        result=_label(result),
        reason=_label(reason, default="none"),
    ).inc()


def observe_tracking_delay_detected(*, trigger: str) -> None:
    EB_TRACKING_DELAY_DETECTED_TOTAL.labels(trigger=_label(trigger)).inc()
