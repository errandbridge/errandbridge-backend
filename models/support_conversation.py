import uuid
from sqlalchemy import Column, Uuid, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from database import Base


class SupportConversation(Base):
    __tablename__ = "support_conversations"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    session_id = Column(String, nullable=False, index=True)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, index=True)
    status = Column(String, nullable=False, default="open")
    handoff_requested = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
