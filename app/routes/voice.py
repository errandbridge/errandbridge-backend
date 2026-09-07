from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import decode_access_token
from database import get_db
from models import Errand, User, VoiceCallSession, VoiceCallEvent
from models.voice_call_event import build_event_hash
from app.services.twilio_voice import create_call, request_transcription
from app.services.voice_worm import store_worm_json, store_worm_bytes
import httpx

router = APIRouter(prefix="/voice", tags=["voice"])


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _mask_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "****"
    return f"***{digits[-4:]}"


def _public_base(request: Request) -> str:
    base = (os.getenv("PUBLIC_API_URL") or "").strip().rstrip("/")
    if base:
        return base
    return str(request.base_url).rstrip("/")


async def _log_event(
    db: AsyncSession,
    session: VoiceCallSession,
    event_type: str,
    payload: dict,
) -> VoiceCallEvent:
    result = await db.execute(
        select(VoiceCallEvent)
        .where(VoiceCallEvent.session_id == session.id)
        .order_by(VoiceCallEvent.id.desc())
    )
    last = result.scalars().first()
    previous_hash = last.entry_hash if last else None
    entry_hash = build_event_hash(event_type, payload, previous_hash)
    event = VoiceCallEvent(
        session_id=session.id,
        event_type=event_type,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        previous_hash=previous_hash,
        entry_hash=entry_hash,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.post("/call/start")
async def start_masked_call(
    request: Request,
    errand_id: int,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _extract_bearer(authorization)
    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    errand = await db.scalar(select(Errand).where(Errand.id == errand_id))
    if not errand:
        raise HTTPException(status_code=404, detail="Errand not found")

    pilot = None
    if errand.pilot_id:
        pilot = await db.get(User, errand.pilot_id)
    customer = await db.get(User, errand.user_id)
    if not pilot or not customer:
        raise HTTPException(status_code=400, detail="Pilot or customer not assigned")

    if int(user_id) not in {int(pilot.id), int(customer.id)}:
        raise HTTPException(status_code=403, detail="Not authorized to start this call")

    if not pilot.phone or not customer.phone:
        raise HTTPException(status_code=400, detail="Pilot or customer phone missing")

    conference = f"errand-{errand.id}-{secrets.token_hex(4)}"
    session = VoiceCallSession(
        errand_id=errand.id,
        initiator_user_id=user_id,
        pilot_user_id=pilot.id,
        customer_user_id=customer.id,
        status="created",
        conference_name=conference,
        pilot_phone_mask=_mask_phone(pilot.phone),
        customer_phone_mask=_mask_phone(customer.phone),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    base = _public_base(request)
    twiml_url = f"{base}/voice/twiml/{session.id}"
    status_callback = f"{base}/voice/status/{session.id}"

    pilot_call = create_call(
        to_number=pilot.phone,
        twiml_url=twiml_url + "?role=pilot",
        status_callback=status_callback,
    )
    customer_call = create_call(
        to_number=customer.phone,
        twiml_url=twiml_url + "?role=customer",
        status_callback=status_callback,
    )

    if not pilot_call.ok or not customer_call.ok:
        session.status = "failed"
        await db.commit()
        await _log_event(
            db,
            session,
            "call_failed",
            {
                "pilot_ok": pilot_call.ok,
                "customer_ok": customer_call.ok,
                "pilot_detail": pilot_call.detail,
                "customer_detail": customer_call.detail,
            },
        )
        raise HTTPException(status_code=500, detail="Unable to start masked call")

    session.status = "dialing"
    await db.commit()
    await _log_event(
        db,
        session,
        "call_started",
        {
            "pilot_call_sid": pilot_call.call_sid,
            "customer_call_sid": customer_call.call_sid,
            "initiator_user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {
        "session_id": session.id,
        "status": session.status,
        "pilot_call_sid": pilot_call.call_sid,
        "customer_call_sid": customer_call.call_sid,
        "pilot_mask": session.pilot_phone_mask,
        "customer_mask": session.customer_phone_mask,
    }


@router.post("/status/{session_id}")
async def twilio_status_callback(
    session_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    call_status = form.get("CallStatus")
    call_sid = form.get("CallSid")
    session = await db.get(VoiceCallSession, session_id)
    if not session:
        return {"ok": True}

    await _log_event(
        db,
        session,
        "call_status",
        {
            "call_status": call_status,
            "call_sid": call_sid,
        },
    )
    return {"ok": True}


@router.post("/recording/{session_id}")
async def twilio_recording_callback(
    session_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    recording_sid = form.get("RecordingSid")
    recording_url = form.get("RecordingUrl")
    session = await db.get(VoiceCallSession, session_id)
    if not session:
        return {"ok": True}

    callback_url = (
        f"{_public_base(request)}/voice/transcription/{session_id}"
        if recording_sid
        else None
    )
    transcription_result = None
    if recording_sid:
        transcription_result = request_transcription(
            recording_sid=recording_sid, callback_url=callback_url
        )

    worm_key = None
    worm_media_key = None
    if recording_sid or recording_url:
        worm_key = store_worm_json(
            key_suffix=f"recordings/session-{session_id}.json",
            payload={
                "recording_sid": recording_sid,
                "recording_url": recording_url,
                "transcription_requested": bool(
                    transcription_result and transcription_result.ok
                ),
                "transcription_detail": (
                    transcription_result.detail if transcription_result else None
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        if recording_url:
            try:
                recording_response = httpx.get(f"{recording_url}.mp3", timeout=15.0)
                if recording_response.status_code == 200:
                    worm_media_key = store_worm_bytes(
                        key_suffix=f"recordings/session-{session_id}.mp3",
                        content=recording_response.content,
                        content_type="audio/mpeg",
                    )
            except Exception:
                worm_media_key = None

    await _log_event(
        db,
        session,
        "recording_ready",
        {
            "recording_sid": recording_sid,
            "recording_url": recording_url,
            "transcription_requested": bool(
                transcription_result and transcription_result.ok
            ),
            "transcription_detail": (
                transcription_result.detail if transcription_result else None
            ),
            "worm_key": worm_key,
            "worm_media_key": worm_media_key,
        },
    )

    return {"ok": True}


@router.post("/transcription/{session_id}")
async def twilio_transcription_callback(
    session_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    transcription_sid = form.get("TranscriptionSid")
    transcription_text = form.get("TranscriptionText")
    transcription_status = form.get("TranscriptionStatus")
    session = await db.get(VoiceCallSession, session_id)
    if not session:
        return {"ok": True}

    worm_key = None
    if transcription_sid or transcription_text:
        worm_key = store_worm_json(
            key_suffix=f"transcripts/session-{session_id}.json",
            payload={
                "transcription_sid": transcription_sid,
                "transcription_status": transcription_status,
                "transcription_text": transcription_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    await _log_event(
        db,
        session,
        "transcription_ready",
        {
            "transcription_sid": transcription_sid,
            "transcription_status": transcription_status,
            "transcription_text": transcription_text,
            "worm_key": worm_key,
        },
    )

    return {"ok": True}


@router.get("/twiml/{session_id}")
async def twiml_for_conference(
    session_id: int,
    request: Request,
    role: str = "participant",
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(VoiceCallSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    recording_callback = f"{_public_base(request)}/voice/recording/{session_id}"

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say>Connecting {role}.</Say>"
        "<Dial>"
        f'<Conference record="record-from-start" recordingStatusCallback="{recording_callback}">{session.conference_name}</Conference>'
        "</Dial>"
        "</Response>"
    )
    return PlainTextResponse(content=twiml, media_type="text/xml")
