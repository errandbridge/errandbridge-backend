from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from database import engine
from models import PilotDispatchPolicy

DEFAULT_SHOW_ALL_JOBS_TO_PILOTS = False
DEFAULT_OPEN_POOL_RADIUS_MILES = 5
ALLOWED_OPEN_POOL_RADIUS_MILES = (5, 10, 15, 20)
PILOT_DISPATCH_POLICY_SINGLETON_ID = 1
_pilot_dispatch_policy_storage_ready = False


def normalize_show_all_jobs_to_pilots(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_open_pool_radius_miles(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = DEFAULT_OPEN_POOL_RADIUS_MILES
    if normalized not in ALLOWED_OPEN_POOL_RADIUS_MILES:
        return DEFAULT_OPEN_POOL_RADIUS_MILES
    return normalized


def default_pilot_dispatch_policy_state() -> dict[str, Any]:
    return {
        "show_all_jobs_to_pilots": DEFAULT_SHOW_ALL_JOBS_TO_PILOTS,
        "open_pool_radius_miles": DEFAULT_OPEN_POOL_RADIUS_MILES,
        "allowed_open_pool_radius_miles": list(ALLOWED_OPEN_POOL_RADIUS_MILES),
        "updated_at": None,
        "updated_by_user_id": None,
    }


def serialize_pilot_dispatch_policy(policy: Any | None) -> dict[str, Any]:
    if not policy:
        return default_pilot_dispatch_policy_state()
    return {
        "show_all_jobs_to_pilots": normalize_show_all_jobs_to_pilots(
            getattr(policy, "show_all_jobs_to_pilots", DEFAULT_SHOW_ALL_JOBS_TO_PILOTS)
        ),
        "open_pool_radius_miles": normalize_open_pool_radius_miles(
            getattr(policy, "open_pool_radius_miles", DEFAULT_OPEN_POOL_RADIUS_MILES)
        ),
        "allowed_open_pool_radius_miles": list(ALLOWED_OPEN_POOL_RADIUS_MILES),
        "updated_at": getattr(policy, "updated_at", None),
        "updated_by_user_id": getattr(policy, "updated_by_user_id", None),
    }


async def _ensure_pilot_dispatch_policy_storage() -> None:
    global _pilot_dispatch_policy_storage_ready
    if _pilot_dispatch_policy_storage_ready:
        return
    async with engine.begin() as conn:
        await conn.run_sync(PilotDispatchPolicy.__table__.create, checkfirst=True)
    _pilot_dispatch_policy_storage_ready = True


async def _load_pilot_dispatch_policy(db: AsyncSession) -> PilotDispatchPolicy | None:
    return await db.get(PilotDispatchPolicy, PILOT_DISPATCH_POLICY_SINGLETON_ID)


async def get_or_create_pilot_dispatch_policy(db: AsyncSession) -> PilotDispatchPolicy:
    await _ensure_pilot_dispatch_policy_storage()
    policy = await _load_pilot_dispatch_policy(db)

    if policy:
        return policy

    policy = PilotDispatchPolicy(
        id=PILOT_DISPATCH_POLICY_SINGLETON_ID,
        show_all_jobs_to_pilots=DEFAULT_SHOW_ALL_JOBS_TO_PILOTS,
        open_pool_radius_miles=DEFAULT_OPEN_POOL_RADIUS_MILES,
    )
    db.add(policy)
    await db.flush()
    return policy


async def get_pilot_dispatch_policy_state(db: AsyncSession) -> dict[str, Any]:
    try:
        await _ensure_pilot_dispatch_policy_storage()
        policy = await _load_pilot_dispatch_policy(db)
    except Exception:
        return default_pilot_dispatch_policy_state()
    return serialize_pilot_dispatch_policy(policy)


async def update_pilot_dispatch_policy(
    db: AsyncSession,
    *,
    show_all_jobs_to_pilots: Any | None = None,
    open_pool_radius_miles: Any | None = None,
    actor_id: int | None = None,
) -> dict[str, Any]:
    policy = await get_or_create_pilot_dispatch_policy(db)

    if show_all_jobs_to_pilots is not None:
        policy.show_all_jobs_to_pilots = normalize_show_all_jobs_to_pilots(
            show_all_jobs_to_pilots
        )
    if open_pool_radius_miles is not None:
        policy.open_pool_radius_miles = normalize_open_pool_radius_miles(
            open_pool_radius_miles
        )
    if actor_id is not None:
        policy.updated_by_user_id = int(actor_id)
    policy.updated_at = datetime.now(timezone.utc)

    await db.flush()
    return serialize_pilot_dispatch_policy(policy)
