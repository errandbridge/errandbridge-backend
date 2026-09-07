from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.admin_utils import require_admin_user
from auth import decode_access_token
from database import get_db
from models import SupportConversation, SupportMessage, User
from app.services.emailer import send_email
from app.utils.notification_utils import notify_admin_support_handoff

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

router = APIRouter(prefix="/support", tags=["support"])


def _require_user_id_from_token(token: Optional[str]) -> int:
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        return int(user_id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


async def _is_admin_user(db: AsyncSession, user_id: int) -> bool:
    try:
        await require_admin_user(db, user_id)
        return True
    except HTTPException:
        return False


class SupportChatIn(BaseModel):
    message: str = Field(..., min_length=2)
    session_id: Optional[str] = None


class SupportChatOut(BaseModel):
    session_id: str
    response: str
    needs_handoff: bool


class AdminSupportMessageIn(BaseModel):
    message: str = Field(..., min_length=2)
    status: Optional[str] = None


class SupportComplaintIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=3, max_length=160)
    category: str = Field(..., min_length=2, max_length=80)
    message: str = Field(..., min_length=10, max_length=2000)
    errand_type: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=80)


class SupportReviewIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    rating: int = Field(..., ge=1, le=5)
    notes: str = Field(..., min_length=10, max_length=2000)
    city: Optional[str] = Field(default=None, max_length=80)
    errand_type: Optional[str] = Field(default=None, max_length=120)


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


def _rule_based_response(message: str) -> tuple[str, bool]:
    text = message.lower()

    if any(
        keyword in text for keyword in ["agent", "human", "representative", "support"]
    ):
        return (
            "I can connect you with a live agent. Please confirm your best contact email or phone.",
            True,
        )

    faq = {
        "tracking": "You can track your errand from the live tracking link sent when the pilot starts. If you lost it, ask us to resend.",
        "delay": "If your pilot is delayed, we will notify you with updated timing. You can also check live tracking for the latest position.",
        "cancel": "To cancel an errand, open the errand details and choose Cancel. If you need help, reply here.",
        "refund": "Refunds are handled after the errand is reviewed. Please share your errand reference number so we can assist.",
        "login": "If you can't log in, try resetting your password. If that doesn't work, tell us the email you used to sign up.",
        "password": "You can reset your password from the login screen. If the reset email doesn't arrive, check spam or tell us your email.",
        "pilot": "Pilots are assigned by admins before the journey starts. You'll receive updates as the status changes.",
    }

    for key, response in faq.items():
        if key in text:
            return response, False

    return (
        "I can help with tracking, delays, cancellations, refunds, or login issues. Tell me which one you need help with.",
        False,
    )


async def _ai_response(message: str) -> tuple[str, bool]:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_SUPPORT_MODEL", "gpt-4")
    if not (api_key and AsyncOpenAI):
        return _rule_based_response(message)

    client = AsyncOpenAI(api_key=api_key)
    system_prompt = (
        "You are ErrandBridge customer support. Answer briefly, resolve common issues, and ask clarifying questions. "
        "If the user asks for a human agent, acknowledge and set handoff_required = true."
    )
    result = await client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        max_output_tokens=300,
    )

    response_text = result.output_text or "I can help with your request."
    needs_handoff = (
        any(term in message.lower() for term in ["agent", "human", "representative"])
        or False
    )
    return response_text, needs_handoff


@router.post("/chat", response_model=SupportChatOut)
async def chat_with_support(
    payload: SupportChatIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _extract_bearer(authorization)
    user_id = decode_access_token(token) if token else None
    session_id = payload.session_id or str(uuid.uuid4())

    conversation = await db.scalar(
        select(SupportConversation).where(SupportConversation.session_id == session_id)
    )

    if not conversation:
        conversation = SupportConversation(session_id=session_id, user_id=user_id)
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
    elif user_id and not conversation.user_id:
        # If the user starts a session while unauthenticated and later logs in,
        # bind the conversation to their user_id so they can retrieve messages.
        conversation.user_id = int(user_id)
        conversation.updated_at = datetime.now(timezone.utc)
        await db.commit()

    user_msg = SupportMessage(
        conversation_id=conversation.id,
        sender_type="customer",
        message=payload.message,
    )
    db.add(user_msg)
    await db.commit()

    response_text, needs_handoff = await _ai_response(payload.message)

    ai_msg = SupportMessage(
        conversation_id=conversation.id,
        sender_type="ai",
        message=response_text,
    )
    db.add(ai_msg)

    handoff_requested_before = conversation.handoff_requested
    conversation.updated_at = datetime.now(timezone.utc)
    if needs_handoff:
        conversation.handoff_requested = True
        conversation.status = "needs_handoff"
    await db.commit()

    if needs_handoff and not handoff_requested_before:
        support_user = (
            await db.get(User, int(conversation.user_id))
            if conversation.user_id
            else None
        )
        try:
            await notify_admin_support_handoff(
                db,
                conversation=conversation,
                user=support_user,
                initial_message=payload.message,
            )
        except Exception:
            pass

    return SupportChatOut(
        session_id=session_id,
        response=response_text,
        needs_handoff=needs_handoff,
    )


@router.get("/sessions/{session_id}/messages", response_model=dict)
async def list_support_session_messages(
    session_id: str,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List messages for a support chat session.

    This endpoint is used by the in-app assistant ("Toxi") to keep the chat
    conversation in sync (including admin replies after a human handoff).

    Access control:
    - Admins can view any session.
    - Customers can view sessions that belong to their user_id.
    - If a session was created before login (conversation.user_id is null), the
      first authenticated customer to access it will claim/bind it.
    """
    token = _extract_bearer(authorization)
    user_id = _require_user_id_from_token(token)

    conversation = await db.scalar(
        select(SupportConversation).where(SupportConversation.session_id == session_id)
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Support session not found")

    if not await _is_admin_user(db, user_id):
        if conversation.user_id is None:
            conversation.user_id = int(user_id)
            conversation.updated_at = datetime.now(timezone.utc)
            await db.commit()
        elif int(conversation.user_id) != int(user_id):
            raise HTTPException(status_code=403, detail="Not allowed")

    messages = await db.execute(
        select(SupportMessage)
        .where(SupportMessage.conversation_id == conversation.id)
        .order_by(SupportMessage.created_at.asc())
    )

    return {
        "messages": [
            {
                "id": msg.id,
                "sender_type": msg.sender_type,
                "message": msg.message,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages.scalars().all()
        ]
    }


@router.get("/conversations", response_model=dict)
async def list_support_conversations(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    await require_admin_user(db, user_id)

    conversations = await db.execute(
        select(SupportConversation).order_by(desc(SupportConversation.updated_at))
    )

    return {
        "conversations": [
            {
                "id": convo.id,
                "session_id": convo.session_id,
                "user_id": convo.user_id,
                "status": convo.status,
                "handoff_requested": convo.handoff_requested,
                "created_at": (
                    convo.created_at.isoformat() if convo.created_at else None
                ),
                "updated_at": (
                    convo.updated_at.isoformat() if convo.updated_at else None
                ),
            }
            for convo in conversations.scalars().all()
        ]
    }


@router.get("/conversations/alerts", response_model=dict)
async def list_support_handoff_alerts(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Return a lightweight support-handoff alert payload for admin polling."""

    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    await require_admin_user(db, user_id)

    conversations = await db.execute(
        select(SupportConversation)
        .where(SupportConversation.handoff_requested.is_(True))
        .order_by(desc(SupportConversation.updated_at), desc(SupportConversation.id))
        .limit(50)
    )

    rows = conversations.scalars().all()
    return {
        "conversations": [
            {
                "id": convo.id,
                "session_id": convo.session_id,
                "status": convo.status,
                "handoff_requested": bool(convo.handoff_requested),
                "updated_at": (
                    convo.updated_at.isoformat() if convo.updated_at else None
                ),
            }
            for convo in rows
        ]
    }


@router.get("/conversations/{conversation_id}/messages", response_model=dict)
async def list_support_messages(
    conversation_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    await require_admin_user(db, user_id)

    messages = await db.execute(
        select(SupportMessage)
        .where(SupportMessage.conversation_id == conversation_id)
        .order_by(SupportMessage.created_at.asc())
    )

    return {
        "messages": [
            {
                "id": msg.id,
                "sender_type": msg.sender_type,
                "message": msg.message,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages.scalars().all()
        ]
    }


@router.post("/conversations/{conversation_id}/admin-message", response_model=dict)
async def add_support_message(
    conversation_id: int,
    payload: AdminSupportMessageIn,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    await require_admin_user(db, user_id)

    conversation = await db.get(SupportConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    admin_msg = SupportMessage(
        conversation_id=conversation.id,
        sender_type="admin",
        message=payload.message,
    )
    db.add(admin_msg)

    if payload.status:
        conversation.status = payload.status.strip().lower()
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"success": True}


@router.post("/complaints", response_model=dict)
async def submit_support_complaint(payload: SupportComplaintIn):
    subject = f"Compliance complaint: {payload.category.strip()}"
    body = (
        "A new support complaint was submitted from the landing page.\n\n"
        f"Name: {payload.name.strip()}\n"
        f"Email: {payload.email.strip().lower()}\n"
        f"Category: {payload.category.strip()}\n"
        f"Errand type: {(payload.errand_type or 'N/A').strip()}\n"
        f"City: {(payload.city or 'N/A').strip()}\n\n"
        "Complaint details:\n"
        f"{payload.message.strip()}\n"
    )
    result = send_email(
        to_email="complaint@errandbridge.com",
        subject=subject,
        body_text=body,
    )
    return {
        "ok": result.delivered,
        "provider": result.provider,
        "detail": result.detail,
    }


@router.post("/reviews", response_model=dict)
async def submit_support_review(payload: SupportReviewIn):
    inbox = (os.getenv("REVIEW_INBOX") or "review@errandbridge.com").strip()
    subject = f"New client review ({payload.rating}★)"
    body = (
        "A new landing page review was submitted.\n\n"
        f"Name: {payload.name.strip()}\n"
        f"Rating: {payload.rating} stars\n"
        f"Errand type: {(payload.errand_type or 'N/A').strip()}\n"
        f"City: {(payload.city or 'N/A').strip()}\n\n"
        "Review notes:\n"
        f"{payload.notes.strip()}\n"
    )
    result = send_email(to_email=inbox, subject=subject, body_text=body)
    return {
        "ok": result.delivered,
        "provider": result.provider,
        "detail": result.detail,
    }
