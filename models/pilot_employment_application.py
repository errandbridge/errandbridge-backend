import uuid
from sqlalchemy import Column, Uuid, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from database import Base


class PilotEmploymentApplication(Base):
    __tablename__ = "pilot_employment_applications"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, nullable=False, index=True)
    phone = Column(String, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    experience = Column(Text, nullable=True)
    availability = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="submitted")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
