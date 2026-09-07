"""Dev-only DB fixups.

This script is intentionally idempotent and can be run multiple times.
It ensures the database schema matches current models for local/dev.

Usage (inside repo):
  python3 scripts/dev_db_fixup.py

Or in docker:
  docker compose exec api python scripts/dev_db_fixup.py
"""

import asyncio
import os
import sys

from sqlalchemy import text

# Ensure imports work when running as `python scripts/...`.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import engine
from models import Base


async def main() -> None:
    async with engine.begin() as conn:
        # Create tables if missing
        await conn.run_sync(Base.metadata.create_all)

        # Add new columns if the table already existed
        await conn.execute(
            text("ALTER TABLE errands ADD COLUMN IF NOT EXISTS pickup_location VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE errands ADD COLUMN IF NOT EXISTS dropoff_location VARCHAR"
            )
        )

        # Ensure the users table exists even if create_all didn't run for some reason.
        # (CREATE TABLE IF NOT EXISTS is supported by Postgres.)
        await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR NOT NULL UNIQUE,
                    password_hash VARCHAR NOT NULL,
                    first_name VARCHAR,
                    last_name VARCHAR,
                    phone VARCHAR,
                    is_email_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    email_otp_hash VARCHAR,
                    email_otp_expires_at BIGINT,
                    email_otp_last_sent_at BIGINT,
                    email_otp_attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """))

        # Add new columns if the users table already existed
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_email_verified BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )

        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_otp_hash VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_otp_expires_at BIGINT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_otp_last_sent_at BIGINT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_otp_attempts INTEGER NOT NULL DEFAULT 0"
            )
        )

        # Helpful indexes (create_all should do this, but keep it idempotent).
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)")
        )


if __name__ == "__main__":
    asyncio.run(main())
