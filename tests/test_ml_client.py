import pytest


@pytest.mark.asyncio
async def test_score_issue_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("ML_ENABLED", "false")

    from ml_client import score_issue

    res = await score_issue({"issueTitle": "anything"})
    assert res is None


@pytest.mark.asyncio
async def test_score_issue_enabled_calls_service(monkeypatch):
    monkeypatch.setenv("ML_ENABLED", "true")
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml:8010")
    monkeypatch.setenv("ML_TIMEOUT_SECONDS", "0.2")

    # Stub httpx so we don't do a real network call.
    import httpx

    class DummyResp:
        status_code = 200

        def json(self):
            return {"priority": 42, "tags": ["urgent"], "reasons": ["x"], "policyVersion": "heuristics-v1"}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            assert url.endswith("/score")
            assert isinstance(json, dict)
            return DummyResp()

    monkeypatch.setattr(httpx, "AsyncClient", DummyClient)

    from ml_client import score_issue

    res = await score_issue({"issueTitle": "Urgent refund", "issueDescription": "ASAP"})
    assert res is not None
    assert res["priority"] == 42
    assert res["policyVersion"] == "heuristics-v1"


@pytest.mark.asyncio
async def test_score_issue_enabled_failure_returns_none(monkeypatch):
    monkeypatch.setenv("ML_ENABLED", "true")

    import httpx

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            raise RuntimeError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", DummyClient)

    from ml_client import score_issue

    res = await score_issue({"issueTitle": "anything"})
    assert res is None
