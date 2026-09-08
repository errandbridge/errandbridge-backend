"""Tracking and Live Location Domain Data Transfer Objects (DTOs)."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.dto.common import FlexibleId


class TrackingStatusResponse(BaseModel):
    """Status of live tracking authorization and time windows for an errand."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    errand_id: FlexibleId = Field(..., description="Errand identifier")
    status: str = Field(..., description="Current errand status")
    tracking_allowed: bool = Field(..., description="True if customer is authorized to view live tracking")
    tracking_active: bool = Field(..., description="True if pilot is actively broadcasting coordinates")
    within_time_window: bool = Field(..., description="True if current time is within scheduled window")
    started_at: Optional[str] = Field(default=None, description="Delivery start ISO timestamp")
    window_start: Optional[str] = Field(default=None, description="Scheduled start time window")
    window_end: Optional[str] = Field(default=None, description="Scheduled end time window")
    reason: Optional[str] = Field(default=None, description="Explanation when tracking is unavailable")
