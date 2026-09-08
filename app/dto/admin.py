"""Admin Domain Data Transfer Objects (DTOs)."""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.dto.common import FlexibleId


class AdminMetricsOverviewResponse(BaseModel):
    """System-wide operational metrics and analytics summary."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    total_users: int = Field(default=0, description="Total registered users")
    verified_users: int = Field(default=0, description="Verified email accounts")
    pending_issues: int = Field(default=0, description="Unresolved errand issues")
    total_errands: int = Field(default=0, description="Total platform errands")
    visits_total: int = Field(default=0, description="Cumulative site visits")
    visits_last_24h: int = Field(default=0, description="Site visits in past 24 hours")
    visits_by_country: list[dict[str, Any]] = Field(default_factory=list, description="Traffic by country")
    visits_by_region: list[dict[str, Any]] = Field(default_factory=list, description="Traffic by region")
    visits_by_city: list[dict[str, Any]] = Field(default_factory=list, description="Traffic by city")
    visits_by_location: list[dict[str, Any]] = Field(default_factory=list, description="Traffic by combined location")
    visits_last_24h_by_location: list[dict[str, Any]] = Field(default_factory=list, description="Recent 24h location traffic")
    visits_recent_24h: list[dict[str, Any]] = Field(default_factory=list, description="Hourly traffic over last 24h")
    visits_by_source: list[dict[str, Any]] = Field(default_factory=list, description="Traffic breakdown by acquisition source")
    errand_funnel: dict[str, int] = Field(default_factory=dict, description="Errand lifecycle count distribution")
    last_updated: Optional[str] = Field(default=None, description="ISO timestamp of metrics compilation")


class AdminPilotDocumentItem(BaseModel):
    """Pilot credential document for administrative compliance review."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Document ID")
    pilot_id: FlexibleId = Field(..., description="Pilot user ID")
    pilot_name: Optional[str] = Field(default=None, description="Pilot full name")
    pilot_email: Optional[str] = Field(default=None, description="Pilot email")
    document_type: Optional[str] = Field(default=None, description="Document category")
    original_filename: str = Field(..., description="Uploaded file name")
    content_type: Optional[str] = Field(default=None, description="MIME type")
    size_bytes: int = Field(..., description="File size in bytes")
    status: str = Field(..., description="Review status (pending, approved, rejected)")
    review_note: Optional[str] = Field(default=None, description="Administrator review notes")
    created_at: Optional[str] = Field(default=None, description="Upload timestamp")


class AdminPilotEmploymentApplicationItem(BaseModel):
    """Pilot job application submission."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Application record ID")
    first_name: Optional[str] = Field(default=None, description="Applicant first name")
    last_name: Optional[str] = Field(default=None, description="Applicant last name")
    email: Optional[str] = Field(default=None, description="Applicant email address")
    phone: Optional[str] = Field(default=None, description="Contact telephone number")
    city: Optional[str] = Field(default=None, description="City of operation")
    status: str = Field(default="pending", description="Application status")
    created_at: Optional[str] = Field(default=None, description="Date submitted")
    attachments: list[dict[str, Any]] = Field(default_factory=list, description="Supporting resume/license documents")


class AdminVoiceCallItem(BaseModel):
    """Masked voice call session between customer and pilot."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Call session ID")
    errand_id: Optional[FlexibleId] = Field(default=None, description="Related errand ID")
    caller_role: Optional[str] = Field(default=None, description="Initiating party role")
    status: str = Field(..., description="Call session status (e.g. completed, in_progress)")
    duration_seconds: Optional[int] = Field(default=None, description="Call length in seconds")
    started_at: Optional[str] = Field(default=None, description="Start timestamp")
    ended_at: Optional[str] = Field(default=None, description="End timestamp")


class AdminVoiceCallEventItem(BaseModel):
    """Telephony webhook event log."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Event ID")
    session_id: FlexibleId = Field(..., description="Parent call session ID")
    event_type: str = Field(..., description="Twilio webhook event type")
    created_at: Optional[str] = Field(default=None, description="Timestamp logged")
    payload: Optional[dict[str, Any]] = Field(default=None, description="Event metadata payload")


class AdminCustomerListItem(BaseModel):
    """Customer record summary for admin customer index."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="User identifier")
    email: str = Field(..., description="Customer email address")
    first_name: Optional[str] = Field(default=None, description="First name")
    last_name: Optional[str] = Field(default=None, description="Last name")
    phone: Optional[str] = Field(default=None, description="Phone number")
    is_email_verified: bool = Field(default=False, description="Email verification state")
    errands_count: int = Field(default=0, description="Total errands created")
    created_at: Optional[str] = Field(default=None, description="Registration timestamp")


class AdminCustomerStatsResponse(BaseModel):
    """Customer demographic and verification metrics."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    total_customers: int = Field(default=0, description="Total customer accounts")
    verified_customers: int = Field(default=0, description="Email and ID verified customers")
    unverified_customers: int = Field(default=0, description="Accounts pending verification")
    countries_represented: int = Field(default=0, description="Distinct customer geographic countries")


class AdminDeleteErrandResponse(BaseModel):
    """Errand deletion acknowledgement."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    deleted: bool = Field(default=True, description="Deletion status")
    id: FlexibleId = Field(..., description="Deleted errand ID")


class AdminErrandStatusUpdateResponse(BaseModel):
    """Errand status update confirmation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Errand ID")
    reference_number: Optional[str] = Field(default=None, alias="referenceNumber", description="Errand reference code")
    status: str = Field(..., description="Updated errand status")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt", description="Update timestamp")


class AdminAssignPilotResponse(BaseModel):
    """Pilot dispatch assignment confirmation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Errand ID")
    reference_number: Optional[str] = Field(default=None, alias="referenceNumber", description="Errand reference code")
    status: str = Field(..., description="Errand status (assigned)")
    pilot_id: Optional[FlexibleId] = Field(default=None, alias="pilotId", description="Assigned pilot user ID")
    assigned_to: Optional[FlexibleId] = Field(default=None, alias="assignedTo", description="Legacy assigned runner ID")
    assigned_at: Optional[str] = Field(default=None, alias="assignedAt", description="Assignment timestamp")


class AdminPilotDispatchStatusResponse(BaseModel):
    """Pilot dispatch enablement modification response."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ok: bool = Field(default=True, description="Operation status")
    pilot_id: FlexibleId = Field(..., description="Pilot ID")
    first_name: Optional[str] = Field(default=None, description="First name")
    last_name: Optional[str] = Field(default=None, description="Last name")
    email: Optional[str] = Field(default=None, description="Email address")


class AdminPilotDocumentReviewResponse(BaseModel):
    """Document approval or rejection outcome."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    success: bool = Field(default=True, description="Review outcome")
    status: str = Field(..., description="New document status (approved, rejected)")


class AdminReviewAttachmentResponse(BaseModel):
    """Attachment verification confirmation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ok: bool = Field(default=True, description="Review success")
    attachment_id: FlexibleId = Field(..., description="Reviewed attachment ID")
    status: str = Field(..., description="Verification state")


class AdminCustomersByCountryResponse(BaseModel):
    """Geographic customer index."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    country: str = Field(..., description="ISO country code")
    total_in_country: int = Field(..., description="Customer count")
    customers: list[dict[str, Any]] = Field(default_factory=list, description="Customer list")


class AdminUnverifiedCustomersResponse(BaseModel):
    """Pending unverified accounts container."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    unverified_count: int = Field(..., description="Total unverified count")
    customers: list[dict[str, Any]] = Field(default_factory=list, description="Unverified customer entries")


class AdminPurgeUnverifiedCustomersResponse(BaseModel):
    """Bulk unverified customer deletion report."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    deleted_count: int = Field(..., description="Number of accounts deleted")
    deleted_emails: list[str] = Field(default_factory=list, description="Deleted user emails")
