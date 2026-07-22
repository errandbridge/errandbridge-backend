from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.routes import tracking
from models import PilotLocation


class FakeDB:
    def __init__(self, scalar_values=None):
        self.scalar_values = list(scalar_values or [])
        self.added = []
        self.commit_calls = 0

    async def scalar(self, _query):
        if not self.scalar_values:
            return None
        return self.scalar_values.pop(0)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, value):
        if isinstance(value, PilotLocation) and getattr(value, "id", None) is None:
            value.id = 101


@pytest.mark.asyncio
async def test_update_location_handles_mixed_timezone_issue_reported_at(monkeypatch):
    aware_last_issue = datetime.now(timezone.utc) - timedelta(minutes=3)
    errand = SimpleNamespace(
        id=55,
        pilot_id=77,
        status="in_progress",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        pickup_time_slot_start=None,
        pickup_time_slot_end=None,
        tracking_paused=False,
        issue_reported_at=aware_last_issue,
        issue_status=None,
        user_id=12,
    )
    stale_loc = SimpleNamespace(
        latitude=6.5244,
        longitude=3.3792,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=8),
    )
    db = FakeDB([errand, stale_loc])

    async def fake_require_assigned_pilot(_authorization, _errand, _db):
        return SimpleNamespace(id=77)

    broadcast_calls = []

    async def fake_broadcast(errand_id, message):
        broadcast_calls.append((errand_id, message))

    monkeypatch.setattr(tracking, "_require_assigned_pilot", fake_require_assigned_pilot)
    monkeypatch.setattr(tracking.manager, "broadcast", fake_broadcast)

    payload = await tracking.update_location(
        location=tracking.LocationUpdate(
            errand_id=55,
            latitude=6.5244,
            longitude=3.3792,
            accuracy=5.0,
        ),
        authorization="Bearer token",
        db=db,
    )

    assert payload.errand_id == 55
    assert payload.pilot_id == 77
    assert payload.source == "mobile_app"
    assert errand.issue_reported_at == aware_last_issue
    assert errand.issue_status is None
    assert broadcast_calls, "Expected live tracking broadcast to continue succeeding"


@pytest.mark.asyncio
async def test_update_location_persists_recorded_at_and_source(monkeypatch):
    recorded_at = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    errand = SimpleNamespace(
        id=88,
        pilot_id=77,
        status="in_progress",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=3),
        pickup_time_slot_start=None,
        pickup_time_slot_end=None,
        tracking_paused=False,
        issue_reported_at=None,
        issue_status=None,
        user_id=12,
    )
    db = FakeDB([errand, None])

    async def fake_require_assigned_pilot(_authorization, _errand, _db):
        return SimpleNamespace(id=77)

    monkeypatch.setattr(tracking, "_require_assigned_pilot", fake_require_assigned_pilot)
    async def fake_broadcast(*_args, **_kwargs):
        return None

    monkeypatch.setattr(tracking.manager, "broadcast", fake_broadcast)

    payload = await tracking.update_location(
        location=tracking.LocationUpdate(
            errand_id=88,
            latitude=6.5244,
            longitude=3.3792,
            accuracy=9.0,
            source="mobile_app",
            recorded_at=recorded_at,
        ),
        authorization="Bearer token",
        db=db,
    )

    stored_location = next(value for value in db.added if isinstance(value, PilotLocation))
    assert stored_location.source == "mobile_app"
    assert stored_location.recorded_at == recorded_at
    assert stored_location.created_at == recorded_at
    assert payload.source == "mobile_app"
    assert payload.recorded_at == recorded_at
