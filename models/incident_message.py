import uuid
from sqlalchemy import Column, Uuid, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class IncidentMessage(Base):
    __tablename__ = "incident_messages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    incident_id = Column(Uuid, ForeignKey("incident_reports.id"), nullable=False, index=True
    )
    sender_type = Column(String, nullable=False)  # pilot | ai | admin
    message = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
