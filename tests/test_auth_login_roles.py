import pytest
from fastapi import HTTPException

import routes_auth


class DummyUser:
    def __init__(self, email: str, *, is_pilot: bool, verified: bool = True):
        self.id = 101
        self.email = email
        self.password_hash = "hashed-password"
        self.first_name = "Test"
        self.last_name = "User"
        self.phone = None
        self.is_email_verified = verified
        self.is_pilot = is_pilot
        self.address_verification_status = "pending"
        self.id_verification_status = "pending"


@pytest.mark.asyncio
async def test_rest_login_rejects_pilot_account_in_client_mode(monkeypatch):
    pilot_user = DummyUser("pilot@example.com", is_pilot=True)

    async def fake_get_user_by_email(db, email: str):
        assert email == "pilot@example.com"
        return pilot_user

    monkeypatch.setattr(routes_auth, "_get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr(routes_auth, "verify_password", lambda *_args, **_kwargs: True)

    with pytest.raises(HTTPException) as exc_info:
        await routes_auth.login(
            routes_auth.LoginRequest(
                email="pilot@example.com",
                password="password123",
                role="client",
            ),
            db=object(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Pilot accounts must sign in via Pilot mode"


@pytest.mark.asyncio
async def test_rest_login_rejects_client_account_in_pilot_mode(monkeypatch):
    client_user = DummyUser("client@example.com", is_pilot=False)

    async def fake_get_user_by_email(db, email: str):
        assert email == "client@example.com"
        return client_user

    monkeypatch.setattr(routes_auth, "_get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr(routes_auth, "verify_password", lambda *_args, **_kwargs: True)

    with pytest.raises(HTTPException) as exc_info:
        await routes_auth.login(
            routes_auth.LoginRequest(
                email="client@example.com",
                password="password123",
                role="pilot",
            ),
            db=object(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "This account is not registered as a pilot"


@pytest.mark.asyncio
async def test_rest_login_allows_matching_role(monkeypatch):
    pilot_user = DummyUser("pilot@example.com", is_pilot=True)

    async def fake_get_user_by_email(db, email: str):
        return pilot_user

    monkeypatch.setattr(routes_auth, "_get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr(routes_auth, "verify_password", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(routes_auth, "create_access_token", lambda user_id: f"token-{user_id}")
    monkeypatch.setattr(routes_auth, "create_refresh_token", lambda user_id: f"refresh-{user_id}")
    monkeypatch.setattr(routes_auth, "admin_emails", lambda: [])

    response = await routes_auth.login(
        routes_auth.LoginRequest(
            email="pilot@example.com",
            password="password123",
            role="pilot",
        ),
        db=object(),
    )

    assert response.access_token == "token-101"
    assert response.refresh_token == "refresh-101"
    assert response.user_id == 101
    assert response.email == "pilot@example.com"


@pytest.mark.asyncio
async def test_refresh_session_exchanges_refresh_token(monkeypatch):
    user = DummyUser("client@example.com", is_pilot=False)

    class FakeDB:
        async def get(self, model, user_id, options=None):
            assert user_id == 101
            return user

    monkeypatch.setattr(routes_auth, "decode_refresh_token", lambda token: 101 if token == "refresh-token" else None)
    monkeypatch.setattr(routes_auth, "create_access_token", lambda user_id: f"token-{user_id}")
    monkeypatch.setattr(routes_auth, "create_refresh_token", lambda user_id: f"refresh-{user_id}")
    monkeypatch.setattr(routes_auth, "admin_emails", lambda: [])

    response = await routes_auth.refresh_session(
        routes_auth.RefreshTokenRequest(refresh_token="refresh-token"),
        db=FakeDB(),
    )

    assert response.access_token == "token-101"
    assert response.refresh_token == "refresh-101"
    assert response.user_id == 101


@pytest.mark.asyncio
async def test_google_auth_rejects_pilot_signup_with_existing_client_email(monkeypatch):
    client_user = DummyUser("client@example.com", is_pilot=False)

    monkeypatch.setattr(
        routes_auth,
        "_verify_google_credential",
        lambda *_args, **_kwargs: {
            "email": "client@example.com",
            "given_name": "Client",
            "family_name": "Tester",
        },
    )

    async def fake_get_user_by_email(db, email: str):
        assert email == "client@example.com"
        return client_user

    monkeypatch.setattr(routes_auth, "_get_user_by_email", fake_get_user_by_email)

    with pytest.raises(HTTPException) as exc_info:
        await routes_auth.google_auth(
            routes_auth.GoogleAuthRequest(
                credential="x" * 20,
                role="pilot",
                allow_pilot_signup=True,
            ),
            db=object(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Email already registered for a different account type"
