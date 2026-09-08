"""Errand messaging API

Provides lightweight, in-app chat between the errand owner (customer) and the assigned pilot.

Access control:
- Errand owner
- Assigned pilot
- Admin

This is intentionally REST (not GraphQL) so both the web app and mobile shells can use it easily.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.utils.admin_utils import require_admin_user
from app.dto import ErrandMessagesResponse, FlexibleId
from auth import decode_access_token
from database import get_db
from models import Errand, ErrandMessage, User

router = APIRouter(prefix="/errands", tags=["errand-messages"])


_EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    flags=re.IGNORECASE,
)

# Broad phone matcher; we validate digit-count before redacting.
_PHONE_CANDIDATE_RE = re.compile(
    r"(?<!\w)(\+?\d[\d\s().-]{7,}\d)(?!\w)",
    flags=re.IGNORECASE,
)


def _redact_contact_info(text: str) -> str:
    """Redact emails and phone-like sequences.

    Intended to reduce sharing personal contact details between customer and pilot.
    Admins can still view the raw transcript.
    """

    if not text:
        return text

    redacted = _EMAIL_RE.sub("⛔ [contact removed]", text)

    def _phone_repl(match: re.Match[str]) -> str:
        candidate = match.group(1) or ""
        digits = re.sub(r"\D", "", candidate)
        # Require a reasonable phone digit count to reduce false positives.
        if 9 <= len(digits) <= 16:
            return "⛔ [contact removed]"
        return candidate

    return _PHONE_CANDIDATE_RE.sub(_phone_repl, redacted)


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


def _normalize_status(value: Optional[str]) -> str:
    """Normalize status values for defensive comparisons."""
    if not value:
        return ""
    key = str(value).strip().lower()
    key = "_".join(key.replace("-", " ").split())
    return key


async def _get_current_user(
    authorization: Optional[str],
    db: AsyncSession,
) -> User:
    token = _extract_bearer(authorization)
    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    user = await db.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


async def _is_admin(db: AsyncSession, user: User) -> bool:
    try:
        await require_admin_user(db, user.id)
        return True
    except HTTPException:
        return False


async def _require_participant(
    db: AsyncSession, *, errand_id: str, user: User
) -> Errand:
    errand = await db.get(Errand, errand_id)
    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")

    if await _is_admin(db, user):
        return errand

    is_owner = int(errand.user_id) == int(user.id)
    is_pilot = bool(errand.pilot_id) and int(errand.pilot_id) == int(user.id)

    if not (is_owner or is_pilot):
        raise HTTPException(status_code=403, detail="Not allowed")

    return errand


class ErrandMessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ErrandMessageOut(BaseModel):
    id: str
    message: str
    sender_id: str
    sender_type: str
    sender_name: str
    mine: bool
    created_at: datetime


@router.get("/{errand_id}/messages", response_model=ErrandMessagesResponse, operation_id="listErrandMessages", summary="Get errand chat messages", description="Retrieve chronological chat history between customer and pilot for an errand.")
async def list_errand_messages(
    errand_id: str,
    limit: int = 50,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_current_user(authorization, db)
    errand = await _require_participant(db, errand_id=errand_id, user=user)

    viewer_is_admin = await _is_admin(db, user)
    errand_owner_id = str(errand.user_id)
    errand_pilot_id = str(errand.pilot_id) if errand.pilot_id else None

    safe_limit = max(1, min(int(limit or 50), 200))

    # Join sender to avoid N+1 fetching.
    result = await db.execute(
        select(ErrandMessage, User)
        .join(User, User.id == ErrandMessage.sender_id)
        .where(ErrandMessage.errand_id == errand.id)
        .order_by(desc(ErrandMessage.created_at), desc(ErrandMessage.id))
        .limit(safe_limit)
    )

    rows = result.all()
    # Return ascending for chat UI.
    rows.reverse()

    messages: list[dict] = []
    for msg, sender in rows:
        sender_type = "unknown"
        if errand_pilot_id and str(sender.id) == str(errand_pilot_id):
            sender_type = "pilot"
        elif str(sender.id) == str(errand_owner_id):
            sender_type = "customer"

        mine = str(sender.id) == str(user.id)
        body = msg.message
        if not viewer_is_admin and not mine:
            body = _redact_contact_info(body)

        sender_name = (
            " ".join([p for p in [sender.first_name, sender.last_name] if p])
            or sender.email
            or ("Pilot" if sender_type == "pilot" else "Customer")
        )

        messages.append(
            {
                "id": msg.id,
                "message": body,
                "sender_id": sender.id,
                "sender_type": sender_type,
                "sender_name": sender_name,
                "mine": mine,
                "created_at": msg.created_at,
            }
        )

    return {"messages": messages}


@router.post("/{errand_id}/messages", response_model=ErrandMessageOut, operation_id="sendErrandMessage", summary="Send errand chat message", description="Post a message in the direct errand conversation thread.")
async def send_errand_message(
    errand_id: str,
    payload: ErrandMessageIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_current_user(authorization, db)
    errand = await _require_participant(db, errand_id=errand_id, user=user)

    # Server-side enforcement: once an errand is terminal, the chat becomes read-only.
    status_key = _normalize_status(getattr(errand, "status", None))
    if (
        status_key in {"completed", "cancelled"}
        or getattr(errand, "completed_at", None) is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="Chat is locked for this errand.",
        )

    text = (payload.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    msg = ErrandMessage(errand_id=errand.id, sender_id=user.id, message=text)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    sender_type = (
        "pilot"
        if errand.pilot_id and int(user.id) == int(errand.pilot_id)
        else "customer"
    )
    sender_name = (
        " ".join([p for p in [user.first_name, user.last_name] if p])
        or user.email
        or sender_type.title()
    )

    return ErrandMessageOut(
        id=int(msg.id),
        message=msg.message,
        sender_id=int(user.id),
        sender_type=sender_type,
        sender_name=sender_name,
        mine=True,
        created_at=msg.created_at,
    )
