"""Support and Incidents Domain Data Transfer Objects (DTOs)."""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.dto.common import FlexibleId, IncidentStatus


class IncidentReportItem(BaseModel):
    """Incident report record."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Incident unique identifier")
    errand_id: FlexibleId = Field(..., description="Related errand ID")
    pilot_id: Optional[FlexibleId] = Field(default=None, description="Assigned pilot if any")
    reporter_role: str = Field(..., description="Role of reporting party (client or pilot)")
    reason: str = Field(..., description="Incident category reason")
    notes: Optional[str] = Field(default=None, description="Incident narrative details")
    status: str = Field(default="open", description="Current incident resolution status")
    preferred_resolution: Optional[str] = Field(default=None, description="Requested remedy")
    created_at: Optional[str] = Field(default=None, description="ISO creation timestamp")
    resolved_at: Optional[str] = Field(default=None, description="ISO resolution timestamp")


class IncidentReportResponse(BaseModel):
    """Confirmation when filing an incident report."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(default="reported", description="Outcome status")
    incident_id: FlexibleId = Field(..., description="Created incident ID")
    errand_id: FlexibleId = Field(..., description="Errand ID")
    message: str = Field(default="Incident reported successfully", description="Status message")


class IncidentListResponse(BaseModel):
    """List of incident reports."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    incidents: list[IncidentReportItem] = Field(default_factory=list, description="List of incidents")


class IncidentMessageItem(BaseModel):
    """Message in an incident thread."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Message identifier")
    incident_id: FlexibleId = Field(..., description="Parent incident ID")
    sender_id: FlexibleId = Field(..., description="Author user ID")
    sender_role: str = Field(..., description="Role of author")
    message_text: str = Field(..., description="Message body content")
    created_at: Optional[str] = Field(default=None, description="Timestamp sent")


class IncidentMessagesListResponse(BaseModel):
    """Thread messages for an incident."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    messages: list[IncidentMessageItem] = Field(default_factory=list, description="Incident messages")


class SupportConversationItem(BaseModel):
    """Support discussion conversation summary."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Conversation identifier")
    user_id: Optional[FlexibleId] = Field(default=None, description="Customer or pilot user ID")
    topic: Optional[str] = Field(default=None, description="Discussion topic")
    status: str = Field(default="open", description="Conversation status")
    created_at: Optional[str] = Field(default=None, description="Timestamp initiated")
    updated_at: Optional[str] = Field(default=None, description="Last activity timestamp")


class SupportConversationsListResponse(BaseModel):
    """List of support conversations."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    conversations: list[SupportConversationItem] = Field(default_factory=list, description="Conversations list")


class SupportMessageItem(BaseModel):
    """Message inside a support conversation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Message identifier")
    conversation_id: FlexibleId = Field(..., description="Parent conversation ID")
    sender_type: str = Field(..., description="user or support/admin")
    message_text: str = Field(..., description="Text body")
    created_at: Optional[str] = Field(default=None, description="Timestamp")


class SupportMessagesListResponse(BaseModel):
    """List of messages in a support conversation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    messages: list[SupportMessageItem] = Field(default_factory=list, description="Messages list")


class SupportActionResponse(BaseModel):
    """Standard response for support complaints, reviews, and messages."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(default="received", description="Operation status outcome")
    id: Optional[FlexibleId] = Field(default=None, description="Created record ID if applicable")
    message: str = Field(default="Submitted successfully", description="Informational message")


class IncidentAlertItem(BaseModel):
    """Urgent incident alert item."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Incident identifier")
    errand_id: FlexibleId = Field(..., description="Errand ID")
    issue_type: Optional[str] = Field(default=None, description="Incident issue classification")
    description: Optional[str] = Field(default=None, description="Incident detail")
    errand_reference: Optional[str] = Field(default=None, description="Errand reference code")
    status: str = Field(..., description="Incident status")
    updated_at: Optional[str] = Field(default=None, description="Last update ISO timestamp")
    created_at: Optional[str] = Field(default=None, description="Creation ISO timestamp")


class IncidentAlertsResponse(BaseModel):
    """Urgent incident alerts container."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    incidents: list[IncidentAlertItem] = Field(default_factory=list, description="List of urgent incident alerts")


class IncidentResolveResponse(BaseModel):
    """Resolution payload when closing an incident."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    success: bool = Field(default=True, description="Action success status")
    status: str = Field(..., description="Updated incident status")
    released_to_admin: bool = Field(default=False, description="Whether errand was returned to admin queue")
    errand_status: Optional[str] = Field(default=None, description="Updated errand status")
    errand_id: Optional[FlexibleId] = Field(default=None, description="Errand identifier")


class SupportHandoffAlertItem(BaseModel):
    """Support handoff alert item."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Conversation ID")
    session_id: Optional[str] = Field(default=None, description="Session identifier")
    status: str = Field(..., description="Conversation status")
    handoff_requested: bool = Field(default=True, description="Whether handoff was requested")
    updated_at: Optional[str] = Field(default=None, description="Last update timestamp")


class SupportHandoffAlertsResponse(BaseModel):
    """Support handoff alerts container."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    conversations: list[SupportHandoffAlertItem] = Field(default_factory=list, description="Pending handoff conversations")


class SupportSuccessResponse(BaseModel):
    """Standard success acknowledgment."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    success: bool = Field(default=True, description="Operation success state")
