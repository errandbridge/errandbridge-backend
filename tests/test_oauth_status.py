import pytest

import routes_auth


@pytest.mark.asyncio
async def test_oauth_status_marks_google_redirect_disabled_when_secret_missing(monkeypatch):
	monkeypatch.delenv("OAUTH_ALLOWED_ORIGINS", raising=False)
	monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
	monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
	monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
	monkeypatch.setenv(
		"GOOGLE_OAUTH_REDIRECT_URI",
		"https://api.errandbridge.com/auth/oauth/google/callback",
	)

	status = await routes_auth.oauth_status(
		origin="https://www.errandbridge.com",
		role="client",
	)

	assert status.google.redirect.enabled is False
	assert status.google.redirect.configured is False
	assert status.google.redirect.reason == "Google OAuth is not configured"


@pytest.mark.asyncio
async def test_oauth_status_marks_google_token_enabled_when_client_id_present(monkeypatch):
	monkeypatch.delenv("OAUTH_ALLOWED_ORIGINS", raising=False)
	monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
	monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
	monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_IDS", raising=False)

	status = await routes_auth.oauth_status(
		origin="https://www.errandbridge.com",
		role="client",
	)

	assert status.google.token.enabled is True
	assert status.google.token.configured is True
	assert status.google.token.reason is None


@pytest.mark.asyncio
async def test_oauth_status_disables_redirect_flows_for_disallowed_origin(monkeypatch):
	monkeypatch.setenv("OAUTH_ALLOWED_ORIGINS", "https://www.errandbridge.com")
	monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
	monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
	monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
	monkeypatch.setenv(
		"GOOGLE_OAUTH_REDIRECT_URI",
		"https://api.errandbridge.com/auth/oauth/google/callback",
	)
	monkeypatch.setenv("APPLE_CLIENT_ID", "com.errandbridge.web")
	monkeypatch.setenv("APPLE_REDIRECT_URI", "https://api.errandbridge.com/auth/oauth/apple/callback")
	monkeypatch.setenv("APPLE_TEAM_ID", "TEAM123")
	monkeypatch.setenv("APPLE_KEY_ID", "KEY123")
	monkeypatch.setattr(routes_auth, "_apple_private_key", lambda: "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")

	status = await routes_auth.oauth_status(
		origin="https://pilot.errandbridge.com",
		role="pilot",
	)

	assert status.google.redirect.enabled is False
	assert status.google.redirect.origin_allowed is False
	assert status.google.redirect.reason == "Origin is not allowed"
	assert status.apple.redirect.enabled is False
	assert status.apple.redirect.origin_allowed is False
	assert status.apple.redirect.reason == "Origin is not allowed"


@pytest.mark.asyncio
async def test_oauth_status_marks_apple_redirect_enabled_when_configured(monkeypatch):
	monkeypatch.delenv("OAUTH_ALLOWED_ORIGINS", raising=False)
	monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
	monkeypatch.setenv("APPLE_CLIENT_ID", "com.errandbridge.web")
	monkeypatch.setenv("APPLE_REDIRECT_URI", "https://api.errandbridge.com/auth/oauth/apple/callback")
	monkeypatch.setenv("APPLE_TEAM_ID", "TEAM123")
	monkeypatch.setenv("APPLE_KEY_ID", "KEY123")
	monkeypatch.setattr(routes_auth, "_apple_private_key", lambda: "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")

	status = await routes_auth.oauth_status(
		origin="https://www.errandbridge.com",
		role="client",
	)

	assert status.apple.redirect.enabled is True
	assert status.apple.redirect.configured is True
	assert status.apple.redirect.reason is None
