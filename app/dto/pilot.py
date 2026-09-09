"""Pilot and Delivery Domain Data Transfer Objects (DTOs).

Covers pilot job marketplace, assigned errand management, delivery lifecycle,
availability, tracking control, and pilot metrics.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.dto.common import (
    CamelModel,
    FlexibleId,
    ErrandStatus,
    PilotAvailabilityStatus,
)


class AvailableJobItem(BaseModel):
    """Summary of an available job listed on the pilot job board."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Errand identifier")
    reference_number: str = Field(..., description="Human-readable reference number")
    title: str = Field(..., description="Errand task title")
    description: Optional[str] = Field(default=None, description="Errand description")
    status: str = Field(..., description="Current errand status")
    pilot_id: Optional[FlexibleId] = Field(default=None, description="Assigned pilot identifier")
    pilotId: Optional[FlexibleId] = Field(default=None, description="CamelCase alias for pilot ID")
    pickup_location: Optional[str] = Field(default=None, description="Pickup address or place")
    dropoff_location: Optional[str] = Field(default=None, description="Dropoff address or place")
    sensitivity: Optional[str] = Field(default=None, description="Handling sensitivity level")
    created_at: Optional[str] = Field(default=None, description="ISO creation timestamp")
    note: Optional[str] = Field(default=None, description="Customer notes")
    customer_name: str = Field(default="Customer", description="Customer display name")
    amount: float = Field(default=0.0, description="Errand compensation or cost")
    payment_amount_ngn_major: Optional[float] = Field(default=None, description="NGN major amount")
    paymentAmountNgnMajor: Optional[float] = Field(default=None, description="CamelCase alias for NGN amount")
    distance_km: Optional[float] = Field(default=None, description="Estimated route distance in km")
    matches_dispatch_policy: bool = Field(default=True, description="Whether job satisfies pilot eligibility")
    acceptance_block_reason: Optional[str] = Field(default=None, description="Reason if acceptance is blocked")
    customer_rating: Optional[float] = Field(default=None, description="Customer average rating")
    pickup_time_slot_start: Optional[str] = Field(default=None, description="Window start time")
    pickup_time_slot_end: Optional[str] = Field(default=None, description="Window end time")
    pickup_time_slot_date: Optional[str] = Field(default=None, description="Window date")


class PilotAvailableJobsResponse(BaseModel):
    """Response payload for available jobs in open pool."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    errands: list[AvailableJobItem] = Field(default_factory=list, description="List of available jobs")
    total: int = Field(..., description="Total count of jobs returned")
    dispatch_state: Optional[dict[str, Any]] = Field(default=None, description="Pilot dispatch state summary")
    dispatch_policy: Optional[dict[str, Any]] = Field(default=None, description="Active dispatch policy rules")


class PilotJobItem(BaseModel):
    """Assigned pilot errand item (active or historical)."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Errand identifier")
    reference_number: str = Field(..., description="Human-readable reference number")
    title: str = Field(..., description="Errand task title")
    description: Optional[str] = Field(default=None, description="Errand description")
    status: str = Field(..., description="Current errand status")
    started_at: Optional[str] = Field(default=None, description="Delivery start timestamp")
    started: bool = Field(default=False, description="Whether delivery has been started")
    pickup_location: Optional[str] = Field(default=None, description="Pickup location")
    dropoff_location: Optional[str] = Field(default=None, description="Dropoff location")
    sensitivity: Optional[str] = Field(default=None, description="Sensitivity rating")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    completed_at: Optional[str] = Field(default=None, description="Completion timestamp")
    note: Optional[str] = Field(default=None, description="Errand instructions")
    customer_name: str = Field(default="Customer", description="Customer display name")
    amount: float = Field(default=0.0, description="Delivery compensation")
    payment_amount_ngn_major: Optional[float] = Field(default=None, description="NGN compensation major unit")
    paymentAmountNgnMajor: Optional[float] = Field(default=None, description="CamelCase alias")
    distance_km: Optional[float] = Field(default=None, description="Distance in km")
    customer_rating: Optional[float] = Field(default=None, description="Rating")
    pickup_time_slot_start: Optional[str] = Field(default=None, description="Time slot start")
    pickup_time_slot_end: Optional[str] = Field(default=None, description="Time slot end")
    pickup_time_slot_date: Optional[str] = Field(default=None, description="Time slot date")


class PilotJobsResponse(BaseModel):
    """Response payload for pilot assigned jobs list."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    errands: list[PilotJobItem] = Field(default_factory=list, description="List of assigned errands")


class PilotJobActionResponse(BaseModel):
    """Standard response when accepting or declining a job."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(..., description="Action status result (e.g. accepted, declined)")
    errand_id: FlexibleId = Field(..., description="Target errand ID")
    pilot_id: Optional[FlexibleId] = Field(default=None, description="Acting pilot ID")
    message: str = Field(..., description="Action result message")


class StartDeliveryResponse(BaseModel):
    """Response when a pilot initiates active delivery."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(default="started", description="Delivery progress status")
    errand_id: FlexibleId = Field(..., description="Errand identifier")
    started_at: str = Field(..., description="ISO timestamp when delivery commenced")
    tracking_active: bool = Field(default=True, description="Whether live GPS tracking is broadcast")
    message: str = Field(..., description="Confirmation message")


class CompleteDeliveryResponse(BaseModel):
    """Response when a pilot concludes and confirms errand delivery."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(default="completed", description="Delivery progress status")
    errand_id: FlexibleId = Field(..., description="Errand identifier")
    completed_at: str = Field(..., description="ISO timestamp when delivery completed")
    message: str = Field(..., description="Confirmation message")


class DelayReasonResponse(BaseModel):
    """Response when reporting a delivery delay explanation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(default="recorded", description="Status of submission")
    errand_id: FlexibleId = Field(..., description="Errand identifier")
    delay_reason: str = Field(..., description="Recorded delay rationale")
    message: str = Field(..., description="Confirmation message")


class TrackingControlResponse(BaseModel):
    """Response when pausing or resuming GPS location tracking."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(..., description="Updated tracking status")
    errand_id: FlexibleId = Field(..., description="Errand identifier")
    tracking_paused: bool = Field(..., description="Whether tracking is currently suspended")
    message: str = Field(..., description="Informational status message")


class ActiveDeliveryResponse(BaseModel):
    """Detailed summary of pilot currently active ongoing delivery."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    has_active_delivery: bool = Field(..., description="True if a delivery is presently in progress")
    errand: Optional[dict[str, Any]] = Field(default=None, description="Active errand object details")


class PilotDocumentItem(BaseModel):
    """Pilot verification or credential document."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Document identifier")
    document_type: Optional[str] = Field(default=None, description="Category of credential")
    original_filename: str = Field(..., description="Original file name")
    content_type: Optional[str] = Field(default=None, description="MIME media type")
    size_bytes: int = Field(..., description="File size in bytes")
    status: str = Field(..., description="Verification status (pending, approved, rejected)")
    review_note: Optional[str] = Field(default=None, description="Reviewer feedback")
    created_at: Optional[str] = Field(default=None, description="Submission timestamp")


class PilotDocumentsListResponse(BaseModel):
    """List of documents uploaded by a pilot."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    documents: list[PilotDocumentItem] = Field(default_factory=list, description="Uploaded documents")


class PilotStatsResponse(BaseModel):
    """Pilot performance metrics and historical statistics."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    pilot_id: FlexibleId = Field(..., description="Pilot user identifier")
    completed_errands: int = Field(..., description="Total successfully completed errands")
    active_errands: int = Field(..., description="Count of active deliveries")
    total_errands: int = Field(..., description="Total errands handled")
    customer_rating: Optional[float] = Field(default=None, description="Average star rating (1-5)")
    active_delivery: Optional[dict[str, Any]] = Field(default=None, description="Current active delivery summary")
    pilot_availability: Optional[str] = Field(default="offline", description="Online availability state")
    admin_dispatch_status: Optional[str] = Field(default="enabled", description="Administrative dispatch status")


class PilotAvailabilityResponse(BaseModel):
    """Confirmation of pilot availability toggle."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    pilot_availability: str = Field(..., description="Updated availability status")
    message: str = Field(..., description="Status message")


class PilotProfileResponse(BaseModel):
    """Comprehensive pilot profile payload."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="User identifier")
    user_uuid: str = Field(..., description="Public stable UUID")
    email: str = Field(..., description="Registered email")
    first_name: Optional[str] = Field(default=None, description="First name")
    last_name: Optional[str] = Field(default=None, description="Last name")
    phone: Optional[str] = Field(default=None, description="Contact telephone number")
    profile_image_url: Optional[str] = Field(default=None, description="Avatar image URL")
    is_email_verified: bool = Field(default=False, description="Email verification state")
    is_pilot: bool = Field(default=True, description="Pilot role confirmation")
    pilot_availability: str = Field(default="offline", description="Availability status")
    admin_dispatch_status: str = Field(default="enabled", description="Dispatch status")
    vehicle_type: Optional[str] = Field(default=None, description="Vehicle category")
    vehicle_make: Optional[str] = Field(default=None, description="Vehicle brand")
    vehicle_model: Optional[str] = Field(default=None, description="Vehicle model")
    vehicle_year: Optional[int] = Field(default=None, description="Year of manufacture")
    license_plate: Optional[str] = Field(default=None, description="Registration plate")
    insurance_provider: Optional[str] = Field(default=None, description="Insurance company")
    insurance_expiry: Optional[str] = Field(default=None, description="Insurance expiry date")
    must_change_password: bool = Field(default=False, description="Whether password change is required")


class PilotProfileUpdateResponse(BaseModel):
    """Profile update confirmation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ok: bool = Field(default=True, description="Success status")
    message: str = Field(..., description="Confirmation message")
    user_id: Optional[FlexibleId] = Field(default=None, description="Pilot user ID")
    profile: Optional[dict[str, Any]] = Field(default=None, description="Updated profile payload")


class PilotChangePasswordResponse(BaseModel):
    """Password change confirmation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ok: bool = Field(default=True, description="Operation outcome")
    message: str = Field(..., description="Confirmation message")
