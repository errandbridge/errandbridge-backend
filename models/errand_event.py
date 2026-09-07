from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class ErrandEvent(Base):
    __tablename__ = "errand_events"
    id = Column(Integer, primary_key=True, index=True)
    errand_id = Column(Integer, ForeignKey("errands.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_id = Column(Integer, nullable=True)
