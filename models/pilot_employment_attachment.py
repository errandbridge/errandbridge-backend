from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class PilotEmploymentAttachment(Base):
    __tablename__ = "pilot_employment_attachments"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("pilot_employment_applications.id"), nullable=False, index=True)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False, unique=True)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False, default=0)
    label = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
