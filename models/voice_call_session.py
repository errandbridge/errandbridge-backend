from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func
from database import Base


class VoiceCallSession(Base):
    __tablename__ = "voice_call_sessions"

    id = Column(Integer, primary_key=True, index=True)
    errand_id = Column(Integer, nullable=False, index=True)
    initiator_user_id = Column(Integer, nullable=False)
    pilot_user_id = Column(Integer, nullable=True)
    customer_user_id = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="created")
    conference_name = Column(String, nullable=False, unique=True, index=True)
    pilot_phone_mask = Column(String, nullable=True)
    customer_phone_mask = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
