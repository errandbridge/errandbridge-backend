from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

import routes_admin


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, query):
        return FakeResult(self._rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [40303538255668495344180454036283315220, uuid.uuid4()])
async def test_admin_errand_chats_preserve_numeric_and_uuid_ids(
    monkeypatch,
    identifier,
):
    async def fake_require_admin(db, authorization):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)

    now = datetime.now(timezone.utc)
    errand = SimpleNamespace(
        id=identifier,
        reference_number="EB-TEST",
        status="pending",
        created_at=now,
        user_id=identifier,
        pilot_id=None,
    )
    customer = SimpleNamespace(
        first_name="Test",
        last_name="Customer",
        email="customer@example.com",
        phone=None,
    )
    db = FakeDB([(errand, customer, None, 1, now, "Hello", identifier)])
    request = Request({"type": "http", "headers": []})

    result = await routes_admin.list_errand_chats(request=request, db=db)

    assert len(result) == 1
    assert result[0].errand_id == identifier
    assert result[0].last_sender_id == identifier