from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routes import tracking


class FakeDB:
    def __init__(self, errand):
        self.errand = errand
        self.commit_calls = 0

    async def scalar(self, _query):
        return self.errand

    async def commit(self):
        self.commit_calls += 1


@pytest.mark.asyncio
async def test_location_update_cannot_start_assigned_unaccepted_errand(monkeypatch):
    errand = SimpleNamespace(
        id="errand-1",
        pilot_id="pilot-1",
        status="assigned",
        started_at=None,
        pickup_time_slot_start=None,
        pickup_time_slot_end=None,
    )
    db = FakeDB(errand)

    async def require_assigned_pilot(*_args, **_kwargs):
        return SimpleNamespace(id="pilot-1")

    monkeypatch.setattr(tracking, "_require_assigned_pilot", require_assigned_pilot)
    monkeypatch.setattr(tracking, "observe_tracking_update", lambda **_kwargs: None)

    with pytest.raises(HTTPException) as error:
        await tracking.update_location(
            tracking.LocationUpdate(
                errand_id="errand-1",
                latitude=6.5244,
                longitude=3.3792,
            ),
            authorization="Bearer token",
            request=None,
            db=db,
        )

    assert error.value.status_code == 409
    assert "assigned" in str(error.value.detail)
    assert errand.status == "assigned"
    assert errand.started_at is None
    assert db.commit_calls == 0