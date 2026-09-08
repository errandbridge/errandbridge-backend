import uuid
from sqlalchemy import Column, Uuid, Integer, DateTime, ForeignKey, Text
from sqlalchemy.sql import func

from database import Base


class ErrandMessage(Base):
    __tablename__ = "errand_messages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    errand_id = Column(Uuid, ForeignKey("errands.id"), nullable=False, index=True)
    sender_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    message = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
