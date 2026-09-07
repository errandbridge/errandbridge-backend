"""Pilot Location model for GPS tracking"""

from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, Index, String
from sqlalchemy.sql import func
from database import Base


class PilotLocation(Base):
    __tablename__ = "pilot_locations"

    id = Column(Integer, primary_key=True, index=True)
    errand_id = Column(
        Integer,
        ForeignKey("errands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pilot_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    latitude = Column(Float, nullable=False)  # Decimal precision handled by DB
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)  # GPS accuracy in meters
    speed = Column(Float, nullable=True)  # Speed in m/s
    heading = Column(Float, nullable=True)  # Direction in degrees (0-360)
    altitude = Column(Float, nullable=True)  # Altitude in meters
    source = Column(
        String, nullable=False, server_default="mobile_app"
    )  # mobile_app | fob
    recorded_at = Column(
        DateTime(timezone=True), nullable=True
    )  # device-recorded event time
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Indexes for fast queries
    __table_args__ = (
        Index("idx_pilot_locations_errand_created", "errand_id", "created_at"),
        Index("idx_pilot_locations_pilot_created", "pilot_id", "created_at"),
    )
