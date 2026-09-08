import uuid
from sqlalchemy import Column, Uuid, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    conversation_id = Column(Uuid, ForeignKey("support_conversations.id"), nullable=False, index=True
    )
    sender_type = Column(String, nullable=False)  # customer | ai | admin
    message = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
