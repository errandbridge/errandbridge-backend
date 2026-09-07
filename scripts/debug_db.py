import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.errand import Errand
from models.errand_attachment import ErrandAttachment
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

        print("\n--- ATTACHMENTS ---")
        atts = (await session.execute(select(ErrandAttachment))).scalars().all()
        for a in atts:
            print(
                f"Attachment {a.id}: errand_id={a.errand_id}, stored={a.stored_filename}"
            )


asyncio.run(main())
