import pytest
from fastapi import HTTPException

import routes_auth
import schema as schema_module


class DummyUser:
    def __init__(
        self,
        email: str,
        *,
        phone: str | None = None,
        is_pilot: bool = False,
        verified: bool = True,
    ):
        self.id = 202
        self.email = email
        self.password_hash = "hashed-password"
        self.first_name = "Phone"
        self.last_name = "User"
        self.phone = phone
        self.is_email_verified = verified
        self.is_pilot = is_pilot
        self.email_otp_hash = None
        self.email_otp_expires_at = None

class FakeDB:
    def __init__(self):
        self.added = []
        self.committed = False
        self.refreshed = []

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 303
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        self.refreshed.append(obj)


@pytest.mark.asyncio
async def test_rest_signup_rejects_invalid_email_before_db_lookup(monkeypatch):
    async def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("DB lookup should not run for invalid email input")

    monkeypatch.setattr(routes_auth, "_get_user_by_phone", unexpected_lookup)
    monkeypatch.setattr(routes_auth, "_get_user_by_email", unexpected_lookup)

    with pytest.raises(HTTPException) as exc_info:
        await routes_auth.signup(
            routes_auth.SignupRequest(
                email="invalid-email",
                password="password123",
                first_name="Ada",
                last_name="Bridge",
                role="client",
            ),
            db=FakeDB(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Enter a valid email address or phone number"


def test_graphql_signup_email_normalizer_rejects_invalid_email():
    with pytest.raises(ValueError, match="Enter a valid email address or phone number"):
        schema_module._normalize_signup_email("invalid-email")


@pytest.mark.asyncio
async def test_rest_login_accepts_phone_identifier(monkeypatch):
    alias_email = routes_auth.build_phone_alias_email("+15555551234", role="client")
    user = DummyUser(alias_email, phone="+15555551234")

    async def fake_get_user_by_identifier(db, identifier: str):
        assert identifier == "+1 (555) 555-1234"
        return user

    monkeypatch.setattr(
        routes_auth, "_get_user_by_identifier", fake_get_user_by_identifier
    )
    monkeypatch.setattr(routes_auth, "_check_otp", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        routes_auth, "create_access_token", lambda user_id: f"token-{user_id}"
    )
    monkeypatch.setattr(routes_auth, "admin_emails", lambda: [])

    response = await routes_auth.login(
        routes_auth.LoginRequest(
            email="+1 (555) 555-1234",
            password="password123",
            role="client",
        ),
        db=FakeDB(),
    )

    assert response.access_token == "token-202"
    assert response.user_id == 202
    assert response.phone == "+15555551234"


@pytest.mark.asyncio
async def test_rest_signup_allows_phone_identifier_and_sends_sms_otp(monkeypatch):
    alias_email = routes_auth.build_phone_alias_email("+15555551234", role="client")

    async def fake_get_user_by_phone(db, phone: str):
        assert phone == "+15555551234"
        return None

    async def fake_get_user_by_email(db, email: str):
        assert email == alias_email
        return None

    sent = {"called": False, "channel": None}

    async def fake_send_otp_for_user(db, user, **kwargs):
        sent["called"] = True
        sent["channel"] = kwargs.get("channel")
        assert user.phone == "+15555551234"
        assert kwargs.get("purpose") == "signup confirmation"

    monkeypatch.setattr(routes_auth, "_get_user_by_phone", fake_get_user_by_phone)
    monkeypatch.setattr(routes_auth, "_get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr(routes_auth, "_send_otp_for_user", fake_send_otp_for_user)
    monkeypatch.setattr(routes_auth, "hash_password", lambda value: f"hashed:{value}")
    monkeypatch.setattr(
        routes_auth, "create_access_token", lambda user_id: f"token-{user_id}"
    )
    monkeypatch.setattr(routes_auth, "admin_emails", lambda: [])
    monkeypatch.setenv("DISABLE_EMAIL_CONFIRMATION", "false")

    db = FakeDB()
    response = await routes_auth.signup(
        routes_auth.SignupRequest(
            email="+1 555 555 1234",
            phone="+1 555 555 1234",
            password="password123",
            first_name="Ada",
            last_name="Bridge",
            role="client",
        ),
        db=db,
    )

    assert db.committed is True
    assert len(db.added) == 1
    created_user = db.added[0]
    assert created_user.email == alias_email
    assert created_user.phone == "+15555551234"
    assert created_user.password_hash == "hashed:password123"
    assert sent["called"] is True
    assert sent["channel"] == "sms"
    assert response.access_token == "token-303"
    assert response.phone == "+15555551234"
    assert response.email == alias_email
