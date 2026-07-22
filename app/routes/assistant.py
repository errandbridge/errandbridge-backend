from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
	from openai import AsyncOpenAI
except ImportError:
	AsyncOpenAI = None

router = APIRouter(prefix="/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)


class AssistantHistoryItem(BaseModel):
    role: str = Field(..., description="user|assistant|system")
    text: str = Field(..., min_length=1, max_length=4000)


class AssistantChatIn(BaseModel):
	message: str = Field(..., min_length=1, max_length=4000)

	mode: Optional[str] = Field(
		default=None,
		description="public|authenticated (defaults to authenticated)",
		max_length=32,
	)
	conversation_id: Optional[str] = Field(default=None, max_length=120)
	uid: Optional[str] = Field(default=None, max_length=120)
	history: list[AssistantHistoryItem] = Field(default_factory=list)


class AssistantChatOut(BaseModel):
	replyText: str


def _fallback_reply(message: str) -> str:
	text = (message or "").strip().lower()
	if not text:
		return "Tell me what you need and I’ll help gently shape it."
	if any(k in text for k in ["how are you", "how's it going", "how is it going"]):
		return "I’m doing well, thank you 👋 Whenever you’re ready, tell me what you need handled and I’ll help organise it gently, step by step."
	if any(
		k in text
		for k in [
			"just saying hello",
			"only saying hello",
			"just checking",
			"just checking in",
			"hello",
			"hi",
			"hey",
		]
	):
		return "Hello 👋 Whenever you’re ready, tell me what needs handling and I’ll help shape the request clearly."
	if any(k in text for k in ["thanks", "thank you"]):
		return "You’re very welcome ✨ When you’re ready, tell me what you need handled and I’ll help organise it with care."
	if any(k in text for k in ["price", "pricing", "cost", "how much"]):
		return "Tell me the errand type + pickup/dropoff city and I’ll explain the typical pricing range."
	if any(k in text for k in ["track", "tracking", "status", "eta"]):
		return "Share your errand reference (e.g., EB-36-5084) and I’ll help you find the latest status."
	if any(k in text for k in ["support", "agent", "human"]):
		return "I can connect you with ErrandBridge Support. Please share your errand reference and what happened."
	return "Got it - can you share what needs handling, where it should start, where it should end, and any deadline?"


@router.post("/chat", response_model=AssistantChatOut)
async def chat(payload: AssistantChatIn) -> AssistantChatOut:
	api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
	model = (os.getenv("OPENAI_ASSISTANT_MODEL") or "gpt-4o-mini").strip()
	max_tokens_raw = (os.getenv("OPENAI_ASSISTANT_MAX_TOKENS") or "350").strip()
	try:
		max_tokens = int(max_tokens_raw)
	except Exception:
		max_tokens = 350

	mode = (payload.mode or "authenticated").strip().lower()
	if mode not in {"public", "authenticated"}:
		mode = "authenticated"

	# Landing concierge should be concise by default.
	# We still allow overriding via env for emergency tuning.
	if mode == "public" and max_tokens > 300:
		max_tokens = 260

	if not (api_key and AsyncOpenAI):
		# Keep the endpoint usable in dev environments where keys aren’t present.
		return AssistantChatOut(replyText=_fallback_reply(payload.message))

	client = AsyncOpenAI(api_key=api_key)

	public_system_prompt = (
		"You are Toxi, the ErrandBridge Concierge on the public landing page. "
		"Goal: help visitors understand the service and take the next step (start a request). "
		"Be premium, warm, polished, and conversion-oriented. Use short paragraphs and keep the tone soft and reassuring. "
		"Handle greetings and casual chat naturally. "
		"Do not pretend that small talk is an errand request, and do not invent pickup, dropoff, timing, or summary state when the user is only chatting. "
		"You MUST NOT claim to access accounts, dashboards, payments, or live tracking. "
		"If asked for tracking/status, explain that live tracking requires an errand reference and the app, "
		"then invite them to start a request. "
		"Ask at most 1-2 clarifying questions when needed (what needs doing, where it starts, where it ends, deadline). "
		"Protect ErrandBridge's brand: be helpful, calm, and respectful, never robotic, pushy, or overly salesy. "
		"End your response with a clear next step: 'Start a request' (signup)."
	)

	authenticated_system_prompt = (
		"You are Toxi, the ErrandBridge assistant. "
		"Be concise, friendly, calm, and genuinely helpful. "
		"Ask clarifying questions when details are missing (pickup/dropoff city, deadline, reference). "
		"Keep replies soft and polished, in the best interest of ErrandBridge's brand. "
		"Avoid sharing private data."
	)

	system_prompt = (
		public_system_prompt if mode == "public" else authenticated_system_prompt
	)

	# Trim history to keep latency/cost predictable.
	history = payload.history[-10:] if payload.history else []

	input_items = [{"role": "system", "content": system_prompt}]
	for item in history:
		role = (item.role or "").strip().lower()
		if role not in {"user", "assistant", "system"}:
			role = "user"
		input_items.append({"role": role, "content": item.text})

	input_items.append({"role": "user", "content": payload.message})

	try:
		result = await client.responses.create(
			model=model,
			input=input_items,
			max_output_tokens=max_tokens,
		)
		reply = (getattr(result, "output_text", "") or "").strip()
		if not reply:
			reply = "I’m here whenever you’re ready. Tell me what you need handled and I’ll help shape it clearly."
		return AssistantChatOut(replyText=reply)
	except Exception as e:
		logger.exception("Public assistant fallback triggered")
		return AssistantChatOut(replyText=_fallback_reply(payload.message))
