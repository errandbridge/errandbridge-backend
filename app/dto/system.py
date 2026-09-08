"""System and Health Domain Data Transfer Objects (DTOs)."""

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Service liveness probe payload."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(default="ok", description="Liveness status flag")
    app: str = Field(default="ErrandBridge", description="Application name")
    timestamp: Optional[str] = Field(default=None, description="Server time")


class ReadinessResponse(BaseModel):
    """Service readiness probe payload."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(default="ready", description="Readiness status flag")


class DbHealthResponse(BaseModel):
    """Database connectivity health check."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(default="ok", description="Status outcome")
    database: str = Field(default="connected", description="Database connection state")


class AnomalyAlertItem(BaseModel):
    """Automated fraud or delivery anomaly detection alert."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: Optional[str] = Field(default=None, description="Alert ID")
    alert_type: Optional[str] = Field(default=None, description="Anomaly categorization")
    severity: Optional[str] = Field(default="warning", description="Severity level (info, warning, critical)")
    message: str = Field(..., description="Descriptive explanation")
    created_at: Optional[str] = Field(default=None, description="Detection timestamp")


class AnalyticsVisitResponse(BaseModel):
    """Analytics tracking confirmation response."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ok: bool = Field(default=True, description="Tracking event acknowledgement")
