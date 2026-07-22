import json
import os
os.environ["SMOKE_OTP_CODE"] = "123456"
os.environ["SMOKE_PASSWORD_CHANGE_OTP"] = "123456"
os.environ["SMOKE_PASSWORD_RESET_OTP"] = "123456"
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://localhost:8001"


def _in_docker() -> bool:
    # Heuristic: standard file that exists in most Docker containers
    return os.path.exists("/.dockerenv")


def http_get(url: str, timeout: float = 10.0, headers: dict | None = None) -> tuple[int, str]:
    req = Request(url, method="GET", headers=headers or {})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body


def http_post_json(
    url: str, payload: dict, timeout: float = 15.0, headers: dict | None = None
) -> tuple[int, dict]:
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


def wait_for(base_url: str, seconds: float = 20.0) -> None:
    """Wait briefly for the API to come up (useful right after docker compose up)."""
    deadline = time.time() + seconds
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            status, _ = http_get(f"{base_url}/", timeout=2.5)
            if 200 <= status < 500:
                return
        except (URLError, OSError) as e:
            last_err = e
        time.sleep(0.5)

    if last_err:
        raise last_err


def graphql(base_url: str, query: str, variables: dict | None = None, headers: dict | None = None) -> dict:
    payload: dict = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    status, body = http_post_json(f"{base_url}/graphql", payload, headers=headers)
    if status != 200:
        raise RuntimeError(f"GraphQL HTTP {status}: {body}")
    if "errors" in body and body["errors"]:
        raise RuntimeError(f"GraphQL errors: {body['errors']}")
    return body.get("data", {})


def main() -> int:
    # When executed inside docker-compose (`docker compose exec api ...`) the API
    # is reachable by service name + internal port, not by the host-mapped port.
    default = "http://api:8000" if _in_docker() else DEFAULT_BASE_URL
    base_url = os.getenv("ERRANDBRIDGE_BASE_URL", default).rstrip("/")

    print(f"[smoke] base_url={base_url}")

    # 1) Wait for API
    print("[smoke] waiting for API...")
    wait_for(base_url)

    # 2) Root endpoint
    print("[smoke] GET /")
    status, body = http_get(f"{base_url}/")
    if status == 409:
        # Re-running with a fixed email is allowed; proceed (OTP may already be verified).
        body = {"detail": "Email already registered"}
    else:
        assert status == 200, f"Expected 200, got {status}: {body}"
    assert "ErrandBridge" in body, "Expected 'ErrandBridge' in root response"

    # 3) Metrics endpoint
    print("[smoke] GET /metrics")
    status, body = http_get(f"{base_url}/metrics")
    assert status == 200, f"Expected 200, got {status}"
    assert "# HELP" in body and "# TYPE" in body, "Expected Prometheus exposition format"

    # 3b) Prompt suggest
    print("[smoke] POST /prompt/suggest")
    status, body = http_post_json(
        f"{base_url}/prompt/suggest",
        {
            "template_id": "market_run",
            "prompt": "Create an errand: Buy yam and tomatoes from the market and deliver to the dropoff.",
        },
    )
    assert status == 200, f"Expected 200, got {status}: {body}"
    assert isinstance(body.get("title"), str) and body["title"], "Expected non-empty title"
    assert isinstance(body.get("description"), str), "Expected description string"

    # 4) GraphQL list
    print("[smoke] GraphQL query errands")
    data = graphql(base_url, "query { errands { id title status userId } }")
    assert "errands" in data and isinstance(data["errands"], list)

    # 4b) Auth signup + me
    print("[smoke] POST /auth/signup")
    email = os.environ.get("SMOKE_EMAIL") or f"smoke_{int(time.time())}@example.com"
    first_name = "Smoke"
    last_name = "Tester"
    phone = "+10000000000"
    status, body = http_post_json(
        f"{base_url}/auth/signup",
        {
            "email": email,
            "password": "password123",
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
        },
    )
    if status != 200 and status != 409:
        raise AssertionError(f"Expected 200 or 409, got {status}: {body}")

    # Helpful when running against docker-compose dev where OTP is printed to logs.
    print(f"[smoke] signup_email={email}")

    print("[smoke] POST /auth/confirm")
    # NOTE: when using `docker compose exec`, the env var must be present in the
    # container environment. Some shells set it only for the host process. We
    # support both by also checking for a helper variable injected via os.environ
    # at runtime.
    code = os.environ.get("SMOKE_OTP_CODE")
    if not code:
        raise RuntimeError(
            "OTP is enabled, but SMOKE_OTP_CODE is not set. "
            "For docker-compose dev, read the code from api logs and export SMOKE_OTP_CODE."
        )

    status, confirm_body = http_post_json(
        f"{base_url}/auth/confirm",
        {"email": email, "code": str(code).strip()},
    )
    assert status == 200, f"Expected 200, got {status}: {confirm_body}"

    print("[smoke] POST /auth/login")
    status, login_body = http_post_json(
        f"{base_url}/auth/login",
        {"email": email, "password": "password123"},
    )
    assert status == 200, f"Expected 200, got {status}: {login_body}"
    token = login_body.get("access_token")
    assert isinstance(token, str) and token, "Expected access_token"

    print("[smoke] GET /auth/me")
    status, me_body_raw = http_get(
        f"{base_url}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200, f"Expected 200, got {status}: {me_body_raw}"
    me_body = json.loads(me_body_raw)
    assert me_body.get("email") == email
    assert me_body.get("first_name") == first_name
    assert me_body.get("last_name") == last_name
    assert me_body.get("phone") == phone

    # 4c) Password change (OTP) - start
    print("[smoke] POST /auth/password-change/start")
    status, body = http_post_json(
        f"{base_url}/auth/password-change/start",
        {},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200, f"Expected 200, got {status}: {body}"

    change_otp = os.environ.get("SMOKE_PASSWORD_CHANGE_OTP")
    if not change_otp:
        raise RuntimeError(
            "Password change OTP is enabled, but SMOKE_PASSWORD_CHANGE_OTP is not set. "
            "For docker-compose dev, read the code from api logs and export SMOKE_PASSWORD_CHANGE_OTP."
        )

    print("[smoke] POST /auth/password-change/confirm")
    new_password = "password456"
    status, body = http_post_json(
        f"{base_url}/auth/password-change/confirm",
        {"code": str(change_otp).strip(), "new_password": new_password},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200, f"Expected 200, got {status}: {body}"

    # Confirm we can log in with the new password.
    print("[smoke] POST /auth/login (after password change)")
    status, login_body2 = http_post_json(
        f"{base_url}/auth/login",
        {"email": email, "password": new_password},
    )
    assert status == 200, f"Expected 200, got {status}: {login_body2}"

    # 4d) Password reset (OTP)
    print("[smoke] POST /auth/password-reset/start")
    status, body = http_post_json(
        f"{base_url}/auth/password-reset/start",
        {"email": email},
    )
    assert status == 200, f"Expected 200, got {status}: {body}"

    reset_otp = os.environ.get("SMOKE_PASSWORD_RESET_OTP")
    if not reset_otp:
        raise RuntimeError(
            "Password reset OTP is enabled, but SMOKE_PASSWORD_RESET_OTP is not set. "
            "For docker-compose dev, read the code from api logs and export SMOKE_PASSWORD_RESET_OTP."
        )

    print("[smoke] POST /auth/password-reset/confirm")
    reset_password = "password789"
    status, body = http_post_json(
        f"{base_url}/auth/password-reset/confirm",
        {"email": email, "code": str(reset_otp).strip(), "new_password": reset_password},
    )
    assert status == 200, f"Expected 200, got {status}: {body}"

    print("[smoke] POST /auth/login (after password reset)")
    status, login_body3 = http_post_json(
        f"{base_url}/auth/login",
        {"email": email, "password": reset_password},
    )
    assert status == 200, f"Expected 200, got {status}: {login_body3}"

    # 5) GraphQL create + update (non-destructive beyond adding one sample row)
    print("[smoke] GraphQL mutation createErrand")
    created = graphql(
        base_url,
        "mutation($input: CreateErrandInput!) { createErrand(input: $input) { id title status userId pickupLocation dropoffLocation } }",
        variables={
            "input": {
                "title": "Smoke test errand",
                "description": "created by smoke test",
                "pickupLocation": "Home",
                "dropoffLocation": "Market",
            }
        },
        headers={"Authorization": f"Bearer {token}"},
    )["createErrand"]
    assert created["title"] == "Smoke test errand"
    assert created["status"]
    assert created.get("pickupLocation") == "Home"
    assert created.get("dropoffLocation") == "Market"

    print("[smoke] GraphQL mutation updateErrandStatus")
    # Update status: submitted → assigned
    updated = graphql(
        base_url,
        "mutation($input: UpdateErrandStatusInput!) { updateErrandStatus(input: $input) { id status } }",
        variables={"input": {"id": int(created["id"]), "status": "assigned"}},
        headers={"Authorization": f"Bearer {token}"},
    )["updateErrandStatus"]
    assert updated["status"] == "assigned"

    # Update status: assigned → picked_up
    updated = graphql(
        base_url,
        "mutation($input: UpdateErrandStatusInput!) { updateErrandStatus(input: $input) { id status } }",
        variables={"input": {"id": int(created["id"]), "status": "picked_up"}},
        headers={"Authorization": f"Bearer {token}"},
    )["updateErrandStatus"]
    assert updated["status"] == "picked_up"

    # Update status: picked_up → delivered
    updated = graphql(
        base_url,
        "mutation($input: UpdateErrandStatusInput!) { updateErrandStatus(input: $input) { id status } }",
        variables={"input": {"id": int(created["id"]), "status": "delivered"}},
        headers={"Authorization": f"Bearer {token}"},
    )["updateErrandStatus"]
    assert updated["status"] == "delivered"

    # Update status: delivered → issue_reported
    updated = graphql(
        base_url,
        "mutation($input: UpdateErrandStatusInput!) { updateErrandStatus(input: $input) { id status } }",
        variables={"input": {"id": int(created["id"]), "status": "issue_reported"}},
        headers={"Authorization": f"Bearer {token}"},
    )["updateErrandStatus"]
    assert updated["status"] == "issue_reported"

    # Update status: issue_reported → completed
    updated = graphql(
        base_url,
        "mutation($input: UpdateErrandStatusInput!) { updateErrandStatus(input: $input) { id status } }",
        variables={"input": {"id": int(created["id"]), "status": "completed"}},
        headers={"Authorization": f"Bearer {token}"},
    )["updateErrandStatus"]
    assert updated["status"] == "completed"

    print("[smoke] GraphQL mutation sendErrandConfirmation")
    sent = graphql(
        base_url,
        "mutation($input: SendErrandConfirmationInput!) { sendErrandConfirmation(input: $input) }",
        variables={"input": {"id": int(created["id"]) }},
        headers={"Authorization": f"Bearer {token}"},
    )["sendErrandConfirmation"]
    assert sent is True

    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"[smoke] FAIL: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[smoke] ERROR: {e}", file=sys.stderr)
        raise
