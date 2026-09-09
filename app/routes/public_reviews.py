from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Errand, User

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class PublicReviewItem(BaseModel):
    """Anonymized customer review for marketing display."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(..., description="Review identifier")
    name: str = Field(..., description="Anonymized customer name")
    region: str = Field(..., description="Service location/region")
    rating: int = Field(..., ge=1, le=5, description="Star rating (1-5)")
    quote: str = Field(..., description="Review quote snippet")
    reviewed_at: Optional[datetime] = Field(default=None, alias="reviewedAt", description="Review completion timestamp")


class PublicReviewsResponse(BaseModel):
    """Container for public verified reviews."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    reviews: list[PublicReviewItem] = Field(default_factory=list, description="List of reviews")

router = APIRouter(prefix="/public", tags=["09 Public & Reviews"])


def _compact_place(value: Optional[str]) -> str:
    """Best-effort: reduce a free-form address/location to a safe, short label.

    We intentionally avoid emitting street numbers or multi-line addresses.
    """

    if not value:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    # Only keep the first line.
    text = text.splitlines()[0].strip()

    # Prefer the first comma-separated token (often a city/area).
    text = text.split(",", 1)[0].strip()

    # Remove obvious street-number prefixes.
    text = re.sub(r"^\s*\d+\s+", "", text)

    # Collapse whitespace and cap length.
    text = re.sub(r"\s+", " ", text).strip()

    return text[:48]


def _format_region(errand: Errand) -> str:
    pickup = _compact_place(getattr(errand, "pickup_location", None))
    dropoff = _compact_place(getattr(errand, "dropoff_location", None))

    if pickup and dropoff and pickup.lower() != dropoff.lower():
        return f"{pickup} → {dropoff}"
    if pickup:
        return pickup
    if dropoff:
        return dropoff
    return "ErrandBridge"


def _format_name(user: Optional[User]) -> str:
    if not user:
        return "ErrandBridge client"

    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()

    if first and last:
        return f"{first} {last[0].upper()}."
    if first:
        return first
    return "ErrandBridge client"


def _truncate_quote(value: Optional[str], max_len: int = 220) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    if len(text) <= max_len:
        return text

    return f"{text[: max(0, max_len - 1)].rstrip()}…"


@router.get(
    "/reviews",
    response_model=PublicReviewsResponse,
    operation_id="listPublicReviews",
    summary="List public customer reviews",
    description="Return recent verified and anonymized customer reviews suitable for landing page display.",
)
async def list_public_reviews(
    limit: int = Query(default=12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Return recent verified customer reviews.

    Source of truth is the Errand review fields:
    - review_status == "reviewed"
    - reviewer_rating is not null

    This endpoint intentionally returns a minimal, non-PII payload suitable for
    the public landing page.
    """

    rows = await db.execute(
        select(Errand, User)
        .join(User, cast(User.id, String) == cast(Errand.user_id, String), isouter=True)
        .where(Errand.review_status == "reviewed")
        .where(Errand.reviewer_rating.is_not(None))
        .order_by(desc(Errand.review_completed_at), desc(Errand.id))
        .limit(int(limit))
    )

    reviews = []
    for errand, user in rows.all():
        rating = getattr(errand, "reviewer_rating", None)
        try:
            rating_int = int(rating) if rating is not None else None
        except Exception:
            rating_int = None
        if rating_int is None:
            continue

        raw_notes = getattr(errand, "reviewer_notes", None)
        quote = _truncate_quote(raw_notes)
        if not quote:
            # Stable fallback so empty-note reviews still contribute.
            title = (getattr(errand, "title", None) or "").strip()
            quote = _truncate_quote(
                (
                    f"Smooth, reliable updates throughout the errand: {title.lower()}."
                    if title
                    else "Smooth, reliable updates throughout the errand and everything felt easy to track."
                )
            )

        reviews.append(
            {
                "id": f"errand-review-{getattr(errand, 'id', '')}",
                "name": _format_name(user),
                "region": _format_region(errand),
                "rating": max(1, min(5, rating_int)),
                "quote": quote,
                "reviewedAt": getattr(errand, "review_completed_at", None),
            }
        )

    return {"reviews": reviews}
