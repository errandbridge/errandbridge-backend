from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.routes import analytics


class _FakeDB:
    def __init__(self):
        self.added = []
        self.committed = 0
        self.rolled_back = 0

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


@pytest.mark.asyncio
async def test_track_visit_reads_vercel_city_and_region_headers(monkeypatch):
    db = _FakeDB()
    recorded = []

    monkeypatch.setattr(
        analytics,
        "record_visit",
        lambda page, source, country: recorded.append(
            SimpleNamespace(page=page, source=source, country=country)
        ),
    )

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/analytics/visit",
            "headers": [
                (b"x-forwarded-for", b"1.2.3.4"),
                (b"x-vercel-ip-country", b"NG"),
                (b"x-vercel-ip-country-region", b"Lagos"),
                (b"x-vercel-ip-city", b"Ikeja"),
                (b"user-agent", b"pytest"),
            ],
        }
    )

    payload = analytics.VisitPayload(page="/", source="web", country="US")
    result = await analytics.track_visit(payload=payload, request=request, db=db)

    assert result == {"ok": True}
    assert db.committed == 1
    assert db.rolled_back == 0
    assert len(db.added) == 1

    visit = db.added[0]
    assert visit.country == "NG"
    assert visit.region == "Lagos"
    assert visit.city == "Ikeja"
    assert visit.ip_hash
    assert recorded[0].page == "/"
    assert recorded[0].source == "web"
    assert recorded[0].country == "NG"
