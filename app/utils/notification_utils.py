from __future__ import annotations

import asyncio
import os
import hashlib
import hmac
from typing import Optional

from app.services.emailer import send_email
from app.services.sms_sender import send_sms
from app.utils.admin_utils import admin_emails
from models import Errand, User


def _status_label(status: Optional[str]) -> str:
    return (status or "").replace("_", " ").strip().title() or "Update"


def _errand_reference(errand: Errand) -> str:
    return errand.reference_number or f"EB-{errand.id}"


def _public_web_base() -> str:
    return (
        os.getenv("PUBLIC_WEB_URL")
        or os.getenv("FRONTEND_URL")
        or "http://localhost:3000"
    ).rstrip("/")


def _currency_minor_per_major(currency: str) -> int:
    cur = (currency or "").strip().upper()
    # Zero-decimal currencies: add more as needed.
    if cur in {"JPY", "KRW"}:
        return 1
    return 100


def _format_money(amount_total_minor: int | None, currency: str | None) -> str:
    if amount_total_minor is None or currency is None:
        return ""
    try:
        minor = int(amount_total_minor)
    except Exception:
        return ""
    cur = (currency or "").strip().upper()
    if not cur:
        return ""
    minor_per_major = _currency_minor_per_major(cur)
    amount_major = float(minor) / float(minor_per_major)

    # Prefer a friendly symbol when we can; fall back to ISO currency code.
    symbols = {
        "USD": "$",
        "CAD": "$",
        "AUD": "$",
        "NZD": "$",
        "EUR": "€",
        "GBP": "£",
    }
    prefix = symbols.get(cur)
    if minor_per_major == 1:
        return f"{prefix}{amount_major:.0f}" if prefix else f"{cur} {amount_major:.0f}"
    return f"{prefix}{amount_major:.2f}" if prefix else f"{cur} {amount_major:.2f}"


def pilot_web_base() -> str:
    return (
        os.getenv("PUBLIC_PILOT_WEB_URL")
        or os.getenv("PILOT_WEB_URL")
        or os.getenv("PILOT_PORTAL_URL")
        or _public_web_base()
    ).rstrip("/")


def _availability_secret() -> str:
    return (
        os.getenv("PILOT_AVAILABILITY_SECRET")
        or os.getenv("JWT_SECRET")
        or os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
    )


def build_pilot_availability_token(
    errand_id: int, pilot_id: int, expires_at: int
) -> str:
    msg = f"{errand_id}:{pilot_id}:{expires_at}".encode("utf-8")
    return hmac.new(
        _availability_secret().encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()


def _tracking_link(errand: Errand) -> str:
    return f"{_public_web_base()}/tracking/{errand.id}"


def _admin_recipients() -> list[str]:
    return sorted(admin_emails())


async def notify_customer_status(
    session,
    *,
    errand: Errand,
    old_status: Optional[str],
    new_status: Optional[str],
    trigger: str,
    message: Optional[str] = None,
) -> None:
    user = await session.get(User, int(errand.user_id))
    if not user or not user.email:
        return

    subject = f"Errand update: {_status_label(new_status)}"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"Your errand has a new update.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Previous status: {_status_label(old_status)}\n"
        f"Current status: {_status_label(new_status)}\n"
        f"Pickup: {errand.pickup_location or '-'}\n"
        f"Dropoff: {errand.dropoff_location or '-'}\n\n"
        f"Update source: {trigger}\n"
    )

    if message:
        body += f"\nDetails: {message}\n"

    body += "\nIf you have questions, reply to this email."

    await asyncio.to_thread(
        send_email, to_email=user.email, subject=subject, body_text=body
    )


async def notify_pilot_status(
    session,
    *,
    errand: Errand,
    new_status: Optional[str],
    trigger: str,
    pilot_user: Optional[User] = None,
) -> None:
    pilot = pilot_user
    if not pilot and errand.pilot_id:
        pilot = await session.get(User, int(errand.pilot_id))
    if not pilot or not pilot.email:
        return

    subject = f"Pilot update: {_status_label(new_status)}"
    body = (
        f"Hi {pilot.first_name or 'there'},\n\n"
        f"You have a new update on an errand you accepted.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Status: {_status_label(new_status)}\n"
        f"Pickup: {errand.pickup_location or '-'}\n"
        f"Dropoff: {errand.dropoff_location or '-'}\n\n"
        f"Update source: {trigger}\n\n"
        "Thanks for helping customers with their errands."
    )

    await asyncio.to_thread(
        send_email, to_email=pilot.email, subject=subject, body_text=body
    )


async def notify_pilot_tip(
    session,
    *,
    # Real signature below
    errand: Errand | None = None,
    pilot_user: Optional[User] = None,
    # Back-compat: older/internal callers may still use this kwarg.
    errandsafe_pilot_user: Optional[User] = None,
    amount_total_minor: int = 0,
    currency: str = "",
    trigger: str = "tip",
) -> None:
    """Notify a Pilot that they received a tip.

    NOTE: This intentionally does not include any customer contact info.
    """

    if errand is None:
        return

    # Resolve pilot
    pilot = pilot_user or errandsafe_pilot_user
    if not pilot and getattr(errand, "pilot_id", None):
        pilot = await session.get(User, int(errand.pilot_id))
    if not pilot or (not pilot.email and not pilot.phone):
        return

    amount_label = _format_money(amount_total_minor, currency) or "a tip"
    subject = f"You received a tip • {amount_label}"
    body = (
        f"Hi {pilot.first_name or 'there'},\n\n"
        f"Good news - a customer left you a tip for an errand you completed.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Tip amount: {amount_label}\n\n"
        "Thanks for being a trusted local Pilot on ErrandBridge."
    )

    if pilot.email:
        await asyncio.to_thread(
            send_email, to_email=pilot.email, subject=subject, body_text=body
        )

    if pilot.phone:
        sms_body = f"Tip received: {amount_label} for {_errand_reference(errand)}. Thank you for helping on ErrandBridge."
        await asyncio.to_thread(send_sms, to_number=pilot.phone, body_text=sms_body)


async def notify_pilot_job_reminder(
    session,
    *,
    errand: Errand,
    pilot_user: Optional[User] = None,
    minutes_to_start: Optional[float] = None,
    availability_links: Optional[dict] = None,
) -> None:
    pilot = pilot_user
    if not pilot and errand.pilot_id:
        pilot = await session.get(User, int(errand.pilot_id))
    if not pilot or not pilot.email:
        return

    timing_note = ""
    if minutes_to_start is not None:
        if minutes_to_start <= 0:
            timing_note = "Start time is now or overdue."
        else:
            timing_note = f"Starts in about {minutes_to_start:.0f} minutes."

    subject = f"Upcoming errand reminder: {_errand_reference(errand)}"
    body = (
        f"Hi {pilot.first_name or 'there'},\n\n"
        "This is a reminder for your upcoming errand assignment.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Status: {_status_label(errand.status)}\n"
        f"Pickup: {errand.pickup_location or '-'}\n"
        f"Dropoff: {errand.dropoff_location or '-'}\n"
    )

    if errand.pickup_time_slot_start:
        body += f"Pickup window starts: {errand.pickup_time_slot_start.isoformat()}\n"
    if errand.pickup_time_slot_end:
        body += f"Pickup window ends: {errand.pickup_time_slot_end.isoformat()}\n"
    if timing_note:
        body += f"\n{timing_note}\n"

    if availability_links:
        yes_link = availability_links.get("yes")
        no_link = availability_links.get("no")
        body += (
            "\nPlease confirm availability 1 hour before pickup:\n"
            f"Yes: {yes_link}\n"
            f"No: {no_link}\n"
        )

    body += "\nPlease be prepared and contact admin if you need to reschedule."

    await asyncio.to_thread(
        send_email, to_email=pilot.email, subject=subject, body_text=body
    )

    if pilot.phone:
        sms_body = (
            f"Errand reminder: {_errand_reference(errand)}. {errand.title}. "
            f"Pickup: {errand.pickup_location or '-'} → Dropoff: {errand.dropoff_location or '-'}."
        )
        if timing_note:
            sms_body += f" {timing_note}"
        if availability_links:
            sms_body += f" Reply: YES {availability_links.get('yes')} or NO {availability_links.get('no')}."
        await asyncio.to_thread(send_sms, to_number=pilot.phone, body_text=sms_body)


async def notify_admin_status(
    session,
    *,
    errand: Errand,
    old_status: Optional[str],
    new_status: Optional[str],
    trigger: str,
    message: Optional[str] = None,
    include_tracking: bool = False,
) -> None:
    recipients = _admin_recipients()
    if not recipients:
        return

    subject = f"Admin alert: {_status_label(new_status)}"
    body = (
        "Admin update for an errand.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Previous status: {_status_label(old_status)}\n"
        f"Current status: {_status_label(new_status)}\n"
        f"Pickup: {errand.pickup_location or '-'}\n"
        f"Dropoff: {errand.dropoff_location or '-'}\n"
    )

    if include_tracking:
        body += f"Live tracking: {_tracking_link(errand)}\n"

    if message:
        body += f"\nNote: {message}\n"

    body += f"\nUpdate source: {trigger}\n"

    for recipient in recipients:
        await asyncio.to_thread(
            send_email, to_email=recipient, subject=subject, body_text=body
        )


async def notify_tracking_started(
    session,
    *,
    errand: Errand,
    trigger: str,
) -> None:
    user = await session.get(User, int(errand.user_id))
    tracking_url = _tracking_link(errand)

    if user and user.email:
        subject = "Live tracking started"
        body = (
            f"Hi {user.first_name or 'there'},\n\n"
            "Your errand is now in progress. Live tracking is available here:\n"
            f"{tracking_url}\n\n"
            f"Reference: {_errand_reference(errand)}\n"
            f"Title: {errand.title}\n"
            f"Update source: {trigger}\n"
        )
        await asyncio.to_thread(
            send_email, to_email=user.email, subject=subject, body_text=body
        )

    await notify_admin_status(
        session,
        errand=errand,
        old_status=errand.status,
        new_status=errand.status,
        trigger=trigger,
        message="Pilot started the journey. Live tracking is active.",
        include_tracking=True,
    )


async def notify_delay_detected(
    session,
    *,
    errand: Errand,
    minutes_idle: float,
    distance_meters: float,
    trigger: str,
) -> None:
    tracking_url = _tracking_link(errand)
    note = (
        f"Pilot appears idle for {minutes_idle:.1f} minutes (movement {distance_meters:.0f}m). "
        f"Tracking: {tracking_url}"
    )

    try:
        await notify_customer_status(
            session,
            errand=errand,
            old_status=errand.status,
            new_status=errand.status,
            trigger=trigger,
            message=(
                "We noticed a brief pause in movement and are monitoring the trip. "
                f"You can keep tracking here: {tracking_url}"
            ),
        )
    except Exception:
        pass

    await notify_admin_status(
        session,
        errand=errand,
        old_status=errand.status,
        new_status=errand.status,
        trigger=trigger,
        message=note,
        include_tracking=True,
    )

    pilot = await session.get(User, int(errand.pilot_id)) if errand.pilot_id else None
    if pilot and pilot.email:
        subject = "ErrandBridge check-in: Are you delayed?"
        body = (
            f"Hi {pilot.first_name or 'there'},\n\n"
            "We noticed your movement has slowed or stopped. Please reply with a short reason for the delay.\n"
            f"Errand: {_errand_reference(errand)}\n"
            f"Title: {errand.title}\n"
            f"Tracking: {tracking_url}\n\n"
            "Reply with what happened so we can update the client and admin."
        )
        await asyncio.to_thread(
            send_email, to_email=pilot.email, subject=subject, body_text=body
        )


async def notify_admin_support_handoff(
    session,
    *,
    conversation,
    user: Optional[User],
    initial_message: Optional[str],
) -> None:
    recipients = _admin_recipients()
    if not recipients:
        return

    subject = "ErrandBridge support handoff requested"
    body = (
        "A customer has requested a human support specialist.\n\n"
        f"Conversation ID: {conversation.id}\n"
        f"Session ID: {conversation.session_id}\n"
        f"Status: {conversation.status}\n"
    )

    if user:
        name = (
            " ".join([part for part in [user.first_name, user.last_name] if part])
            or "Customer"
        )
        body += (
            f"Customer: {name}\n"
            f"Email: {user.email or '-'}\n"
            f"Phone: {user.phone or '-'}\n"
        )

    if initial_message:
        body += f"\nCustomer message: {initial_message}\n"

    body += "\nOpen the ErrandBridge admin dashboard to continue the conversation."

    for recipient in recipients:
        await asyncio.to_thread(
            send_email, to_email=recipient, subject=subject, body_text=body
        )


async def notify_customer_incident_update(
    session,
    *,
    errand: Errand,
    message: str,
) -> None:
    user = await session.get(User, int(errand.user_id))
    if not user or not user.email:
        return

    subject = f"Incident update: {_errand_reference(errand)}"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        "We have an update on your errand incident.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Status: {_status_label(errand.status)}\n"
        f"Update: {message}\n\n"
        f"Live tracking: {_tracking_link(errand)}\n\n"
        "Reply to this email if you have questions."
    )

    await asyncio.to_thread(
        send_email, to_email=user.email, subject=subject, body_text=body
    )


async def notify_pilot_document_review(
    session,
    *,
    pilot: User,
    document_type: str,
    status: str,
    note: Optional[str] = None,
) -> None:
    if not pilot or not pilot.email:
        return

    normalized_status = (status or "").strip().lower()
    readable_status = "Approved" if normalized_status == "approved" else "Rejected"
    subject = f"ErrandBridge document review: {readable_status}"
    portal_url = f"{pilot_web_base()}/pilot"

    body = (
        f"Hi {pilot.first_name or 'there'},\n\n"
        "Your verification document has now been reviewed by the ErrandBridge team.\n\n"
        f"Document type: {document_type or 'Document'}\n"
        f"Decision: {readable_status}\n"
    )

    if note:
        body += f"Admin note: {note}\n"

    body += (
        "\nYou can view your document status in your Pilot profile settings."
        f"\nPortal: {portal_url}\n\n"
        "Reply to this email if you need help."
    )

    await asyncio.to_thread(
        send_email, to_email=pilot.email, subject=subject, body_text=body
    )

    if pilot.phone:
        sms_body = f"ErrandBridge: Your {document_type or 'document'} was {readable_status.lower()}."
        if note:
            sms_body += f" Note: {note}"
        await asyncio.to_thread(send_sms, to_number=pilot.phone, body_text=sms_body)
