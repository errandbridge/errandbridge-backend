"""
Real-time pilot location tracking for ErrandBridge
Handles GPS updates, location history, and live tracking streams
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
    Header,
    Request,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, desc, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal
import json
import logging
import sys
import os
import math

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from auth import decode_access_token
from app.utils.admin_utils import admin_emails
from database import get_db, AsyncSessionLocal
from models import (
    PilotLocation,
    Errand,
    User,
    IncidentReport,
    IncidentMessage,
    ErrandEvent,
)
from app.utils.notification_utils import notify_delay_detected

from app.metrics.business_metrics import (
    observe_tracking_delay_detected,
    observe_tracking_update,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracking", tags=["pilot-tracking"])

ACTIVE_TRACKING_STATUSES = {"in_progress", "picked_up", "delivered"}
HISTORY_TRACKING_STATUSES = {"completed", *ACTIVE_TRACKING_STATUSES}
STALL_MINUTES = int(os.getenv("PILOT_STALL_MINUTES", "5"))
STALL_DISTANCE_METERS = float(os.getenv("PILOT_STALL_DISTANCE_METERS", "30"))
STALL_REPEAT_MINUTES = int(os.getenv("PILOT_STALL_REPEAT_MINUTES", "15"))
TRACKING_SOURCES = {"mobile_app", "fob"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _tracking_window_info(errand: Errand) -> dict:
    started_at = _coerce_utc(errand.started_at)
    window_start = _coerce_utc(errand.pickup_time_slot_start)
    window_end = _coerce_utc(errand.pickup_time_slot_end)

    within_window = True
    if window_start and window_end and started_at:
        within_window = window_start <= started_at <= window_end

    return {
        "started_at": started_at,
        "window_start": window_start,
        "window_end": window_end,
        "within_window": within_window,
    }


def _tracking_status_payload(errand: Errand) -> dict:
    window_info = _tracking_window_info(errand)
    started_at = window_info["started_at"]
    within_window = window_info["within_window"]
    tracking_active = errand.status in ACTIVE_TRACKING_STATUSES
    tracking_allowed = bool(started_at) and within_window

    reason = None
    if not started_at:
        reason = "Tracking becomes available once the pilot starts the errand."
    elif not within_window:
        reason = "Tracking is unavailable because the pilot started outside the requested time window."
    elif not tracking_active:
        reason = "Tracking is not active for this errand status."

    return {
        "errand_id": errand.id,
        "status": errand.status,
        "tracking_allowed": tracking_allowed,
        "tracking_active": tracking_active,
        "within_time_window": within_window,
        "started_at": started_at.isoformat() if started_at else None,
        "window_start": (
            window_info["window_start"].isoformat()
            if window_info["window_start"]
            else None
        ),
        "window_end": (
            window_info["window_end"].isoformat() if window_info["window_end"] else None
        ),
        "reason": reason,
    }


def _normalize_tracking_source(value: Optional[str]) -> str:
    normalized = str(value or "mobile_app").strip().lower()
    if normalized not in TRACKING_SOURCES:
        return "mobile_app"
    return normalized


def _validate_tracking_access(errand: Errand, allow_history: bool = False) -> dict:
    payload = _tracking_status_payload(errand)

    if not payload["tracking_allowed"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=payload["reason"] or "Tracking is not available for this errand.",
        )

    if allow_history:
        if errand.status not in HISTORY_TRACKING_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=payload["reason"] or "Tracking history is not available yet.",
            )
    else:
        if errand.status not in ACTIVE_TRACKING_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=payload["reason"] or "Tracking is not active for this errand.",
            )

    return payload


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def _require_assigned_pilot(
    authorization: Optional[str],
    errand: Errand,
    db: AsyncSession,
) -> User:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not getattr(user, "is_pilot", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pilot access required",
        )

    if not errand.pilot_id or int(errand.pilot_id) != int(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this errand",
        )

    return user


async def _require_errand_owner(
    authorization: Optional[str],
    errand: Errand,
    db: AsyncSession,
) -> User:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    admin_set = admin_emails()
    is_admin = user.email.lower() in admin_set if user.email else False
    is_pilot = errand.pilot_id and int(errand.pilot_id) == int(user.id)

    if int(errand.user_id) != int(user.id) and not is_admin and not is_pilot:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the errand owner, assigned pilot, or admin can track this delivery",
        )

    return user


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _tracking_request_fingerprint(request: Request, location) -> dict:
    headers = getattr(request, "headers", None) or {}
    return {
        "errand_id": location.errand_id,
        "client": headers.get("x-eb-tracking-client", "unknown"),
        "client_version": headers.get("x-eb-tracking-client-version", "unknown"),
        "client_session": headers.get("x-eb-tracking-session", "unknown"),
        "origin": headers.get("origin", ""),
        "referer": headers.get("referer", ""),
        "user_agent": headers.get("user-agent", ""),
    }


# ============= Pydantic Models =============


class LocationUpdate(BaseModel):
    """GPS location update from pilot"""

    errand_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    altitude: Optional[float] = None
    source: Literal["mobile_app", "fob"] = "mobile_app"
    recorded_at: Optional[datetime] = None


class LocationResponse(BaseModel):
    """Single location data point"""

    id: int
    errand_id: int
    pilot_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float]
    speed: Optional[float]
    heading: Optional[float]
    altitude: Optional[float]
    source: str = "mobile_app"
    recorded_at: Optional[datetime] = None
    created_at: datetime
    status: Optional[str] = None
    tracking_paused: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


def _build_location_response(
    location: PilotLocation, errand: Errand
) -> LocationResponse:
    return LocationResponse(
        id=location.id,
        errand_id=location.errand_id,
        pilot_id=location.pilot_id,
        latitude=location.latitude,
        longitude=location.longitude,
        accuracy=location.accuracy,
        speed=location.speed,
        heading=location.heading,
        altitude=location.altitude,
        source=_normalize_tracking_source(getattr(location, "source", None)),
        recorded_at=_coerce_utc(getattr(location, "recorded_at", None))
        or _coerce_utc(location.created_at),
        created_at=location.created_at,
        status=errand.status,
        tracking_paused=bool(getattr(errand, "tracking_paused", False)),
    )


class RouteHistoryResponse(BaseModel):
    """Complete route history for an errand"""

    errand_id: int
    pilot_id: int
    total_points: int
    start_location: Optional[LocationResponse]
    end_location: Optional[LocationResponse]
    locations: list
    distance_traveled: Optional[float]  # in km
    duration: Optional[str]


# ============= REST Endpoints =============


@router.post("/update", response_model=LocationResponse)
async def update_location(
    location: LocationUpdate,
    authorization: Optional[str] = Header(default=None),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Update pilot location during active errand
    Called frequently (every 5-10 seconds) from mobile app
    """

    # Verify errand exists
    errand_query = select(Errand).where(Errand.id == location.errand_id)
    errand = await db.scalar(errand_query)

    if not errand:
        observe_tracking_update(result="rejected", reason="errand_not_found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Errand not found"
        )

    fingerprint = _tracking_request_fingerprint(request, location)

    try:
        pilot_user = await _require_assigned_pilot(authorization, errand, db)
    except HTTPException as exc:
        pilot_user_id = None
        try:
            token_value = _extract_bearer(authorization)
            pilot_user_id = decode_access_token(token_value) if token_value else None
        except Exception:
            pilot_user_id = None

        if exc.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
            reason = (
                "unauthorized"
                if exc.status_code == status.HTTP_401_UNAUTHORIZED
                else "forbidden"
            )
            observe_tracking_update(result="rejected", reason=reason)
            logger.warning(
                "[tracking] rejected update errand_id=%s status=%s pilot_user_id=%s assigned_pilot_id=%s client=%s version=%s session=%s origin=%s referer=%s ua=%s",
                fingerprint["errand_id"],
                exc.status_code,
                pilot_user_id or "unknown",
                getattr(errand, "pilot_id", None),
                fingerprint["client"],
                fingerprint["client_version"],
                fingerprint["client_session"],
                fingerprint["origin"],
                fingerprint["referer"],
                fingerprint["user_agent"],
            )
        raise

    window_info = _tracking_window_info(errand)
    started_now = False
    status_updated = False
    previous_status = errand.status

    if not errand.started_at:
        errand.started_at = _utc_now()
        started_now = True

    if errand.status not in ACTIVE_TRACKING_STATUSES and errand.status not in {
        "completed",
        "cancelled",
    }:
        errand.status = "in_progress"
        status_updated = True

    if started_now or status_updated:
        db.add(errand)
        db.add(
            ErrandEvent(
                errand_id=errand.id,
                event_type="pilot_started" if status_updated else "tracking_started",
                old_status=previous_status,
                new_status=errand.status,
                note="Tracking started from pilot GPS update.",
                user_id=errand.pilot_id,
            )
        )
        await db.commit()
        await db.refresh(errand)

    # Get pilot_id from errand
    pilot_id = errand.pilot_id or pilot_user.id

    normalized_source = _normalize_tracking_source(location.source)
    recorded_at = _coerce_utc(location.recorded_at) or _utc_now()

    # Create location record
    pilot_loc = PilotLocation(
        errand_id=location.errand_id,
        pilot_id=pilot_id,
        latitude=location.latitude,
        longitude=location.longitude,
        accuracy=location.accuracy,
        speed=location.speed,
        heading=location.heading,
        altitude=location.altitude,
        source=normalized_source,
        recorded_at=recorded_at,
        created_at=recorded_at,
    )

    db.add(pilot_loc)
    await db.commit()
    await db.refresh(pilot_loc)

    logger.info(
        "Location update: pilot %s errand_id=%s client=%s version=%s session=%s at %s,%s",
        pilot_id,
        location.errand_id,
        fingerprint["client"],
        fingerprint["client_version"],
        fingerprint["client_session"],
        location.latitude,
        location.longitude,
    )

    observe_tracking_update(result="ok", reason="none")

    if errand.status in ACTIVE_TRACKING_STATUSES:
        cutoff = _utc_now() - timedelta(minutes=STALL_MINUTES)
        try:
            stale_loc = await db.scalar(
                select(PilotLocation)
                .where(PilotLocation.errand_id == location.errand_id)
                .where(PilotLocation.created_at <= cutoff)
                .order_by(desc(PilotLocation.created_at))
                .limit(1)
            )
        except Exception:
            stale_loc = None

        if stale_loc:
            distance_m = _haversine_meters(
                stale_loc.latitude,
                stale_loc.longitude,
                pilot_loc.latitude,
                pilot_loc.longitude,
            )
            stale_created_at = _coerce_utc(stale_loc.created_at)
            current_created_at = _coerce_utc(pilot_loc.created_at) or _utc_now()
            minutes_idle = (current_created_at - stale_created_at).total_seconds() / 60
            now = _utc_now()
            last_issue = _coerce_utc(errand.issue_reported_at)

            if distance_m <= STALL_DISTANCE_METERS:
                should_alert = not last_issue or (now - last_issue) > timedelta(
                    minutes=STALL_REPEAT_MINUTES
                )
                if should_alert:
                    observe_tracking_delay_detected(trigger="tracking-delay")
                    errand.issue_reported_at = now
                    errand.issue_status = "delay_detected"
                    await db.commit()

                    incident = await db.scalar(
                        select(IncidentReport)
                        .where(IncidentReport.errand_id == errand.id)
                        .where(IncidentReport.status == "open")
                        .order_by(desc(IncidentReport.created_at))
                    )

                    if not incident:
                        incident = IncidentReport(
                            errand_id=errand.id,
                            pilot_id=errand.pilot_id,
                            incident_type="delay_detected",
                            description=f"Movement stalled for {minutes_idle:.1f} minutes.",
                            status="open",
                            detected_by="ai",
                        )
                        db.add(incident)
                        await db.commit()
                        await db.refresh(incident)

                    db.add(
                        IncidentMessage(
                            incident_id=incident.id,
                            sender_type="ai",
                            message="AI detected a delay. Please share what happened so we can update the client and admin.",
                        )
                    )
                    await db.commit()
                    await notify_delay_detected(
                        db,
                        errand=errand,
                        minutes_idle=minutes_idle,
                        distance_meters=distance_m,
                        trigger="tracking-delay",
                    )

    payload = _build_location_response(pilot_loc, errand)

    if (
        errand.status in ACTIVE_TRACKING_STATUSES
        and not errand.tracking_paused
        and window_info["within_window"]
    ):
        await manager.broadcast(
            location.errand_id,
            {
                "type": "location_update",
                "location": payload.model_dump(mode="json"),
            },
        )

    return payload


@router.get("/status/{errand_id}", response_model=dict)
async def get_tracking_status(
    errand_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    errand = await db.scalar(select(Errand).where(Errand.id == errand_id))

    if not errand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Errand not found",
        )

    await _require_errand_owner(authorization, errand, db)

    return _tracking_status_payload(errand)


@router.get("/current/{errand_id}", response_model=LocationResponse)
async def get_current_location(
    errand_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Get latest location for an errand
    Visible to customers and pilots
    """

    errand = await db.scalar(select(Errand).where(Errand.id == errand_id))
    if not errand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Errand not found",
        )

    await _require_errand_owner(authorization, errand, db)
    _validate_tracking_access(errand, allow_history=True)

    # Get latest location
    query = (
        select(PilotLocation)
        .where(PilotLocation.errand_id == errand_id)
        .order_by(
            desc(func.coalesce(PilotLocation.recorded_at, PilotLocation.created_at))
        )
        .limit(1)
    )

    location = await db.scalar(query)

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No location data available yet",
        )

    return _build_location_response(location, errand)


@router.get("/history/{errand_id}", response_model=RouteHistoryResponse)
async def get_route_history(
    errand_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Get complete location history for an errand
    Visible to customers and pilots
    """

    errand = await db.scalar(select(Errand).where(Errand.id == errand_id))
    if not errand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Errand not found",
        )

    await _require_errand_owner(authorization, errand, db)
    _validate_tracking_access(errand, allow_history=True)

    # Get all locations for errand, ordered by time
    query = (
        select(PilotLocation)
        .where(PilotLocation.errand_id == errand_id)
        .order_by(
            func.coalesce(PilotLocation.recorded_at, PilotLocation.created_at),
            PilotLocation.id,
        )
    )

    locations = await db.scalars(query)
    locations = list(locations)

    if not locations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No location history available",
        )

    start_loc = _build_location_response(locations[0], errand) if locations else None
    end_loc = _build_location_response(locations[-1], errand) if locations else None

    # Calculate approximate distance (simplified)
    distance = calculate_total_distance([loc for loc in locations])
    duration = (
        locations[-1].created_at - locations[0].created_at
        if len(locations) > 1
        else None
    )

    return RouteHistoryResponse(
        errand_id=errand_id,
        pilot_id=locations[0].pilot_id,
        total_points=len(locations),
        start_location=start_loc,
        end_location=end_loc,
        locations=[_build_location_response(loc, errand) for loc in locations],
        distance_traveled=distance,
        duration=str(duration) if duration else None,
    )


@router.get("/locations-last-hour/{errand_id}", response_model=list)
async def get_locations_last_hour(
    errand_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get all locations from the last hour"""

    errand = await db.scalar(select(Errand).where(Errand.id == errand_id))
    if not errand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Errand not found",
        )

    await _require_errand_owner(authorization, errand, db)
    _validate_tracking_access(errand, allow_history=True)

    one_hour_ago = _utc_now() - timedelta(hours=1)

    query = (
        select(PilotLocation)
        .where(
            and_(
                PilotLocation.errand_id == errand_id,
                func.coalesce(PilotLocation.recorded_at, PilotLocation.created_at)
                >= one_hour_ago,
            )
        )
        .order_by(
            func.coalesce(PilotLocation.recorded_at, PilotLocation.created_at),
            PilotLocation.id,
        )
    )

    locations = await db.scalars(query)
    return [_build_location_response(loc, errand) for loc in locations]


# ============= WebSocket for Real-time Tracking =============


class ConnectionManager:
    """Manage WebSocket connections for real-time tracking"""

    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, errand_id: int, websocket: WebSocket):
        await websocket.accept()
        if errand_id not in self.active_connections:
            self.active_connections[errand_id] = []
        self.active_connections[errand_id].append(websocket)

    def disconnect(self, errand_id: int, websocket: WebSocket):
        if errand_id in self.active_connections:
            self.active_connections[errand_id].remove(websocket)
            if not self.active_connections[errand_id]:
                del self.active_connections[errand_id]

    async def broadcast(self, errand_id: int, message: dict):
        """Send location update to all connected clients watching this errand"""
        if errand_id in self.active_connections:
            stale_connections: list[WebSocket] = []
            for connection in list(self.active_connections[errand_id]):
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting: {e}")
                    stale_connections.append(connection)

            for connection in stale_connections:
                self.disconnect(errand_id, connection)


manager = ConnectionManager()


@router.websocket("/ws/{errand_id}")
async def websocket_endpoint(websocket: WebSocket, errand_id: int):
    """
    WebSocket for real-time pilot location tracking
    Connect to receive live updates as pilot moves
    """
    token = websocket.query_params.get("token")

    async with AsyncSessionLocal() as session:
        errand = await session.scalar(select(Errand).where(Errand.id == errand_id))
        if not token:
            errand = None
        elif errand:
            user_id = decode_access_token(token)
            if not user_id:
                errand = None
            else:
                user = await session.get(User, user_id)
                if not user:
                    errand = None
                else:
                    admin_set = admin_emails()
                    is_admin = user.email.lower() in admin_set if user.email else False
                    is_pilot = errand.pilot_id and int(errand.pilot_id) == int(user.id)
                    is_owner = int(errand.user_id) == int(user.id)
                    if not (is_admin or is_owner or is_pilot):
                        errand = None

    if not errand:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "tracking_unavailable",
                "reason": "Tracking is restricted to the errand owner.",
            }
        )
        await websocket.close(code=1008)
        return

    payload = _tracking_status_payload(errand)
    if not payload["tracking_allowed"] or errand.status not in ACTIVE_TRACKING_STATUSES:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "tracking_unavailable",
                "reason": payload["reason"]
                or "Tracking is not active for this errand.",
            }
        )
        await websocket.close(code=1008)
        return

    await manager.connect(errand_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(errand_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(errand_id, websocket)


# ============= Utility Functions =============


def calculate_total_distance(locations: list[PilotLocation]) -> float:
    """Calculate approximate distance traveled using Haversine formula"""
    from math import radians, cos, sin, asin, sqrt

    if len(locations) < 2:
        return 0.0

    total_distance = 0.0

    for i in range(len(locations) - 1):
        lat1, lon1 = radians(float(locations[i].latitude)), radians(
            float(locations[i].longitude)
        )
        lat2, lon2 = radians(float(locations[i + 1].latitude)), radians(
            float(locations[i + 1].longitude)
        )

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        r = 6371  # Earth radius in km

        total_distance += c * r

    return round(total_distance, 2)
