from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import routes_admin


class _AllRowsResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _FakeAdminMetricsDB:
    """Minimal DB stub for get_admin_metrics_overview().

    This test is intentionally focused on the "Unknown" country rollup to
    ensure "XX" placeholder rows are not double-counted.
    """

    def __init__(self):
        # Scalar calls (in order):
        # 1 total_users, 2 verified_users, 3 total_errands, 4 pending_issues,
        # 5 visits_total, 6 visits_last_24h, 7 unknown_visits
        self._scalar_values = [
            0,
            0,
            0,
            0,
            10,  # total visits
            10,  # visits last 24h
            6,  # unknown_visits: None (4) + XX (2)
        ]
        self._scalar_calls = 0
        self._execute_calls = 0

        # Country distribution in the underlying table (conceptually):
        # US: 3, XX: 2, UNKNOWN: 1, NULL: 4
        self._country_rows_with_xx = [("US", 3), ("XX", 2), ("UNKNOWN", 1)]

    async def scalar(self, _query):
        self._scalar_calls += 1
        try:
            return self._scalar_values[self._scalar_calls - 1]
        except IndexError as exc:
            raise AssertionError(f"Unexpected scalar() call #{self._scalar_calls}") from exc

    async def execute(self, query):
        self._execute_calls += 1

        # get_admin_metrics_overview() execute calls (in order):
        # 1 country_rows, 2 region_rows, 3 city_rows, 4 location_rows,
        # 5 last_24h_location_rows, 6 recent_visit_rows, 7 source_rows, 8 status_rows
        if self._execute_calls == 1:
            # If the query excludes XX (country_norm != 'XX'), then the grouped
            # result set should not include XX rows.
            params = {}
            try:
                params = query.compile().params
            except Exception:
                params = {}

            query_str = str(query).lower()
            has_xx_param = any(str(v) == "XX" for v in params.values())
            has_not_equal = ("!=" in query_str) or ("<>" in query_str)
            mentions_country_norm = "upper" in query_str and "trim" in query_str and "country" in query_str
            excludes_xx = has_xx_param and has_not_equal and mentions_country_norm

            if excludes_xx:
                rows = [("US", 3), ("UNKNOWN", 1)]
            else:
                rows = list(self._country_rows_with_xx)
            return _AllRowsResult(rows)

        # Remaining execute calls return empty datasets for this unit test.
        if self._execute_calls == 6:
            return _AllRowsResult([
                ("/", "web", "US", None, None, datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)),
            ])

        if 2 <= self._execute_calls <= 8:
            return _AllRowsResult([])

        raise AssertionError(f"Unexpected execute() call #{self._execute_calls}")


@pytest.mark.asyncio
async def test_admin_metrics_overview_unknown_country_does_not_double_count_xx(monkeypatch):
    db = _FakeAdminMetricsDB()

    async def fake_require_admin(_db, _authorization):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)
    monkeypatch.setattr(routes_admin, "update_admin_metrics", lambda _payload: None)

    payload = await routes_admin.get_admin_metrics_overview(
        authorization="Bearer token",
        db=db,
    )

    assert payload["visits_total"] == 10

    counts = {row["country"]: int(row["count"]) for row in payload["visits_by_country"]}
    assert counts["US"] == 3

    # Unknown should be: NULL (4) + XX (2) + UNKNOWN placeholder (1) = 7
    assert counts["Unknown"] == 7

    # Sanity: top countries + Unknown should account for all visits in this dataset.
    assert sum(counts.values()) == payload["visits_total"]


class _FakeAdminMetricsCountryAliasDB(_FakeAdminMetricsDB):
    def __init__(self):
        super().__init__()
        self._scalar_values = [0, 0, 0, 0, 3, 3, 0]

    async def execute(self, _query):
        self._execute_calls += 1
        if self._execute_calls == 1:
            return _AllRowsResult([("NIGERIA", 2), ("US", 1)])
        if 2 <= self._execute_calls <= 4:
            return _AllRowsResult([])
        if self._execute_calls == 5:
            return _AllRowsResult([("NIGERIA", "Lagos", "Ikeja", 2)])
        if self._execute_calls == 6:
            return _AllRowsResult([
                ("/pricing", "web", "NIGERIA", "Lagos", "Ikeja", datetime(2026, 7, 8, 14, 30, tzinfo=timezone.utc)),
            ])
        if self._execute_calls in {7, 8}:
            return _AllRowsResult([])
        raise AssertionError(f"Unexpected execute() call #{self._execute_calls}")


@pytest.mark.asyncio
async def test_admin_metrics_overview_normalizes_full_country_names(monkeypatch):
    db = _FakeAdminMetricsCountryAliasDB()

    async def fake_require_admin(_db, _authorization):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(routes_admin, "_require_admin", fake_require_admin)
    monkeypatch.setattr(routes_admin, "update_admin_metrics", lambda _payload: None)

    payload = await routes_admin.get_admin_metrics_overview(
        authorization="Bearer token",
        db=db,
    )

    counts = {row["country"]: int(row["count"]) for row in payload["visits_by_country"]}
    assert counts["NG"] == 2
    assert counts["US"] == 1
    assert payload["visits_last_24h_by_location"] == [
        {"country": "NG", "region": "Lagos", "city": "Ikeja", "count": 2}
    ]
    assert payload["visits_recent_24h"] == [
        {
            "page": "/pricing",
            "source": "web",
            "country": "NG",
            "region": "Lagos",
            "city": "Ikeja",
            "created_at": "2026-07-08T14:30:00+00:00",
        }
    ]
