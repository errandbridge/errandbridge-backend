from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes import errand_messages as routes


@pytest.fixture
def chat(monkeypatch):
    user = SimpleNamespace(id=uuid4(), first_name="Test", last_name="Client", email="client@example.test")
    errand = SimpleNamespace(id=uuid4(), user_id=user.id, pilot_id=uuid4(), status="assigned", completed_at=None)
    message = SimpleNamespace(id=uuid4(), errand_id=errand.id, sender_id=user.id, message="At reception", created_at=datetime.now(timezone.utc))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(message, user)])), commit=AsyncMock(), refresh=AsyncMock())
    def add(record):
        record.id = message.id
        record.created_at = message.created_at
    db.add = add
    monkeypatch.setattr(routes, "_get_current_user", AsyncMock(return_value=user))
    monkeypatch.setattr(routes, "_require_participant", AsyncMock(return_value=errand))
    monkeypatch.setattr(routes, "_is_admin", AsyncMock(return_value=False))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_db] = lambda: db
    with TestClient(app) as client:
        yield client, errand, message, db


def test_history_serializes_uuid_and_datetime(chat):
    client, errand, message, _ = chat
    response = client.get(f"/errands/{errand.id}/messages")
    assert response.status_code == 200
    item = response.json()["messages"][0]
    assert item["id"] == str(message.id)
    assert item["errand_id"] == str(errand.id)
    assert item["mine"] is True
    assert item["created_at"] == message.created_at.isoformat()


def test_send_serializes_uuid_without_integer_conversion(chat):
    client, errand, message, db = chat
    response = client.post(f"/errands/{errand.id}/messages", json={"message": "At reception"})
    assert response.status_code == 200
    assert response.json()["id"] == str(message.id)
    assert response.json()["mine"] is True
    db.commit.assert_awaited_once()


def test_completed_history_remains_readable_but_send_is_locked(chat):
    client, errand, _, db = chat
    errand.status = "completed"
    assert client.get(f"/errands/{errand.id}/messages").status_code == 200
    assert client.post(f"/errands/{errand.id}/messages", json={"message": "Hello"}).status_code == 409
    db.commit.assert_not_awaited()


def test_invalid_errand_id_is_rejected_before_database_lookup(chat):
    client, _, _, db = chat
    assert client.get("/errands/not-a-uuid/messages").status_code == 422
    db.execute.assert_not_awaited()
