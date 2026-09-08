"""Errands, Attachments, and Messages Domain Data Transfer Objects (DTOs)."""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.dto.common import FlexibleId


class AttachmentItem(BaseModel):
    """Attachment document metadata associated with an errand."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Attachment ID")
    errand_id: FlexibleId = Field(..., description="Errand ID")
    filename: Optional[str] = Field(default=None, description="Display filename")
    original_filename: str = Field(..., description="Original filename on upload")
    content_type: Optional[str] = Field(default=None, description="MIME media type")
    size_bytes: int = Field(default=0, description="Byte size")
    label: Optional[str] = Field(default=None, description="Document label or category")
    review_status: str = Field(default="pending", description="Review status (pending, approved, rejected)")
    created_at: Optional[str] = Field(default=None, description="Upload timestamp")


class AttachmentLabelResponse(BaseModel):
    """Response after modifying an attachment label."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Attachment ID")
    label: Optional[str] = Field(default=None, description="Updated label")
    updatedAt: Optional[str] = Field(default=None, description="CamelCase timestamp")


class AttachmentShareResponse(BaseModel):
    """Response when creating a temporary secure sharing link for an attachment."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    share_token: str = Field(..., description="Access token for public link")
    share_url: str = Field(..., description="Full download URL")
    expires_at: Optional[str] = Field(default=None, description="Token expiration timestamp")


class ErrandMessageItem(BaseModel):
    """Message in an errand direct chat thread."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Message identifier")
    errand_id: FlexibleId = Field(..., description="Related errand identifier")
    sender_id: FlexibleId = Field(..., description="Author user identifier")
    sender_name: Optional[str] = Field(default=None, description="Author display name")
    message: str = Field(..., description="Message text content")
    created_at: Optional[str] = Field(default=None, description="ISO creation timestamp")


class ErrandMessagesResponse(BaseModel):
    """List of chat messages for an errand thread."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    messages: list[ErrandMessageItem] = Field(default_factory=list, description="Messages list")
    total: int = Field(default=0, description="Message count")

class ErrandAttachmentItem(BaseModel):
    """Customer errand attachment item."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: FlexibleId = Field(..., description="Attachment unique identifier")
    errandId: FlexibleId = Field(..., description="Parent errand ID")
    filename: str = Field(..., description="Attachment filename")
    contentType: Optional[str] = Field(default=None, description="MIME media type")
    sizeBytes: int = Field(default=0, description="File size in bytes")
    url: str = Field(..., description="Download URL path")
    label: Optional[str] = Field(default=None, description="Category label")
    reviewStatus: Optional[str] = Field(default="pending", description="Review status")
    reviewNote: Optional[str] = Field(default=None, description="Review notes")
    reviewedAt: Optional[str] = Field(default=None, description="Reviewed timestamp")
    reviewedByUserId: Optional[FlexibleId] = Field(default=None, description="Reviewer user ID")
    createdAt: Optional[str] = Field(default=None, description="Upload timestamp")
