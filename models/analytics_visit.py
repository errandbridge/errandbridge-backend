import uuid
from sqlalchemy import Column, Uuid, DateTime, Integer, String
from sqlalchemy.sql import func
from database import Base


class AnalyticsVisit(Base):
    __tablename__ = "analytics_visits"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    page = Column(String, nullable=True)
    source = Column(String, nullable=True)
    country = Column(String, nullable=True)
    region = Column(String, nullable=True)
    city = Column(String, nullable=True)
    ip_hash = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
