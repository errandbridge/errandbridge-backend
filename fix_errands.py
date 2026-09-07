import asyncio
from sqlalchemy import update
from database import AsyncSessionLocal
from models.errand import Errand

async def main():
    async with AsyncSessionLocal() as session:
        # Set all unassigned errands to pilot_id 1 just to fix the state mismatch
        await session.execute(update(Errand).values(pilot_id=1, status='accepted'))
        await session.commit()
        print("Updated errands to pilot_id 1")

asyncio.run(main())
