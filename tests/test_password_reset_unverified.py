import pytest

import routes_auth


class DummyUser:
    def __init__(self, email: str, *, verified: bool):
        self.email = email
        self.is_email_verified = verified
        self.password_hash = "old"
        self.email_otp_hash = "hash"
        self.email_otp_expires_at = 123
        self.email_otp_last_sent_at = 0
        self.email_otp_attempts = 0


class FakeDB:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_password_reset_start_sends_otp_for_unverified_user(monkeypatch):
    user = DummyUser("user@example.com", verified=False)

    async def fake_get_user_by_email(db, email: str):
        assert email == "user@example.com"
        return user

    sent = {"called": False}

    async def fake_send_otp_for_user(db, user_obj, **kwargs):
        sent["called"] = True
        assert user_obj is user
        assert kwargs.get("purpose") == "password reset"

    monkeypatch.setattr(routes_auth, "_get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr(routes_auth, "_send_otp_for_user", fake_send_otp_for_user)

    db = FakeDB()
    payload = routes_auth.PasswordResetStartRequest(email="user@example.com")
    resp = await routes_auth.password_reset_start(payload, db=db)

    assert resp.ok is True
    assert sent["called"] is True


@pytest.mark.asyncio
async def test_password_reset_confirm_marks_user_verified_and_updates_password(
    monkeypatch,
):
    user = DummyUser("user@example.com", verified=False)

    async def fake_get_user_by_email(db, email: str):
        return user

    def fake_check_otp(user_obj, code: str):
        assert user_obj is user
        assert code == "123456"
        return None

    def fake_hash_password(value: str) -> str:
        assert value == "newpassword123"
        return "hashed:newpassword123"

    monkeypatch.setattr(routes_auth, "_get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr(routes_auth, "_check_otp", fake_check_otp)
    monkeypatch.setattr(routes_auth, "hash_password", fake_hash_password)

    db = FakeDB()
    payload = routes_auth.PasswordResetConfirmRequest(
        email="user@example.com",
        code="123456",
        new_password="newpassword123",
    )
    resp = await routes_auth.password_reset_confirm(payload, db=db)

    assert resp.ok is True
    assert db.committed is True
    assert user.password_hash == "hashed:newpassword123"
    assert user.is_email_verified is True
    # OTP is cleared on successful reset
    assert user.email_otp_hash is None
    assert user.email_otp_expires_at is None
    assert user.email_otp_last_sent_at is None
    assert user.email_otp_attempts == 0
