import smtplib

import pytest

from app.services import emailer
import routes_auth


def _clear_email_env(monkeypatch):
    for key in (
        "ENV",
        "APP_ENV",
        "SMTP_HOST",
        "SMTP_SERVER",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "SMTP_USE_TLS",
        "SMTP_AUTH_MODE",
        "SMTP_FORCE_IPV4",
        "SMTP_FALLBACK_TO_STDOUT",
        "GRAPH_TENANT_ID",
        "GRAPH_CLIENT_ID",
        "GRAPH_CLIENT_SECRET",
        "GRAPH_SENDER",
    ):
        monkeypatch.delenv(key, raising=False)


def test_smtp_health_check_sets_tls_hostname(monkeypatch):
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "password")
    monkeypatch.setenv("SMTP_FROM", "user@example.com")
    monkeypatch.setenv("SMTP_FORCE_IPV4", "false")

    events = []

    class FakeSMTP:
        def __init__(self, timeout=None):
            self.timeout = timeout
            self._host = ""

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb):
            return False

        def connect(self, host, port):
            events.append(("connect", host, port))

        def ehlo_or_helo_if_needed(self):
            events.append(("ehlo_or_helo", self._host))

        def starttls(self):
            events.append(("starttls", self._host))
            if not self._host:
                raise ValueError("server_hostname cannot be empty")

        def ehlo(self):
            events.append(("ehlo", self._host))

        def login(self, username, password):
            events.append(("login", username, bool(password)))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    result = emailer.smtp_health_check()

    assert result.ok is True
    assert ("connect", "smtp.example.com", 587) in events
    assert ("starttls", "smtp.example.com") in events
    assert ("login", "user@example.com", True) in events


def test_smtp_enabled_accepts_legacy_smtp_server(monkeypatch):
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "password")
    monkeypatch.setenv("SMTP_FROM", "user@example.com")

    assert emailer._smtp_enabled() is True


def test_send_email_does_not_stdout_fallback_in_production(monkeypatch):
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("ENV", "prod")

    result = emailer.send_email(
        to_email="client@example.com",
        subject="Test",
        body_text="Hello",
    )

    assert result.delivered is False
    assert result.provider == "none"
    assert result.detail == "missing_email_provider_config"


@pytest.mark.asyncio
async def test_email_health_keeps_configured_smtp_mode_when_health_fails(monkeypatch):
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "password")
    monkeypatch.setenv("SMTP_FROM", "user@example.com")

    monkeypatch.setattr(
        emailer,
        "graph_health_check",
        lambda: emailer.HealthResult(
            ok=False, provider="graph", detail="missing_config"
        ),
    )
    monkeypatch.setattr(
        emailer,
        "smtp_health_check",
        lambda: emailer.HealthResult(ok=False, provider="smtp", detail="smtp_failed"),
    )

    result = await routes_auth.email_health()

    assert result.smtp_ok is False
    assert result.smtp_detail == "smtp_failed"
    assert result.delivery_mode == "smtp"
