from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
import asyncio
import time
import os
from typing import Optional
from urllib.parse import urlencode
from email_validator import EmailNotValidError, validate_email
import strawberry
from strawberry.types import Info
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from auth_user_query import (
    AUTH_SAFE_USER_LOAD_OPTIONS,
    auth_safe_user_by_email_query,
    auth_safe_user_by_phone_query,
    build_phone_alias_email,
    is_phone_identifier,
    normalize_phone_for_storage,
)
from emailer import send_email
from sms_sender import send_sms
from notification_utils import notify_customer_status, notify_pilot_status
from models import (
    Errand as ErrandModel,
    User,
    ErrandEvent,
    ClientSubscription,
    StripeCheckoutSession,
)


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _public_user_uuid(user: User) -> str:
    value = getattr(user, "user_uuid", None)
    if value:
        return str(value)
    return f"00000000-0000-0000-0000-{int(getattr(user, 'id', 0)):012d}"


async def _get_auth_user_by_email(session: AsyncSession, email: str) -> User | None:
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    result = await session.execute(auth_safe_user_by_email_query(normalized))
    return result.scalars().first()


async def _get_auth_user_by_phone(session: AsyncSession, phone: str) -> User | None:
    normalized = normalize_phone_for_storage(phone)
    if not normalized:
        return None
    result = await session.execute(auth_safe_user_by_phone_query(normalized))
    return result.scalars().first()


async def _get_auth_user_by_identifier(session: AsyncSession, identifier: str) -> User | None:
    raw = (identifier or "").strip()
    if not raw:
        return None
    if is_phone_identifier(raw):
        return await _get_auth_user_by_phone(session, raw)
    return await _get_auth_user_by_email(session, raw)


def _normalize_signup_email(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        raise ValueError("Enter a valid email address or phone number")

    try:
        validated = validate_email(candidate, check_deliverability=False)
    except EmailNotValidError:
        raise ValueError("Enter a valid email address or phone number")

    return str(validated.normalized).strip().lower()


# Strawberry type for errand event history
@strawberry.type
class ErrandEventType:
    id: int
    eventType: str
    oldStatus: str | None
    newStatus: str | None
    note: str | None
    createdAt: datetime
    userId: int | None


@strawberry.enum
class SortOrder(Enum):
    ASC = "asc"
    DESC = "desc"


@strawberry.type
class ErrandTimelineEvent:
    """Flattened timeline event used for client toast polling.

    This avoids the N+1 cost of querying `errand.history` for many errands.
    """

    id: int
    errandId: int
    referenceNumber: str
    errandTitle: str
    eventType: str
    oldStatus: str | None
    newStatus: str | None
    note: str | None
    createdAt: datetime
    userId: int | None


# Strawberry type for errand attachments
@strawberry.type
class AttachmentType:
    id: int
    filename: str
    contentType: str
    sizeBytes: int
    createdAt: datetime


def _make_reference_number(errand_id: int) -> str:
    """Generate a stable customer-facing reference number.

    Format: EB-<id>-<4-digit-check>
    The check portion is deterministic from `id`.
    """
    check = (int(errand_id) * 7919) % 10000
    return f"EB-{int(errand_id)}-{check:04d}"


# Status progression (v1)
#
# Canonical values are snake_case to keep API payloads predictable.
# We still accept a few legacy aliases to avoid breaking existing clients.
_CANONICAL_STATUSES = [
    "submitted",
    "assigned",
    "picked_up",
    "delivered",
    "issue_reported",
    "completed",
]

_STATUS_ALIASES = {
    # legacy or common variants
    "pending": "submitted",
    "created": "submitted",
    "new": "submitted",
    "in_progress": "assigned",
    "in-progress": "assigned",
    "active": "assigned",
    "picked up": "picked_up",
    "picked-up": "picked_up",
}

REFERRAL_CAMPAIGN_END = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _completed_client_statuses() -> set[str]:
    return {"completed", "accepted", "delivered"}


def _referral_public_base_url() -> str:
    candidates = [
        os.getenv("PUBLIC_APP_BASE_URL"),
        os.getenv("APP_BASE_URL"),
        os.getenv("REACT_APP_APP_BASE_URL"),
        "https://www.errandbridge.com",
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value.rstrip("/")
    return "https://www.errandbridge.com"


def build_referral_code_for_user(user: User | None) -> str | None:
    if not user or getattr(user, "id", None) is None:
        return None

    seed_parts = [
        str(getattr(user, "first_name", "") or ""),
        str(getattr(user, "last_name", "") or ""),
        str(getattr(user, "email", "") or ""),
    ]
    letters = "".join(ch for part in seed_parts for ch in part.upper() if ch.isalpha())
    prefix = (letters[:4] or "EBCL").ljust(4, "X")
    checksum = (int(user.id) * 7919) % 10000
    return f"{prefix}{int(user.id)}{checksum:04d}"


def build_client_lifecycle_snapshot(
    *,
    user: User | None,
    errands: list[ErrandModel] | None,
    promo_codes: list,
    public_base_url: str | None = None,
) -> dict:
    errands = list(errands or [])
    promo_codes = list(promo_codes or [])
    is_logged_in = bool(user and getattr(user, "id", None) is not None)

    completed_statuses = _completed_client_statuses()
    completed_errands = []
    pending_review_errands = []
    submitted_review_count = 0

    for errand in errands:
        status = _normalize_status(getattr(errand, "status", None))
        review_status = str(getattr(errand, "review_status", "") or "").strip().lower()
        if review_status == "reviewed":
            submitted_review_count += 1
        if status in completed_statuses:
            completed_errands.append(errand)
        if status == "completed" and review_status != "reviewed":
            pending_review_errands.append(errand)

    completed_errands.sort(
        key=lambda errand: getattr(errand, "completed_at", None)
        or getattr(errand, "review_completed_at", None)
        or getattr(errand, "created_at", None)
        or datetime.min,
        reverse=True,
    )
    pending_review_errands.sort(
        key=lambda errand: getattr(errand, "completed_at", None)
        or getattr(errand, "created_at", None)
        or datetime.min,
        reverse=True,
    )

    referral_code = build_referral_code_for_user(user) if is_logged_in else None
    referral_share_link = (
        f"{(public_base_url or _referral_public_base_url())}/signup?ref={referral_code}"
        if referral_code
        else None
    )

    referral_promos = [
        promo
        for promo in promo_codes
        if str(getattr(promo, "source", "") or "").startswith("referral_reward:")
    ]
    unused_referral_promos = [
        promo
        for promo in referral_promos
        if int(getattr(promo, "redeemed_count", 0) or 0)
        < int(getattr(promo, "max_redemptions", 1) or 1)
    ]

    latest_unused_expiry = REFERRAL_CAMPAIGN_END if unused_referral_promos else None

    return {
        "userId": int(user.id) if is_logged_in else None,
        "isLoggedIn": is_logged_in,
        "hasSubmittedRequest": bool(errands),
        "isReturningClient": len(errands) > 0,
        "completedErrandCount": len(completed_errands),
        "pendingReviewErrandIds": [int(errand.id) for errand in pending_review_errands],
        "lastCompletedErrandId": int(completed_errands[0].id) if completed_errands else None,
        "hasSubmittedAnyReview": submitted_review_count > 0,
        "hasPendingReview": bool(pending_review_errands),
        "referralCode": referral_code,
        "referralShareLink": referral_share_link,
        "hasEarnedReferralReward": bool(referral_promos),
        "hasUnusedReferralReward": bool(unused_referral_promos),
        "referralRewardExpiresAt": _serialize_datetime(latest_unused_expiry),
        "referralCampaignEndsAt": _serialize_datetime(REFERRAL_CAMPAIGN_END),
        "hasReferralShareAvailable": bool(referral_share_link and submitted_review_count > 0),
    }


def _normalize_status(value: str | None) -> str:
    v = (value or "").strip().lower()
    if not v:
        return "submitted"
    v = _STATUS_ALIASES.get(v, v)
    return v


def _is_valid_transition(prev_status: str, next_status: str) -> bool:
    # Allow idempotent.
    if prev_status == next_status:
        return True

    # Allow forward-only progression.
    try:
        prev_idx = _CANONICAL_STATUSES.index(prev_status)
        next_idx = _CANONICAL_STATUSES.index(next_status)
    except ValueError:
        return False

    return next_idx == prev_idx + 1


def _build_user_display_name(user: User | None) -> str:
    if not user:
        return "Pilot"
    first = str(getattr(user, "first_name", "") or "").strip()
    last = str(getattr(user, "last_name", "") or "").strip()
    full = " ".join(part for part in [first, last] if part).strip()
    return full or str(getattr(user, "email", "") or "Pilot").strip() or "Pilot"


def build_assigned_pilot_trust_snapshot(
    *,
    pilot: User | None,
    reviewed_errands: list[ErrandModel] | None,
    completed_errands_count: int = 0,
) -> dict | None:
    if not pilot or not getattr(pilot, "id", None):
        return None

    reviewed_errands = list(reviewed_errands or [])
    ratings = [
        int(getattr(errand, "reviewer_rating", 0) or 0)
        for errand in reviewed_errands
        if getattr(errand, "reviewer_rating", None) is not None
    ]
    average_rating = round(sum(ratings) / len(ratings), 1) if ratings else None
    fallback_rating = getattr(pilot, "rating", None)
    if average_rating is None:
        try:
            average_rating = round(float(fallback_rating), 1)
        except (TypeError, ValueError):
            average_rating = 4.8

    verification_status = str(
        getattr(pilot, "id_verification_status", "") or "",
    ).strip().lower()
    if getattr(pilot, "is_email_verified", False) and verification_status in {"verified", "approved"}:
        verification_label = "Identity verified"
    elif getattr(pilot, "is_email_verified", False):
        verification_label = "Email verified"
    else:
        verification_label = "Verification pending"

    review_count = len(ratings)
    if review_count >= 15 or completed_errands_count >= 75:
        trust_label = "Top rated pilot"
    elif review_count >= 5 or completed_errands_count >= 20:
        trust_label = "Trusted by clients"
    elif completed_errands_count > 0:
        trust_label = "Active delivery pilot"
    else:
        trust_label = "New pilot profile"

    recent_reviews = []
    for errand in reviewed_errands[:3]:
        recent_reviews.append(
            {
                "title": getattr(errand, "title", None) or "Recent errand",
                "referenceNumber": getattr(errand, "reference_number", None)
                or _make_reference_number(getattr(errand, "id", 0) or 0),
                "rating": getattr(errand, "reviewer_rating", None),
                "reviewNotes": getattr(errand, "reviewer_notes", None),
                "reviewedAt": getattr(errand, "review_completed_at", None)
                or getattr(errand, "completed_at", None)
                or getattr(errand, "created_at", None),
            }
        )

    return {
        "pilotId": int(pilot.id),
        "displayName": _build_user_display_name(pilot),
        "firstName": getattr(pilot, "first_name", None),
        "lastName": getattr(pilot, "last_name", None),
        "rating": average_rating,
        "reviewCount": review_count,
        "completedErrands": int(completed_errands_count or 0),
        "verificationLabel": verification_label,
        "trustLabel": trust_label,
        "profileImageUrl": getattr(pilot, "profile_image_url", None),
        "recentReviews": recent_reviews,
    }


@strawberry.type
class AssignedPilotTrustReview:
    title: str
    referenceNumber: str
    rating: Optional[int]
    reviewNotes: Optional[str]
    reviewedAt: Optional[datetime]


@strawberry.type
class AssignedPilotTrust:
    pilotId: int
    displayName: str
    firstName: Optional[str]
    lastName: Optional[str]
    rating: float
    reviewCount: int
    completedErrands: int
    verificationLabel: str
    trustLabel: str
    profileImageUrl: Optional[str]
    recentReviews: list[AssignedPilotTrustReview]

@strawberry.type
class Errand:
    @strawberry.field
    async def history(self, info: Info) -> list[ErrandEventType]:
        from models import ErrandEvent
        session: AsyncSession = info.context["db"]
        result = await session.execute(
            select(ErrandEvent).where(ErrandEvent.errand_id == self.id).order_by(ErrandEvent.created_at.asc())
        )
        rows = result.scalars().all()
        return [ErrandEventType(
            id=e.id,
            eventType=e.event_type,
            oldStatus=e.old_status,
            newStatus=e.new_status,
            note=e.note,
            createdAt=e.created_at,
            userId=e.user_id
        ) for e in rows]
    
    @strawberry.field
    async def attachments(self, info: Info) -> list[AttachmentType]:
        from models import ErrandAttachment
        session: AsyncSession = info.context["db"]
        result = await session.execute(
            select(ErrandAttachment).where(ErrandAttachment.errand_id == self.id).order_by(ErrandAttachment.created_at.asc())
        )
        rows = result.scalars().all()
        return [AttachmentType(
            id=a.id,
            filename=a.original_filename,
            contentType=a.content_type,
            sizeBytes=a.size_bytes,
            createdAt=a.created_at
        ) for a in rows]

    @strawberry.field
    async def assignedPilotTrust(self, info: Info) -> Optional[AssignedPilotTrust]:
        session: AsyncSession = info.context["db"]
        pilot_id = getattr(self, "pilotId", None)
        if not pilot_id:
            return None

        pilot = await session.get(User, int(pilot_id))
        if not pilot or not getattr(pilot, "is_pilot", False):
            return None

        reviewed_result = await session.execute(
            select(ErrandModel)
            .where(ErrandModel.pilot_id == int(pilot_id))
            .where(ErrandModel.review_status == "reviewed")
            .where(ErrandModel.reviewer_rating.is_not(None))
            .order_by(
                func.coalesce(
                    ErrandModel.review_completed_at,
                    ErrandModel.completed_at,
                    ErrandModel.created_at,
                ).desc()
            )
            .limit(3)
        )
        reviewed_errands = reviewed_result.scalars().all()

        completed_count_result = await session.execute(
            select(func.count(ErrandModel.id))
            .where(ErrandModel.pilot_id == int(pilot_id))
            .where(ErrandModel.status.in_(["accepted", "delivered", "completed"]))
        )
        completed_errands_count = completed_count_result.scalar() or 0

        snapshot = build_assigned_pilot_trust_snapshot(
            pilot=pilot,
            reviewed_errands=reviewed_errands,
            completed_errands_count=int(completed_errands_count or 0),
        )
        if not snapshot:
            return None

        return AssignedPilotTrust(
            pilotId=snapshot["pilotId"],
            displayName=snapshot["displayName"],
            firstName=snapshot["firstName"],
            lastName=snapshot["lastName"],
            rating=snapshot["rating"],
            reviewCount=snapshot["reviewCount"],
            completedErrands=snapshot["completedErrands"],
            verificationLabel=snapshot["verificationLabel"],
            trustLabel=snapshot["trustLabel"],
            profileImageUrl=snapshot["profileImageUrl"],
            recentReviews=[
                AssignedPilotTrustReview(
                    title=review["title"],
                    referenceNumber=review["referenceNumber"],
                    rating=review["rating"],
                    reviewNotes=review["reviewNotes"],
                    reviewedAt=review["reviewedAt"],
                )
                for review in snapshot["recentReviews"]
            ],
        )
    
    id: int
    referenceNumber: str
    title: str
    description: Optional[str]
    categoryId: Optional[str]
    templateId: Optional[str]
    supportType: Optional[str]
    preferredTime: Optional[str]
    priorityLevel: Optional[str]
    distanceKm: Optional[float]
    finalPriceMinor: Optional[int]
    finalPriceCurrency: Optional[str]
    sensitivity: Optional[str]
    confirmationSentAt: Optional[int]
    pickupLocation: Optional[str]
    dropoffLocation: Optional[str]
    note: Optional[str]  # Added note field
    status: str
    issueReason: Optional[str]
    issueNotes: Optional[str]
    issueReportedAt: Optional[datetime]
    issuePreferredResolution: Optional[str]
    issueStatus: Optional[str]
    issueResolvedAt: Optional[datetime]
    issueResolutionNotes: Optional[str]
    issueEvidenceAttachmentIds: Optional[str]
    created_at: datetime
    userId: int
    
    # Pickup time slot
    pickupTimeSlotStart: Optional[datetime]
    pickupTimeSlotEnd: Optional[datetime]
    pickupTimeSlotDate: Optional[str]
    
    # Assignment fields
    assignedTo: Optional[int]  # Admin user ID
    assignedAt: Optional[datetime]
    pilotId: Optional[int]
    
    # Review fields
    reviewStatus: Optional[str]  # 'pending', 'reviewed', 'appealed'
    reviewerRating: Optional[int]  # 1-5 stars
    reviewerNotes: Optional[str]
    reviewCompletedAt: Optional[datetime]


@strawberry.input
class CreateErrandInput:
    title: str
    description: Optional[str] = None
    categoryId: Optional[str] = None
    templateId: Optional[str] = None
    supportType: Optional[str] = None
    preferredTime: Optional[str] = None
    priorityLevel: Optional[str] = None
    distanceKm: Optional[float] = None
    finalPriceMinor: Optional[int] = None
    finalPriceCurrency: Optional[str] = None
    sensitivity: Optional[str] = None
    pickupLocation: Optional[str] = None
    dropoffLocation: Optional[str] = None
    note: Optional[str] = None  # Added note field
    pickupTimeSlotStart: Optional[str] = None  # ISO format datetime string
    pickupTimeSlotEnd: Optional[str] = None    # ISO format datetime string
    pickupTimeSlotDate: Optional[str] = None   # YYYY-MM-DD format
    # New scheduling API (backward compatible). The frontend may send either
    # the legacy pickupTimeSlot* fields or a nested schedule object.
    scheduleType: Optional[str] = None  # e.g. 'now' | 'one_time' | 'recurring'
    schedule: Optional["ScheduleInput"] = None

    # When enforcement is enabled, a paid unused Stripe Checkout Session ID is required
    # unless the user has an active Plus subscription.
    paymentSessionId: Optional[str] = None

    userId: Optional[int] = None


@strawberry.input
class ScheduleInput:
    """Client-provided schedule shape.

    We persist scheduling into existing Errand columns:
    - one_time.date/startTime/endTime -> pickupTimeSlotDate/start/end
    - now clears pickupTimeSlot*

    Recurring scheduling isn't yet persisted (no DB fields). The input is
    accepted so the UI can evolve without breaking.
    """

    type: str  # 'now' | 'one_time' | 'recurring'

    # one_time
    date: Optional[str] = None
    startTime: Optional[str] = None  # 'HH:MM'
    endTime: Optional[str] = None    # 'HH:MM'

    # recurring (accepted but not persisted yet)
    frequency: Optional[str] = None
    days: Optional[list[str]] = None
    time: Optional[str] = None


@strawberry.input
class UpdateErrandStatusInput:
    id: int
    status: str


@strawberry.input
class UpdateErrandInput:
    id: int
    title: Optional[str] = None
    description: Optional[str] = None
    templateId: Optional[str] = None
    sensitivity: Optional[str] = None
    pickupLocation: Optional[str] = None
    dropoffLocation: Optional[str] = None
    note: Optional[str] = None
    pickupTimeSlotStart: Optional[str] = None
    pickupTimeSlotEnd: Optional[str] = None
    pickupTimeSlotDate: Optional[str] = None


@strawberry.input
class ReportErrandIssueInput:
    id: int
    reason: str
    notes: Optional[str] = None
    preferredResolution: Optional[str] = None
    evidenceAttachmentIds: Optional[list[int]] = None


@strawberry.input
class SendErrandConfirmationInput:
    id: int


@strawberry.input
class LoginInput:
    email: str
    password: str
    role: Optional[str] = None


@strawberry.input
class SignupInput:
    email: str
    password: str
    firstName: str | None = None
    lastName: str | None = None
    phone: str | None = None
    addressLine1: str | None = None
    addressLine2: str | None = None
    city: str | None = None
    state: str | None = None
    postalCode: str | None = None
    country: str | None = None
    otpDeliveryChannel: str = "email"
    otpDeliveryMode: str = "code"
    role: Optional[str] = None


@strawberry.type
class AuthResponse:
    accessToken: str
    refreshToken: str
    userId: int
    userUuid: str
    email: str
    firstName: str | None
    lastName: str | None
    phone: str | None
    addressLine1: str | None
    addressLine2: str | None
    city: str | None
    state: str | None
    postalCode: str | None
    country: str | None
    isEmailVerified: bool
    isAdmin: bool


@strawberry.type
class Transparency:
    """User's transparency metrics"""
    completed_errands: int
    documents_handled: int


@strawberry.type
class UserProfile:
    """Current user profile information"""
    id: int
    userUuid: str
    email: str
    firstName: str | None
    lastName: str | None
    phone: str | None
    addressLine1: str | None
    addressLine2: str | None
    city: str | None
    state: str | None
    postalCode: str | None
    country: str | None
    isEmailVerified: bool
    isAdmin: bool
    profileImageUrl: str | None = None
    transparency: Transparency | None = None


@strawberry.type
class ClientLifecycle:
    userId: int | None
    isLoggedIn: bool
    hasSubmittedRequest: bool
    isReturningClient: bool
    completedErrandCount: int
    pendingReviewErrandIds: list[int]
    lastCompletedErrandId: int | None
    hasSubmittedAnyReview: bool
    hasPendingReview: bool
    referralCode: str | None
    referralShareLink: str | None
    hasEarnedReferralReward: bool
    hasUnusedReferralReward: bool
    referralRewardExpiresAt: str | None
    referralCampaignEndsAt: str
    hasReferralShareAvailable: bool


@strawberry.input
class UpdateProfileInput:
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    addressLine1: Optional[str] = None
    addressLine2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postalCode: Optional[str] = None
    country: Optional[str] = None


_OTP_CHANNELS = {"email", "sms"}
_OTP_MODES = {"code", "link", "both"}
_DEFAULT_OTP_CHANNEL = "email"
_DEFAULT_OTP_MODE = "code"


def _normalize_otp_options(channel: str | None, mode: str | None) -> tuple[str, str]:
    resolved_channel = (channel or _DEFAULT_OTP_CHANNEL).strip().lower()
    resolved_mode = (mode or _DEFAULT_OTP_MODE).strip().lower()
    if resolved_channel not in _OTP_CHANNELS:
        resolved_channel = _DEFAULT_OTP_CHANNEL
    if resolved_mode not in _OTP_MODES:
        resolved_mode = _DEFAULT_OTP_MODE
    if resolved_mode in {"link", "both"} and not (os.getenv("OTP_VERIFICATION_LINK_BASE_URL") or "").strip():
        resolved_mode = "code"
    return resolved_channel, resolved_mode


def _derive_names_from_email(email: str) -> tuple[str, str]:
    base = email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
    if not base:
        return "Customer", ""
    parts = [part for part in base.split() if part]
    first = parts[0].title() if parts else "Customer"
    last = " ".join(part.title() for part in parts[1:]) if len(parts) > 1 else ""
    return first, last


def _build_otp_link(email: str, code: str) -> str | None:
    base = (os.getenv("OTP_VERIFICATION_LINK_BASE_URL") or "").strip()
    if not base:
        return None
    query = urlencode({"email": email, "code": code})
    return f"{base.rstrip('/')}/?{query}"


def _build_otp_body(*, email: str, code: str, purpose: str, mode: str) -> str:
    link = _build_otp_link(email, code)
    if mode in ("link", "both") and not link:
        raise ValueError("OTP link delivery requested but OTP_VERIFICATION_LINK_BASE_URL is not set")

    if mode == "link":
        return (
            f"Use this link to complete {purpose}:\n\n{link}\n\n"
            "It expires in 10 minutes."
        )
    if mode == "both":
        return (
            f"Your security code is:\n\n{code}\n\n"
            f"Or use this link to complete {purpose}:\n\n{link}\n\n"
            "It expires in 10 minutes."
        )

    return (
        f"Your security code is:\n\n{code}\n\n"
        "It expires in 10 minutes."
    )


async def _prepare_and_send_otp(
    *,
    session: AsyncSession,
    user: User,
    purpose: str,
    channel: str,
    mode: str,
) -> None:
    from otp import generate_numeric_code, hash_code, now_ts

    code = generate_numeric_code(6)
    user.email_otp_hash = hash_code(code)
    user.email_otp_expires_at = now_ts() + int(10 * 60)
    user.email_otp_last_sent_at = now_ts()
    user.email_otp_attempts = 0
    await session.commit()

    body_text = _build_otp_body(email=user.email, code=code, purpose=purpose, mode=mode)

    if channel == "sms":
        if not user.phone:
            raise ValueError("Phone number required for SMS OTP delivery")
        try:
            result = await asyncio.to_thread(send_sms, to_number=user.phone, body_text=body_text)
            if not result.delivered:
                print(f"[GRAPHQL OTP] SMS send failed: {result.detail}")
                user.email_otp_last_sent_at = 0
                await session.commit()
                raise ValueError("SMS delivery is unavailable. Please try again later.")
        except ValueError:
            raise
        except Exception as e:
            print(f"[GRAPHQL OTP] SMS send failed: {e}")
            user.email_otp_last_sent_at = 0
            await session.commit()
            raise ValueError("SMS delivery is unavailable. Please try again later.")
        return

    try:
        result = await asyncio.to_thread(
            send_email,
            to_email=user.email,
            subject="Your ErrandBridge verification code",
            body_text=body_text,
        )
        if result.provider == "stdout":
            if channel != "sms" and user.phone:
                async def _dispatch_stdout_sms_fallback() -> None:
                    fallback = await asyncio.to_thread(
                        send_sms,
                        to_number=user.phone,
                        body_text=body_text,
                    )
                    if not fallback.delivered:
                        print(f"[GRAPHQL OTP] Stdout SMS fallback failed: {fallback.detail}")

                asyncio.create_task(_dispatch_stdout_sms_fallback())
            return
        if not result.delivered:
            print(f"[GRAPHQL OTP] Email send failed: {result.detail}")
            if channel != "sms" and user.phone:
                async def _dispatch_sms_fallback() -> None:
                    fallback = await asyncio.to_thread(
                        send_sms,
                        to_number=user.phone,
                        body_text=body_text,
                    )
                    if not fallback.delivered:
                        print(f"[GRAPHQL OTP] SMS fallback failed: {fallback.detail}")

                asyncio.create_task(_dispatch_sms_fallback())
                return
            user.email_otp_last_sent_at = 0
            await session.commit()
            raise ValueError("Email delivery is unavailable. Please try again later.")
    except ValueError:
        raise
    except Exception as e:
        print(f"[GRAPHQL OTP] Email send failed: {e}")
        if channel != "sms" and user.phone:
            async def _dispatch_sms_fallback() -> None:
                fallback = await asyncio.to_thread(
                    send_sms,
                    to_number=user.phone,
                    body_text=body_text,
                )
                if not fallback.delivered:
                    print(f"[GRAPHQL OTP] SMS fallback failed: {fallback.detail}")

            asyncio.create_task(_dispatch_sms_fallback())
            return
        user.email_otp_last_sent_at = 0
        await session.commit()
        raise ValueError("Email delivery is unavailable. Please try again later.")


def _to_gql(model: ErrandModel) -> Errand:
    return Errand(
        id=model.id,
        referenceNumber=getattr(model, "reference_number", None) or _make_reference_number(model.id),
        title=model.title,
        description=model.description,
        categoryId=getattr(model, "category_id", None),
        templateId=model.template_id,
        supportType=getattr(model, "support_type", None),
        preferredTime=getattr(model, "preferred_time", None),
        priorityLevel=getattr(model, "priority_level", None),
        distanceKm=getattr(model, "distance_km", None),
        finalPriceMinor=getattr(model, "final_price_minor", None),
        finalPriceCurrency=getattr(model, "final_price_currency", None),
        sensitivity=model.sensitivity,
        confirmationSentAt=getattr(model, "confirmation_sent_at", None),
        pickupLocation=model.pickup_location,
        dropoffLocation=model.dropoff_location,
        note=getattr(model, "note", None),
        status=model.status,
        issueReason=getattr(model, "issue_reason", None),
        issueNotes=getattr(model, "issue_notes", None),
        issueReportedAt=getattr(model, "issue_reported_at", None),
        issuePreferredResolution=getattr(model, "issue_preferred_resolution", None),
        issueStatus=getattr(model, "issue_status", None),
        issueResolvedAt=getattr(model, "issue_resolved_at", None),
        issueResolutionNotes=getattr(model, "issue_resolution_notes", None),
        issueEvidenceAttachmentIds=getattr(model, "issue_evidence_attachment_ids", None),
        created_at=model.created_at,
        userId=model.user_id,
        pickupTimeSlotStart=getattr(model, "pickup_time_slot_start", None),
        pickupTimeSlotEnd=getattr(model, "pickup_time_slot_end", None),
        pickupTimeSlotDate=getattr(model, "pickup_time_slot_date", None),
        assignedTo=getattr(model, "assigned_to", None),
        assignedAt=getattr(model, "assigned_at", None),
        pilotId=getattr(model, "pilot_id", None),
        reviewStatus=getattr(model, "review_status", None),
        reviewerRating=getattr(model, "reviewer_rating", None),
        reviewerNotes=getattr(model, "reviewer_notes", None),
        reviewCompletedAt=getattr(model, "review_completed_at", None),
    )


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def request_password_reset(
        self,
        info: Info,
        email: str,
        otpDeliveryChannel: str | None = None,
        otpDeliveryMode: str | None = None,
    ) -> bool:
        """Request password reset for a user (admin or regular). Sends OTP to email or SMS."""
        session: AsyncSession = info.context["db"]
        normalized_email = (email or "").strip().lower()
        print(f"[RESET] Password reset requested for: {normalized_email}")
        if not normalized_email:
            # For security, do not reveal details.
            return True

        result = await session.execute(auth_safe_user_by_email_query(normalized_email))
        user = result.scalars().first()
        if not user:
            print(f"[RESET] No user found for: {normalized_email}")
            # For security, do not reveal if user does not exist
            return True

        channel, mode = _normalize_otp_options(otpDeliveryChannel, otpDeliveryMode)
        if channel == "sms" and not user.phone:
            channel = "email"

        try:
            await _prepare_and_send_otp(
                session=session,
                user=user,
                purpose="password reset",
                channel=channel,
                mode=mode,
            )
        except ValueError as e:
            if channel == "sms":
                try:
                    await _prepare_and_send_otp(
                        session=session,
                        user=user,
                        purpose="password reset",
                        channel="email",
                        mode=mode,
                    )
                except Exception:
                    print(f"[GRAPHQL] Password reset OTP fallback failed: {e}")
            else:
                print(f"[GRAPHQL] Password reset OTP send failed: {e}")
        return True

    @strawberry.mutation
    async def update_profile(self, info: Info, input: UpdateProfileInput) -> UserProfile:
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")

        if not current_user_id:
            raise ValueError("Not authenticated")

        user = await session.get(User, current_user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
        if not user:
            raise ValueError("User not found")

        if input.firstName is not None:
            user.first_name = input.firstName or None
        if input.lastName is not None:
            user.last_name = input.lastName or None
        if input.phone is not None:
            user.phone = input.phone or None
        if input.addressLine1 is not None:
            user.address_line1 = input.addressLine1 or None
        if input.addressLine2 is not None:
            user.address_line2 = input.addressLine2 or None
        if input.city is not None:
            user.city = input.city or None
        if input.state is not None:
            user.state = input.state or None
        if input.postalCode is not None:
            user.postal_code = input.postalCode or None
        if input.country is not None:
            user.country = input.country or None

        await session.commit()
        await session.refresh(user)

        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        admin_emails_list = [e.strip() for e in admin_emails if e.strip()]
        is_admin = user.email.strip() in admin_emails_list

        return UserProfile(
            id=user.id,
            userUuid=_public_user_uuid(user),
            email=user.email,
            firstName=user.first_name,
            lastName=user.last_name,
            phone=user.phone,
            addressLine1=user.address_line1,
            addressLine2=user.address_line2,
            city=user.city,
            state=user.state,
            postalCode=user.postal_code,
            country=user.country,
            isEmailVerified=bool(user.is_email_verified),
            isAdmin=is_admin,
            profileImageUrl=getattr(user, "profile_image_url", None),
            transparency=None,
        )
    @strawberry.mutation
    async def create_errand(self, info: Info, input: CreateErrandInput) -> Errand:
        session: AsyncSession = info.context["db"]
        resolved_user_id = input.userId or info.context.get("current_user_id")
        if not resolved_user_id:
            raise ValueError("Missing user_id (not logged in)")

        try:
            resolved_user_id = int(resolved_user_id)
        except Exception:
            raise ValueError("Invalid user_id")

        enforce_payment = _env_truthy(os.getenv("ENFORCE_ERRAND_PAYMENT"))
        paid_session_row: StripeCheckoutSession | None = None

        if enforce_payment:
            sub_active = await session.scalar(
                select(ClientSubscription.id).where(
                    ClientSubscription.user_id == int(resolved_user_id),
                    ClientSubscription.plan == "plus",
                    ClientSubscription.status.in_(["active", "trialing"]),
                )
            )

            if not sub_active:
                payment_session_id = (getattr(input, "paymentSessionId", None) or "").strip()
                if not payment_session_id:
                    raise ValueError("Payment required")

                paid_session_row = await session.scalar(
                    select(StripeCheckoutSession)
                    .where(
                        StripeCheckoutSession.stripe_session_id == payment_session_id,
                        StripeCheckoutSession.user_id == int(resolved_user_id),
                    )
                    .with_for_update()
                )

                if (
                    not paid_session_row
                    or not bool(getattr(paid_session_row, "paid", False))
                    or getattr(paid_session_row, "used_for_errand_id", None) is not None
                ):
                    raise ValueError("Payment not verified")

        # With reference_number now NOT NULL at the DB layer, we must set a
        # placeholder value on insert (we'll overwrite it once we have the ID).
        placeholder_ref = _make_reference_number(int(time.time() * 1_000_000))

        # Scheduling inputs (backward compatible):
        # - Legacy pickupTimeSlot* fields (already supported)
        # - New schedule object + scheduleType
        pickup_time_start = None
        pickup_time_end = None
        pickup_time_slot_date = input.pickupTimeSlotDate

        schedule = getattr(input, "schedule", None)
        schedule_type = (getattr(input, "scheduleType", None) or "").strip().lower()
        if schedule is not None:
            schedule_kind = (getattr(schedule, "type", None) or schedule_type or "").strip().lower()
            if schedule_kind == "now":
                pickup_time_slot_date = None
                pickup_time_start = None
                pickup_time_end = None
            elif schedule_kind == "one_time":
                pickup_time_slot_date = getattr(schedule, "date", None) or pickup_time_slot_date
                start_time = getattr(schedule, "startTime", None)
                end_time = getattr(schedule, "endTime", None)
                # Convert date+time (HH:MM) into ISO-like strings and parse.
                if pickup_time_slot_date and start_time:
                    from datetime import datetime
                    pickup_time_start = datetime.fromisoformat(f"{pickup_time_slot_date}T{start_time}:00")
                if pickup_time_slot_date and end_time:
                    from datetime import datetime
                    pickup_time_end = datetime.fromisoformat(f"{pickup_time_slot_date}T{end_time}:00")

        # Parse legacy ISO slot strings if provided (frontends before schedule object).
        if pickup_time_start is None and input.pickupTimeSlotStart:
            from datetime import datetime
            pickup_time_start = datetime.fromisoformat(input.pickupTimeSlotStart.replace('Z', '+00:00'))
        if pickup_time_end is None and input.pickupTimeSlotEnd:
            from datetime import datetime
            pickup_time_end = datetime.fromisoformat(input.pickupTimeSlotEnd.replace('Z', '+00:00'))

        model = ErrandModel(
            reference_number=placeholder_ref,
            title=input.title,
            description=input.description,
            category_id=input.categoryId,
            template_id=input.templateId,
            support_type=input.supportType,
            preferred_time=input.preferredTime,
            priority_level=input.priorityLevel,
            distance_km=input.distanceKm,
            final_price_minor=input.finalPriceMinor,
            final_price_currency=input.finalPriceCurrency,
            sensitivity=input.sensitivity,
            pickup_location=input.pickupLocation,
            dropoff_location=input.dropoffLocation,
            note=getattr(input, "note", None),
            pickup_time_slot_start=pickup_time_start,
            pickup_time_slot_end=pickup_time_end,
            pickup_time_slot_date=pickup_time_slot_date,
            status="submitted",
            user_id=int(resolved_user_id),
        )
        session.add(model)
        await session.flush()

        # Assign reference number once ID exists.
        model.reference_number = _make_reference_number(model.id)

        # Mark the paid session as consumed for this errand (if used).
        if paid_session_row is not None:
            paid_session_row.used_for_errand_id = int(model.id)
            paid_session_row.used_at = datetime.now(timezone.utc)

        # Log event: errand created
        session.add(
            ErrandEvent(
                errand_id=model.id,
                event_type="created",
                old_status=None,
                new_status="submitted",
                note=None,
                user_id=int(resolved_user_id),
            )
        )

        await session.commit()
        await session.refresh(model)

        return _to_gql(model)

    @strawberry.mutation
    async def update_errand_status(self, info: Info, input: UpdateErrandStatusInput) -> Errand:
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")

        # Ensure the caller owns the errand.
        result = await session.execute(
            select(ErrandModel).where(
                ErrandModel.id == input.id,
                ErrandModel.user_id == current_user_id,
            )
        )
        model = result.scalars().first()
        if model is None:
            raise ValueError("Errand not found")

        previous_status = _normalize_status(model.status)
        next_status = _normalize_status(input.status)

        if next_status not in _CANONICAL_STATUSES:
            raise ValueError(
                "Invalid status. Expected one of: " + ", ".join(_CANONICAL_STATUSES)
            )

        if not _is_valid_transition(previous_status, next_status):
            raise ValueError(
                f"Invalid status transition: {previous_status} → {next_status}. "
                f"Expected next: {_CANONICAL_STATUSES[min(_CANONICAL_STATUSES.index(previous_status) + 1, len(_CANONICAL_STATUSES) - 1)]}"
            )

        model.status = next_status

        # Log event: status change
        from models import ErrandEvent
        event = ErrandEvent(
            errand_id=model.id,
            event_type="status_change",
            old_status=previous_status,
            new_status=next_status,
            note=None,
            user_id=current_user_id,
        )
        session.add(event)

        # If the errand is completed, automatically send a confirmation email once.
        should_auto_send = (
            next_status == "completed"
            and previous_status != "completed"
            and getattr(model, "confirmation_sent_at", None) is None
        )
        if should_auto_send:
            user = await session.get(User, current_user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
            if user and user.email:
                subject = f"Errand confirmation - #{model.id} ({model.title})"
                body = (
                    "Your errand is marked as completed. Here are the details:\n\n"
                    f"Errand ID: {model.id}\n"
                    f"Reference: {getattr(model, 'reference_number', None) or _make_reference_number(model.id)}\n"
                    f"Title: {model.title}\n"
                    f"Status: {model.status}\n"
                    f"Pickup: {model.pickup_location or '-'}\n"
                    f"Dropoff: {model.dropoff_location or '-'}\n\n"
                    "If anything looks wrong, reply to this email."
                )

                res = send_email(to_email=user.email, subject=subject, body_text=body)
                if res.delivered:
                    model.confirmation_sent_at = int(time.time())

        await session.commit()
        await session.refresh(model)

        try:
            await notify_customer_status(
                session,
                errand=model,
                old_status=previous_status,
                new_status=next_status,
                trigger="graphql-status-update",
            )
            if next_status in {"accepted", "completed"}:
                await notify_pilot_status(
                    session,
                    errand=model,
                    new_status=next_status,
                    trigger="graphql-status-update",
                )
        except Exception as e:
            print(f"[notify] graphql status update email failed: {e}")
        return _to_gql(model)

    @strawberry.mutation
    async def update_errand(self, info: Info, input: UpdateErrandInput) -> Errand:
        """Update errand details (title, description, locations, template, sensitivity)."""
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")

        # Ensure the caller owns the errand
        result = await session.execute(
            select(ErrandModel).where(
                ErrandModel.id == input.id,
                ErrandModel.user_id == current_user_id,
            )
        )
        model = result.scalars().first()
        if model is None:
            raise ValueError("Errand not found")

        # Update fields (only if provided)
        if input.title is not None:
            model.title = input.title
        if input.description is not None:
            model.description = input.description
        if input.templateId is not None:
            model.template_id = input.templateId
        if input.sensitivity is not None:
            model.sensitivity = input.sensitivity
        if input.pickupLocation is not None:
            model.pickup_location = input.pickupLocation
        if input.dropoffLocation is not None:
            model.dropoff_location = input.dropoffLocation
        if input.note is not None:
            model.note = input.note
        
        # Handle time slot updates
        if input.pickupTimeSlotStart is not None:
            from datetime import datetime
            model.pickup_time_slot_start = datetime.fromisoformat(input.pickupTimeSlotStart.replace('Z', '+00:00'))
        if input.pickupTimeSlotEnd is not None:
            from datetime import datetime
            model.pickup_time_slot_end = datetime.fromisoformat(input.pickupTimeSlotEnd.replace('Z', '+00:00'))
        if input.pickupTimeSlotDate is not None:
            model.pickup_time_slot_date = input.pickupTimeSlotDate

        await session.commit()
        await session.refresh(model)
        
        # Log event: errand edited
        from models import ErrandEvent
        event = ErrandEvent(
            errand_id=model.id,
            event_type="edited",
            old_status=None,
            new_status=None,
            note=f"Edited: {', '.join([k for k in ['title', 'description', 'template', 'sensitivity', 'pickup', 'dropoff', 'note'] if getattr(input, k.replace('pickup', 'pickupLocation').replace('dropoff', 'dropoffLocation'), None) is not None])}",
            user_id=current_user_id,
        )
        session.add(event)
        await session.commit()
        
        return _to_gql(model)

    @strawberry.mutation
    async def report_errand_issue(self, info: Info, input: ReportErrandIssueInput) -> Errand:
        """Customer reports an issue; locks in issue metadata and advances status."""
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")

        result = await session.execute(
            select(ErrandModel).where(
                ErrandModel.id == input.id,
                ErrandModel.user_id == current_user_id,
            )
        )
        model = result.scalars().first()
        if model is None:
            raise ValueError("Errand not found")

        reason = (input.reason or "").strip()
        if not reason:
            raise ValueError("Reason is required")
        if len(reason) > 120:
            raise ValueError("Reason is too long")

        notes = (input.notes or "").strip() or None
        if notes and len(notes) > 2000:
            raise ValueError("Notes is too long")

        preferred = (input.preferredResolution or "").strip() or None
        if preferred and len(preferred) > 120:
            raise ValueError("Preferred resolution is too long")

        evidence_ids = input.evidenceAttachmentIds or []
        # Keep this intentionally simple (string snapshot) for MVP.
        evidence_snapshot = ",".join(str(int(x)) for x in evidence_ids if x is not None) or None

        # Store metadata.
        setattr(model, "issue_reason", reason)
        setattr(model, "issue_notes", notes)
        setattr(model, "issue_reported_at", datetime.utcnow())

        # v2 metadata.
        if preferred is not None:
            setattr(model, "issue_preferred_resolution", preferred)
        if evidence_snapshot is not None:
            setattr(model, "issue_evidence_attachment_ids", evidence_snapshot)

        # Default dispute lifecycle.
        if getattr(model, "issue_status", None) is None:
            setattr(model, "issue_status", "open")

        # Move status forward to issue_reported (if possible).
        prev = _normalize_status(model.status)
        next_status = "issue_reported"

        # If the errand is already beyond issue_reported (e.g., completed), keep its status.
        # If it hasn't reached delivered yet, allow it to transition forward naturally.
        if next_status in _CANONICAL_STATUSES:
            try:
                prev_idx = _CANONICAL_STATUSES.index(prev)
                next_idx = _CANONICAL_STATUSES.index(next_status)
            except ValueError:
                prev_idx = None
                next_idx = None

            if prev_idx is not None and next_idx is not None:
                # Only apply if it's a valid forward move along the chain.
                if _is_valid_transition(prev, next_status):
                    model.status = next_status
                elif prev_idx > next_idx:
                    # Already past issue_reported in the chain; don't move backwards.
                    pass
                else:
                    # Not directly adjacent; leave status as-is (prevents skipping).
                    pass

        await session.commit()
        await session.refresh(model)
        return _to_gql(model)

    @strawberry.mutation
    async def send_errand_confirmation(self, info: Info, input: SendErrandConfirmationInput) -> bool:
        """Send an errand details confirmation email to the customer."""
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")

        # Ensure the caller owns the errand.
        result = await session.execute(
            select(ErrandModel).where(
                ErrandModel.id == input.id,
                ErrandModel.user_id == current_user_id,
            )
        )
        errand = result.scalars().first()
        if errand is None:
            raise ValueError("Errand not found")

        user = await session.get(User, current_user_id)
        if not user or not user.email:
            raise ValueError("User not found")

        subject = f"Errand confirmation - #{errand.id} ({errand.title})"
        body = (
            "Your errand details:\n\n"
            f"Errand ID: {errand.id}\n"
            f"Reference: {getattr(errand, 'reference_number', None) or _make_reference_number(errand.id)}\n"
            f"Title: {errand.title}\n"
            f"Status: {errand.status}\n"
            f"Pickup: {errand.pickup_location or '-'}\n"
            f"Dropoff: {errand.dropoff_location or '-'}\n\n"
            "If anything looks wrong, reply to this email."
        )

        res = send_email(to_email=user.email, subject=subject, body_text=body)
        if not res.delivered:
            raise ValueError(res.detail or "Failed to send confirmation")

        # Record that we've sent at least one confirmation.
        if getattr(errand, "confirmation_sent_at", None) is None:
            errand.confirmation_sent_at = int(time.time())
            await session.commit()
        return True

    @strawberry.mutation
    async def delete_errand(self, info: Info, id: int) -> bool:
        """Delete an errand and all its associated attachments."""
        print(f"[DELETE_ERRAND] Called with id={id}")
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        print(f"[DELETE_ERRAND] current_user_id={current_user_id}")
        if not current_user_id:
            print("[DELETE_ERRAND] ERROR: No current_user_id")
            raise ValueError("Missing user_id (not logged in)")

        # Ensure the caller owns the errand
        result = await session.execute(
            select(ErrandModel).where(
                ErrandModel.id == id,
                ErrandModel.user_id == current_user_id,
            )
        )
        errand = result.scalars().first()
        print(f"[DELETE_ERRAND] Found errand={errand}")
        if errand is None:
            print("[DELETE_ERRAND] ERROR: Errand not found or permission denied")
            raise ValueError("Errand not found or you do not have permission to delete it")

        # Delete all attachments associated with this errand first
        from models import ErrandAttachment
        await session.execute(
            delete(ErrandAttachment).where(ErrandAttachment.errand_id == id)
        )

        # Delete all events associated with this errand
        from models import ErrandEvent
        await session.execute(
            delete(ErrandEvent).where(ErrandEvent.errand_id == id)
        )

        # Delete the errand itself
        await session.execute(
            delete(ErrandModel).where(ErrandModel.id == id)
        )
        await session.commit()
        print(f"[DELETE_ERRAND] ✅ Successfully deleted errand id={id}")
        return True

    @strawberry.mutation
    async def assign_errand(self, info: Info, errand_id: int) -> Errand:
        """Admin assigns an errand to themselves (or an admin can assign to another admin)."""
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")
        
        # Check if current user is admin using proper admin verification
        from admin_utils import require_admin_user
        try:
            admin_user = await require_admin_user(session, current_user_id)
        except Exception as e:
            raise ValueError(f"Only admins can assign errands: {str(e)}")
        
        # Get the errand
        errand_result = await session.execute(
            select(ErrandModel).where(ErrandModel.id == errand_id)
        )
        errand = errand_result.scalars().first()
        if not errand:
            raise ValueError("Errand not found")
        
        # Check status is 'submitted'
        if _normalize_status(errand.status) != "submitted":
            raise ValueError(f"Can only assign errands with 'submitted' status, current: {errand.status}")
        
        # Assign to current admin
        errand.assigned_to = current_user_id
        errand.assigned_at = datetime.now()
        
        # Change status to 'assigned'
        errand.status = "assigned"
        
        # Log event
        from models import ErrandEvent
        event = ErrandEvent(
            errand_id=errand.id,
            event_type="assigned",
            old_status="submitted",
            new_status="assigned",
            note=f"Assigned to admin user {admin_user.email}",
            user_id=current_user_id,
        )
        session.add(event)
        
        await session.commit()
        await session.refresh(errand)

        try:
            await notify_customer_status(
                session,
                errand=errand,
                old_status="submitted",
                new_status="assigned",
                trigger="graphql-assign",
            )
        except Exception as e:
            print(f"[notify] assign errand email failed: {e}")
        return _to_gql(errand)

    @strawberry.mutation
    async def approve_errand(self, info: Info, errand_id: int, notes: str = "") -> Errand:
        """Admin approves an assigned errand and changes status to 'approved'."""
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")
        
        # Check if current user is admin using proper admin verification
        from admin_utils import require_admin_user
        try:
            admin_user = await require_admin_user(session, current_user_id)
        except Exception as e:
            raise ValueError(f"Only admins can approve errands: {str(e)}")
        
        # Get the errand
        errand_result = await session.execute(
            select(ErrandModel).where(ErrandModel.id == errand_id)
        )
        errand = errand_result.scalars().first()
        if not errand:
            raise ValueError("Errand not found")
        
        # Check status is 'assigned'
        if _normalize_status(errand.status) != "assigned":
            raise ValueError(f"Can only approve 'assigned' errands, current: {errand.status}")
        
        # Update status to approved
        old_status = errand.status
        errand.status = "approved"
        
        # Log event
        from models import ErrandEvent
        event = ErrandEvent(
            errand_id=errand.id,
            event_type="approved",
            old_status=old_status,
            new_status="approved",
            note=f"Approved by admin {admin_user.email}" + (f": {notes}" if notes else ""),
            user_id=current_user_id,
        )
        session.add(event)
        
        await session.commit()
        await session.refresh(errand)
        return _to_gql(errand)

    @strawberry.mutation
    async def mark_errand_done(self, info: Info, errand_id: int) -> Errand:
        """Admin or customer marks errand as done (completed)."""
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")
        
        # Get the errand
        errand_result = await session.execute(
            select(ErrandModel).where(ErrandModel.id == errand_id)
        )
        errand = errand_result.scalars().first()
        if not errand:
            raise ValueError("Errand not found")
        
        # Check if current user is the customer or the assigned admin
        is_customer = errand.user_id == current_user_id
        is_assigned_admin = errand.assigned_to == current_user_id
        
        if not (is_customer or is_assigned_admin):
            raise ValueError("Only the customer or assigned admin can mark this errand as done")
        
        # Check status is 'assigned'
        if _normalize_status(errand.status) != "assigned":
            raise ValueError(f"Can only mark 'assigned' errands as done, current: {errand.status}")
        
        # Change status to 'completed'
        previous_status = errand.status
        errand.status = "completed"
        errand.review_status = "pending"  # Ready for customer review
        
        # Log event
        from models import ErrandEvent
        event = ErrandEvent(
            errand_id=errand.id,
            event_type="completed",
            old_status=previous_status,
            new_status="completed",
            note=f"Marked as done by {'customer' if is_customer else 'admin'} user {current_user_id}",
            user_id=current_user_id,
        )
        session.add(event)
        
        await session.commit()
        await session.refresh(errand)

        try:
            await notify_customer_status(
                session,
                errand=errand,
                old_status=previous_status,
                new_status="completed",
                trigger="graphql-mark-done",
            )
            await notify_pilot_status(
                session,
                errand=errand,
                new_status="completed",
                trigger="graphql-mark-done",
            )
        except Exception as e:
            print(f"[notify] mark errand done email failed: {e}")
        return _to_gql(errand)

    @strawberry.mutation
    async def confirm_errand_received(self, info: Info, errand_id: int) -> Errand:
        """Customer confirms they have received the completed errand/report.

        This transitions the errand from 'completed' -> 'accepted'.
        """
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")

        errand_result = await session.execute(
            select(ErrandModel).where(ErrandModel.id == errand_id)
        )
        errand = errand_result.scalars().first()
        if not errand:
            raise ValueError("Errand not found")

        if int(errand.user_id) != int(current_user_id):
            raise ValueError("Only the customer can confirm receipt for this errand")

        if _normalize_status(errand.status) != "completed":
            raise ValueError(
                f"Can only confirm receipt for completed errands, current: {errand.status}"
            )

        old_status = errand.status
        errand.status = "accepted"

        from models import ErrandEvent

        event = ErrandEvent(
            errand_id=errand.id,
            event_type="accepted",
            old_status=old_status,
            new_status="accepted",
            note=f"Customer confirmed receipt (user_id={current_user_id})",
            user_id=current_user_id,
        )
        session.add(event)

        await session.commit()
        await session.refresh(errand)

        try:
            await notify_pilot_status(
                session,
                errand=errand,
                new_status="accepted",
                trigger="graphql-confirm-received",
            )
        except Exception as e:
            print(f"[notify] confirm receipt email failed: {e}")

        return _to_gql(errand)

    @strawberry.mutation
    async def cancel_errand(
        self,
        info: Info,
        errand_id: int,
        agree_to_deduction: bool,
        reason: Optional[str] = None,
    ) -> Errand:
        """Customer cancels an errand.

        Policy:
        - Before a pilot is assigned: cancel with zero charges.
        - After allocation/dispatch: cancellation may incur deductions based on work started.

        This mutation records the user's consent and moves the errand into a terminal
        cancelled state so it appears in Archive.

        NOTE: This does not execute a payment refund; it only changes state + logs an event.
        """

        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")

        errand_result = await session.execute(
            select(ErrandModel).where(ErrandModel.id == errand_id)
        )
        errand = errand_result.scalars().first()
        if not errand:
            raise ValueError("Errand not found")

        if int(errand.user_id) != int(current_user_id):
            raise ValueError("Only the customer can cancel this errand")

        status_key = _normalize_status(errand.status)
        if status_key in {"cancelled", "accepted"}:
            raise ValueError(f"Errand is already {status_key}")
        if status_key in {"delivered", "completed"}:
            raise ValueError(
                "This errand is already completed. Please use Done → review instead of cancelling."
            )

        # Classify the cancellation stage.
        # If no pilot is assigned yet, cancellation is free (zero charge).
        pilot_id = getattr(errand, "pilot_id", None)
        pre_assignment_statuses = {"pending", "submitted"}
        stage = (
            "pre-assignment"
            if status_key in pre_assignment_statuses and not pilot_id
            else "after-allocation"
        )

        # Require explicit consent only when charges/deductions may apply.
        if stage != "pre-assignment" and not agree_to_deduction:
            raise ValueError(
                "Cancellation requires agreeing to the deduction/refund policy."
            )

        old_status = errand.status
        errand.status = "cancelled"

        from models import ErrandEvent

        reason_clean = (reason or "").strip()
        note_parts = [
            f"Customer cancelled ({stage})",
            "Policy consent: agreed" if agree_to_deduction else "Policy consent: not required",
        ]
        if stage == "pre-assignment":
            note_parts.append("Policy: zero charge (no pilot assigned)")
        else:
            note_parts.append("Policy: deductions may apply based on work started")
        if reason_clean:
            note_parts.append(f"Reason: {reason_clean}")

        event = ErrandEvent(
            errand_id=errand.id,
            event_type="customer_cancelled",
            old_status=old_status,
            new_status="cancelled",
            note=" | ".join(note_parts),
            user_id=current_user_id,
        )
        session.add(event)

        await session.commit()
        await session.refresh(errand)

        # Best-effort notifications.
        try:
            await notify_pilot_status(
                session,
                errand=errand,
                new_status="cancelled",
                trigger="graphql-cancel",
            )
        except Exception as e:
            print(f"[notify] cancel errand pilot email failed: {e}")

        return _to_gql(errand)

    @strawberry.mutation
    async def submit_errand_review(self, info: Info, errand_id: int, rating: int, notes: str = None) -> Errand:
        """Customer submits a review after errand completion."""
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            raise ValueError("Missing user_id (not logged in)")
        
        # Get the errand
        errand_result = await session.execute(
            select(ErrandModel).where(ErrandModel.id == errand_id)
        )
        errand = errand_result.scalars().first()
        if not errand:
            raise ValueError("Errand not found")
        
        # Only customer can review
        if errand.user_id != current_user_id:
            raise ValueError("Only the customer can review this errand")
        
        # Check status is 'completed'
        if _normalize_status(errand.status) != "completed":
            raise ValueError(f"Can only review completed errands, current: {errand.status}")

        # Prevent duplicate rewards + review spam.
        if (errand.review_status or "").strip().lower() == "reviewed":
            raise ValueError("Review already submitted")
        
        # Validate rating
        if rating < 1 or rating > 5:
            raise ValueError("Rating must be between 1 and 5")
        
        # Validate notes
        if notes and len(notes) > 1000:
            raise ValueError("Review notes are too long (max 1000 characters)")
        
        # Store review
        errand.reviewer_rating = rating
        errand.reviewer_notes = notes or None
        errand.review_status = "reviewed"
        errand.review_completed_at = datetime.now()
        
        # Log event
        from models import ErrandEvent
        event = ErrandEvent(
            errand_id=errand.id,
            event_type="reviewed",
            old_status=None,
            new_status=None,
            note=f"Customer review: {rating} stars",
            user_id=current_user_id,
        )
        session.add(event)
        
        await session.commit()
        await session.refresh(errand)

        # Best-effort: issue a one-time promo code reward tied to this user.
        # We key by source=review_reward:<errand_id> to make this idempotent.
        try:
            from models import PromoCode
            from promo_code_service import issue_promo_code

            source = f"review_reward:{int(errand.id)}"
            existing = await session.scalar(
                select(PromoCode)
                .where(PromoCode.user_id == int(current_user_id))
                .where(PromoCode.source == source)
            )
            if not existing:
                await issue_promo_code(
                    session,
                    user_id=int(current_user_id),
                    percent_off=10,
                    max_redemptions=1,
                    created_by_admin_id=None,
                    source=source,
                    prefix="EB10",
                )
        except Exception as e:
            print(f"[promo] review reward issuance failed: {e}", flush=True)

        return _to_gql(errand)

    @strawberry.mutation
    async def login(self, info: Info, input: LoginInput) -> AuthResponse:
        """Login a user with email or phone and password"""
        from auth import create_access_token, create_refresh_token, is_email_confirmation_disabled, verify_password
        import os
        session: AsyncSession = info.context["db"]
        disable_email_confirmation = is_email_confirmation_disabled()
        role = (input.role or "client").strip().lower()
        if role not in {"client", "pilot"}:
            raise ValueError("Invalid role. Use client or pilot.")

        identifier = (input.email or "").strip()
        if not identifier:
            raise ValueError("Invalid email or password")
        
        user = await _get_auth_user_by_identifier(session, identifier)
        
        if not user or not verify_password(input.password, user.password_hash):
            raise ValueError("Invalid email or password")
        
        if not disable_email_confirmation and not user.is_email_verified:
            raise ValueError("Email not verified - please verify your email first")

        if role == "pilot" and not user.is_pilot:
            raise ValueError("This account is not registered as a pilot")
        if role == "client" and user.is_pilot:
            raise ValueError("Pilot accounts must sign in via Pilot mode")
        
        # Create token
        token = create_access_token(user_id=user.id)
        refresh_token = create_refresh_token(user_id=user.id)
        
        # Check if user is admin
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        admin_emails_list = [e.strip().lower() for e in admin_emails if e.strip()]
        is_admin = user.email.strip().lower() in admin_emails_list
        
        return AuthResponse(
            accessToken=token,
            refreshToken=refresh_token,
            userId=user.id,
            userUuid=_public_user_uuid(user),
            email=user.email,
            firstName=user.first_name,
            lastName=user.last_name,
            phone=user.phone,
            addressLine1=user.address_line1,
            addressLine2=user.address_line2,
            city=user.city,
            state=user.state,
            postalCode=user.postal_code,
            country=user.country,
            isEmailVerified=bool(user.is_email_verified),
            isAdmin=is_admin,
        )

    @strawberry.mutation
    async def signup(self, info: Info, input: SignupInput) -> AuthResponse:
        """Sign up a new user"""
        from auth import create_access_token, create_refresh_token, hash_password, is_email_confirmation_disabled
        import os
        session: AsyncSession = info.context["db"]
        disable_email_confirmation = is_email_confirmation_disabled()
        channel, mode = _normalize_otp_options(input.otpDeliveryChannel, input.otpDeliveryMode)
        role = (input.role or "client").strip().lower()
        if role not in {"client", "pilot"}:
            raise ValueError("Invalid role. Use client or pilot.")
        
        raw_identifier = (input.email or "").strip()
        raw_phone = (input.phone or "").strip()
        if not raw_identifier:
            raise ValueError("Enter a valid email address or phone number")

        identifier_kind = "phone" if is_phone_identifier(raw_identifier) else "email"
        if identifier_kind == "phone":
            normalized_phone = normalize_phone_for_storage(raw_phone or raw_identifier)
            if not normalized_phone:
                raise ValueError("Invalid phone number")
            email = build_phone_alias_email(normalized_phone, role=role)
            existing = await _get_auth_user_by_phone(session, normalized_phone)
        else:
            email = _normalize_signup_email(raw_identifier)
            normalized_phone = normalize_phone_for_storage(raw_phone) or None
            existing = await _get_auth_user_by_email(session, email)

        phone_owner = await _get_auth_user_by_phone(session, normalized_phone) if normalized_phone else None
        if phone_owner and (not existing or phone_owner.id != existing.id):
            if phone_owner.is_pilot != (role == "pilot"):
                raise ValueError("Phone number already registered for a different account type")
            raise ValueError("Phone number already registered")

        if existing:
            if existing.is_pilot != (role == "pilot"):
                conflict_label = "Phone number" if identifier_kind == "phone" else "Email"
                raise ValueError(f"{conflict_label} already registered for a different account type")
            # If the account exists but isn't verified, resend OTP for the same email.
            if not existing.is_email_verified:
                if disable_email_confirmation:
                    existing.is_email_verified = True
                    existing.email_otp_hash = None
                    existing.email_otp_expires_at = None
                    existing.email_otp_last_sent_at = None
                    existing.email_otp_attempts = 0
                    await session.commit()
                    token = create_access_token(user_id=existing.id)
                    refresh_token = create_refresh_token(user_id=existing.id)
                    admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
                    is_admin = existing.email.strip() in [e.strip() for e in admin_emails if e.strip()]
                    return AuthResponse(
                        accessToken=token,
                        refreshToken=refresh_token,
                        userId=existing.id,
                        userUuid=_public_user_uuid(existing),
                        email=existing.email,
                        firstName=existing.first_name,
                        lastName=existing.last_name,
                        phone=existing.phone,
                        addressLine1=existing.address_line1,
                        addressLine2=existing.address_line2,
                        city=existing.city,
                        state=existing.state,
                        postalCode=existing.postal_code,
                        country=existing.country,
                        isEmailVerified=True,
                        isAdmin=is_admin,
                    )
                await _prepare_and_send_otp(
                    session=session,
                    user=existing,
                    purpose="confirmation",
                    channel=("sms" if identifier_kind == "phone" else channel),
                    mode=mode,
                )

                raise ValueError("Email pending verification. We sent a new code.")
            raise ValueError("Phone number already registered" if identifier_kind == "phone" else "Email already registered")
        
        # Create new user
        first_name = (input.firstName or "").strip()
        last_name = (input.lastName or "").strip()
        if not first_name or not last_name:
            raise ValueError("First and last name are required for signup.")

        user = User(
            email=email,
            password_hash=hash_password(input.password),
            first_name=first_name,
            last_name=last_name,
            phone=normalized_phone,
            address_line1=input.addressLine1,
            address_line2=input.addressLine2,
            city=input.city,
            state=input.state,
            postal_code=input.postalCode,
            country=input.country,
            is_email_verified=disable_email_confirmation,
            is_pilot=(role == "pilot"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        
        if not disable_email_confirmation:
            await _prepare_and_send_otp(
                session=session,
                user=user,
                purpose="signup confirmation",
                channel=("sms" if identifier_kind == "phone" else channel),
                mode=mode,
            )
        
        # Return token (account will be unverified until email is confirmed)
        token = create_access_token(user_id=user.id)
        refresh_token = create_refresh_token(user_id=user.id)
        
        # Check if user is admin
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        admin_emails_list = [e.strip().lower() for e in admin_emails if e.strip()]
        is_admin = user.email.strip().lower() in admin_emails_list

        return AuthResponse(
            accessToken=token,
            refreshToken=refresh_token,
            userId=user.id,
            userUuid=_public_user_uuid(user),
            email=user.email,
            firstName=user.first_name,
            lastName=user.last_name,
            phone=user.phone,
            addressLine1=user.address_line1,
            addressLine2=user.address_line2,
            city=user.city,
            state=user.state,
            postalCode=user.postal_code,
            country=user.country,
            isEmailVerified=bool(user.is_email_verified),
            isAdmin=is_admin,
        )


@strawberry.type
class Query:
    @strawberry.field
    async def clientLifecycle(self, info: Info) -> ClientLifecycle:
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")

        if not current_user_id:
            snapshot = build_client_lifecycle_snapshot(
                user=None,
                errands=[],
                promo_codes=[],
                public_base_url=_referral_public_base_url(),
            )
            return ClientLifecycle(**snapshot)

        user = await session.get(User, current_user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
        errands_result = await session.execute(
            select(ErrandModel)
            .where(ErrandModel.user_id == current_user_id)
            .order_by(ErrandModel.created_at.desc())
        )
        errands = errands_result.scalars().all()

        from models import PromoCode

        promo_result = await session.execute(
            select(PromoCode)
            .where(PromoCode.user_id == current_user_id)
            .order_by(PromoCode.created_at.desc())
        )
        promo_codes = promo_result.scalars().all()

        snapshot = build_client_lifecycle_snapshot(
            user=user,
            errands=errands,
            promo_codes=promo_codes,
            public_base_url=_referral_public_base_url(),
        )
        return ClientLifecycle(**snapshot)

    @strawberry.field
    async def me(self, info: Info) -> Optional[UserProfile]:
        """Get current logged-in user's profile"""
        import os
        from models import ErrandAttachment
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        
        if not current_user_id:
            return None
        
        user = await session.get(User, current_user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
        if not user:
            return None
        
        # Check if user is admin based on ADMIN_EMAILS environment variable
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        admin_emails_list = [e.strip() for e in admin_emails if e.strip()]
        is_admin = user.email.strip() in admin_emails_list
        
        # Get transparency data
        # Count completed errands (jobs that are finished)
        completed_statuses = {"completed", "accepted", "delivered"}
        completed_q = await session.execute(
            select(ErrandModel)
            .where(
                ErrandModel.user_id == current_user_id,
                ErrandModel.status.in_(completed_statuses),
            )
        )
        completed_count = len(completed_q.scalars().all())
        print(f"[ME QUERY] user_id={current_user_id}, completed_count={completed_count}")

        # Count all documents uploaded
        docs_q = await session.execute(
            select(ErrandAttachment)
            .join(ErrandModel, ErrandModel.id == ErrandAttachment.errand_id)
            .where(ErrandModel.user_id == current_user_id)
        )
        docs_count = len(docs_q.scalars().all())
        print(f"[ME QUERY] user_id={current_user_id}, docs_count={docs_count}")
        
        return UserProfile(
            id=user.id,
            userUuid=_public_user_uuid(user),
            email=user.email,
            firstName=user.first_name,
            lastName=user.last_name,
            phone=user.phone,
            addressLine1=user.address_line1,
            addressLine2=user.address_line2,
            city=user.city,
            state=user.state,
            postalCode=user.postal_code,
            country=user.country,
            isEmailVerified=bool(user.is_email_verified),
            isAdmin=is_admin,
            profileImageUrl=getattr(user, "profile_image_url", None),
            transparency=Transparency(
                completed_errands=int(completed_count),
                documents_handled=int(docs_count)
            )
        )

    @strawberry.field
    async def errands(self, info: Info) -> list[Errand]:
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        
        # Return only the current user's errands if logged in
        if not current_user_id:
            return []
        
        result = await session.execute(
            select(ErrandModel).where(
                ErrandModel.user_id == current_user_id
            ).order_by(ErrandModel.created_at.desc())
        )
        rows = result.scalars().all()
        return [_to_gql(m) for m in rows]

    @strawberry.field
    async def errand(self, info: Info, id: int) -> Optional[Errand]:
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            return None

        # Determine admin state (same logic as `me`).
        admin_emails = os.getenv("ADMIN_EMAILS", "").split(",")
        admin_emails_list = [e.strip() for e in admin_emails if e.strip()]
        user = await session.get(User, current_user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
        is_admin = bool(user and user.email and user.email.strip() in admin_emails_list)

        # Access control:
        # - Admin users may fetch any errand by ID.
        # - Non-admin users may only fetch their own errand by ID.
        stmt = select(ErrandModel).where(ErrandModel.id == id)
        if not is_admin:
            stmt = stmt.where(ErrandModel.user_id == current_user_id)

        result = await session.execute(stmt)
        model = result.scalars().first()
        return _to_gql(model) if model else None

    @strawberry.field
    async def errandsByIds(self, info: Info, ids: list[int]) -> list[Errand]:
        """Fetch a specific set of errands by id.

        Used by the frontend for granular per-errand polling.
        Access control:
        - Non-admin users can only fetch their own errands.
        - Admin users can fetch any errand.
        """
        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            return []

        # Determine admin state (same logic as `me`).
        admin_emails = os.getenv("ADMIN_EMAILS", "").split(",")
        admin_emails_list = [e.strip() for e in admin_emails if e.strip()]
        user = await session.get(User, current_user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
        is_admin = bool(user and user.email and user.email.strip() in admin_emails_list)

        ids_norm = [int(i) for i in (ids or []) if i is not None]
        if not ids_norm:
            return []

        stmt = select(ErrandModel).where(ErrandModel.id.in_(ids_norm))
        if not is_admin:
            stmt = stmt.where(ErrandModel.user_id == current_user_id)

        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [_to_gql(m) for m in rows]

    @strawberry.field
    async def errandTimelineEvents(
        self,
        info: Info,
        errandIds: list[int] | None = None,
        sinceId: int | None = None,
        limit: int = 50,
        order: SortOrder = SortOrder.ASC,
    ) -> list[ErrandTimelineEvent]:
        """Return timeline events for the current user's errands.

        Designed for lightweight client polling:
        - `sinceId`: only return events with id > sinceId.
        - `errandIds`: optionally restrict to specific errands.
        - `order`: ASC for chronological playback, DESC for latest-only sampling.
        """

        session: AsyncSession = info.context["db"]
        current_user_id = info.context.get("current_user_id")
        if not current_user_id:
            return []

        # Determine admin state (same logic as `me`).
        admin_emails = os.getenv("ADMIN_EMAILS", "").split(",")
        admin_emails_list = [e.strip() for e in admin_emails if e.strip()]
        user = await session.get(User, current_user_id, options=AUTH_SAFE_USER_LOAD_OPTIONS)
        is_admin = bool(user and user.email and user.email.strip() in admin_emails_list)

        from models import ErrandEvent

        safe_limit = 50
        try:
            safe_limit = int(limit or 50)
        except Exception:
            safe_limit = 50
        safe_limit = max(1, min(safe_limit, 200))

        stmt = (
            select(ErrandEvent, ErrandModel)
            .join(ErrandModel, ErrandModel.id == ErrandEvent.errand_id)
        )
        if not is_admin:
            stmt = stmt.where(ErrandModel.user_id == current_user_id)

        ids_norm: list[int] | None = None
        if errandIds is not None:
            ids_norm = [int(i) for i in (errandIds or []) if i is not None]
            if not ids_norm:
                return []
            stmt = stmt.where(ErrandEvent.errand_id.in_(ids_norm))

        if sinceId is not None:
            try:
                stmt = stmt.where(ErrandEvent.id > int(sinceId))
            except Exception:
                # If the client passes garbage, treat as "no since".
                pass

        if order == SortOrder.DESC:
            stmt = stmt.order_by(ErrandEvent.id.desc())
        else:
            stmt = stmt.order_by(ErrandEvent.id.asc())

        stmt = stmt.limit(safe_limit)

        result = await session.execute(stmt)
        rows = result.all()

        events: list[ErrandTimelineEvent] = []
        for (e, errand) in rows:
            reference = getattr(errand, "reference_number", None) or _make_reference_number(
                int(getattr(errand, "id", 0) or 0)
            )
            created_at = getattr(e, "created_at", None) or datetime.now(timezone.utc)
            events.append(
                ErrandTimelineEvent(
                    id=int(e.id),
                    errandId=int(e.errand_id),
                    referenceNumber=str(reference),
                    errandTitle=str(getattr(errand, "title", "") or ""),
                    eventType=str(getattr(e, "event_type", "") or "status_update"),
                    oldStatus=getattr(e, "old_status", None),
                    newStatus=getattr(e, "new_status", None),
                    note=getattr(e, "note", None),
                    createdAt=created_at,
                    userId=getattr(e, "user_id", None),
                )
            )

        return events

schema = strawberry.Schema(query=Query, mutation=Mutation)
