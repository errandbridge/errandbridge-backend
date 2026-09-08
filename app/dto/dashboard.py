"""Consolidated Customer, Pilot, and Admin Dashboard DTO Trees.

Provides rich, composable, strongly-typed domain representations designed to
eliminate high-latency frontend waterfalls on initial dashboard render.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.dto.common import (
    CamelModel,
    FlexibleId,
    ErrandStatus,
    PilotAvailabilityStatus,
    UserRole,
)


class CustomerDashboardStats(CamelModel):
    """High-level summary metrics for a customer account."""
    total_errands: int = Field(default=0, description="Lifetime errands created by customer")
    active_errands: int = Field(default=0, description="Currently active errands in progress")
    completed_errands: int = Field(default=0, description="Successfully finished deliveries")
    draft_errands: int = Field(default=0, description="Unsubmitted or pending checkout errands")


class CustomerActiveErrandItem(CamelModel):
    """Active errand summary with live status and tracking flags."""
    id: FlexibleId = Field(..., description="Errand identifier")
    reference_number: Optional[str] = Field(default=None, description="Human reference number")
    title: Optional[str] = Field(default=None, description="Errand task title")
    status: str = Field(..., description="Current errand status")
    pilot_name: Optional[str] = Field(default=None, description="Assigned pilot display name")
    pickup_location: Optional[str] = Field(default=None, description="Pickup address")
    dropoff_location: Optional[str] = Field(default=None, description="Dropoff address")
    tracking_allowed: bool = Field(default=False, description="Whether tracking window is currently active")
    tracking_active: bool = Field(default=False, description="Whether pilot is actively broadcasting coordinates")
    created_at: Optional[datetime] = Field(default=None, description="Creation timestamp")


class CustomerRecentErrandItem(CamelModel):
    """Past errand record displayed in customer activity feed."""
    id: FlexibleId = Field(..., description="Errand identifier")
    reference_number: Optional[str] = Field(default=None, description="Human reference number")
    title: Optional[str] = Field(default=None, description="Errand task title")
    status: str = Field(..., description="Terminal errand status")
    completed_at: Optional[datetime] = Field(default=None, description="Completion timestamp")
    created_at: Optional[datetime] = Field(default=None, description="Creation timestamp")
    amount_ngn: Optional[float] = Field(default=None, description="Final errand total in NGN")


class CustomerSpendingSummary(CamelModel):
    """Customer billing and subscription overview."""
    currency: str = Field(default="NGN", description="Currency code")
    total_spent_minor: int = Field(default=0, description="Total expenditure in minor units")
    active_subscription_tier: Optional[str] = Field(default=None, description="Current active subscription tier")
    active_subscription_status: Optional[str] = Field(default=None, description="Status of client subscription")


class CustomerRecommendedAction(CamelModel):
    """Contextual action card or banner for customer dashboard."""
    action_type: str = Field(..., description="Type of action: COMPLETE_PROFILE, VERIFY_ID, TRACK_ERRAND, etc.")
    title: str = Field(..., description="Action card headline")
    description: str = Field(..., description="Explanation of recommended action")
    deep_link: str = Field(..., description="Target navigation route or action trigger")


class CustomerDashboardResponse(CamelModel):
    """Unified initial payload for Customer dashboard render."""
    stats: CustomerDashboardStats = Field(..., description="Summary counters")
    active_errands: list[CustomerActiveErrandItem] = Field(default_factory=list, description="Live errands")
    recent_errands: list[CustomerRecentErrandItem] = Field(default_factory=list, description="Historical errands")
    spending: CustomerSpendingSummary = Field(..., description="Financial snapshot")
    actions: list[CustomerRecommendedAction] = Field(default_factory=list, description="Recommended actions")


class PilotDashboardStats(CamelModel):
    """Performance metrics for pilot home screen."""
    completed_jobs_count: int = Field(default=0, description="Total deliveries finished by pilot")
    active_jobs_count: int = Field(default=0, description="Deliveries currently in progress")
    total_jobs_count: int = Field(default=0, description="Total lifetime accepted errands")
    customer_rating: Optional[float] = Field(default=None, description="Pilot star rating out of 5")
    acceptance_rate: Optional[float] = Field(default=None, description="Percentage of dispatched jobs accepted")


class PilotEarningsSummary(CamelModel):
    """Machine-readable earnings summary across time windows."""
    currency: str = Field(default="NGN", description="Currency code")
    today_minor: int = Field(default=0, description="Earnings today in kobo/cents")
    week_minor: int = Field(default=0, description="Earnings this week in kobo/cents")
    total_minor: int = Field(default=0, description="Lifetime earnings in kobo/cents")


class PilotAvailabilitySummary(CamelModel):
    """Pilot availability and dispatch readiness status."""
    status: str = Field(default="offline", description="Online/offline/busy state")
    dispatch_status: str = Field(default="enabled", description="Administrative dispatch approval state")
    is_eligible_for_dispatch: bool = Field(default=True, description="True if verified and available for jobs")


class PilotAlertItem(CamelModel):
    """Operational alert or announcement for pilot."""
    severity: str = Field(default="info", description="Alert level: info, warning, error")
    message: str = Field(..., description="Alert text")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Alert creation timestamp")


class PilotDashboardResponse(CamelModel):
    """Unified initial payload for Pilot portal render."""
    stats: PilotDashboardStats = Field(..., description="Pilot metrics")
    active_delivery: Optional[CustomerActiveErrandItem] = Field(default=None, description="Current active run")
    available_jobs_count: int = Field(default=0, description="Count of open jobs within radius")
    earnings: PilotEarningsSummary = Field(..., description="Earnings summary")
    availability: PilotAvailabilitySummary = Field(..., description="Availability flags")
    alerts: list[PilotAlertItem] = Field(default_factory=list, description="System notices")


class UnifiedDashboardResponse(CamelModel):
    """Root response for GET /dashboard, switching by user role."""
    account_type: str = Field(..., description="User account type (client, pilot, admin)")
    customer: Optional[CustomerDashboardResponse] = Field(default=None, description="Populated if client")
    pilot: Optional[PilotDashboardResponse] = Field(default=None, description="Populated if pilot")
