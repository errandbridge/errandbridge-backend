#!/usr/bin/env python3
"""No-OTP smoke checks for ErrandBridge backend.

Goals:
- Fast and deterministic
- Does not require signup/login/OTP
- Works both from host (python) and inside docker compose (service URL)

Checks:
- GET / returns expected marker
- GET /metrics returns Prometheus exposition format
- GraphQL accepts confirmationSentAt field on Errand selection set
- (Optional) Admin errands endpoint is reachable (only if ADMIN_BEARER_TOKEN is provided)

Usage examples:
- Host (repo venv):
  ERRANDBRIDGE_BASE_URL=http://localhost:8001 /path/to/.venv/bin/python errandbridge-backend/scripts/smoke_no_otp.py

- Docker:
  docker compose exec -T api /usr/local/bin/python scripts/smoke_no_otp.py

"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://localhost:8001"


def _in_docker() -> bool:
    return os.path.exists("/.dockerenv")


@dataclass(frozen=True)
class HttpResult:
    status: int
    body_text: str


def http_get(
    url: str, timeout: float = 10.0, headers: dict[str, str] | None = None
) -> HttpResult:
    req = Request(url, method="GET", headers=headers or {})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return HttpResult(status=resp.status, body_text=body)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return HttpResult(status=e.code, body_text=body)


def http_post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}


def wait_for(base_url: str, seconds: float = 15.0) -> None:
    deadline = time.time() + seconds
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            res = http_get(f"{base_url}/", timeout=2.5)
            if 200 <= res.status < 500:
                return
        except (URLError, OSError) as e:
            last_err = e
        time.sleep(0.5)

    if last_err:
        raise last_err


def graphql(
    base_url: str, query: str, variables: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query}
    if variables is not None:
        payload["variables"] = variables

    status, body = http_post_json(f"{base_url}/graphql", payload)
    if status != 200:
        raise RuntimeError(f"GraphQL HTTP {status}: {body}")
    if body.get("errors"):
        raise RuntimeError(f"GraphQL errors: {body['errors']}")
    return body.get("data", {})


def main() -> int:
    default = "http://api:8000" if _in_docker() else DEFAULT_BASE_URL
    base_url = os.getenv("ERRANDBRIDGE_BASE_URL", default).rstrip("/")

    print(f"[smoke-no-otp] base_url={base_url}")

    print("[smoke-no-otp] waiting for API...")
    wait_for(base_url)

    print("[smoke-no-otp] GET /")
    root = http_get(f"{base_url}/")
    assert root.status == 200, f"Expected 200, got {root.status}: {root.body_text}"
    assert (
        "ErrandBridge" in root.body_text
    ), "Expected 'ErrandBridge' marker in root response"

    print("[smoke-no-otp] GET /metrics")
    metrics = http_get(f"{base_url}/metrics")
    assert (
        metrics.status == 200
    ), f"Expected 200, got {metrics.status}: {metrics.body_text[:250]}"
    assert (
        "# HELP" in metrics.body_text and "# TYPE" in metrics.body_text
    ), "Expected Prometheus exposition format"

    print("[smoke-no-otp] GraphQL: schema accepts confirmationSentAt")
    data = graphql(base_url, "query { errands { id confirmationSentAt } }")
    assert "errands" in data and isinstance(
        data["errands"], list
    ), "Expected errands list"

    admin_token = os.getenv("ADMIN_BEARER_TOKEN")
    if admin_token:
        print("[smoke-no-otp] GET /admin/errands (token provided)")
        res = http_get(
            f"{base_url}/admin/errands",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status == 200, f"Expected 200, got {res.status}: {res.body_text}"
        try:
            body = json.loads(res.body_text)
        except Exception as e:
            raise AssertionError(
                f"Expected JSON body from /admin/errands but failed to parse: {e}\n{res.body_text}"
            )

        assert isinstance(body, list), "Expected list response from /admin/errands"
        if body:
            sample = body[0]
            assert (
                "reference_number" in sample
            ), "Expected reference_number in admin errand item"
            assert (
                "confirmation_sent_at" in sample
            ), "Expected confirmation_sent_at in admin errand item"
        print("[smoke-no-otp] /admin/errands OK")
    else:
        print(
            "[smoke-no-otp] skipping /admin/errands (set ADMIN_BEARER_TOKEN to enable)"
        )

    print("[smoke-no-otp] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
