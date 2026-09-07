from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx


def ml_enabled() -> bool:
    return (os.getenv("ML_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def ml_service_url() -> str:
    # In docker-compose, the ml service is reachable at http://ml:8010
    return (os.getenv("ML_SERVICE_URL") or "http://ml:8010").strip()


def ml_timeout_seconds() -> float:
    raw = (os.getenv("ML_TIMEOUT_SECONDS") or "0.8").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.8


async def score_issue(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call the ML service for scoring.

    Returns the JSON response dict on success, else None.
    Never raises (so admin endpoints don't break if ML is down).
    """

    if not ml_enabled():
        return None

    url = f"{ml_service_url().rstrip('/')}/score"
    try:
        async with httpx.AsyncClient(timeout=ml_timeout_seconds()) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                return None
            return resp.json()
    except Exception:
        return None
