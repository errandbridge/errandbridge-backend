import uuid
from sqlalchemy import Column, Uuid, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class PilotEmploymentAttachment(Base):
    __tablename__ = "pilot_employment_attachments"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    application_id = Column(Uuid, ForeignKey("pilot_employment_applications.id"),
        nullable=False,
        index=True,
    )
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False, unique=True)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False, default=0)
    label = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
