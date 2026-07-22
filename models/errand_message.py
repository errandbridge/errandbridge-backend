from sqlalchemy import Column, Integer, DateTime, ForeignKey, Text
from sqlalchemy.sql import func

from database import Base


class ErrandMessage(Base):
    __tablename__ = "errand_messages"

    id = Column(Integer, primary_key=True, index=True)
    errand_id = Column(Integer, ForeignKey("errands.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
