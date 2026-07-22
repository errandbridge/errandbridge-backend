from types import SimpleNamespace

import pytest

from app.routes import pilot_delivery, pilot_profile


class ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, *, scalar_values=None, rows=None):
        self.scalar_values = list(scalar_values or [])
        self.rows = rows if rows is not None else []
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)
        if self.scalar_values:
            return ScalarResult(self.scalar_values.pop(0))
        return RowsResult(self.rows)

    async def commit(self):
        return None

    async def refresh(self, _value):
        return None


@pytest.mark.asyncio
async def test_get_pilot_stats_counts_only_completed_errands(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(id=77, rating=4.9)

    monkeypatch.setattr(pilot_profile, "_get_current_user", fake_current_user)
    db = FakeDB(scalar_values=[0, 0, 0])

    payload = await pilot_profile.get_pilot_stats(
        authorization="Bearer token",
        db=db,
    )

    assert payload["totalDeliveries"] == 0
    assert payload["totalErrands"] == 0
    assert payload["completedToday"] == 0
    assert payload["rating"] == 4.9
    compiled = db.queries[0].compile()
    assert "errands.status" in str(compiled)
    assert compiled.params["status_1"] == "completed"


@pytest.mark.asyncio
async def test_list_pilot_jobs_accepts_status_query_name(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(id=77)

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    db = FakeDB(rows=[])

    payload = await pilot_delivery.list_pilot_jobs(
        status="completed",
        authorization="Bearer token",
        db=db,
    )

    assert payload == {"errands": []}
    assert db.queries, "Expected the route to execute a jobs query"
    compiled = db.queries[0].compile()
    assert "errands.status" in str(compiled)
    assert compiled.params["status_1"] == ["completed"]


@pytest.mark.asyncio
async def test_list_pilot_jobs_exposes_canonical_payment_amount(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(id=77)

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    db = FakeDB(
        rows=[
            (
                SimpleNamespace(
                    id=1,
                    reference_number="EB-1",
                    title="Airport pickup",
                    description="Pickup and dropoff",
                    status="assigned",
                    started_at=None,
                    pickup_location="MMA",
                    dropoff_location="Lekki",
                    sensitivity=None,
                    created_at=None,
                    completed_at=None,
                    note=None,
                    amount=10000,
                    payment_amount_ngn_major=10000,
                    distance_km=4.5,
                    customer_rating=None,
                    pickup_time_slot_start=None,
                    pickup_time_slot_end=None,
                    pickup_time_slot_date=None,
                ),
                SimpleNamespace(first_name="Ada", last_name="Pilot"),
            )
        ]
    )

    payload = await pilot_delivery.list_pilot_jobs(
        status="active",
        authorization="Bearer token",
        db=db,
    )

    assert payload["errands"][0]["payment_amount_ngn_major"] == 10000
    assert payload["errands"][0]["paymentAmountNgnMajor"] == 10000


@pytest.mark.asyncio
async def test_list_available_jobs_filters_open_pool_by_city_and_5_miles_but_keeps_dedicated_assignments(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(id=77, city="Lagos", state_province="Lagos")

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(
        pilot_delivery,
        "serialize_pilot_dispatch_state",
        lambda _pilot: {"canAcceptJobs": True, "dispatchBlockReason": ""},
    )

    db = FakeDB(
        rows=[
            (
                SimpleNamespace(
                    id=1,
                    reference_number="EB-1",
                    title="Nearby Lagos run",
                    description="Pickup in Lagos",
                    status="pending",
                    pilot_id=None,
                    pickup_location="Ikeja, Lagos",
                    dropoff_location="Lekki, Lagos",
                    sensitivity=None,
                    created_at=None,
                    note=None,
                    amount=10000,
                    payment_amount_ngn_major=10000,
                    distance_km=4.5,
                    customer_rating=None,
                    pickup_time_slot_start=None,
                    pickup_time_slot_end=None,
                    pickup_time_slot_date=None,
                ),
                SimpleNamespace(first_name="Ada", last_name="Client"),
            ),
            (
                SimpleNamespace(
                    id=2,
                    reference_number="EB-2",
                    title="Ibadan open pool",
                    description="Pickup in Ibadan",
                    status="pending",
                    pilot_id=None,
                    pickup_location="Bodija, Ibadan",
                    dropoff_location="UI, Ibadan",
                    sensitivity=None,
                    created_at=None,
                    note=None,
                    amount=8000,
                    payment_amount_ngn_major=8000,
                    distance_km=4.0,
                    customer_rating=None,
                    pickup_time_slot_start=None,
                    pickup_time_slot_end=None,
                    pickup_time_slot_date=None,
                ),
                SimpleNamespace(first_name="Bisi", last_name="Client"),
            ),
            (
                SimpleNamespace(
                    id=3,
                    reference_number="EB-3",
                    title="Far Lagos open pool",
                    description="Too far away",
                    status="pending",
                    pilot_id=None,
                    pickup_location="Ikorodu, Lagos",
                    dropoff_location="Badagry, Lagos",
                    sensitivity=None,
                    created_at=None,
                    note=None,
                    amount=12000,
                    payment_amount_ngn_major=12000,
                    distance_km=12.0,
                    customer_rating=None,
                    pickup_time_slot_start=None,
                    pickup_time_slot_end=None,
                    pickup_time_slot_date=None,
                ),
                SimpleNamespace(first_name="Chidi", last_name="Client"),
            ),
            (
                SimpleNamespace(
                    id=4,
                    reference_number="EB-4",
                    title="Dedicated out-of-area errand",
                    description="Assigned directly to the pilot",
                    status="assigned",
                    pilot_id=77,
                    pickup_location="Bodija, Ibadan",
                    dropoff_location="UI, Ibadan",
                    sensitivity=None,
                    created_at=None,
                    note=None,
                    amount=15000,
                    payment_amount_ngn_major=15000,
                    distance_km=98.0,
                    customer_rating=None,
                    pickup_time_slot_start=None,
                    pickup_time_slot_end=None,
                    pickup_time_slot_date=None,
                ),
                SimpleNamespace(first_name="Dami", last_name="Client"),
            ),
        ]
    )

    payload = await pilot_delivery.list_available_jobs(
        authorization="Bearer token",
        db=db,
    )

    assert [errand["id"] for errand in payload["errands"]] == [1, 4]
    assert payload["total"] == 2


@pytest.mark.asyncio
async def test_list_available_jobs_can_show_non_matching_jobs_when_policy_allows(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(id=77, city="Lagos", state_province="Lagos")

    async def fake_policy_state(_db):
        return {
            "show_all_jobs_to_pilots": True,
            "open_pool_radius_miles": 15,
        }

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    monkeypatch.setattr(
        pilot_delivery,
        "serialize_pilot_dispatch_state",
        lambda _pilot: {"canAcceptJobs": True, "dispatchBlockReason": ""},
    )
    monkeypatch.setattr(
        pilot_delivery,
        "get_pilot_dispatch_policy_state",
        fake_policy_state,
    )

    db = FakeDB(
        rows=[
            (
                SimpleNamespace(
                    id=1,
                    reference_number="EB-1",
                    title="Nearby Lagos run",
                    description="Pickup in Lagos",
                    status="pending",
                    pilot_id=None,
                    pickup_location="Ikeja, Lagos",
                    dropoff_location="Lekki, Lagos",
                    sensitivity=None,
                    created_at=None,
                    note=None,
                    amount=10000,
                    payment_amount_ngn_major=10000,
                    distance_km=6.5,
                    customer_rating=None,
                    pickup_time_slot_start=None,
                    pickup_time_slot_end=None,
                    pickup_time_slot_date=None,
                ),
                SimpleNamespace(first_name="Ada", last_name="Client"),
            ),
            (
                SimpleNamespace(
                    id=2,
                    reference_number="EB-2",
                    title="Far Lagos open pool",
                    description="Too far away",
                    status="pending",
                    pilot_id=None,
                    pickup_location="Ikorodu, Lagos",
                    dropoff_location="Badagry, Lagos",
                    sensitivity=None,
                    created_at=None,
                    note=None,
                    amount=12000,
                    payment_amount_ngn_major=12000,
                    distance_km=30.0,
                    customer_rating=None,
                    pickup_time_slot_start=None,
                    pickup_time_slot_end=None,
                    pickup_time_slot_date=None,
                ),
                SimpleNamespace(first_name="Chidi", last_name="Client"),
            ),
        ]
    )

    payload = await pilot_delivery.list_available_jobs(
        authorization="Bearer token",
        db=db,
    )

    assert [errand["id"] for errand in payload["errands"]] == [1, 2]
    assert payload["dispatch_policy"]["show_all_jobs_to_pilots"] is True
    assert payload["dispatch_policy"]["open_pool_radius_miles"] == 15
    assert payload["errands"][0]["matches_dispatch_policy"] is True
    assert payload["errands"][0]["acceptance_block_reason"] is None
    assert payload["errands"][1]["matches_dispatch_policy"] is False
    assert payload["errands"][1]["acceptance_block_reason"] == "Errand is outside the 15 mile radius"


@pytest.mark.asyncio
async def test_get_active_delivery_scopes_to_authenticated_pilot(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(id=77, is_pilot=True)

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    db = FakeDB(
        scalar_values=[
            SimpleNamespace(
                id=18,
                pilot_id=77,
                customer_name="Ada Client",
                pickup_location="Ikeja",
                dropoff_location="Lekki",
                amount=12000,
                payment_amount_ngn_major=12000,
                status="in_progress",
                started_at=None,
                tracking_paused=False,
            )
        ]
    )

    payload = await pilot_delivery.get_active_delivery(
        authorization="Bearer token",
        db=db,
    )

    assert payload["has_active_delivery"] is True
    assert payload["errand"]["id"] == 18
    assert payload["errand"]["pilot_id"] == 77
    compiled = db.queries[0].compile()
    compiled_sql = str(compiled)
    assert "errands.pilot_id" in compiled_sql
    assert compiled.params["pilot_id_1"] == 77
    assert compiled.params["status_1"] == "in_progress"


@pytest.mark.asyncio
async def test_get_active_delivery_rejects_other_pilot_id(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(id=77, is_pilot=True)

    monkeypatch.setattr(pilot_delivery, "_get_current_user", fake_current_user)
    db = FakeDB()

    with pytest.raises(pilot_delivery.HTTPException) as exc_info:
        await pilot_delivery.get_active_delivery(
            authorization="Bearer token",
            pilot_id=88,
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "You can only view your own active delivery"


@pytest.mark.asyncio
async def test_update_vehicle_accepts_json_body_payload(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(
            id=77,
            email="pilot@example.com",
            first_name="Ada",
            last_name="Pilot",
            phone="0800",
            is_email_verified=True,
            id_verification_status="pending",
            address_verification_status="pending",
            date_of_birth=None,
            profile_image_url=None,
            street_address="12 Allen Avenue",
            city="Lagos",
            state_province="Lagos",
            postal_code=None,
            country="Nigeria",
            vehicle_type="car",
            vehicle_make=None,
            vehicle_model=None,
            vehicle_year=None,
            license_plate=None,
            insurance_provider=None,
            insurance_expiry=None,
            pilot_availability="offline",
            admin_dispatch_status="enabled",
        )

    monkeypatch.setattr(pilot_profile, "_get_current_user", fake_current_user)
    db = FakeDB()

    payload = await pilot_profile.update_vehicle(
        payload=pilot_profile.VehicleUpdate(
            vehicle_type="car",
            vehicle_make="Toyota",
            vehicle_model="Corolla",
            vehicle_year=2024,
            license_plate="ABC-123",
            insurance_provider="Acme Insurance",
            insurance_expiry="2026-12-01",
        ),
        authorization="Bearer token",
        db=db,
    )

    assert payload["ok"] is True
    assert payload["profile"]["vehicle_type"] == "car"
    assert payload["profile"]["has_car"] is True
    assert payload["profile"]["has_bike"] is False
    assert payload["profile"]["service_area_text"] == "Lagos"
    compiled = db.queries[0].compile()
    params = compiled.params
    assert params["vehicle_type"] == "car"
    assert params["vehicle_make"] == "Toyota"
    assert params["vehicle_model"] == "Corolla"
    assert params["vehicle_year"] == 2024
    assert params["license_plate"] == "ABC-123"
    assert params["insurance_provider"] == "Acme Insurance"


@pytest.mark.asyncio
async def test_change_password_accepts_json_body_payload(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(id=77, password_hash="stored-hash")

    hash_calls = []

    def fake_verify_password(current_password, password_hash):
        return current_password == "current-pass" and password_hash == "stored-hash"

    def fake_hash_password(new_password):
        hash_calls.append(new_password)
        return f"hashed::{new_password}"

    monkeypatch.setattr(pilot_profile, "_get_current_user", fake_current_user)
    monkeypatch.setattr(
        pilot_profile,
        "verify_password",
        fake_verify_password,
        raising=False,
    )
    monkeypatch.setattr(
        pilot_profile,
        "hash_password",
        fake_hash_password,
        raising=False,
    )

    import auth as auth_module

    monkeypatch.setattr(auth_module, "verify_password", fake_verify_password)
    monkeypatch.setattr(auth_module, "hash_password", fake_hash_password)

    db = FakeDB()

    payload = await pilot_profile.change_password(
        payload=pilot_profile.ChangePasswordIn(
            current_password="current-pass",
            new_password="new-password-123",
        ),
        authorization="Bearer token",
        db=db,
    )

    assert payload["ok"] is True
    assert hash_calls == ["new-password-123"]
    compiled = db.queries[0].compile()
    assert compiled.params["password_hash"] == "hashed::new-password-123"


@pytest.mark.asyncio
async def test_get_profile_exposes_dispatch_fit_flags(monkeypatch):
    async def fake_current_user(_authorization, _db):
        return SimpleNamespace(
            id=77,
            email="pilot@example.com",
            first_name="Ada",
            last_name="Pilot",
            phone="0800",
            is_email_verified=True,
            id_verification_status="approved",
            address_verification_status="approved",
            date_of_birth=None,
            profile_image_url=None,
            street_address="12 Allen Avenue",
            city="Lagos",
            state_province="Lagos",
            postal_code="100001",
            country="Nigeria",
            vehicle_type="motorcycle",
            vehicle_make="Honda",
            vehicle_model="CB",
            vehicle_year=2023,
            license_plate="EB-77",
            insurance_provider="Acme",
            insurance_expiry=None,
            pilot_availability="online",
            admin_dispatch_status="enabled",
            cross_city_available=True,
            service_radius_km=18,
        )

    monkeypatch.setattr(pilot_profile, "_get_current_user", fake_current_user)

    payload = await pilot_profile.get_profile(
        authorization="Bearer token",
        db=FakeDB(),
    )

    assert payload["has_bike"] is True
    assert payload["has_car"] is False
    assert payload["cross_city_available"] is True
    assert payload["service_radius_km"] == 18
    assert payload["service_area_text"] == "Lagos"
