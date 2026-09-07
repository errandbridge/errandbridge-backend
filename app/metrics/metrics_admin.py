from __future__ import annotations

from prometheus_client import Counter, Gauge

VISITS_TOTAL = Counter(
    "errandbridge_visits_total",
    "Total visits recorded by the analytics endpoint.",
    ["page", "source", "country"],
)

ADMIN_TOTAL_USERS = Gauge(
    "errandbridge_admin_total_users",
    "Total users in the system.",
)

ADMIN_VERIFIED_USERS = Gauge(
    "errandbridge_admin_verified_users",
    "Verified users in the system.",
)

ADMIN_TOTAL_ERRANDS = Gauge(
    "errandbridge_admin_total_errands",
    "Total errands in the system.",
)

ADMIN_PENDING_ISSUES = Gauge(
    "errandbridge_admin_pending_issues",
    "Open issues awaiting review.",
)

VISITS_LAST_24H = Gauge(
    "errandbridge_visits_last_24h",
    "Visits recorded in the last 24 hours.",
)

ERRANDS_BY_STATUS = Gauge(
    "errandbridge_errands_by_status",
    "Errand counts by status.",
    ["status"],
)


def record_visit(page: str | None, source: str | None, country: str | None) -> None:
    VISITS_TOTAL.labels(
        page=(page or "unknown")[:64],
        source=(source or "unknown")[:32],
        country=(country or "unknown")[:32],
    ).inc()


def update_admin_metrics(payload: dict) -> None:
    ADMIN_TOTAL_USERS.set(int(payload.get("total_users") or 0))
    ADMIN_VERIFIED_USERS.set(int(payload.get("verified_users") or 0))
    ADMIN_TOTAL_ERRANDS.set(int(payload.get("total_errands") or 0))
    ADMIN_PENDING_ISSUES.set(int(payload.get("pending_issues") or 0))
    VISITS_LAST_24H.set(int(payload.get("visits_last_24h") or 0))

    funnel = payload.get("errand_funnel") or {}
    for status, value in funnel.items():
        ERRANDS_BY_STATUS.labels(status=str(status)).set(int(value or 0))
