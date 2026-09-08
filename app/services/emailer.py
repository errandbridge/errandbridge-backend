from __future__ import annotations

import os
import smtplib
import socket
from urllib.parse import quote
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True)
class SendResult:
    delivered: bool
    provider: str
    detail: str | None = None


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    provider: str
    detail: str | None = None


def _smtp_host() -> str:
    # SMTP_SERVER is a legacy variable still used by older scripts/task defs.
    return (os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER") or "").strip()


def _stdout_fallback_allowed() -> bool:
    env = (os.getenv("ENV") or os.getenv("APP_ENV") or "").strip().lower()
    if env in {"prod", "production", "staging"}:
        return os.getenv("SMTP_FALLBACK_TO_STDOUT", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
    return True


def _smtp_enabled() -> bool:
    # Treat SMTP as enabled only when the required essentials are set.
    # This prevents confusing "dev mode" fallbacks when values are missing.
    host = _smtp_host()
    from_email = (os.getenv("SMTP_FROM") or "").strip()
    username = (os.getenv("SMTP_USERNAME") or "").strip()
    password = os.getenv("SMTP_PASSWORD")
    auth_mode = (os.getenv("SMTP_AUTH_MODE") or "login").strip().lower()
    # If SMTP_FROM isn't set, we can still send when username is used as from.
    # For relay connections (auth_mode=none), allow host+from without creds.
    if auth_mode == "none":
        return bool(host and (from_email or username))
    return bool(host and (from_email or username) and username and password)


def _graph_enabled() -> bool:
    tenant = (os.getenv("GRAPH_TENANT_ID") or "").strip()
    client_id = (os.getenv("GRAPH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GRAPH_CLIENT_SECRET") or "").strip()
    sender = (os.getenv("GRAPH_SENDER") or "").strip()
    return bool(tenant and client_id and client_secret and sender)


def _format_from_email(from_email: str) -> str:
    from_name = (
        os.getenv("SMTP_FROM_NAME") or os.getenv("EMAIL_FROM_NAME") or ""
    ).strip()
    if not from_name:
        from_name = (os.getenv("DEFAULT_FROM_NAME") or "ErrandBridge").strip()
    if from_name:
        return f"{from_name} <{from_email}>"
    return from_email


def _reply_to_address() -> str:
    return (os.getenv("SMTP_REPLY_TO") or os.getenv("EMAIL_REPLY_TO") or "").strip()


def graph_health_check() -> HealthResult:
    if not _graph_enabled():
        return HealthResult(ok=False, provider="graph", detail="missing_config")

    import httpx

    tenant = (os.getenv("GRAPH_TENANT_ID") or "").strip()
    client_id = (os.getenv("GRAPH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GRAPH_CLIENT_SECRET") or "").strip()
    sender = (os.getenv("GRAPH_SENDER") or "").strip()
    timeout = int(os.getenv("GRAPH_TIMEOUT_SECONDS", "10"))

    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            token_res = client.post(token_url, data=token_payload)
            token_res.raise_for_status()
            access_token = token_res.json().get("access_token")
            if not access_token:
                return HealthResult(
                    ok=False, provider="graph", detail="missing_access_token"
                )

            sender_encoded = quote(sender)
            probe_url = f"https://graph.microsoft.com/v1.0/users/{sender_encoded}?$select=id,mail,userPrincipalName"
            probe_res = client.get(
                probe_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            probe_res.raise_for_status()
        return HealthResult(ok=True, provider="graph")
    except Exception as e:
        safe_detail = f"graph_health_failed: sender_set={bool(sender)} error={e}"
        print(f"[GRAPH ERROR] {safe_detail}")
        return HealthResult(ok=False, provider="graph", detail=safe_detail)


def smtp_health_check() -> HealthResult:
    if not _smtp_enabled():
        return HealthResult(ok=False, provider="smtp", detail="missing_config")

    host = _smtp_host()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = (os.getenv("SMTP_USERNAME") or "").strip() or None
    password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in ("1", "true", "yes")
    auth_mode = (os.getenv("SMTP_AUTH_MODE") or "login").strip().lower()
    timeout = int(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))

    try:
        force_ipv4 = os.getenv("SMTP_FORCE_IPV4", "true").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        connect_host = host
        if force_ipv4 and host:
            try:
                addr_info = socket.getaddrinfo(
                    host, port, socket.AF_INET, socket.SOCK_STREAM
                )
                if addr_info:
                    connect_host = addr_info[0][4][0]
            except Exception as e:
                print(f"[SMTP WARN] IPv4 resolution failed for {host}: {e}")

        with smtplib.SMTP(timeout=timeout) as server:
            server.connect(connect_host, port)
            # smtplib.starttls() uses server._host for SNI/hostname validation.
            # When we connect manually (or connect to a resolved IPv4 address),
            # keep the logical SMTP hostname here so TLS has a valid server name.
            server._host = host
            server.ehlo_or_helo_if_needed()
            if use_tls:
                server.starttls()
                server.ehlo()
            if auth_mode != "none" and username and password:
                server.login(username, password)
        return HealthResult(ok=True, provider="smtp")
    except Exception as e:
        return HealthResult(
            ok=False, provider="smtp", detail=f"smtp_health_failed: {e}"
        )


def send_email(*, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> SendResult:
    """Send an email.

    - If SMTP env vars are configured, sends via SMTP.
    - Otherwise, logs to stdout (dev-friendly for Docker Compose).

        Env vars:
            SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM
            SMTP_USE_TLS=true|false
            SMTP_AUTH_MODE=login|none
    """

    if _graph_enabled():
        result = _send_via_graph(
            to_email=to_email, subject=subject, body_text=body_text, body_html=body_html
        )
        if result.delivered:
            return result

    if _smtp_enabled():
        result = _send_via_smtp(to_email=to_email, subject=subject, body_text=body_text, body_html=body_html)
        if not result.delivered:
            if _stdout_fallback_allowed():
                print("\n--- EMAIL (smtp failed; fallback stdout) ---")
                print(f"TO: {to_email}")
                print(f"SUBJECT: {subject}")
                print(body_text)
                print("--- END EMAIL ---\n")
                return SendResult(
                    delivered=True, provider="stdout", detail="smtp_failed_logged"
                )
        return result

    if not _smtp_enabled():
        if not _stdout_fallback_allowed():
            return SendResult(
                delivered=False, provider="none", detail="missing_email_provider_config"
            )
        # Dev mode: print so you can confirm OTP from container logs.
        print("\n--- EMAIL (dev mode) ---")
        print(f"TO: {to_email}")
        print(f"SUBJECT: {subject}")
        print(body_text)
        print("--- END EMAIL ---\n")
        return SendResult(delivered=True, provider="stdout", detail="logged_to_stdout")


def _send_via_graph(*, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> SendResult:
    import httpx

    tenant = (os.getenv("GRAPH_TENANT_ID") or "").strip()
    client_id = (os.getenv("GRAPH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GRAPH_CLIENT_SECRET") or "").strip()
    sender = (os.getenv("GRAPH_SENDER") or "").strip()
    from_name = (
        os.getenv("SMTP_FROM_NAME") or os.getenv("EMAIL_FROM_NAME") or ""
    ).strip()
    if not from_name:
        from_name = (os.getenv("DEFAULT_FROM_NAME") or "ErrandBridge").strip()
    reply_to = _reply_to_address()
    timeout = int(os.getenv("GRAPH_TIMEOUT_SECONDS", "15"))

    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            token_res = client.post(token_url, data=token_payload)
            token_res.raise_for_status()
            access_token = token_res.json().get("access_token")
            if not access_token:
                return SendResult(
                    delivered=False, provider="graph", detail="missing_access_token"
                )

            mail_payload = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "HTML" if body_html else "Text", "content": body_html or body_text},
                    "toRecipients": [{"emailAddress": {"address": to_email}}],
                },
                "saveToSentItems": "false",
            }
            if reply_to:
                mail_payload["message"]["replyTo"] = [
                    {
                        "emailAddress": {
                            "address": reply_to,
                            "name": from_name or reply_to,
                        }
                    }
                ]
            if from_name:
                mail_payload["message"]["from"] = {
                    "emailAddress": {"address": sender, "name": from_name}
                }
                mail_payload["message"]["sender"] = {
                    "emailAddress": {"address": sender, "name": from_name}
                }
            sender_encoded = quote(sender)
            send_url = (
                f"https://graph.microsoft.com/v1.0/users/{sender_encoded}/sendMail"
            )
            send_res = client.post(
                send_url,
                json=mail_payload,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            send_res.raise_for_status()
        return SendResult(delivered=True, provider="graph")
    except Exception as e:
        safe_detail = f"graph_send_failed: sender_set={bool(sender)} error={e}"
        print(f"[GRAPH ERROR] {safe_detail}")
        return SendResult(delivered=False, provider="graph", detail=safe_detail)


def _send_via_smtp(*, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> SendResult:
    host = _smtp_host()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = (os.getenv("SMTP_USERNAME") or "").strip() or None
    password = os.getenv("SMTP_PASSWORD")
    from_email = (
        (os.getenv("SMTP_FROM") or "").strip()
        or username
        or "no-reply@errandbridge.com"
    )
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in ("1", "true", "yes")
    timeout = int(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
    auth_mode = (os.getenv("SMTP_AUTH_MODE") or "login").strip().lower()
    fallback_from = None
    if (
        username
        and from_email
        and from_email.strip().lower() != username.strip().lower()
    ):
        fallback_from = username

    def _attempt_send(selected_from: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = _format_from_email(selected_from)
        msg["To"] = to_email
        reply_to = _reply_to_address()
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")

        force_ipv4 = os.getenv("SMTP_FORCE_IPV4", "true").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        connect_host = host

        if force_ipv4 and host:
            try:
                addr_info = socket.getaddrinfo(
                    host, port, socket.AF_INET, socket.SOCK_STREAM
                )
                if addr_info:
                    connect_host = addr_info[0][4][0]
            except Exception as e:
                print(f"[SMTP WARN] IPv4 resolution failed for {host}: {e}")

        with smtplib.SMTP(timeout=timeout) as server:
            server.connect(connect_host, port)
            server._host = host
            if use_tls:
                server.starttls()
            if auth_mode != "none" and username and password:
                server.login(username, password)
            server.send_message(msg)

    try:
        _attempt_send(from_email)
        return SendResult(delivered=True, provider="smtp")
    except Exception as e:
        # One quick retry for transient network issues to keep OTP latency under 30s.
        transient_retry = isinstance(
            e, (smtplib.SMTPServerDisconnected, TimeoutError, socket.timeout)
        )
        if transient_retry:
            try:
                _attempt_send(from_email)
                return SendResult(
                    delivered=True, provider="smtp", detail="retry_success"
                )
            except Exception as retry_error:
                e = retry_error
        if fallback_from:
            print(
                "[SMTP WARN] Primary From address rejected; retrying with authenticated username as From."
            )
            try:
                _attempt_send(fallback_from)
                return SendResult(
                    delivered=True, provider="smtp", detail="fallback_from_username"
                )
            except Exception as fallback_error:
                safe_detail = (
                    f"smtp_send_failed: host={host!r} port={port} use_tls={use_tls} "
                    f"username_set={bool(username)} from_set={bool(os.getenv('SMTP_FROM'))} "
                    f"error={e} fallback_error={fallback_error}"
                )
                print(f"[SMTP ERROR] {safe_detail}")
                return SendResult(delivered=False, provider="smtp", detail=safe_detail)

        safe_detail = (
            f"smtp_send_failed: host={host!r} port={port} use_tls={use_tls} "
            f"username_set={bool(username)} from_set={bool(os.getenv('SMTP_FROM'))} error={e}"
        )
        print(f"[SMTP ERROR] {safe_detail}")
        return SendResult(delivered=False, provider="smtp", detail=safe_detail)
