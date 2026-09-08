"""Reusable Core DTOs, Enums, and Response Wrappers for ErrandBridge.

Provides base models with camelCase aliases (CamelModel), flexible ID types,
monetary representation, standard pagination, and error contracts.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T")

# Flexible ID accepting UUID, integer, or string representation
FlexibleId = Union[uuid.UUID, int, str]


class ErrandStatus(str, Enum):
    """Canonical errand lifecycle status values."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PilotAvailabilityStatus(str, Enum):
    """Pilot availability states."""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"


class UserRole(str, Enum):
    """User authorization roles."""
    CLIENT = "client"
    PILOT = "pilot"
    ADMIN = "admin"


class IncidentStatus(str, Enum):
    """Support and delivery incident resolution statuses."""
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class VerificationStatus(str, Enum):
    """Identity and document verification states."""
    PENDING = "pending"
    PENDING_MANUAL = "pending_manual"
    APPROVED = "approved"
    VERIFIED = "verified"
    REJECTED = "rejected"


class PaymentStatus(str, Enum):
    """Transaction and errand payment states."""
    UNPAID = "unpaid"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class TrackingStatus(str, Enum):
    """Live GPS tracking availability states."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class ResponseStatus(str, Enum):
    """API envelope status discriminator."""
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    PENDING = "PENDING"


class CamelModel(BaseModel):
    """Base Pydantic model with camelCase serialization and snake_case alias support."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Money(CamelModel):
    """Standard machine-readable monetary structure preserving currency precision."""
    amount_minor: int = Field(
        ...,
        description="Monetary value in smallest currency units (e.g. kobo or cents).",
        examples=[500000],
    )
    currency: str = Field(
        default="NGN",
        description="Three-letter ISO-4217 currency code.",
        examples=["NGN"],
    )
    amount_major: float = Field(
        ...,
        description="Decimal monetary representation in major units.",
        examples=[5000.0],
    )


class PaginationMeta(CamelModel):
    """Reusable pagination metadata for collection endpoints."""
    limit: int = Field(..., description="Maximum items requested per page.", examples=[20])
    offset: int = Field(..., description="Number of items skipped.", examples=[0])
    total: int = Field(..., description="Total items matching query filter.", examples=[137])
    has_more: bool = Field(..., description="True if subsequent pages exist.", examples=[True])


class PaginatedResponse(CamelModel, Generic[T]):
    """Standard paginated collection envelope."""
    items: list[T] = Field(..., description="List of page items.")
    pagination: PaginationMeta = Field(..., description="Pagination metadata.")


class ApiError(CamelModel):
    """Structured business and validation error contract."""
    code: str = Field(
        ...,
        description="Machine-readable error code (e.g. ERRAND_NOT_FOUND, UNAUTHORIZED).",
        examples=["ERRAND_NOT_FOUND"],
    )
    message: str = Field(
        ...,
        description="Human-readable error explanation.",
        examples=["The requested errand was not found or has expired."],
    )
    details: Optional[Any] = Field(
        default=None,
        description="Contextual error payload or validation breakdown.",
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier for request auditing.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when error occurred.",
    )
    path: Optional[str] = Field(
        default=None,
        description="Request route path that produced the error.",
    )


class ApiResponse(CamelModel, Generic[T]):
    """Predictable top-level API response envelope for new versioned endpoints."""
    status: ResponseStatus = Field(
        default=ResponseStatus.SUCCESS,
        description="Operation status discriminator.",
    )
    code: int = Field(default=200, description="HTTP status code equivalent.")
    message: str = Field(
        default="Operation completed successfully",
        description="Summary message.",
    )
    data: T = Field(..., description="Strongly-typed payload.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC generation timestamp.",
    )
    error: Optional[ApiError] = Field(
        default=None,
        description="Populated with error details when status is ERROR.",
    )
    path: Optional[str] = Field(
        default=None,
        description="Request route path.",
    )
