import argparse
import asyncio
from datetime import datetime, timedelta, timezone

# Allow running this script from any working directory.
# When executed as "python scripts/delete_unverified_users.py", Python sets sys.path[0]
# to the scripts/ directory, so project-root imports (e.g., `import database`) fail.
import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sqlalchemy import delete, select

from database import AsyncSessionLocal
from models import User


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete unverified users.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Comma-separated list of user IDs to delete.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for how many users to delete.",
    )
    parser.add_argument(
        "--before-days",
        type=int,
        default=None,
        help="Only delete users created more than N days ago.",
    )
    parser.add_argument(
        "--email-contains",
        type=str,
        default=None,
        help="Only delete users whose email contains the given text.",
    )
    parser.add_argument(
        "--email-domain",
        type=str,
        default=None,
        help="Only delete users with a specific email domain (e.g., example.com).",
    )
    return parser.parse_args()


async def _collect_unverified_users(session, before_days: int | None, limit: int | None):
    query = select(User).where(User.is_email_verified.is_(False))
    if before_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=before_days)
        query = query.where(User.created_at < cutoff)
    query = query.order_by(User.created_at.asc())
    if limit is not None:
        query = query.limit(limit)
    result = await session.execute(query)
    return result.scalars().all()


def _parse_ids(raw_ids: str | None) -> list[int]:
    if not raw_ids:
        return []
    ids = []
    for raw in raw_ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ids.append(int(raw))
        except ValueError as exc:
            raise ValueError(f"Invalid ID value: {raw}") from exc
    return ids


async def main() -> None:
    args = _parse_args()
    async with AsyncSessionLocal() as session:
        ids = _parse_ids(args.ids)
        if ids:
            query = select(User).where(User.id.in_(ids))
            result = await session.execute(query)
            users = result.scalars().all()
        else:
            users = await _collect_unverified_users(session, args.before_days, args.limit)

        if args.email_contains:
            token = args.email_contains.lower()
            users = [user for user in users if token in (user.email or "").lower()]

        if args.email_domain:
            domain = args.email_domain.lower().lstrip("@").strip()
            users = [
                user
                for user in users
                if (user.email or "").lower().endswith(f"@{domain}")
            ]
        if not users:
            print("No unverified users found for cleanup.")
            return

        print(f"Found {len(users)} unverified user(s).")
        for user in users:
            created_at = user.created_at.isoformat() if user.created_at else "unknown"
            print(f"- id={user.id} email={user.email} created_at={created_at}")

        if not args.apply:
            print("Dry run only. Re-run with --apply to delete these users.")
            return

        ids = [u.id for u in users]
        delete_query = delete(User).where(User.id.in_(ids))
        result = await session.execute(delete_query)
        await session.commit()
        print(f"Deleted {result.rowcount or 0} unverified user(s).")


if __name__ == "__main__":
    asyncio.run(main())
