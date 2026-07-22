from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator


class ScoreRequest(BaseModel):
    # Keep this schema flexible and forward-compatible.
    issueTitle: Optional[str] = None
    issueDescription: Optional[str] = None
    preferredResolution: Optional[str] = None
    customerName: Optional[str] = None

    # Optional context knobs
    amount: Optional[float] = None
    currency: Optional[str] = None


class ScoreResponse(BaseModel):
    priority: int = Field(..., ge=0, le=100)
    tags: List[str]
    reasons: List[str]
    policyVersion: str


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def score_issue(payload: ScoreRequest) -> ScoreResponse:
    """Deterministic scoring rules.

    Contract:
    - input: ScoreRequest
    - output: priority 0..100 + tags + reasons
    - no side effects
    """

    text = " ".join(
        [
            _norm(payload.issueTitle),
            _norm(payload.issueDescription),
            _norm(payload.preferredResolution),
        ]
    ).strip()

    tags: List[str] = []
    reasons: List[str] = []
    priority = 10

    # High urgency keywords
    urgent_terms = ["urgent", "asap", "immediately", "emergency", "now"]
    if any(t in text for t in urgent_terms):
        priority += 35
        tags.append("urgent")
        reasons.append("Contains urgent language")

    # Safety / fraud / payment risk
    risk_terms = ["fraud", "scam", "chargeback", "stolen", "police", "threat", "unsafe"]
    if any(t in text for t in risk_terms):
        priority += 45
        tags.append("risk")
        reasons.append("Contains potential safety/fraud indicators")

    # Delivery / no-show
    delivery_terms = ["no show", "didn't arrive", "did not arrive", "missing", "late"]
    if any(t in text for t in delivery_terms):
        priority += 20
        tags.append("delivery")
        reasons.append("Delivery/no-show related")

    # Amount-based bump
    if payload.amount is not None:
        if payload.amount >= 200:
            priority += 20
            tags.append("high_value")
            reasons.append("High value amount")
        elif payload.amount >= 100:
            priority += 10
            tags.append("mid_value")
            reasons.append("Mid value amount")

    # Preferred resolution hints
    if "refund" in text:
        tags.append("refund")
    if "reschedule" in text:
        tags.append("reschedule")

    # De-dupe tags while keeping order
    seen = set()
    tags = [t for t in tags if not (t in seen or seen.add(t))]

    # Clamp
    priority = max(0, min(100, priority))

    return ScoreResponse(
        priority=priority,
        tags=tags,
        reasons=reasons,
        policyVersion="heuristics-v1",
    )


app = FastAPI(title="ErrandBridge ML", version="0.1.0")

# Prometheus instrumentation
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest) -> ScoreResponse:
    return score_issue(req)
