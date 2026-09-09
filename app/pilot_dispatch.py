from __future__ import annotations
import uuid

from datetime import datetime, timezone
from typing import Any, Optional

PILOT_AVAILABILITY_ONLINE = "online"
PILOT_AVAILABILITY_OFFLINE = "offline"
ADMIN_DISPATCH_ENABLED = "enabled"
ADMIN_DISPATCH_DISABLED = "disabled"
ADMIN_DISPATCH_PERMANENTLY_DISABLED = "permanently_disabled"

VALID_PILOT_AVAILABILITIES = {
    PILOT_AVAILABILITY_ONLINE,
    PILOT_AVAILABILITY_OFFLINE,
}

VALID_ADMIN_DISPATCH_STATUSES = {
    ADMIN_DISPATCH_ENABLED,
    ADMIN_DISPATCH_DISABLED,
    ADMIN_DISPATCH_PERMANENTLY_DISABLED,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_pilot_availability(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_PILOT_AVAILABILITIES:
        return normalized
    return PILOT_AVAILABILITY_OFFLINE


def normalize_admin_dispatch_status(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if normalized in {"permanent_block", "permanentblocked", "blocked"}:
        normalized = ADMIN_DISPATCH_PERMANENTLY_DISABLED
    if normalized in VALID_ADMIN_DISPATCH_STATUSES:
        return normalized
    return ADMIN_DISPATCH_ENABLED


def _dispatch_block_reason(
    admin_dispatch_status: str, availability: str
) -> Optional[str]:
    if admin_dispatch_status == ADMIN_DISPATCH_PERMANENTLY_DISABLED:
        return "Your pilot account has been permanently blocked from dispatch."
    if admin_dispatch_status == ADMIN_DISPATCH_DISABLED:
        return "Dispatch access is currently disabled by admin."
    if availability != PILOT_AVAILABILITY_ONLINE:
        return "Go online to accept new errands."
    return None


def serialize_pilot_dispatch_state(user: Any) -> dict[str, Any]:
    availability = normalize_pilot_availability(
        getattr(user, "pilot_availability", None)
    )
    admin_dispatch_status = normalize_admin_dispatch_status(
        getattr(user, "admin_dispatch_status", None),
    )
    block_reason = _dispatch_block_reason(admin_dispatch_status, availability)
    can_accept_jobs = block_reason is None
    return {
        "availability": availability,
        "admin_dispatch_status": admin_dispatch_status,
        "admin_dispatch_note": getattr(user, "admin_dispatch_note", None),
        "can_accept_jobs": can_accept_jobs,
        "dispatch_block_reason": block_reason,
        "pilot_status_changed_at": getattr(user, "pilot_status_changed_at", None),
        "pilot_status_changed_by": str(getattr(user, "pilot_status_changed_by", None)) if getattr(user, "pilot_status_changed_by", None) else None,
    }


def set_pilot_availability(
    user: Any,
    availability: str,
    *,
    actor_id: Optional[Any] = None,
) -> dict[str, Any]:
    normalized = normalize_pilot_availability(availability)
    user.pilot_availability = normalized
    user.pilot_status_changed_at = utcnow()
    if actor_id is not None:
        try:
            if isinstance(actor_id, str):
                actor_id = uuid.UUID(actor_id)
            user.pilot_status_changed_by = actor_id
        except Exception:
            user.pilot_status_changed_by = None
    return serialize_pilot_dispatch_state(user)


def set_admin_dispatch_status(
    user: Any,
    admin_dispatch_status: str,
    *,
    actor_id: Optional[Any] = None,
    note: Optional[str] = None,
    force_offline: bool = True,
) -> dict[str, Any]:
    normalized = normalize_admin_dispatch_status(admin_dispatch_status)
    user.admin_dispatch_status = normalized
    user.admin_dispatch_note = (note or "").strip() or None
    if force_offline and normalized != ADMIN_DISPATCH_ENABLED:
        user.pilot_availability = PILOT_AVAILABILITY_OFFLINE
    user.pilot_status_changed_at = utcnow()
    if actor_id is not None:
        try:
            if isinstance(actor_id, str):
                actor_id = uuid.UUID(actor_id)
            user.pilot_status_changed_by = actor_id
        except Exception:
            user.pilot_status_changed_by = None
    return serialize_pilot_dispatch_state(user)


def ensure_pilot_can_accept_jobs(user: Any) -> dict[str, Any]:
    state = serialize_pilot_dispatch_state(user)
    if not state["can_accept_jobs"]:
        raise PermissionError(
            state["dispatch_block_reason"] or "Pilot cannot accept jobs right now."
        )
    return state
