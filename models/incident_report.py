from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class IncidentReport(Base):
    __tablename__ = "incident_reports"

    id = Column(Integer, primary_key=True, index=True)
    errand_id = Column(Integer, ForeignKey("errands.id"), nullable=False, index=True)
    pilot_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    incident_type = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, nullable=False, default="open")
    detected_by = Column(String, nullable=False, default="pilot")  # pilot | ai | admin
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
