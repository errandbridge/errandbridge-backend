"""Exercise the REST status handler without booting external app services."""
import ast
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import column, table


@pytest.fixture
def status_route(monkeypatch):
    # Execute the real handler and its real SQLAlchemy imports. This catches
    # missing module imports (cast/String) that mocked query builders conceal.
    source = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())
    imports = [node for node in source.body if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy"]
    handler = next(node for node in source.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_errand_status")
    handler.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *imports, handler], type_ignores=[])
    errand_table = table("errands", column("id"))
    errand_table.id = errand_table.c.id
    user_table = table("users", column("id"))
    user_table.id = user_table.c.id
    errand = SimpleNamespace(id="test-id", user_id="client", pilot_id="pilot", status="accepted", photo_url=None, started_at=None, tracking_paused=True)
    state = SimpleNamespace(errand=errand, actor="pilot", events=[], commits=0, queries=[])

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def execute(self, query):
            state.queries.append(query)
            value = None if query.get_final_froms()[0].name == "users" else state.errand
            return SimpleNamespace(scalar_one_or_none=lambda: value)
        def add(self, value):
            if isinstance(value, dict): state.events.append(value)
        async def commit(self): state.commits += 1
        async def refresh(self, value): pass

    tracking = ModuleType("app.routes.tracking")
    tracking.manager = SimpleNamespace(broadcast=AsyncMock())
    monkeypatch.setitem(sys.modules, "app.routes.tracking", tracking)
    notifications = ModuleType("app.utils.notification_utils")
    notifications.notify_customer_status = AsyncMock()
    notifications.notify_pilot_status = AsyncMock()
    monkeypatch.setitem(sys.modules, "app.utils.notification_utils", notifications)
    namespace = dict(Errand=errand_table, User=user_table, ErrandEvent=lambda **values: values,
        _current_user_id_from_request=lambda request: state.actor, AsyncSessionLocal=Session,
        _errand_response=lambda model: {"status": model.status}, datetime=datetime,
        timezone=timezone, HTTPException=HTTPException)
    exec(compile(ast.fix_missing_locations(module), "main.py", "exec"), namespace)
    return namespace["update_errand_status"], state


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["arrived_at_pickup", "picked_up", "arrived_at_dropoff"])
async def test_status_update_saves_and_returns_success(status_route, status):
    handler, state = status_route
    result = await handler("test-id", SimpleNamespace(status=status, imageProofUrl=None), None)
    assert result == {"status": status}
    assert state.commits == 1
    assert "CAST(errands.id AS VARCHAR)" in str(state.queries[0].compile())
    assert state.events[0]["new_status"] == status


@pytest.mark.asyncio
async def test_status_update_rejects_unassigned_actor(status_route):
    handler, state = status_route
    state.actor = "another-pilot"
    with pytest.raises(HTTPException) as error:
        await handler("test-id", SimpleNamespace(status="arrived_at_pickup", imageProofUrl=None), None)
    assert error.value.status_code == 403
    assert state.commits == 0
