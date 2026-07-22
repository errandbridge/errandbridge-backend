"""Set a user's password in the local database.

This is a *development/admin* helper intended for local Docker Compose usage.

Examples (run inside the api container):
  python scripts/set_user_password.py --email admin@errandbridge.com --password 'London25'

Notes:
- Password is hashed using the project's configured password context.
- This script does not send email/OTP.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from auth import hash_password
from database import AsyncSessionLocal
from models import User


async def _set_password(email: str, password: str) -> int:
    email_norm = (email or "").strip().lower()
    if not email_norm:
        raise SystemExit("Missing --email")
    if password is None or len(password) < 1:
        raise SystemExit("Missing --password")

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email_norm))
        user = result.scalars().first()
        if not user:
            raise SystemExit(f"User not found: {email_norm}")

        user.password_hash = hash_password(password)
        await session.commit()
        return int(user.id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Set a user's password (dev helper).")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--password", required=True, help="New password (plain text)")
    args = parser.parse_args()

    user_id = asyncio.run(_set_password(args.email, args.password))
    print(f"OK: updated password for user_id={user_id} email={args.email}")


if __name__ == "__main__":
    main()
