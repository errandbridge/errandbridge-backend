from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

try:
    import stripe
except ImportError:  # pragma: no cover - handled by callers in minimal environments
    stripe = None

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import StripeCheckoutSession


PaymentAction = Literal[
    "captured",
    "already_captured",
    "authorization_cancelled",
    "already_cancelled",
    "demo",
    "no_payment",
]


@dataclass(frozen=True)
class PaymentLifecycleResult:
    action: PaymentAction
    payment_intent_id: str | None = None
    status: str | None = None


class PaymentLifecycleError(RuntimeError):
    """Raised when a linked Stripe payment cannot complete a lifecycle action."""


def _stripe_value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _require_stripe() -> None:
    if stripe is None:
        raise PaymentLifecycleError("Stripe SDK is unavailable")


def _load_payment_intent(stripe_reference: str) -> Any:
    _require_stripe()

    if stripe_reference.startswith("pi_"):
        return stripe.PaymentIntent.retrieve(stripe_reference)

    checkout_session = stripe.checkout.Session.retrieve(
        stripe_reference,
        expand=["payment_intent"],
    )
    payment_intent = _stripe_value(checkout_session, "payment_intent")
    if not payment_intent:
        raise PaymentLifecycleError("Stripe checkout has no PaymentIntent")
    if isinstance(payment_intent, str):
        return stripe.PaymentIntent.retrieve(payment_intent)
    return payment_intent


async def _linked_payment_reference(
    db: AsyncSession, errand_id: Any
) -> str | None:
    row = await db.scalar(
        select(StripeCheckoutSession)
        .where(
            cast(StripeCheckoutSession.used_for_errand_id, String) == str(errand_id),
            StripeCheckoutSession.kind == "payment",
            StripeCheckoutSession.mode == "payment",
        )
        .order_by(StripeCheckoutSession.created_at.desc())
    )
    return str(row.stripe_session_id) if row else None


async def capture_errand_payment(
    db: AsyncSession, errand_id: Any
) -> PaymentLifecycleResult:
    """Capture the client's authorized payment when work is confirmed complete.

    The operation is idempotent: already-captured PaymentIntents are accepted.
    Legacy/demo errands without a linked real Stripe payment remain completable.
    """

    reference = await _linked_payment_reference(db, errand_id)
    if not reference:
        return PaymentLifecycleResult(action="no_payment")
    if reference.startswith("demo_"):
        return PaymentLifecycleResult(action="demo", payment_intent_id=reference)

    try:
        intent = _load_payment_intent(reference)
        intent_id = str(_stripe_value(intent, "id") or "") or None
        intent_status = str(_stripe_value(intent, "status") or "")

        if intent_status == "succeeded":
            return PaymentLifecycleResult(
                action="already_captured",
                payment_intent_id=intent_id,
                status=intent_status,
            )
        if intent_status != "requires_capture" or not intent_id:
            raise PaymentLifecycleError(
                f"Payment is not capturable (Stripe status: {intent_status or 'unknown'})"
            )

        captured = stripe.PaymentIntent.capture(intent_id)
        captured_status = str(_stripe_value(captured, "status") or "")
        if captured_status != "succeeded":
            raise PaymentLifecycleError(
                f"Stripe did not complete capture (status: {captured_status or 'unknown'})"
            )
        return PaymentLifecycleResult(
            action="captured",
            payment_intent_id=intent_id,
            status=captured_status,
        )
    except PaymentLifecycleError:
        raise
    except Exception as exc:
        raise PaymentLifecycleError("Stripe payment capture failed") from exc


async def cancel_errand_authorization(
    db: AsyncSession, errand_id: Any
) -> PaymentLifecycleResult:
    """Release an uncaptured card authorization for a cancelled errand."""

    reference = await _linked_payment_reference(db, errand_id)
    if not reference:
        return PaymentLifecycleResult(action="no_payment")
    if reference.startswith("demo_"):
        return PaymentLifecycleResult(action="demo", payment_intent_id=reference)

    try:
        intent = _load_payment_intent(reference)
        intent_id = str(_stripe_value(intent, "id") or "") or None
        intent_status = str(_stripe_value(intent, "status") or "")

        if intent_status == "canceled":
            return PaymentLifecycleResult(
                action="already_cancelled",
                payment_intent_id=intent_id,
                status=intent_status,
            )
        if intent_status == "succeeded":
            return PaymentLifecycleResult(
                action="already_captured",
                payment_intent_id=intent_id,
                status=intent_status,
            )
        if intent_status != "requires_capture" or not intent_id:
            raise PaymentLifecycleError(
                f"Payment authorization is not releasable (Stripe status: {intent_status or 'unknown'})"
            )

        cancelled = stripe.PaymentIntent.cancel(intent_id)
        cancelled_status = str(_stripe_value(cancelled, "status") or "")
        return PaymentLifecycleResult(
            action="authorization_cancelled",
            payment_intent_id=intent_id,
            status=cancelled_status,
        )
    except PaymentLifecycleError:
        raise
    except Exception as exc:
        raise PaymentLifecycleError("Stripe authorization release failed") from exc
