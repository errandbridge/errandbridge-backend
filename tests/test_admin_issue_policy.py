from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes_admin
from app import pilot_dispatch_policy


class ScalarListResult:
    def __init__(self, values):
        self._values = list(values)

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class CaptureIssuesDB:
    def __init__(self, rows):
        self.rows = list(rows)
        self.query = None

    async def execute(self, query):
        self.query = query
        return ScalarListResult(self.rows)


class FakePolicyDB:
    def __init__(self, get_results=None, flush_error=None):
        self.get_results = list(get_results or [])
        self.flush_error = flush_error
        self.added = []
        self.flush_calls = 0

    async def get(self, _model, _id):
        if self.get_results:
            result = self.get_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flush_calls += 1
        if self.flush_error is not None:
            error = self.flush_error
            self.flush_error = None
            raise error


class DeleteUserDB:
    def __init__(self, users):
        self.users = {int(user.id): user for user in users}
        self.deleted_ids = []
        self.commit_calls = 0
        self.begin_nested_calls = 0

    async def get(self, _model, user_id):
        return self.users.get(int(user_id))

    async def delete(self, user):
        self.deleted_ids.append(int(user.id))
        self.users.pop(int(user.id), None)

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        return None

    def begin_nested(self):
        self.begin_nested_calls += 1
        db = self

        class _NestedContext:
            async def __aenter__(self_inner):
                return db

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _NestedContext()


class BulkDeleteDB(DeleteUserDB):
    class _ScalarResult:
        def __init__(self, values):
            self._values = list(values)

        def scalars(self):
            return self

        def all(self):
            return list(self._values)

    async def execute(self, query):
        requested_ids = query._where_criteria[0].right.value
        values = [self.users[int(user_id)] for user_id in requested_ids if int(user_id) in self.users]
        return self._ScalarResult(values)


@pytest.mark.asyncio
async def test_list_issues_defaults_to_open_and_exposes_resolution_fields(monkeypatch):
    reported_at = datetime.now(timezone.utc)
    resolved_at = datetime.now(timezone.utc)
    db = CaptureIssuesDB(
        [
            SimpleNamespace(
                id=42,
                reference_number="EB-42",
                status="submitted",
                user_id=7,
                created_at=reported_at,
                issue_reason="wrong_item",
                issue_notes="Customer received the wrong package",
                issue_reported_at=reported_at,
                issue_preferred_resolution="refund",
                issue_status="open",
                issue_resolved_at=resolved_at,
                issue_resolution_notes="Reviewed by admin",
                issue_evidence_attachment_ids="12,13",
            )
        ]
    )

    async def fake_require_admin(_db, _authorization):
        return SimpleNamespace(id=99)

    async def fake_score_issue(_payload):
        return {
            "priority": 3,
            "tags": ["refund"],
            "reasons": ["Customer reported mismatch"],
            "policyVersion": "test-v1",
        }

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)
    monkeypatch.setattr(routes_admin, "score_issue", fake_score_issue)

    payload = await routes_admin.list_issues(
        authorization="Bearer token",
        db=db,
    )

    assert len(payload) == 1
    assert payload[0].issue_status == "open"
    assert payload[0].issue_resolved_at == resolved_at
    assert payload[0].issue_resolution_notes == "Reviewed by admin"
    assert payload[0].issue_evidence_attachment_ids == "12,13"
    assert payload[0].ml_priority == 3
    assert payload[0].ml_tags == ["refund"]
    assert "issue_status" in str(db.query)
    assert "issue_status" in str(db.query.whereclause)


@pytest.mark.asyncio
async def test_list_issues_honors_explicit_status_filter(monkeypatch):
    db = CaptureIssuesDB([])

    async def fake_require_admin(_db, _authorization):
        return SimpleNamespace(id=100)

    async def fake_score_issue(_payload):
        return {}

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)
    monkeypatch.setattr(routes_admin, "score_issue", fake_score_issue)

    await routes_admin.list_issues(
        authorization="Bearer token",
        status="resolved",
        db=db,
    )

    compiled = db.query.compile()
    assert "issue_status" in str(db.query.whereclause)
    assert "resolved" in compiled.params.values()


@pytest.mark.asyncio
async def test_update_pilot_dispatch_policy_sets_updated_at(monkeypatch):
    existing_policy = SimpleNamespace(
        id=1,
        show_all_jobs_to_pilots=False,
        open_pool_radius_miles=5,
        updated_at=None,
        updated_by_user_id=None,
    )
    db = FakePolicyDB(get_results=[existing_policy])

    async def fake_ensure_storage():
        return None

    monkeypatch.setattr(
        pilot_dispatch_policy,
        "_ensure_pilot_dispatch_policy_storage",
        fake_ensure_storage,
    )

    payload = await pilot_dispatch_policy.update_pilot_dispatch_policy(
        db,
        show_all_jobs_to_pilots=True,
        open_pool_radius_miles=15,
        actor_id=55,
    )

    assert existing_policy.show_all_jobs_to_pilots is True
    assert existing_policy.open_pool_radius_miles == 15
    assert existing_policy.updated_by_user_id == 55
    assert existing_policy.updated_at is not None
    assert payload["show_all_jobs_to_pilots"] is True
    assert payload["open_pool_radius_miles"] == 15
    assert payload["updated_by_user_id"] == 55
    assert payload["updated_at"] == existing_policy.updated_at


@pytest.mark.asyncio
async def test_get_or_create_pilot_dispatch_policy_ensures_storage_before_query(monkeypatch):
    db = FakePolicyDB(get_results=[None])
    ensure_calls = []

    async def fake_ensure_storage():
        ensure_calls.append("called")

    monkeypatch.setattr(
        pilot_dispatch_policy,
        "_ensure_pilot_dispatch_policy_storage",
        fake_ensure_storage,
    )

    policy = await pilot_dispatch_policy.get_or_create_pilot_dispatch_policy(db)

    assert ensure_calls == ["called"]
    assert db.flush_calls == 1
    assert db.added
    assert policy.show_all_jobs_to_pilots is False
    assert policy.open_pool_radius_miles == 5


@pytest.mark.asyncio
async def test_standard_admin_cannot_delete_another_admin(monkeypatch):
    admin = SimpleNamespace(id=10, email="admin@errandbridge.com")
    target = SimpleNamespace(id=27, email="ade@errandbridge.com")
    db = DeleteUserDB([target])
    request = SimpleNamespace(headers={})

    async def fake_require_admin(_db, _authorization):
        return admin

    async def fake_cascade_delete_user_data(_db, _user_id):
        return {"stored_filenames": []}

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)
    monkeypatch.setattr(routes_admin, "_cascade_delete_user_data", fake_cascade_delete_user_data)
    monkeypatch.setattr(routes_admin, "admin_emails", lambda: {"admin@errandbridge.com", "ade@errandbridge.com"})
    monkeypatch.setattr(routes_admin, "is_elevated_admin_email", lambda email: str(email).lower() == "ade@errandbridge.com")

    with pytest.raises(HTTPException) as excinfo:
        await routes_admin.delete_user(user_id=27, request=request, db=db)

    assert excinfo.value.status_code == 403
    assert "elevated admins" in excinfo.value.detail
    assert db.deleted_ids == []


@pytest.mark.asyncio
async def test_elevated_admin_can_delete_another_admin(monkeypatch):
    admin = SimpleNamespace(id=27, email="ade@errandbridge.com")
    target = SimpleNamespace(id=10, email="admin@errandbridge.com")
    db = DeleteUserDB([target])
    request = SimpleNamespace(headers={})

    async def fake_require_admin(_db, _authorization):
        return admin

    async def fake_cascade_delete_user_data(_db, _user_id):
        return {"stored_filenames": []}

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)
    monkeypatch.setattr(routes_admin, "_cascade_delete_user_data", fake_cascade_delete_user_data)
    monkeypatch.setattr(routes_admin, "admin_emails", lambda: {"admin@errandbridge.com", "ade@errandbridge.com"})
    monkeypatch.setattr(routes_admin, "is_elevated_admin_email", lambda email: str(email).lower() == "ade@errandbridge.com")

    payload = await routes_admin.delete_user(user_id=10, request=request, db=db)

    assert payload.deleted is True
    assert db.deleted_ids == [10]
    assert db.commit_calls == 1


@pytest.mark.asyncio
async def test_bulk_delete_skips_admins_for_standard_admin(monkeypatch):
    admin = SimpleNamespace(id=10, email="admin@errandbridge.com")
    target_admin = SimpleNamespace(id=27, email="ade@errandbridge.com")
    target_user = SimpleNamespace(id=33, email="customer@example.com")
    db = BulkDeleteDB([target_admin, target_user])
    request = SimpleNamespace(headers={})

    async def fake_require_admin(_db, _authorization):
        return admin

    async def fake_cascade_delete_user_data(_db, _user_id):
        return {"stored_filenames": []}

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)
    monkeypatch.setattr(routes_admin, "_cascade_delete_user_data", fake_cascade_delete_user_data)
    monkeypatch.setattr(
        routes_admin,
        "admin_emails",
        lambda: {"admin@errandbridge.com", "ade@errandbridge.com"},
    )
    monkeypatch.setattr(routes_admin, "is_elevated_admin_email", lambda email: str(email).lower() == "ade@errandbridge.com")

    payload = await routes_admin.bulk_delete_users(
        payload=routes_admin.AdminBulkDeleteUsersIn(user_ids=[27, 33]),
        request=request,
        db=db,
    )

    assert payload.deleted == 1
    assert payload.deleted_user_ids == [33]
    assert payload.skipped_admins == ["ade@errandbridge.com"]
    assert payload.skipped_user_ids == [27]
    assert db.deleted_ids == [33]
    assert db.begin_nested_calls == 1
    assert db.commit_calls == 1


@pytest.mark.asyncio
async def test_bulk_delete_allows_admin_targets_for_elevated_admin(monkeypatch):
    admin = SimpleNamespace(id=27, email="ade@errandbridge.com")
    target_admin = SimpleNamespace(id=10, email="admin@errandbridge.com")
    target_user = SimpleNamespace(id=33, email="customer@example.com")
    db = BulkDeleteDB([target_admin, target_user])
    request = SimpleNamespace(headers={})

    async def fake_require_admin(_db, _authorization):
        return admin

    async def fake_cascade_delete_user_data(_db, _user_id):
        return {"stored_filenames": []}

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)
    monkeypatch.setattr(routes_admin, "_cascade_delete_user_data", fake_cascade_delete_user_data)
    monkeypatch.setattr(
        routes_admin,
        "admin_emails",
        lambda: {"admin@errandbridge.com", "ade@errandbridge.com"},
    )
    monkeypatch.setattr(routes_admin, "is_elevated_admin_email", lambda email: str(email).lower() == "ade@errandbridge.com")

    payload = await routes_admin.bulk_delete_users(
        payload=routes_admin.AdminBulkDeleteUsersIn(user_ids=[10, 33]),
        request=request,
        db=db,
    )

    assert payload.deleted == 2
    assert payload.deleted_user_ids == [10, 33]
    assert payload.skipped_admins == []
    assert payload.skipped_user_ids == []
    assert db.deleted_ids == [10, 33]
    assert db.begin_nested_calls == 2
    assert db.commit_calls == 1
