from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx


def _running_in_docker_filesystem() -> bool:
    try:
        return os.path.exists("/.dockerenv")
    except Exception:
        return False


def _normalize_db_dsn(url: str) -> str:
    """Normalize DATABASE_URL-like values into a DSN asyncpg can use."""

    raw = (url or "").strip()
    if not raw:
        return raw

    # SQLAlchemy async URLs -> plain Postgres DSN.
    raw = raw.replace("postgresql+asyncpg://", "postgresql://")
    raw = raw.replace("postgres://", "postgresql://")

    # If we're running on the host and the DSN uses docker-compose hostname `db`,
    # translate to host-mapped localhost port.
    if not _running_in_docker_filesystem():
        raw = raw.replace("@db:5432/", "@127.0.0.1:5433/")

    return raw


def _default_db_dsn() -> str:
    # Prefer DATABASE_URL if set.
    env_url = (os.getenv("DATABASE_URL") or "").strip()
    if env_url:
        return _normalize_db_dsn(env_url)

    # Otherwise, choose a safe default depending on where we run.
    if _running_in_docker_filesystem():
        return "postgresql://postgres:postgres@db:5432/errandbridge"
    return "postgresql://postgres:postgres@127.0.0.1:5433/errandbridge"


@dataclass
class ScanResult:
    ok: bool
    details: list[str]


async def _fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    res = await client.get(url)
    res.raise_for_status()
    return res.json()


async def _db_country_counts(
    *, dsn: str, since_epoch_s: float
) -> dict[str | None, int]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        # Only count visits we created during the scan.
        rows = await conn.fetch(
            """
            SELECT country, COUNT(*)::int AS c
            FROM analytics_visits
            WHERE source = $1 AND EXTRACT(EPOCH FROM created_at) >= $2
            GROUP BY country
            ORDER BY c DESC
            """,
            "stack-scan",
            float(since_epoch_s),
        )
        return {r["country"]: int(r["c"]) for r in rows}
    finally:
        await conn.close()


async def run_scan(
    *, api_base: str, db_dsn: str, admin_token: str | None
) -> ScanResult:
    details: list[str] = []

    base = api_base.rstrip("/")
    health_url = f"{base}/health"
    ready_url = f"{base}/ready"
    metrics_url = f"{base}/metrics"
    visit_url = f"{base}/analytics/visit"
    admin_overview_url = f"{base}/admin/metrics/overview"

    since = time.time()

    async with httpx.AsyncClient(timeout=8.0) as client:
        # 1) Liveness & readiness
        try:
            r = await client.get(health_url)
            r.raise_for_status()
            details.append(f"health: {r.status_code}")
        except Exception as exc:
            return ScanResult(False, details + [f"health failed: {exc}"])

        try:
            r = await client.get(ready_url)
            r.raise_for_status()
            details.append(f"ready: {r.status_code}")
        except Exception as exc:
            return ScanResult(False, details + [f"ready failed: {exc}"])

        # 2) Metrics endpoint
        try:
            r = await client.get(metrics_url)
            r.raise_for_status()
            text = r.text or ""
            if "errandbridge_visits_total" not in text:
                return ScanResult(
                    False, details + ["metrics missing errandbridge_visits_total"]
                )
            details.append(f"metrics: {r.status_code}")
        except Exception as exc:
            return ScanResult(False, details + [f"metrics failed: {exc}"])

        # 3) Visit analytics country capture
        try:
            res1 = await client.post(
                visit_url,
                json={"page": "/stack-scan", "source": "stack-scan"},
                headers={"cloudfront-viewer-country": "NG"},
            )
            if res1.status_code != 202:
                return ScanResult(
                    False, details + [f"visit(geo header) status={res1.status_code}"]
                )

            res2 = await client.post(
                visit_url,
                json={"page": "/stack-scan", "source": "stack-scan", "country": "GB"},
            )
            if res2.status_code != 202:
                return ScanResult(
                    False,
                    details + [f"visit(payload country) status={res2.status_code}"],
                )

            details.append("analytics: posted 2 visits")
        except Exception as exc:
            return ScanResult(False, details + [f"analytics visit failed: {exc}"])

        # 4) Verify DB actually recorded those countries.
        try:
            counts = await _db_country_counts(dsn=db_dsn, since_epoch_s=since)
            details.append(f"db: {counts}")

            if counts.get("NG", 0) <= 0:
                return ScanResult(False, details + ["db missing NG visit"])
            if counts.get("GB", 0) <= 0:
                return ScanResult(False, details + ["db missing GB visit"])
        except Exception as exc:
            return ScanResult(False, details + [f"db check failed: {exc}"])

        # 5) Optional: verify admin overview aggregates country buckets.
        if admin_token:
            try:
                overview = await _fetch_json(
                    client,
                    admin_overview_url,
                )
                # If you pass a token, also pass it as default header for this request.
            except Exception:
                # retry with auth header
                try:
                    r = await client.get(
                        admin_overview_url,
                        headers={"Authorization": f"Bearer {admin_token}"},
                    )
                    r.raise_for_status()
                    overview = r.json()
                except Exception as exc:
                    return ScanResult(
                        False, details + [f"admin overview failed: {exc}"]
                    )

            by_country = overview.get("visits_by_country") or []
            details.append(f"admin overview visits_by_country: {by_country}")

    return ScanResult(True, details)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ErrandBridge stack scan")
    parser.add_argument(
        "--api-base",
        default=os.getenv("EB_API_BASE") or "http://localhost:8001",
        help="API base URL (default: http://localhost:8001)",
    )
    parser.add_argument(
        "--db-dsn",
        default=os.getenv("EB_DB_DSN") or _default_db_dsn(),
        help="Postgres DSN for asyncpg (defaults to DATABASE_URL or local compose)",
    )
    parser.add_argument(
        "--admin-token",
        default=os.getenv("EB_ADMIN_TOKEN") or None,
        help="Optional admin bearer token (enables /admin/metrics/overview checks)",
    )

    args = parser.parse_args(argv)

    result = asyncio.run(
        run_scan(
            api_base=str(args.api_base),
            db_dsn=_normalize_db_dsn(str(args.db_dsn)),
            admin_token=args.admin_token,
        )
    )

    for line in result.details:
        print(line)

    print("OK" if result.ok else "FAILED")
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
