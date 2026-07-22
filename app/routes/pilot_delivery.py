"""
Pilot Delivery Control API
Handles pilot actions: start delivery, complete delivery, pause tracking
Integrates with tracking system
"""

from fastapi import APIRouter, Depends, HTTPException, status, Body, Header, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from datetime import datetime, timezone
from typing import Optional
import asyncio
import re
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from auth import decode_access_token
from models import (
    Errand,
    ErrandEvent,
    User,
    ErrandAttachment,
    IncidentReport,
    IncidentMessage,
    PilotDocument,
    PilotLocation,
)
from database import get_db, AsyncSessionLocal
from notification_utils import (
    notify_customer_status,
    notify_pilot_status,
    notify_tracking_started,
    notify_admin_status,
)
from app.pilot_dispatch import ensure_pilot_can_accept_jobs, serialize_pilot_dispatch_state
from app.pilot_dispatch_policy import get_pilot_dispatch_policy_state
import hashlib
import hmac
from storage import build_stored_filename, put_bytes
import json
 
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pilots", tags=["pilots"])

MAX_ACCEPT_DISTANCE_MILES = 5
MAX_ACCEPT_DISTANCE_KM = MAX_ACCEPT_DISTANCE_MILES * 1.60934


def _normalize_status(value: Optional[str]) -> str:
    """Normalize status values for defensive comparisons.

    We have seen variants like "in progress" vs "in_progress".
    """
    if not value:
        return ""
    key = str(value).strip().lower()
    # Convert whitespace/hyphens to underscores and collapse repeats.
    key = "_".join(key.replace("-", " ").split())
    return key


def _normalize_location_text(value: Optional[str]) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower())
    return " ".join(normalized.split())


def _normalize_support_type(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"standard_assistance", "standard", "foot"}:
        return "standard_assistance"
    if raw in {"bike_support", "bike", "bicycle", "motorbike", "motorcycle", "scooter"}:
        return "bike_support"
    if raw in {"car_support", "car", "vehicle"}:
        return "car_support"
    return "flexible"


def _normalize_vehicle_type(value: Optional[str]) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _pilot_has_bike(pilot: User) -> bool:
    vehicle_type = _normalize_vehicle_type(getattr(pilot, "vehicle_type", None))
    return bool(
        getattr(pilot, "hasBike", False)
        or getattr(pilot, "has_bike", False)
        or vehicle_type in {"bike", "bike_support", "bicycle", "motorbike", "motorcycle", "scooter"}
    )


def _pilot_has_car(pilot: User) -> bool:
    vehicle_type = _normalize_vehicle_type(getattr(pilot, "vehicle_type", None))
    return bool(
        getattr(pilot, "hasCar", False)
        or getattr(pilot, "has_car", False)
        or vehicle_type in {"car", "saloon", "sedan", "suv", "van", "truck"}
    )


def _pilot_cross_city_available(pilot: User) -> bool:
    return bool(
        getattr(pilot, "crossCityAvailable", False)
        or getattr(pilot, "cross_city_available", False)
    )


def _pilot_service_radius_km(pilot: User) -> Optional[float]:
    raw = (
        getattr(pilot, "serviceRadius", None)
        or getattr(pilot, "service_radius_km", None)
        or getattr(pilot, "service_radius", None)
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _pilot_service_area_text(pilot: User) -> str:
    city = _normalize_location_text(getattr(pilot, "city", None))
    if city:
        return city
    return _normalize_location_text(
        getattr(pilot, "state_province", None) or getattr(pilot, "state", None)
    )


def _policy_radius_miles(policy_state: Optional[dict]) -> int:
    if not policy_state:
        return MAX_ACCEPT_DISTANCE_MILES
    try:
        radius_miles = int(policy_state.get("open_pool_radius_miles") or MAX_ACCEPT_DISTANCE_MILES)
    except (TypeError, ValueError):
        radius_miles = MAX_ACCEPT_DISTANCE_MILES
    return radius_miles


def _policy_radius_km(policy_state: Optional[dict]) -> float:
    return _policy_radius_miles(policy_state) * 1.60934


def _open_pool_visibility_check(
    errand: Errand,
    pilot: User,
    *,
    policy_state: Optional[dict] = None,
) -> tuple[bool, str | None]:
    support_type = _normalize_support_type(getattr(errand, "support_type", None))
    if support_type == "bike_support" and not _pilot_has_bike(pilot):
        return False, "bike_required"
    if support_type == "car_support" and not _pilot_has_car(pilot):
        return False, "car_required"

    distance_km = getattr(errand, "distance_km", None)
    if distance_km is None:
        return False, "missing_distance"

    if float(distance_km) > 30 and not _pilot_cross_city_available(pilot):
        return False, "cross_city_required"

    pilot_service_radius_km = _pilot_service_radius_km(pilot)
    if pilot_service_radius_km is not None and float(distance_km) > pilot_service_radius_km:
        return False, "outside_service_radius"

    service_area = _pilot_service_area_text(pilot)
    if not service_area:
        return False, "missing_service_area"

    location_haystack = _normalize_location_text(
        " ".join(
            filter(
                None,
                [
                    getattr(errand, "pickup_location", None),
                    getattr(errand, "dropoff_location", None),
                ],
            )
        )
    )
    if not location_haystack or service_area not in location_haystack:
        return False, "outside_service_area"

    if distance_km > _policy_radius_km(policy_state):
        return False, "outside_radius"

    return True, None


def _open_pool_visibility_error_detail(
    reason: str | None,
    *,
    policy_state: Optional[dict] = None,
) -> str:
    if reason == "bike_required":
        return "Bike support requires a pilot with bike access"
    if reason == "car_required":
        return "Car support requires a pilot with car access"
    if reason == "cross_city_required":
        return "This errand requires a cross-city enabled pilot"
    if reason == "missing_service_area":
        return "Complete your pilot address before accessing open-pool errands"
    if reason == "outside_service_area":
        return "Errand is outside your service area"
    if reason == "missing_distance":
        return "Errand distance is unavailable"
    if reason == "outside_service_radius":
        return "Errand is outside your configured service radius"
    if reason == "outside_radius":
        return f"Errand is outside the {_policy_radius_miles(policy_state)} mile radius"
    return "Errand does not match your pilot profile"


async def _archive_route_snapshot(db: AsyncSession, errand: Errand, actor_id: Optional[int] = None) -> Optional[dict]:
    locations = await db.scalars(
        select(PilotLocation)
        .where(PilotLocation.errand_id == errand.id)
        .order_by(PilotLocation.created_at)
    )
    locations = list(locations)
    if not locations:
        return None

    existing_archive = await db.scalar(
        select(ErrandEvent)
        .where(ErrandEvent.errand_id == errand.id)
        .where(ErrandEvent.event_type == "route_archive")
        .order_by(ErrandEvent.created_at.desc())
        .limit(1)
    )
    if existing_archive and existing_archive.note:
        try:
            return json.loads(existing_archive.note)
        except Exception:
            pass

    def _serialize_location(loc: PilotLocation) -> dict:
        return {
            "id": loc.id,
            "errand_id": loc.errand_id,
            "pilot_id": loc.pilot_id,
            "latitude": float(loc.latitude),
            "longitude": float(loc.longitude),
            "accuracy": loc.accuracy,
            "speed": loc.speed,
            "heading": loc.heading,
            "altitude": loc.altitude,
            "created_at": loc.created_at.isoformat() if loc.created_at else None,
        }

    def _calc_distance_km(points: list[PilotLocation]) -> float:
        from math import radians, cos, sin, asin, sqrt
        if len(points) < 2:
            return 0.0
        total_distance = 0.0
        for i in range(len(points) - 1):
            lat1, lon1 = radians(float(points[i].latitude)), radians(float(points[i].longitude))
            lat2, lon2 = radians(float(points[i + 1].latitude)), radians(float(points[i + 1].longitude))
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            c = 2 * asin(sqrt(a))
            total_distance += 6371 * c
        return round(total_distance, 2)

    archive_payload = {
        "errand_id": errand.id,
        "pilot_id": errand.pilot_id,
        "status": errand.status,
        "started_at": errand.started_at.isoformat() if errand.started_at else None,
        "completed_at": errand.completed_at.isoformat() if errand.completed_at else None,
        "total_points": len(locations),
        "distance_km": _calc_distance_km(locations),
        "locations": [_serialize_location(loc) for loc in locations],
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }

    stored_filename = build_stored_filename(f"route-archive-{errand.id}.json")
    driver, location = put_bytes(
        stored_filename,
        json.dumps(archive_payload).encode("utf-8"),
        content_type="application/json",
    )

    archive_record = {
        "driver": driver,
        "location": location,
        "stored_filename": stored_filename,
        "total_points": archive_payload["total_points"],
        "distance_km": archive_payload["distance_km"],
        "archived_at": archive_payload["archived_at"],
    }

    db.add(
        ErrandEvent(
            errand_id=errand.id,
            event_type="route_archive",
            old_status=errand.status,
            new_status=errand.status,
            note=json.dumps(archive_record),
            user_id=actor_id,
        )
    )
    await db.commit()

    return archive_record


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def _get_current_user(
    authorization: Optional[str],
    db: AsyncSession,
):
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not getattr(user, "is_pilot", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Pilot access required")

    return user


@router.get("/available-jobs", response_model=dict)
async def list_available_jobs(
    status_filter: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List errands that are open for pilots to accept."""

    pilot = await _get_current_user(authorization, db)
    dispatch_state = serialize_pilot_dispatch_state(pilot)
    dispatch_policy = await get_pilot_dispatch_policy_state(db)

    allowed_statuses = ["assigned", "approved", "submitted", "pending"]
    if status_filter:
        status_value = status_filter.strip().lower()
        if status_value in allowed_statuses:
            allowed_statuses = [status_value]

    result = await db.execute(
        select(Errand, User)
        .join(User, User.id == Errand.user_id)
        .where(Errand.status.in_(allowed_statuses))
        .where(or_(Errand.pilot_id.is_(None), Errand.pilot_id == pilot.id))
        .order_by(Errand.created_at.desc())
    )

    errands = []
    for errand, user in result.all():
        matches_dispatch_policy = True
        acceptance_block_reason = None
        if errand.pilot_id != pilot.id:
            is_visible, reason = _open_pool_visibility_check(
                errand,
                pilot,
                policy_state=dispatch_policy,
            )
            matches_dispatch_policy = is_visible
            if not is_visible:
                if not dispatch_policy.get("show_all_jobs_to_pilots"):
                    continue
                acceptance_block_reason = _open_pool_visibility_error_detail(
                    reason,
                    policy_state=dispatch_policy,
                )

        errands.append({
            "id": errand.id,
            "reference_number": errand.reference_number,
            "title": errand.title,
            "description": errand.description,
            "status": errand.status,
            "pilot_id": errand.pilot_id,
            "pilotId": errand.pilot_id,
            "pickup_location": errand.pickup_location,
            "dropoff_location": errand.dropoff_location,
            "sensitivity": errand.sensitivity,
            "created_at": errand.created_at.isoformat() if errand.created_at else None,
            "note": errand.note,
            # Pilots should not receive direct customer contact details.
            "customer_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or "Customer",
            "amount": getattr(errand, "amount", 0),
            "payment_amount_ngn_major": getattr(errand, "payment_amount_ngn_major", None),
            "paymentAmountNgnMajor": getattr(errand, "payment_amount_ngn_major", None),
            "distance_km": getattr(errand, "distance_km", None),
            "matches_dispatch_policy": matches_dispatch_policy,
            "acceptance_block_reason": acceptance_block_reason,
            "customer_rating": getattr(errand, "customer_rating", None),
            "pickup_time_slot_start": errand.pickup_time_slot_start.isoformat() if errand.pickup_time_slot_start else None,
            "pickup_time_slot_end": errand.pickup_time_slot_end.isoformat() if errand.pickup_time_slot_end else None,
            "pickup_time_slot_date": errand.pickup_time_slot_date,
        })

    return {
        "errands": errands,
        "total": len(errands),
        "dispatch_state": dispatch_state,
        "dispatch_policy": dispatch_policy,
    }


@router.get("/jobs", response_model=dict)
async def list_pilot_jobs(
    status: Optional[str] = Query(default=None),
    status_filter: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List errands assigned to the current pilot."""

    pilot = await _get_current_user(authorization, db)

    status_value = (status or status_filter or "active").strip().lower()
    active_statuses = ["assigned", "accepted", "picked_up", "delivered", "in_progress"]
    completed_statuses = ["completed"]

    statuses = None
    if status_value == "active":
        statuses = active_statuses
    elif status_value == "completed":
        statuses = completed_statuses
    elif status_value == "all":
        statuses = None
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status filter. Use active, completed, or all.",
        )

    query = (
        select(Errand, User)
        .join(User, User.id == Errand.user_id)
        .where(Errand.pilot_id == pilot.id)
    )

    if statuses:
        query = query.where(Errand.status.in_(statuses))

    result = await db.execute(query.order_by(Errand.updated_at.desc()))

    errands = []
    for errand, user in result.all():
        errands.append({
            "id": errand.id,
            "reference_number": errand.reference_number,
            "title": errand.title,
            "description": errand.description,
            "status": errand.status,
            "started_at": errand.started_at.isoformat() if errand.started_at else None,
            "started": bool(errand.started_at),
            "pickup_location": errand.pickup_location,
            "dropoff_location": errand.dropoff_location,
            "sensitivity": errand.sensitivity,
            "created_at": errand.created_at.isoformat() if errand.created_at else None,
            "completed_at": errand.completed_at.isoformat() if errand.completed_at else None,
            "note": errand.note,
            # Pilots should not receive direct customer contact details.
            "customer_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or "Customer",
            "amount": getattr(errand, "amount", 0),
            "payment_amount_ngn_major": getattr(errand, "payment_amount_ngn_major", None),
            "paymentAmountNgnMajor": getattr(errand, "payment_amount_ngn_major", None),
            "distance_km": getattr(errand, "distance_km", None),
            "customer_rating": getattr(errand, "customer_rating", None),
            "pickup_time_slot_start": errand.pickup_time_slot_start.isoformat() if errand.pickup_time_slot_start else None,
            "pickup_time_slot_end": errand.pickup_time_slot_end.isoformat() if errand.pickup_time_slot_end else None,
            "pickup_time_slot_date": errand.pickup_time_slot_date,
        })

    return {"errands": errands}


@router.post("/accept-job", response_model=dict)
async def accept_job(
    errand_id: int = Body(..., embed=True),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Pilot accepts a job and claims the errand."""

    pilot = await _get_current_user(authorization, db)
    try:
        ensure_pilot_can_accept_jobs(pilot)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    result = await db.execute(select(Errand).where(Errand.id == errand_id))
    errand = result.scalar_one_or_none()
    if not errand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Errand not found")

    was_unassigned = errand.pilot_id is None

    # Prevent pilots from accepting errands that are assigned to another pilot.
    # Unassigned errands are claimable (see /available-jobs behavior).
    if errand.pilot_id is not None and int(errand.pilot_id) != int(pilot.id):
        try:
            await notify_admin_status(
                db,
                errand=errand,
                old_status=errand.status,
                new_status=errand.status,
                trigger="pilot-accept-not-assigned",
                message=f"Pilot {pilot.email} attempted to accept an errand assigned to another pilot (pilot_id={errand.pilot_id}).",
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Errand is assigned to another pilot",
        )

    if errand.pilot_id is not None and int(errand.pilot_id) == int(pilot.id):
        normalized_status = _normalize_status(errand.status)
        if normalized_status in ["accepted", "picked_up", "in_progress", "delivered"]:
            customer = await db.get(User, errand.user_id)
            return {
                "ok": True,
                "already_active": True,
                "errand": {
                    "id": errand.id,
                    "status": errand.status,
                    "title": errand.title,
                    "description": errand.description,
                    "note": errand.note,
                    "pickup_location": errand.pickup_location,
                    "dropoff_location": errand.dropoff_location,
                    "amount": getattr(errand, "amount", 0),
                    "payment_amount_ngn_major": getattr(errand, "payment_amount_ngn_major", None),
                    "paymentAmountNgnMajor": getattr(errand, "payment_amount_ngn_major", None),
                    "distance_km": getattr(errand, "distance_km", None),
                    "customer_name": (
                        f"{customer.first_name or ''} {customer.last_name or ''}".strip()
                        if customer
                        else "Customer"
                    ),
                },
            }

    allowed_accept_statuses = ["assigned", "approved", "submitted", "pending"]
    if errand.status not in allowed_accept_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot accept errand with status {errand.status}",
        )

    active_conflict = await db.scalar(
        select(Errand)
        .where(Errand.pilot_id == pilot.id)
        .where(Errand.id != errand.id)
        .where(Errand.status.in_(["accepted", "picked_up", "in_progress", "delivered"]))
        .limit(1)
    )
    if active_conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active errand. Complete it before accepting a new one.",
        )

    dispatch_policy = await get_pilot_dispatch_policy_state(db)
    if was_unassigned:
        is_visible, reason = _open_pool_visibility_check(
            errand,
            pilot,
            policy_state=dispatch_policy,
        )
        if not is_visible:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_open_pool_visibility_error_detail(
                    reason,
                    policy_state=dispatch_policy,
                ),
            )

    previous_status = errand.status
    errand.pilot_id = pilot.id
    errand.status = "accepted"
    if not errand.assigned_at:
        errand.assigned_at = datetime.now(timezone.utc)

    event = ErrandEvent(
        errand_id=errand.id,
        event_type="pilot_accept",
        old_status=previous_status,
        new_status=errand.status,
        note="Pilot claimed the errand" if was_unassigned else "Pilot accepted the assigned errand",
        user_id=pilot.id,
    )
    db.add(event)

    await db.commit()
    await db.refresh(errand)

    customer = await db.get(User, errand.user_id)

    try:
        await notify_customer_status(
            db,
            errand=errand,
            old_status=previous_status,
            new_status=errand.status,
            trigger="pilot-accept",
        )
        await notify_admin_status(
            db,
            errand=errand,
            old_status=previous_status,
            new_status=errand.status,
            trigger="pilot-accept",
            message=(
                "Pilot claimed an open errand." if was_unassigned else "Pilot accepted the assigned errand."
            ),
        )
        await notify_pilot_status(
            db,
            errand=errand,
            new_status="accepted",
            trigger="pilot-accept",
            pilot_user=pilot,
        )
    except Exception as e:
        logger.warning(f"[notify] pilot accept email failed: {e}")

    return {
        "ok": True,
        "errand": {
            "id": errand.id,
            "status": errand.status,
            "title": errand.title,
            "description": errand.description,
            "note": errand.note,
            "pickup_location": errand.pickup_location,
            "dropoff_location": errand.dropoff_location,
            "amount": getattr(errand, "amount", 0),
            "payment_amount_ngn_major": getattr(errand, "payment_amount_ngn_major", None),
            "paymentAmountNgnMajor": getattr(errand, "payment_amount_ngn_major", None),
            "distance_km": getattr(errand, "distance_km", None),
            # Pilots should not receive direct customer contact details.
            "customer_name": (
                f"{customer.first_name or ''} {customer.last_name or ''}".strip()
                if customer
                else "Customer"
            ),
        },
    }


@router.post("/assign", response_model=dict)
async def assign_job_legacy(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Legacy alias for accept-job (kept for backward compatibility)."""
    errand_id = payload.get("errand_id") or payload.get("id")
    if not errand_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="errand_id is required")
    return await accept_job(errand_id=int(errand_id), authorization=authorization, db=db)


@router.get("/availability-history", response_model=dict)
async def list_availability_history(
    limit: int = 20,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Return recent availability confirmation events for the pilot."""

    pilot = await _get_current_user(authorization, db)

    limit_value = max(1, min(int(limit), 50))
    result = await db.execute(
        select(ErrandEvent, Errand)
        .join(Errand, Errand.id == ErrandEvent.errand_id)
        .where(ErrandEvent.user_id == pilot.id)
        .where(ErrandEvent.event_type.in_([
            "pilot_availability_request",
            "pilot_availability_yes",
            "pilot_availability_no",
            "pilot_reminder",
        ]))
        .order_by(ErrandEvent.created_at.desc())
        .limit(limit_value)
    )

    history = []
    for event, errand in result.all():
        history.append({
            "id": event.id,
            "event_type": event.event_type,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "note": event.note,
            "errand_id": errand.id,
            "errand_reference": errand.reference_number,
            "errand_title": errand.title,
            "pickup_time_slot_start": errand.pickup_time_slot_start.isoformat() if errand.pickup_time_slot_start else None,
        })

    return {"events": history}


@router.post("/decline-job", response_model=dict)
async def decline_job(
    errand_id: int = Body(..., embed=True),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Pilot declines an assigned job before starting delivery."""

    pilot = await _get_current_user(authorization, db)

    result = await db.execute(select(Errand).where(Errand.id == errand_id))
    errand = result.scalar_one_or_none()
    if not errand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Errand not found")

    if not errand.pilot_id or int(errand.pilot_id) != int(pilot.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not assigned to this errand")

    status_key = _normalize_status(getattr(errand, "status", None))
    started_statuses = {"picked_up", "in_progress", "delivered", "completed"}
    if getattr(errand, "started_at", None) is not None or status_key in started_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot decline once the errand has started",
        )

    # Only allow declines in pre-start states.
    # NOTE: Do not allow declining once in progress; that is treated as "started".
    if status_key not in {"assigned", "accepted", "pending", "submitted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot decline errand with status {getattr(errand, 'status', None)}",
        )

    previous_status = errand.status
    errand.pilot_id = None
    errand.status = "submitted"
    errand.started_at = None
    errand.tracking_paused = False

    event = ErrandEvent(
        errand_id=errand.id,
        event_type="pilot_decline",
        old_status=previous_status,
        new_status=errand.status,
        note="Pilot declined the errand",
        user_id=pilot.id,
    )
    db.add(event)

    await db.commit()
    await db.refresh(errand)

    try:
        await notify_admin_status(
            db,
            errand=errand,
            old_status=previous_status,
            new_status=errand.status,
            trigger="pilot-decline",
            message="Pilot declined the assignment; job released back to the queue.",
        )
    except Exception:
        pass

    return {
        "ok": True,
        "errand": {
            "id": errand.id,
            "status": errand.status,
            "title": errand.title,
            "pickup_location": errand.pickup_location,
            "dropoff_location": errand.dropoff_location,
        },
    }


def _availability_secret() -> str:
    return os.getenv("PILOT_AVAILABILITY_SECRET") or os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")


def _availability_token(errand_id: int, pilot_id: int, expires_at: int) -> str:
    msg = f"{errand_id}:{pilot_id}:{expires_at}".encode("utf-8")
    return hmac.new(_availability_secret().encode("utf-8"), msg, hashlib.sha256).hexdigest()


@router.get("/availability-response", response_model=dict)
async def availability_response(
    errand_id: int,
    response: str,
    pilot_id: Optional[int] = None,
    expires: Optional[int] = None,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Pilot responds to availability check (yes/no)."""

    pilot = None
    if authorization:
        pilot = await _get_current_user(authorization, db)
    else:
        if pilot_id is None or expires is None or token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
        if expires < int(datetime.now(timezone.utc).timestamp()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Availability link expired")
        expected = _availability_token(errand_id, pilot_id, expires)
        if not hmac.compare_digest(expected, token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        pilot = await db.get(User, pilot_id)
        if not pilot or not getattr(pilot, "is_pilot", False):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Pilot access required")

    errand = await db.get(Errand, errand_id)
    if not errand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Errand not found")

    if not errand.pilot_id or int(errand.pilot_id) != int(pilot.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not assigned to this errand")

    response_value = response.strip().lower()
    if response_value not in {"yes", "no"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Response must be yes or no")

    previous_status = errand.status
    if response_value == "yes":
        db.add(
            ErrandEvent(
                errand_id=errand.id,
                event_type="pilot_availability_yes",
                old_status=previous_status,
                new_status=errand.status,
                note="Pilot confirmed availability",
                user_id=pilot.id,
            )
        )
        await db.commit()
        return {"ok": True, "status": errand.status, "response": "yes"}

    errand.pilot_id = None
    errand.status = "submitted"
    errand.started_at = None
    errand.tracking_paused = False

    db.add(
        ErrandEvent(
            errand_id=errand.id,
            event_type="pilot_availability_no",
            old_status=previous_status,
            new_status=errand.status,
            note="Pilot unavailable; assignment released",
            user_id=pilot.id,
        )
    )
    await db.commit()

    try:
        await notify_admin_status(
            db,
            errand=errand,
            old_status=previous_status,
            new_status=errand.status,
            trigger="pilot-availability-no",
            message="Pilot marked unavailable; errand released to open queue.",
        )
    except Exception:
        pass

    return {"ok": True, "status": errand.status, "response": "no"}


@router.post("/errands/{errand_id}/attachments", response_model=dict)
async def upload_pilot_attachment(
    errand_id: int,
    authorization: Optional[str] = Header(default=None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Pilot uploads proof for an assigned errand.

    Auth: assigned pilot only. Stored as pending review for admin.
    """

    pilot = await _get_current_user(authorization, db)

    errand = await db.get(Errand, errand_id)
    if not errand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Errand not found")

    if not errand.pilot_id or int(errand.pilot_id) != int(pilot.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not assigned to this errand")

    if not file or not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing filename")

    content = await file.read()
    size_bytes = len(content)
    if size_bytes == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if size_bytes > 10 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large (max 10MB)")

    stored_filename = build_stored_filename(file.filename)
    put_bytes(
        stored_filename=stored_filename,
        content=content,
        content_type=file.content_type,
    )

    attachment = ErrandAttachment(
        errand_id=errand_id,
        original_filename=file.filename,
        stored_filename=stored_filename,
        content_type=file.content_type,
        size_bytes=size_bytes,
        label="pilot-proof",
        review_status="pending",
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    return {
        "id": attachment.id,
        "errandId": attachment.errand_id,
        "filename": attachment.original_filename,
        "contentType": attachment.content_type,
        "sizeBytes": attachment.size_bytes,
        "reviewStatus": attachment.review_status,
    }


@router.post("/documents", response_model=dict)
async def upload_pilot_document(
    document_type: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Pilot uploads verification documents for approval."""

    pilot = await _get_current_user(authorization, db)

    if not file or not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing filename")

    content = await file.read()
    size_bytes = len(content)
    if size_bytes == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if size_bytes > 10 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large (max 10MB)")

    stored_filename = build_stored_filename(file.filename)
    put_bytes(
        stored_filename=stored_filename,
        content=content,
        content_type=file.content_type,
    )

    document = PilotDocument(
        pilot_id=pilot.id,
        document_type=document_type or "id_document",
        original_filename=file.filename,
        stored_filename=stored_filename,
        content_type=file.content_type,
        size_bytes=size_bytes,
        status="pending",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    return {
        "id": document.id,
        "status": document.status,
        "document_type": document.document_type,
        "original_filename": document.original_filename,
        "size_bytes": document.size_bytes,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }


@router.get("/documents", response_model=dict)
async def list_pilot_documents(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List documents uploaded by the current pilot."""

    pilot = await _get_current_user(authorization, db)
    result = await db.execute(
        select(PilotDocument)
        .where(PilotDocument.pilot_id == pilot.id)
        .order_by(PilotDocument.created_at.desc())
    )
    docs = result.scalars().all()

    return {
        "documents": [
            {
                "id": doc.id,
                "document_type": doc.document_type,
                "status": doc.status,
                "original_filename": doc.original_filename,
                "size_bytes": doc.size_bytes,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "review_note": doc.review_note,
            }
            for doc in docs
        ]
    }
@router.post("/start-delivery", response_model=dict)
async def start_delivery(
    errand_id: int,
    note: Optional[str] = None,
    pilot_id: Optional[int] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Pilot starts a delivery
    - Updates errand status to 'in_progress'
    - Activates GPS tracking
    - Returns tracking endpoint info
    """
    try:
        pilot_user = await _get_current_user(authorization, db)

        # Verify errand exists
        query = select(Errand).filter(Errand.id == errand_id)
        result = await db.execute(query)
        errand = result.scalar_one_or_none()

        if not errand:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Errand not found"
            )

        if errand.pilot_id and int(errand.pilot_id) != int(pilot_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not assigned to this errand",
            )

        if errand.status == 'in_progress':
            return {
                "success": True,
                "already_started": True,
                "errand_id": errand_id,
                "status": errand.status,
                "tracking_enabled": not bool(getattr(errand, "tracking_paused", False)),
                "tracking_paused": bool(getattr(errand, "tracking_paused", False)),
                "tracking_url": f"/tracking/ws/{errand_id}",
                "message": "Delivery is already in progress.",
                "pickup_location": errand.pickup_location,
                "dropoff_location": errand.dropoff_location,
                "delivery_location": errand.dropoff_location,
                "customer_name": getattr(errand, "customer_name", "Unknown"),
                "amount": getattr(errand, "amount", 0),
            }

        if errand.status not in ['assigned', 'accepted']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot start delivery - current status is {errand.status}"
            )

        if pilot_id and errand.pilot_id and int(errand.pilot_id) != int(pilot_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not assigned to this errand",
            )

        previous_status = errand.status

        # Update errand status
        errand.status = 'in_progress'
        errand.started_at = datetime.now(timezone.utc)
        errand.tracking_paused = False
        if note:
            errand.pilot_notes = note

        # Record timeline/history event (used by client timeline + pilot/admin activity feeds).
        db.add(
            ErrandEvent(
                errand_id=errand.id,
                event_type="pilot_started",
                old_status=previous_status,
                new_status=errand.status,
                note=(note or "Pilot started delivery")[:2000] if note else "Pilot started delivery",
                user_id=pilot_user.id,
            )
        )

        await db.commit()
        await db.refresh(errand)

        # Notifications can be slow (email/SMS). Do not block pilot UX on them.
        async def _send_start_notifications() -> None:
            try:
                async with AsyncSessionLocal() as session:
                    refreshed = await session.get(Errand, int(errand_id))
                    if not refreshed:
                        return
                    await notify_customer_status(
                        session,
                        errand=refreshed,
                        old_status=previous_status,
                        new_status=refreshed.status,
                        trigger="pilot-start",
                    )
                    await notify_tracking_started(
                        session,
                        errand=refreshed,
                        trigger="pilot-start",
                    )
            except Exception as e:
                logger.warning(f"[notify] pilot start notifications failed: {e}")

        if isinstance(db, AsyncSession):
            asyncio.create_task(_send_start_notifications())

        pilot_id_used = pilot_id or errand.pilot_id or 1
        logger.info(f"🚀 Pilot {pilot_id_used} started delivery {errand_id}")

        return {
            "success": True,
            "errand_id": errand_id,
            "status": errand.status,
            "tracking_enabled": True,
            "tracking_url": f"/tracking/ws/{errand_id}",
            "message": "Delivery started. GPS tracking is now active.",
            "pickup_location": errand.pickup_location,
            "dropoff_location": errand.dropoff_location,
            "delivery_location": errand.dropoff_location,
            "customer_name": getattr(errand, "customer_name", "Unknown"),
            "amount": getattr(errand, "amount", 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting delivery: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start delivery"
        )


@router.post("/delay-reason", response_model=dict)
async def submit_delay_reason(
    errand_id: int = Body(..., embed=True),
    reason: str = Body(..., embed=True),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Pilot submits a reason for a detected delay."""

    pilot = await _get_current_user(authorization, db)

    errand = await db.get(Errand, errand_id)
    if not errand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Errand not found")

    if not errand.pilot_id or int(errand.pilot_id) != int(pilot.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not assigned to this errand")

    errand.issue_reason = reason
    errand.issue_notes = reason
    errand.issue_status = "delay_reported"
    errand.issue_reported_at = datetime.now(timezone.utc)

    db.add(
        ErrandEvent(
            errand_id=errand.id,
            event_type="delay_reason",
            old_status=errand.status,
            new_status=errand.status,
            note=reason,
            user_id=pilot.id,
        )
    )

    await db.commit()
    await db.refresh(errand)

    incident = await db.scalar(
        select(IncidentReport)
        .where(IncidentReport.errand_id == errand.id)
        .where(IncidentReport.status == "open")
        .order_by(IncidentReport.created_at.desc())
    )

    if not incident:
        incident = IncidentReport(
            errand_id=errand.id,
            pilot_id=pilot.id,
            incident_type="delay_reported",
            description=reason,
            status="open",
            detected_by="pilot",
        )
        db.add(incident)
        await db.commit()
        await db.refresh(incident)

    db.add(
        IncidentMessage(
            incident_id=incident.id,
            sender_type="pilot",
            message=reason,
        )
    )

    db.add(
        ErrandEvent(
            errand_id=errand.id,
            event_type="delay_reason",
            old_status=errand.status,
            new_status=errand.status,
            note=reason,
            user_id=pilot.id,
        )
    )
    await db.commit()

    try:
        await notify_admin_status(
            db,
            errand=errand,
            old_status=errand.status,
            new_status=errand.status,
            trigger="pilot-delay-reason",
            message=f"Pilot submitted delay reason: {reason}",
            include_tracking=True,
        )
        await notify_customer_status(
            db,
            errand=errand,
            old_status=errand.status,
            new_status=errand.status,
            trigger="pilot-delay-reason",
        )
    except Exception as e:
        logger.warning(f"[notify] delay reason email failed: {e}")

    return {
        "success": True,
        "errand_id": errand.id,
        "status": errand.status,
        "issue_status": errand.issue_status,
    }


@router.post("/complete-delivery", response_model=dict)
async def complete_delivery(
    errand_id: int,
    signature_url: Optional[str] = None,
    photo_url: Optional[str] = None,
    notes: Optional[str] = None,
    tip: Optional[float] = 0,
    pilot_id: Optional[int] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Pilot completes a delivery
    - Stops GPS tracking
    - Updates errand status to 'completed'
    - Records delivery proof (signature/photo)
    - Calculates distance and time
    """
    try:
        pilot_user = await _get_current_user(authorization, db)

        # Verify errand exists
        query = select(Errand).filter(Errand.id == errand_id)
        result = await db.execute(query)
        errand = result.scalar_one_or_none()

        if not errand:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Errand not found"
            )

        if errand.pilot_id and int(errand.pilot_id) != int(pilot_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not assigned to this errand",
            )

        if errand.status != 'in_progress':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot complete delivery - current status is {errand.status}"
            )

        # Calculate delivery time
        if errand.started_at:
            now = datetime.now(timezone.utc)
            delivery_time = (now - errand.started_at).total_seconds()
        else:
            delivery_time = 0

        previous_status = errand.status

        # Update errand
        errand.status = 'completed'
        errand.completed_at = datetime.now(timezone.utc)
        errand.delivery_time = delivery_time
        errand.tracking_paused = False
        if signature_url:
            errand.signature_url = signature_url
        if photo_url:
            errand.photo_url = photo_url
        if notes:
            errand.completion_notes = notes
        if tip:
            errand.tip = tip

        # Record timeline/history event (used by client timeline + pilot/admin activity feeds).
        db.add(
            ErrandEvent(
                errand_id=errand.id,
                event_type="pilot_completed",
                old_status=previous_status,
                new_status=errand.status,
                note=(notes or "Pilot completed delivery")[:2000] if notes else "Pilot completed delivery",
                user_id=pilot_user.id,
            )
        )

        # Mark tracking as inactive
        # (This would be tracked in pilot_locations table with completion flag)

        await db.commit()
        await db.refresh(errand)

        try:
            await notify_customer_status(
                db,
                errand=errand,
                old_status=previous_status,
                new_status=errand.status,
                trigger="pilot-complete",
            )
            await notify_pilot_status(
                db,
                errand=errand,
                new_status="completed",
                trigger="pilot-complete",
            )
        except Exception as e:
            logger.warning(f"[notify] pilot completion email failed: {e}")

        pilot_id_used = pilot_id or errand.pilot_id or 1
        archive_payload = None
        try:
            archive_payload = await _archive_route_snapshot(db, errand, actor_id=pilot_id_used)
        except Exception as archive_err:
            logger.warning(f"[tracking] Unable to archive route for errand {errand_id}: {archive_err}")

        logger.info(
            f"✅ Pilot {pilot_id_used} completed delivery {errand_id} "
            f"in {delivery_time/60:.1f} minutes"
        )

        return {
            "success": True,
            "errand_id": errand_id,
            "status": errand.status,
            "tracking_enabled": False,
            "delivery_time_minutes": round(delivery_time / 60, 1),
            "delivery_time_seconds": int(delivery_time),
            "message": "✅ Delivery completed successfully!",
            "completed_at": errand.completed_at.isoformat(),
            "route_archive": archive_payload,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing delivery: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete delivery"
        )


@router.post("/pause-tracking", response_model=dict)
async def pause_tracking(
    errand_id: int,
    pilot_id: Optional[int] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Pilot pauses GPS tracking temporarily
    - Still marked as in_progress
    - No location updates sent
    - Can resume tracking
    """
    try:
        pilot_user = await _get_current_user(authorization, db)
        query = select(Errand).filter(Errand.id == errand_id)
        result = await db.execute(query)
        errand = result.scalar_one_or_none()

        if not errand:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Errand not found"
            )

        if errand.pilot_id and int(errand.pilot_id) != int(pilot_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not assigned to this errand",
            )

        if errand.status != 'in_progress':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only pause active deliveries"
            )

        # Set tracking pause flag
        errand.tracking_paused = True
        await db.commit()

        try:
            await notify_customer_status(
                db,
                errand=errand,
                old_status=errand.status,
                new_status=errand.status,
                trigger="tracking-paused",
                message="Live tracking is temporarily paused. Your pilot will resume sharing location shortly.",
            )
        except Exception as e:
            logger.warning(f"[notify] tracking pause email failed: {e}")

        pilot_id_used = pilot_id or errand.pilot_id or 1
        logger.info(f"⏸️ Pilot {pilot_id_used} paused tracking for {errand_id}")

        return {
            "success": True,
            "errand_id": errand_id,
            "tracking_paused": True,
            "message": "Tracking paused. Your location is no longer being shared.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pausing tracking: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to pause tracking"
        )


@router.post("/resume-tracking", response_model=dict)
async def resume_tracking(
    errand_id: int,
    pilot_id: Optional[int] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Pilot resumes GPS tracking
    """
    try:
        pilot_user = await _get_current_user(authorization, db)
        query = select(Errand).filter(Errand.id == errand_id)
        result = await db.execute(query)
        errand = result.scalar_one_or_none()

        if not errand:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Errand not found"
            )

        if errand.pilot_id and int(errand.pilot_id) != int(pilot_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not assigned to this errand",
            )

        if errand.status != 'in_progress':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only resume active deliveries"
            )

        errand.tracking_paused = False
        await db.commit()

        try:
            await notify_customer_status(
                db,
                errand=errand,
                old_status=errand.status,
                new_status=errand.status,
                trigger="tracking-resumed",
                message="Live tracking is back on. You can continue following the pilot in real time.",
            )
        except Exception as e:
            logger.warning(f"[notify] tracking resume email failed: {e}")

        pilot_id_used = pilot_id or errand.pilot_id or 1
        logger.info(f"▶️ Pilot {pilot_id_used} resumed tracking for {errand_id}")

        return {
            "success": True,
            "errand_id": errand_id,
            "tracking_paused": False,
            "message": "Tracking resumed. Your live location is being shared again.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming tracking: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resume tracking"
        )

@router.get("/active-delivery", response_model=dict)
async def get_active_delivery(
    authorization: Optional[str] = Header(default=None),
    pilot_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get pilot's current active delivery (if any)
    """
    try:
        pilot = await _get_current_user(authorization, db)

        requested_pilot_id = pilot_id or pilot.id
        if int(requested_pilot_id) != int(pilot.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own active delivery",
            )

        query = (
            select(Errand)
            .filter(Errand.status == 'in_progress')
            .filter(Errand.pilot_id == pilot.id)
            .order_by(Errand.started_at.desc(), Errand.id.desc())
        )
        result = await db.execute(query)
        errand = result.scalar()

        if not errand:
            return {
                "has_active_delivery": False,
                "errand": None,
                "message": "No active delivery",
            }

        return {
            "has_active_delivery": True,
            "errand": {
                "id": errand.id,
                "customer_name": getattr(errand, "customer_name", "Unknown"),
                "pickup_location": errand.pickup_location,
                "dropoff_location": errand.dropoff_location,
                "delivery_location": errand.dropoff_location,
                "pilot_id": errand.pilot_id,
                "pilotId": errand.pilot_id,
                "amount": getattr(errand, "amount", 0),
                "payment_amount_ngn_major": getattr(errand, "payment_amount_ngn_major", None),
                "paymentAmountNgnMajor": getattr(errand, "payment_amount_ngn_major", None),
                "status": errand.status,
                "started_at": errand.started_at.isoformat() if errand.started_at else None,
                "tracking_paused": getattr(errand, "tracking_paused", False),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting active delivery: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get active delivery"
        )


@router.post("/assign-job", response_model=dict)
async def assign_job(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Pilot accepts an admin-assigned job
    - Confirms pilot assignment
    - Changes status to 'accepted'
    - Returns the errand details
    """
    try:
        # Get pilot from auth or request body
        errand_id = payload.get('errand_id')
        pilot_id = payload.get('pilot_id')
        
        # If no pilot_id in body, get from authorization
        if not pilot_id and authorization:
            from auth import decode_access_token
            token = authorization.replace("Bearer ", "")
            pilot_id = decode_access_token(token)
        
        if not errand_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="errand_id is required"
            )
        
        if not pilot_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pilot_id or valid authorization token is required"
            )

        # Get the errand
        query = select(Errand).filter(Errand.id == errand_id)
        result = await db.execute(query)
        errand = result.scalar_one_or_none()

        if not errand:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Errand not found"
            )

        print(f"[DEBUG] Errand {errand_id}: status={errand.status}, pilot_id={errand.pilot_id}", flush=True)

        if errand.pilot_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Errand must be assigned by an admin before acceptance"
            )

        if int(errand.pilot_id) != int(pilot_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not assigned to this errand"
            )

        if errand.status != "assigned":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot accept errand with status {errand.status}"
            )

        previous_status = errand.status

        # Accept the assigned errand
        errand.status = "accepted"

        await db.commit()
        await db.refresh(errand)

        try:
            pilot_user = await db.get(User, int(pilot_id))
            await notify_customer_status(
                db,
                errand=errand,
                old_status=previous_status,
                new_status=errand.status,
                trigger="pilot-assign-job",
            )
            await notify_admin_status(
                db,
                errand=errand,
                old_status=previous_status,
                new_status=errand.status,
                trigger="pilot-assign-job",
                message="Pilot accepted the admin-assigned errand.",
            )
            await notify_pilot_status(
                db,
                errand=errand,
                new_status="accepted",
                trigger="pilot-assign-job",
                pilot_user=pilot_user,
            )
        except Exception as e:
            logger.warning(f"[notify] assign-job email failed: {e}")

        logger.info(f"✅ Pilot {pilot_id} accepted job {errand_id}")

        return {
            "success": True,
            "errand_id": errand_id,
            "pilot_id": pilot_id,
            "status": errand.status,
            "message": "Job accepted successfully",
            "id": errand.id,
            "reference_number": errand.reference_number,
            "title": errand.title,
            "description": errand.description,
            "pickup_location": errand.pickup_location,
            "dropoff_location": errand.dropoff_location,
            "customer_name": getattr(errand, "customer_name", "Unknown"),
            "amount": getattr(errand, "amount", 0),
            "payment_amount_ngn_major": getattr(errand, "payment_amount_ngn_major", None),
            "paymentAmountNgnMajor": getattr(errand, "payment_amount_ngn_major", None),
            "distance_km": getattr(errand, "distance_km", None),
            "customer_rating": getattr(errand, "customer_rating", 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning job: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign job"
        )
