import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.errand import Errand
from models.user import User


async def main():
    async with AsyncSessionLocal() as session:
        print("--- USERS ---")
        users = (await session.execute(select(User))).scalars().all()
        for u in users:
            print(f"User {u.id}: email={u.email}, is_pilot={u.is_pilot}")

        print("\n--- ERRANDS ---")
        errands = (await session.execute(select(Errand))).scalars().all()
        for e in errands:
            print(
                f"Errand {e.id}: user_id={e.user_id}, pilot_id={e.pilot_id}, status={e.status}"
            )


asyncio.run(main())
