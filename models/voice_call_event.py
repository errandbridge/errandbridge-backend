import hashlib
import json
from sqlalchemy import Column, DateTime, Integer, String, ForeignKey, Text
from sqlalchemy.sql import func
from database import Base


class VoiceCallEvent(Base):
    __tablename__ = "voice_call_events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("voice_call_sessions.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    previous_hash = Column(String, nullable=True)
    entry_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


def build_event_hash(event_type: str, payload: dict, previous_hash: str | None) -> str:
    raw = json.dumps(
        {
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash or "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
