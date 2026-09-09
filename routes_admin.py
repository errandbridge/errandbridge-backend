from __future__ import annotations
import uuid

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, delete, func, update, or_, distinct
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from fastapi.responses import FileResponse, RedirectResponse
import os
import pathlib

from app.utils.admin_utils import (
    require_admin_user,
    admin_emails,
    is_elevated_admin_email,
)
from app.dto import (
    AdminDeleteErrandResponse,
    AdminErrandStatusUpdateResponse,
    AdminAssignPilotResponse,
    AdminPilotDispatchStatusResponse,
    AdminPilotDocumentReviewResponse,
    AdminReviewAttachmentResponse,
    AdminCustomersByCountryResponse,
    AdminUnverifiedCustomersResponse,
    AdminPurgeUnverifiedCustomersResponse,
    FlexibleId,
    AdminMetricsOverviewResponse,
    AdminPilotDocumentItem,
    AdminPilotEmploymentApplicationItem,
    AdminVoiceCallItem,
    AdminVoiceCallEventItem,
    AdminCustomerListItem,
    AdminCustomerStatsResponse,
)
from auth import decode_access_token
from database import get_db
from models import (
    Errand,
    ErrandAttachment,
    ErrandMessage,
    User,
    AttachmentShareLink,
    ErrandEvent,
    PromoCode,
    PilotDocument,
    PilotLocation,
    IncidentReport,
    IncidentMessage,
    SupportConversation,
    SupportMessage,
    AnalyticsVisit,
    VoiceCallSession,
    VoiceCallEvent,
    PilotEmploymentApplication,
    PilotEmploymentAttachment,
)

from app.services.storage import (
    get_storage_config,
    presign_or_stream_key,
    s3_key,
    delete_object_if_exists,
)
from app.services.ml_client import score_issue
from app.utils.notification_utils import (
    notify_customer_status,
    notify_pilot_status,
    notify_admin_status,
    notify_pilot_document_review,
)
from app.services.emailer import send_email
import hashlib
import secrets
from app.metrics.metrics_admin import update_admin_metrics
import json
from fastapi.responses import JSONResponse
import hmac

from app.services.promo_code_service import issue_promo_code, format_display_code
from app.pilot_dispatch import (
    ADMIN_DISPATCH_DISABLED,
    ADMIN_DISPATCH_ENABLED,
    ADMIN_DISPATCH_PERMANENTLY_DISABLED,
    serialize_pilot_dispatch_state,
    set_admin_dispatch_status,
)
from app.pilot_dispatch_policy import (
    get_pilot_dispatch_policy_state,
    normalize_open_pool_radius_miles,
    normalize_show_all_jobs_to_pilots,
    update_pilot_dispatch_policy,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_DEFAULT_UPLOAD_DIR = pathlib.Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR = pathlib.Path(os.getenv("UPLOAD_DIR", str(_DEFAULT_UPLOAD_DIR)))


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def _require_admin(
    db: AsyncSession,
    authorization: Optional[str],
) -> User:
    token = _extract_bearer(authorization)
    user_id = decode_access_token(token) if token else None
    return await require_admin_user(db, user_id)


def _can_delete_other_admin_accounts(actor: User) -> bool:
    """Only elevated admins may delete other configured admin accounts."""
    return is_elevated_admin_email(getattr(actor, "email", None))


class AdminUserOut(BaseModel):
    id: FlexibleId
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    is_email_verified: bool
    created_at: Optional[datetime] = None


class AdminErrandOut(BaseModel):
    id: FlexibleId
    reference_number: Optional[str] = None
    title: str
    description: Optional[str] = None
    note: Optional[str] = None
    pickup_location: Optional[str] = None
    dropoff_location: Optional[str] = None
    status: str
    pilot_id: Optional[FlexibleId] = None
    # Admin-only disclosure: admins can see full customer info + timestamps.
    user_id: Optional[FlexibleId] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    created_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    confirmation_sent_at: Optional[int] = None

    # Helpful operational fields (best-effort; may be null in older rows)
    amount: Optional[float] = None
    distance_km: Optional[float] = None
    sensitivity: Optional[str] = None


class AdminErrandChatOut(BaseModel):
    errand_id: FlexibleId
    reference_number: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None

    user_id: Optional[FlexibleId] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None

    pilot_id: Optional[FlexibleId] = None
    pilot_name: Optional[str] = None
    pilot_email: Optional[str] = None
    pilot_phone: Optional[str] = None

    message_count: int
    last_message_at: Optional[datetime] = None
    last_message: Optional[str] = None
    last_sender_id: Optional[uuid.UUID] = None


class AdminResetVisitsPayload(BaseModel):
    password: str


class AdminPilotDocumentReviewIn(BaseModel):
    action: str
    note: Optional[str] = None


class AdminIssueOut(BaseModel):
    errand_id: FlexibleId
    reference_number: Optional[str] = None
    errand_status: str
    user_id: Optional[FlexibleId] = None
    created_at: Optional[datetime] = None

    issue_reason: Optional[str] = None
    issue_notes: Optional[str] = None
    issue_reported_at: Optional[datetime] = None
    issue_preferred_resolution: Optional[str] = None
    issue_status: Optional[str] = None
    issue_resolved_at: Optional[datetime] = None
    issue_resolution_notes: Optional[str] = None
    issue_evidence_attachment_ids: Optional[str] = None

    # Optional ML enrichment (present only when ML_ENABLED=true and scoring succeeds)
    ml_priority: Optional[int] = None
    ml_tags: Optional[list[str]] = None
    ml_reasons: Optional[list[str]] = None
    ml_policy_version: Optional[str] = None


class AdminDeleteUserOut(BaseModel):
    deleted: bool
    user_id: FlexibleId
    email: Optional[str] = None


class AdminBulkDeleteUsersIn(BaseModel):
    user_ids: list[int]


class AdminBulkDeleteUsersOut(BaseModel):
    requested: int
    deleted: int
    deleted_user_ids: list[int] = []
    skipped_self: bool = False
    skipped_admins: list[str] = []
    skipped_user_ids: list[int] = []
    failed_user_ids: list[int] = []
    not_found: list[int] = []


async def _cascade_delete_user_data(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, list[str]]:
    """Best-effort removal of rows that can block deleting a user.

    Returns:
        {"stored_filenames": [...]} filenames that should be deleted from object storage.
    """

    stored_filenames: list[str] = []

    # Support conversations/messages can reference users.id via FK.
    convo_ids = (
        (
            await db.execute(
                select(SupportConversation.id).where(
                    SupportConversation.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    if convo_ids:
        await db.execute(
            delete(SupportMessage).where(SupportMessage.conversation_id.in_(convo_ids))
        )
        await db.execute(
            delete(SupportConversation).where(SupportConversation.id.in_(convo_ids))
        )

    # Pilot documents reference users.id via FK (non-nullable).
    pilot_docs = (
        (
            await db.execute(
                select(PilotDocument.stored_filename).where(
                    PilotDocument.pilot_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    stored_filenames.extend([name for name in pilot_docs if name])
    await db.execute(delete(PilotDocument).where(PilotDocument.pilot_id == user_id))

    # Pilot locations reference users.id via FK.
    await db.execute(delete(PilotLocation).where(PilotLocation.pilot_id == user_id))

    # Incident reports reference users.id via FK (nullable); keep the incident but detach the pilot.
    await db.execute(
        update(IncidentReport)
        .where(IncidentReport.pilot_id == user_id)
        .values(pilot_id=None)
    )

    # Cleanup the user's errands and errand-owned children (not required for FK safety,
    # but keeps test account purges complete).
    errand_ids = (
        (await db.execute(select(Errand.id).where(Errand.user_id == user_id)))
        .scalars()
        .all()
    )

    if errand_ids:
        # Incidents for those errands.
        incident_ids = (
            (
                await db.execute(
                    select(IncidentReport.id).where(
                        IncidentReport.errand_id.in_(errand_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        if incident_ids:
            await db.execute(
                delete(IncidentMessage).where(
                    IncidentMessage.incident_id.in_(incident_ids)
                )
            )
            await db.execute(
                delete(IncidentReport).where(IncidentReport.id.in_(incident_ids))
            )

        # Pilot location entries for those errands.
        await db.execute(
            delete(PilotLocation).where(PilotLocation.errand_id.in_(errand_ids))
        )

        # Attachments + share links.
        attachment_rows = (
            await db.execute(
                select(ErrandAttachment.id, ErrandAttachment.stored_filename).where(
                    ErrandAttachment.errand_id.in_(errand_ids)
                )
            )
        ).all()
        attachment_ids: list[int] = []
        for attachment_id, stored_name in attachment_rows:
            if attachment_id is not None:
                attachment_ids.append(int(attachment_id))
            if stored_name:
                stored_filenames.append(stored_name)

        if attachment_ids:
            await db.execute(
                delete(AttachmentShareLink).where(
                    AttachmentShareLink.attachment_id.in_(attachment_ids)
                )
            )

        await db.execute(
            delete(ErrandEvent).where(ErrandEvent.errand_id.in_(errand_ids))
        )
        await db.execute(
            delete(ErrandAttachment).where(ErrandAttachment.errand_id.in_(errand_ids))
        )

        # Voice call events/sessions (FK exists from events -> sessions).
        session_ids = (
            (
                await db.execute(
                    select(VoiceCallSession.id).where(
                        VoiceCallSession.errand_id.in_(errand_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        if session_ids:
            await db.execute(
                delete(VoiceCallEvent).where(VoiceCallEvent.session_id.in_(session_ids))
            )
            await db.execute(
                delete(VoiceCallSession).where(VoiceCallSession.id.in_(session_ids))
            )

        await db.execute(delete(Errand).where(Errand.id.in_(errand_ids)))

    # Attachment share links created by this user (no FK, but good hygiene).
    await db.execute(
        delete(AttachmentShareLink).where(
            AttachmentShareLink.created_by_user_id == user_id
        )
    )

    return {"stored_filenames": list({name for name in stored_filenames if name})}


class AdminIssueResolveIn(BaseModel):
    action: str  # resolve | reject | reopen
    notes: Optional[str] = None


class AdminAttachmentOut(BaseModel):
    id: uuid.UUID
    errand_id: uuid.UUID
    user_id: uuid.UUID
    reference_number: Optional[str] = None
    errand_title: Optional[str] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    original_filename: str
    stored_filename: str
    content_type: Optional[str] = None
    size_bytes: int
    label: Optional[str] = None
    review_status: str
    review_note: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by_user_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None


class AdminAttachmentReviewIn(BaseModel):
    action: str
    note: Optional[str] = None


class AdminErrandStatusUpdateIn(BaseModel):
    status: str
    note: Optional[str] = None


class AdminAssignPilotIn(BaseModel):
    pilot_id: uuid.UUID
    note: Optional[str] = None


class AdminPilotDispatchUpdateIn(BaseModel):
    action: str
    note: Optional[str] = None


class AdminPilotDispatchPolicyUpdateIn(BaseModel):
    show_all_jobs_to_pilots: Optional[bool] = None
    open_pool_radius_miles: Optional[int] = None


class AdminPilotDispatchPolicyOut(BaseModel):
    show_all_jobs_to_pilots: bool
    open_pool_radius_miles: int
    allowed_open_pool_radius_miles: list[int]
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[uuid.UUID] = None


class AdminPromoCodeGenerateIn(BaseModel):
    user_id: Optional[uuid.UUID] = None
    percent_off: int = 10
    max_redemptions: int = 1
    source: Optional[str] = None


class AdminPromoCodeOut(BaseModel):
    id: uuid.UUID
    code: str
    display_code: str
    percent_off: int
    user_id: Optional[uuid.UUID] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    created_by_admin_id: Optional[uuid.UUID] = None
    source: Optional[str] = None
    max_redemptions: int
    redeemed_count: int
    redeemed_at: Optional[datetime] = None
    redeemed_errand_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None


def _promo_to_admin_out(p: PromoCode, user: Optional[User] = None) -> AdminPromoCodeOut:
    user_email = user.email if user else None
    user_name = None
    if user:
        user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or None
    return AdminPromoCodeOut(
        id=p.id,
        code=p.code,
        display_code=format_display_code(p.code),
        percent_off=int(p.percent_off or 0),
        user_id=p.user_id,
        user_email=user_email,
        user_name=user_name,
        created_by_admin_id=p.created_by_admin_id,
        source=p.source,
        max_redemptions=int(p.max_redemptions or 1),
        redeemed_count=int(p.redeemed_count or 0),
        redeemed_at=p.redeemed_at,
        redeemed_errand_id=p.redeemed_errand_id,
        created_at=p.created_at,
    )


@router.get("/promo-codes", response_model=list[AdminPromoCodeOut])
async def list_promo_codes(
    request: Request,
    user_id: Optional[uuid.UUID] = None,
    redeemed: Optional[bool] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List promo codes (admin-only)."""
    admin = await _require_admin(
        db, authorization or request.headers.get("authorization")
    )

    q = select(PromoCode, User).outerjoin(User, User.id == PromoCode.user_id)
    if user_id is not None:
        q = q.where(PromoCode.user_id == int(user_id))
    if redeemed is True:
        q = q.where(PromoCode.redeemed_count >= PromoCode.max_redemptions)
    elif redeemed is False:
        q = q.where(PromoCode.redeemed_count < PromoCode.max_redemptions)

    q = q.order_by(PromoCode.id.desc()).limit(300)
    res = await db.execute(q)
    rows = res.all()
    print(f"[admin] user_id={admin.id} action=list_promo_codes count={len(rows)}")
    return [_promo_to_admin_out(promo, user) for promo, user in rows]


@router.post("/promo-codes/generate", response_model=AdminPromoCodeOut)
async def generate_promo_code(
    payload: AdminPromoCodeGenerateIn,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Generate a promo code (admin-only)."""
    admin = await _require_admin(
        db, authorization or request.headers.get("authorization")
    )

    user_id_value = payload.user_id
    if user_id_value is not None:
        target = await db.get(User, int(user_id_value))
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
    else:
        target = None

    try:
        promo = await issue_promo_code(
            db,
            user_id=int(user_id_value) if user_id_value is not None else None,
            percent_off=int(payload.percent_off or 10),
            max_redemptions=int(payload.max_redemptions or 1),
            created_by_admin_id=int(admin.id),
            source=(payload.source or "admin_manual"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    print(
        f"[admin] user_id={admin.id} action=generate_promo_code promo_id={promo.id} user_id={promo.user_id} percent_off={promo.percent_off}"
    )
    return _promo_to_admin_out(promo, target)


@router.get("/users", response_model=list[AdminUserOut], operation_id="listAdminUsers", summary="List user accounts", description="Administrative list of all user accounts.")
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Accept standard Authorization header
    # Robust header extraction: case-insensitive
    authorization = request.headers.get("authorization")
    if not authorization:
        # Try alternate casing (some ASGI servers use 'Authorization')
        authorization = request.headers.get("Authorization")
    if not authorization:
        # Try all headers (case-insensitive search)
        for k, v in request.headers.items():
            if k.lower() == "authorization":
                authorization = v
                break
    admin = await _require_admin(db, authorization)

    res = await db.execute(select(User).order_by(User.id.desc()))
    users = res.scalars().all()

    print(f"[admin] user_id={admin.id} action=list_users count={len(users)}")

    return [
        AdminUserOut(
            id=u.id,
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            phone=u.phone,
            is_email_verified=bool(u.is_email_verified),
            created_at=u.created_at,
        )
        for u in users
    ]


@router.delete("/users/{user_id}", response_model=AdminDeleteUserOut, operation_id="deleteAdminUser", summary="Delete user account", description="Permanently delete a user account with safety guards.")
async def delete_user(
    user_id: FlexibleId,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a user account by id.

    Safety:
    - Requires admin.
    - Prevents deleting the currently authenticated admin user.
    - Prevents deleting other admin accounts unless the actor is an elevated admin.
    """

    authorization = request.headers.get("authorization") or request.headers.get(
        "Authorization"
    )
    if not authorization:
        for k, v in request.headers.items():
            if k.lower() == "authorization":
                authorization = v
                break

    admin = await _require_admin(db, authorization)

    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if str(user_id) == str(admin.id):
        raise HTTPException(
            status_code=400,
            detail="You cannot delete the currently authenticated admin user.",
        )

    target_is_admin = (target.email or "").strip().lower() in admin_emails()
    if target_is_admin and not _can_delete_other_admin_accounts(admin):
        raise HTTPException(
            status_code=403,
            detail="Only elevated admins can delete another admin account.",
        )

    # Capture email before deletion for UI.
    target_email = target.email

    try:
        cascade_result = await _cascade_delete_user_data(db, int(user_id))
        await db.delete(target)
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        print(
            f"[admin] user_id={admin.id} action=delete_user_failed target_user_id={user_id} reason=integrity_error {str(e)}"
        )
        raise HTTPException(
            status_code=409,
            detail="Cannot delete user due to related records. Try bulk delete again or contact support.",
        ) from e
    except Exception as e:
        await db.rollback()
        print(
            f"[admin] user_id={admin.id} action=delete_user_failed target_user_id={user_id} reason=exception {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to delete user: {str(e)}"
        ) from e

    # Best-effort object storage cleanup (S3 only).
    for stored_name in cascade_result.get("stored_filenames", []):
        delete_object_if_exists(stored_name)

    print(f"[admin] user_id={admin.id} action=delete_user target_user_id={user_id}")

    return AdminDeleteUserOut(deleted=True, user_id=user_id, email=target_email)


@router.options("/users/{user_id}", include_in_schema=False)
async def options_delete_user(user_id: uuid.UUID):
    # Let the global CORS middleware (if enabled) answer preflight cleanly.
    # Explicit route avoids 405 in setups where middleware isn't catching OPTIONS.
    return Response(status_code=200)


@router.post("/users/bulk-delete", response_model=AdminBulkDeleteUsersOut)
async def bulk_delete_users(
    payload: AdminBulkDeleteUsersIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Bulk delete users by id.

    Safety:
    - Requires admin.
    - Skips deleting the current admin user.
    - Skips deleting admin accounts unless the actor is an elevated admin.
    """

    authorization = request.headers.get("authorization") or request.headers.get(
        "Authorization"
    )
    if not authorization:
        for k, v in request.headers.items():
            if k.lower() == "authorization":
                authorization = v
                break

    admin = await _require_admin(db, authorization)

    raw_ids = payload.user_ids or []
    # Normalize + de-duplicate
    requested_ids: list[int] = []
    seen: set[int] = set()
    for v in raw_ids:
        try:
            i = int(v)
        except Exception:
            continue
        if i <= 0 or i in seen:
            continue
        seen.add(i)
        requested_ids.append(i)

    if not requested_ids:
        return AdminBulkDeleteUsersOut(requested=0, deleted=0)

    # Fetch targets
    res = await db.execute(select(User).where(User.id.in_(requested_ids)))
    targets = res.scalars().all()
    targets_by_id = {int(u.id): u for u in targets}

    not_found = [i for i in requested_ids if i not in targets_by_id]

    admin_email_set = admin_emails()
    skipped_admin_emails: list[str] = []
    skipped_self = False
    can_delete_admins = _can_delete_other_admin_accounts(admin)

    skipped_user_ids: list[int] = []

    deletable_ids: list[int] = []
    for i in requested_ids:
        u = targets_by_id.get(i)
        if not u:
            continue
        if int(i) == int(admin.id):
            skipped_self = True
            skipped_user_ids.append(int(i))
            continue
        email_norm = (u.email or "").strip().lower()
        if email_norm and email_norm in admin_email_set and not can_delete_admins:
            skipped_admin_emails.append(email_norm)
            skipped_user_ids.append(int(i))
            continue
        deletable_ids.append(i)

    deleted_user_ids: list[int] = []
    failed_user_ids: list[int] = []
    stored_filenames_to_delete: set[str] = set()
    if deletable_ids:
        # Delete one-by-one with savepoints so a single FK/integrity failure does not
        # poison the entire bulk request, while still paying for only one outer commit.
        for target_id in deletable_ids:
            try:
                async with db.begin_nested():
                    user = await db.get(User, int(target_id))
                    if not user:
                        continue
                    cascade_result = await _cascade_delete_user_data(db, int(target_id))
                    await db.delete(user)
                deleted_user_ids.append(int(target_id))
                for stored_name in cascade_result.get("stored_filenames", []):
                    if stored_name:
                        stored_filenames_to_delete.add(stored_name)
            except IntegrityError:
                await db.rollback()
                # Keep going; one problematic record shouldn't block the rest.
                print(
                    f"[admin] user_id={admin.id} action=bulk_delete_user_failed target_user_id={target_id} reason=integrity_error"
                )
                failed_user_ids.append(int(target_id))
                continue
            except Exception:
                await db.rollback()
                print(
                    f"[admin] user_id={admin.id} action=bulk_delete_user_failed target_user_id={target_id} reason=exception"
                )
                failed_user_ids.append(int(target_id))
                continue

        if deleted_user_ids:
            await db.commit()

    for stored_name in sorted(stored_filenames_to_delete):
        delete_object_if_exists(stored_name)

    deleted_count = len(deleted_user_ids)

    print(
        f"[admin] user_id={admin.id} action=bulk_delete_users requested={len(requested_ids)} deleted={deleted_count}"
    )

    return AdminBulkDeleteUsersOut(
        requested=len(requested_ids),
        deleted=deleted_count,
        deleted_user_ids=deleted_user_ids,
        skipped_self=skipped_self,
        skipped_admins=sorted(set(skipped_admin_emails)),
        skipped_user_ids=sorted(set(skipped_user_ids)),
        failed_user_ids=sorted(set(failed_user_ids)),
        not_found=not_found,
    )


@router.options("/users/bulk-delete", include_in_schema=False)
async def options_bulk_delete_users():
    return Response(status_code=200)


@router.get("/errands", response_model=list[AdminErrandOut], operation_id="listAdminErrands", summary="List admin errands", description="Platform-wide administrative errand index with filters.")
async def list_errands(
    request: Request,
    user_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    # Accept standard Authorization header
    authorization = request.headers.get("authorization")
    admin = await _require_admin(db, authorization)

    q = select(Errand, User).join(User, cast(User.id, String) == cast(Errand.user_id, String))
    if user_id is not None:
        q = q.where(Errand.user_id == user_id)
    if status is not None:
        q = q.where(Errand.status == status)

    q = q.order_by(Errand.created_at.desc())

    res = await db.execute(q)
    rows = res.all()

    print(
        f"[admin] user_id={admin.id} action=list_errands count={len(rows)} user_id_filter={user_id} status_filter={status}"
    )

    return [
        AdminErrandOut(
            id=errand.id,
            reference_number=getattr(errand, "reference_number", None),
            title=errand.title,
            description=errand.description,
            note=getattr(errand, "note", None),
            pickup_location=errand.pickup_location,
            dropoff_location=errand.dropoff_location,
            status=errand.status,
            pilot_id=getattr(errand, "pilot_id", None),
            assigned_at=getattr(errand, "assigned_at", None),
            user_id=errand.user_id,
            customer_name=f"{user.first_name or ''} {user.last_name or ''}".strip()
            or user.email,
            customer_email=user.email,
            customer_phone=user.phone,
            created_at=errand.created_at,
            confirmation_sent_at=getattr(errand, "confirmation_sent_at", None),
            amount=getattr(errand, "amount", None),
            distance_km=getattr(errand, "distance_km", None),
            sensitivity=getattr(errand, "sensitivity", None),
        )
        for errand, user in rows
    ]


@router.get("/errand-chats", response_model=list[AdminErrandChatOut], operation_id="listAdminErrandChats", summary="List errand chats", description="List recent chat threads across errands.")
async def list_errand_chats(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    """Admin conversation report: one row per errand with at least one message."""

    authorization = request.headers.get("authorization")
    admin = await _require_admin(db, authorization)

    safe_limit = max(1, min(int(limit or 200), 500))

    customer = aliased(User)
    pilot = aliased(User)

    # Aggregate message counts + last timestamp.
    agg_subq = (
        select(
            ErrandMessage.errand_id.label("errand_id"),
            func.count(ErrandMessage.id).label("message_count"),
            func.max(ErrandMessage.created_at).label("last_message_at"),
        )
        .group_by(ErrandMessage.errand_id)
        .subquery()
    )

    # Pick last message per errand via window function.
    ranked_last = select(
        ErrandMessage.errand_id.label("errand_id"),
        ErrandMessage.message.label("message"),
        ErrandMessage.sender_id.label("sender_id"),
        ErrandMessage.created_at.label("created_at"),
        func.row_number()
        .over(
            partition_by=ErrandMessage.errand_id,
            order_by=(ErrandMessage.created_at.desc(), ErrandMessage.id.desc()),
        )
        .label("rn"),
    ).subquery()
    last_subq = (
        select(
            ranked_last.c.errand_id,
            ranked_last.c.message,
            ranked_last.c.sender_id,
            ranked_last.c.created_at,
        )
        .where(ranked_last.c.rn == 1)
        .subquery()
    )

    query = (
        select(
            Errand,
            customer,
            pilot,
            agg_subq.c.message_count,
            agg_subq.c.last_message_at,
            last_subq.c.message,
            last_subq.c.sender_id,
        )
        .join(agg_subq, agg_subq.c.errand_id == Errand.id)
        .outerjoin(last_subq, last_subq.c.errand_id == Errand.id)
        .join(customer, customer.id == Errand.user_id)
        .outerjoin(pilot, pilot.id == Errand.pilot_id)
    )

    if status:
        query = query.where(Errand.status == status)

    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                Errand.reference_number.ilike(needle),
                customer.email.ilike(needle),
                customer.first_name.ilike(needle),
                customer.last_name.ilike(needle),
                pilot.email.ilike(needle),
                pilot.first_name.ilike(needle),
                pilot.last_name.ilike(needle),
            )
        )

    query = query.order_by(agg_subq.c.last_message_at.desc(), Errand.id.desc()).limit(
        safe_limit
    )

    res = await db.execute(query)
    rows = res.all()

    print(
        f"[admin] user_id={admin.id} action=list_errand_chats count={len(rows)} q={q!r} status_filter={status!r} limit={safe_limit}"
    )

    out: list[AdminErrandChatOut] = []
    for (
        errand,
        cust,
        pil,
        message_count,
        last_message_at,
        last_message,
        last_sender_id,
    ) in rows:
        cust_name = (
            f"{cust.first_name or ''} {cust.last_name or ''}".strip() or cust.email
        )
        pil_name = None
        if pil:
            pil_name = (
                f"{pil.first_name or ''} {pil.last_name or ''}".strip() or pil.email
            )

        out.append(
            AdminErrandChatOut(
                errand_id=int(errand.id),
                reference_number=getattr(errand, "reference_number", None),
                status=errand.status,
                created_at=getattr(errand, "created_at", None),
                user_id=getattr(errand, "user_id", None),
                customer_name=cust_name,
                customer_email=cust.email,
                customer_phone=cust.phone,
                pilot_id=getattr(errand, "pilot_id", None),
                pilot_name=pil_name,
                pilot_email=getattr(pil, "email", None) if pil else None,
                pilot_phone=getattr(pil, "phone", None) if pil else None,
                message_count=int(message_count or 0),
                last_message_at=last_message_at,
                last_message=last_message,
                last_sender_id=(
                    int(last_sender_id) if last_sender_id is not None else None
                ),
            )
        )

    return out


@router.get("/errands/{errand_id}", response_model=AdminErrandOut, operation_id="getAdminErrandDetail", summary="Get admin errand detail", description="Detailed administrative errand inspection.")
async def get_errand_detail(
    errand_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single errand with customer info for admin detail views."""

    authorization = request.headers.get("authorization")
    admin = await _require_admin(db, authorization)

    res = await db.execute(
        select(Errand, User)
        .join(User, cast(User.id, String) == cast(Errand.user_id, String))
        .where(Errand.id == errand_id)
        .limit(1)
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=404, detail="Errand not found")

    errand, user = row
    print(f"[admin] user_id={admin.id} action=get_errand_detail errand_id={errand_id}")

    return AdminErrandOut(
        id=errand.id,
        reference_number=getattr(errand, "reference_number", None),
        title=errand.title,
        description=errand.description,
        note=getattr(errand, "note", None),
        pickup_location=errand.pickup_location,
        dropoff_location=errand.dropoff_location,
        status=errand.status,
        pilot_id=getattr(errand, "pilot_id", None),
        assigned_at=getattr(errand, "assigned_at", None),
        user_id=errand.user_id,
        customer_name=f"{user.first_name or ''} {user.last_name or ''}".strip()
        or user.email,
        customer_email=user.email,
        customer_phone=user.phone,
        created_at=errand.created_at,
        confirmation_sent_at=getattr(errand, "confirmation_sent_at", None),
        amount=getattr(errand, "amount", None),
        distance_km=getattr(errand, "distance_km", None),
        sensitivity=getattr(errand, "sensitivity", None),
    )


@router.get("/attachments", response_model=list[AdminAttachmentOut], operation_id="listAdminAttachments", summary="List admin attachments", description="Administrative listing of all user and errand attachments.")
async def list_attachments(
    authorization: Optional[str] = Header(default=None),
    errand_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin(db, authorization)

    # Join through errands and users so admin tools can group files by owner
    # without forcing operators to reverse-lookup raw errand ids.
    q = (
        select(ErrandAttachment, Errand, User)
        .join(Errand, Errand.id == ErrandAttachment.errand_id)
        .join(User, cast(User.id, String) == cast(Errand.user_id, String))
        .order_by(ErrandAttachment.id.desc())
    )

    if errand_id is not None:
        q = q.where(ErrandAttachment.errand_id == errand_id)
    if user_id is not None:
        q = q.where(Errand.user_id == user_id)

    res = await db.execute(q)
    rows = res.all()

    print(
        f"[admin] user_id={admin.id} action=list_attachments count={len(rows)} errand_id_filter={errand_id} user_id_filter={user_id}"
    )

    out: list[AdminAttachmentOut] = []
    for attachment, errand, owner in rows:
        owner_name = f"{owner.first_name or ''} {owner.last_name or ''}".strip() or None
        out.append(
            AdminAttachmentOut(
                id=attachment.id,
                errand_id=attachment.errand_id,
                user_id=int(errand.user_id),
                reference_number=getattr(errand, "reference_number", None),
                errand_title=getattr(errand, "title", None),
                owner_name=owner_name or getattr(owner, "email", None),
                owner_email=getattr(owner, "email", None),
                original_filename=attachment.original_filename,
                stored_filename=attachment.stored_filename,
                content_type=attachment.content_type,
                size_bytes=int(attachment.size_bytes or 0),
                label=getattr(attachment, "label", None),
                review_status=str(
                    getattr(attachment, "review_status", "pending") or "pending"
                ),
                review_note=getattr(attachment, "review_note", None),
                reviewed_at=getattr(attachment, "reviewed_at", None),
                reviewed_by_user_id=getattr(attachment, "reviewed_by_user_id", None),
                created_at=attachment.created_at,
            )
        )
    return out


@router.post(
    "/attachments/{attachment_id}/review",
    response_model=AdminReviewAttachmentResponse,
    operation_id="reviewAdminAttachment",
    summary="Review errand attachment",
    description="Approve or reject an errand verification attachment.",
)
async def review_attachment(
    attachment_id: int,
    payload: AdminAttachmentReviewIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin marks an attachment as approved/rejected and optionally leaves a note."""

    admin = await _require_admin(db, authorization)

    action = (payload.action or "").strip().lower()
    if action not in {"approve", "reject"}:
        raise HTTPException(
            status_code=400, detail="Invalid action; expected 'approve' or 'reject'"
        )

    attachment = await db.get(ErrandAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    attachment.review_status = "approved" if action == "approve" else "rejected"
    attachment.review_note = (payload.note or "").strip() or None
    attachment.reviewed_at = datetime.utcnow()
    attachment.reviewed_by_user_id = int(admin.id)

    # Record errand history entry so clients/pilots can surface in-app activity updates.
    try:
        errand = await db.get(Errand, attachment.errand_id)
    except Exception:
        errand = None

    if errand:
        note_parts = [
            f"Attachment {action}d",
            (
                f"file={attachment.original_filename}"
                if attachment.original_filename
                else None
            ),
            f"note={attachment.review_note}" if attachment.review_note else None,
        ]
        db.add(
            ErrandEvent(
                errand_id=int(errand.id),
                event_type=(
                    "admin_attachment_approved"
                    if attachment.review_status == "approved"
                    else "admin_attachment_rejected"
                ),
                old_status=getattr(errand, "status", None),
                new_status=getattr(errand, "status", None),
                note=" | ".join([p for p in note_parts if p])[:2000],
                user_id=int(admin.id),
            )
        )

    await db.commit()
    await db.refresh(attachment)

    if attachment.review_status == "approved":
        try:
            errand = await db.get(Errand, attachment.errand_id)
            owner_user = await db.get(User, int(errand.user_id)) if errand else None
            if owner_user and owner_user.email:
                share_token = secrets.token_urlsafe(24)
                pin = secrets.token_urlsafe(4)
                token_hash = hashlib.sha256(share_token.encode("utf-8")).hexdigest()
                pin_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest()

                expires_at = datetime.utcnow() + timedelta(hours=72)

                link = AttachmentShareLink(
                    attachment_id=int(attachment.id),
                    token_hash=token_hash,
                    pin_hash=pin_hash,
                    expires_at=expires_at,
                    uses=0,
                    max_uses=10,
                    created_by_user_id=int(admin.id),
                )
                db.add(link)
                await db.commit()

                public_base = (
                    os.getenv("PUBLIC_API_URL") or "http://localhost:8001"
                ).rstrip("/")
                subject = f"Errand receipt approved: {attachment.original_filename}"
                body = (
                    "Your errand receipt has been verified by our admin team.\n\n"
                    f"Receipt: {attachment.original_filename}\n"
                    f"Download link: {public_base}/share/{share_token}/download?pin={pin}\n"
                    "\nThis link expires in 72 hours and may be used up to 10 times."
                )
                send_email(to_email=owner_user.email, subject=subject, body_text=body)

            if errand and errand.pilot_id:
                await notify_pilot_status(
                    db,
                    errand=errand,
                    new_status="receipt approved",
                    trigger="admin-attachment-approve",
                )
        except Exception as e:
            print(f"[notify] receipt approval email failed: {e}")

    print(
        f"[admin] user_id={admin.id} action=review_attachment attachment_id={attachment_id} review_status={attachment.review_status}"
    )

    return {
        "id": attachment.id,
        "reviewStatus": attachment.review_status,
        "reviewNote": attachment.review_note,
        "reviewedAt": (
            attachment.reviewed_at.isoformat() if attachment.reviewed_at else None
        ),
        "reviewedByUserId": attachment.reviewed_by_user_id,
    }


@router.post(
    "/errands/{errand_id}/status",
    response_model=AdminErrandStatusUpdateResponse,
    operation_id="updateAdminErrandStatus",
    summary="Update errand lifecycle status",
    description="Administratively advance or update the status of an errand.",
)
async def update_errand_status(
    errand_id: uuid.UUID,
    payload: AdminErrandStatusUpdateIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin updates an errand status (e.g., from 'assigned' to 'completed')."""

    admin = await _require_admin(db, authorization)

    new_status = (payload.status or "").strip().lower()
    valid_statuses = [
        "pending",
        "assigned",
        "picked_up",
        "delivered",
        "completed",
        "accepted",
        "cancelled",
    ]

    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Expected one of: {', '.join(valid_statuses)}",
        )

    errand = await db.get(Errand, errand_id)
    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")

    old_status = errand.status
    errand.status = new_status

    if new_status == "assigned":
        if errand.assigned_to is None:
            errand.assigned_to = admin.id
        if not errand.assigned_at:
            errand.assigned_at = datetime.now(timezone.utc)

    # Update timestamp
    errand.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(errand)

    try:
        await notify_customer_status(
            db,
            errand=errand,
            old_status=old_status,
            new_status=new_status,
            trigger="admin-status-update",
        )
        if new_status in {"accepted", "completed"}:
            await notify_pilot_status(
                db,
                errand=errand,
                new_status=new_status,
                trigger="admin-status-update",
            )
    except Exception as e:
        print(f"[notify] admin status update email failed: {e}")

    print(
        f"[admin] user_id={admin.id} action=update_errand_status errand_id={errand_id} old_status={old_status} new_status={new_status}"
    )

    return {
        "id": errand.id,
        "referenceNumber": errand.reference_number,
        "status": errand.status,
        "updatedAt": (
            errand.updated_at.isoformat()
            if hasattr(errand, "updated_at") and errand.updated_at
            else None
        ),
    }


@router.delete(
    "/errands/{errand_id}",
    response_model=AdminDeleteErrandResponse,
    operation_id="deleteAdminErrand",
    summary="Delete unstarted errand",
    description="Remove a pending or cancelled errand and cascading associations.",
)
async def delete_errand(
    errand_id: uuid.UUID,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin deletes an open errand and its related records."""

    admin = await _require_admin(db, authorization)

    errand = await db.get(Errand, errand_id)
    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")

    status_key = (errand.status or "").strip().lower()
    if status_key == "completed":
        raise HTTPException(
            status_code=400, detail="Completed errands cannot be deleted"
        )

    # Deleting active errands is risky and can break FK constraints while a pilot/client is still interacting.
    # Keep deletes to only truly-open states.
    deletable_statuses = {"pending", "submitted", "cancelled"}
    if status_key and status_key not in deletable_statuses:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Errand cannot be deleted while status is '{errand.status}'. "
                "Cancel it first if you need to remove it from the live queue."
            ),
        )

    attachments = (
        (
            await db.execute(
                select(ErrandAttachment).where(ErrandAttachment.errand_id == errand_id)
            )
        )
        .scalars()
        .all()
    )
    attachment_ids = [attachment.id for attachment in attachments]
    for attachment in attachments:
        delete_object_if_exists(attachment.stored_filename)

    if attachment_ids:
        await db.execute(
            delete(AttachmentShareLink).where(
                AttachmentShareLink.attachment_id.in_(attachment_ids)
            )
        )
    await db.execute(
        delete(ErrandAttachment).where(ErrandAttachment.errand_id == errand_id)
    )

    incident_reports = (
        (
            await db.execute(
                select(IncidentReport).where(IncidentReport.errand_id == errand_id)
            )
        )
        .scalars()
        .all()
    )
    incident_ids = [incident.id for incident in incident_reports]
    if incident_ids:
        await db.execute(
            delete(IncidentMessage).where(IncidentMessage.incident_id.in_(incident_ids))
        )
    await db.execute(
        delete(IncidentReport).where(IncidentReport.errand_id == errand_id)
    )

    await db.execute(delete(ErrandMessage).where(ErrandMessage.errand_id == errand_id))
    await db.execute(delete(ErrandEvent).where(ErrandEvent.errand_id == errand_id))
    await db.execute(delete(PilotLocation).where(PilotLocation.errand_id == errand_id))

    # Avoid FK constraint failures (nullable FK still restricts delete unless ON DELETE SET NULL).
    await db.execute(
        update(PromoCode)
        .where(PromoCode.redeemed_errand_id == errand_id)
        .values(redeemed_errand_id=None)
    )

    try:
        await db.delete(errand)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Errand could not be deleted because related records still exist.",
        )

    print(f"[admin] user_id={admin.id} action=delete_errand errand_id={errand_id}")

    return {"deleted": True, "id": errand_id}


@router.options("/errands/{errand_id}", include_in_schema=False)
async def options_delete_errand(errand_id: uuid.UUID):
    # Let the global CORS middleware (if enabled) answer preflight cleanly.
    # Explicit route avoids 405 in setups where middleware isn't catching OPTIONS.
    return Response(status_code=200)


@router.post(
    "/errands/{errand_id}/assign-pilot",
    response_model=AdminAssignPilotResponse,
    operation_id="assignAdminPilotToErrand",
    summary="Assign pilot to errand",
    description="Directly dispatch an eligible pilot to an active errand.",
)
async def assign_pilot_to_errand(
    errand_id: uuid.UUID,
    payload: AdminAssignPilotIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin assigns a pilot to an errand and notifies customer/pilot."""

    admin = await _require_admin(db, authorization)

    errand = await db.get(Errand, errand_id)
    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")

    if errand.status not in {"submitted", "pending"}:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot assign pilot for errand status {errand.status}",
        )

    pilot = await db.get(User, int(payload.pilot_id))
    if not pilot or not getattr(pilot, "is_pilot", False):
        raise HTTPException(status_code=400, detail="Pilot not found or not eligible")

    pilot_dispatch_state = serialize_pilot_dispatch_state(pilot)
    if pilot_dispatch_state["admin_dispatch_status"] != ADMIN_DISPATCH_ENABLED:
        raise HTTPException(
            status_code=409,
            detail=pilot_dispatch_state["dispatch_block_reason"]
            or "Pilot dispatch access is disabled.",
        )

    future_errand = await db.scalar(
        select(Errand)
        .where(Errand.pilot_id == pilot.id)
        .where(Errand.status == "assigned")
        .limit(1)
    )
    if future_errand:
        raise HTTPException(
            status_code=409,
            detail="Pilot already has a future errand assigned",
        )

    previous_status = errand.status
    errand.pilot_id = payload.pilot_id
    errand.status = "assigned"
    errand.assigned_to = admin.id
    errand.assigned_at = datetime.now(timezone.utc)

    if payload.note:
        errand.pilot_notes = payload.note

    db.add(
        ErrandEvent(
            errand_id=errand.id,
            event_type="admin_assign_pilot",
            old_status=previous_status,
            new_status=errand.status,
            note=payload.note,
            user_id=admin.id,
        )
    )

    await db.commit()
    await db.refresh(errand)

    try:
        await notify_customer_status(
            db,
            errand=errand,
            old_status=previous_status,
            new_status=errand.status,
            trigger="admin-assign-pilot",
        )
        await notify_pilot_status(
            db,
            errand=errand,
            new_status="assigned",
            trigger="admin-assign-pilot",
            pilot_user=pilot,
        )
        await notify_admin_status(
            db,
            errand=errand,
            old_status=previous_status,
            new_status=errand.status,
            trigger="admin-assign-pilot",
            message=f"Pilot {pilot.email} assigned by admin.",
        )
    except Exception as e:
        print(f"[notify] admin assign pilot email failed: {e}")

    return {
        "id": errand.id,
        "referenceNumber": errand.reference_number,
        "status": errand.status,
        "pilotId": errand.pilot_id,
        "assignedTo": errand.assigned_to,
        "assignedAt": errand.assigned_at.isoformat() if errand.assigned_at else None,
    }


@router.post(
    "/pilots/{pilot_id}/dispatch-status",
    response_model=AdminPilotDispatchStatusResponse,
    operation_id="updateAdminPilotDispatchStatus",
    summary="Modify pilot dispatch privileges",
    description="Enable, disable, or permanently restrict pilot access to open dispatches.",
)
async def update_pilot_dispatch_status(
    pilot_id: uuid.UUID,
    payload: AdminPilotDispatchUpdateIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin control for enabling, disabling, or permanently blocking pilot dispatch access."""

    admin = await _require_admin(db, authorization)
    pilot = await db.get(User, pilot_id)
    if not pilot or not getattr(pilot, "is_pilot", False):
        raise HTTPException(status_code=404, detail="Pilot not found")

    action = (payload.action or "").strip().lower().replace("-", "_")
    action_to_status = {
        "enable": ADMIN_DISPATCH_ENABLED,
        "enabled": ADMIN_DISPATCH_ENABLED,
        "disable": ADMIN_DISPATCH_DISABLED,
        "disabled": ADMIN_DISPATCH_DISABLED,
        "permanently_disable": ADMIN_DISPATCH_PERMANENTLY_DISABLED,
        "permanent_block": ADMIN_DISPATCH_PERMANENTLY_DISABLED,
        "permanently_disabled": ADMIN_DISPATCH_PERMANENTLY_DISABLED,
    }
    next_status = action_to_status.get(action)
    if not next_status:
        raise HTTPException(
            status_code=400,
            detail="Invalid action. Use enable, disable, or permanently_disable.",
        )

    state = set_admin_dispatch_status(
        pilot,
        next_status,
        actor_id=admin.id,
        note=payload.note,
        force_offline=True,
    )
    await db.commit()
    await db.refresh(pilot)

    return {
        "ok": True,
        "pilot_id": pilot.id,
        "first_name": pilot.first_name,
        "last_name": pilot.last_name,
        "email": pilot.email,
        **state,
    }


@router.get("/pilot-dispatch-policy", response_model=AdminPilotDispatchPolicyOut)
async def get_admin_pilot_dispatch_policy(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin-readable global pilot dispatch policy."""

    await _require_admin(db, authorization)
    state = await get_pilot_dispatch_policy_state(db)
    return AdminPilotDispatchPolicyOut(**state)


@router.put("/pilot-dispatch-policy", response_model=AdminPilotDispatchPolicyOut)
async def put_admin_pilot_dispatch_policy(
    payload: AdminPilotDispatchPolicyUpdateIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin updates global pilot dispatch visibility/radius policy."""

    admin = await _require_admin(db, authorization)

    if (
        payload.show_all_jobs_to_pilots is None
        and payload.open_pool_radius_miles is None
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide show_all_jobs_to_pilots and/or open_pool_radius_miles.",
        )

    if payload.open_pool_radius_miles is not None:
        normalized_radius = normalize_open_pool_radius_miles(
            payload.open_pool_radius_miles
        )
        if normalized_radius != int(payload.open_pool_radius_miles):
            raise HTTPException(
                status_code=400,
                detail="open_pool_radius_miles must be one of: 5, 10, 15, 20.",
            )

    state = await update_pilot_dispatch_policy(
        db,
        show_all_jobs_to_pilots=(
            normalize_show_all_jobs_to_pilots(payload.show_all_jobs_to_pilots)
            if payload.show_all_jobs_to_pilots is not None
            else None
        ),
        open_pool_radius_miles=payload.open_pool_radius_miles,
        actor_id=int(admin.id),
    )
    await db.commit()
    return AdminPilotDispatchPolicyOut(**state)


@router.get("/attachments/{attachment_id}/download")
async def admin_download_attachment(
    attachment_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only attachment download.

    This bypasses errand ownership checks so an admin can support customers.
    """

    admin = await _require_admin(db, authorization)

    attachment = await db.get(ErrandAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    errand = await db.get(Errand, attachment.errand_id)
    owner_user_id = int(errand.user_id) if errand else None

    print(
        f"[admin] user_id={admin.id} action=download_attachment attachment_id={attachment_id} errand_id={attachment.errand_id} owner_user_id={owner_user_id}"
    )

    cfg = get_storage_config()
    if cfg.driver == "s3":
        key = s3_key(cfg.s3_prefix, attachment.stored_filename)
        url = presign_or_stream_key(
            key=key,
            filename=attachment.original_filename,
            content_type=attachment.content_type,
            expires_seconds=120,
        )
        return RedirectResponse(url=url, status_code=302)

    path = UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on server")

    return FileResponse(
        path=str(path),
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@router.get("/pilot-documents", response_model=list[AdminPilotDocumentItem], operation_id="listAdminPilotDocuments", summary="List pilot compliance documents", description="Retrieve pilot driver licenses, IDs, and insurance filings.")
async def list_pilot_documents(
    authorization: Optional[str] = Header(default=None),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Admin list of pilot documents awaiting verification."""

    admin = await _require_admin(db, authorization)

    query = (
        select(PilotDocument, User)
        .join(User, User.id == PilotDocument.pilot_id)
        .order_by(PilotDocument.created_at.desc())
    )
    if status:
        query = query.where(PilotDocument.status == status)

    result = await db.execute(query)
    rows = result.all()

    print(
        f"[admin] user_id={admin.id} action=list_pilot_documents count={len(rows)} status_filter={status}"
    )

    return [
        {
            "id": doc.id,
            "pilot_id": doc.pilot_id,
            "pilot_name": f"{pilot.first_name or ''} {pilot.last_name or ''}".strip()
            or pilot.email,
            "pilot_email": pilot.email,
            "document_type": doc.document_type,
            "original_filename": doc.original_filename,
            "content_type": doc.content_type,
            "size_bytes": doc.size_bytes,
            "status": doc.status,
            "review_note": doc.review_note,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }
        for doc, pilot in rows
    ]


@router.get("/pilot-documents/{document_id}/download")
async def download_pilot_document(
    document_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only pilot document download."""

    admin = await _require_admin(db, authorization)
    document = await db.get(PilotDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    print(
        f"[admin] user_id={admin.id} action=download_pilot_document document_id={document_id}"
    )

    cfg = get_storage_config()
    if cfg.driver == "s3":
        key = s3_key(cfg.s3_prefix, document.stored_filename)
        url = presign_or_stream_key(
            key=key,
            filename=document.original_filename,
            content_type=document.content_type,
            expires_seconds=120,
        )
        return RedirectResponse(url=url, status_code=302)

    path = UPLOAD_DIR / document.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on server")

    return FileResponse(
        path=str(path),
        media_type=document.content_type or "application/octet-stream",
        filename=document.original_filename,
    )


@router.post(
    "/pilot-documents/{document_id}/review",
    response_model=AdminPilotDocumentReviewResponse,
    operation_id="reviewAdminPilotDocument",
    summary="Review pilot onboarding document",
    description="Approve or reject a submitted driver license or insurance document.",
)
async def review_pilot_document(
    document_id: int,
    payload: AdminPilotDocumentReviewIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin approves or rejects pilot documents."""

    admin = await _require_admin(db, authorization)
    document = await db.get(PilotDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    action = (payload.action or "").strip().lower()
    if action not in {"approve", "reject"}:
        raise HTTPException(
            status_code=400, detail="Invalid action; use approve or reject"
        )

    document.status = "approved" if action == "approve" else "rejected"
    document.review_note = payload.note
    document.reviewed_at = datetime.now(timezone.utc)
    document.reviewed_by_user_id = admin.id

    pilot = await db.get(User, document.pilot_id)
    if pilot:
        pilot.id_verification_status = "verified" if action == "approve" else "rejected"

    await db.commit()

    if pilot:
        try:
            await notify_pilot_document_review(
                db,
                pilot=pilot,
                document_type=document.document_type,
                status=document.status,
                note=document.review_note,
            )
        except Exception as exc:
            print(f"[admin] failed to notify pilot document decision: {exc}")

    return {"success": True, "status": document.status}


@router.get("/pilot-employment/applications", response_model=list[AdminPilotEmploymentApplicationItem], operation_id="listAdminPilotEmploymentApplications", summary="List pilot job applications", description="Retrieve submitted pilot onboarding applications and resumes.")
async def list_pilot_employment_applications(
    authorization: Optional[str] = Header(default=None),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Admin list of pilot employment applications."""

    admin = await _require_admin(db, authorization)

    query = select(PilotEmploymentApplication).order_by(
        PilotEmploymentApplication.created_at.desc()
    )
    if status:
        query = query.where(PilotEmploymentApplication.status == status)

    res = await db.execute(query)
    applications = res.scalars().all()
    app_ids = [app.id for app in applications]

    attachments_by_app: dict[int, list[PilotEmploymentAttachment]] = {}
    if app_ids:
        attachment_res = await db.execute(
            select(PilotEmploymentAttachment)
            .where(PilotEmploymentAttachment.application_id.in_(app_ids))
            .order_by(PilotEmploymentAttachment.created_at.desc())
        )
        for attachment in attachment_res.scalars().all():
            attachments_by_app.setdefault(attachment.application_id, []).append(
                attachment
            )

    print(
        f"[admin] user_id={admin.id} action=list_pilot_employment_applications count={len(applications)} status_filter={status}"
    )

    return [
        {
            "id": app.id,
            "first_name": app.first_name,
            "last_name": app.last_name,
            "email": app.email,
            "phone": app.phone,
            "city": app.city,
            "country": app.country,
            "experience": app.experience,
            "availability": app.availability,
            "notes": app.notes,
            "status": app.status,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "attachments": [
                {
                    "id": att.id,
                    "original_filename": att.original_filename,
                    "content_type": att.content_type,
                    "size_bytes": att.size_bytes,
                    "label": att.label,
                    "created_at": (
                        att.created_at.isoformat() if att.created_at else None
                    ),
                }
                for att in attachments_by_app.get(app.id, [])
            ],
        }
        for app in applications
    ]


@router.get("/pilot-employment/attachments/{attachment_id}/download")
async def download_pilot_employment_attachment(
    attachment_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only employment attachment download."""

    admin = await _require_admin(db, authorization)
    attachment = await db.get(PilotEmploymentAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    print(
        f"[admin] user_id={admin.id} action=download_pilot_employment_attachment attachment_id={attachment_id}"
    )

    cfg = get_storage_config()
    if cfg.driver == "s3":
        key = s3_key(cfg.s3_prefix, attachment.stored_filename)
        url = presign_or_stream_key(
            key=key,
            filename=attachment.original_filename,
            content_type=attachment.content_type,
            expires_seconds=120,
        )
        return RedirectResponse(url=url, status_code=302)

    path = UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on server")

    return FileResponse(
        path=str(path),
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@router.get("/availability-events", response_model=dict)
async def list_availability_events(
    authorization: Optional[str] = Header(default=None),
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Admin audit view of pilot availability confirmations/reminders."""

    admin = await _require_admin(db, authorization)

    limit_value = max(1, min(int(limit), 200))
    res = await db.execute(
        select(ErrandEvent, Errand, User)
        .join(Errand, Errand.id == ErrandEvent.errand_id)
        .join(User, cast(User.id, String) == cast(Errand.user_id, String))
        .where(
            ErrandEvent.event_type.in_(
                [
                    "pilot_availability_request",
                    "pilot_availability_yes",
                    "pilot_availability_no",
                    "pilot_reminder",
                ]
            )
        )
        .order_by(ErrandEvent.created_at.desc())
        .limit(limit_value)
    )

    rows = res.all()
    print(
        f"[admin] user_id={admin.id} action=list_availability_events count={len(rows)}"
    )

    payload = []
    for event, errand, customer in rows:
        payload.append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "created_at": (
                    event.created_at.isoformat() if event.created_at else None
                ),
                "note": event.note,
                "errand_id": errand.id,
                "errand_reference": errand.reference_number,
                "errand_title": errand.title,
                "errand_status": errand.status,
                "pilot_id": errand.pilot_id,
                "customer_name": f"{customer.first_name or ''} {customer.last_name or ''}".strip()
                or customer.email,
                "customer_email": customer.email,
            }
        )

    return {"events": payload}


@router.get("/issues", response_model=list[AdminIssueOut])
async def list_issues(
    authorization: Optional[str] = Header(default=None),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Admin queue for customer-reported issues/disputes."""

    admin = await _require_admin(db, authorization)

    status_filter = (status or "").strip().lower() or "open"

    q = (
        select(Errand)
        .where(Errand.issue_reported_at.isnot(None))
        .where(getattr(Errand, "issue_status", None) == status_filter)
    )
    q = q.order_by(Errand.issue_reported_at.desc(), Errand.id.desc())

    res = await db.execute(q)
    rows = res.scalars().all()

    print(
        f"[admin] user_id={admin.id} action=list_issues count={len(rows)} status_filter={status_filter}"
    )

    ml_payloads = [
        {
            "issueTitle": getattr(e, "issue_reason", None),
            "issueDescription": getattr(e, "issue_notes", None),
            "preferredResolution": getattr(e, "issue_preferred_resolution", None),
        }
        for e in rows
    ]
    ml_results = (
        await asyncio.gather(*(score_issue(payload) for payload in ml_payloads))
        if ml_payloads
        else []
    )

    out: list[AdminIssueOut] = []
    for e, ml in zip(rows, ml_results):

        out.append(
            AdminIssueOut(
                errand_id=e.id,
                reference_number=getattr(e, "reference_number", None),
                errand_status=e.status,
                user_id=e.user_id,
                created_at=e.created_at,
                issue_reason=getattr(e, "issue_reason", None),
                issue_notes=getattr(e, "issue_notes", None),
                issue_reported_at=getattr(e, "issue_reported_at", None),
                issue_preferred_resolution=getattr(
                    e, "issue_preferred_resolution", None
                ),
                issue_status=getattr(e, "issue_status", None),
                issue_resolved_at=getattr(e, "issue_resolved_at", None),
                issue_resolution_notes=getattr(e, "issue_resolution_notes", None),
                issue_evidence_attachment_ids=getattr(
                    e, "issue_evidence_attachment_ids", None
                ),
                ml_priority=(
                    int(ml.get("priority"))
                    if isinstance(ml, dict) and ml.get("priority") is not None
                    else None
                ),
                ml_tags=ml.get("tags") if isinstance(ml, dict) else None,
                ml_reasons=ml.get("reasons") if isinstance(ml, dict) else None,
                ml_policy_version=(
                    ml.get("policyVersion") if isinstance(ml, dict) else None
                ),
            )
        )
    return out


@router.post("/issues/{errand_id}/resolve")
async def resolve_issue(
    errand_id: uuid.UUID,
    payload: AdminIssueResolveIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Admin resolves/rejects/reopens a customer-reported issue."""

    admin = await _require_admin(db, authorization)

    action = (payload.action or "").strip().lower()
    if action not in {"resolve", "reject", "reopen"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid action; expected 'resolve', 'reject', or 'reopen'",
        )

    errand = await db.get(Errand, errand_id)
    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")

    if getattr(errand, "issue_reported_at", None) is None:
        raise HTTPException(status_code=400, detail="Errand has no reported issue")

    notes = (payload.notes or "").strip() or None
    if notes and len(notes) > 5000:
        raise HTTPException(status_code=400, detail="Notes is too long")

    if action == "reopen":
        setattr(errand, "issue_status", "open")
        setattr(errand, "issue_resolved_at", None)
    else:
        setattr(
            errand, "issue_status", "resolved" if action == "resolve" else "rejected"
        )
        setattr(errand, "issue_resolved_at", datetime.utcnow())

    if notes is not None:
        setattr(errand, "issue_resolution_notes", notes)

    await db.commit()
    await db.refresh(errand)

    print(
        f"[admin] user_id={admin.id} action=resolve_issue errand_id={errand_id} issue_status={getattr(errand, 'issue_status', None)}"
    )

    return {
        "errandId": errand.id,
        "issueStatus": getattr(errand, "issue_status", None),
        "issueResolvedAt": (
            getattr(errand, "issue_resolved_at", None).isoformat()
            if getattr(errand, "issue_resolved_at", None)
            else None
        ),
        "issueResolutionNotes": getattr(errand, "issue_resolution_notes", None),
    }


# ============================================================================
# CUSTOMER MANAGEMENT ENDPOINTS
# ============================================================================


class CustomerDetailOut(BaseModel):
    """Detailed customer profile"""

    id: uuid.UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    address_line1: Optional[str]
    address_line2: Optional[str]
    city: Optional[str]
    state: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    is_email_verified: bool
    id_verification_status: str
    address_verification_status: str
    created_at: str
    account_age_days: int


@router.get("/customers/stats", response_model=AdminCustomerStatsResponse, operation_id="getAdminCustomerStats", summary="Get customer statistics", description="Demographic and verification breakdown of platform customer accounts.")
async def get_customer_statistics(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get customer signup statistics"""
    admin = await _require_admin(db, authorization)

    total = await db.scalar(select(func.count()).select_from(User)) or 0
    verified = (
        await db.scalar(
            select(func.count()).select_from(User).where(User.is_email_verified)
        )
        or 0
    )
    countries_count = (
        await db.scalar(
            select(func.count(distinct(User.country))).where(User.country.is_not(None))
        )
        or 0
    )
    countries_result = await db.execute(
        select(User.country)
        .where(User.country.is_not(None))
        .distinct()
        .order_by(User.country.asc())
        .limit(10)
    )
    countries = [c[0] for c in countries_result.all() if c[0]]

    print(
        f"[admin] user_id={admin.id} action=get_customer_statistics total_customers={total} verified={verified}"
    )

    return {
        "total_customers": total,
        "verified_customers": verified,
        "unverified_customers": total - verified,
        "verification_rate": f"{(verified/total*100):.1f}%" if total > 0 else "0%",
        "countries_represented": int(countries_count),
        "top_countries": countries[:10] if countries else [],
    }


@router.get("/calls", response_model=list[AdminVoiceCallItem], operation_id="listAdminVoiceCalls", summary="List voice call sessions", description="Audit logs of customer-pilot masked call connections.")
async def list_voice_calls(
    authorization: Optional[str] = Header(default=None),
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin(db, authorization)

    query = (
        select(VoiceCallSession)
        .order_by(VoiceCallSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    sessions = result.scalars().all()

    print(f"[admin] user_id={admin.id} action=list_voice_calls count={len(sessions)}")

    return [
        {
            "id": session.id,
            "errand_id": session.errand_id,
            "status": session.status,
            "created_at": (
                session.created_at.isoformat() if session.created_at else None
            ),
            "initiator_user_id": session.initiator_user_id,
            "pilot_user_id": session.pilot_user_id,
            "customer_user_id": session.customer_user_id,
            "pilot_mask": session.pilot_phone_mask,
            "customer_mask": session.customer_phone_mask,
            "conference_name": session.conference_name,
        }
        for session in sessions
    ]


@router.get("/calls/{session_id}/events", response_model=list[AdminVoiceCallEventItem], operation_id="listAdminVoiceCallEvents", summary="List telephony session events", description="Audit webhook timeline events for a given voice session.")
async def list_voice_call_events(
    session_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin(db, authorization)

    session = await db.get(VoiceCallSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found")

    result = await db.execute(
        select(VoiceCallEvent)
        .where(VoiceCallEvent.session_id == session_id)
        .order_by(VoiceCallEvent.id.asc())
    )
    events = result.scalars().all()

    print(
        f"[admin] user_id={admin.id} action=list_voice_call_events session_id={session_id} count={len(events)}"
    )

    payload = []
    for event in events:
        parsed = None
        try:
            parsed = json.loads(event.payload_json)
        except Exception:
            parsed = event.payload_json
        payload.append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "payload": parsed,
                "created_at": (
                    event.created_at.isoformat() if event.created_at else None
                ),
                "entry_hash": event.entry_hash,
                "previous_hash": event.previous_hash,
            }
        )

    return payload


@router.get("/calls/{session_id}/transcript/download")
async def download_voice_transcript(
    session_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin(db, authorization)

    session = await db.get(VoiceCallSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found")

    result = await db.execute(
        select(VoiceCallEvent)
        .where(VoiceCallEvent.session_id == session_id)
        .order_by(VoiceCallEvent.id.asc())
    )
    events = result.scalars().all()
    transcript_events = []
    for event in events:
        if event.event_type != "transcription_ready":
            continue
        try:
            payload = json.loads(event.payload_json)
        except Exception:
            payload = event.payload_json
        transcript_events.append(
            {
                "created_at": (
                    event.created_at.isoformat() if event.created_at else None
                ),
                "payload": payload,
                "entry_hash": event.entry_hash,
                "previous_hash": event.previous_hash,
            }
        )

    filename = f"call-transcript-session-{session_id}.json"
    print(
        f"[admin] user_id={admin.id} action=download_transcript session_id={session_id}"
    )
    return JSONResponse(
        content={
            "session_id": session_id,
            "errand_id": session.errand_id,
            "events": transcript_events,
        },
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/dashboard",
    response_model=AdminMetricsOverviewResponse,
    operation_id="getAdminDashboard",
    summary="Get admin console dashboard overview",
    description="Consolidated operational metrics and activity summary for administrator portal.",
)
async def get_admin_dashboard(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AdminMetricsOverviewResponse:
    return await get_admin_metrics_overview(authorization=authorization, db=db)


@router.get("/metrics/overview", response_model=AdminMetricsOverviewResponse, operation_id="getAdminMetricsOverview", summary="Get admin operational metrics", description="Platform-wide monitoring metrics including user counts, errand funnel, and site visits.")
async def get_admin_metrics_overview(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Return admin-facing monitoring metrics (used by admin dashboard + Grafana)."""
    admin = await _require_admin(db, authorization)

    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    verified_users = (
        await db.scalar(
            select(func.count()).select_from(User).where(User.is_email_verified)
        )
        or 0
    )
    total_errands = await db.scalar(select(func.count()).select_from(Errand)) or 0
    pending_issues = (
        await db.scalar(
            select(func.count())
            .select_from(Errand)
            .where(Errand.issue_status == "open")
        )
        or 0
    )

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    visits_total = (
        await db.scalar(select(func.count()).select_from(AnalyticsVisit)) or 0
    )
    visits_last_24h = (
        await db.scalar(
            select(func.count())
            .select_from(AnalyticsVisit)
            .where(AnalyticsVisit.created_at >= since)
        )
        or 0
    )

    country_trim = func.trim(AnalyticsVisit.country)
    country_norm = func.upper(country_trim)

    def normalize_country_for_stats(value: Optional[str]) -> Optional[str]:
        """Best-effort normalization of legacy country strings to ISO-3166-1 alpha-2.

        The ingestion pipeline attempts to store ISO-2 already, but older rows may
        contain full names (e.g. 'UNITED KINGDOM') or aliases (e.g. 'UK').
        """

        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None

        upper = raw.upper()
        if upper in {"XX", "UNKNOWN", "UNSPECIFIED", "N/A", "NONE", "NULL"}:
            return None

        alias_map = {
            # UK
            "UK": "GB",
            "GBR": "GB",
            "GREAT BRITAIN": "GB",
            "UNITED KINGDOM": "GB",
            "ENGLAND": "GB",
            "SCOTLAND": "GB",
            "WALES": "GB",
            "NORTHERN IRELAND": "GB",
            # US
            "USA": "US",
            "UNITED STATES": "US",
            "UNITED STATES OF AMERICA": "US",
            # UAE
            "UAE": "AE",
            "UNITED ARAB EMIRATES": "AE",
            # Nigeria / common explicit names
            "NIGERIA": "NG",
            "CANADA": "CA",
            "AUSTRALIA": "AU",
        }
        upper = alias_map.get(upper, upper)

        if len(upper) == 2 and upper.isalpha():
            return upper
        return None

    def build_location_rollup(
        rows: list[tuple[Optional[str], Optional[str], Optional[str], int]],
    ) -> list[dict]:
        location_counts: dict[tuple[str, str, str], int] = {}
        unknown_only_total = 0

        for raw_country, raw_region, raw_city, count in rows:
            c = int(count or 0)
            if not c:
                continue

            country_code = normalize_country_for_stats(raw_country) or "Unknown"
            region = str(raw_region).strip() if raw_region else ""
            city = str(raw_city).strip() if raw_city else ""

            if country_code == "Unknown" and not region and not city:
                unknown_only_total += c
                continue

            key = (country_code, region, city)
            location_counts[key] = location_counts.get(key, 0) + c

        payload = [
            {
                "country": k[0],
                "region": k[1] or None,
                "city": k[2] or None,
                "count": int(v),
            }
            for k, v in sorted(
                location_counts.items(), key=lambda item: item[1], reverse=True
            )
        ]

        if unknown_only_total:
            payload.append(
                {
                    "country": "Unknown",
                    "region": None,
                    "city": None,
                    "count": int(unknown_only_total),
                }
            )

        return payload[:25]

    country_rows = await db.execute(
        select(country_norm.label("country"), func.count())
        .where(AnalyticsVisit.country.is_not(None))
        .where(country_trim != "")
        .where(country_norm != "XX")
        .group_by(country_norm)
        .order_by(func.count().desc())
        .limit(250)
    )

    normalized_country_counts: dict[str, int] = {}
    unrecognized_country_total = 0
    for raw_country, count in country_rows.all():
        n = normalize_country_for_stats(raw_country)
        c = int(count or 0)
        if not c:
            continue
        if n is None:
            unrecognized_country_total += c
            continue
        normalized_country_counts[n] = normalized_country_counts.get(n, 0) + c

    unknown_visits = (
        await db.scalar(
            select(func.count())
            .select_from(AnalyticsVisit)
            .where(
                or_(
                    AnalyticsVisit.country.is_(None),
                    country_trim == "",
                    country_norm == "XX",
                )
            )
        )
    ) or 0

    combined_country_counts = [
        {"country": code, "count": int(count)}
        for code, count in normalized_country_counts.items()
    ]

    unknown_total = int(unknown_visits) + int(unrecognized_country_total)
    if unknown_total:
        combined_country_counts.append({"country": "Unknown", "count": unknown_total})

    visits_by_country = sorted(
        combined_country_counts,
        key=lambda item: int(item.get("count") or 0),
        reverse=True,
    )[:10]

    region_trim = func.trim(AnalyticsVisit.region)
    city_trim = func.trim(AnalyticsVisit.city)

    region_rows = await db.execute(
        select(region_trim.label("region"), func.count())
        .where(AnalyticsVisit.region.is_not(None))
        .where(region_trim != "")
        .group_by(region_trim)
        .order_by(func.count().desc())
        .limit(25)
    )
    visits_by_region = [
        {"region": row[0], "count": int(row[1] or 0)}
        for row in region_rows.all()
        if row[0]
    ][:10]

    city_rows = await db.execute(
        select(city_trim.label("city"), func.count())
        .where(AnalyticsVisit.city.is_not(None))
        .where(city_trim != "")
        .group_by(city_trim)
        .order_by(func.count().desc())
        .limit(25)
    )
    visits_by_city = [
        {"city": row[0], "count": int(row[1] or 0)} for row in city_rows.all() if row[0]
    ][:10]

    # Best-effort location breakdown (country/region/city). This is only as accurate
    # as the upstream geo headers (CloudFront/CF/etc). If those are absent, the
    # client-sent country hint still allows country-level aggregation.
    location_rows = await db.execute(
        select(
            country_norm.label("country"),
            region_trim.label("region"),
            city_trim.label("city"),
            func.count(),
        )
        .where(
            or_(
                AnalyticsVisit.country.is_not(None),
                AnalyticsVisit.region.is_not(None),
                AnalyticsVisit.city.is_not(None),
            )
        )
        .group_by(country_norm, region_trim, city_trim)
        .order_by(func.count().desc())
        .limit(250)
    )
    visits_by_location = build_location_rollup(location_rows.all())

    location_rows_last_24h = await db.execute(
        select(
            country_norm.label("country"),
            region_trim.label("region"),
            city_trim.label("city"),
            func.count(),
        )
        .where(AnalyticsVisit.created_at >= since)
        .where(
            or_(
                AnalyticsVisit.country.is_not(None),
                AnalyticsVisit.region.is_not(None),
                AnalyticsVisit.city.is_not(None),
            )
        )
        .group_by(country_norm, region_trim, city_trim)
        .order_by(func.count().desc())
        .limit(250)
    )
    visits_last_24h_by_location = build_location_rollup(location_rows_last_24h.all())

    recent_visit_rows = await db.execute(
        select(
            AnalyticsVisit.page,
            AnalyticsVisit.source,
            country_norm.label("country"),
            region_trim.label("region"),
            city_trim.label("city"),
            AnalyticsVisit.created_at,
        )
        .where(AnalyticsVisit.created_at >= since)
        .order_by(AnalyticsVisit.created_at.desc(), AnalyticsVisit.id.desc())
        .limit(100)
    )
    visits_recent_24h = []
    for (
        page,
        source,
        raw_country,
        raw_region,
        raw_city,
        created_at,
    ) in recent_visit_rows.all():
        visits_recent_24h.append(
            {
                "page": page,
                "source": source,
                "country": normalize_country_for_stats(raw_country) or "Unknown",
                "region": str(raw_region).strip() if raw_region else None,
                "city": str(raw_city).strip() if raw_city else None,
                "created_at": created_at.isoformat() if created_at else None,
            }
        )

    source_rows = await db.execute(
        select(AnalyticsVisit.source, func.count())
        .where(AnalyticsVisit.source.is_not(None))
        .group_by(AnalyticsVisit.source)
        .order_by(func.count().desc())
        .limit(10)
    )
    visits_by_source = [
        {"source": row[0], "count": row[1]} for row in source_rows.all() if row[0]
    ]

    funnel_stages = [
        "pending",
        "accepted",
        "assigned",
        "in_progress",
        "picked_up",
        "delivered",
        "completed",
        "cancelled",
    ]
    funnel = {stage: 0 for stage in funnel_stages}
    status_rows = await db.execute(
        select(Errand.status, func.count()).group_by(Errand.status)
    )
    for status, count in status_rows.all():
        if not status:
            continue
        funnel[str(status)] = int(count)

    payload = {
        "total_users": int(total_users),
        "verified_users": int(verified_users),
        "pending_issues": int(pending_issues),
        "total_errands": int(total_errands),
        "visits_total": int(visits_total),
        "visits_last_24h": int(visits_last_24h),
        "visits_by_country": visits_by_country,
        "visits_by_region": visits_by_region,
        "visits_by_city": visits_by_city,
        "visits_by_location": visits_by_location,
        "visits_last_24h_by_location": visits_last_24h_by_location,
        "visits_recent_24h": visits_recent_24h,
        "visits_by_source": visits_by_source,
        "errand_funnel": funnel,
        "last_updated": now.isoformat(),
    }

    update_admin_metrics(payload)

    print(
        f"[admin] user_id={admin.id} action=get_admin_metrics_overview total_users={total_users} visits_total={visits_total}"
    )

    return payload


@router.post("/metrics/reset-visits", response_model=dict)
async def reset_admin_visit_metrics(
    payload: AdminResetVisitsPayload,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Delete visit analytics rows so Admin Dashboard visit counters reset.

    This is intentionally password-guarded (in addition to admin auth) because it
    is a destructive operation.
    """
    admin = await _require_admin(db, authorization)

    expected = (os.getenv("ADMIN_STATS_RESET_PASSWORD") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "ADMIN_STATS_RESET_PASSWORD is not configured. "
                "Set it in the API environment (local docker-compose: errandbridge-backend/.env) "
                "and restart the API to enable reset."
            ),
        )

    provided = (payload.password or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid reset password")

    deleted = 0
    try:
        deleted = (
            await db.scalar(select(func.count()).select_from(AnalyticsVisit))
        ) or 0
        await db.execute(delete(AnalyticsVisit))
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    print(
        f"[admin] user_id={admin.id} action=reset_admin_visit_metrics deleted={int(deleted)}"
    )
    return {"ok": True, "deleted": int(deleted)}


@router.get("/customers/{user_id}", response_model=CustomerDetailOut, operation_id="getAdminCustomerDetail", summary="Get customer details", description="Retrieve complete customer profile and errand history.")
async def get_customer_details(
    user_id: uuid.UUID,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed profile of a specific customer"""
    admin = await _require_admin(db, authorization)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Customer not found")

    account_age = (datetime.utcnow() - user.created_at).days if user.created_at else 0

    print(
        f"[admin] user_id={admin.id} action=get_customer_details target_user_id={user_id}"
    )

    return CustomerDetailOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        address_line1=user.address_line1,
        address_line2=user.address_line2,
        city=user.city,
        state=user.state,
        postal_code=user.postal_code,
        country=user.country,
        is_email_verified=bool(user.is_email_verified),
        id_verification_status=user.id_verification_status,
        address_verification_status=user.address_verification_status,
        created_at=user.created_at.isoformat() if user.created_at else "",
        account_age_days=account_age,
    )


@router.get("/customers", response_model=list[AdminCustomerListItem], operation_id="listAdminCustomers", summary="List all platform customers", description="Administrative directory of registered customers.")
async def list_all_customers(
    authorization: Optional[str] = Header(default=None),
    verified_only: bool = False,
    country: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List customers with optional filters"""
    admin = await _require_admin(db, authorization)

    query = select(User)

    # Apply filters
    if verified_only:
        query = query.where(User.is_email_verified)

    if country:
        query = query.where(User.country == country)

    # Order by newest first
    query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    users = result.scalars().all()

    print(
        f"[admin] user_id={admin.id} action=list_customers count={len(users)} verified_only={verified_only} country={country}"
    )

    return [
        {
            "id": u.id,
            "email": u.email,
            "first_name": u.first_name or "",
            "last_name": u.last_name or "",
            "phone": u.phone,
            "city": u.city,
            "country": u.country,
            "is_email_verified": bool(u.is_email_verified),
            "is_pilot": bool(getattr(u, "is_pilot", False)),
            "rating": (
                float(u.rating) if getattr(u, "rating", None) is not None else None
            ),
            "profile_image_url": u.profile_image_url,
            "created_at": u.created_at.isoformat() if u.created_at else "",
            **serialize_pilot_dispatch_state(u),
        }
        for u in users
    ]


@router.get(
    "/customers/location/{country}",
    response_model=AdminCustomersByCountryResponse,
    operation_id="getAdminCustomersByCountry",
    summary="Get customers by country",
    description="Filter customer database by ISO country identifier.",
)
async def get_customers_by_country(
    country: str,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get all customers from a specific country"""
    admin = await _require_admin(db, authorization)

    result = await db.execute(
        select(User).where(User.country == country).order_by(User.city)
    )
    users = result.scalars().all()

    print(
        f"[admin] user_id={admin.id} action=get_customers_by_country country={country} count={len(users)}"
    )

    return {
        "country": country,
        "total_in_country": len(users),
        "customers": [
            {
                "id": u.id,
                "email": u.email,
                "name": f"{u.first_name or ''} {u.last_name or ''}".strip(),
                "city": u.city,
                "state": u.state,
                "postal_code": u.postal_code,
                "verified": bool(u.is_email_verified),
            }
            for u in users
        ],
    }


@router.get(
    "/customers/unverified/list",
    response_model=AdminUnverifiedCustomersResponse,
    operation_id="listAdminUnverifiedCustomers",
    summary="List unverified customer accounts",
    description="Retrieve customers who have not completed email verification.",
)
async def get_unverified_customers(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get list of unverified customers (for follow-up)"""
    admin = await _require_admin(db, authorization)

    result = await db.execute(
        select(User).where(~User.is_email_verified).order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    print(
        f"[admin] user_id={admin.id} action=get_unverified_customers count={len(users)}"
    )

    return {
        "unverified_count": len(users),
        "customers": [
            {
                "id": u.id,
                "email": u.email,
                "name": f"{u.first_name or ''} {u.last_name or ''}".strip(),
                "otp_attempts": u.email_otp_attempts,
                "created_at": u.created_at.isoformat() if u.created_at else "",
                "days_since_signup": (
                    (datetime.now(timezone.utc) - u.created_at).days
                    if u.created_at
                    else 0
                ),
            }
            for u in users
        ],
    }


@router.post(
    "/customers/unverified/purge",
    response_model=AdminPurgeUnverifiedCustomersResponse,
    operation_id="purgeAdminUnverifiedCustomers",
    summary="Bulk purge unverified accounts",
    description="Permanently remove accounts that have never confirmed email verification.",
)
async def purge_unverified_customers(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Delete all unverified accounts at once."""
    admin = await _require_admin(db, authorization)

    result = await db.execute(select(User).where(~User.is_email_verified))
    users = result.scalars().all()
    deleted_count = len(users)
    deleted_emails = [user.email for user in users if user.email]

    if deleted_count:
        await db.execute(delete(User).where(~User.is_email_verified))
        await db.commit()

    print(
        f"[admin] user_id={admin.id} action=purge_unverified_customers count={deleted_count}"
    )

    return {
        "deleted_count": deleted_count,
        "deleted_emails": deleted_emails,
    }
