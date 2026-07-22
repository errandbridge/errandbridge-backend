from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

try:
	from openai import AsyncOpenAI
except ImportError:
	AsyncOpenAI = None

router = APIRouter(prefix="/v1/toxi", tags=["toxi"])
logger = logging.getLogger(__name__)


Intent = Literal[
	"greeting",
	"new_request",
	"pricing",
	"patch",
	"redirect",
	"support",
	"status",
	"unknown",
]

Confidence = Literal["low", "medium", "high"]


class ToxiActionLink(BaseModel):
	label: str = Field(..., min_length=1, max_length=80)
	href: str = Field(..., min_length=1, max_length=500)
	icon: Literal["arrow", "login", "track", "payment", "support"] = Field(...)
	variant: Literal["primary", "secondary", "ghost"] = Field(...)

	class Config:
		extra = "forbid"


class ToxiStructuredFields(BaseModel):
	serviceType: Optional[str] = None
	pickupLocation: Optional[str] = None
	dropoffLocation: Optional[str] = None
	deadline: Optional[str] = None
	notes: Optional[str] = None
	specialRequirements: Optional[str] = None
	routeType: Optional[str] = None
	city: Optional[str] = None
	country: Optional[str] = None
	tier: Optional[Literal["standard", "priority", "concierge"]] = None
	higherProof: Optional[bool] = None
	airportCoordination: Optional[bool] = None

	class Config:
		extra = "forbid"


class ToxiStructuredResponse(BaseModel):
	mode: Literal["openai", "fallback"] = "openai"
	intent: Intent
	reply_text: str = Field(..., min_length=1, max_length=4000)
	fields: ToxiStructuredFields
	patch: ToxiStructuredFields
	actionLink: Optional[ToxiActionLink] = None
	needsClarification: bool
	missingFields: List[str] = Field(default_factory=list)
	confidence: Confidence

	class Config:
		extra = "forbid"


class ToxiStructuredRequest(BaseModel):
	message: str = Field(..., min_length=1, max_length=4000)
	mode: Optional[str] = Field(
		default="request_builder",
		description="request_builder (reserved for future: landing/client_support)",
		max_length=64,
	)
	page_context: Dict[str, Any] = Field(default_factory=dict)

	class Config:
		extra = "forbid"


def _is_enabled() -> bool:
	return (os.getenv("OPENAI_TOXI_ENABLED") or "").strip().lower() == "true"


def _build_fallback(message: str) -> ToxiStructuredResponse:
	# Always return a schema-valid response so the frontend can safely proceed.
	return ToxiStructuredResponse(
		mode="fallback",
		intent="unknown",
		reply_text=(
			"I’m happy to help. Tell me what needs to be handled, where it should start, where it should end, and when you need it done."
		),
		fields=ToxiStructuredFields(
			serviceType=None,
			pickupLocation=None,
			dropoffLocation=None,
			deadline=None,
			notes=None,
			specialRequirements=None,
			routeType=None,
			city=None,
			country=None,
			tier=None,
			higherProof=None,
			airportCoordination=None,
		),
		patch=ToxiStructuredFields(
			serviceType=None,
			pickupLocation=None,
			dropoffLocation=None,
			deadline=None,
			notes=None,
			specialRequirements=None,
			routeType=None,
			city=None,
			country=None,
			tier=None,
			higherProof=None,
			airportCoordination=None,
		),
		actionLink=None,
		needsClarification=True,
		missingFields=["serviceType", "pickupLocation", "dropoffLocation", "deadline"],
		confidence="low",
	)


_TOXI_SCHEMA: Dict[str, Any] = {
	"type": "object",
	"additionalProperties": False,
	"properties": {
		"mode": {"type": "string", "enum": ["openai", "fallback"]},
		"intent": {
			"type": "string",
			"enum": [
				"greeting",
				"new_request",
				"pricing",
				"patch",
				"redirect",
				"support",
				"status",
				"unknown",
			],
		},
		"reply_text": {"type": "string"},
		"fields": {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"serviceType": {"type": ["string", "null"]},
				"pickupLocation": {"type": ["string", "null"]},
				"dropoffLocation": {"type": ["string", "null"]},
				"deadline": {"type": ["string", "null"]},
				"notes": {"type": ["string", "null"]},
				"specialRequirements": {"type": ["string", "null"]},
				"routeType": {"type": ["string", "null"]},
				"city": {"type": ["string", "null"]},
				"country": {"type": ["string", "null"]},
				"tier": {
					"type": ["string", "null"],
					"enum": ["standard", "priority", "concierge", None],
				},
				"higherProof": {"type": ["boolean", "null"]},
				"airportCoordination": {"type": ["boolean", "null"]},
			},
			"required": [
				"serviceType",
				"pickupLocation",
				"dropoffLocation",
				"deadline",
				"notes",
				"specialRequirements",
				"routeType",
				"city",
				"country",
				"tier",
				"higherProof",
				"airportCoordination",
			],
		},
		"patch": {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"serviceType": {"type": ["string", "null"]},
				"pickupLocation": {"type": ["string", "null"]},
				"dropoffLocation": {"type": ["string", "null"]},
				"deadline": {"type": ["string", "null"]},
				"notes": {"type": ["string", "null"]},
				"specialRequirements": {"type": ["string", "null"]},
				"routeType": {"type": ["string", "null"]},
				"city": {"type": ["string", "null"]},
				"country": {"type": ["string", "null"]},
				"tier": {
					"type": ["string", "null"],
					"enum": ["standard", "priority", "concierge", None],
				},
				"higherProof": {"type": ["boolean", "null"]},
				"airportCoordination": {"type": ["boolean", "null"]},
			},
			"required": [
				"serviceType",
				"pickupLocation",
				"dropoffLocation",
				"deadline",
				"notes",
				"specialRequirements",
				"routeType",
				"city",
				"country",
				"tier",
				"higherProof",
				"airportCoordination",
			],
		},
		"actionLink": {
			"anyOf": [
				{"type": "null"},
				{
					"type": "object",
					"additionalProperties": False,
					"properties": {
						"label": {"type": "string"},
						"href": {"type": "string"},
						"icon": {
							"type": "string",
							"enum": ["arrow", "login", "track", "payment", "support"],
						},
						"variant": {
							"type": "string",
							"enum": ["primary", "secondary", "ghost"],
						},
					},
					"required": ["label", "href", "icon", "variant"],
				},
			],
		},
		"needsClarification": {"type": "boolean"},
		"missingFields": {"type": "array", "items": {"type": "string"}},
		"confidence": {"type": "string", "enum": ["low", "medium", "high"]},
	},
	"required": [
		"mode",
		"intent",
		"reply_text",
		"fields",
		"patch",
		"actionLink",
		"needsClarification",
		"missingFields",
		"confidence",
	],
}


@router.post("/structured", response_model=ToxiStructuredResponse)
async def structured(req: ToxiStructuredRequest) -> ToxiStructuredResponse:
	# Explicit feature flag gate (safe rollout).
	if not _is_enabled():
		return _build_fallback(req.message)

	api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
	model = (os.getenv("OPENAI_TOXI_MODEL") or "gpt-4o-mini").strip()
	max_tokens_raw = (os.getenv("OPENAI_TOXI_MAX_TOKENS") or "450").strip()
	try:
		max_tokens = int(max_tokens_raw)
	except Exception:
		max_tokens = 450

	if not (api_key and AsyncOpenAI):
		return _build_fallback(req.message)

	mode = (req.mode or "request_builder").strip().lower()
	# For now, we only support request_builder. Everything else returns fallback.
	if mode not in {"request_builder"}:
		return _build_fallback(req.message)

	client = AsyncOpenAI(api_key=api_key)

	system_prompt = (
		"You are Toxi, the ErrandBridge concierge. "
		"You are a premium operational assistant, not a generic chatbot. "
		"Be warm, polished, calm, and genuinely helpful in a way that protects ErrandBridge's brand. "
		"Sound human and reassuring, but never fluffy or overly chatty. "
		"Do not treat greetings, pleasantries, thanks, or casual chat as an errand request. "
		"When the user is only chatting, keep fields and patch values null, avoid inventing summary state, and respond naturally. "
		"Extract useful request details from messy user input. "
		"Always separate the action from the locations. Never use a place noun like 'airport', 'Lagos', or 'Ibadan' as the serviceType unless the user literally asked for an airport transfer; even then prefer action labels like 'airport pickup / transfer'. "
		"If the user says collect, meet, pick up, receive, drive, transport, or take a person somewhere, preserve that as the task rather than collapsing it into a place. "
		"If the request sounds like collecting someone from an airport and taking them onward, the serviceType should reflect pickup/transfer, pickupLocation should be the airport, and dropoffLocation should be the destination. "
		"Never invent final prices, request status, authentication state, or redirects. "
		"If redirection is needed, return an actionLink object rather than a raw URL in chat. "
		"Suggest form patches, but do not assume they are applied. "
		"Ask only for missing essentials. Ask one precise next question at a time. "
		"When you already know some fields, acknowledge them briefly and then ask only for the next missing field."
	)

	developer_prompt = (
		"Current mode: request_builder. "
		"The user is already inside the request flow. "
		"Use existing request context. Do not restart intake from zero. "
		"If the message is a greeting, social remark, or acknowledgment, return intent='greeting' or intent='unknown' with an empty/no-op patch and no invented fields. "
		"If you are uncertain about a field, leave it null instead of guessing. "
		"Prefer specific, natural service labels like 'person pickup / transport', 'airport pickup / transfer', 'courier / delivery', or 'passport / visa pickup' over vague nouns. "
		"Do not repeat generic prompts like 'what needs to be done' if the action is already clear from the user message or page context. "
		"Return only structured JSON matching the required schema. "
		"Set mode to 'openai'.\n\n"
		f"Page context: {json.dumps(req.page_context or {}, ensure_ascii=False)}"
	)

	try:
		result = await client.responses.create(
			model=model,
			input=[
				{"role": "system", "content": system_prompt},
				{"role": "developer", "content": developer_prompt},
				{"role": "user", "content": req.message},
			],
			max_output_tokens=max_tokens,
			response_format={
				"type": "json_schema",
				"json_schema": {
					"name": "toxi_response",
					"strict": True,
					"schema": _TOXI_SCHEMA,
				},
			},
		)

		content = (getattr(result, "output_text", "") or "").strip()
		if not content:
			return _build_fallback(req.message)

		parsed = json.loads(content)
		# Validate/normalize to our response model.
		return ToxiStructuredResponse.parse_obj(parsed)
	except Exception:
		# Never break Toxi UX if OpenAI fails.
		logger.exception("Structured Toxi fallback triggered")
		return _build_fallback(req.message)
