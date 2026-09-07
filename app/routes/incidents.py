from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.admin_utils import require_admin_user
from auth import decode_access_token
from database import get_db
from models import Errand, IncidentReport, IncidentMessage, User
from app.utils.notification_utils import (
    notify_admin_status,
    notify_customer_incident_update,
    notify_customer_status,
    notify_pilot_status,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


class IncidentReportIn(BaseModel):
    errand_id: int
    incident_type: str = Field(..., min_length=2)
    description: str = Field(..., min_length=3)


class IncidentMessageIn(BaseModel):
    message: str = Field(..., min_length=2)


class AdminIncidentMessageIn(BaseModel):
    message: str = Field(..., min_length=2)
    notify_customer: bool = True


class AdminIncidentResolveIn(BaseModel):
    status: str = Field(default="resolved")
    release_errand: bool = True


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token


async def _require_pilot(authorization: Optional[str], db: AsyncSession) -> User:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.get(User, user_id)
    if not user or not getattr(user, "is_pilot", False):
        raise HTTPException(status_code=403, detail="Pilot access required")
    return user


@router.post("/report", response_model=dict)
async def report_incident(
    payload: IncidentReportIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Pilot reports an incident during a trip."""

    pilot = await _require_pilot(authorization, db)

    errand = await db.get(Errand, payload.errand_id)
    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")

    if not errand.pilot_id or int(errand.pilot_id) != int(pilot.id):
        raise HTTPException(status_code=403, detail="Not assigned to this errand")

    errand.issue_reason = payload.incident_type
    errand.issue_notes = payload.description
    errand.issue_status = "pending_admin_review"
    errand.issue_reported_at = datetime.now(timezone.utc)

    incident = IncidentReport(
        errand_id=errand.id,
        pilot_id=pilot.id,
        incident_type=payload.incident_type,
        description=payload.description,
        detected_by="pilot",
        status="open",
    )
    db.add(incident)
    await db.commit()
    await db.refresh(incident)

    message = IncidentMessage(
        incident_id=incident.id,
        sender_type="pilot",
        message=payload.description,
    )
    db.add(message)
    await db.commit()

    try:
        await notify_admin_status(
            db,
            errand=errand,
            old_status=errand.status,
            new_status=errand.status,
            trigger="pilot-incident-report",
            message=f"Incident reported: {payload.incident_type} - {payload.description}",
            include_tracking=True,
        )
    except Exception:
        pass

    return {"incident_id": incident.id, "status": incident.status}


@router.post("/{incident_id}/messages", response_model=dict)
async def add_incident_message(
    incident_id: int,
    payload: IncidentMessageIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Pilot adds a message to an incident thread."""

    pilot = await _require_pilot(authorization, db)

    incident = await db.get(IncidentReport, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if not incident.pilot_id or int(incident.pilot_id) != int(pilot.id):
        raise HTTPException(status_code=403, detail="Not assigned to this incident")

    message = IncidentMessage(
        incident_id=incident.id,
        sender_type="pilot",
        message=payload.message,
    )
    db.add(message)
    await db.commit()

    errand = await db.get(Errand, incident.errand_id)
    if errand:
        try:
            await notify_admin_status(
                db,
                errand=errand,
                old_status=errand.status,
                new_status=errand.status,
                trigger="pilot-incident-message",
                message=f"Pilot update: {payload.message}",
                include_tracking=True,
            )
        except Exception:
            pass

    return {"success": True}


@router.get("", response_model=dict)
async def list_all_incidents(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin view of all incidents."""

    user = None
    token = _extract_bearer(authorization)
    if token:
        user_id = decode_access_token(token)
        if user_id:
            user = await db.get(User, user_id)

    if not user:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    await require_admin_user(db, user.id)

    incidents = await db.execute(
        select(IncidentReport, Errand)
        .join(Errand, IncidentReport.errand_id == Errand.id)
        .order_by(desc(IncidentReport.created_at))
    )

    payload = []
    for incident, errand in incidents.all():
        payload.append(
            {
                "id": incident.id,
                "errand_id": incident.errand_id,
                "errand_reference": errand.reference_number or f"EB-{errand.id}",
                "errand_title": errand.title,
                "errand_status": errand.status,
                "pilot_id": incident.pilot_id,
                "incident_type": incident.incident_type,
                "description": incident.description,
                "status": incident.status,
                "detected_by": incident.detected_by,
                "created_at": (
                    incident.created_at.isoformat() if incident.created_at else None
                ),
                "updated_at": (
                    incident.updated_at.isoformat() if incident.updated_at else None
                ),
            }
        )

    return {"incidents": payload}


@router.get("/alerts", response_model=dict)
async def list_incident_alerts(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Return a lightweight open-incident payload for admin polling."""

    user = None
    token = _extract_bearer(authorization)
    if token:
        user_id = decode_access_token(token)
        if user_id:
            user = await db.get(User, user_id)

    if not user:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    await require_admin_user(db, user.id)

    incidents = await db.execute(
        select(IncidentReport, Errand)
        .join(Errand, IncidentReport.errand_id == Errand.id)
        .where(IncidentReport.status == "open")
        .order_by(desc(IncidentReport.updated_at), desc(IncidentReport.created_at))
        .limit(50)
    )

    return {
        "incidents": [
            {
                "id": incident.id,
                "errand_id": incident.errand_id,
                "errand_reference": errand.reference_number or f"EB-{errand.id}",
                "status": incident.status,
                "updated_at": (
                    incident.updated_at.isoformat() if incident.updated_at else None
                ),
                "created_at": (
                    incident.created_at.isoformat() if incident.created_at else None
                ),
            }
            for incident, errand in incidents.all()
        ]
    }


@router.post("/{incident_id}/admin-message", response_model=dict)
async def add_admin_incident_message(
    incident_id: int,
    payload: AdminIncidentMessageIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin adds a message to an incident thread and optionally notifies customer."""

    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    await require_admin_user(db, user_id)

    incident = await db.get(IncidentReport, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    message = IncidentMessage(
        incident_id=incident.id,
        sender_type="admin",
        message=payload.message,
    )
    db.add(message)

    incident.updated_at = datetime.now(timezone.utc)
    await db.commit()

    errand = await db.get(Errand, incident.errand_id)
    if errand and payload.notify_customer:
        try:
            await notify_customer_incident_update(
                db, errand=errand, message=payload.message
            )
        except Exception:
            pass

    return {"success": True}


@router.post("/{incident_id}/resolve", response_model=dict)
async def resolve_incident(
    incident_id: int,
    payload: AdminIncidentResolveIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin marks an incident as resolved."""

    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    await require_admin_user(db, user_id)

    incident = await db.get(IncidentReport, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident.status = (payload.status or "resolved").strip().lower()
    incident.updated_at = datetime.now(timezone.utc)

    errand = await db.get(Errand, incident.errand_id)
    previous_status = errand.status if errand else None
    released_to_admin = False

    if errand and payload.release_errand:
        errand.issue_status = "approved"
        errand.issue_notes = incident.description or errand.issue_notes
        errand.issue_reason = incident.incident_type or errand.issue_reason
        errand.issue_reported_at = errand.issue_reported_at or incident.created_at
        errand.pilot_id = None
        errand.assigned_to = None
        errand.assigned_at = None
        errand.started_at = None
        errand.tracking_paused = False
        errand.status = "submitted"
        released_to_admin = True

        db.add(
            IncidentMessage(
                incident_id=incident.id,
                sender_type="admin",
                message="Approved by ErrandBridge Support. Errand released back to the admin dashboard for reassignment.",
            )
        )

    await db.commit()

    if errand and released_to_admin:
        try:
            await notify_admin_status(
                db,
                errand=errand,
                old_status=previous_status,
                new_status=errand.status,
                trigger="incident-approved-release",
                message="Incident approved. Errand returned to the admin dashboard for reassignment.",
                include_tracking=True,
            )
            await notify_pilot_status(
                db,
                errand=errand,
                new_status="submitted",
                trigger="incident-approved-release",
            )
        except Exception:
            pass

    return {
        "success": True,
        "status": incident.status,
        "released_to_admin": released_to_admin,
        "errand_status": errand.status if errand else None,
        "errand_id": incident.errand_id,
    }


@router.get("/errand/{errand_id}", response_model=dict)
async def list_incidents_for_errand(
    errand_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin view of incidents for a specific errand."""

    user = None
    token = _extract_bearer(authorization)
    if token:
        user_id = decode_access_token(token)
        if user_id:
            user = await db.get(User, user_id)

    if not user:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    if not user.email:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        await require_admin_user(db, user.id)
    except HTTPException:
        if not await db.scalar(
            select(Errand).where(Errand.id == errand_id, Errand.user_id == user.id)
        ):
            raise

    incidents = await db.execute(
        select(IncidentReport)
        .where(IncidentReport.errand_id == errand_id)
        .order_by(desc(IncidentReport.created_at))
    )

    return {
        "incidents": [
            {
                "id": incident.id,
                "errand_id": incident.errand_id,
                "pilot_id": incident.pilot_id,
                "incident_type": incident.incident_type,
                "description": incident.description,
                "status": incident.status,
                "detected_by": incident.detected_by,
                "created_at": (
                    incident.created_at.isoformat() if incident.created_at else None
                ),
                "updated_at": (
                    incident.updated_at.isoformat() if incident.updated_at else None
                ),
            }
            for incident in incidents.scalars().all()
        ]
    }


@router.get("/{incident_id}/messages", response_model=dict)
async def list_incident_messages(
    incident_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin view of incident conversation thread."""

    user = None
    token = _extract_bearer(authorization)
    if token:
        user_id = decode_access_token(token)
        if user_id:
            user = await db.get(User, user_id)

    if not user:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        await require_admin_user(db, user.id)
    except HTTPException:
        incident = await db.get(IncidentReport, incident_id)
        if not incident or int(incident.pilot_id or 0) != int(user.id):
            raise

    messages = await db.execute(
        select(IncidentMessage)
        .where(IncidentMessage.incident_id == incident_id)
        .order_by(IncidentMessage.created_at.asc())
    )

    return {
        "messages": [
            {
                "id": msg.id,
                "incident_id": msg.incident_id,
                "sender_type": msg.sender_type,
                "message": msg.message,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages.scalars().all()
        ]
    }
