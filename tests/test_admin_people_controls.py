from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4, UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import routes_admin
from app import pilot_dispatch_policy as policy
from database import get_db
from models import PilotDispatchPolicy


@pytest.fixture
def api(monkeypatch):
    pilot = SimpleNamespace(id=uuid4(), first_name="Test", last_name="Pilot", email="pilot@example.com", is_pilot=True, id_verification_status="pending", pilot_availability="online", admin_dispatch_status="enabled", pilot_status_changed_by=None)
    admin = SimpleNamespace(id=uuid4())
    db = SimpleNamespace(get=AsyncMock(return_value=pilot), commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(routes_admin, "_require_admin", AsyncMock(return_value=admin))
    app = FastAPI()
    app.include_router(routes_admin.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), pilot, admin, db


def test_verification_approve_and_revoke(api):
    client, pilot, _, db = api
    for approved in [True, False]:
        response = client.post(f"/admin/pilots/{pilot.id}/verify", json={"is_verified": approved})
        assert response.status_code == 200, response.text
        assert response.json()["is_verified"] is approved
        assert pilot.id_verification_status == ("verified" if approved else "pending")
    assert db.commit.await_count == 2


def test_verification_rejects_non_pilot_and_invalid_payload(api):
    client, pilot, _, db = api
    pilot.is_pilot = False
    assert client.post(f"/admin/pilots/{pilot.id}/verify", json={"is_verified": True}).status_code == 404
    assert client.post(f"/admin/pilots/{pilot.id}/verify", json={}).status_code == 422
    db.commit.assert_not_awaited()


def test_verification_requires_admin(api, monkeypatch):
    client, pilot, _, db = api
    monkeypatch.setattr(routes_admin, "_require_admin", AsyncMock(side_effect=HTTPException(403, "Admin access denied")))
    assert client.post(f"/admin/pilots/{pilot.id}/verify", json={"is_verified": True}).status_code == 403
    db.commit.assert_not_awaited()


def test_dispatch_actions_with_uuid(api):
    client, pilot, admin, _ = api
    for action, status in [("disable", "disabled"), ("permanently_disable", "permanently_disabled"), ("enable", "enabled")]:
        response = client.post(f"/admin/pilots/{pilot.id}/dispatch-status", json={"action": action})
        assert response.status_code == 200, response.text
        assert response.json()["admin_dispatch_status"] == status
        assert pilot.pilot_status_changed_by == admin.id


def test_policy_route_preserves_uuid_actor(api, monkeypatch):
    client, _, admin, db = api
    update = AsyncMock(return_value={"show_all_jobs_to_pilots": True, "open_pool_radius_miles": 15, "allowed_open_pool_radius_miles": [5, 10, 15, 20], "updated_by_user_id": admin.id})
    monkeypatch.setattr(routes_admin, "update_pilot_dispatch_policy", update)
    response = client.put("/admin/pilot-dispatch-policy", json={"show_all_jobs_to_pilots": True, "open_pool_radius_miles": 15})
    assert response.status_code == 200, response.text
    assert update.call_args.kwargs["actor_id"] == admin.id
    assert response.json()["updated_by_user_id"] == str(admin.id)
    for payload in [{}, {"open_pool_radius_miles": 7}]:
        assert client.put("/admin/pilot-dispatch-policy", json=payload).status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_policy_round_trip_with_uuid_schema(monkeypatch, existing):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(PilotDispatchPolicy.__table__.create)
    monkeypatch.setattr(policy, "_ensure_pilot_dispatch_policy_storage", AsyncMock())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    original_id = uuid4()
    actor = uuid4()
    async with sessions() as db:
        if existing:
            db.add(PilotDispatchPolicy(id=original_id, show_all_jobs_to_pilots=False, open_pool_radius_miles=5))
            await db.commit()
        for radius in [5, 10, 15, 20]:
            await policy.update_pilot_dispatch_policy(db, show_all_jobs_to_pilots=True, open_pool_radius_miles=radius, actor_id=actor)
            await db.commit()
            db.expunge_all()
            saved = await policy.get_pilot_dispatch_policy_state(db)
            assert saved["show_all_jobs_to_pilots"] is True
            assert saved["open_pool_radius_miles"] == radius
            assert saved["updated_by_user_id"] == actor
        row = await policy._load_pilot_dispatch_policy(db)
        assert isinstance(row.id, UUID)
        if existing:
            assert row.id == original_id
    await engine.dispose()
