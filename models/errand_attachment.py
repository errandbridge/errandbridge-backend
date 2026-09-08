import uuid
from sqlalchemy import Column, Uuid, Integer, String, DateTime
from sqlalchemy.sql import func
from database import Base


class ErrandAttachment(Base):
    __tablename__ = "errand_attachments"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    errand_id = Column(Integer, nullable=False, index=True)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False, unique=True)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False, default=0)
    label = Column(String, nullable=True)
    review_status = Column(String, nullable=False, default="pending")
    review_note = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
