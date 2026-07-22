#!/usr/bin/env python3

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass

from sqlalchemy import func, select

from auth import hash_password
from database import AsyncSessionLocal
from models import User


DEFAULT_PASSWORD = "Password123!"
DEFAULT_CUSTOMER_EMAIL = "customer_test_001@example.com"
DEFAULT_PILOT_EMAIL = "pilot_test_001@example.com"


@dataclass
class TesterSpec:
    email: str
    first_name: str
    last_name: str
    is_pilot: bool
    city: str = "Lagos"
    state: str = "Lagos"
    country: str = "Nigeria"


TESTER_SPECS = [
    TesterSpec(
        email=DEFAULT_CUSTOMER_EMAIL,
        first_name="Android",
        last_name="Customer Tester",
        is_pilot=False,
    ),
    TesterSpec(
        email=DEFAULT_PILOT_EMAIL,
        first_name="Android",
        last_name="Pilot Tester",
        is_pilot=True,
    ),
]


async def _find_user_by_email(session, email: str) -> User | None:
    normalized_email = (email or "").strip().lower()
    result = await session.execute(
        select(User).where(func.lower(User.email) == normalized_email)
    )
    return result.scalars().first()


async def ensure_tester_users(*, password: str, reset_existing: bool) -> list[dict]:
    if not (password or "").strip():
        raise SystemExit("Password is required")

    summary: list[dict] = []

    async with AsyncSessionLocal() as session:
        for spec in TESTER_SPECS:
            normalized_email = spec.email.strip().lower()
            existing_user = await _find_user_by_email(session, normalized_email)

            if existing_user:
                changed = False
                existing_user.email = normalized_email

                if reset_existing:
                    existing_user.password_hash = hash_password(password)
                    changed = True

                if existing_user.is_pilot != spec.is_pilot:
                    existing_user.is_pilot = spec.is_pilot
                    changed = True

                if not existing_user.is_email_verified:
                    existing_user.is_email_verified = True
                    changed = True

                if existing_user.first_name != spec.first_name:
                    existing_user.first_name = spec.first_name
                    changed = True
                if existing_user.last_name != spec.last_name:
                    existing_user.last_name = spec.last_name
                    changed = True
                if getattr(existing_user, "city", None) != spec.city:
                    existing_user.city = spec.city
                    changed = True
                if getattr(existing_user, "state", None) != spec.state:
                    existing_user.state = spec.state
                    changed = True
                if getattr(existing_user, "country", None) != spec.country:
                    existing_user.country = spec.country
                    changed = True

                existing_user.email_otp_hash = None
                existing_user.email_otp_expires_at = None
                existing_user.email_otp_last_sent_at = None
                existing_user.email_otp_attempts = 0

                if changed or reset_existing:
                    await session.flush()
                    summary.append(
                        {
                            "email": normalized_email,
                            "role": "pilot" if spec.is_pilot else "client",
                            "action": "updated",
                            "user_id": existing_user.id,
                        }
                    )
                else:
                    summary.append(
                        {
                            "email": normalized_email,
                            "role": "pilot" if spec.is_pilot else "client",
                            "action": "unchanged",
                            "user_id": existing_user.id,
                        }
                    )
                continue

            user = User(
                email=normalized_email,
                password_hash=hash_password(password),
                first_name=spec.first_name,
                last_name=spec.last_name,
                city=spec.city,
                state=spec.state,
                country=spec.country,
                is_pilot=spec.is_pilot,
                is_email_verified=True,
                id_verification_status="pending",
                address_verification_status="pending",
                email_otp_attempts=0,
            )
            session.add(user)
            await session.flush()
            summary.append(
                {
                    "email": normalized_email,
                    "role": "pilot" if spec.is_pilot else "client",
                    "action": "created",
                    "user_id": user.id,
                }
            )

        await session.commit()

    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ensure the standard Android internal-testing users exist and are verified."
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Password to set for both tester users (default: Password123!).",
    )
    parser.add_argument(
        "--reset-existing",
        action="store_true",
        help="Reset the password and role fields for existing tester users.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the result summary as JSON.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = asyncio.run(
        ensure_tester_users(
            password=args.password,
            reset_existing=bool(args.reset_existing),
        )
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("✅ Android tester users ensured")
        for row in result:
            print(
                f"   - {row['email']} ({row['role']}) -> {row['action']}"
            )
        print(f"   - Password: {args.password}")
