import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.errand import Errand


async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Errand).order_by(Errand.id.desc()).limit(5)
        )
        errands = result.scalars().all()
        for errand in errands:
            print(
                f"Errand ID: {errand.id} | Status: {errand.status} | User: {errand.user_id} | Pilot: {errand.pilot_id}"
            )


asyncio.run(main())
