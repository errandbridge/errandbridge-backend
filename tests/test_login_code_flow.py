import pytest
from fastapi import HTTPException

import routes_auth


class DummyUrl:
    def __init__(self, path: str):
        self.path = path


class DummyRequest:
    def __init__(self, path: str):
        self.url = DummyUrl(path)


class DummyUser:
    def __init__(self, *, is_pilot: bool = False, verified: bool = True):
        self.id = 42
        self.email = "client@example.com"
        self.first_name = "Client"
        self.last_name = "Tester"
        self.phone = "+15551234567"
        self.is_email_verified = verified
        self.is_pilot = is_pilot
        self.email_otp_hash = "hash"
        self.email_otp_expires_at = 123
        self.email_otp_last_sent_at = 0
        self.email_otp_attempts = 0


class FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_tso_request_code_accepts_token_alias_and_sends_otp(monkeypatch):
    user = DummyUser()

    async def fake_get_user_from_login_link_token(db, link_token):
        assert link_token == "token-value-12345"
        return user

    sent = {}

    async def fake_send_otp_for_user(db, user_obj, **kwargs):
        sent["user"] = user_obj
        sent["kwargs"] = kwargs

    monkeypatch.setattr(routes_auth, "_get_user_from_login_link_token", fake_get_user_from_login_link_token)
    monkeypatch.setattr(routes_auth, "_send_otp_for_user", fake_send_otp_for_user)
    monkeypatch.setattr(routes_auth, "_api_timestamp", lambda: "2026-07-20T19:42:59.464Z")

    payload = routes_auth.LoginCodeRequest.model_validate({"token": "token-value-12345"})
    response = await routes_auth.login_request_code(
        payload,
        request=DummyRequest("/tso/request-code"),
        db=FakeDB(),
    )

    assert response.status == "SUCCESS"
    assert response.code == 0
    assert response.path == "/tso/request-code"
    assert response.data.model_dump() == {
        "deliveryChannel": "email",
        "maskedDestination": "cl***@example.com",
        "expiresInSeconds": 600,
    }
    assert sent["user"] is user
    assert sent["kwargs"]["purpose"] == "login"
    assert sent["kwargs"]["smoke_env"] == "SMOKE_LOGIN_OTP"


@pytest.mark.asyncio
async def test_tso_verify_returns_time_limited_session_token(monkeypatch):
    user = DummyUser()
    db = FakeDB()

    async def fake_get_user_from_login_link_token(db_obj, link_token):
        assert link_token == "token-value-12345"
        return user

    def fake_check_otp(user_obj, code):
        assert user_obj is user
        assert code == "483921"

    def fake_create_access_token(**kwargs):
        assert kwargs == {"user_id": 42, "expires_minutes": 60}
        return "session-token-abc"

    def fake_create_refresh_token(**kwargs):
        assert kwargs == {"user_id": 42}
        return "refresh-token-abc"

    monkeypatch.setattr(routes_auth, "_get_user_from_login_link_token", fake_get_user_from_login_link_token)
    monkeypatch.setattr(routes_auth, "_check_otp", fake_check_otp)
    monkeypatch.setattr(routes_auth, "create_access_token", fake_create_access_token)
    monkeypatch.setattr(routes_auth, "create_refresh_token", fake_create_refresh_token)
    monkeypatch.setattr(routes_auth, "admin_emails", lambda: [])
    monkeypatch.setattr(routes_auth, "_api_timestamp", lambda: "2026-07-20T19:41:41.640Z")

    payload = routes_auth.LoginCodeVerifyRequest.model_validate({
        "token": "token-value-12345",
        "code": "483921",
    })
    response = await routes_auth.login_verify_code(
        payload,
        request=DummyRequest("/tso/verify"),
        db=db,
    )

    assert response.status == "SUCCESS"
    assert response.code == 0
    assert response.path == "/tso/verify"
    assert response.data.model_dump() == {
        "sessionToken": "session-token-abc",
        "refreshToken": "refresh-token-abc",
        "userUuid": "00000000-0000-0000-0000-000000000042",
        "expiresInSeconds": 3600,
        "tokenType": "bearer",
    }
    assert db.commits == 1
    assert user.email_otp_hash is None
    assert user.email_otp_expires_at is None
    assert user.email_otp_last_sent_at is None
    assert user.email_otp_attempts == 0


@pytest.mark.asyncio
async def test_tso_verify_persists_invalid_code_attempt(monkeypatch):
    user = DummyUser()
    db = FakeDB()

    async def fake_get_user_from_login_link_token(db_obj, link_token):
        return user

    def fake_check_otp(user_obj, code):
        raise HTTPException(status_code=400, detail="Invalid code")

    monkeypatch.setattr(routes_auth, "_get_user_from_login_link_token", fake_get_user_from_login_link_token)
    monkeypatch.setattr(routes_auth, "_check_otp", fake_check_otp)

    payload = routes_auth.LoginCodeVerifyRequest.model_validate({
        "token": "token-value-12345",
        "code": "000000",
    })

    with pytest.raises(HTTPException) as exc_info:
        await routes_auth.login_verify_code(
            payload,
            request=DummyRequest("/tso/verify"),
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid code"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_tso_request_code_rejects_unverified_user(monkeypatch):
    user = DummyUser(verified=False)

    async def fake_get_user_from_login_link_token(db, link_token):
        return user

    monkeypatch.setattr(routes_auth, "_get_user_from_login_link_token", fake_get_user_from_login_link_token)

    payload = routes_auth.LoginCodeRequest.model_validate({"token": "token-value-12345"})

    with pytest.raises(HTTPException) as exc_info:
        await routes_auth.login_request_code(
            payload,
            request=DummyRequest("/tso/request-code"),
            db=FakeDB(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Email not verified"
