from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy.sql import func

from database import Base


class PilotDispatchPolicy(Base):
    __tablename__ = "pilot_dispatch_policies"

    id = Column(Integer, primary_key=True, index=True)
    show_all_jobs_to_pilots = Column(Boolean, nullable=False, default=False)
    open_pool_radius_miles = Column(Integer, nullable=False, default=5)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by_user_id = Column(Integer, nullable=True)
