from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.routes import pilot_delivery


class ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDB:
    def __init__(self, errand):
        self._errand = errand
        self.added = []
        self.commit_calls = 0
        self.refresh_calls = 0

    async def execute(self, _query):
        # start_delivery/complete_delivery both do one execute() to fetch the errand.
        value = self._errand
        return ScalarResult(value)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, _value):
        self.refresh_calls += 1


@pytest.mark.asyncio
async def test_start_delivery_records_pilot_started_event(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", is_pilot=True)
    errand = SimpleNamespace(
        id=55,
        pilot_id=77,
        status="accepted",
        pickup_location="Ikeja",
        dropoff_location="Yaba",
        started_at=None,
        tracking_paused=False,
    )
    db = FakeDB(errand=errand)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_tracking_started", fake_notify)

    payload = await pilot_delivery.start_delivery(
        errand_id=55,
        note="Starting now",
        authorization="Bearer token",
        db=db,
    )

    assert payload["success"] is True
    assert errand.status == "in_progress"
    assert isinstance(errand.started_at, datetime)
    assert errand.started_at.tzinfo == timezone.utc

    assert db.commit_calls == 1
    assert db.refresh_calls == 1

    event_types = [getattr(e, "event_type", None) for e in db.added]
    assert "pilot_started" in event_types


@pytest.mark.asyncio
async def test_complete_delivery_records_pilot_completed_event(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", is_pilot=True)
    errand = SimpleNamespace(
        id=56,
        pilot_id=77,
        status="in_progress",
        pickup_location="Ikeja",
        dropoff_location="Yaba",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        tracking_paused=False,
    )
    db = FakeDB(errand=errand)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_notify(*_args, **_kwargs):
        return None

    async def fake_archive(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "_archive_route_snapshot", fake_archive)

    payload = await pilot_delivery.complete_delivery(
        errand_id=56,
        notes="Done",
        authorization="Bearer token",
        db=db,
    )

    assert payload["success"] is True
    assert errand.status == "completed"
    assert isinstance(errand.completed_at, datetime)
    assert errand.completed_at.tzinfo == timezone.utc

    # complete_delivery calls commit once before archiving.
    assert db.commit_calls == 1
    assert db.refresh_calls == 1

    event_types = [getattr(e, "event_type", None) for e in db.added]
    assert "pilot_completed" in event_types


@pytest.mark.asyncio
async def test_start_and_complete_delivery_with_uuid_ids(monkeypatch):
    pilot_uuid = "6d28c4eb-dc2e-4e92-9cff-771f984d33b5"
    errand_uuid = "83335f97-3991-4174-997c-77f76f72bf86"

    pilot = SimpleNamespace(id=pilot_uuid, email="pilot@example.com", is_pilot=True)
    errand = SimpleNamespace(
        id=errand_uuid,
        pilot_id=pilot_uuid,
        status="accepted",
        pickup_location="Ikeja",
        dropoff_location="Yaba",
        started_at=None,
        completed_at=None,
        tracking_paused=False,
    )
    db = FakeDB(errand=errand)

    async def fake_get_current_user(*_args, **_kwargs):
        return pilot
    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_get_current_user)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pilot_delivery, "notify_tracking_started", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pilot_delivery, "_archive_route_snapshot", lambda *_args, **_kwargs: None)

    # 1. Start delivery with UUIDs (previously crashed with ValueError in int(errand.pilot_id))
    start_payload = await pilot_delivery.start_delivery(
        errand_id=errand_uuid,
        note="UUID test start",
        authorization="Bearer token",
        db=db,
    )
    assert start_payload["success"] is True
    assert errand.status == "in_progress"
    assert isinstance(errand.started_at, datetime)

    # 2. Complete delivery with UUIDs
    complete_payload = await pilot_delivery.complete_delivery(
        errand_id=errand_uuid,
        notes="UUID test complete",
        authorization="Bearer token",
        db=db,
    )
    assert complete_payload["success"] is True
    assert errand.status == "completed"
    assert isinstance(errand.completed_at, datetime)
