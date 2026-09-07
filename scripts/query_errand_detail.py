import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/errandbridge"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id, title, pickup_location, dropoff_location, distance_km FROM errands WHERE id = 4"
            )
        )
        for row in result:
            print(row)
    await engine.dispose()


asyncio.run(main())
