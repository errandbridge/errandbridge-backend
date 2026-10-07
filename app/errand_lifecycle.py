from __future__ import annotations


STATUS_ALIASES = {
    "created": "submitted",
    "new": "submitted",
    "open": "submitted",
    "pending": "submitted",
    "in progress": "in_progress",
    "picked up": "picked_up",
}

PILOT_TRANSITIONS = {
    "accepted": {"in_progress"},
    "in_progress": {"arrived_at_pickup"},
    "pickup_started": {"arrived_at_pickup"},
    "arrived_at_pickup": {"picked_up"},
    "picked_up": {"arrived_at_dropoff"},
    "dropoff_started": {"arrived_at_dropoff"},
    "arrived_at_dropoff": {"proof_submitted"},
    "proof_submitted": {"delivered"},
}

CUSTOMER_TRANSITIONS = {
    "delivered": {"completed", "disputed"},
    "proof_submitted": {"disputed"},
}

ADMIN_TRANSITIONS = {
    "delivered": {"completed"},
    "disputed": {"completed"},
}


def normalize_errand_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    normalized = "_".join(normalized.split())
    return STATUS_ALIASES.get(normalized, normalized)


def validate_errand_transition(
    *,
    actor: str,
    current_status: str | None,
    next_status: str | None,
) -> str:
    current = normalize_errand_status(current_status)
    requested = normalize_errand_status(next_status)

    if not requested:
        raise ValueError("A status is required")
    if current == requested:
        return requested

    transitions = {
        "pilot": PILOT_TRANSITIONS,
        "customer": CUSTOMER_TRANSITIONS,
        "admin": ADMIN_TRANSITIONS,
    }.get(actor)
    if transitions is None:
        raise ValueError("Unknown errand workflow actor")

    allowed = transitions.get(current, set())
    if requested not in allowed:
        expected = ", ".join(sorted(allowed)) or "no further action"
        raise ValueError(
            f"Cannot change errand from {current or 'unknown'} to {requested}. "
            f"The next allowed {actor} action is: {expected}."
        )

    return requested