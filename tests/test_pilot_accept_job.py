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
    def __init__(self, errand, active_conflict=None, customer=None):
        self.errand = errand
        self.active_conflict = active_conflict
        self.customer = customer
        self.added = []
        self.commit_calls = 0
        self.refresh_calls = 0

    async def execute(self, _query):
        if self.errand is not None:
            value = self.errand
            self.errand = None
            return ScalarResult(value)
        return ScalarResult(self.active_conflict)

    async def scalar(self, _query):
        return self.active_conflict

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, _value):
        self.refresh_calls += 1

    async def get(self, _model, _id):
        return self.customer


@pytest.mark.asyncio
async def test_accept_job_allows_open_pool_pending_errand(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", city="Lagos", state_province="Lagos")
    customer = SimpleNamespace(first_name="Ada", last_name="Client")
    errand = SimpleNamespace(
        id=55,
        pilot_id=None,
        status="pending",
        assigned_at=None,
        title="Courier / Document Delivery",
        description="Deliver documents",
        note="Handle with care",
        pickup_location="Ikeja, Lagos",
        dropoff_location="Lekki, Lagos",
        amount=10000,
        payment_amount_ngn_major=10000,
        distance_km=3.2,
        user_id=12,
    )
    db = FakeDB(errand=errand, customer=customer)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "ensure_pilot_can_accept_jobs", lambda _pilot: None)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_admin_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", fake_notify)

    payload = await pilot_delivery.accept_job(
        errand_id=55,
        authorization="Bearer token",
        db=db,
    )

    assert payload["ok"] is True
    assert payload["errand"]["id"] == 55
    assert payload["errand"]["status"] == "accepted"
    assert errand.pilot_id == 77
    assert errand.status == "accepted"
    assert isinstance(errand.assigned_at, datetime)
    assert errand.assigned_at.tzinfo == timezone.utc
    assert db.commit_calls == 1
    assert db.refresh_calls == 1
    assert db.added, "Expected a pilot_accept event to be recorded"


@pytest.mark.asyncio
async def test_accept_job_rejects_open_pool_errand_outside_service_area(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", city="Lagos", state_province="Lagos")
    customer = SimpleNamespace(first_name="Ada", last_name="Client")
    errand = SimpleNamespace(
        id=56,
        pilot_id=None,
        status="pending",
        assigned_at=None,
        title="Ibadan dispatch",
        description="Deliver package",
        note=None,
        pickup_location="Bodija, Ibadan",
        dropoff_location="UI, Ibadan",
        amount=10000,
        payment_amount_ngn_major=10000,
        distance_km=4.8,
        user_id=12,
    )
    db = FakeDB(errand=errand, customer=customer)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "ensure_pilot_can_accept_jobs", lambda _pilot: None)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_admin_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", fake_notify)

    with pytest.raises(pilot_delivery.HTTPException) as exc_info:
        await pilot_delivery.accept_job(
            errand_id=56,
            authorization="Bearer token",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Errand is outside your service area"


@pytest.mark.asyncio
async def test_accept_job_rejects_open_pool_errand_outside_5_mile_radius(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", city="Lagos", state_province="Lagos")
    customer = SimpleNamespace(first_name="Ada", last_name="Client")
    errand = SimpleNamespace(
        id=57,
        pilot_id=None,
        status="pending",
        assigned_at=None,
        title="Far Lagos dispatch",
        description="Deliver package",
        note=None,
        pickup_location="Ikorodu, Lagos",
        dropoff_location="Badagry, Lagos",
        amount=10000,
        payment_amount_ngn_major=10000,
        distance_km=20.0,
        user_id=12,
    )
    db = FakeDB(errand=errand, customer=customer)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "ensure_pilot_can_accept_jobs", lambda _pilot: None)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_admin_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", fake_notify)

    with pytest.raises(pilot_delivery.HTTPException) as exc_info:
        await pilot_delivery.accept_job(
            errand_id=57,
            authorization="Bearer token",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Errand is outside the 5 mile radius"


@pytest.mark.asyncio
async def test_accept_job_rejects_bike_support_for_pilot_without_bike(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", city="Lagos", state_province="Lagos", vehicle_type="car")
    customer = SimpleNamespace(first_name="Ada", last_name="Client")
    errand = SimpleNamespace(
        id=57,
        pilot_id=None,
        status="pending",
        assigned_at=None,
        title="Passport support",
        description="Collect passport",
        note=None,
        pickup_location="Ikeja, Lagos",
        dropoff_location="Lekki, Lagos",
        amount=10000,
        payment_amount_ngn_major=10000,
        distance_km=8.0,
        support_type="bike_support",
        user_id=12,
    )
    db = FakeDB(errand=errand, customer=customer)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "ensure_pilot_can_accept_jobs", lambda _pilot: None)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_admin_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", fake_notify)

    with pytest.raises(pilot_delivery.HTTPException) as exc_info:
        await pilot_delivery.accept_job(
            errand_id=57,
            authorization="Bearer token",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Bike support requires a pilot with bike access"


@pytest.mark.asyncio
async def test_accept_job_rejects_car_support_for_pilot_without_car(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", city="Lagos", state_province="Lagos", vehicle_type="bike")
    customer = SimpleNamespace(first_name="Ada", last_name="Client")
    errand = SimpleNamespace(
        id=58,
        pilot_id=None,
        status="pending",
        assigned_at=None,
        title="Legal filing",
        description="Sensitive filing",
        note=None,
        pickup_location="Ikeja, Lagos",
        dropoff_location="Victoria Island, Lagos",
        amount=10000,
        payment_amount_ngn_major=10000,
        distance_km=12.0,
        support_type="car_support",
        user_id=12,
    )
    db = FakeDB(errand=errand, customer=customer)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "ensure_pilot_can_accept_jobs", lambda _pilot: None)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_admin_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", fake_notify)

    with pytest.raises(pilot_delivery.HTTPException) as exc_info:
        await pilot_delivery.accept_job(
            errand_id=58,
            authorization="Bearer token",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Car support requires a pilot with car access"


@pytest.mark.asyncio
async def test_accept_job_requires_cross_city_enabled_pilot_for_long_distance(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", city="Lagos", state_province="Lagos", vehicle_type="car")
    customer = SimpleNamespace(first_name="Ada", last_name="Client")
    errand = SimpleNamespace(
        id=59,
        pilot_id=None,
        status="pending",
        assigned_at=None,
        title="Ibadan support",
        description="Long distance support",
        note=None,
        pickup_location="Yaba, Lagos",
        dropoff_location="Bodija, Ibadan",
        amount=10000,
        payment_amount_ngn_major=10000,
        distance_km=40.0,
        support_type="car_support",
        user_id=12,
    )
    db = FakeDB(errand=errand, customer=customer)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "ensure_pilot_can_accept_jobs", lambda _pilot: None)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_admin_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", fake_notify)

    with pytest.raises(pilot_delivery.HTTPException) as exc_info:
        await pilot_delivery.accept_job(
            errand_id=59,
            authorization="Bearer token",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "This errand requires a cross-city enabled pilot"


@pytest.mark.asyncio
async def test_accept_job_uses_configured_open_pool_radius(monkeypatch):
    pilot = SimpleNamespace(id=77, email="pilot@example.com", city="Lagos", state_province="Lagos")
    customer = SimpleNamespace(first_name="Ada", last_name="Client")
    errand = SimpleNamespace(
        id=58,
        pilot_id=None,
        status="pending",
        assigned_at=None,
        title="Farther Lagos dispatch",
        description="Deliver package",
        note=None,
        pickup_location="Ikorodu, Lagos",
        dropoff_location="Badagry, Lagos",
        amount=10000,
        payment_amount_ngn_major=10000,
        distance_km=30.0,
        user_id=12,
    )
    db = FakeDB(errand=errand, customer=customer)

    async def fake_current_user(_authorization, _db):
        return pilot

    async def fake_policy_state(_db):
        return {
            "show_all_jobs_to_pilots": False,
            "open_pool_radius_miles": 15,
        }

    async def fake_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(pilot_delivery, "ensure_pilot_can_accept_jobs", lambda _pilot: None)
    monkeypatch.setattr(pilot_delivery, "get_pilot_dispatch_policy_state", fake_policy_state)
    monkeypatch.setattr(pilot_delivery, "notify_customer_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_admin_status", fake_notify)
    monkeypatch.setattr(pilot_delivery, "notify_pilot_status", fake_notify)

    with pytest.raises(pilot_delivery.HTTPException) as exc_info:
        await pilot_delivery.accept_job(
            errand_id=58,
            authorization="Bearer token",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Errand is outside the 15 mile radius"