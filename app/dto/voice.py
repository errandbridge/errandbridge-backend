"""Voice Telephony Domain Data Transfer Objects (DTOs)."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.dto.common import FlexibleId


class VoiceCallStartResponse(BaseModel):
    """Masked voice call initiation payload."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    session_id: FlexibleId = Field(..., description="Voice call session ID")
    status: str = Field(..., description="Session state (dialing, created, failed)")
    pilot_call_sid: Optional[str] = Field(default=None, description="Twilio call SID for pilot leg")
    customer_call_sid: Optional[str] = Field(default=None, description="Twilio call SID for customer leg")
    pilot_mask: Optional[str] = Field(default=None, description="Masked pilot phone number")
    customer_mask: Optional[str] = Field(default=None, description="Masked customer phone number")


class VoiceCallbackResponse(BaseModel):
    """Telephony webhook confirmation."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ok: bool = Field(default=True, description="Webhook receipt acknowledgement")
