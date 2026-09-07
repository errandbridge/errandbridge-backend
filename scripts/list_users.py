import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User


async def main():
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User))
        users = res.scalars().all()
        for u in users:
            print(u.id, u.email, getattr(u, "user_uuid", None))


asyncio.run(main())
