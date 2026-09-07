#!/usr/bin/env python3
"""Smoke test for admin delete cascade.

This script:
- signs up + logs in an admin user (must be in ADMIN_EMAILS)
- signs up + logs in a pilot user
- uploads a pilot document (creates PilotDocument FK row)
- deletes the pilot via /admin/users/{id}

Usage (optional):
  BASE_URL=http://localhost:8001 python3 scripts/smoke_admin_delete.py

Notes:
- Uses stdlib only (no requests dependency).
"""

from __future__ import annotations

import json
import os
import ssl
import uuid
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse


@dataclass
class HttpResult:
    status: int
    reason: str
    headers: Dict[str, str]
    body: bytes


def _conn(parsed):
    if parsed.scheme == "https":
        ctx = ssl.create_default_context()
        return HTTPSConnection(parsed.hostname, parsed.port or 443, context=ctx)
    return HTTPConnection(parsed.hostname, parsed.port or 80)


def _request(
    base_url: str,
    method: str,
    path: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
) -> HttpResult:
    parsed = urlparse(base_url)
    conn = _conn(parsed)
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    conn.request(method, path, body=body, headers=req_headers)
    resp = conn.getresponse()
    resp_body = resp.read() or b""
    resp_headers = {k.lower(): v for k, v in resp.getheaders()}
    return HttpResult(
        status=resp.status, reason=resp.reason, headers=resp_headers, body=resp_body
    )


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[HttpResult, Optional[Dict[str, Any]]]:
    body_bytes = None
    req_headers = dict(headers or {})
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    res = _request(base_url, method, path, headers=req_headers, body=body_bytes)
    parsed = None
    if res.body:
        try:
            parsed = json.loads(res.body.decode("utf-8"))
        except Exception:
            parsed = None
    return res, parsed


def request_multipart_file(
    base_url: str,
    path: str,
    bearer_token: str,
    file_path: str,
    field_name: str = "file",
    content_type: str = "text/plain",
) -> HttpResult:
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    boundary = f"----eb-smoke-{uuid.uuid4().hex}"
    filename = os.path.basename(file_path)

    parts = []
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(parts)

    return _request(
        base_url,
        "POST",
        path,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        body=body,
    )


def _must_token(obj: Optional[Dict[str, Any]]) -> str:
    if not obj:
        raise RuntimeError("Missing JSON response")
    token = obj.get("access_token")
    if not token or not isinstance(token, str):
        raise RuntimeError(f"Missing access_token in response: {obj}")
    return token


def _must_user_id(obj: Optional[Dict[str, Any]]) -> int:
    if not obj:
        raise RuntimeError("Missing JSON response")
    user_id = obj.get("user_id")
    if not isinstance(user_id, int):
        raise RuntimeError(f"Missing user_id in response: {obj}")
    return user_id


def main() -> int:
    base = os.getenv("BASE_URL", "http://localhost:8001").strip()

    admin_email = os.getenv("SMOKE_ADMIN_EMAIL", "admin@errandbridge.com")
    admin_pass = os.getenv("SMOKE_ADMIN_PASSWORD", "Password123!")

    pilot_email = os.getenv("SMOKE_PILOT_EMAIL", "delete-smoke-pilot@example.com")
    pilot_pass = os.getenv("SMOKE_PILOT_PASSWORD", "Password123!")

    # Ensure admin exists
    _, _ = request_json(
        base,
        "POST",
        "/auth/signup",
        payload={
            "email": admin_email,
            "password": admin_pass,
            "first_name": "Admin",
            "last_name": "User",
            "role": "client",
        },
    )

    res, admin_login = request_json(
        base,
        "POST",
        "/auth/login",
        payload={"email": admin_email, "password": admin_pass},
    )
    if res.status >= 400:
        raise RuntimeError(
            f"Admin login failed ({res.status}): {res.body.decode('utf-8', 'ignore')}"
        )
    admin_token = _must_token(admin_login)

    # Create pilot
    _, _ = request_json(
        base,
        "POST",
        "/auth/signup",
        payload={
            "email": pilot_email,
            "password": pilot_pass,
            "first_name": "Smoke",
            "last_name": "Pilot",
            "role": "pilot",
        },
    )

    res, pilot_login = request_json(
        base,
        "POST",
        "/auth/login",
        payload={"email": pilot_email, "password": pilot_pass},
    )
    if res.status >= 400:
        raise RuntimeError(
            f"Pilot login failed ({res.status}): {res.body.decode('utf-8', 'ignore')}"
        )

    pilot_token = _must_token(pilot_login)
    pilot_id = _must_user_id(pilot_login)

    upload_res = request_multipart_file(
        base,
        "/api/v1/pilots/documents?document_type=id_document",
        bearer_token=pilot_token,
        file_path="/etc/hosts",
    )
    if upload_res.status >= 400:
        raise RuntimeError(
            f"Pilot doc upload failed ({upload_res.status}): {upload_res.body.decode('utf-8', 'ignore')}"
        )

    delete_res = _request(
        base,
        "DELETE",
        f"/admin/users/{pilot_id}",
        headers={
            "Origin": "http://localhost:3000",
            "Authorization": f"Bearer {admin_token}",
        },
    )

    print(f"DELETE /admin/users/{pilot_id} -> {delete_res.status} {delete_res.reason}")
    print(
        "access-control-allow-origin:",
        delete_res.headers.get("access-control-allow-origin"),
    )
    print(delete_res.body.decode("utf-8", "ignore"))

    if delete_res.status >= 400:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
