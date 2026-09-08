from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import decode_access_token
from database import get_db
from models import PromoCode
from app.services.promo_code_service import (
    format_display_code,
    normalize_promo_code,
    validate_promo_code_for_user,
)

router = APIRouter(prefix="/promo-codes", tags=["promo-codes"])


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def _current_user_id_from_request(
    request: Request, authorization: Optional[str]
) -> int:
    header = (
        authorization
        or request.headers.get("authorization")
        or request.headers.get("Authorization")
    )
    token = _extract_bearer(header)
    user_id = decode_access_token(token) if token else None
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return int(user_id)


class PromoCodeOut(BaseModel):
    id: str
    code: str
    display_code: str
    percent_off: int
    source: Optional[str] = None
    max_redemptions: int
    redeemed_count: int
    redeemed_at: Optional[datetime] = None
    redeemed_errand_id: Optional[int] = None
    created_at: Optional[datetime] = None


class ValidatePromoIn(BaseModel):
    code: str


class ValidatePromoOut(BaseModel):
    ok: bool
    code: Optional[str] = None
    display_code: Optional[str] = None
    percent_off: Optional[int] = None
    message: Optional[str] = None


@router.get("/me", response_model=list[PromoCodeOut])
async def list_my_promo_codes(
    request: Request,
    source: Optional[str] = None,
    include_redeemed: bool = False,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _current_user_id_from_request(request, authorization)

    q = select(PromoCode).where(PromoCode.user_id == user_id)
    if source:
        q = q.where(PromoCode.source == source)
    if not include_redeemed:
        q = q.where(PromoCode.redeemed_count < PromoCode.max_redemptions)

    q = q.order_by(PromoCode.id.desc()).limit(50)
    res = await db.execute(q)
    promos = res.scalars().all()

    return [
        PromoCodeOut(
            id=p.id,
            code=p.code,
            display_code=format_display_code(p.code),
            percent_off=int(p.percent_off or 0),
            source=p.source,
            max_redemptions=int(p.max_redemptions or 1),
            redeemed_count=int(p.redeemed_count or 0),
            redeemed_at=p.redeemed_at,
            redeemed_errand_id=p.redeemed_errand_id,
            created_at=p.created_at,
        )
        for p in promos
    ]


@router.post("/validate", response_model=ValidatePromoOut)
async def validate_promo_code(
    payload: ValidatePromoIn,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    raw = payload.code or ""
    code = normalize_promo_code(raw)
    if not code:
        raise HTTPException(status_code=400, detail="Promo code is required")

    # Determine caller identity if present.
    header = (
        authorization
        or request.headers.get("authorization")
        or request.headers.get("Authorization")
    )
    token = _extract_bearer(header)
    user_id = decode_access_token(token) if token else None

    try:
        promo = await validate_promo_code_for_user(
            db, code=code, user_id=(int(user_id) if user_id else None)
        )
    except ValueError as e:
        return ValidatePromoOut(ok=False, message=str(e))

    return ValidatePromoOut(
        ok=True,
        code=promo.code,
        display_code=format_display_code(promo.code),
        percent_off=int(promo.percent_off or 0),
        message="Promo code applied",
    )
