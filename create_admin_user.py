#!/usr/bin/env python3

import argparse
import asyncio

from sqlalchemy import func, select

from auth import hash_password
from database import AsyncSessionLocal
from models import User


async def create_or_reset_admin_user(email: str, password: str, *, reset: bool) -> None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        raise SystemExit("Invalid email")
    if not (password or "").strip():
        raise SystemExit("Invalid password")

    async with AsyncSessionLocal() as session:
        # Case-insensitive lookup to tolerate legacy mixed-case stored emails.
        result = await session.execute(select(User).where(func.lower(User.email) == normalized_email))
        existing_user = result.scalars().first()

        if existing_user:
            if reset:
                existing_user.email = normalized_email
                existing_user.password_hash = hash_password(password)
                existing_user.is_email_verified = True
                await session.commit()
                print(f"✅ Admin user password reset: {normalized_email}")
                return

            print(f"✅ Admin user already exists: {existing_user.email}")
            return

        admin_user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            is_email_verified=True,
            first_name="Admin",
            last_name="User",
        )
        session.add(admin_user)
        await session.commit()
        print(f"✅ Admin user created: {normalized_email}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or reset a local admin user.")
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="If the user already exists, reset their password and mark email as verified.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(create_or_reset_admin_user(args.email, args.password, reset=bool(args.reset)))
