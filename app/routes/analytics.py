from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import hashlib

from database import get_db
from models import AnalyticsVisit
from metrics_admin import record_visit

router = APIRouter(prefix="/analytics", tags=["analytics"])


class VisitPayload(BaseModel):
    page: Optional[str] = None
    source: Optional[str] = None
    country: Optional[str] = None


def _hash_ip(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _first_header(headers: dict, *keys: str) -> Optional[str]:
    for key in keys:
        value = headers.get(key)
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return None


def _normalize_country(value: str | None) -> str | None:
    """Normalize country input to a stable code for aggregation.

    Expected sources:
    - CDN geo headers (CloudFront / Cloudflare)
    - Client hint (payload.country)

    We prefer ISO-3166-1 alpha-2 codes when available.
    """

    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    upper = raw.upper()
    # Cloudflare uses XX for unknown.
    if upper in {"XX", "UNKNOWN", "UNSPECIFIED", "N/A"}:
        return None

    # Common aliases (best-effort).
    alias_map = {
        "UK": "GB",
        "GBR": "GB",
        "GREAT BRITAIN": "GB",
        "UNITED KINGDOM": "GB",
        "ENGLAND": "GB",
        "SCOTLAND": "GB",
        "WALES": "GB",
        "NORTHERN IRELAND": "GB",
        "UAE": "AE",
        "UNITED ARAB EMIRATES": "AE",
        "USA": "US",
        "UNITED STATES": "US",
        "UNITED STATES OF AMERICA": "US",
        "NIGERIA": "NG",
        "CANADA": "CA",
        "AUSTRALIA": "AU",
    }
    upper = alias_map.get(upper, upper)

    # Accept only stable alpha-2 codes; anything else becomes "unknown".
    if len(upper) == 2 and upper.isalpha():
        return upper

    return None


def _normalize_location_value(value: str | None) -> str | None:
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    upper = raw.upper()
    if upper in {"XX", "UNKNOWN", "UNSPECIFIED", "N/A", "NONE", "NULL"}:
        return None

    return raw


@router.post("/visit", status_code=202)
async def track_visit(
    payload: VisitPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    headers = request.headers

    ip = _first_header(
        headers,
        "cf-connecting-ip",
        "x-forwarded-for",
        "x-real-ip",
    )
    if ip and "," in ip:
        ip = ip.split(",", 1)[0].strip()

    country_raw = _first_header(
        headers,
        "cloudfront-viewer-country",
        "cf-ipcountry",
        # Common vendor-specific geo headers (best-effort; may not be present).
        "x-vercel-ip-country",
        "fastly-client-country",
        "x-country-code",
        "x-geo-country",
    ) or payload.country
    country = _normalize_country(country_raw)
    region = _normalize_location_value(
        _first_header(
            headers,
            "cloudfront-viewer-country-region",
            "cloudfront-viewer-country-region-name",
            "cf-region",
            "cf-region-code",
            "x-vercel-ip-country-region",
            "x-vercel-ip-region",
            "fastly-region",
            "fastly-client-region",
            "x-region",
            "x-geo-region",
        )
    )
    city = _normalize_location_value(
        _first_header(
            headers,
            "cloudfront-viewer-city",
            "cf-ipcity",
            "x-vercel-ip-city",
            "fastly-city",
            "fastly-client-city",
            "x-city",
            "x-geo-city",
        )
    )
    user_agent = headers.get("user-agent")

    visit = AnalyticsVisit(
        page=(payload.page or "")[:256] or None,
        source=(payload.source or "")[:64] or None,
        country=(country or "")[:64] or None,
        region=(region or "")[:128] or None,
        city=(city or "")[:128] or None,
        ip_hash=_hash_ip(ip),
        user_agent=(user_agent or "")[:256] or None,
    )

    try:
        db.add(visit)
        await db.commit()
    except Exception:
        await db.rollback()
    finally:
        record_visit(payload.page, payload.source, country)

    return {"ok": True}
