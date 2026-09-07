from types import SimpleNamespace

import pytest

from app.routes import errand_messages


@pytest.mark.asyncio
async def test_send_errand_message_is_blocked_after_completion(monkeypatch):
    user = SimpleNamespace(id=10, email="customer@example.com")
    errand = SimpleNamespace(
        id=123,
        user_id=10,
        pilot_id=77,
        status="completed",
        completed_at=None,
    )

    async def fake_current_user(_authorization, _db):
        return user

    async def fake_require_participant(_db, *, errand_id, user):
        assert int(errand_id) == 123
        assert int(user.id) == 10
        return errand

    monkeypatch.setattr(errand_messages, "_get_current_user", fake_current_user)
    monkeypatch.setattr(
        errand_messages, "_require_participant", fake_require_participant
    )

    with pytest.raises(errand_messages.HTTPException) as exc_info:
        await errand_messages.send_errand_message(
            errand_id=123,
            payload=errand_messages.ErrandMessageIn(message="hello"),
            authorization="Bearer token",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 409
    assert "locked" in str(exc_info.value.detail).lower()
