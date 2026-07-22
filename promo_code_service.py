from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import PromoCode


_ALPHABET = string.ascii_uppercase + string.digits


def normalize_promo_code(value: str | None) -> str:
    """Normalize a user-entered promo code.

    - Uppercase
    - Strip whitespace
    - Remove common separators (spaces, hyphens)
    """
    if not value:
        return ""
    raw = str(value).strip().upper()
    for ch in (" ", "-", "_"):
        raw = raw.replace(ch, "")
    return raw


def format_display_code(code: str) -> str:
    """Format a stored canonical code for display."""
    c = normalize_promo_code(code)
    if len(c) <= 4:
        return c
    return f"{c[:4]}-{c[4:]}"


def _generate_code(*, prefix: str = "EB10", random_len: int = 8) -> str:
    prefix_norm = normalize_promo_code(prefix)
    rand = "".join(secrets.choice(_ALPHABET) for _ in range(max(4, int(random_len))))
    return f"{prefix_norm}{rand}"


async def issue_promo_code(
    db: AsyncSession,
    *,
    user_id: Optional[int] = None,
    percent_off: int = 10,
    max_redemptions: int = 1,
    created_by_admin_id: Optional[int] = None,
    source: Optional[str] = None,
    fixed_code: Optional[str] = None,
    prefix: str = "EB10",
) -> PromoCode:
    """Create a promo code row with best-effort uniqueness.

    Retries on unique-code collision.
    """

    percent = int(percent_off)
    if percent <= 0 or percent > 100:
        raise ValueError("percent_off must be between 1 and 100")

    max_red = int(max_redemptions)
    if max_red <= 0:
        raise ValueError("max_redemptions must be >= 1")

    attempts = 0
    last_exc: Exception | None = None

    while attempts < 6:
        attempts += 1
        candidate = normalize_promo_code(fixed_code) if fixed_code else _generate_code(prefix=prefix)

        promo = PromoCode(
            code=candidate,
            percent_off=percent,
            user_id=int(user_id) if user_id is not None else None,
            created_by_admin_id=int(created_by_admin_id) if created_by_admin_id is not None else None,
            source=(str(source).strip() if source else None),
            max_redemptions=max_red,
            redeemed_count=0,
        )
        db.add(promo)
        try:
            await db.commit()
            await db.refresh(promo)
            return promo
        except IntegrityError as exc:
            await db.rollback()
            last_exc = exc
            # Retry only when we are not using a fixed code.
            if fixed_code:
                break
            continue

    raise ValueError("Unable to generate a unique promo code") from last_exc


async def find_promo_code(db: AsyncSession, *, code: str) -> Optional[PromoCode]:
    canonical = normalize_promo_code(code)
    if not canonical:
        return None
    res = await db.execute(select(PromoCode).where(PromoCode.code == canonical))
    return res.scalars().first()


def promo_is_redeemable(promo: PromoCode) -> bool:
    try:
        return int(promo.redeemed_count or 0) < int(promo.max_redemptions or 1)
    except Exception:
        return False


async def validate_promo_code_for_user(
    db: AsyncSession,
    *,
    code: str,
    user_id: Optional[int],
) -> PromoCode:
    promo = await find_promo_code(db, code=code)
    if not promo:
        raise ValueError("Promo code not found")

    if not promo_is_redeemable(promo):
        raise ValueError("Promo code already redeemed")

    # If promo is tied to a user, require matching auth user.
    if promo.user_id is not None:
        if user_id is None:
            raise ValueError("Login required for this promo code")
        if int(promo.user_id) != int(user_id):
            raise ValueError("Promo code is not valid for this account")

    return promo


async def redeem_promo_code(
    db: AsyncSession,
    *,
    promo: PromoCode,
    errand_id: Optional[int] = None,
) -> PromoCode:
    """Mark a promo code as redeemed once, idempotently."""
    if promo.redeemed_at:
        return promo

    promo.redeemed_count = int(promo.redeemed_count or 0) + 1
    promo.redeemed_at = datetime.now(timezone.utc)
    if errand_id is not None:
        promo.redeemed_errand_id = int(errand_id)

    db.add(promo)
    await db.commit()
    await db.refresh(promo)
    return promo
