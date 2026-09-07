from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from twilio.rest import Client  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Client = None


@dataclass(frozen=True)
class VoiceConfig:
    account_sid: str
    auth_token: str
    from_number: str
    voice_number: str


@dataclass(frozen=True)
class VoiceCallResult:
    ok: bool
    detail: str | None = None
    call_sid: str | None = None


def _voice_enabled() -> bool:
    return bool(
        (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
        and (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
        and (
            (os.getenv("TWILIO_VOICE_NUMBER") or "").strip()
            or (os.getenv("TWILIO_FROM_NUMBER") or "").strip()
        )
    )


def _voice_config() -> VoiceConfig | None:
    if not _voice_enabled():
        return None
    return VoiceConfig(
        account_sid=(os.getenv("TWILIO_ACCOUNT_SID") or "").strip(),
        auth_token=(os.getenv("TWILIO_AUTH_TOKEN") or "").strip(),
        from_number=(os.getenv("TWILIO_FROM_NUMBER") or "").strip(),
        voice_number=(
            os.getenv("TWILIO_VOICE_NUMBER") or os.getenv("TWILIO_FROM_NUMBER") or ""
        ).strip(),
    )


def create_call(
    *, to_number: str, twiml_url: str, status_callback: str | None = None
) -> VoiceCallResult:
    config = _voice_config()
    if config is None:
        return VoiceCallResult(ok=False, detail="missing_config")
    if Client is None:
        return VoiceCallResult(ok=False, detail="missing_dependency")

    try:
        client = Client(config.account_sid, config.auth_token)
        call = client.calls.create(
            to=to_number,
            from_=config.voice_number or config.from_number,
            url=twiml_url,
            status_callback=status_callback,
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        return VoiceCallResult(ok=True, call_sid=call.sid)
    except Exception as exc:
        return VoiceCallResult(ok=False, detail=f"twilio_call_failed: {exc}")


def request_transcription(
    *, recording_sid: str, callback_url: str | None = None
) -> VoiceCallResult:
    config = _voice_config()
    if config is None:
        return VoiceCallResult(ok=False, detail="missing_config")
    if Client is None:
        return VoiceCallResult(ok=False, detail="missing_dependency")

    try:
        client = Client(config.account_sid, config.auth_token)
        transcription = client.recordings(recording_sid).transcriptions.create(
            transcription_callback=callback_url
        )
        return VoiceCallResult(ok=True, call_sid=getattr(transcription, "sid", None))
    except Exception as exc:
        return VoiceCallResult(ok=False, detail=f"twilio_transcribe_failed: {exc}")
